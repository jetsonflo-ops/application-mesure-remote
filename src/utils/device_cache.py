"""Device cache - Persistance des appareils Bluetooth connus."""
import json
import os
from datetime import datetime
from typing import List, Optional, Dict

class DeviceCache:
    """Cache persistant des appareils Bluetooth deja decouverts.
    
    Permet de retrouver un appareil sans rescan BLE complet.
    Le cache est stocke dans ~/.application_mesure/known_devices.json
    """
    
    def __init__(self):
        app_dir = os.path.join(os.path.expanduser("~"), ".application_mesure")
        self.cache_path = os.path.join(app_dir, "known_devices.json")
        self.devices: List[dict] = self._load()
    
    def _load(self) -> List[dict]:
        """Charge le cache depuis le fichier JSON."""
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return []
    
    def _save(self):
        """Sauvegarde le cache dans le fichier JSON."""
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, 'w', encoding='utf-8') as f:
            json.dump(self.devices, f, indent=2)
    
    def update(self, address: str, name: str, details: dict = None):
        """Ajoute ou met a jour un appareil dans le cache."""
        now = datetime.now().isoformat()
        for device in self.devices:
            if device['address'] == address:
                device['name'] = name or device['name']
                device['last_seen'] = now
                if details:
                    device.update(details)
                self._save()
                return
        
        self.devices.append({
            'address': address,
            'name': name or 'Inconnu',
            'first_seen': now,
            'last_seen': now,
            'details': details or {}
        })
        self._save()
    
    def get_by_address(self, address: str) -> Optional[dict]:
        """Retourne un appareil par son adresse."""
        for device in self.devices:
            if device['address'] == address:
                return device
        return None
    
    def get_all(self) -> List[dict]:
        """Retourne tous les appareils connus."""
        return self.devices
    
    def remove(self, address: str):
        """Supprime un appareil du cache."""
        self.devices = [d for d in self.devices if d['address'] != address]
        self._save()
    
    def clear(self):
        """Vide le cache."""
        self.devices = []
        self._save()
