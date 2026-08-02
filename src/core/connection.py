import asyncio
import logging
import platform
import random
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from bleak import BleakClient, BleakScanner, BleakError
try:
    from bleak_retry_connector import establish_connection, BleakClientWithServiceCache
except ImportError:
    pass

from src.utils.error_manager import error_manager
from src.utils.error_types import ErrorCategory
from src.utils.qt_async_executor import create_task

from .types import (
    ConnectionState,
    BleDeviceInfo,
    DiscoveredDevice,
    CONNECT_TIMEOUT,
    FIND_DEVICE_TIMEOUT,
    MAX_RECONNECT_ATTEMPTS,
    BASE_RECONNECT_DELAY,
    MAX_RECONNECT_DELAY,
    _CONNECTION_SEMAPHORE,
    _HAS_BLEAK,
    _HAS_RETRY,
    _HAS_WINRT,
)

logger = logging.getLogger(__name__)

__all__ = ["ConnectionWatchdog", "BleConnection"]

class ConnectionWatchdog:
    """Detecte les connexions zombies via inactivite des notifications.

    Si aucune notification n'est recue pendant `timeout` secondes,
    la connexion est consideree comme morte et le disconnect est force.
    Source: bleak-retry-connector #228, best practices 2026.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        on_timeout: Optional[Callable[["BleConnection"], None]] = None,
    ) -> None:
        """Initialise le watchdog.
        
        Args:
            timeout: Secondes d'inactivité avant timeout
            on_timeout: Callback appelé lors du timeout
        """
        self.timeout = timeout
        self._on_timeout = on_timeout
        self._last_activity: float = 0.0
        self._task: Optional[asyncio.Task] = None
        self._active = False
        self._connection: Optional["BleConnection"] = None

    def start(self, connection: "BleConnection") -> None:
        """Demarre le watchdog pour une connexion.
        
        Args:
            connection: La connexion à surveiller
        """
        self._connection = connection
        self._active = True
        self._last_activity = time.time()
        try:
            self._task = create_task(self._monitor())
        except RuntimeError as e:
            logger.debug(f"Impossible de demarrer le watchdog: {e}")

    def stop(self) -> None:
        """Arrete le watchdog."""
        self._active = False
        self._connection = None
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None

    def notify_activity(self) -> None:
        """Appeler quand une notification est recue."""
        self._last_activity = time.time()

    async def _monitor(self) -> None:
        """Boucle de surveillance en arriere-plan."""
        try:
            while self._active and self._connection:
                await asyncio.sleep(5.0)
                if not self._active:
                    return
                elapsed = time.time() - self._last_activity
                if elapsed > self.timeout:
                    if self._on_timeout and self._connection:
                        self._on_timeout(self._connection)
                    self._active = False
                    return
        except asyncio.CancelledError:
            pass


class BleConnection:
    """Machine d'etats pour une connexion BLE individuelle.

    Chaque peripherique BLE suit un cycle de vie formel avec gestion
    d'erreur, reconnexion automatique et nettoyage WinRT.
    """

    _NOTIFICATION_COOLDOWN = 0.050
    _RSSI_HISTORY_SIZE = 10

    def __init__(
        self,
        address: str,
        name: str,
        device_info: BleDeviceInfo,
        disconnected_cb: Optional[Callable[["BleConnection"], None]] = None,
    ) -> None:
        """Initialise la connexion.
        
        Args:
            address: Adresse MAC ou UUID
            name: Nom de l'appareil
            device_info: Objet DeviceInfo
            disconnected_cb: Callback de déconnexion
        """
        self.address = address
        self.name = name
        self.device_info = device_info
        self.state = ConnectionState.IDLE
        self.client: Optional[Any] = None
        self._bledevice: Optional[Any] = None
        self._disconnected_cb = disconnected_cb
        self._lock = asyncio.Lock()
        self._reconnect_task: Optional[asyncio.Task] = None
        self._disconnect_event = asyncio.Event()
        self._notification_tasks: List[asyncio.Task] = []
        self.last_error: Optional[str] = None
        self.connected_at: Optional[datetime] = None
        self.disconnected_at: Optional[datetime] = None
        self.reconnect_count = 0
        self._last_notification_times: Dict[str, float] = {}
        self._rssi_history: List[Tuple[float, int]] = []
        self._watchdog: Optional[ConnectionWatchdog] = None
        self._notification_timeout: float = 30.0
        self._discovered_char_uuid: Optional[str] = None
        # Références fortes des tâches de fond — évite le garbage-collect
        # des tâches asyncio avant leur fin (docs Python : asyncio.create_task).
        self._background_tasks: set = set()

    @property
    def is_connected(self) -> bool:
        """Vérifie si la connexion est active."""
        if self.client is not None:
            try:
                return bool(self.client.is_connected)
            except Exception:
                return False
        return False

    def update_rssi(self, rssi: int) -> None:
        """Enregistre une valeur RSSI dans l'historique."""
        self._rssi_history.append((time.time(), rssi))
        if len(self._rssi_history) > self._RSSI_HISTORY_SIZE:
            self._rssi_history = self._rssi_history[-self._RSSI_HISTORY_SIZE:]

    def get_signal_quality(self) -> str:
        """Retourne la qualite du signal basee sur les dernieres valeurs RSSI.

        Returns:
            "Excellent", "Bon", "Faible", "Critique" ou "Inconnu"
        """
        if not self._rssi_history:
            return "Inconnu"
        avg_rssi = sum(r for _, r in self._rssi_history) / len(self._rssi_history)
        if avg_rssi >= -50:
            return "Excellent"
        elif avg_rssi >= -65:
            return "Bon"
        elif avg_rssi >= -80:
            return "Faible"
        return "Critique"

    @property
    def average_rssi(self) -> Optional[int]:
        """RSSI moyen des dernieres valeurs."""
        if not self._rssi_history:
            return None
        return int(sum(r for _, r in self._rssi_history) / len(self._rssi_history))

    def _is_duplicate_notification(self, characteristic_uuid: str) -> bool:
        """Verifie si une notification est un doublon."""
        now = time.time()
        last = self._last_notification_times.get(characteristic_uuid, 0.0)
        if (now - last) < self._NOTIFICATION_COOLDOWN:
            return True
        self._last_notification_times[characteristic_uuid] = now
        return False

    def setup_watchdog(self, timeout: float = 30.0) -> None:
        """Configure et demarre le watchdog de connexion."""
        self._notification_timeout = timeout
        self._watchdog = ConnectionWatchdog(
            timeout=timeout,
            on_timeout=self._on_watchdog_timeout,
        )
        self._watchdog.start(self)

    def stop_watchdog(self) -> None:
        """Arrete le watchdog."""
        if self._watchdog:
            self._watchdog.stop()
            self._watchdog = None

    def _on_watchdog_timeout(self, conn: "BleConnection") -> None:
        """Callback watchdog: connexion zombie detectee."""
        error_manager.warning(
            category=ErrorCategory.BLUETOOTH,
            error_type="zombie_connection",
            message=f"Connexion zombie detectee pour {self.name or self.address} "
                    f"(>{self._notification_timeout}s sans donnees). "
                    f"Reconnexion...",
        )
        try:
            task = create_task(conn.disconnect(force=True))
            # Référence forte : empêche le garbage-collect avant exécution
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        except RuntimeError:
            pass

    async def connect(
        self,
        bledevice: Any,
        timeout: float = CONNECT_TIMEOUT,
    ) -> bool:
        """Connecte le peripherique BLE avec retry et service caching."""
        async with self._lock:
            if self.state == ConnectionState.CONNECTED:
                return True

            self.state = ConnectionState.CONNECTING
            self._bledevice = bledevice
            self.last_error = None

        try:
            async with _CONNECTION_SEMAPHORE:
                if _HAS_RETRY:
                    self.client = await establish_connection(
                        BleakClientWithServiceCache,
                        bledevice,
                        self.name or self.address,
                        max_attempts=3,
                        timeout=timeout,
                        disconnected_callback=self._on_disconnected,
                    )
                    if platform.system() != "Windows" and hasattr(self.client, 'pair'):
                        try:
                            await asyncio.wait_for(self.client.pair(), timeout=15.0)
                            self.device_info.is_paired = True
                        except Exception:
                            self.device_info.is_paired = False
                else:
                    self.client = BleakClient(
                        bledevice,
                        timeout=timeout,
                        disconnected_callback=self._on_disconnected,
                    )
                    await self.client.connect()
                    if platform.system() != "Windows" and hasattr(self.client, 'pair'):
                        try:
                            await asyncio.wait_for(self.client.pair(), timeout=15.0)
                            self.device_info.is_paired = True
                        except Exception:
                            self.device_info.is_paired = False

            async with self._lock:
                if self.client and self.is_connected:
                    if not await self.validate_gatt_services():
                        self.state = ConnectionState.ERROR
                        self.last_error = "Phantom connection: services GATT vides"
                        try:
                            await self.client.disconnect()
                        except BleakError:
                            pass
                        self.client = None
                        return False

                    self.state = ConnectionState.CONNECTED
                    self.connected_at = datetime.now()
                    self.reconnect_count = 0
                    self.device_info.connection_state = ConnectionState.CONNECTED
                    self.device_info.is_paired = self.client.is_paired if hasattr(
                        self.client, "is_paired"
                    ) else False

                    self.setup_watchdog(timeout=self._notification_timeout)
                    return True
                else:
                    self.state = ConnectionState.ERROR
                    self.last_error = "Echec connexion: client non connecte"
                    return False

        except BleakError as exc:
            async with self._lock:
                self.state = ConnectionState.ERROR
                self.last_error = str(exc)
            error_manager.error(
                category=ErrorCategory.BLUETOOTH,
                error_type="connection_failed",
                message=f"Impossible de se connecter a "
                        f"l'appareil {self.name or self.address}. "
                        f"Verifiez qu'il est allume.",
            )
            return False
        except asyncio.TimeoutError as exc:
            async with self._lock:
                self.state = ConnectionState.ERROR
                self.last_error = "Timeout de connexion"
            error_manager.error(
                category=ErrorCategory.BLUETOOTH,
                error_type="connection_failed",
                message=f"Timeout en se connectant a {self.name or self.address}.",
            )
            return False

    async def disconnect(self, force: bool = False) -> bool:
        """Deconnecte proprement avec nettoyage WinRT."""
        async with self._lock:
            if self.state in (
                ConnectionState.DISCONNECTED,
                ConnectionState.IDLE,
            ):
                return True
            self.state = ConnectionState.DISCONNECTING

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None

        self.stop_watchdog()

        for task in self._notification_tasks:
            if not task.done():
                task.cancel()
        self._notification_tasks.clear()

        try:
            if self.client is not None:
                await self.client.disconnect()
                if force and _HAS_BLEAK:
                    await self._force_winrt_disconnect()
        except BleakError as exc:
            self.last_error = f"Erreur deconnexion: {exc}"

        async with self._lock:
            self.state = ConnectionState.DISCONNECTED
            self.disconnected_at = datetime.now()
            self.device_info.connection_state = ConnectionState.DISCONNECTED
            self.client = None
            self._bledevice = None
        return True

    async def validate_gatt_services(self) -> bool:
        """Verifie que les services GATT sont disponibles apres connexion."""
        if self.client is None or not self.is_connected:
            return False
        try:
            services = self.client.services
            if services is None or len(services) == 0:
                return False
            for service in services:
                if len(list(service.characteristics)) > 0:
                    return True
            return False
        except BleakError:
            return False

    async def discover_notify_characteristic(
        self,
        preferred_uuids: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Decouvre automatiquement une caracteristique avec notify/indicate."""
        if self.client is None or not self.is_connected:
            return None
        try:
            services = self.client.services
            if not services:
                return None

            candidates: List[str] = []

            for service in services:
                for char in service.characteristics:
                    props = char.properties
                    if "notify" in props or "indicate" in props:
                        char_str = str(char.uuid)
                        candidates.append(char_str)

            if not candidates:
                return None

            if preferred_uuids:
                for pref in preferred_uuids:
                    pref_lower = pref.lower()
                    for c in candidates:
                        if pref_lower in c.lower():
                            self._discovered_char_uuid = c
                            return c

            self._discovered_char_uuid = candidates[0]
            return candidates[0]

        except BleakError:
            return None

    async def _force_winrt_disconnect(self) -> None:
        """Force la fermeture de la session WinRT sous Windows."""
        if platform.system() != "Windows" or not _HAS_BLEAK:
            return
        if not _HAS_WINRT:
            return
        try:
            from bleak.backends.winrt.util import uninitialize_sta
            uninitialize_sta()
        except ImportError:
            pass

    def _on_disconnected(self, client: Any) -> None:
        """Callback deconnexion inattendue — declenche reconnexion."""
        self.client = None
        if self.state == ConnectionState.DISCONNECTING:
            return
        self.state = ConnectionState.DISCONNECTED
        if self.device_info:
            self.device_info.connection_state = ConnectionState.DISCONNECTED
        self.disconnected_at = datetime.now()

        if self._disconnected_cb:
            try:
                self._disconnected_cb(self)
            except Exception as e:
                logger.error(f"Error in disconnected callback: {e}")

        try:
            if self._reconnect_task and not self._reconnect_task.done():
                self._reconnect_task.cancel()
            self._reconnect_task = create_task(self._reconnect_with_backoff())
        except RuntimeError:
            pass

    async def _reconnect_with_backoff(self) -> None:
        """Reconnexion avec backoff exponentiel + jitter."""
        try:
            for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
                if self.state == ConnectionState.DISCONNECTING:
                    return

                delay = min(
                    BASE_RECONNECT_DELAY * (2 ** (attempt - 1)),
                    MAX_RECONNECT_DELAY,
                )
                jitter = random.uniform(0.8, 1.2)
                await asyncio.sleep(delay * jitter)

                async with self._lock:
                    self.state = ConnectionState.RECONNECTING
                    self.reconnect_count += 1

                try:
                    if _HAS_BLEAK:
                        device = await BleakScanner.find_device_by_address(
                            self.address,
                            timeout=FIND_DEVICE_TIMEOUT,
                            scanning_mode="active",  # SCAN_RSP pour détection fiable
                        )
                        if device:
                            success = await self.connect(device, timeout=CONNECT_TIMEOUT)
                            if success:
                                return
                except BleakError:
                    continue

            async with self._lock:
                self.state = ConnectionState.ERROR
                self.last_error = f"Reconnexion abandonnée apres {MAX_RECONNECT_ATTEMPTS} tentatives"
                self.device_info.connection_state = ConnectionState.ERROR
        except asyncio.CancelledError:
            pass

    async def read_characteristic(
        self, char_uuid: str, use_cached: bool = True
    ) -> Optional[bytes]:
        """Lit une caractéristique GATT."""
        if self.client is None or not self.is_connected:
            self.last_error = "Non connecte"
            return None
        try:
            return await self.client.read_gatt_char(char_uuid, use_cached=use_cached)
        except BleakError as exc:
            self.last_error = f"Erreur lecture {char_uuid}: {exc}"
            try:
                from src.utils.sound_manager import SoundManager
                SoundManager.instance().play_error_async()
            except ImportError:
                pass
            return None

    async def start_notify(
        self, char_uuid: str, callback: Callable[[int, bytes], None]
    ) -> bool:
        """Active les notifications sur une caractéristique."""
        if self.client is None or not self.is_connected:
            self.last_error = "Non connecte"
            return False
        try:
            await self.client.start_notify(char_uuid, callback)
            return True
        except BleakError as exc:
            self.last_error = f"Erreur start_notify {char_uuid}: {exc}"
            try:
                from src.utils.sound_manager import SoundManager
                SoundManager.instance().play_error_async()
            except ImportError:
                pass
            return False

    async def stop_notify(self, char_uuid: str) -> bool:
        """Desactive les notifications."""
        if self.client is None:
            return True
        try:
            await self.client.stop_notify(char_uuid)
            return True
        except BleakError:
            return False
