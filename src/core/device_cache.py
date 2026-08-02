"""Cache persistant des appareils BLE connus (fichier JSON)."""

import asyncio
import json
import logging
import os
from collections import OrderedDict
from typing import List, Optional

from .types import BleDeviceInfo, ConnectionState, DiscoveredDevice, KNOWN_DEVICES_PATH, _now_iso

logger = logging.getLogger(__name__)

class DeviceCache:
    """Cache persistant des appareils BLE connus (fichier JSON).

    Permet d'afficher les appareils connus immédiatement, même hors scan,
    et de retrouver un appareil par adresse sans rediscovery.
    """

    def __init__(self, path: str = KNOWN_DEVICES_PATH) -> None:
        """Initialise le cache persistant de périphériques.

        Args:
            path (str): Chemin du fichier de persistance JSON.
        """
        self._path = path
        self._store: "OrderedDict[str, BleDeviceInfo]" = OrderedDict()
        self._dirty: bool = False
        self._save_timer: Optional[asyncio.TimerHandle] = None
        self._load()

    # -- Persistance -------------------------------------------------------

    def _load(self) -> None:
        """Charge le cache depuis le disque."""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for entry in raw:
                try:
                    info = BleDeviceInfo.from_dict(entry)
                    self._store[info.address] = info
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(f"Ignored invalid device entry: {e}")
                    continue
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading device cache: {e}")

    def _write_disk(self) -> None:
        """Ecriture reelle sur le disque (appelee par le timer debounce)."""
        self._save_timer = None
        if not self._dirty:
            return
        self._dirty = False
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(
                    [info.to_dict() for info in self._store.values()],
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except IOError as e:
            logger.error(f"Failed to write device cache to disk: {e}")

    def _schedule_save(self) -> None:
        """Planifie une sauvegarde debouncée (max 1x / 5s)."""
        self._dirty = True
        if self._save_timer is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop:
            self._save_timer = loop.call_later(5.0, self._write_disk)
        else:
            self._write_disk()

    def flush(self) -> None:
        """Ecriture immediate (appeler au shutdown)."""
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None
        self._dirty = True
        self._write_disk()

    # -- CRUD --------------------------------------------------------------

    def upsert(self, info: BleDeviceInfo) -> None:
        """Ajoute ou met à jour un appareil dans le cache.
        
        Args:
            info (BleDeviceInfo): Informations de l'appareil à insérer ou mettre à jour.
        """
        now = _now_iso()
        existing = self._store.get(info.address)
        if existing:
            info.first_seen = existing.first_seen
        else:
            info.first_seen = now
        info.last_seen = now
        self._store[info.address] = info
        self._schedule_save()

    def get(self, address: str) -> Optional[BleDeviceInfo]:
        """Récupère un appareil depuis le cache par son adresse.
        
        Args:
            address (str): Adresse MAC (ou UUID) du périphérique.
            
        Returns:
            Optional[BleDeviceInfo]: Le périphérique s'il est dans le cache, sinon None.
        """
        return self._store.get(address)

    def get_all(self) -> List[BleDeviceInfo]:
        """Retourne tous les appareils stockés dans le cache.
        
        Returns:
            List[BleDeviceInfo]: Liste des appareils.
        """
        return list(self._store.values())

    def remove(self, address: str) -> bool:
        """Supprime un appareil du cache.
        
        Args:
            address (str): Adresse du périphérique.
            
        Returns:
            bool: True si l'appareil a été supprimé, False s'il n'existait pas.
        """
        if address in self._store:
            del self._store[address]
            self._schedule_save()
            return True
        return False

    def clear(self) -> None:
        """Vide le cache de tous les appareils."""
        self._store.clear()
        self._schedule_save()

    def merge_scan_results(
        self, devices: List["DiscoveredDevice"]
    ) -> List[BleDeviceInfo]:
        """Fusionne les resultats d'un scan dans le cache et retourne la liste complete.
        
        Args:
            devices (List[DiscoveredDevice]): Liste d'appareils découverts lors du scan.
            
        Returns:
            List[BleDeviceInfo]: Liste complète des appareils en cache.
        """
        for dev in devices:
            info = BleDeviceInfo(
                address=dev.address,
                name=dev.name or "Inconnu",
                rssi=dev.rssi,
                manufacturer_id=dev.manufacturer_id,
                manufacturer_data=dev.manufacturer_data,
                service_uuids=dev.service_uuids,
                service_data=dev.service_data,
                tx_power=dev.tx_power,
                device_type=dev.device_type,
                connection_state=ConnectionState.DISCOVERED,
                is_connectable=dev.is_connectable,
            )
            self.upsert(info)
        return self.get_all()

    def update(self, address: str, name: str, details: dict = None) -> None:
        """Méthode de compatibilité pour l'API DeviceCache (update -> upsert).
        
        Args:
            address (str): L'adresse du périphérique.
            name (str): Le nom du périphérique.
            details (dict, optional): Détails supplémentaires.
        """
        now = _now_iso()
        existing = self._store.get(address)
        if existing:
            info = BleDeviceInfo(
                address=address,
                name=name or existing.name,
                rssi=details.get("rssi", existing.rssi) if details else existing.rssi,
                manufacturer_id=existing.manufacturer_id,
                manufacturer_data=existing.manufacturer_data,
                service_uuids=existing.service_uuids,
                service_data=existing.service_data,
                tx_power=existing.tx_power,
                device_type=existing.device_type,
                first_seen=existing.first_seen,
                last_seen=now,
                connection_state=ConnectionState[details.get("status", "DISCOVERED").upper()] if details and "status" in details else existing.connection_state,
                is_paired=existing.is_paired,
                is_connectable=existing.is_connectable,
                last_error=existing.last_error,
            )
        else:
            info = BleDeviceInfo(
                address=address,
                name=name or "Inconnu",
                rssi=details.get("rssi", -100) if details else -100,
                connection_state=ConnectionState[details.get("status", "DISCOVERED").upper()] if details and "status" in details else ConnectionState.DISCOVERED,
            )
        self.upsert(info)

__all__ = ["DeviceCache"]
