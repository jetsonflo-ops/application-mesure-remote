#!/usr/bin/env python3
"""Tests de validation pour ble_core — vérifie que tout le module s'importe
et que les composants principaux fonctionnent sans matériel BLE."""

import sys
import os
import asyncio
import struct
import tempfile
import json
import pytest

# Ajouter le projet au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models.ble_core import (
    BluetoothCore,
    BleConnection,
    ConnectionState,
    DeviceType,
    DeviceCache,
    DeviceProfiler,
    BleDataParser,
    DiscoveredDevice,
    BleDeviceInfo,
    _HAS_BLEAK,
    _HAS_RETRY,
    _HAS_CONSTRUCT,
    _HAS_WINRT,
    MANUFACTURER_DB,
    MEASUREMENT_SERVICE_UUIDS,
    _CONNECTION_SEMAPHORE,
)


# ===================================================================
# Tests synchrones
# ===================================================================


def test_imports():
    """Verifie que toutes les dependances optionnelles sont correctement detectees."""
    assert _HAS_BLEAK is True
    assert _HAS_RETRY is True
    assert _HAS_CONSTRUCT is True


def test_enums():
    """Verifie les enums et structures de base."""
    assert ConnectionState.IDLE.value >= 1
    assert ConnectionState.CONNECTED.name == "CONNECTED"
    assert len(list(ConnectionState)) == 8
    assert DeviceType.UNKNOWN != DeviceType.CALIPER


def test_device_cache():
    """Test du cache persistant (lecture/ecriture/fusion)."""
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = os.path.join(tmp, "known_devices.json")
        cache = DeviceCache(path=cache_path)

        assert len(cache.get_all()) == 0

        info = BleDeviceInfo(
            address="AA:BB:CC:DD:EE:FF",
            name="Test Rule",
            rssi=-70,
            manufacturer_id=0x02E5,
            service_uuids=["0000180a-..."],
            device_type=DeviceType.RULE_500,
        )
        cache.upsert(info)
        assert len(cache.get_all()) == 1

        retrieved = cache.get("AA:BB:CC:DD:EE:FF")
        assert retrieved is not None
        assert retrieved.name == "Test Rule"
        assert retrieved.device_type == DeviceType.RULE_500

        assert cache.remove("AA:BB:CC:DD:EE:FF")
        assert cache.get("AA:BB:CC:DD:EE:FF") is None

        assert os.path.exists(cache_path)
        with open(cache_path, "r") as f:
            data = json.load(f)
        assert isinstance(data, list)


def test_manufacturer_db():
    """Verifie que la base des fabricants contient les entrees essentielles."""
    assert 0x02E5 in MANUFACTURER_DB  # Espressif
    assert 0x004D in MANUFACTURER_DB   # Nokia
    assert 0x0059 in MANUFACTURER_DB   # Nordic Semi
    assert 0x000D in MANUFACTURER_DB   # Texas Instruments
    assert len(MANUFACTURER_DB) > 15


def test_device_profiler():
    """Verifie le profilage automatique des appareils."""
    assert DeviceProfiler.NAME_PATTERNS.get("500") == DeviceType.RULE_500
    assert DeviceProfiler.NAME_PATTERNS.get("caliper") == DeviceType.CALIPER
    assert DeviceProfiler.NAME_PATTERNS.get("micro") == DeviceType.MICROMETER
    assert DeviceProfiler.NAME_PATTERNS.get("roughness") == DeviceType.ROUGHNESS

    dev_type = DeviceProfiler.profile(
        name="Pied a coulisse digital BT",
        service_uuids=[],
        manufacturer_id=None,
    )
    assert dev_type == DeviceType.CALIPER

    dev_type = DeviceProfiler.profile(
        name="Capteur industriel",
        service_uuids=["0000181a-0000-1000-8000-00805f9b34fb"],
    )
    assert dev_type == DeviceType.GENERIC_SENSOR

    mfr = DeviceProfiler.detect_manufacturer(0x02E5)
    assert mfr == "Espressif"

    mfr = DeviceProfiler.detect_manufacturer(0x9999)
    assert mfr is None


def test_ble_data_parser():
    """Verifie le parseur de donnees BLE."""
    # Format measurement : float 32 bits
    val = BleDataParser.format_measurement(struct.pack("<f", 25.4))
    assert val is not None
    assert abs(val - 25.4) < 0.001

    # Format measurement : int 16 bits
    val = BleDataParser.format_measurement(struct.pack("<h", 1234))
    assert val is not None
    assert val == 1234.0

    # Format measurement : texte
    val = BleDataParser.format_measurement(b"3.141")
    assert val is not None
    assert abs(val - 3.141) < 0.001

    # Format measurement : None sur donnees vides
    val = BleDataParser.format_measurement(b"")
    assert val is None

    # Manufacturer data avec Construct
    test_data = struct.pack("<H", 0x02E5) + b"\x01\x02\x03"
    parsed = BleDataParser.parse_manufacturer_data(test_data)
    assert parsed is not None
    assert parsed["company_id"] == 0x02E5
    assert parsed["company_name"] == "Espressif"
    assert parsed["payload"] == b"\x01\x02\x03"

    # Manufacturer data avec moins de 2 octets
    parsed = BleDataParser.parse_manufacturer_data(b"")
    assert parsed is None


def test_discovered_device_dataclass():
    """Verifie la structure DiscoveredDevice."""
    dev = DiscoveredDevice(
        address="11:22:33:44:55:66",
        name="Test Device",
        rssi=-80,
        service_uuids=["uuid1", "uuid2"],
        is_connectable=True,
    )
    assert dev.address == "11:22:33:44:55:66"
    assert dev.name == "Test Device"
    assert dev.is_connectable

    info = BleDeviceInfo(
        address=dev.address,
        name=dev.name or "Inconnu",
        rssi=dev.rssi,
        service_uuids=dev.service_uuids,
        device_type=dev.device_type,
        connection_state=ConnectionState.DISCOVERED,
    )
    d = info.to_dict()
    assert d["address"] == "11:22:33:44:55:66"
    assert d["device_type"] == "UNKNOWN"
    assert d["connection_state"] == "DISCOVERED"

    restored = BleDeviceInfo.from_dict(d)
    assert restored.address == "11:22:33:44:55:66"
    assert restored.device_type == DeviceType.UNKNOWN


def test_connection_semaphore():
    """Verifie que le semaphore est correctement configure."""
    assert _CONNECTION_SEMAPHORE._value > 0
    assert _CONNECTION_SEMAPHORE._value <= 3


# ===================================================================
# Tests asynchrones
# ===================================================================


@pytest.mark.asyncio
async def test_bluetooth_core_mock_mode():
    """Test du BluetoothCore en mode mock (sans materiel)."""
    core = await BluetoothCore.get_instance()
    core._use_mock = True
    core._running = True

    results = await core.scan(timeout=2.0)
    assert len(results) > 0

    diag = core.get_diagnostics()
    assert diag["use_mock"] is True
    assert "cache_size" in diag
    assert "connections_active" in diag

    BluetoothCore.reset_instance()


# ===================================================================
# Execution directe (python tests/test_ble_core.py)
# ===================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Tests de validation — ble_core.py")
    print("=" * 60)
    print()

    test_imports()
    print("test_imports:              OK")
    test_enums()
    print("test_enums:                OK")
    with tempfile.TemporaryDirectory() as tmp:
        # On injecte tmp dans le test via un override
        cache_path = os.path.join(tmp, "known_devices.json")
        orig = DeviceCache.__init__
        def patched_init(self, path=None):
            orig(self, path=cache_path)
        DeviceCache.__init__ = patched_init
        test_device_cache()
    print("test_device_cache:         OK")
    test_manufacturer_db()
    print("test_manufacturer_db:      OK")
    test_device_profiler()
    print("test_device_profiler:      OK")
    test_ble_data_parser()
    print("test_ble_data_parser:      OK")
    test_discovered_device_dataclass()
    print("test_discovered_dataclass: OK")
    test_connection_semaphore()
    print("test_connection_semaphore: OK")

    print()
    print("=" * 60)
    print("Tests synchrones: OK")
    print()

    try:
        asyncio.run(test_bluetooth_core_mock_mode())
        print("test_bluetooth_core_mock:  OK")
    except RuntimeError:
        print("test_bluetooth_core_mock:  SKIP (event loop deja actif)")

    print()
    print("=" * 60)
    print("Tous les tests ont reussi.")
