# src/core/__init__.py
"""Core BLE package — modular architecture.

Exports the high-level API used by the rest of the application.
Sub-modules:
  - types: Enums, dataclasses, constants
  - device_cache: Persistent device cache (JSON)
  - profiler: Automatic device type detection
  - connection: BLE connection state machine & watchdog
  - scanner: BLE scanning & advertisement processing
  - pairing: Pairing/unpairing utilities (WinRT)
  - parser: BLE data parsing (manufacturer data, service data)
"""

from .types import (
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
)
from .device_cache import DeviceCache
from .profiler import DeviceProfiler
from .connection import ConnectionWatchdog, BleConnection
from .scanner import BleScanner
from .parser import BleDataParser
from .pairing import unpair_device, remove_from_cache, forget_device, list_paired_devices

__all__ = [
    # Types & constants
    "ConnectionState",
    "DeviceType",
    "AdvertisementData",
    "BleDeviceInfo",
    "DiscoveredDevice",
    "MANUFACTURER_DB",
    "MEASUREMENT_SERVICE_UUIDS",
    # Core classes
    "DeviceCache",
    "DeviceProfiler",
    "ConnectionWatchdog",
    "BleConnection",
    "BleScanner",
    "BleDataParser",
    # Pairing utilities
    "unpair_device",
    "remove_from_cache",
    "forget_device",
    "list_paired_devices",
]
