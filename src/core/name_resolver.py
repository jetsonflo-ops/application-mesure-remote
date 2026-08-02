"""Résolution de noms BLE enrichie — Windows.

Problème : bleak ne remonte le nom local que si l'appareil l'envoie dans
sa trame publicitaire OU sa scan response (le nom arrive souvent en 2e
trame, après la SCAN_REQ). Beaucoup d'appareils (téléphones, écouteurs,
souris, montres) restent donc "Inconnu" malgré un nom connu de Windows.

Stratégie de résolution (par ordre de fiabilité) :
  1. adv.local_name  — nom dans la trame publicitaire
  2. device.name     — nom OS donné par bleak (rempli par la scan response)
  3. WinRT BluetoothLEDevice.from_bluetooth_address_async() — appareils
     pairés ou présents dans le cache système Windows (MS Learn)
  4. Registre BTHPORT\\Parameters\\Devices — appareils BT classiques pairés
     (nom stocké en base64, valeur "Name")
  5. Fabricant via Company ID publicitaire (manufacturer_data) — même pour
     les adresses randomisées (Apple, Samsung, etc. émettent leur Company ID)
  6. Fabricant via préfixe MAC (OUI IEEE) — adresses publiques uniquement
"""

from __future__ import annotations

import asyncio
import base64
import logging
import platform
from typing import Dict, Optional

from .device_db import manufacturer_display, is_random_address

logger = logging.getLogger(__name__)

# Cache des noms résolus par adresse (évite les appels WinRT répétés)
_resolved_names: Dict[str, str] = {}
# Cache des échecs de résolution (TTL 60s) — une trame BLE revient ~1x/s,
# on ne veut pas marteler WinRT pour un appareil non résolvable.
_failed_resolutions: Dict[str, float] = {}
_FAIL_TTL = 60.0


def _is_failed(address: str) -> bool:
    """Vrai si la résolution a récemment échoué pour cette adresse."""
    import time
    ts = _failed_resolutions.get(address)
    if ts is None:
        return False
    if time.time() - ts > _FAIL_TTL:
        _failed_resolutions.pop(address, None)
        return False
    return True


def _parse_addr(address: str) -> Optional[int]:
    """Convertit une adresse MAC 'AA:BB:CC:DD:EE:FF' en entier 64 bits."""
    try:
        clean = address.replace(":", "").replace("-", "")
        if len(clean) != 12:
            return None
        return int(clean, 16)
    except (ValueError, AttributeError):
        return None


def _load_registry_names() -> Dict[str, str]:
    """Lit le registre Windows BTHPORT pour les appareils BT classiques pairés.

    Clé : HKLM\\SYSTEM\\CurrentControlSet\\Services\\BTHPORT\\Parameters\\Devices
    Chaque sous-clé = adresse sans séparateurs, valeur "Name" = nom en base64.
    """
    names: Dict[str, str] = {}
    if platform.system() != "Windows":
        return names
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices",
        )
        count = winreg.QueryInfoKey(key)[0]
        for i in range(count):
            sub_name = winreg.EnumKey(key, i)
            try:
                sub = winreg.OpenKey(key, sub_name)
                try:
                    val, _ = winreg.QueryValueEx(sub, "Name")
                    if val:
                        decoded = None
                        # Format 1 : base64 → UTF-8/ASCII (nom terminé par \x00)
                        try:
                            raw = base64.b64decode(val, validate=False)
                            decoded = raw.decode(
                                "utf-8", errors="ignore"
                            ).strip("\x00").strip()
                        except Exception:
                            decoded = None
                        # Format 2 : base64 → UTF-16 LE (certains claviers/souris)
                        if not decoded:
                            try:
                                raw = base64.b64decode(val, validate=False)
                                decoded = raw.decode(
                                    "utf-16-le", errors="ignore"
                                ).strip("\x00").strip()
                            except Exception:
                                decoded = None
                        # Format 3 : chaîne brute UTF-8 directe
                        if not decoded:
                            try:
                                decoded = val.decode(
                                    "utf-8", errors="ignore"
                                ).strip("\x00").strip()
                            except Exception:
                                decoded = None
                        if decoded:
                            addr_key = sub_name.lower()
                            names[addr_key] = decoded
                except FileNotFoundError:
                    pass
                winreg.CloseKey(sub)
            except OSError:
                continue
        winreg.CloseKey(key)
    except (FileNotFoundError, OSError, ImportError) as e:
        logger.debug("Registre BTHPORT inaccessible: %s", e)
    return names


async def _resolve_winrt(address: str) -> Optional[str]:
    """Résout le nom via WinRT (appareils pairés / cache système Windows).

    Source : Windows.Devices.Bluetooth.BluetoothLEDevice.FromBluetoothAddressAsync
    (Microsoft Learn) — retourne le nom même si l'appareil n'émet plus
    de trames publicitaires, tant qu'il est pairé ou dans le cache système.
    """
    addr_int = _parse_addr(address)
    if addr_int is None:
        return None
    try:
        from winrt.windows.devices.bluetooth import BluetoothLEDevice
        ble_device = await BluetoothLEDevice.from_bluetooth_address_async(addr_int)
        if ble_device is not None:
            name = ble_device.name
            if name and not name.startswith("Bluetooth "):
                return name
    except ImportError:
        logger.debug("WinRT indisponible (paquet winrt-Windows.Devices.Bluetooth manquant)")
    except Exception as e:
        logger.debug("Erreur WinRT pour %s: %s", address, e)
    return None


async def resolve_name(
    address: str,
    local_name: Optional[str],
    device_name: Optional[str],
    company_id: Optional[int] = None,
) -> str:
    """Retourne le meilleur nom/fabricant disponible pour un appareil BLE.

    Args:
        address: Adresse MAC de l'appareil
        local_name: Nom de la trame publicitaire (adv.local_name)
        device_name: Nom OS fourni par bleak (BLEDevice.name)
        company_id: Company ID Bluetooth SIG des données publicitaires

    Returns:
        Nom affichable, ou fabricant, ou "Inconnu".
    """
    # 1. Nom déjà en cache
    cached = _resolved_names.get(address)
    if cached:
        return cached

    # 1b. Échec récent → éviter de marteler WinRT (trames répétées ~1x/s)
    if _is_failed(address):
        # Même en échec, on tente le fabricant (pas de WinRT requis)
        mfr = manufacturer_display(company_id, address)
        if mfr:
            return f"Appareil {mfr}"
        return "Inconnu"

    # 2. local_name (trame publicitaire) — prioritaire
    if local_name and local_name.strip():
        _resolved_names[address] = local_name.strip()
        return local_name.strip()

    # 3. device.name (nom OS bleak, souvent rempli par la scan response)
    if device_name and device_name.strip() and device_name.strip() != "Inconnu":
        _resolved_names[address] = device_name.strip()
        return device_name.strip()

    # 4. WinRT — appareils pairés / cache système Windows
    winrt_name = await _resolve_winrt(address)
    if winrt_name:
        _resolved_names[address] = winrt_name
        return winrt_name

    # 5. Registre BTHPORT — appareils BT classiques pairés
    reg_names = _load_registry_names()
    addr_key = address.replace(":", "").replace("-", "").lower()
    reg_name = reg_names.get(addr_key)
    if reg_name:
        _resolved_names[address] = reg_name
        return reg_name

    # 6. Fabricant via Company ID publicitaire (même adresse randomisée)
    mfr = manufacturer_display(company_id, address)
    if mfr:
        display = f"Appareil {mfr}"
        _resolved_names[address] = display
        return display

    # Échec : mémoriser pour ne pas réessayer avant TTL
    import time
    _failed_resolutions[address] = time.time()
    return "Inconnu"


def clear_cache() -> None:
    """Vide le cache des noms résolus (appelé au reset/stop)."""
    _resolved_names.clear()


async def _resolve_gatt_name(address: str) -> Optional[str]:
    """Dernier recours : lecture de la caractéristique GATT Device Name (0x2A00).

    Nécessite une connexion BLE éphémère (timeout court, aucune écriture).
    Seuls les appareils exposant le service Device Information répondent.
    Utilisé UNIQUEMENT en scan manuel (trop lent pour le scan continu).
    """
    try:
        from bleak import BleakClient

        async with BleakClient(address, timeout=5.0) as client:
            try:
                data = await client.read_gatt_char(
                    "00002a00-0000-1000-8000-00805f9b34fb"
                )
                name = bytes(data).decode("utf-8", errors="replace").strip()
                if name:
                    return name
            except Exception:
                return None
    except Exception:
        pass
    return None


async def enrich_all(devices: list) -> None:
    """Enrichit une liste d'appareils sans nom via WinRT (résolution groupée).

    Args:
        devices: Liste d'objets avec attributs .address/.name
    """
    pending = [d for d in devices if not (d.name and d.name.strip())]
    if not pending:
        return
    for dev in pending:
        name = await resolve_name(dev.address, None, None)
        if name == "Inconnu":
            # Scan manuel : tentative GATT (lecture 0x2A00) en dernier recours
            name = await _resolve_gatt_name(dev.address) or "Inconnu"
        if name != "Inconnu":
            dev.name = name
