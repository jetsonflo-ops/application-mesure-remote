"""Profileur d'appareils BLE - Détection intelligente des types d'appareils."""

import struct
import logging
from typing import Dict, List, Optional

from .types import DeviceType, MANUFACTURER_DB, MEASUREMENT_SERVICE_UUIDS

logger = logging.getLogger(__name__)

class DeviceProfiler:
    """Analyse les données publicitaires BLE pour identifier le type d'appareil.

    Utilise :
      - Service UUIDs (16 et 128 bits)
      - Manufacturer Company ID
      - Nom de l'appareil (mot-clés)
      - Données service_data
    """

    # Mots-cles dans le nom pour identifier le type d'outil
    NAME_PATTERNS: Dict[str, DeviceType] = {
        "500": DeviceType.RULE_500,
        "1000": DeviceType.RULE_1000,
        "regle": DeviceType.RULE_500,
        "planéité": DeviceType.RULE_500,
        "planeite": DeviceType.RULE_500,
        "pied": DeviceType.CALIPER,
        "coulisse": DeviceType.CALIPER,
        "caliper": DeviceType.CALIPER,
        "micrometre": DeviceType.MICROMETER,
        "micrometer": DeviceType.MICROMETER,
        "micro": DeviceType.MICROMETER,
        "rugosimetre": DeviceType.ROUGHNESS,
        "roughness": DeviceType.ROUGHNESS,
        "thermometre": DeviceType.THERMOMETER,
        "thermometer": DeviceType.THERMOMETER,
        "pression": DeviceType.PRESSURE,
        "pressure": DeviceType.PRESSURE,
    }

    @classmethod
    def profile(
        cls,
        name: Optional[str],
        service_uuids: List[str],
        manufacturer_id: Optional[int] = None,
        manufacturer_data: Optional[bytes] = None,
        service_data: Optional[Dict[str, bytes]] = None,
    ) -> DeviceType:
        """Determine le type d'appareil a partir des metadonnees disponibles.
        
        Args:
            name (Optional[str]): Nom de l'appareil.
            service_uuids (List[str]): UUIDs de service associés.
            manufacturer_id (Optional[int]): L'ID de l'entreprise fabricante.
            manufacturer_data (Optional[bytes]): Les données du fabricant en bytes.
            service_data (Optional[Dict[str, bytes]]): Les données du service.
            
        Returns:
            DeviceType: Le type de l'appareil détecté.
        """
        # 1. Service UUIDs — regarder les UUIDs standards ou connus
        if service_uuids:
            for uuid_str in service_uuids:
                uuid_lower = uuid_str.lower()
                for known_uuid, (_, dev_type) in MEASUREMENT_SERVICE_UUIDS.items():
                    # Comparaison partielle (les UUIDs peuvent etre raccourcis)
                    if known_uuid.startswith(uuid_lower) or uuid_lower.startswith(
                        known_uuid[:8]
                    ):
                        if dev_type != DeviceType.UNKNOWN:
                            return dev_type

        # 2. Manufacturer ID — certains IDs sont specifiques à des outils
        if manufacturer_id is not None:
            mfr_name = MANUFACTURER_DB.get(manufacturer_id, "").lower()
            # Si c'est un fabricant d'outils de mesure connu
            if "mitutoyo" in mfr_name:
                return DeviceType.CALIPER  # Par défaut (le plus commun)

        # 3. Nom de l'appareil — analyse lexicale
        if name:
            name_lower = name.lower()
            for pattern, dev_type in cls.NAME_PATTERNS.items():
                if pattern in name_lower:
                    return dev_type

        return DeviceType.UNKNOWN

    @classmethod
    def detect_manufacturer(
        cls, manufacturer_id: Optional[int]
    ) -> Optional[str]:
        """Retourne le nom du fabricant à partir du Company ID.
        
        Args:
            manufacturer_id (Optional[int]): L'ID de l'entreprise fabricante.
            
        Returns:
            Optional[str]: Le nom du fabricant s'il est connu, sinon None.
        """
        if manufacturer_id is None:
            return None
        return MANUFACTURER_DB.get(manufacturer_id)

    @classmethod
    def format_manufacturer_data(
        cls, data: Optional[bytes]
    ) -> Optional[str]:
        """Tente de décoder les données fabricant en lisible (hex + texte).
        
        Args:
            data (Optional[bytes]): Les données brutes du fabricant.
            
        Returns:
            Optional[str]: Les données décodées en texte lisible.
        """
        if data is None or len(data) < 2:
            return None
        # Les 2 premiers octets = Company ID
        company_id = struct.unpack("<H", data[:2])[0]
        mfr_name = MANUFACTURER_DB.get(company_id, "Inconnu")
        if len(data) > 2:
            payload_hex = data[2:].hex(" ")
            try:
                payload_text = data[2:].decode("utf-8", errors="replace")
                return f"{mfr_name} (0x{company_id:04X}) [{payload_hex}] \"{payload_text}\""
            except Exception:
                return f"{mfr_name} (0x{company_id:04X}) [{payload_hex}]"
        return f"{mfr_name} (0x{company_id:04X})"

__all__ = ["DeviceProfiler"]
