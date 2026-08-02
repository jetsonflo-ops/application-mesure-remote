"""Configurateur de chiffrement modulaire pour l'application de mesure BLE."""

import os
from typing import Dict


class EncryptionConfig:
    """Configuration modulaire du chiffrement avec contrôles par rôle.

    Permet d'activer/désactiver indépendamment :
    - Chiffrement réception Bluetooth (AES-256-GCM)
    - Chiffrement export fichier (AES-256-GCM)

    Ces paramètres sont globaux et ne varient pas selon l'utilisateur.
    Le superviseur seul peut les modifier via l'onglet Paramètres.
    """

    # Paramètres par défaut
    BLE_RECEIVE_ENCRYPTION_DEFAULT = False  # Désactivé pour performance
    FILE_EXPORT_ENCRYPTION_DEFAULT = True   # Activé pour sécurité

    def __init__(self):
        """Initialise la configuration avec les valeurs par défaut."""
        self._settings: Dict[str, bool] = {
            'ble_receive_encryption': self.BLE_RECEIVE_ENCRYPTION_DEFAULT,
            'file_export_encryption': self.FILE_EXPORT_ENCRYPTION_DEFAULT,
        }

    # =========================================================================
    # Accès aux paramètres (lecture seule)
    # =========================================================================

    def is_ble_receive_encrypted(self) -> bool:
        """Vérifie si le chiffrement BLE est activé."""
        return self._settings.get('ble_receive_encryption', self.BLE_RECEIVE_ENCRYPTION_DEFAULT)

    def is_file_export_encrypted(self) -> bool:
        """Vérifie si le chiffrement d'export est activé."""
        return self._settings.get('file_export_encryption', self.FILE_EXPORT_ENCRYPTION_DEFAULT)

    # =========================================================================
    # Modificateurs (superviseur uniquement - appelés depuis SettingsTab)
    # =========================================================================

    def set_ble_receive_encryption(self, enabled: bool) -> None:
        """Active ou désactive le chiffrement BLE."""
        self._settings['ble_receive_encryption'] = enabled

    def set_file_export_encryption(self, enabled: bool) -> None:
        """Active ou désactive le chiffrement d'export."""
        self._settings['file_export_encryption'] = enabled

    # =========================================================================
    # Sérialisation/Deserialization
    # =========================================================================

    def to_dict(self) -> Dict[str, bool]:
        """Convertit la configuration en dictionnaire."""
        return {
            'ble_receive_encryption': self._settings['ble_receive_encryption'],
            'file_export_encryption': self._settings['file_export_encryption'],
        }

    def from_dict(self, data: Dict[str, bool]) -> None:
        """Charge la configuration depuis un dictionnaire."""
        try:
            self._settings['ble_receive_encryption'] = bool(data.get('ble_receive_encryption', 
                self.BLE_RECEIVE_ENCRYPTION_DEFAULT))
            self._settings['file_export_encryption'] = bool(data.get('file_export_encryption',
                self.FILE_EXPORT_ENCRYPTION_DEFAULT))
        except (TypeError, ValueError):
            pass  # Garder les valeurs par défaut en cas d'erreur

    # =========================================================================
    # Chargement/Sauvegarde fichier
    # =========================================================================

    def load_from_file(self, filepath: str) -> bool:
        """Charge la configuration depuis un fichier JSON chiffré ou non."""
        import json
        from src.utils.file_crypto import decrypt_json

        try:
            # Tentative de déchiffrement
            data = decrypt_json(filepath)
            if isinstance(data, dict):
                self.from_dict(data)
                return True
            
            # Fallback en clair (migration silencieuse)
            with open(filepath, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.from_dict(loaded)
        except Exception:
            pass
        
        # Chargement des valeurs par défaut en cas d'erreur
        self._settings['ble_receive_encryption'] = self.BLE_RECEIVE_ENCRYPTION_DEFAULT
        self._settings['file_export_encryption'] = self.FILE_EXPORT_ENCRYPTION_DEFAULT
        return True

    def save_to_file(self, filepath: str) -> bool:
        """Sauvegarde la configuration dans un fichier JSON chiffré."""
        import json
        from src.utils.file_crypto import encrypt_json

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Sauvegarde en clair (fallback si chiffrement échoue)
        try:
            encrypted = encrypt_json(filepath, self.to_dict())
            if not encrypted:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(self.to_dict(), f, indent=2)
            return True
        except Exception:
            # Fallback plaintext
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=2)
            return True


# Singleton global
encryption_config = EncryptionConfig()
