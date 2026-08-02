"""Simulateur Bluetooth réaliste pour tests sans matériel physique."""
import asyncio
from typing import Dict, List, Callable, Optional, Any
import random
from datetime import datetime

class MockBleDevice:
    """Simulation d'un appareil BLE industriel."""
    
    def __init__(self, name: str, address: str, device_type: str):
        self.name = name
        self.address = address
        self.device_type = device_type  # 'rule', 'caliper', 'microscope', 'roughness'
        self.is_connected = False
        self.signal_strength = random.randint(60, 95)
        
    def to_dict(self):
        return {
            'name': self.name,
            'address': self.address,
            'device_type': self.device_type,
            'is_connected': self.is_connected,
            'signal_strength': self.signal_strength
        }

class MockBleakClient:
    """Simulation d'un client BLE (remplace BleakClient réel)."""
    
    def __init__(self, address: str):
        self.address = address
        self.is_connected = False
        # NB: device_name est une @property (ligne 105) dérivée de l'adresse
        self.services: Dict[str, 'MockService'] = {}
        
        # Initialiser les services selon le type d'appareil
        self._initialize_mock_services()
    
    async def connect(self) -> bool:
        """Simule une connexion BLE."""
        await asyncio.sleep(0.5)  # Délai de simulation
        self.is_connected = True
        return True
    
    async def disconnect(self):
        """Simule une déconnexion BLE."""
        self.is_connected = False
        await asyncio.sleep(0.3)
    
    async def get_services(self) -> List['MockService']:
        """Retourne la liste des services simulés."""
        return list(self.services.values())
    
    async def read_gatt_char(self, uuid: str) -> bytes:
        """Lit une caractéristique et retourne ses données simulées."""
        if not self.is_connected:
            raise ConnectionError("Non connecté")
        
        # Simuler des données selon l'UUID (simplifié pour la démo)
        if "2a29" in uuid:  # Manufacturer Name String
            return b"SimulatedToolXYZ"
        elif "2a24" in uuid:  # Model Number String
            return f"{self.device_name}_V1.0".encode('utf-8')
        else:
            # Données de mesure aléatoires
            value = random.uniform(0.0, 5.0)
            return f"{value:.3f}".encode('utf-8')
    
    def _initialize_mock_services(self):
        """Initialise les services BLE simulés."""
        self.services = {
            "00001800-0000-1000-8000-00805f9b34fb": MockService("Device Information"),
            "0000180d-0000-1000-8000-00805f9b34fb": MockService("Battery Service"),
            "0000ffe0-0000-1000-8000-00805f9b34fb": MockService("Measurement Data")
        }
        
        # Ajouter les caractéristiques simulées
        for service in self.services.values():
            if "Device Information" in service.name:
                service.characteristics.append(MockCharacteristic(
                    uuid="00002a29-0000-1000-8000-00805f9b34fb",
                    name="Manufacturer Name",
                    properties=["Read"]
                ))
            elif "Measurement Data" in service.name:
                # UUID personnalisé pour les mesures
                service.characteristics.append(MockCharacteristic(
                    uuid="0000ffe1-0000-1000-8000-00805f9b34fb",
                    name="Measurement Value",
                    properties=["Read", "Notify"],
                    value_provider=self._generate_measurement
                ))

    def _generate_measurement(self):
        """Génère une valeur de mesure aléatoire."""
        # Valeur différente selon le type d'appareil
        if self.device_name.startswith("A"):  # Règle 500mm
            return round(random.uniform(0.0, 2.0), 3)
        elif self.device_name.startswith("F") or "micro" in self.device_name.lower():  # Micromètre
            return round(random.uniform(0.001, 0.01), 4)
        elif "caliper" in self.device_name.lower():  # Pied à coulisse
            return round(random.uniform(0.1, 300.0), 2)
        else:  # Rugosimètre
            return round(random.uniform(0.01, 5.0), 2)

    @property
    def device_name(self) -> str:
        return self.address.split('-')[0].upper() if '-' in self.address else "MOCK"

class MockService:
    """Simulation d'un service BLE."""
    
    def __init__(self, name: str):
        self.name = name
        self.uuid = "0000180d-0000-1000-8000-00805f9b34fb"  # UUID standard simulé
        self.characteristics: List['MockCharacteristic'] = []

class MockCharacteristic:
    """Simulation d'une caractéristique BLE."""
    
    def __init__(self, uuid: str, name: str, properties: List[str], value_provider: Optional[Callable] = None):
        self.uuid = uuid
        self.name = name
        self.properties = [type(p).__name__ if not isinstance(p, str) else p for p in properties]
        self.value_provider = value_provider
    
    def get_value(self):
        """Retourne la valeur simulée."""
        if self.value_provider:
            return self.value_provider()
        return random.randint(0, 100)

class MockBleakScanner:
    """Simule le scan BLE d'appareils disponibles."""
    
    def __init__(self):
        # Liste d'appareils simulés (représentant les outils industriels)
        self.mock_devices = [
            MockBleDevice("Règle 500mm", "A1-B2-C3-D4-E5-F6", "rule"),
            MockBleDevice("Micromètre Digital", "F1-E2-D3-C4-B5-A6", "microscope"),
            MockBleDevice("Pied à coulisse BT", "11-22-33-44-55-66", "caliper"),
            MockBleDevice("Rugosimètre Pro", "AA-BB-CC-DD-EE-FF", "roughness")
        ]
    
    async def discover(self, timeout: float = 10.0):
        """Retourne la liste des appareils découverts."""
        await asyncio.sleep(2)  # Délai de scan simulé
        return [(d.address, d) for d in self.mock_devices]

class MockBleakManager:
    """Gère le cycle de vie du simulateur BLE."""
    
    def __init__(self):
        self.scanner = MockBleakScanner()
        self.clients: Dict[str, MockBleakClient] = {}
        self.running = False
    
    async def start(self):
        """Démare le simulateur."""
        self.running = True
        print("🟢 Simulateur BLE démarré")
    
    async def stop(self):
        """Arrête le simulateur."""
        self.running = False
        self.clients.clear()
        print("🔴 Simulateur BLE arrêté")
    
    async def get_devices(self) -> List[MockBleDevice]:
        """Retourne les appareils disponibles."""
        return self.scanner.mock_devices
    
    async def connect(self, address: str) -> Optional[MockBleakClient]:
        """Connecte un appareil simulé."""
        if address in self.clients:
            return self.clients[address]
        
        client = MockBleakClient(address)
        await client.connect()
        self.clients[address] = client
        return client
    
    async def disconnect(self, address: str):
        """Déconnecte un appareil."""
        if address in self.clients:
            client = self.clients[address]
            await client.disconnect()
            del self.clients[address]

# Singleton du simulateur
_simulator_instance = None

def get_ble_simulator():
    """Retourne l'instance singleton du simulateur BLE."""
    global _simulator_instance
    if _simulator_instance is None:
        _simulator_instance = MockBleakManager()
    return _simulator_instance
