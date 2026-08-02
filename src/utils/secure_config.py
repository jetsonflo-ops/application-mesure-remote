"""Configuration sécurisée — pepper et gestion des secrets.

Le pepper est chiffré et stocké dans un fichier ~/.application_mesure/pepper.key
avec protection de permissions (chmod 600). Généré automatiquement au premier appel.

NE JAMAIS commit ce fichier de pepper dans git.
"""

import os
import hashlib
import platform
import secrets
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PEPPER_DIR = os.path.join(os.path.expanduser("~"), ".application_mesure")
PEPPER_FILE = os.path.join(PEPPER_DIR, "pepper.key")


def _secure_permissions(filepath: str) -> None:
    """Définit les permissions du fichier sur 600 (lecture/écriture propriétaire uniquement)."""
    try:
        # Sur Unix/Linux/Mac
        os.chmod(filepath, 0o600)
    except OSError as e:
        logger.debug("Impossible de définir les permissions %s: %s", filepath, e)


def _derive_key_from_user() -> bytes:
    """Dériver une clé basée sur l'utilisateur et le hostname pour la protection du pepper.

    Utilise PBKDF2-HMAC-SHA256 (600k itérations — recommandation OWASP 2023+)
    au lieu d'un simple SHA256, pour résister au brute-force hors-ligne.
    """
    # Obtenir un identifiant utilisateur STABLE (ne doit PAS changer entre restarts)
    try:
        import pwd
        uid = os.getuid()
    except ImportError:
        # Sur Windows, utiliser le nom de login (stable, contrairement à os.getpid())
        try:
            uid = os.getlogin()
        except OSError:
            uid = os.environ.get("USERNAME", os.environ.get("USER", "default"))

    hostname = platform.node() or "unknown"
    unique_string = f"appmesure:{hostname}:{uid}"

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"appmesure-pepper-key-salt-v2",
        iterations=600_000,  # OWASP 2023+ : PBKDF2-HMAC-SHA256 → 600k itérations
    )
    return kdf.derive(unique_string.encode())


def _encrypt_pepper(plaintext: bytes) -> tuple[bytes, bytes]:
    """Chiffre le pepper avec une clé dérivée et retourne nonce + ciphertext."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _derive_key_from_user()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96 bits
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce, ciphertext


def _decrypt_pepper(nonce: bytes, ciphertext: bytes) -> bytes:
    """Déchiffre le pepper."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _derive_key_from_user()
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext


def _generate_pepper(force: bool = False) -> bytes:
    """Génère un pepper de 32 bytes et le sauvegarde de manière sécurisée.

    Args:
        force: Si True, régénère même si le fichier existe déjà

    Returns:
        bytes de 32 octets (pepper)
    """
    pepper = None

    if not force and os.path.exists(PEPPER_FILE):
        # Lire le fichier existant
        try:
            with open(PEPPER_FILE, "rb") as f:
                raw_data = f.read()
            if len(raw_data) >= 28:  # nonce (12) + ciphertext min (16)
                nonce = raw_data[:12]
                ciphertext = raw_data[12:]
                try:
                    pepper = _decrypt_pepper(nonce, ciphertext)
                    if len(pepper) == 32:
                        return pepper
                    logger.warning("pepper.key invalide (%d bytes), on régénère", len(pepper))
                except Exception as e:
                    logger.debug("Erreur déchiffrement pepper.key: %s", e)
        except OSError as e:
            logger.error("Erreur lecture pepper.key: %s", e)

    if pepper is None or len(pepper) != 32:
        os.makedirs(PEPPER_DIR, exist_ok=True)
        pepper = secrets.token_bytes(32)
        try:
            # Chiffrer avant d'écrire
            nonce, ciphertext = _encrypt_pepper(pepper)
            payload = nonce + ciphertext
            with open(PEPPER_FILE, "wb") as f:
                f.write(payload)
            # Protéger les permissions du fichier
            _secure_permissions(PEPPER_FILE)
            logger.info("Nouveau pepper généré et chiffré dans %s", PEPPER_FILE)
        except OSError as e:
            logger.error("Impossible d'écrire pepper.key: %s", e)
            # Fallback ultime: HMAC du hostname (stable par machine) - NE PAS UTILISER EN PRODUCTION
            hostname = platform.node() or "unknown"
            pepper = hashlib.sha256(f"appmesure:{hostname}".encode()).digest()
            logger.warning("Fallback pepper utilisé (hostname=%s)", hostname)

    return pepper


_pepper_cache: bytes | None = None
_pepper_cache_valid: bool = False


def get_pepper() -> bytes:
    """Retourne le pepper stocké ou en génère un nouveau.

    Cache en mémoire : le pepper ne change jamais entre deux appels
    (le fichier est relu uniquement au premier appel ou si absent).
    """
    global _pepper_cache, _pepper_cache_valid
    if _pepper_cache_valid and _pepper_cache is not None:
        return _pepper_cache
    _pepper_cache = _generate_pepper(force=False)
    _pepper_cache_valid = True
    return _pepper_cache
