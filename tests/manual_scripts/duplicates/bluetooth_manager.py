"""Bluetooth manager - Optimisé pour flux temps réel sans chiffrement."""
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, Callable, List

from .tool import Tool
from .measurement import MeasurementsRepository, Measurement  # Nouveau repo simple et rapide
from .ble_core import (
    BluetoothCore,
    DeviceCache as BleDeviceCache,
    BleConnection,
    ConnectionState,
    DeviceProfiler,
    DiscoveredDevice,
    MAX_CONCURRENT_CONNECTIONS,
)
from ..utils.encryption_manager import encryption_manager

logger = logging.getLogger(__name__)


class BluetoothManager:
    """Singleton compatible avec l'ancienne API, base sur BluetoothCore.

    Optimisé pour flux temps réel : pas de chiffrement, pas de stockage persistant.
    Les mesures sont envoyées directement vers l'export Excel/CSV.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.use_mock = False  # Detecte automatiquement par ble_core
        self.mock_manager = None  # Plus utilise — ble_core gere le fallback mock

        # Cache persistant (meme instance que ble_core)
        self.device_cache = BleDeviceCache()

        # Appareils decouverts (objets BLEDevice) — delegue a BluetoothCore
        self._scanned_devices: Dict[str, object] = {}

        # Clients connectes — delegue a BluetoothCore
        self.clients: Dict[str, object] = {}

        # Callbacks de notification par outil
        self.callbacks: Dict[str, List[Callable]] = {}

        # Scanner continu
        self._continuous_scanner: Optional[object] = None
        self.running = False

        # Outils enregistres
        self.tools: List[Tool] = []
        self._next_tool_id = 1

        # Parametres de reconnexion
        self.max_reconnect_attempts = 5
        self.base_reconnect_delay = 1.0
        self.max_reconnect_delay = 60.0

        # Reference vers le core (creee asynchrone)
        self._core: Optional[BluetoothCore] = None

        # Ensemble de taches asyncio — strong reference pour eviter GC Python 3.13+
        self._bg_tasks: set = set()

        # NOUVEAU : Repository de mesures temps reel (sans chiffrement)
        self.measurements_repo = MeasurementsRepository()

        # Export automatique en background
        self._auto_export_active = False
        self._export_filepath: Optional[str] = None
        self._export_interval_minutes: int = 1
        self._export_lock = asyncio.Lock()

    # -- Proprietes synchrones apres init asynchrone -----------------------

    @property
    def core(self) -> BluetoothCore:
        """Retourne l'instance BluetoothCore, creee si necessaire."""
        if self._core is None:
            raise RuntimeError(
                "BluetoothCore non initialise. Appelez await start() d'abord."
            )
        return self._core

    # -- Cycle de vie ------------------------------------------------------

    async def start(self):
        """Demarre le gestionnaire Bluetooth — delegue a BluetoothCore."""
        if self.running:
            return

        self.running = True
        self._core = await BluetoothCore.get_instance()
        await self._core.start()

        # Synchroniser le cache
        cached = self._core.get_cached_devices()
        for info in cached:
            self.device_cache.update(
                address=info.address,
                name=info.name,
                details={"status": info.connection_state.name}
            )

        # Copier les references aux devices pour compatibilite
        self._scanned_devices = self._core.get_cached_scanned_devices()

        logger.info("Gestionnaire Bluetooth demarre (moteur: ble_core)")

    async def stop(self):
        """Arrete tous les clients et nettoie — delegue a BluetoothCore."""
        self.running = False

        if self._core:
            await self._core.stop()
            self._core = None

        self.clients.clear()
        self._scanned_devices.clear()

        # Arreter l'export automatique si actif
        if self._auto_export_active:
            self._auto_export_active = False

        logger.info("Gestionnaire Bluetooth arrete")

    # -- Scan / Decouverte -------------------------------------------------

    async def discover_devices(self, timeout: float = 10.0) -> List[Tool]:
        """Decouvre les appareils BLE disponibles.

        Retourne les appareils decouverts sous forme d'objets Tool
        pour compatibilite avec les vues existantes.
        """
        core = await BluetoothCore.get_instance()

        # Utiliser le scan continu si deja actif
        if self._core and self._core._running:
            cached = core.get_cached_devices()
            if cached:
                tools = []
                for info in cached:
                    tool = Tool(
                        name=info.name,
                        bluetooth_uuid=info.address,
                        manufacturer=DeviceProfiler.detect_manufacturer(
                            info.manufacturer_id
                        ) or "",
                    )
                    tool.status = info.connection_state.name.lower()
                    tool.signal_strength = info.rssi
                    tools.append(tool)
                return tools

        # Sinon, scan manuel
        discovered = await core.scan(timeout=timeout)

        # Synchroniser le cache local
        for dev in discovered:
            self.device_cache.update(
                address=dev.address,
                name=dev.name or "Inconnu",
                details={"rssi": dev.rssi}
            )
            if dev.raw_device is not None:
                self._scanned_devices[dev.address] = dev.raw_device

        # Convertir en liste de Tool pour compatibilite
        return self._to_tool_list(discovered)

    def _to_tool_list(self, discovered: List[DiscoveredDevice]) -> List[Tool]:
        """Convertit une liste DiscoveredDevice en liste Tool (compatibilite)."""
        tools = []
        for dev in discovered:
            name = dev.name or f"Appareil {dev.address[:min(8, len(dev.address))]}"
            tool = Tool(
                name=name,
                bluetooth_uuid=dev.address,
                manufacturer=DeviceProfiler.detect_manufacturer(
                    dev.manufacturer_id
                ) or "",
            )
            tool.signal_strength = dev.rssi
            tools.append(tool)
        return tools

    # -- Connexion / Deconnexion -------------------------------------------

    async def connect_tool(self, tool: Tool) -> bool:
        """Etablit une connexion BLE avec un outil."""
        if tool.bluetooth_uuid in self.clients:
            return True

        core = await BluetoothCore.get_instance()
        conn = await core.connect(
            address=tool.bluetooth_uuid,
            name=tool.name,
            timeout=20.0,
        )

        if conn is not None and conn.is_connected:
            self.clients[tool.bluetooth_uuid] = conn
            self._setup_callbacks(tool, conn)
            logger.info(f"Connecte a {tool.name} ({tool.bluetooth_uuid})")
            self.device_cache.update(
                address=tool.bluetooth_uuid,
                name=tool.name,
                details={"status": "connected"}
            )
            return True
        else:
            logger.warning(f"Echec connexion {tool.name}")
            return False

    async def disconnect_tool(self, bluetooth_uuid: str) -> bool:
        """Deconnecte un outil specifique par son adresse Bluetooth."""
        if bluetooth_uuid not in self.clients:
            return True

        core = await BluetoothCore.get_instance()
        success = await core.disconnect(bluetooth_uuid)

        if bluetooth_uuid in self.clients:
            del self.clients[bluetooth_uuid]

        # Mettre à jour le statut dans la liste tools
        for t in self.tools:
            if t.bluetooth_uuid == bluetooth_uuid:
                t.status = "disconnected"
                break

        logger.info(f"Deconnecte {bluetooth_uuid}")
        return success

    def _setup_callbacks(self, tool: Tool, connection: BleConnection = None):
        """Configure le callback de notification pour traitement temps reel."""
        # UUID de caracteristique par defaut (Measurement Data)
        char_uuid = "0000ffe1-0000-1000-8000-00805f9b34fb"

        async def measurement_handler(sender: int, data: bytes):
            try:
                from .ble_core import BleDataParser
                value = BleDataParser.format_measurement(data)
                if value is not None:
                    # Creation immédiate de la mesure sans stockage persistant
                    measurement = Measurement(
                        tool_id=tool.tool_id,
                        value=value,
                        unit=tool.unit,
                        status="OK"
                    )

                    # Ajout au flux temps reel (optimise - pas de chiffrement)
                    self.measurements_repo.add_measurement(measurement)

                    # Envoi immediat vers l'export si actif
                    if self._auto_export_active:
                        await self._perform_export()

            except Exception as e:
                logger.error(f"Erreur parsing mesure {tool.name}: {e}")

        # Si on a deja la connexion, demarrer les notifications directement
        if connection and connection.is_connected:
            task = asyncio.create_task(
                connection.start_notify(char_uuid, measurement_handler)
            )
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
            logger.info(f"Notifications activees pour {tool.name}")
        else:
            logger.warning(f"Notification pour {tool.name}: pas de connexion active")

    # -- Cache & etat ------------------------------------------------------

    def get_known_devices(self) -> List[dict]:
        """Retourne tous les appareils connus (cache persistant)."""
        return self.device_cache.get_all()

    def get_connected_tools(self) -> List[Tool]:
        """Retourne la liste des outils connectes."""
        connected = []
        for t in self.tools:
            if t.bluetooth_uuid in self.clients:
                t.status = "connected"
                connected.append(t)
        return connected

    # -- Export Temps Réel (Optimise) --------------------------------------

    async def start_auto_export(self, filepath: str, interval_minutes: int = 1):
        """Active l'export automatique toutes les X minutes."""
        self._auto_export_active = True
        self._export_filepath = filepath
        self._export_interval_minutes = interval_minutes

        # Tâche background pour export périodique
        task = asyncio.create_task(self._auto_export_loop())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        logger.info(f"Export automatique active (fichier: {filepath}, interval: {interval_minutes} min)")

    async def stop_auto_export(self):
        """Desactive l'export automatique."""
        self._auto_export_active = False
        logger.info("Export automatique desactive")

    async def _auto_export_loop(self):
        """Boucle d'export automatique en background."""
        while self.running and self._auto_export_active:
            await asyncio.sleep(self._export_interval_minutes * 60)
            if self.running and self._auto_export_active:
                await self._perform_export()

    async def _perform_export(self):
        """Exporte les mesures et vide le buffer."""
        async with self._export_lock:
            if not self._export_filepath:
                return

            # Format du nom de fichier : chemin_base_timestamp.csv/xlsx
            base_path = self._export_filepath
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            ext = 'csv' if base_path.endswith('.csv') else 'xlsx'
            filepath = f"{base_path}_{timestamp}.{ext}"

            # Export vers le fichier (avec ou sans chiffrement selon config)
            measurements = self.measurements_repo.get_all()  # Liste d'objets Measurement
            
            # Convertir les mesures en dict pour EncryptionManager
            data_dicts = [m.to_dict() for m in measurements]
            
            # Utiliser EncryptionManager pour l'export
            result_filepath = await encryption_manager.export_file(data_dicts, filepath)
            
            if result_filepath:
                logger.info(f"Export realise : {result_filepath}")
                # Suppression des mesures exportees (buffer vide)
                self.measurements_repo.clear_old()
            else:
                logger.error(f"Echec de l'export vers {filepath}")

    # -- Diagnostics -------------------------------------------------------

    def get_diagnostics(self) -> dict:
        """Retourne les diagnostics du systeme Bluetooth."""
        if self._core:
            return self._core.get_diagnostics()
        return {"running": self.running, "core": None}

