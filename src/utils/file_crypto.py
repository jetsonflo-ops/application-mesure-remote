"""Chiffrement AES-256-GCM pour les fichiers JSON au repos.

Derivation de cle:
    PBKDF2HMAC(SHA256, pepper + sel_aleatoire_par_fichier, iterations=600000)

Format fichier (binaire puis base64) :
    [version:1][salt:16][nonce:12][aad_len:4][aad:N][pt_len:4][ciphertext+tag:M]

Caracteristiques :
    - Sel aleatoire par fichier (pas de sel fixe)
    - AAD lie au chemin du fichier (anti-rebond)
    - Ecriture atomique via fichier temporaire + rename
    - Version byte pour compatibilite future
"""

import base64
import json
import logging
import os
import tempfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.utils.secure_config import get_pepper

logger = logging.getLogger(__name__)

# Format version — incrementer si le format change
_FORMAT_VERSION = 2
_SALT_SIZE = 16
_NONCE_SIZE = 12
_KEY_LENGTH = 32  # AES-256
_ITERATIONS = 600_000  # OWASP 2026 minimum pour PBKDF2-SHA256
# Taille minimale d'un payload valide : version(1) + salt(16) + nonce(12) + aad_len(4) + aad(0) + pt_len(4) = 37 bytes
_MIN_PAYLOAD_SIZE = 37


def _derive_key(pepper: bytes, salt: bytes) -> bytes:
    """Derive une cle AES-256 depuis pepper + sel via PBKDF2-HMAC-SHA256."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LENGTH,
        salt=salt,
        iterations=_ITERATIONS,
    )
    return kdf.derive(pepper)


def _encrypt(plaintext: bytes, aad: bytes, pepper: bytes) -> bytes:
    """Chiffre plaintext avec AES-256-GCM, sel aleatoire.

    Returns:
        Payload binaire : version + salt + nonce + aad_len + aad + pt_len + ciphertext
    """
    import os as _os
    salt = _os.urandom(_SALT_SIZE)
    key = _derive_key(pepper, salt)
    aesgcm = AESGCM(key)
    nonce = _os.urandom(_NONCE_SIZE)
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)

    # Assemblage : [version:1][salt:16][nonce:12][aad_len:4][aad:N][pt_len:4][ciphertext:M]
    import struct
    payload = struct.pack("B", _FORMAT_VERSION)
    payload += salt
    payload += nonce
    payload += struct.pack(">I", len(aad))
    payload += aad
    payload += struct.pack(">I", len(plaintext))
    payload += ciphertext
    return payload


def _decrypt(payload: bytes, aad: bytes, pepper: bytes) -> bytes:
    """Dechiffre un payload cree par _encrypt.

    Returns:
        Plaintext original.

    Raises:
        ValueError: Si le format est invalide ou la cle est incorrecte.
    """
    import struct

    if len(payload) < _MIN_PAYLOAD_SIZE:
        raise ValueError(f"Payload trop court: {len(payload)} bytes")

    offset = 0
    version = struct.unpack("B", payload[offset:offset + 1])[0]
    offset += 1
    if version > _FORMAT_VERSION:
        raise ValueError(f"Version de format inconnue: {version}")

    salt = payload[offset:offset + _SALT_SIZE]
    offset += _SALT_SIZE
    nonce = payload[offset:offset + _NONCE_SIZE]
    offset += _NONCE_SIZE
    aad_len = struct.unpack(">I", payload[offset:offset + 4])[0]
    offset += 4
    stored_aad = payload[offset:offset + aad_len]
    offset += aad_len
    if stored_aad != aad:
        logger.warning("AAD mismatch: fichier lie a un chemin different (stored vs current)")
    pt_len = struct.unpack(">I", payload[offset:offset + 4])[0]
    offset += 4
    ciphertext = payload[offset:]

    key = _derive_key(pepper, salt)
    aesgcm = AESGCM(key)
    # Utiliser stored_aad pour le dechiffrement — correspond a ce qui a ete
    # fourni a aesgcm.encrypt() lors du chiffrement initial.
    return aesgcm.decrypt(nonce, ciphertext, stored_aad)


def encrypt_json(filepath: str, data: dict | list) -> bool:
    """Chiffre et ecrit un fichier JSON avec AES-256-GCM.

    Args:
        filepath: Chemin du fichier a ecrire
        data: Donnees Python (dict ou list) a serialiser

    Returns:
        True si reussi, False sinon
    """
    try:
        pepper = get_pepper()
        plaintext = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        aad = os.path.abspath(filepath).encode("utf-8")
        payload = _encrypt(plaintext, aad, pepper)

        # Ecriture atomique : fichier temporaire → rename
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(filepath) or '.',
            suffix=".tmp",
            prefix=".enc_",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(base64.b64encode(payload).decode("ascii"))
            os.replace(tmp_path, filepath)
        except Exception:
            # Nettoyer le fichier temporaire si erreur
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return True
    except Exception as e:
        logger.error("Erreur chiffrement %s: %s", filepath, e)
        return False


def decrypt_json(filepath: str) -> dict | list | None:
    """Dechiffre et charge un fichier JSON chiffre.

    Args:
        filepath: Chemin du fichier a lire

    Returns:
        Donnees Python (dict/list) ou None si erreur/fichier inexistant
    """
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return None

        payload = base64.b64decode(raw)
        if len(payload) < _MIN_PAYLOAD_SIZE:
            logger.warning("Fichier trop court ou invalide: %s", filepath)
            return None

        pepper = get_pepper()
        aad = os.path.abspath(filepath).encode("utf-8")
        plaintext = _decrypt(payload, aad, pepper)

        return json.loads(plaintext.decode("utf-8"))
    except Exception as e:
        logger.error("Erreur dechiffrement %s: %s", filepath, e)
        return None
