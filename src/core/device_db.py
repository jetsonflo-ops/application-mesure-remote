"""Bases de données d'identification Bluetooth intégrées.

Deux sources complémentaires :
1. COMPANY_IDS : Company Identifiers Bluetooth SIG officiels (1136 entrées)
   — identifie le FABRICANT via les données publicitaires (manufacturer_data).
   Fonctionne même avec les adresses MAC randomisées (Apple, Samsung, etc.
   émettent leur Company ID dans le payload même avec adresse aléatoire).
2. OUI_DB : préfixes MAC (OUI IEEE, 40102 entrées) → fabricant.
   Utilisable uniquement pour les adresses MAC publiques (non randomisées).

Sources :
- Company IDs : Bluetooth SIG Assigned Numbers (gist angorb, mis à jour)
- OUI : OUI-Master-Database (IEEE + Nmap + Wireshark, 88k+ vendors)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Company Identifiers Bluetooth SIG : {int company_id: str fabricant}
COMPANY_IDS: Dict[int, str] = {}
# OUI MAC : {préfixe 6-hex minuscules: str fabricant}
OUI_DB: Dict[str, str] = {}


def _load_json(filename: str) -> dict:
    """Charge un fichier JSON de données, avec fallback silencieux."""
    path = os.path.join(_DATA_DIR, filename)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Base %s non chargée: %s", filename, e)
    return {}


def _init() -> None:
    """Charge les bases au premier accès."""
    global COMPANY_IDS, OUI_DB
    if COMPANY_IDS:
        return
    raw_cids = _load_json("company_ids.json")
    COMPANY_IDS = {int(k): v for k, v in raw_cids.items()}
    raw_oui = _load_json("oui_norm.json")
    OUI_DB = {k.lower(): v for k, v in raw_oui.items()}
    logger.info(
        "Bases BLE chargées: %d company IDs, %d OUI",
        len(COMPANY_IDS), len(OUI_DB),
    )


_init()


def company_name(company_id: Optional[int]) -> Optional[str]:
    """Retourne le nom du fabricant pour un Company ID Bluetooth SIG."""
    if company_id is None:
        return None
    return COMPANY_IDS.get(company_id)


def oui_name(address: str) -> Optional[str]:
    """Retourne le fabricant depuis le préfixe MAC (adresses publiques).

    Args:
        address: Adresse MAC 'AA:BB:CC:DD:EE:FF'

    Returns:
        Nom du fabricant si le préfixe est connu, sinon None.
    """
    if not address:
        return None
    prefix = address.replace(":", "").replace("-", "").lower()[:6]
    if len(prefix) != 6:
        return None
    return OUI_DB.get(prefix)


def manufacturer_display(
    company_id: Optional[int], address: str
) -> Optional[str]:
    """Nom du fabricant par Company ID, fallback OUI MAC.

    Returns:
        Nom du fabricant, ou None si aucune source.
    """
    name = company_name(company_id)
    if name:
        return name
    return oui_name(address)


def is_random_address(address: str) -> bool:
    """Vrai si l'adresse MAC est randomisée (bit 1 du premier octet).

    Les adresses randomisées (privacy) ne sont PAS résolvables par OUI.
    Le Company ID des données publicitaires reste LA méthode d'identification.
    """
    if not address or len(address) < 2:
        return False
    first = address[:2]
    try:
        return bool(int(first, 16) & 0x02)
    except ValueError:
        return False
