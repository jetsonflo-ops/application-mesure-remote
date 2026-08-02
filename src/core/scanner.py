import asyncio
import logging
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

from bleak import BleakScanner, BleakError

from src.utils.error_manager import error_manager
from src.utils.error_types import ErrorCategory

from .types import (
    BleDeviceInfo,
    ConnectionState,
    DiscoveredDevice,
    MAX_SCANNED_DEVICES,
    SCAN_TIMEOUT,
    _HAS_BLEAK,
    DeviceType,
)
from .device_cache import DeviceCache
from .profiler import DeviceProfiler
from .name_resolver import resolve_name

logger = logging.getLogger(__name__)

__all__ = ["BleScanner"]

class BleScanner:
    """Gestionnaire de scan et de decouverte BLE.

    Encapsule la logique de scan continu et manuel, et maintient 
    le cache des appareils scannes recemment.
    """

    def __init__(
        self, 
        device_cache: DeviceCache, 
        scan_callback: Optional[Callable[[DiscoveredDevice], None]] = None
    ) -> None:
        """Initialise le scanner.
        
        Args:
            device_cache: Instance du cache pour stocker les infos
            scan_callback: Fonction de callback appelée lors d'une découverte
        """
        self.device_cache = device_cache
        self._scan_callback = scan_callback
        self._continuous_scanner: Optional[Any] = None
        self._scanned_devices: OrderedDict = OrderedDict()
        self._running = False
        self._use_mock = not _HAS_BLEAK
        self._scan_lock = asyncio.Lock()

    @property
    def scanned_devices(self) -> Dict[str, Any]:
        """Retourne une copie des references BLEDevice scannées recemment."""
        return dict(self._scanned_devices)

    async def start_continuous(self) -> None:
        """Demarre le scan continu pour alimenter le cache."""
        if self._running:
            return

        if self._use_mock:
            logger.info("BLE core: bleak indisponible, utilisation du mock.")
            self._running = True
            return

        self._running = True

        try:
            self._continuous_scanner = BleakScanner(
                detection_callback=self._on_advertisement,
                scanning_mode="active",  # Déclenche la SCAN_REQ → SCAN_RSP
                # (la scan response contient souvent le nom local — doc bleak)
            )
            await self._continuous_scanner.start()
        except BleakError as exc:
            logger.warning(f"BLE core: impossible de demarrer le scan continu: {exc}")

    async def stop_continuous(self) -> None:
        """Arrete le scan continu."""
        self._running = False

        if self._continuous_scanner is not None:
            try:
                await self._continuous_scanner.stop()
            except BleakError:
                pass
            self._continuous_scanner = None
        
        self._scanned_devices.clear()

    async def _on_advertisement(
        self, device: Any, advertisement_data: Any
    ) -> None:
        """Callback interne de scan continu — notification et cache.

        Coroutine async : bleak exécute les callbacks coroutine dans l'event
        loop (changelog bleak 0.10.0 — Windows garantit l'exécution dans le
        thread de l'event loop asyncio). Permet la résolution WinRT du nom.
        """
        if not self._running:
            return

        try:
            address = device.address if hasattr(device, "address") else str(device)
            # BUG FIX : hasattr(local_name) est TOUJOURS True (l'attribut existe
            # même quand il vaut None). Le nom est souvent envoyé dans la
            # SCAN RESPONSE, pas dans la trame initiale → device.name (nom OS)
            # est rempli par bleak après la réponse. Il faut donc tester la
            # VALEUR, pas l'existence de l'attribut.
            local_name = getattr(advertisement_data, "local_name", None)
            os_name = getattr(device, "name", None)
            # Priorité : local_name (trame) > device.name (scan response OS)
            name = local_name or os_name
            rssi = advertisement_data.rssi if hasattr(advertisement_data, "rssi") else -100
            mfr_data = (
                advertisement_data.manufacturer_data
                if hasattr(advertisement_data, "manufacturer_data")
                else {}
            )
            svc_uuids = (
                list(advertisement_data.service_uuids)
                if hasattr(advertisement_data, "service_uuids")
                else []
            )
        except Exception as e:
            logger.debug(f"Erreur extraction donnee publicitaire: {e}")
            return

        mfr_id = None
        mfr_raw = None
        if mfr_data:
            try:
                mfr_id = next(iter(mfr_data.keys()))
                mfr_raw = mfr_data.get(mfr_id)
            except Exception:
                pass

        dev_type = DeviceProfiler.profile(
            name=name,
            service_uuids=svc_uuids,
            manufacturer_id=mfr_id,
            manufacturer_data=mfr_raw,
        )

        discovered = DiscoveredDevice(
            address=address,
            name=name,
            rssi=rssi,
            manufacturer_id=mfr_id,
            manufacturer_data=mfr_raw,
            service_uuids=svc_uuids,
            device_type=dev_type,
            is_connectable=True,
        )

        # Ne PAS écraser un nom déjà connu par "Inconnu" : les trames
        # publicitaires se répètent toutes les ~100ms-1s, et le nom n'arrive
        # souvent qu'avec la scan response (2e trame). Si on écrase, le nom
        # disparaît dès qu'une trame sans nom est reçue.
        existing = self.device_cache.get(address)
        final_name = name
        if not final_name and existing and existing.name and existing.name != "Inconnu":
            final_name = existing.name

        # Dernier recours : résolution WinRT / registre Windows (pairé)
        if not final_name:
            try:
                final_name = await resolve_name(address, None, None)
            except Exception:
                final_name = None

        self.device_cache.upsert(
            BleDeviceInfo(
                address=address,
                name=final_name or "Inconnu",
                rssi=rssi,
                manufacturer_id=mfr_id,
                service_uuids=svc_uuids,
                device_type=dev_type,
                connection_state=ConnectionState.DISCOVERED,
                is_connectable=True,
            )
        )

        self._scanned_devices[address] = device
        while len(self._scanned_devices) > MAX_SCANNED_DEVICES:
            self._scanned_devices.popitem(last=False)

        if self._scan_callback:
            try:
                self._scan_callback(discovered)
            except Exception as e:
                logger.debug(f"Erreur dans le callback de scan: {e}")

    def set_scan_callback(
        self, callback: Optional[Callable[[DiscoveredDevice], None]]
    ) -> None:
        """Enregistre un callback appele à chaque detection publicitaire."""
        self._scan_callback = callback

    async def scan(
        self, timeout: float = SCAN_TIMEOUT
    ) -> List[DiscoveredDevice]:
        """Scan BLE manuel — découverte complète des appareils à proximité.

        Résultats fusionnés dans le cache persistant automatiquement.

        Returns:
            Liste de DiscoveredDevice
        """
        if self._use_mock or not _HAS_BLEAK:
            return await self._mock_scan()

        async with self._scan_lock:
            try:
                devices = await BleakScanner.discover(
                    timeout=timeout,
                    return_adv=True,
                    scanning_mode="active",  # SCAN_RSP → noms complets
                )
            except BleakError as exc:
                logger.error(f"BLE core: erreur scan: {exc}")
                error_manager.error(
                    category=ErrorCategory.BLUETOOTH,
                    error_type="scan_failed",
                )
                return []

        results: List[DiscoveredDevice] = []
        for address, (device, adv_data) in devices.items():
            mfr_data = adv_data.manufacturer_data if hasattr(adv_data, "manufacturer_data") else {}
            mfr_id = next(iter(mfr_data.keys())) if mfr_data else None
            mfr_raw = mfr_data.get(mfr_id) if mfr_id else None
            svc_uuids = (
                list(adv_data.service_uuids) if hasattr(adv_data, "service_uuids") else []
            )

            # BUG FIX : tester la VALEUR de local_name, pas l'existence
            # (hasattr est toujours True quand l'attribut existe mais vaut None).
            local_name = getattr(adv_data, "local_name", None) or None
            os_name = getattr(device, "name", None) or None
            dev_name = local_name or os_name

            dev_type = DeviceProfiler.profile(
                name=dev_name,
                service_uuids=svc_uuids,
                manufacturer_id=mfr_id,
                manufacturer_data=mfr_raw,
            )

            discovered = DiscoveredDevice(
                address=address,
                name=dev_name,
                rssi=adv_data.rssi if hasattr(adv_data, "rssi") else -100,
                manufacturer_id=mfr_id,
                manufacturer_data=mfr_raw,
                service_uuids=svc_uuids,
                device_type=dev_type,
                is_connectable=True,
                raw_device=device,
            )
            results.append(discovered)

            self._scanned_devices[address] = device
            while len(self._scanned_devices) > MAX_SCANNED_DEVICES:
                self._scanned_devices.popitem(last=False)

        # Résolution WinRT des noms manquants (appareils pairés Windows)
        for dev in results:
            if not (dev.name and dev.name.strip()):
                try:
                    dev.name = await resolve_name(dev.address, None, None)
                except Exception:
                    pass

        self.device_cache.merge_scan_results(results)

        return results

    async def _mock_scan(self) -> List[DiscoveredDevice]:
        """Scan simulé pour les tests sans matériel."""
        await asyncio.sleep(1.5)
        try:
            from src.utils.mocks.ble_simulator import get_ble_simulator
            mgr = get_ble_simulator()
            devices = await mgr.get_devices() if hasattr(mgr, "get_devices") else []
        except ImportError:
            devices = []

        results = []
        for d in devices:
            addr = d.address if hasattr(d, "address") else "00:00:00:00:00:00"
            results.append(
                DiscoveredDevice(
                    address=addr,
                    name=d.name if hasattr(d, "name") else "Mock",
                    rssi=-60,
                    device_type=DeviceType.UNKNOWN,
                    is_connectable=True,
                )
            )
        return results

    def get_cached_scanned_devices(self) -> Dict[str, Any]:
        """Retourne les references BLEDevice pour connexion rapide."""
        return dict(self._scanned_devices)

    def register_scanned_device(self, device: Any) -> None:
        """Enregistre un appareil scanné (accès public au registre interne).

        Utilisé par BluetoothCore lors d'un scan complet de dernier recours
        pour alimenter le cache BLEDevice sans violer l'encapsulation.
        """
        if device is None or not hasattr(device, "address"):
            return
        self._scanned_devices[device.address] = device
        while len(self._scanned_devices) > MAX_SCANNED_DEVICES:
            self._scanned_devices.popitem(last=False)
