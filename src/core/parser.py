"""Parseur de données BLE."""

import struct
import logging
from typing import Any, Dict, Optional

from .types import _HAS_CONSTRUCT, BleManufacturerData, MANUFACTURER_DB

logger = logging.getLogger(__name__)

class BleDataParser:
    """Parseur de données BLE avec la librairie Construct.

    Utilisé pour décoder les manufacturer data et service data
    des trames publicitaires BLE en structures Python lisibles.
    """

    @staticmethod
    def parse_manufacturer_data(
        data: bytes,
    ) -> Optional[Dict[str, Any]]:
        """Décode les données fabricant d'une trame publicitaire BLE.

        Format : [Company ID 2 octets] [Données spécifiques fabricant]

        Args:
            data (bytes): Les données brutes de la trame BLE.

        Returns:
            Optional[Dict[str, Any]]: Un dictionnaire contenant les données décodées:
                {"company_id": int, "company_name": str, "payload": bytes, "payload_hex": str}
                ou None si le décodage échoue.
        """
        if not _HAS_CONSTRUCT or BleManufacturerData is None:
            # Mode sans construct — décodage manuel basique
            if data is None or len(data) < 2:
                return None
            company_id = struct.unpack("<H", data[:2])[0]
            return {
                "company_id": company_id,
                "company_name": MANUFACTURER_DB.get(company_id, "Inconnu"),
                "payload": data[2:],
                "payload_hex": data[2:].hex(),
            }

        try:
            parsed = BleManufacturerData.parse(data)
            return {
                "company_id": parsed.company_id,
                "company_name": MANUFACTURER_DB.get(
                    parsed.company_id, f"0x{parsed.company_id:04X}"
                ),
                "payload": parsed.payload,
                "payload_hex": parsed.payload.hex(),
            }
        except Exception:
            # Fallback silencieux
            if len(data) >= 2:
                company_id = struct.unpack("<H", data[:2])[0]
                return {
                    "company_id": company_id,
                    "company_name": MANUFACTURER_DB.get(company_id, "Inconnu"),
                    "payload": data[2:],
                    "payload_hex": data[2:].hex() if len(data) > 2 else "",
                }
            return None

    @staticmethod
    def parse_service_data(
        uuid: str, data: bytes
    ) -> Optional[Dict[str, Any]]:
        """Décode des données de service.

        Les données de service peuvent contenir des mesures brutes
        selon le format du fabricant — cette méthode tente
        plusieurs interprétations courantes.
        
        Args:
            uuid (str): L'UUID du service.
            data (bytes): Les données brutes du service.
            
        Returns:
            Optional[Dict[str, Any]]: Dictionnaire contenant le résultat du décodage.
        """
        if data is None:
            return None

        result: Dict[str, Any] = {
            "uuid": uuid,
            "raw_hex": data.hex(),
            "raw_length": len(data),
        }

        # Tentative d'interprétation selon les UUIDs standards
        # Environmental Sensing (0x181A)
        if "0000181a" in uuid.lower() or "181a" in uuid:
            result["type"] = "environmental_sensing"
            if len(data) >= 2:
                result["temperature"] = struct.unpack("<h", data[:2])[0] / 100.0
            if len(data) >= 4:
                result["humidity"] = struct.unpack("<H", data[2:4])[0] / 100.0

        # Battery (0x180F)
        elif "0000180f" in uuid.lower() or "180f" in uuid:
            result["type"] = "battery"
            if len(data) >= 1:
                result["level_percent"] = data[0]

        # Device Information (0x180A)
        elif "0000180a" in uuid.lower() or "180a" in uuid:
            result["type"] = "device_info"
            try:
                result["string_value"] = data.decode("utf-8", errors="replace")
            except Exception:
                result["string_value"] = data.hex()

        # Données numériques génériques (mesures industrielles)
        else:
            result["type"] = "generic"
            # Tenter d'interpréter comme un float
            if len(data) == 4:
                try:
                    result["float_value"] = struct.unpack("<f", data)[0]
                except Exception:
                    pass
            elif len(data) == 2:
                try:
                    result["int_value"] = struct.unpack("<H", data)[0]
                except Exception:
                    pass

            # Toujours essayer le décodage texte
            try:
                text = data.decode("utf-8", errors="replace").strip()
                if text and not text.startswith("\uFFFD"):
                    result["text_value"] = text
            except Exception:
                pass

        return result

    @staticmethod
    def format_measurement(data: bytes) -> Optional[float]:
        """Tente d'extraire une valeur numérique de mesure depuis des données brutes.

        Essaie plusieurs formats dans l'ordre :
          1. Texte décodable en float (prioritaire car les outils industriels
             envoient souvent des chaînes comme \"25.400\")
          2. Float 32 bits (IEEE 754)
          3. Int 32 bits signé
          4. Int 16 bits signé

        Args:
            data (bytes): Les données de mesure brutes.
            
        Returns:
            Optional[float]: La valeur extraite, ou None si aucun format ne correspond.
        """
        if data is None or len(data) == 0:
            return None

        # Essai décodage texte en premier (outils industriels → chaînes)
        try:
            text = data.decode("utf-8", errors="replace").strip()
            return float(text)
        except (ValueError, UnicodeDecodeError):
            pass

        # Essai float 32 bits
        if len(data) >= 4:
            try:
                val = struct.unpack("<f", data[:4])[0]
                if not (val == float("inf") or val == float("nan")):
                    return round(val, 4)
            except Exception:
                pass

        # Essai int 32 bits signé
        if len(data) >= 4:
            try:
                val = struct.unpack("<i", data[:4])[0]
                return float(val)
            except Exception:
                pass

        # Essai int 16 bits signé
        if len(data) >= 2:
            try:
                val = struct.unpack("<h", data[:2])[0]
                return float(val)
            except Exception:
                pass

        return None

__all__ = ["BleDataParser"]
