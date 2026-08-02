"""Connection tab — Gestion interactive des connexions Bluetooth.

Decouvre automatiquement les appareils Bluetooth au chargement,
affiche un cache persistant, et maintient un flux RSSI en temps reel
pour chaque appareil decouvert.

Architecture :
  - DeviceCard pour chaque peripherique (nom, RSSI bars, statut anime)
  - QTimer pour rafraichir RSSI toutes les 3 secondes
  - Scan periodique toutes les 15 secondes
  - Cache persistant pour les appareils connus
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional, Union

from PySide6.QtCore import Qt, QTimer, QMetaObject
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QFrame,
    QScrollArea,
    QMessageBox,
    QSizePolicy,
    QDialog,
    QComboBox,
    QFormLayout,
    QCheckBox,
)
from PySide6.QtGui import QFont

from src.models.bluetooth_manager import BluetoothManager
from src.models.tool import Tool, ToolsRepository
from src.views.widgets import (
    DeviceCard,
    ScanProgressBar,
    EmptyState,
    StatusState,
    ShortcutsFooter,
)

logger = logging.getLogger(__name__)

# Intervalle de rafraichissement RSSI (secondes)
RSSI_REFRESH_INTERVAL = 3.0
# Intervalle de scan automatique (secondes)
AUTO_SCAN_INTERVAL = 15.0


class SectionFrame(QFrame):
    """Cadre repliable pour une section de la page de connexion."""

    def __init__(self, title: str, accent_color: str = "#FFFFFF", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #2B2B3D;
                border-radius: 8px;
                padding: 10px;
                margin-top: 5px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 8, 12, 8)

        # En-tete de section avec titre colore
        header = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {accent_color}; font-size: 10px;")
        dot.setFixedWidth(16)
        header.addWidget(dot)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {accent_color};"
        )
        header.addWidget(self.title_label)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet(
            "font-size: 13px; color: #757575; padding-left: 8px;"
        )
        header.addWidget(self.count_label)

        header.addStretch()
        layout.addLayout(header)

        # Contenu
        self.content = QVBoxLayout()
        self.content.setSpacing(6)
        layout.addLayout(self.content)

    def set_count(self, count: int):
        if count > 0:
            self.count_label.setText(f"({count})")
        else:
            self.count_label.setText("")


class ConnectionTab(QWidget):
    """Onglet de connexion/deconnexion des outils avec interface interactive."""

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)

        self.connected_tools: List[Tool] = []
        self.discovered_devices: List[Tool] = []
        self.known_devices_cache: List[dict] = []
        self.selected_card: Optional[str] = None

        # Mapping adresse → DeviceCard
        self._known_cards: dict[str, DeviceCard] = {}
        self._discovered_cards: dict[str, DeviceCard] = {}
        self._connected_cards: dict[str, DeviceCard] = {}

        self.bluetooth_manager = BluetoothManager()
        # Utiliser le cache de ble_core via bluetooth_manager (synchrone avec les scans)
        self.device_cache = self.bluetooth_manager.device_cache

        # Ensemble de taches asyncio — strong reference pour eviter GC Python 3.13+
        self._bg_tasks: set = set()

        self.setup_ui()

        # Timer RSSI — rafraichit les barres de signal toutes les 3s
        self._rssi_timer = QTimer(self)
        self._rssi_timer.timeout.connect(self._refresh_rssi)
        self._rssi_timer.start(RSSI_REFRESH_INTERVAL)

        # Scan automatique differe
        QTimer.singleShot(400, self.auto_scan)

        # Raccourcis clavier propres a l'onglet
        from PySide6.QtGui import QShortcut, QKeySequence
        self._esc_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._esc_shortcut.activated.connect(self._shortcut_escape)

        self._filter_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._filter_shortcut.activated.connect(self._shortcut_filter)

    def _shortcut_escape(self):
        """Escape → annule le scan si en cours."""
        self.stop_scan()

    def _shortcut_filter(self):
        """Ctrl+F → barre de recherche si elle existe."""
        if hasattr(self, "_filter_input"):
            self._filter_input.setFocus()
            self._filter_input.selectAll()

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        # --- En-tete ---
        header = QHBoxLayout()

        title = QLabel("Connexions Bluetooth")
        title_font = QFont("Segoe UI", 24, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: white;")
        header.addWidget(title)

        header.addStretch()

        # Barre de recherche rapide
        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("Rechercher...")
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.setFixedWidth(200)
        self._filter_input.setStyleSheet("""
            QLineEdit {
                padding: 8px 12px; border: 1px solid #3D3D50;
                border-radius: 4px; background-color: #2B2B3D;
                color: white; font-size: 13px;
            }
            QLineEdit:focus { border: 1px solid #4CAF50; }
        """)
        self._filter_input.textChanged.connect(self._filter_cards)

        self.scan_btn = QPushButton("  Scanner  ")
        self.scan_btn.setToolTip(
            "Lancer un scan Bluetooth (Ctrl+R)"
        )
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3; color: white;
                padding: 12px 26px; border: none;
                border-radius: 6px; font-size: 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1E88E5; }
            QPushButton:disabled { background-color: #3D3D50; color: #757575; }
        """)
        self.scan_btn.clicked.connect(self.scan_devices)
        header.addWidget(self.scan_btn)

        self.stop_scan_btn = QPushButton("  Arreter  ")
        self.stop_scan_btn.setToolTip(
            "Arreter le scan en cours (Esc)"
        )
        self.stop_scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336; color: white;
                padding: 12px 26px; border: none;
                border-radius: 6px; font-size: 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #D32F2F; }
        """)
        self.stop_scan_btn.clicked.connect(self.stop_scan)
        self.stop_scan_btn.hide()
        header.addWidget(self.stop_scan_btn)

        layout.addLayout(header)

        # --- Barre de progression du scan ---
        self.scan_progress = ScanProgressBar(self)
        self.scan_progress.scan_cancelled.connect(self.stop_scan)
        layout.addWidget(self.scan_progress)

        # --- Zone de scroll pour les sections ---
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
        self._scroll_layout = QVBoxLayout(scroll_content)
        self._scroll_layout.setSpacing(14)

        # --- Appareils connus ---
        self.known_section = SectionFrame("Appareils Connus", accent_color="#FF9800")
        self._scroll_layout.addWidget(self.known_section)

        # --- Appareils decouverts ---
        self.discovered_section = SectionFrame("Appareils Decouverts", accent_color="#2196F3")
        self._scroll_layout.addWidget(self.discovered_section)

        # --- Outils connectes ---
        self.connected_section = SectionFrame("Outils Connectes", accent_color="#4CAF50")
        self._scroll_layout.addWidget(self.connected_section)

        self._scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Lexique de raccourcis clavier
        layout.addWidget(ShortcutsFooter([
            ("Ctrl+F", "Rechercher"),
            ("Ctrl+R", "Scanner"),
            ("Esc", "Arreter le scan"),
            ("Ctrl+Maj+L", "Deconnexion"),
        ]))

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def auto_scan(self):
        """Lance un scan automatique au demarrage + affiche le cache."""
        self.update_known_devices()
        self.scan_devices()

    def scan_devices(self):
        """Lance un scan Bluetooth asynchrone."""
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scan...")
        self.stop_scan_btn.show()
        self.scan_progress.start_scan(timeout=8.0)

        # Marquer les cartes decouvertes comme SCANNING
        for card in self._discovered_cards.values():
            card.set_state(StatusState.SCANNING)

        self._scan_task = task = asyncio.create_task(self._do_scan())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _do_scan(self):
        try:
            devices = await self.bluetooth_manager.discover_devices(timeout=6.0)
            self.discovered_devices = devices
            self.scan_progress.set_device_count(len(devices))

            # Mettre a jour dans le thread Qt
            QTimer.singleShot(0, self._on_scan_complete)
        except asyncio.CancelledError:
            logger.info("Scan BLE annule")
            raise
        except Exception as e:
            logger.error("Erreur scan BLE: %s", e)
            QTimer.singleShot(0, lambda msg=str(e): self._on_scan_error(msg))

    def stop_scan(self):
        """Annule le scan en cours."""
        if hasattr(self, "_scan_task") and self._scan_task:
            self._scan_task.cancel()
            self._scan_task = None
        self.scan_progress.cancel_btn.hide()
        self.scan_progress.label.setText("Scan annule")
        self.scan_progress.label.setStyleSheet("font-size: 12px; color: #FF9800;")
        self._reset_scan_button()

    def _reset_scan_button(self):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("  Scanner  ")
        self.stop_scan_btn.hide()

    def update_ble_status(self) -> str:
        """Retourne un texte court sur l'etat BLE pour la barre de statut.

        Utilise par MainWindow pour la QStatusBar.
        """
        try:
            from src.models.ble_core import BluetoothCore
            if BluetoothCore._instance and BluetoothCore._instance._running:
                return "BLE: actif"
        except Exception:
            pass
        return "BLE: inactif"

    # ------------------------------------------------------------------
    # Mise a jour des listes
    # ------------------------------------------------------------------

    def _on_scan_complete(self):
        """Slot appele depuis le thread du scan termine."""
        self.scan_progress.finish_scan(len(self.discovered_devices))
        self._reset_scan_button()
        self.update_lists()

    def _on_scan_error(self, error_msg: str):
        self.scan_progress.set_error(error_msg)
        self._reset_scan_button()
        # Afficher le cache quand meme
        self.update_lists()

    def update_lists(self):
        """Met a jour toutes les listes apres un scan."""
        self.update_known_devices()
        self._update_discovered_list()
        self._update_connected_list()

    def _filter_cards(self, text: str):
        """Filtre les cartes affichees selon le texte saisi."""
        text = text.lower()
        # Parcourt toutes les sections et leurs cartes
        for section, cards_dict in [
            (self.known_section, self._known_cards),
            (self.discovered_section, self._discovered_cards),
            (self.connected_section, self._connected_cards),
        ]:
            for addr, card in cards_dict.items():
                visible = (
                    text in card.device_name.lower()
                    or text in addr.lower()
                    or not text  # vide = tout afficher
                )
                card.setVisible(visible)

    # ------------------------------------------------------------------
    # Appareils connus (cache persistant)
    # ------------------------------------------------------------------

    def update_known_devices(self):
        """Affiche les appareils connus du cache persistant (ble_core.DeviceCache)."""
        self._clear_layout(self.known_section.content)
        self._known_cards.clear()

        known = self.device_cache.get_all()
        self.known_devices_cache = known or []
        self.known_section.set_count(len(self.known_devices_cache))

        if not known:
            label = QLabel("Aucun appareil connu. Lancez un scan.")
            label.setStyleSheet("color: #757575; padding: 8px 0; font-size: 13px;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.known_section.content.addWidget(label)
            return

        for info in known:
            # info est un BleDeviceInfo (depuis ble_core)
            card = DeviceCard(
                address=info.address,
                name=info.name or "Inconnu",
            )
            # Convertir les types BleDeviceInfo pour set_info
            from src.models.ble_core import DeviceProfiler, DeviceType
            manufacturer_name = DeviceProfiler.detect_manufacturer(
                info.manufacturer_id
            ) if info.manufacturer_id is not None else None
            dev_type = info.device_type.name if isinstance(info.device_type, DeviceType) else "generic"

            card.set_info(
                address=info.address,
                name=info.name or "Inconnu",
                rssi=info.rssi,
                manufacturer=manufacturer_name,
                device_type=dev_type,
                is_paired=info.is_paired,
            )
            card.set_state(StatusState.DISCOVERED)

            card.connect_requested.connect(self._on_card_connect)
            card.disconnect_requested.connect(self._on_card_disconnect)
            card.forget_requested.connect(self._on_card_forget)

            self._known_cards[info.address] = card
            self.known_section.content.addWidget(card)

    # ------------------------------------------------------------------
    # Appareils decouverts (dernier scan)
    # ------------------------------------------------------------------

    def _update_discovered_list(self):
        """Affiche les appareils decouverts avec RSSI et statut."""
        self._clear_layout(self.discovered_section.content)
        self._discovered_cards.clear()
        self.discovered_section.set_count(len(self.discovered_devices))

        if not self.discovered_devices:
            empty = EmptyState("Aucun appareil trouve lors du scan")
            empty.rescan_requested.connect(self.scan_devices)
            self.discovered_section.content.addWidget(empty)
            return

        for device in self.discovered_devices:
            card = DeviceCard(
                address=device.bluetooth_uuid or "",
                name=device.name or "Appareil inconnu",
            )
            # Profilage via bluetooth_manager si disponible
            profiled_type = "generic"
            manufacturer = None
            if hasattr(self.bluetooth_manager, "profile_device"):
                try:
                    profile = self.bluetooth_manager.profile_device(
                        device.bluetooth_uuid or ""
                    )
                    if profile:
                        profiled_type = profile.get("device_type", "generic")
                        manufacturer = profile.get("manufacturer")
                except Exception:
                    pass

            card.set_info(
                address=device.bluetooth_uuid or "",
                name=device.name or "Inconnu",
                rssi=getattr(device, "rssi", None),
                manufacturer=manufacturer,
                device_type=profiled_type,
                is_paired=False,
            )
            card.set_state(StatusState.DISCOVERED)

            card.connect_requested.connect(self._on_card_connect)
            card.disconnect_requested.connect(self._on_card_disconnect)
            card.forget_requested.connect(self._on_card_forget)

            self._discovered_cards[device.bluetooth_uuid or ""] = card
            self.discovered_section.content.addWidget(card)

    # ------------------------------------------------------------------
    # Outils connectes
    # ------------------------------------------------------------------

    def _update_connected_list(self):
        """Affiche les outils actuellement connectes."""
        self._clear_layout(self.connected_section.content)
        self._connected_cards.clear()
        self.connected_section.set_count(len(self.connected_tools))

        if not self.connected_tools:
            label = QLabel("Aucun outil connecte.")
            label.setStyleSheet("color: #757575; padding: 8px 0; font-size: 13px;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.connected_section.content.addWidget(label)
            return

        for tool in self.connected_tools:
            addr = tool.bluetooth_uuid or ""
            card = DeviceCard(
                address=addr,
                name=tool.name,
            )
            card.set_info(
                address=addr,
                name=tool.name,
                rssi=None,
                device_type=getattr(tool, "device_type", "generic"),
            )
            card.set_state(StatusState.CONNECTED)

            card.connect_requested.connect(self._on_card_connect)
            card.disconnect_requested.connect(self._on_card_disconnect)
            card.forget_requested.connect(self._on_card_forget)

            self._connected_cards[addr] = card
            self.connected_section.content.addWidget(card)

    # ------------------------------------------------------------------
    # Actions cartes
    # ------------------------------------------------------------------

    def _on_card_connect(self, address: str, name: str):
        """Connecte un appareil depuis une DeviceCard."""
        tool = Tool(name=name, bluetooth_uuid=address)

        # Mettre la carte en mode CONNECTING
        card = (self._discovered_cards.get(address)
                or self._known_cards.get(address))
        if card:
            card.set_state(StatusState.CONNECTING)

        task = asyncio.create_task(self._do_connect(tool, address))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _do_connect(self, tool: Tool, address: str):
        try:
            success = await self.bluetooth_manager.connect_tool(tool)
            if success:
                # --- NOUVEAU: Utiliser PairAndEditToolDialog extrait ---
                from PySide6.QtWidgets import QDialog
                from src.views.dialogs.pair_edit_tool_dialog import PairAndEditToolDialog
                
                dialog = PairAndEditToolDialog(
                    bluetooth_uuid=address,
                    device_name=tool.name or "Appareil inconnu",
                    existing_tools=self.repository.get_all() if hasattr(self, 'repository') else None,
                    parent=self.parent()
                )
                
                result = dialog.exec()
                
                if result == QDialog.DialogCode.Accepted:
                    selected = dialog.get_result()
                    
                    if isinstance(selected, int):
                        # Outil existant sélectionné
                        tool_obj = self.repository.get_by_id(selected) if hasattr(self, 'repository') else None
                        if tool_obj:
                            if not any(t.bluetooth_uuid == address for t in self.connected_tools):
                                self.connected_tools.append(tool_obj)
                                QTimer.singleShot(0, self.update_lists)
                    elif isinstance(selected, Tool):
                        # Nouvel outil créé
                        tool_obj = selected
                        if not any(t.bluetooth_uuid == address for t in self.connected_tools):
                            self.connected_tools.append(tool_obj)
                            QTimer.singleShot(0, self.update_lists)
                
                else:
                    # Annulé - on ne fait rien, l'utilisateur peut juste fermer
                    pass
                    
            else:
                # Echec → ERROR
                QTimer.singleShot(0, lambda a=address: self._set_card_error(a))
        except asyncio.CancelledError:
            logger.info("Connexion BLE annulee: %s", address)
            raise
        except Exception as e:
            logger.error("Echec connexion %s: %s", address, e)
            QTimer.singleShot(0, lambda a=address: self._set_card_error(a))

    def _on_card_disconnect(self, address: str):
        """Deconnecte un appareil depuis une DeviceCard."""
        task = asyncio.create_task(self._do_disconnect(address))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _do_disconnect(self, address: str):
        try:
            # Trouver le tool correspondant
            tool = next(
                (t for t in self.connected_tools if t.bluetooth_uuid == address),
                None
            )
            await self.bluetooth_manager.disconnect_tool(address)
            if tool and tool in self.connected_tools:
                self.connected_tools.remove(tool)
            QTimer.singleShot(0, self.update_lists)
        except Exception as e:
            logger.error("Echec deconnexion %s: %s", address, e)
            QMessageBox.warning(self, "Erreur", f"Echec deconnexion: {e}")

    def _on_card_forget(self, address: str):
        """Supprime un appareil du cache."""
        self.device_cache.remove(address)
        self.update_known_devices()

    def _set_card_error(self, address: str):
        """Passe une carte en erreur."""
        card = (self._discovered_cards.get(address)
                or self._known_cards.get(address)
                or self._connected_cards.get(address))
        if card:
            card.set_state(StatusState.ERROR)

    # ------------------------------------------------------------------
    # Rafraichissement RSSI (timer)
    # ------------------------------------------------------------------

    def _refresh_rssi(self):
        """Met a jour les barres RSSI de toutes les cartes decouvertes.

        Utilise les donnees du cache BluetoothCore si disponible,
        sinon les valeurs du dernier scan sont conservees.
        """
        # Les cartes conserve leur dernier RSSI connu via set_info()
        # Le scan periodique (auto_scan) met a jour les RSSI
        # On peut forcer une mise a jour depuis le cache si disponible
        try:
            if self.bluetooth_manager:
                core = self.bluetooth_manager.core
                if core:
                    cached = core.get_cached_devices()
                    for info in cached:
                        addr = info.address
                        card = (self._discovered_cards.get(addr)
                                or self._known_cards.get(addr))
                        if card and info.rssi is not None:
                            card.set_rssi(info.rssi)
        except Exception:
            pass

    # ------------------------------------------------------------------
# Utilitaires
# ------------------------------------------------------------------

    def _clear_layout(self, layout):
        """Supprime tous les widgets d'un layout, y compris sous-layouts."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            else:
                sub = item.layout()
                if sub:
                    self._clear_layout(sub)
