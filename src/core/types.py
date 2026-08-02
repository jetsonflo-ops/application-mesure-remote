"""Types partagés et structures de données pour le module core.

Définit les énumérations de statut, les classes de données et la logique
de gestion pour les informations de périphériques et les parsings Construct.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import struct
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dépendances optionnelles — on importe avec fallback pour le mock
# ---------------------------------------------------------------------------
_HAS_BLEAK = False
_HAS_RETRY = False
_HAS_CONSTRUCT = False
_HAS_WINRT = False

try:
    from bleak import BleakScanner, BleakClient, BleakError
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementDataCallback

    _HAS_BLEAK = True
except ImportError:  # pragma: no cover
    BleakScanner = None  # type: ignore
    BleakClient = None  # type: ignore
    BleakError = Exception

try:
    from bleak_retry_connector import (
        establish_connection,
        BleakClientWithServiceCache,
    )

    _HAS_RETRY = True
except ImportError:  # pragma: no cover
    _HAS_RETRY = False

try:
    import construct as cs

    _HAS_CONSTRUCT = True
except ImportError:  # pragma: no cover
    cs = None  # type: ignore

# WinRT — disponible uniquement sous Windows
if platform.system() == "Windows":
    try:
        from winrt.windows.devices.bluetooth import BluetoothLEDevice
        from winrt.windows.devices.enumeration import DeviceInformation

        _HAS_WINRT = True
    except ImportError:  # pragma: no cover
        _HAS_WINRT = False

APP_DIR: str = os.path.join(os.path.expanduser("~"), ".application_mesure")
KNOWN_DEVICES_PATH: str = os.path.join(APP_DIR, "known_devices.json")
os.makedirs(APP_DIR, exist_ok=True)

# Limite BLE centrale réelle — la plupart des adaptateurs Windows gèrent 3-4 périphériques
# au-delà les connexions deviennent instables (GitHub bleak #1858, #470)
MAX_CONCURRENT_CONNECTIONS: int = 3
MAX_SCANNED_DEVICES: int = 200  # LRU max — eviction des plus anciens

# Timeouts
SCAN_TIMEOUT: float = 8.0
CONNECT_TIMEOUT: float = 20.0
FIND_DEVICE_TIMEOUT: float = 10.0
OPERATION_TIMEOUT: float = 15.0

# Reconnexion
MAX_RECONNECT_ATTEMPTS: int = 5
BASE_RECONNECT_DELAY: float = 1.0
MAX_RECONNECT_DELAY: float = 60.0

# Files d'attente — pas plus de 3 opérations simultanées
_CONNECTION_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_CONNECTIONS)


class ConnectionState(Enum):
    """Machine d'etats d'une connexion BLE."""

    IDLE = auto()  # Pas encore decouvert
    DISCOVERED = auto()  # Visible en scan
    CONNECTING = auto()  # Connexion en cours
    CONNECTED = auto()  # Connecte et operationnel
    DISCONNECTING = auto()  # Deconnexion en cours
    RECONNECTING = auto()  # Reconnexion automatique avec backoff
    DISCONNECTED = auto()  # Deconnecte (intentionnellement)
    ERROR = auto()  # Erreur permanente


class DeviceType(Enum):
    """Classification des appareils par type (detectee automatiquement)."""

    UNKNOWN = auto()
    RULE_500 = auto()  # Regle de planéité 500mm
    RULE_1000 = auto()  # Regle de planéité 1000mm
    CALIPER = auto()  # Pied à coulisse
    MICROMETER = auto()  # Micromètre
    ROUGHNESS = auto()  # Rugosimètre
    THERMOMETER = auto()  # Thermomètre
    PRESSURE = auto()  # Manomètre / pression
    GENERIC_SENSOR = auto()  # Capteur générique


@dataclass
class AdvertisementData:
    """Données publicitaires BLE nettoyées et standardisées."""

    local_name: Optional[str] = None
    manufacturer_data: Dict[int, bytes] = field(default_factory=dict)
    service_uuids: List[str] = field(default_factory=list)
    service_data: Dict[str, bytes] = field(default_factory=dict)
    tx_power: Optional[int] = None
    rssi: Optional[int] = None
    address: Optional[str] = None


@dataclass
class BleDeviceInfo:
    """Information consolidée sur un périphérique BLE."""

    address: str
    name: str
    rssi: int = -100
    manufacturer_id: Optional[int] = None
    manufacturer_data: Optional[bytes] = None
    service_uuids: List[str] = field(default_factory=list)
    service_data: Dict[str, bytes] = field(default_factory=dict)
    tx_power: Optional[int] = None
    device_type: DeviceType = DeviceType.UNKNOWN
    first_seen: str = ""
    last_seen: str = ""
    connection_state: ConnectionState = ConnectionState.IDLE
    is_paired: bool = False
    is_connectable: bool = True
    last_error: Optional[str] = None

    def to_dict(self) -> dict:
        """Exporte l'objet sous forme de dictionnaire."""
        return {
            "address": self.address,
            "name": self.name,
            "rssi": self.rssi,
            "manufacturer_id": self.manufacturer_id,
            "service_uuids": self.service_uuids,
            "device_type": self.device_type.name,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "connection_state": self.connection_state.name,
            "is_paired": self.is_paired,
            "is_connectable": self.is_connectable,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BleDeviceInfo:
        """Crée une instance à partir d'un dictionnaire."""
        info = cls(
            address=data["address"],
            name=data.get("name", "Inconnu"),
            rssi=data.get("rssi", -100),
            manufacturer_id=data.get("manufacturer_id"),
            service_uuids=data.get("service_uuids", []),
            first_seen=data.get("first_seen", ""),
            last_seen=data.get("last_seen", ""),
            is_paired=data.get("is_paired", False),
            is_connectable=data.get("is_connectable", True),
            last_error=data.get("last_error"),
        )
        type_name = data.get("device_type", "UNKNOWN")
        try:
            info.device_type = DeviceType[type_name]
        except KeyError:
            info.device_type = DeviceType.UNKNOWN
        state_name = data.get("connection_state", "IDLE")
        try:
            info.connection_state = ConnectionState[state_name]
        except KeyError:
            info.connection_state = ConnectionState.IDLE
        return info


# ---------------------------------------------------------------------------
# Construct — parseurs de trames publicitaires BLE (optionnel)
# ---------------------------------------------------------------------------

if _HAS_CONSTRUCT:
    # Structure d'une trame manufacturer data BLE
    # https://www.bluetooth.com/specifications/assigned-numbers/company-identifiers/
    # Note: on utilise cs.Prefixed pour eviter les problemes de contexte
    BleManufacturerData = cs.Struct(
        "company_id" / cs.Int16ub,
        "payload" / cs.Bytes(cs.this._ending_offset - 2),
    )

    # Service UUID 16 bits (standard BLE SIG)
    BleServiceUuid16 = cs.Struct(
        "uuid" / cs.Int16ub,
    )

    # Structure AD Element générique (Advertising Data)
    # Type fields: https://www.bluetooth.com/specifications/assigned-numbers/
    BleAdElement = cs.Struct(
        "length" / cs.Int8ub,
        "type" / cs.Int8ub,
        "data" / cs.Bytes(cs.this.length - 1) if cs.this.length > 1 else cs.Bytes(0),
        cs.Check(cs.len_(cs.this.data) >= 0),
    )
else:
    # Stubs pour quand construct n'est pas installe
    BleManufacturerData = None  # type: ignore
    BleServiceUuid16 = None  # type: ignore
    BleAdElement = None  # type: ignore

# ---------------------------------------------------------------------------
# Base de données de reconnaissance des fabricants industriels
# Company IDs: https://www.bluetooth.com/specifications/assigned-numbers/company-identifiers/
# ---------------------------------------------------------------------------
MANUFACTURER_DB: Dict[int, str] = {
    0x0006: "Microsoft",
    0x000D: "Texas Instruments",
    0x0012: "Intel",
    0x002E: "STMicroelectronics",
    0x004D: "Nokia",
    0x0059: "Nordic Semiconductor",
    0x0060: "NXP Semiconductors",
    0x007A: "Cypress Semiconductor",
    0x009E: "Renesas Electronics",
    0x00E0: "Murata",
    0x0131: "Silicon Labs",
    0x013E: "NXP (ancien)",
    0x0157: "Dialog Semiconductor",
    0x02E5: "Espressif",
    0x030B: "Texas Instruments (BLE)",
    0x0499: "Raspberry Pi",
    0x04C6: "Pine64",
    0x0590: "Microchip",
    0xFFFF: "MITUTOYO",  # Company ID non standard — a vérifier
}

# UUIDs de service liés aux outils de mesure industriels
# Standard GATT : https://www.bluetooth.com/specifications/gatt/services/
MEASUREMENT_SERVICE_UUIDS: Dict[str, Tuple[str, DeviceType]] = {
    "0000180a-0000-1000-8000-00805f9b34fb": ("Device Information", DeviceType.UNKNOWN),
    "0000180d-0000-1000-8000-00805f9b34fb": ("Battery Service", DeviceType.UNKNOWN),
    "0000181a-0000-1000-8000-00805f9b34fb": ("Environmental Sensing", DeviceType.GENERIC_SENSOR),
    "0000181c-0000-1000-8000-00805f9b34fb": ("User Data", DeviceType.UNKNOWN),
    # Custom UUIDs fabricants (exemples — à enrichir avec les vrais appareils)
    "0000ffe0-0000-1000-8000-00805f9b34fb": ("Measurement Data", DeviceType.GENERIC_SENSOR),
    "0000fff0-0000-1000-8000-00805f9b34fb": ("Custom Sensor", DeviceType.GENERIC_SENSOR),
}


def _now_iso() -> str:
    """Retourne la date et l'heure courante au format ISO 8601.

    Returns:
        str: La date au format ISO, par exemple '2023-10-27T10:00:00'.
    """
    return datetime.now().isoformat(timespec="seconds")

@dataclass
class DiscoveredDevice:
    """Resultat brut d'un scan BLE, avant fusion dans le cache."""

    address: str
    name: Optional[str]
    rssi: int = -100
    manufacturer_id: Optional[int] = None
    manufacturer_data: Optional[bytes] = None
    service_uuids: List[str] = field(default_factory=list)
    service_data: Dict[str, bytes] = field(default_factory=dict)
    tx_power: Optional[int] = None
    device_type: DeviceType = DeviceType.UNKNOWN
    is_connectable: bool = True
    raw_device: Any = None  # Reference vers l'objet BLEDevice, conservee pour connexion rapide


__all__ = [
    "ConnectionState",
    "DeviceType",
    "AdvertisementData",
    "BleDeviceInfo",
    "DiscoveredDevice",
    "APP_DIR",
    "KNOWN_DEVICES_PATH",
    "MAX_CONCURRENT_CONNECTIONS",
    "MAX_SCANNED_DEVICES",
    "SCAN_TIMEOUT",
    "CONNECT_TIMEOUT",
    "FIND_DEVICE_TIMEOUT",
    "OPERATION_TIMEOUT",
    "MAX_RECONNECT_ATTEMPTS",
    "BASE_RECONNECT_DELAY",
    "MAX_RECONNECT_DELAY",
    "MANUFACTURER_DB",
    "MEASUREMENT_SERVICE_UUIDS",
    "_now_iso",
    "BleManufacturerData",
    "BleServiceUuid16",
    "BleAdElement",
    "_CONNECTION_SEMAPHORE",
    "_HAS_BLEAK",
    "_HAS_RETRY",
    "_HAS_CONSTRUCT",
    "_HAS_WINRT",
]
