"""Tool model and repository for managing measurement instruments."""
import json
import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict

from src.utils.file_crypto import encrypt_json, decrypt_json

class Tool:
    """Représentation d'un outil de mesure."""
    
    # Unites de mesure et multiplicateurs autorises
    UNIT_OPTIONS = ["mm", "cm", "µm", "Nm", "Ra", "N", "°C", "%"]
    MULTIPLIER_OPTIONS = [1.0, 0.1, 0.01, 0.001]
    # Coherence unite → multiplicateurs valides
    UNIT_MULTIPLIER_MAP = {
        "mm":   [1.0, 0.1, 0.01, 0.001],
        "cm":   [1.0, 0.1, 0.01],
        "µm":   [1.0, 0.1, 0.01, 0.001],
        "Nm":   [1.0, 0.1, 0.01, 0.001],
        "Ra":   [1.0, 0.1, 0.01, 0.001],
        "N":    [1.0, 0.1, 0.01, 0.001],
        "°C":   [1.0, 0.1],
        "%":    [1.0, 0.1],
    }

    def __init__(self, name: str, data_type: str = "numeric", unit: str = "mm",
                 unit_symbol: str = "mm", multiplier: float = 1.0,
                 bluetooth_uuid: str = None, backup_bluetooth_uuid: str = None,
                 manufacturer: str = "",
                 last_calibration: str = None, tool_id: int = None,
                 notification_timeout: float = 30.0):
        self.tool_id = tool_id or int(uuid.uuid4().hex[:8], 16)
        self.name = name
        self.data_type = data_type  # numeric, string, etc.
        self.unit = unit
        self.unit_symbol = unit_symbol or unit
        self.multiplier = multiplier if multiplier in self.MULTIPLIER_OPTIONS else 1.0
        self.bluetooth_uuid = bluetooth_uuid  # Adresse MAC principale
        self.backup_bluetooth_uuid = backup_bluetooth_uuid  # Adresse MAC secondaire
        self.manufacturer = manufacturer
        self.last_calibration = last_calibration
        self.photo_path: str = None
        self.status = "disconnected"  # disconnected, connected, error
        self.signal_strength: Optional[int] = None
        self.created_at = datetime.now()
        self.last_measurement = None
        self.notification_timeout = notification_timeout  # Watchdog timeout en secondes
    
    def to_dict(self) -> dict:
        return {
            'tool_id': self.tool_id,
            'name': self.name,
            'data_type': self.data_type,
            'unit': self.unit,
            'unit_symbol': self.unit_symbol,
            'multiplier': self.multiplier,
            'bluetooth_uuid': self.bluetooth_uuid,
            'backup_bluetooth_uuid': self.backup_bluetooth_uuid,
            'manufacturer': self.manufacturer,
            'last_calibration': self.last_calibration,
            'photo_path': self.photo_path,
            'status': self.status,
            'signal_strength': self.signal_strength,
            'created_at': self.created_at.isoformat(),
            'last_measurement': self.last_measurement.isoformat() if self.last_measurement else None,
            'notification_timeout': self.notification_timeout,
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        tool = cls(
            name=data['name'],
            data_type=data.get('data_type', 'numeric'),
            unit=data.get('unit', ''),
            unit_symbol=data.get('unit_symbol', data.get('unit', '')),
            multiplier=data.get('multiplier', 1.0),
            bluetooth_uuid=data.get('bluetooth_uuid'),
            backup_bluetooth_uuid=data.get('backup_bluetooth_uuid'),
            manufacturer=data.get('manufacturer', ''),
            last_calibration=data.get('last_calibration'),
            tool_id=data.get('tool_id')
        )
        tool.photo_path = data.get('photo_path')
        tool.status = data.get('status', 'disconnected')
        tool.signal_strength = data.get('signal_strength')
        tool.notification_timeout = data.get('notification_timeout', 30.0)
        return tool
    
    def get_active_uuid(self) -> Optional[str]:
        """Retourne l'UUID principal, ou le backup si le principal est absent."""
        if self.bluetooth_uuid:
            return self.bluetooth_uuid
        return self.backup_bluetooth_uuid
    
    def get_uuids(self) -> List[str]:
        """Retourne la liste des UUIDs non vides."""
        uuids = []
        if self.bluetooth_uuid:
            uuids.append(self.bluetooth_uuid)
        if self.backup_bluetooth_uuid:
            uuids.append(self.backup_bluetooth_uuid)
        return uuids
    
    def __str__(self):
        return f"{self.name} ({self.unit}) - {self.status}"

class ToolsRepository:
    """Gère le stockage et la persistance des outils."""
    
    def __init__(self, config_path: str = "config/tools.json"):
        self.config_path = config_path
        self.tools: List[Tool] = []
        self._load_tools()
        
        # Outils par défaut si aucun outil n'est configuré
        if not self.tools:
            self._create_default_tools()
    
    def _load_tools(self):
        """Charge les outils depuis un fichier JSON chiffre AES-256-GCM."""
        if not os.path.exists(self.config_path):
            return

        # Tentative dechiffrement
        data = decrypt_json(self.config_path)
        if isinstance(data, list):
            self.tools = [Tool.from_dict(t) for t in data]
            return

        # Fallback: fichier plaintext (migration silencieuse)
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                tools_data = json.load(f)
                self.tools = [Tool.from_dict(t) for t in tools_data]
        except (json.JSONDecodeError, IOError):
            pass

    def _save_tools(self):
        """Sauvegarde les outils dans un fichier JSON chiffre AES-256-GCM."""
        os.makedirs(os.path.dirname(self.config_path) or '.', exist_ok=True)
        data = [t.to_dict() for t in self.tools]
        if not encrypt_json(self.config_path, data):
            # Fallback plaintext si le chiffrement echoue
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
    
    def _create_default_tools(self):
        """Crée les outils de mesure par défaut."""
        default_tools = [
            Tool(name="Règle de planéité 500mm", data_type="numeric", unit="mm",
                 unit_symbol="mm", multiplier=1.0,
                 bluetooth_uuid="XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"),
            Tool(name="Règle de planéité 1000mm", data_type="numeric", unit="mm",
                 unit_symbol="mm", multiplier=1.0,
                 bluetooth_uuid="YYYYYYYY-YYYY-YYYY-YYYY-YYYYYYYYYYYY"),
            Tool(name="Pied à coulisse", data_type="numeric", unit="mm",
                 unit_symbol="mm", multiplier=0.01,
                 bluetooth_uuid="ZZZZZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZZZZZZZZZ"),
            Tool(name="Micromètre", data_type="numeric", unit="µm",
                 unit_symbol="µm", multiplier=1.0,
                 bluetooth_uuid="AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"),
            Tool(name="Rugosimètre", data_type="numeric", unit="Ra",
                 unit_symbol="Ra", multiplier=1.0,
                 bluetooth_uuid="BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB")
        ]
        
        self.tools = default_tools
        self._save_tools()
    
    def get_all(self) -> List[Tool]:
        """Retourne tous les outils."""
        return self.tools
    
    def get_by_id(self, tool_id: int) -> Optional[Tool]:
        """Trouve un outil par son ID."""
        for tool in self.tools:
            if tool.tool_id == tool_id:
                return tool
        return None
    
    def add_tool(self, tool: Tool):
        """Ajoute un nouvel outil."""
        tool.status = "disconnected"
        self.tools.append(tool)
        self._save_tools()
    
    def update_tool(self, tool: Tool):
        """Met à jour les informations d'un outil existant."""
        for i, t in enumerate(self.tools):
            if t.tool_id == tool.tool_id:
                self.tools[i] = tool
                self._save_tools()
                return
    
    def delete_tool(self, tool_id: int):
        """Supprime un outil de la liste."""
        self.tools = [t for t in self.tools if t.tool_id != tool_id]
        self._save_tools()
    
    def update_status(self, tool_id: int, status: str, signal_strength: Optional[int] = None):
        """Met à jour le statut de connexion d'un outil."""
        for tool in self.tools:
            if tool.tool_id == tool_id:
                tool.status = status
                if signal_strength is not None:
                    tool.signal_strength = signal_strength
                self._save_tools()
                return
    
    def set_last_measurement(self, tool_id: int, measurement_time: datetime):
        """Met à jour l'heure de la dernière mesure."""
        for tool in self.tools:
            if tool.tool_id == tool_id:
                tool.last_measurement = measurement_time
                self._save_tools()
