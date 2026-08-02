"""Audit logger — traçage des actions critiques.

Stocke un fichier JSON Lines horodaté dans ~/.application_mesure/audit.log
avec rotation automatique à 10 MB et signature cryptographique HMAC-SHA256
pour prévenir la falsification des logs.
"""

import os
import json
import logging
import hmac
import hashlib
from datetime import datetime
from src.utils.secure_config import get_pepper

logger = logging.getLogger(__name__)

AUDIT_LOG = os.path.join(
    os.path.expanduser("~"), ".application_mesure", "audit.log"
)
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB


def _rotate_if_needed():
    """Rotation automatique si le fichier dépasse la limite."""
    if not os.path.exists(AUDIT_LOG):
        return
    try:
        size = os.path.getsize(AUDIT_LOG)
        if size > MAX_LOG_SIZE:
            base = AUDIT_LOG
            idx = 1
            while os.path.exists(f"{base}.{idx}"):
                idx += 1
            os.rename(base, f"{base}.{idx}")
            logger.info("Rotation audit.log → audit.log.%d", idx)
    except OSError:
        pass


def _sign_entry(entry: dict) -> str:
    """Signe une entrée d'audit avec HMAC-SHA256 pour prévention falsification."""
    pepper = get_pepper()
    # Créer un message signé sans le champ 'signature'
    msg_data = json.dumps(entry, ensure_ascii=False).encode('utf-8')
    signature = hmac.new(pepper, msg_data, hashlib.sha256).hexdigest()
    entry['signature'] = signature
    return json.dumps(entry, ensure_ascii=False)


def audit(action: str, user: str, detail: str = ""):
    """Écrit une entrée dans le journal d'audit signé.

    Args:
        action: Nom de l'action (LOGIN, TOOL_ADD, PASSWORD_CHANGE, etc.)
        user: Nom d'utilisateur
        detail: Information complémentaire
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "user": user,
        "detail": detail,
    }
    try:
        _rotate_if_needed()
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(_sign_entry(entry) + "\n")
    except OSError as e:
        logger.error("Impossible d'écrire dans audit.log: %s", e)
