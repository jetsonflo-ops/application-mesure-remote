"""Measurement model and repository for storing measurement data."""
import json
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict

class Measurement:
    """Représentation d'une mesure individuelle."""
    
    def __init__(self, tool_id: int, value: float, unit: str, 
                 status: str = "OK", note: str = "", measurement_id: int = None):
        self.measurement_id = measurement_id or int(datetime.now().timestamp() * 1000)
        self.tool_id = tool_id
        self.value = value
        self.unit = unit
        self.status = status  # OK, Alerte, Erreur
        self.note = note
        self.timestamp = datetime.now()
    
    def to_dict(self) -> dict:
        return {
            'measurement_id': self.measurement_id,
            'tool_id': self.tool_id,
            'value': self.value,
            'unit': self.unit,
            'status': self.status,
            'note': self.note,
            'timestamp': self.timestamp.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        m = cls(
            tool_id=data['tool_id'],
            value=data['value'],
            unit=data['unit'],
            status=data.get('status', 'OK'),
            note=data.get('note', ''),
            measurement_id=data.get('measurement_id'),
        )
        # Restaurer le timestamp original depuis le JSON
        ts = data.get('timestamp')
        if ts:
            try:
                m.timestamp = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass  # Garder datetime.now() par défaut
        return m
    
    def __str__(self):
        return f"{self.timestamp.strftime('%H:%M:%S')} - {self.value} {self.unit} ({self.status})"

class MeasurementsRepository:
    """Gère le stockage et la persistance des mesures."""
    
    def __init__(self, data_path: str = "config/measures.json"):
        self.data_path = data_path
        self.measurements: List[Measurement] = []
        self._load_measurements()
    
    def _load_measurements(self):
        """Charge les mesures depuis le fichier JSON."""
        if os.path.exists(self.data_path):
            with open(self.data_path, 'r', encoding='utf-8') as f:
                measures_data = json.load(f)
                self.measurements = [Measurement.from_dict(m) for m in measures_data]
    
    def _save_measurements(self):
        """Sauvegarde les mesures dans le fichier JSON."""
        os.makedirs(os.path.dirname(self.data_path) or '.', exist_ok=True)
        with open(self.data_path, 'w', encoding='utf-8') as f:
            json.dump([m.to_dict() for m in self.measurements], f, indent=2)
    
    def add_measurement(self, measurement: Measurement):
        """Ajoute une nouvelle mesure et la sauvegarde."""
        self.measurements.append(measurement)
        
        # Limiter la taille du buffer (garder les 1000 dernières mesures)
        if len(self.measurements) > 1000:
            self.measurements = self.measurements[-1000:]
        
        self._save_measurements()
    
    def get_all(self, limit: int = None) -> List[Measurement]:
        """Retourne toutes les mesures (optionnellement limité)."""
        if limit is None:
            return self.measurements
        
        # Retourner les dernières mesures
        return self.measurements[-limit:]
    
    def get_by_tool(self, tool_id: int) -> List[Measurement]:
        """Filtre les mesures par outil."""
        return [m for m in self.measurements if m.tool_id == tool_id]
    
    def get_by_date_range(self, start_date: datetime, end_date: datetime) -> List[Measurement]:
        """Filtre les mesures par plage de dates."""
        result = []
        for m in self.measurements:
            if start_date <= m.timestamp <= end_date:
                result.append(m)
        return result
    
    def get_recent(self, minutes: int = 1) -> List[Measurement]:
        """Retourne les mesures des X dernières minutes."""
        cutoff = datetime.now() - timedelta(minutes=minutes)
        return [m for m in self.measurements if m.timestamp >= cutoff]
    
    def clear_old(self, days: int = 7):
        """Supprime les mesures anciennes de plus de X jours."""
        cutoff = datetime.now() - timedelta(days=days)
        self.measurements = [m for m in self.measurements if m.timestamp >= cutoff]
        self._save_measurements()

    def clear_exported(self, count: int = None):
        """Vide le buffer après export réussi.

        Args:
            count: Nombre de mesures à supprimer depuis le début.
                   Si None, vide tout le buffer.
        """
        if count is None:
            self.measurements.clear()
        else:
            self.measurements = self.measurements[count:]
        self._save_measurements()
