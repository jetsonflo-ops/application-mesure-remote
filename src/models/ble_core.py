"""ble_core — Shim de compatibilité et orchestrateur BluetoothCore.

Ce fichier conserve la classe BluetoothCore (singleton orchestrateur) et
ré-exporte tous les types et classes depuis le nouveau package src.core.

DÉPRÉCIÉ : importez directement depuis src.core à la place.
Exemple : from src.core import BluetoothCore, DeviceCache, BleConnection
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional

from src.utils.error_types import ErrorCategory
from src.utils.error_manager import error_manager
from src.utils.qt_async_executor import create_task

# ---------------------------------------------------------------------------
# Ré-export depuis le nouveau package core
# ---------------------------------------------------------------------------
from src.core.types import (
    ConnectionState,
    DeviceType,
    AdvertisementData,
    BleDeviceInfo,
    DiscoveredDevice,
    APP_DIR,
    KNOWN_DEVICES_PATH,
    MAX_CONCURRENT_CONNECTIONS,
    MAX_SCANNED_DEVICES,
    SCAN_TIMEOUT,
    CONNECT_TIMEOUT,
    FIND_DEVICE_TIMEOUT,
    OPERATION_TIMEOUT,
    MAX_RECONNECT_ATTEMPTS,
    BASE_RECONNECT_DELAY,
    MAX_RECONNECT_DELAY,
    MANUFACTURER_DB,
    MEASUREMENT_SERVICE_UUIDS,
    _now_iso,
    _HAS_BLEAK,
    _HAS_RETRY,
    _HAS_CONSTRUCT,
    _HAS_WINRT,
    _CONNECTION_SEMAPHORE,
)

# Imports conditionnels de bleak (depuis types.py)
try:
    from bleak import BleakScanner, BleakClient, BleakError
    from bleak.backends.device import BLEDevice
except ImportError:
    BleakScanner = None  # type: ignore
    BleakClient = None  # type: ignore
    BleakError = Exception

from src.core.device_cache import DeviceCache
from src.core.profiler import DeviceProfiler
from src.core.connection import ConnectionWatchdog, BleConnection
from src.core.scanner import BleScanner
from src.core.parser import BleDataParser
from src.core.pairing import (
    unpair_device as _unpair_device,
    remove_from_cache as _remove_from_cache,
    forget_device as _forget_device,
    list_paired_devices as _list_paired_devices,
)

logger = logging.getLogger(__name__)


# ===================================================================
# BluetoothCore — Singleton orchestrateur (point d'entrée principal)
# ===================================================================


class BluetoothCore:
    """Noyau Bluetooth de l'application — point d'entree unique.

    Singleton qui orchestre :
      - Decouverte 3 couches (via BleScanner)
      - Connexions multiples avec state machine (via BleConnection)
      - Cache persistant (via DeviceCache)
      - Profileur d'appareils (via DeviceProfiler)
      - API de gestion (pair/unpair/forget/remove)

    Patron utilisé : Singleton thread-safe (asyncio).

    Utilisation :
        core = BluetoothCore()
        await core.start()

        # Scan
        devices = await core.scan()

        # Connexion
        conn = await core.connect("XX:XX:XX:XX:XX:XX")
        if conn:
            data = await conn.read_characteristic("...")
    """

    _instance: Optional["BluetoothCore"] = None
    _lock = asyncio.Lock()

    def __init__(self):
        if BluetoothCore._instance is not None:
            raise RuntimeError(
                "Utilisez BluetoothCore.get_instance() ou await BluetoothCore.create()"
            )
        self._initialized = False
        self.device_cache = DeviceCache()
        self._connections: Dict[str, BleConnection] = {}
        self._scan_callback: Optional[Callable[[DiscoveredDevice], None]] = None
        self._scanner: Optional[BleScanner] = None
        self._running = False
        self._use_mock = False
        self._connection_event_callbacks: Dict[str, List[Callable]] = {}
        # Delai entre connexions consecutives (BlueZ best practice 2026)
        self._stagger_delay: float = 1.5

    # -- Singleton ---------------------------------------------------------

    @classmethod
    async def get_instance(cls) -> "BluetoothCore":
        """Retourne l'instance unique (crée si nécessaire)."""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    await cls._instance._initialize()
        elif not cls._instance._initialized:
            async with cls._lock:
                if not cls._instance._initialized:
                    await cls._instance._initialize()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset du singleton (utile pour les tests ou le nettoyage complet)."""
        cls._instance = None

    async def _initialize(self) -> None:
        if self._initialized:
            return
        self._scanner = BleScanner(
            device_cache=self.device_cache,
            scan_callback=self._scan_callback,
        )
        self._initialized = True

    # -- Start / Stop ------------------------------------------------------

    async def start(self) -> None:
        """Demarre le gestionnaire Bluetooth.

        - Démarre le scan continu pour alimenter le cache
        - Si bleak indisponible, passe en mode mock
        """
        if self._running:
            return

        if not _HAS_BLEAK:
            self._use_mock = True
            logger.info("BLE core: bleak indisponible, utilisation du mock.")
            self._running = True
            return

        self._running = True

        # Scan continu via BleScanner
        if self._scanner:
            try:
                await self._scanner.start_continuous()
            except Exception as exc:
                logger.warning("BLE core: impossible de demarrer le scan continu: %s", exc)

    async def stop(self) -> None:
        """Arrete tout : scanner, connexions, nettoyage WinRT."""
        self._running = False

        # Arreter le scan continu
        if self._scanner:
            await self._scanner.stop_continuous()

        # Deconnecter toutes les connexions (force pour nettoyer WinRT)
        disconnect_tasks = []
        for conn in list(self._connections.values()):
            disconnect_tasks.append(conn.disconnect(force=True))
        if disconnect_tasks:
            await asyncio.gather(*disconnect_tasks, return_exceptions=True)
        self._connections.clear()

    # -- Scan / Découverte -------------------------------------------------

    def set_scan_callback(
        self, callback: Optional[Callable[[DiscoveredDevice], None]]
    ) -> None:
        """Enregistre un callback appele à chaque detection publicitaire."""
        self._scan_callback = callback
        if self._scanner:
            self._scanner.set_scan_callback(callback)

    def get_cached_devices(self) -> List[BleDeviceInfo]:
        """Retourne tous les appareils connus (cache persistant)."""
        return self.device_cache.get_all()

    def get_cached_scanned_devices(self) -> Dict[str, Any]:
        """Retourne les references BLEDevice pour connexion rapide."""
        if self._scanner:
            return self._scanner.get_cached_scanned_devices()
        return {}

    async def scan(
        self, timeout: float = SCAN_TIMEOUT
    ) -> List[DiscoveredDevice]:
        """Scan BLE manuel — découverte complète des appareils à proximité.

        Résultats fusionnés dans le cache persistant automatiquement.

        Retourne : liste de DiscoveredDevice
        """
        if self._scanner:
            return await self._scanner.scan(timeout=timeout)
        return []

    # -- Connexion / Déconnexion -------------------------------------------

    async def connect(
        self,
        address: str,
        name: str = "Inconnu",
        timeout: float = CONNECT_TIMEOUT,
    ) -> Optional[BleConnection]:
        """Connecte un peripherique BLE.

        Stratégie de découverte (3 couches) :
          1. Cache BLEDevice récent (scan continu ou scan manuel)
          2. find_device_by_address() (pas de scan complet)
          3. Scan complet en dernier recours

        Args:
            address: Adresse MAC ou UUID du peripherique
            name: Nom d'affichage
            timeout: Timeout de connexion

        Retourne :
            BleConnection si réussi, None si échec
        """
        if address in self._connections:
            conn = self._connections[address]
            if conn.is_connected:
                return conn
            # Nettoyer l'ancienne connexion morte
            await conn.disconnect()
            del self._connections[address]

        if not _HAS_BLEAK or self._use_mock:
            return await self._mock_connect(address, name)

        # 1. Chercher l'objet BLEDevice dans le cache recent
        scanned = self.get_cached_scanned_devices()
        bledevice = scanned.get(address)

        # 2. Pas en cache → find_device_by_address (pas de scan complet)
        if bledevice is None:
            try:
                bledevice = await BleakScanner.find_device_by_address(
                    address, timeout=FIND_DEVICE_TIMEOUT
                )
            except Exception:
                pass

        # 3. Toujours pas → scan complet en dernier recours
        if bledevice is None:
            logger.info("BLE core: scan complet pour trouver %s...", address)
            try:
                devices = await BleakScanner.discover(timeout=SCAN_TIMEOUT)
                for d in devices:
                    if self._scanner:
                        self._scanner._scanned_devices[d.address] = d
                    if d.address == address:
                        bledevice = d
                        break
            except Exception:
                pass

        if bledevice is None:
            logger.warning("BLE core: appareil %s introuvable", address)
            return None

        # Arreter le scan continu avant de connecter (BlueZ best practice)
        scanner_was_running = False
        if self._scanner and self._scanner._continuous_scanner is not None:
            try:
                await self._scanner.stop_continuous()
                scanner_was_running = True
            except Exception:
                pass

        # Delai espace entre connexions (evite les collisions BlueZ)
        if self._connections:
            await asyncio.sleep(self._stagger_delay)

        # Infos cache pour l'objet connection
        cached = self.device_cache.get(address)

        # Créer l'objet connection avec state machine
        device_info = cached or BleDeviceInfo(
            address=address, name=name, connection_state=ConnectionState.CONNECTING
        )
        conn = BleConnection(
            address=address,
            name=name,
            device_info=device_info,
            disconnected_cb=self._on_connection_lost,
        )

        # Connexion
        success = await conn.connect(bledevice, timeout=timeout)

        # Redemarrer le scan continu si necessaire
        if scanner_was_running and self._running and self._scanner:
            try:
                await self._scanner.start_continuous()
            except Exception:
                pass

        if success:
            self._connections[address] = conn
            device_info.connection_state = ConnectionState.CONNECTED
            self.device_cache.upsert(device_info)
        else:
            device_info.connection_state = ConnectionState.ERROR
            self.device_cache.upsert(device_info)

        return conn if success else None

    async def _mock_connect(
        self, address: str, name: str
    ) -> Optional[BleConnection]:
        """Connexion simulée pour les tests."""
        await asyncio.sleep(0.5)
        device_info = BleDeviceInfo(
            address=address,
            name=name,
            connection_state=ConnectionState.CONNECTED,
        )
        conn = BleConnection(address=address, name=name, device_info=device_info)
        conn.state = ConnectionState.CONNECTED
        self._connections[address] = conn
        return conn

    async def disconnect(self, address: str, force: bool = False) -> bool:
        """Deconnecte un peripherique."""
        conn = self._connections.get(address)
        if conn is None:
            return True
        success = await conn.disconnect(force=force)
        if success or force:
            if address in self._connections:
                del self._connections[address]
            # Mettre à jour le cache
            cached = self.device_cache.get(address)
            if cached:
                cached.connection_state = ConnectionState.DISCONNECTED
                self.device_cache.upsert(cached)
        return success

    async def disconnect_all(self) -> None:
        """Deconnecte tous les peripheriques."""
        tasks = [conn.disconnect(force=True) for conn in self._connections.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._connections.clear()

    def _on_connection_lost(self, connection: BleConnection) -> None:
        """Callback quand une connexion est perdue (déconnexion inattendue)."""
        address = connection.address
        event_key = f"disconnected:{address}"
        callbacks = self._connection_event_callbacks.get(event_key, [])
        for cb in callbacks:
            try:
                cb(connection)
            except Exception:
                pass

        # Notifier générique
        for cb in self._connection_event_callbacks.get("disconnected", []):
            try:
                cb(connection)
            except Exception:
                pass

    def on_event(self, event: str, callback: Callable) -> None:
        """Enregistre un callback d'événement.

        Events: 'disconnected', 'disconnected:<address>', 'connected:<address>',
                'reconnected:<address>', 'scan_result'
        """
        if event not in self._connection_event_callbacks:
            self._connection_event_callbacks[event] = []
        self._connection_event_callbacks[event].append(callback)

    def remove_event(self, event: str, callback: Callable) -> None:
        """Supprime un callback d'événement."""
        if event in self._connection_event_callbacks:
            self._connection_event_callbacks[event] = [
                cb for cb in self._connection_event_callbacks[event] if cb is not callback
            ]

    # -- Gestion des connexions --------------------------------------------

    def get_connection(self, address: str) -> Optional[BleConnection]:
        """Retourne l'objet connection pour une adresse."""
        return self._connections.get(address)

    def get_connected_addresses(self) -> List[str]:
        """Retourne les adresses des peripheriques connectes."""
        return [
            addr
            for addr, conn in self._connections.items()
            if conn.is_connected
        ]

    def get_connected_count(self) -> int:
        return len(self.get_connected_addresses())

    def get_all_connections(self) -> Dict[str, BleConnection]:
        return dict(self._connections)

    # -- Unpair / Device Management (déléguée au module pairing) ----------

    @staticmethod
    async def unpair_device(address: str) -> bool:
        """Supprime l'appairage BLE d'un périphérique sous Windows."""
        return await _unpair_device(address)

    @staticmethod
    async def remove_from_cache(address: str) -> bool:
        """Supprime un appareil du cache persistant."""
        return await _remove_from_cache(address)

    @staticmethod
    async def forget_device(address: str) -> bool:
        """Oublie complètement un appareil : unpair + cache clear."""
        return await _forget_device(address)

    @staticmethod
    async def list_paired_devices() -> List[Dict[str, Any]]:
        """Liste les périphériques BLE pairés sous Windows."""
        return await _list_paired_devices()

    # -- Diagnostics -------------------------------------------------------

    def get_diagnostics(self) -> Dict[str, Any]:
        """Retourne un etat complet du systeme pour debug."""
        return {
            "running": self._running,
            "use_mock": self._use_mock,
            "bleak_available": _HAS_BLEAK,
            "retry_connector_available": _HAS_RETRY,
            "construct_available": _HAS_CONSTRUCT,
            "winrt_available": _HAS_WINRT,
            "cache_size": len(self.device_cache.get_all()),
            "connections_active": self.get_connected_count(),
            "connections_total": len(self._connections),
            "connections": [
                {
                    "address": addr,
                    "state": conn.state.name,
                    "connected": conn.is_connected,
                    "reconnect_count": conn.reconnect_count,
                    "last_error": conn.last_error,
                    "connected_at": str(conn.connected_at) if conn.connected_at else None,
                }
                for addr, conn in self._connections.items()
            ],
        }
