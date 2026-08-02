"""Tools tab — Gestion interactive des outils de mesure.

Fonctionnalites :
  - Ajout/edition/suppression d'outils via dialogue enrichi
  - Scan BLE integre avec grille d'appareils decouverts
  - Profilage automatique (fabricant, type d'appareil)
  - Connexion/deconnexion directe depuis la liste
  - Affichage RSSI en temps reel
"""

from __future__ import annotations

import os
import asyncio
import logging
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QMetaObject
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QDialog,
    QLineEdit,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QGridLayout,
    QSizePolicy,
)
from PySide6.QtGui import QFont, QShortcut, QKeySequence

from src.models.tool import Tool, ToolsRepository
from src.models.bluetooth_manager import BluetoothManager
from src.utils.qt_async_executor import create_task
from src.utils.sound_manager import SoundManager
from src.views.widgets import (
    DeviceCard,
    ScanProgressBar,
    EmptyState,
    StatusState,
    SignalStrengthBars,
    ShortcutsFooter,
)

logger = logging.getLogger(__name__)


# ===================================================================
# Dialogue d'ajout/edition enrichi
# ===================================================================


class AddEditToolDialog(QDialog):
    """Dialogue pour ajouter/editer un outil avec scan BLE integre.

    L'UUID Bluetooth est découvert automatiquement par scan BLE.
    L'utilisateur ne doit jamais fournir d'UUID manuellement.
    """

    def __init__(self, tool: Optional[Tool] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajouter / Modifier un outil")
        self.setMinimumSize(520, 700)

        self.tool_data = tool
        self.discovered_devices: List[Tool] = []
        self.selected_device_uuid: Optional[str] = None
        self.selected_device_name: Optional[str] = None
        self.bluetooth_manager = BluetoothManager()
        self._current_scan_task = None

        self.setup_ui()

        if tool:
            self._populate(tool)

    def setup_ui(self):
        """Configure le formulaire amélioré."""
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        # --- Nom ---
        self._add_field_label(layout, "Nom de l'outil")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("ex: Pied a coulisse etage")
        self.name_input.setStyleSheet("""
            QLineEdit {
                padding: 12px; border: 1px solid #444;
                border-radius: 4px; background-color: #2B2B3D;
                color: white; font-size: 15px;
            }
        """)
        layout.addWidget(self.name_input)

        # --- Type de donnee ---
        self._add_field_label(layout, "Type de donnee")
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Numérique", "String", "Booléen"])
        self.type_combo.setStyleSheet("""
            QComboBox {
                padding: 12px; border: 1px solid #444;
                border-radius: 4px; background-color: #2B2B3D;
                color: white; font-size: 15px;
            }
        """)
        layout.addWidget(self.type_combo)

        # --- Unite de mesure ---
        self._add_field_label(layout, "Unite de mesure")
        unit_layout = QHBoxLayout()
        unit_layout.setSpacing(10)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(Tool.UNIT_OPTIONS)
        self.unit_combo.setToolTip("Symbole de l'unite de mesure")
        self.unit_combo.setStyleSheet("""
            QComboBox {
                padding: 12px; border: 1px solid #444;
                border-radius: 4px; background-color: #2B2B3D;
                color: white; font-size: 15px;
            }
            QComboBox:hover { border: 1px solid #2196F3; }
            QComboBox QAbstractItemView {
                background-color: #2B2B3D; color: white;
                selection-background-color: #2196F3;
            }
        """)
        self.unit_combo.currentTextChanged.connect(self._on_unit_changed)
        unit_layout.addWidget(self.unit_combo)

        self.multiplier_combo = QComboBox()
        self.multiplier_combo.setToolTip("Facteur d'echelle applique aux donnees recues")
        self.multiplier_combo.setStyleSheet("""
            QComboBox {
                padding: 12px; border: 1px solid #444;
                border-radius: 4px; background-color: #2B2B3D;
                color: white; font-size: 15px;
            }
            QComboBox:hover { border: 1px solid #FF9800; }
            QComboBox QAbstractItemView {
                background-color: #2B2B3D; color: white;
                selection-background-color: #FF9800;
            }
        """)
        unit_layout.addWidget(self.multiplier_combo)

        layout.addLayout(unit_layout)

        # --- Séparateur ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #3D3D50;")
        layout.addWidget(sep)

        # --- Association Bluetooth ---
        self._add_field_label(layout, "Association Bluetooth", "#2196F3")

        # Bouton scan avec indicateur
        scan_layout = QHBoxLayout()
        self.scan_ble_btn = QPushButton(" Scanner les appareils BLE")
        self.scan_ble_btn.setToolTip(
            "Lancer un scan pour decouvrir les appareils BLE a proximite"
        )
        self.scan_ble_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3; color: white;
                padding: 12px 20px; border: none;
                border-radius: 4px; font-size: 15px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1E88E5; }
            QPushButton:disabled { background-color: #3D3D50; color: #757575; }
        """)
        self.scan_ble_btn.clicked.connect(self._scan_bluetooth)
        scan_layout.addWidget(self.scan_ble_btn)

        self.scan_status = QLabel("")
        self.scan_status.setStyleSheet("color: #757575; font-size: 13px;")
        scan_layout.addWidget(self.scan_status)
        scan_layout.addStretch()
        layout.addLayout(scan_layout)

        # Liste d'appareils decouverts (cartes)
        self._add_field_label(layout, "Appareils a proximite", "#A0A0A0")
        self.devices_container = QVBoxLayout()
        self.devices_container.setSpacing(6)
        layout.addLayout(self.devices_container)

        # Aucun appareil par defaut
        empty = QLabel("Lancez un scan pour decouvrir les appareils BLE.")
        empty.setStyleSheet("color: #757575; font-size: 12px; padding: 8px;")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.devices_container.addWidget(empty)

        # --- Adresse MAC secondaire (backup) ---
        self._add_field_label(layout, "Adresse secondaire (backup)", "#FF9800")
        self.backup_uuid_input = QLineEdit()
        self.backup_uuid_input.setPlaceholderText("XX:XX:XX:XX:XX:XX (optionnel)")
        self.backup_uuid_input.setStyleSheet("""
            QLineEdit {
                padding: 12px; border: 1px solid #444;
                border-radius: 4px; background-color: #2B2B3D;
                color: #FF9800; font-size: 13px;
            }
        """)
        layout.addWidget(self.backup_uuid_input)

        layout.addStretch()

        # --- Boutons d'action ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        cancel_btn = QPushButton("Annuler")
        cancel_btn.setToolTip("Annuler les modifications (Esc)")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #757575; color: white;
                padding: 12px 28px; border: none;
                border-radius: 4px; font-size: 15px;
            }
            QPushButton:hover { background-color: #616161; }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        btn_layout.addStretch()

        save_btn = QPushButton("Sauvegarder")
        save_btn.setToolTip("Enregistrer l'outil (Ctrl+Enter)")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
                padding: 12px 28px; border: none;
                border-radius: 4px; font-size: 15px; font-weight: bold;
            }
            QPushButton:hover { background-color: #45A049; }
        """)
        save_btn.clicked.connect(self.accept)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # Utilitaires UI
    # ------------------------------------------------------------------

    def _add_field_label(self, layout, text: str, color: str = "white"):
        """Ajoute un label de champ."""
        label = QLabel(text)
        label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px;")
        label.setContentsMargins(0, 8, 0, 4)
        layout.addWidget(label)

    def _on_unit_changed(self, unit: str):
        """Met a jour les multiplicateurs disponibles selon l'unite selectionnee."""
        prev = self.multiplier_combo.currentData()
        self.multiplier_combo.clear()
        multipliers = Tool.UNIT_MULTIPLIER_MAP.get(unit, Tool.MULTIPLIER_OPTIONS)
        for m in multipliers:
            if m >= 0.01:
                label = f"{m}"
            else:
                label = str(m)
            self.multiplier_combo.addItem(label, m)
        # Restaurer la valeur precedente si possible
        idx = self.multiplier_combo.findData(prev)
        if idx >= 0:
            self.multiplier_combo.setCurrentIndex(idx)

    def _populate(self, tool: Tool):
        """Pre-remplit le formulaire avec un outil existant."""
        self.name_input.setText(tool.name)
        type_map = {"Numérique": 0, "String": 1, "Booléen": 2}
        idx = type_map.get(tool.data_type, 0)
        self.type_combo.setCurrentIndex(idx)
        # Unite et multiplicateur
        unit = tool.unit_symbol or tool.unit or "mm"
        idx_u = self.unit_combo.findText(unit)
        if idx_u >= 0:
            self.unit_combo.setCurrentIndex(idx_u)
        self._on_unit_changed(self.unit_combo.currentText())
        idx_m = self.multiplier_combo.findData(tool.multiplier)
        if idx_m >= 0:
            self.multiplier_combo.setCurrentIndex(idx_m)
        self.selected_device_uuid = tool.bluetooth_uuid
        self.backup_uuid_input.setText(tool.backup_bluetooth_uuid or "")

    # ------------------------------------------------------------------
    # Scan BLE
    # ------------------------------------------------------------------

    def _scan_bluetooth(self):
        """Lance un scan BLE asynchrone."""
        self.scan_ble_btn.setEnabled(False)
        self.scan_ble_btn.setText("Scan en cours...")
        self.scan_status.setText("Recherche d'appareils...")

        create_task(self._do_scan())

    async def _do_scan(self):
        try:
            devices = await self.bluetooth_manager.discover_devices(timeout=5.0)
            self.discovered_devices = devices
            QTimer.singleShot(0, self._on_scan_done)
        except asyncio.CancelledError:
            logger.info("Scan BLE outils annule")
            raise
        except Exception as e:
            QTimer.singleShot(0, lambda msg=str(e): self._on_scan_error(msg))

    def _on_scan_done(self):
        """Met a jour l'interface apres le scan."""
        self.scan_ble_btn.setEnabled(True)
        self.scan_ble_btn.setText(" Scanner les appareils BLE")

        # Nettoyer l'ancienne liste
        self._clear_layout(self.devices_container)

        if not self.discovered_devices:
            self.scan_status.setText("Aucun appareil trouve.")
            empty = QLabel("Aucun appareil BLE trouve a proximite.")
            empty.setStyleSheet("color: #FF9800; font-size: 12px; padding: 8px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.devices_container.addWidget(empty)
            return

        self.scan_status.setText(
            f"{len(self.discovered_devices)} appareil(s) trouve(s) — "
            "Cliquez pour selectionner"
        )

        for device in self.discovered_devices:
            addr = device.bluetooth_uuid or ""
            name = device.name or "Appareil inconnu"

            # Carte selectionnable
            card = DeviceCard(address=addr, name=name)
            card.set_info(
                address=addr,
                name=name,
                rssi=getattr(device, "rssi", None),
                device_type="generic",
            )
            card.set_state(StatusState.DISCOVERED)

            # Connecter le clic comme selection
            card.connect_requested.connect(
                lambda a=addr, n=name: self._select_device(a, n)
            )
            # Cacher le bouton action
            card.action_btn.hide()

            self.devices_container.addWidget(card)

        # Marquer la selection courante si existante
        self._highlight_selection()

    def _on_scan_error(self, error_msg: str):
        self.scan_ble_btn.setEnabled(True)
        self.scan_ble_btn.setText(" Scanner les appareils BLE")
        self.scan_status.setText(f"Erreur: {error_msg}")

    # ------------------------------------------------------------------
    # Selection d'appareil
    # ------------------------------------------------------------------

    def _select_device(self, address: str, name: str):
        """Selectionne un appareil dans la liste."""
        self.selected_device_uuid = address
        self.selected_device_name = name
        self.scan_status.setText(f"Selectionne: {name}")
        self._highlight_selection()

    def _highlight_selection(self):
        """Met en evidence la carte selectionnee."""
        for i in range(self.devices_container.count()):
            item = self.devices_container.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if isinstance(widget, DeviceCard):
                    selected = (widget.address == self.selected_device_uuid)
                    widget.setStyleSheet(
                        "DeviceCard { background-color: #1E3A1E; "
                        "border: 2px solid #4CAF50; border-radius: 8px; }"
                        if selected else ""
                    )

    # ------------------------------------------------------------------
    # Recuperation des donnees
    # ------------------------------------------------------------------

    def get_tool_data(self) -> dict:
        """Retourne les donnees saisies dans le formulaire."""
        backup_uuid = self.backup_uuid_input.text().strip()
        unit_symbol = self.unit_combo.currentText()
        multiplier = self.multiplier_combo.currentData() or 1.0
        type_display = self.type_combo.currentText()
        return {
            "name": self.name_input.text(),
            "data_type": DATA_TYPE_REVERSE.get(type_display, "numeric"),
            "unit": unit_symbol,
            "unit_symbol": unit_symbol,
            "multiplier": multiplier,
            "bluetooth_uuid": self.selected_device_uuid,
            "backup_bluetooth_uuid": backup_uuid if backup_uuid else None,
            "photo_path": getattr(self, "selected_photo", None),
        }

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            else:
                sub = item.layout()
                if sub:
                    self._clear_layout(sub)


# ===================================================================
# Dialogue de configuration rapide d'un outil
# ===================================================================


DATA_TYPE_DISPLAY = {"numeric": "Numerique", "string": "Texte", "bool": "Booleen"}
DATA_TYPE_REVERSE = {v: k for k, v in DATA_TYPE_DISPLAY.items()}


class ToolConfigDialog(QDialog):
    """Dialogue de configuration rapide : unite, multiplicateur, type, nom."""

    def __init__(self, tool: Tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.setWindowTitle(f"Configurer - {tool.name}")
        self.setMinimumWidth(380)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog { background-color: #1E1E2E; }
            QLabel { color: white; font-size: 13px; }
            QComboBox {
                padding: 8px; border: 1px solid #444;
                border-radius: 4px; background-color: #2B2B3D;
                color: white; font-size: 14px;
            }
            QComboBox:hover { border: 1px solid #2196F3; }
            QComboBox QAbstractItemView {
                background-color: #2B2B3D; color: white;
                selection-background-color: #2196F3;
            }
            QLineEdit {
                padding: 8px; border: 1px solid #444;
                border-radius: 4px; background-color: #2B2B3D;
                color: white; font-size: 14px;
            }
            QLineEdit:focus { border: 1px solid #2196F3; }
        """)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Nom
        lbl = QLabel("Nom de l'outil:")
        lbl.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl)
        self.name_input = QLineEdit(self.tool.name)
        layout.addWidget(self.name_input)

        # Type
        lbl = QLabel("Type de donnee:")
        lbl.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Numerique", "Texte", "Booleen"])
        current_type = DATA_TYPE_DISPLAY.get(self.tool.data_type, self.tool.data_type)
        idx = self.type_combo.findText(current_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        layout.addWidget(self.type_combo)

        # Unite
        lbl = QLabel("Unite de mesure:")
        lbl.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(Tool.UNIT_OPTIONS)
        idx = self.unit_combo.findText(self.tool.unit)
        if idx >= 0:
            self.unit_combo.setCurrentIndex(idx)
        self.unit_combo.currentTextChanged.connect(self._on_unit_changed)
        layout.addWidget(self.unit_combo)

        # Multiplicateur
        lbl = QLabel("Multiplicateur:")
        lbl.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl)
        self.multiplier_combo = QComboBox()
        self._populate_multipliers(self.tool.unit)
        layout.addWidget(self.multiplier_combo)

        # Boutons
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Annuler")
        cancel_btn.setStyleSheet("""
            QPushButton { background-color: #757575; color: white; padding: 8px 20px; border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #616161; }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        save_btn = QPushButton("Enregistrer")
        save_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; padding: 8px 20px; border: none; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #45A049; }
        """)
        save_btn.clicked.connect(self.accept)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _on_unit_changed(self, unit_text):
        self._populate_multipliers(unit_text)

    def _populate_multipliers(self, unit_text):
        self.multiplier_combo.clear()
        multipliers = Tool.UNIT_MULTIPLIER_MAP.get(unit_text, [1.0])
        for m in multipliers:
            self.multiplier_combo.addItem(str(m), m)
        idx = self.multiplier_combo.findData(self.tool.multiplier)
        if idx >= 0:
            self.multiplier_combo.setCurrentIndex(idx)

    def get_data(self) -> dict:
        type_display = self.type_combo.currentText()
        return {
            "name": self.name_input.text().strip() or self.tool.name,
            "data_type": DATA_TYPE_REVERSE.get(type_display, "numeric"),
            "unit": self.unit_combo.currentText(),
            "unit_symbol": self.unit_combo.currentText(),
            "multiplier": self.multiplier_combo.currentData() or 1.0,
        }


# ===================================================================
# Onglet outils principal
# ===================================================================


class ToolsTab(QWidget):
    """Onglet de gestion des outils avec interface visuelle enrichie."""

    def __init__(self, parent=None, auth_manager=None):
        super().__init__(parent)

        # Gestionnaire d'authentification pour le controle d'acces
        self.auth_manager = auth_manager

        # Repository persistant
        app_dir = os.path.join(os.path.expanduser("~"), ".application_mesure")
        config_path = os.path.join(app_dir, "tools.json")
        self.repository = ToolsRepository(config_path=config_path)
        self.tools = self.repository.get_all()

        self.bluetooth_manager = BluetoothManager()
        self._tool_cards: dict[str, DeviceCard] = {}

        self.setup_ui()

        # Raccourcis clavier
        sc_add = QShortcut(QKeySequence("Ctrl+N"), self)
        sc_add.activated.connect(self._add_tool)

        # Raccourci Suppression (accessible uniquement si superviseur)
        sc_delete = QShortcut(QKeySequence("Delete"), self)
        sc_delete.activated.connect(self._delete_selected_tool)

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 16, 20, 16)

        # --- En-tete ---
        header = QHBoxLayout()

        title = QLabel("Gestion des Outils")
        title_font = QFont("Segoe UI", 24, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: white;")
        header.addWidget(title)

        header.addStretch()

        # Bouton ajouter (superviseur seulement)
        self.add_btn = QPushButton(" + Ajouter un outil")
        self.add_btn.setToolTip(
            "Ajouter un nouvel outil de mesure (Ctrl+N)"
        )
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
                padding: 12px 20px; border: none;
                border-radius: 6px; font-size: 15px; font-weight: bold;
            }
            QPushButton:hover { background-color: #45A049; }
        """)
        self.add_btn.clicked.connect(self._add_tool)
        header.addWidget(self.add_btn)

        layout.addLayout(header)

        # --- Barre d'outils / stats ---
        stats_bar = QHBoxLayout()
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #A0A0A0; font-size: 14px;")
        stats_bar.addWidget(self.stats_label)
        stats_bar.addStretch()
        layout.addLayout(stats_bar)

        # --- Zone de scroll ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea { background-color: transparent; border: none; }
            QScrollBar:vertical {
                background: #1E1E2E; width: 8px; border: none;
            }
            QScrollBar::handle:vertical {
                background: #3D3D50; border-radius: 4px; min-height: 30px;
            }
        """)

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: transparent;")

        # Layout en grille pour les outils
        self._grid_layout = QVBoxLayout(scroll_content)
        self._grid_layout.setSpacing(8)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Lexique de raccourcis clavier
        layout.addWidget(ShortcutsFooter([
            ("Ctrl+N", "Ajouter un outil"),
            ("Delete", "Supprimer l'outil selectionne"),
            ("Ctrl+Maj+L", "Deconnexion"),
        ]))

        # Premier rendu
        self._refresh()

        # Appliquer les permissions UI selon le role
        self.apply_permissions()

    # ------------------------------------------------------------------
    # Rendu de la liste
    # ------------------------------------------------------------------

    def _refresh(self):
        """Rafraichit la liste des outils."""
        self._clear_layout(self._grid_layout)
        self._tool_cards.clear()

        self.tools = self.repository.get_all()
        total = len(self.tools)

        is_supervisor = self._is_supervisor()

        if not self.tools:
            empty = EmptyState("Aucun outil configure")
            empty.rescan_requested.connect(self._add_tool)
            empty.scan_btn.setText("Ajouter un premier outil")
            empty.scan_btn.setVisible(is_supervisor)
            self._grid_layout.addWidget(empty)
            # Mettre a jour les stats
            self.stats_label.setText("0 outil(s)")
            return

        # Compter les connectes
        connected = 0
        try:
            connected_tools = self._get_connected_tools()
            connected = len(connected_tools)
        except Exception:
            pass

        self.stats_label.setText(
            f"{total} outil(s) — {connected} connecte(s)"
        )

        for tool_obj in self.tools:
            card = self._create_tool_card(tool_obj, is_supervisor)
            self._grid_layout.addWidget(card)

    def _create_tool_card(self, tool_obj: Tool, is_supervisor: bool) -> QFrame:
        """Cree une carte graphique pour un outil avec support des deux MAC."""
        from PySide6.QtWidgets import QSizePolicy

        main_uuid = tool_obj.bluetooth_uuid or ""
        backup_uuid = tool_obj.backup_bluetooth_uuid or ""

        # Verifier si l'une des adresses est connectee
        is_connected = False
        active_uuid = ""
        try:
            for ct in self._get_connected_tools():
                if ct.bluetooth_uuid == main_uuid:
                    is_connected = True
                    active_uuid = main_uuid
                    break
                if backup_uuid and ct.bluetooth_uuid == backup_uuid:
                    is_connected = True
                    active_uuid = backup_uuid
                    break
        except Exception:
            pass

        # --- Carte principale ---
        card = QFrame()
        card.setStyleSheet("""
            QFrame#ToolCard {
                background-color: #1E1E2E;
                border-radius: 8px;
                padding: 0px;
                margin-bottom: 5px;
            }
            QFrame#ToolCard:hover {
                background-color: #252538;
                border: 1px solid #3D3D50;
            }
        """)
        card.setObjectName("ToolCard")
        card.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QHBoxLayout(card)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 8, 12, 8)

        # Indicateur de statut
        from src.views.widgets.widgets import StatusIndicator, StatusState, SignalStrengthBars
        status_indicator = StatusIndicator(card, size=14)
        state = StatusState.CONNECTED if is_connected else StatusState.DISCOVERED
        status_indicator.set_state(state)
        layout.addWidget(status_indicator)

        # Infos outil (nom + MACs)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_label = QLabel(tool_obj.name)
        name_label.setStyleSheet("font-size: 15px; font-weight: bold; color: white;")
        info_layout.addWidget(name_label)

        # Type + unite
        DATA_TYPE_DISPLAY = {"numeric": "Numerique", "string": "Texte", "bool": "Booleen"}
        type_display = DATA_TYPE_DISPLAY.get(tool_obj.data_type, tool_obj.data_type)
        mult_str = f" x{tool_obj.multiplier}" if tool_obj.multiplier != 1.0 else ""
        type_label = QLabel(f"{type_display} - {tool_obj.unit_symbol}{mult_str}")
        type_label.setStyleSheet("font-size: 12px; color: #A0A0A0;")
        info_layout.addWidget(type_label)

        # Adresse MAC principale
        primary_label = QLabel(f"Principal: {main_uuid if main_uuid else 'Non defini'}")
        primary_label.setStyleSheet(
            "font-size: 12px; color: #4CAF50;" if main_uuid and main_uuid == active_uuid
            else "font-size: 12px; color: #757575;"
        )
        info_layout.addWidget(primary_label)

        # Adresse MAC secondaire
        if backup_uuid:
            backup_label = QLabel(f"Secondaire: {backup_uuid}")
            backup_label.setStyleSheet(
                "font-size: 12px; color: #FF9800;" if backup_uuid == active_uuid
                else "font-size: 12px; color: #757575;"
            )
            info_layout.addWidget(backup_label)
        else:
            backup_label = QLabel("Secondaire: Non defini")
            backup_label.setStyleSheet("font-size: 12px; color: #555;")
            info_layout.addWidget(backup_label)

        layout.addLayout(info_layout)
        layout.addStretch()

        # --- Actions ---
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)

        # Selection de l'adresse active
        mac_selector = QComboBox()
        mac_selector.addItem("Principal", main_uuid) if main_uuid else None
        if backup_uuid:
            mac_selector.addItem("Secondaire", backup_uuid)
        # Preselectionner l'adresse active
        active_idx = mac_selector.findData(active_uuid)
        if active_idx >= 0:
            mac_selector.setCurrentIndex(active_idx)
        mac_selector.setStyleSheet("""
            QComboBox {
                background-color: #2B2B3D; color: white;
                padding: 4px 8px; border: 1px solid #444;
                border-radius: 4px; font-size: 12px;
            }
            QComboBox::drop-down { border: none; }
        """)
        btn_layout.addWidget(mac_selector)

        # Bouton connecter/deconnecter
        connect_btn = QPushButton(
            "Deconnecter" if is_connected else "Connecter"
        )
        connect_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {'#F44336' if is_connected else '#4CAF50'};
                color: white; padding: 8px 18px; border: none;
                border-radius: 4px; font-size: 14px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {'#D32F2F' if is_connected else '#45A049'}; }}
        """)
        connect_btn.clicked.connect(
            lambda checked, t=tool_obj, cb=mac_selector: self._on_tool_connect(t, cb)
        )
        btn_layout.addWidget(connect_btn)

        # Bouton scan par outil
        scan_btn = QPushButton("Scan")
        scan_btn.setToolTip("Rechercher cet outil en Bluetooth")
        scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3; color: white;
                padding: 4px 12px; border: none;
                border-radius: 4px; font-size: 12px;
            }
            QPushButton:hover { background-color: #1E88E5; }
        """)
        scan_btn.clicked.connect(
            lambda checked, t=tool_obj: self._scan_single_tool(t)
        )
        btn_layout.addWidget(scan_btn)

        # Bouton configurer
        config_btn = QPushButton("Configurer")
        config_btn.setToolTip("Modifier l'unite, le type et le multiplicateur")
        config_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800; color: white;
                padding: 4px 12px; border: none;
                border-radius: 4px; font-size: 12px;
            }
            QPushButton:hover { background-color: #F57C00; }
        """)
        config_btn.clicked.connect(
            lambda checked, t=tool_obj: self._configure_tool(t)
        )
        btn_layout.addWidget(config_btn)

        # Bouton supprimer (superviseur seulement)
        if is_supervisor:
            delete_btn = QPushButton("Supprimer")
            delete_btn.setStyleSheet("""
                QPushButton {
                    background-color: #F44336; color: white;
                    padding: 4px 12px; border: none;
                    border-radius: 4px; font-size: 12px;
                }
                QPushButton:hover { background-color: #D32F2F; }
            """)
            delete_btn.clicked.connect(
                lambda checked, t=tool_obj: self._delete_tool(t)
            )
            btn_layout.addWidget(delete_btn)

        layout.addLayout(btn_layout)

        return card

    # ------------------------------------------------------------------
    # Actions cartes
    # ------------------------------------------------------------------

    def _on_tool_connect(self, tool_obj: Tool, mac_selector: QComboBox):
        """Connecte/deconnecte un outil avec l'adresse selectionnee."""
        selected_uuid = mac_selector.currentData()
        if not selected_uuid:
            SoundManager.instance().play_error_async()
            QMessageBox.warning(self, "Erreur",
                                "Aucune adresse MAC configuree pour cet outil.")
            return

        # Verifier si deja connecte
        try:
            for ct in self._get_connected_tools():
                if ct.bluetooth_uuid == selected_uuid:
                    # Deconnecter
                    create_task(self._do_disconnect_tool(selected_uuid))
                    return
        except Exception:
            pass

        # Connecter
        tool = Tool(name=tool_obj.name, bluetooth_uuid=selected_uuid)
        create_task(self._do_connect_tool(tool))

    def _on_card_connect(self, address: str, name: str):
        """Connecte un outil depuis sa carte."""
        tool = Tool(name=name, bluetooth_uuid=address)
        card = self._tool_cards.get(address)
        if card:
            card.set_state(StatusState.CONNECTING)

        create_task(self._do_connect_tool(tool))

    async def _do_connect_tool(self, tool: Tool):
        try:
            # Essayer l'adresse principale, puis le backup si disponible
            success = await self.bluetooth_manager.connect_tool(tool)
            if success:
                QTimer.singleShot(0, self._refresh)
            else:
                # Essayer le backup si disponible
                backup = getattr(tool, 'backup_bluetooth_uuid', None)
                if backup and backup != tool.bluetooth_uuid:
                    tool_backup = Tool(name=tool.name, bluetooth_uuid=backup)
                    success = await self.bluetooth_manager.connect_tool(tool_backup)
                    if success:
                        QTimer.singleShot(0, self._refresh)
                        return
                addr = tool.bluetooth_uuid or ""
                QTimer.singleShot(0, lambda a=addr: self._set_card_error(a))
        except asyncio.CancelledError:
            logger.info("Connexion outil annulee: %s", tool.bluetooth_uuid)
            raise
        except Exception as e:
            logger.error("Erreur connexion outil: %s", e)

    def _on_card_disconnect(self, address: str):
        """Deconnecte un outil depuis sa carte."""
        create_task(self._do_disconnect_tool(address))

    async def _do_disconnect_tool(self, address: str):
        try:
            await self.bluetooth_manager.disconnect_tool(address)
            QTimer.singleShot(0, self._refresh)
        except Exception as e:
            logger.error("Erreur deconnexion outil: %s", e)

    def _set_card_error(self, address: str):
        card = self._tool_cards.get(address)
        if card:
            card.set_state(StatusState.ERROR)

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    def _is_supervisor(self) -> bool:
        """Verifie si l'utilisateur courant est superviseur."""
        return (self.auth_manager is not None
                and self.auth_manager.current_user is not None
                and self.auth_manager.current_user.role == "supervision")

    def apply_permissions(self):
        """Applique les permissions UI selon le role de l'utilisateur."""
        is_supervisor = self._is_supervisor()
        self.add_btn.setVisible(is_supervisor)
        # Le bouton scan BLE reste accessible aux deux roles pour verifier
        # les appareils a proximite, mais l'edition est cachee

    # ------------------------------------------------------------------
    # Crud
    # ------------------------------------------------------------------

    def _add_tool(self):
        """Ouvre le dialogue d'ajout d'outil (superviseur seulement)."""
        if not self._is_supervisor():
            QMessageBox.warning(self, "Acces refuse",
                                "Reserve au Superviseur.")
            return
        dialog = AddEditToolDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_tool_data()
            if data["name"]:
                tool = Tool(
                    name=data["name"],
                    data_type=data["data_type"],
                    unit=data["unit"],
                    unit_symbol=data["unit_symbol"],
                    multiplier=data["multiplier"],
                    bluetooth_uuid=data["bluetooth_uuid"],
                    backup_bluetooth_uuid=data.get("backup_bluetooth_uuid"),
                )
                self.repository.add_tool(tool)
                self._refresh()

    def _edit_tool(self, tool: Tool):
        """Ouvre le dialogue d'edition d'outil (superviseur seulement)."""
        if not self._is_supervisor():
            QMessageBox.warning(self, "Acces refuse",
                                "Reserve au Superviseur.")
            return
        dialog = AddEditToolDialog(tool=tool, parent=self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_tool_data()
            if data["name"]:
                tool.name = data["name"]
                tool.data_type = data["data_type"]
                tool.unit = data["unit"]
                tool.unit_symbol = data["unit_symbol"]
                tool.multiplier = data["multiplier"]
                tool.bluetooth_uuid = data["bluetooth_uuid"]
                tool.backup_bluetooth_uuid = data.get("backup_bluetooth_uuid")
                self.repository.update_tool(tool)
                self._refresh()

    def _configure_tool(self, tool: Tool):
        """Ouvre le dialogue de configuration rapide d'un outil."""
        dialog = ToolConfigDialog(tool, parent=self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            tool.name = data["name"]
            tool.data_type = data["data_type"]
            tool.unit = data["unit"]
            tool.unit_symbol = data["unit_symbol"]
            tool.multiplier = data["multiplier"]
            self.repository.update_tool(tool)
            self._refresh()

    def _delete_tool(self, tool: Tool):
        """Supprime un outil apres confirmation (superviseur seulement)."""
        if not self._is_supervisor():
            QMessageBox.warning(self, "Acces refuse",
                                "Reserve au Superviseur.")
            return
        reply = QMessageBox.question(
            self,
            "Confirmer la suppression",
            f"Supprimer l'outil '{tool.name}' ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.repository.delete_tool(tool.tool_id)
            self._refresh()

    def _delete_selected_tool(self):
        """Supprime l'outil actuellement selectionne (raccourci Delete)."""
        if not self._is_supervisor():
            return
        # Trouver l'outil selectionne via la carte active
        # Par defaut, on prend le dernier outil de la liste si un seul
        tools = self.repository.get_all()
        if len(tools) == 0:
            return
        if len(tools) == 1:
            self._delete_tool(tools[0])
            return
        # Si plusieurs outils, demander lequel supprimer via une boite de dialogue
        from PySide6.QtWidgets import QInputDialog
        names = [t.name for t in tools]
        name, ok = QInputDialog.getItem(
            self, "Supprimer un outil",
            "Selectionnez l'outil a supprimer:", names, False
        )
        if ok and name:
            for t in tools:
                if t.name == name:
                    self._delete_tool(t)
                    break

    # ------------------------------------------------------------------
    # Scan BLE par outil
    # ------------------------------------------------------------------

    def _scan_single_tool(self, tool: Tool):
        """Lance un scan BLE cible pour un outil specifique."""
        uuids = tool.get_uuids()
        if not uuids:
            QMessageBox.information(self, "Scan",
                                    "Aucune adresse MAC configuree pour cet outil.")
            return

        async def _scan_tool():
            try:
                devices = await self.bluetooth_manager.discover_devices(timeout=4.0)
                found = False
                for device in devices:
                    if device.bluetooth_uuid in uuids:
                        found = True
                        logger.info("Outil trouve: %s (%s)", device.name, device.bluetooth_uuid)
                if not found:
                    logger.info("Outil %s non trouve lors du scan", tool.name)
            except Exception as e:
                logger.error("Erreur scan outil %s: %s", tool.name, e)

        create_task(_scan_tool())

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    def _get_connected_tools(self) -> list:
        """Retourne la liste des outils connectes."""
        try:
            # BluetoothManager a une methode get_connected_tools()
            return self.bluetooth_manager.get_connected_tools() if hasattr(
                self.bluetooth_manager, "get_connected_tools"
            ) else []
        except Exception:
            return []

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            else:
                sub = item.layout()
                if sub:
                    self._clear_layout(sub)
