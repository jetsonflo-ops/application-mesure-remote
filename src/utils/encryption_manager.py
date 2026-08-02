"""Gestionnaire de chiffrement modulaire pour l'application de mesure BLE."""

import asyncio
import base64
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.config.encryption_config import EncryptionConfig, encryption_config

logger = logging.getLogger(__name__)


class EncryptionManager:
    """Gère le chiffrement/déchiffrement modulaire selon les paramètres.

    Ce gestionnaire orchestre l'application du chiffrement AES-256-GCM sur :
    - Les données reçues du BLE (optionnel, pour performance)
    - Les exports de fichiers Excel/CSV (optionnel, pour sécurité)

    L'activation/désactivation dépend des paramètres globaux (superviseur uniquement).
    """

    # Clé dérivée une seule fois (le pepper ne change pas en cours de session)
    _cached_key: Optional[bytes] = None

    def __init__(self, config: Optional[EncryptionConfig] = None):
        """Initialise le gestionnaire avec la configuration.

        Args:
            config: Configuration du chiffrement. Si None, utilise le singleton global.
        """
        self.config = config or encryption_config

    # =========================================================================
    # Méthodes utilitaires de chiffrement/déchiffrement
    # =========================================================================

    def _get_key(self) -> bytes:
        """Retourne la clé AES-256 dérivée (mise en cache).

        La dérivation via sha256(pepper + domain) est calculée UNE SEULE
        fois par session — le pepper est stable (voir secure_config.get_pepper).
        """
        if EncryptionManager._cached_key is None:
            from src.utils.secure_config import get_pepper
            import hashlib
            pepper = get_pepper()
            key_material = hashlib.sha256(pepper + b"encryption-layer").digest()
            EncryptionManager._cached_key = key_material[:32]
        return EncryptionManager._cached_key

    def _encrypt_data(
        self, plaintext_bytes: bytes, aad: Optional[bytes] = None
    ) -> Tuple[bytes, bytes]:
        """Chiffre des données binaires avec AES-256-GCM.

        Args:
            plaintext_bytes: Données à chiffrer
            aad: Données authentifiées (optionnel). Utilisé pour lier le
                 chiffrement à son contexte d'usage (anti-rejeu). Le défaut
                 None préserve la rétro-compatibilité des exports existants.

        Returns:
            Tuple (ciphertext, iv) - Le texte chiffré et l'IV généré aléatoirement
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            import os

            aesgcm = AESGCM(self._get_key())  # Clé de 32 octets pour AES-256
            iv = os.urandom(12)  # IV de 12 octets pour AES-GCM (random secure)
            ciphertext = aesgcm.encrypt(iv, plaintext_bytes, aad)

            return ciphertext, iv
        except ImportError:
            logger.warning("Module cryptography non disponible - chiffrement désactivé")
            raise RuntimeError("Cryptographie requise mais non installée")

    def _decrypt_data(
        self, ciphertext: bytes, iv: bytes, aad: Optional[bytes] = None
    ) -> bytes:
        """Déchiffre des données AES-256-GCM.

        Args:
            ciphertext: Données chiffrées
            iv: Vecteur d'initialisation généré à la chiffrement
            aad: Données authentifiées utilisées au chiffrement (doit correspondre)

        Returns:
            Données déchiffrées en clair
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            aesgcm = AESGCM(self._get_key())
            plaintext = aesgcm.decrypt(iv, ciphertext, aad)
            return plaintext
        except ImportError:
            logger.warning("Module cryptography non disponible - déchiffrement désactivé")
            raise RuntimeError("Cryptographie requise mais non installée")

    def _encrypt_file_content(self, data_dict: Dict[str, Any]) -> Tuple[bytes, bytes]:
        """Chiffre un dictionnaire de données en JSON.

        Args:
            data_dict: Données à chiffrer (doit être sérialisable en JSON)

        Returns:
            Tuple (ciphertext, iv)
        """
        json_str = json.dumps(data_dict, indent=2, ensure_ascii=False)
        return self._encrypt_data(json_str.encode('utf-8'))

    def _decrypt_file_content(self, ciphertext: bytes, iv: bytes) -> Dict[str, Any]:
        """Déchiffre et désérialise un dictionnaire JSON.

        Args:
            ciphertext: Données chiffrées
            iv: Vecteur d'initialisation

        Returns:
            Dictionnaire de données déchiffrées
        """
        json_bytes = self._decrypt_data(ciphertext, iv)
        return json.loads(json_bytes.decode('utf-8'))

    # =========================================================================
    # Traitement des données BLE reçues
    # =========================================================================

    async def process_ble_receive(self, raw_data: bytes) -> bytes:
        """Traite les données reçues du BLE selon la configuration.

        Args:
            raw_data: Données brutes reçues du périphérique BLE

        Returns:
            Données traitées (chiffrées ou en clair selon configuration)
        """
        if self.config.is_ble_receive_encrypted():
            try:
                logger.info("Chiffrement des données BLE")
                # AAD lié au domaine : empêche le rejeu de paquets BLE
                # chiffrés dans un autre contexte (export, fichier).
                ciphertext, iv = self._encrypt_data(
                    raw_data, aad=b"application-mesure:ble-receive:v1"
                )
                
                result = {
                    'encrypted': True,
                    'ciphertext': base64.b64encode(ciphertext).decode('utf-8'),
                    'iv': base64.b64encode(iv).decode('utf-8')
                }
                return json.dumps(result).encode('utf-8')
            except Exception as e:
                logger.error(f"Erreur lors du chiffrement BLE: {e}")
                return raw_data  # Fallback en clair si échec (ne pas bloquer)
        else:
            return raw_data  # Retour en clair pour performance

    async def decrypt_ble_receive(self, encrypted_data: bytes) -> Optional[bytes]:
        """Déchiffre des données BLE si nécessaire.

        Args:
            encrypted_data: Données potentiellement chiffrées

        Returns:
            Données déchiffrées ou None si échec/déchiffrement non requis
        """
        if not self.config.is_ble_receive_encrypted():
            return encrypted_data  # Données déjà en clair
        
        try:
            data_dict = json.loads(encrypted_data.decode('utf-8'))
            if data_dict.get('encrypted'):
                ciphertext = base64.b64decode(data_dict['ciphertext'])
                iv = base64.b64decode(data_dict['iv'])
                return self._decrypt_data(
                    ciphertext, iv, aad=b"application-mesure:ble-receive:v1"
                )
        except Exception as e:
            logger.error(f"Erreur lors du déchiffrement BLE: {e}")
        
        return encrypted_data  # Retour en clair si échec

    # =========================================================================
    # Gestion des exports de fichiers
    # =========================================================================

    async def export_file(self, data: List[Dict[str, Any]], filepath: str) -> str:
        """Exporte des données vers un fichier Excel/CSV.

        Args:
            data: Liste de dictionnaires représentant les mesures
            filepath: Chemin du fichier à exporter

        Returns:
            Chemin du fichier exporté (potentiellement chiffré)
        """
        if self.config.is_file_export_encrypted():
            try:
                logger.info(f"Export chiffré vers {filepath}")
                
                file_data = {
                    'export_date': datetime.now().isoformat(),
                    'measurements': data
                }
                
                ciphertext, iv = self._encrypt_file_content(file_data)
                
                with open(filepath, 'wb') as f:
                    f.write(b'MESURE1')  # Signature magique (7 octets)
                    f.write(len(iv).to_bytes(4, 'big'))  # Taille IV
                    f.write(iv)  # IV
                    f.write(len(ciphertext).to_bytes(4, 'big'))  # Taille données
                    f.write(ciphertext)  # Données chiffrées
                
                return filepath
                
            except Exception as e:
                logger.error(f"Erreur lors de l'export chiffré: {e}")
                return self._export_plain_file(data, filepath)  # Fallback en clair
        else:
            return self._export_plain_file(data, filepath)

    def _export_plain_file(self, data: List[Dict[str, Any]], filepath: str) -> str:
        """Exporte des données vers un fichier Excel/CSV en clair.

        Args:
            data: Liste de dictionnaires
            filepath: Chemin du fichier

        Returns:
            Chemin du fichier exporté
        """
        import pandas as pd
        
        df = pd.DataFrame(data)
        
        if filepath.endswith('.csv'):
            df.to_csv(filepath, index=False, encoding='utf-8-sig')
        elif filepath.endswith(('.xls', '.xlsx')):
            try:
                df.to_excel(filepath, index=False, engine='openpyxl')
            except ImportError:
                # Fallback CSV si openpyxl manquant
                filepath = filepath.rsplit('.', 1)[0] + '.csv'
                df.to_csv(filepath, index=False, encoding='utf-8-sig', sep=';')
                logger.warning("openpyxl non disponible - export CSV à la place de XLSX")
        else:
            filepath = filepath if filepath.endswith('.csv') else filepath + '.csv'
            df.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        return filepath

    def _import_file(self, filepath: str) -> Optional[List[Dict[str, Any]]]:
        """Importe et déchiffre un fichier d'export.

        Args:
            filepath: Chemin du fichier à importer

        Returns:
            Liste de mesures importées, ou None en cas d'erreur
        """
        if not self.config.is_file_export_encrypted():
            return self._import_plain_file(filepath)
        
        try:
            with open(filepath, 'rb') as f:
                magic = f.read(7)
                if magic != b'MESURE1':
                    logger.warning(f"Fichier non chiffré détecté: {filepath}")
                    return self._import_plain_file(filepath)
                
                iv_size = int.from_bytes(f.read(4), 'big')
                iv = f.read(iv_size)
                data_size = int.from_bytes(f.read(4), 'big')
                ciphertext = f.read(data_size)
            
            file_data = self._decrypt_file_content(ciphertext, iv)
            return file_data.get('measurements', [])
            
        except Exception as e:
            logger.error(f"Erreur lors de l'import chiffré: {e}")
            return None

    def _import_plain_file(self, filepath: str) -> Optional[List[Dict[str, Any]]]:
        """Importe un fichier CSV/Excel en clair.

        Args:
            filepath: Chemin du fichier

        Returns:
            Liste de mesures importées
        """
        import pandas as pd
        
        try:
            if filepath.endswith('.csv'):
                df = pd.read_csv(filepath, encoding='utf-8-sig')
            else:
                df = pd.read_excel(filepath) if filepath.endswith(('.xls', '.xlsx')) else None
            
            if df is not None:
                return df.to_dict('records')
        except Exception as e:
            logger.error(f"Erreur lors de l'import: {e}")
        
        return None

    # =========================================================================
    # Méthodes utilitaires
    # =========================================================================

    def get_encryption_status(self) -> Dict[str, bool]:
        """Retourne le statut du chiffrement.

        Returns:
            Dictionnaire avec les statuts
        """
        return {
            'ble_receive_encrypted': self.config.is_ble_receive_encrypted(),
            'file_export_encrypted': self.config.is_file_export_encrypted()
        }


# Singleton global
encryption_manager = EncryptionManager()
