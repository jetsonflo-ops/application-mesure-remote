import logging
import platform
from typing import Any, Dict, List

from .device_cache import DeviceCache
from .types import _HAS_WINRT

logger = logging.getLogger(__name__)

__all__ = [
    "unpair_device",
    "remove_from_cache",
    "forget_device",
    "list_paired_devices",
]

async def unpair_device(address: str) -> bool:
    """Supprime l'appairage BLE d'un périphérique sous Windows.

    Méthodes tentées dans l'ordre :
      1. WinRT DeviceInformationPairing.UnpairAsync() (BLE)
      2. BluetoothDeleteDevice Win32 (Classic BT)

    Nécessite winrt sous Windows.

    Note : Windows 10+ n'exige PAS le pairing pour BLE.
    Le pairing peut causer des erreurs "unreachable" (Nordic DevZone).
    Cette méthode est utile pour nettoyer les devices pairés
    qui posent problème.
    
    Args:
        address: Adresse MAC du périphérique
        
    Returns:
        True si succès, False sinon
    """
    if platform.system() != "Windows":
        logger.info(f"BLE core: unpair non supporté sur {platform.system()}")
        return False

    if not _HAS_WINRT:
        try:
            import ctypes

            bthapi = ctypes.windll.bthprops
            bth_addr = int(address.replace(":", ""), 16)
            result = bthapi.BluetoothRemoveDevice(ctypes.c_ulonglong(bth_addr))
            if result == 0:
                return True
            logger.warning(f"BLE core: BluetoothRemoveDevice a echoue (code {result})")
            return False
        except Exception as exc:
            logger.error(f"BLE core: unpair (fallback) erreur: {exc}")
            return False

    try:
        from winrt.windows.devices.bluetooth import BluetoothLEDevice

        ble_device = await BluetoothLEDevice.from_bluetooth_address_async(
            int(address.replace(":", ""), 16)
        )
        if ble_device is None:
            logger.warning(f"BLE core: appareil {address} non trouvé via WinRT")
            return False

        if ble_device.device_information and ble_device.device_information.pairing:
            if ble_device.device_information.pairing.is_paired:
                await ble_device.device_information.pairing.unpair_async()
                logger.info(f"BLE core: appareil {address} dépairé avec succès")
            else:
                logger.info(f"BLE core: appareil {address} n'était pas pairé")

        ble_device.close()
        return True
    except Exception as exc:
        logger.error(f"BLE core: unpair WinRT erreur: {exc}")
        return False


async def remove_from_cache(address: str) -> bool:
    """Supprime un appareil du cache persistant.

    Ne supprime pas l'appairage système — uniquement le cache local.
    
    Args:
        address: Adresse MAC du périphérique
        
    Returns:
        True si supprimé, False sinon
    """
    cache = DeviceCache()
    return cache.remove(address)


async def forget_device(address: str) -> bool:
    """Oublie complètement un appareil : unpair + cache clear.

    Combinaison de :
      1. unpair_device() (WinRT si Windows, sinon ignoré)
      2. remove_from_cache() (cache local)
      
    Args:
        address: Adresse MAC du périphérique
        
    Returns:
        True si succès, False sinon
    """
    if platform.system() == "Windows":
        await unpair_device(address)
    return await remove_from_cache(address)


async def list_paired_devices() -> List[Dict[str, Any]]:
    """Liste les périphériques BLE pairés sous Windows.

    Utile pour le diagnostic et la gestion des appareils
    qui pourraient causer des conflits.
    
    Returns:
        Liste de dictionnaires contenant les informations des appareils
    """
    if platform.system() != "Windows" or not _HAS_WINRT:
        return []

    paired = []
    try:
        from winrt.windows.devices.enumeration import DeviceInformation

        try:
            selector = (
                "System.Devices.Aep.CanPair:=System.StructuredQueryType.Boolean#True"
            )
            devices = await DeviceInformation.find_all_async_async(selector)
            for dev in devices:
                if dev.name and "bluetooth" in dev.kind.lower():
                    paired.append(
                        {
                            "id": dev.id,
                            "name": dev.name,
                            "is_paired": dev.pairing.is_paired if dev.pairing else False,
                        }
                    )
        except Exception as e:
            logger.debug(f"Erreur enumeration appareils: {e}")
    except Exception as e:
        logger.debug(f"Erreur winrt module: {e}")
    return paired
