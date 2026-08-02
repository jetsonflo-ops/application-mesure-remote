"""Dialogue d'association et création d'outils après connexion BLE."""

import os
from typing import Optional, Union

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QCheckBox, QPushButton, QScrollArea, QWidget,
                               QFormLayout, QLineEdit, QComboBox, QFrame)
from src.models.tool import Tool, ToolsRepository


class PairAndEditToolDialog(QDialog):
    """Dialogue pour associer l'appareil BLE à un outil existant ou créer un nouvel outil."""

    def __init__(self, bluetooth_uuid: str, device_name: str, 
                 existing_tools: Optional[list] = None, repository=None, parent=None):
        """Initialise le dialogue.

        Args:
            bluetooth_uuid: UUID Bluetooth de l'appareil connecté
            device_name: Nom du dispositif BLE
            existing_tools: Liste d'outils existants (peut être None)
            repository: Repository des outils (optionnel, si None créer un nouveau)
            parent: Parent Qt (MainWindow par défaut)
        """
        super().__init__(parent)
        self.setWindowTitle("Association avec outil")
        self.setMinimumSize(500, 600)
        self.bluetooth_uuid = bluetooth_uuid
        self.device_name = device_name
        
        # Repository des outils
        if repository:
            self.repository = repository
        else:
            app_dir = os.path.join(os.path.expanduser("~"), ".application_mesure")
            config_path = os.path.join(app_dir, "tools.json")
            self.repository = ToolsRepository(config_path=config_path)
        
        # Utiliser existing_tools si fourni, sinon charger depuis le repository
        if existing_tools is not None:
            self.existing_tools = existing_tools
        else:
            self.existing_tools = self.repository.get_all()
        
        # Resultat: soit un outil existant (int), soit un nouvel outil (Tool)
        self.selected_tool: Optional[Union[int, Tool]] = None
        
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Titre
        title = QLabel(f"Appareil connecté: {self.device_name}")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: white;")
        layout.addWidget(title)
        
        # Section 1: Outils existants
        existing_label = QLabel("Ou sélectionnez un outil existant:")
        existing_label.setStyleSheet("color: #A0A0A0; font-size: 14px;")
        layout.addWidget(existing_label)
        
        # Scroll area pour la liste des outils
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: transparent; border: none;")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: #2B2B3D; border-radius: 8px;")
        tools_layout = QVBoxLayout(scroll_content)
        tools_layout.setSpacing(6)
        tools_layout.setContentsMargins(10, 10, 10, 10)
        
        for t in self.existing_tools:
            checkbox = QCheckBox(f"{t.name} ({t.unit})")
            checkbox.setStyleSheet("""
                QCheckBox { color: white; font-size: 14px; padding: 8px; }
                QCheckBox::indicator { width: 20px; height: 20px; border-radius: 4px; background-color: #3D3D50; border: 1px solid #555; }
                QCheckBox::indicator:checked { background-color: #4CAF50; border: 1px solid #4CAF50; }
            """)
            checkbox.toggled.connect(lambda checked, tool_id=t.tool_id: self._on_tool_selected(checked, tool_id))
            tools_layout.addWidget(checkbox)
        
        if not self.existing_tools:
            empty = QLabel("Aucun outil existant. Créez-en un nouveau.")
            empty.setStyleSheet("color: #757575; font-size: 13px; text-align: center;")
            tools_layout.addWidget(empty)
        
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        # Separateur
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #3D3D50;")
        layout.addWidget(sep)
        
        # Section 2: Ou créer un nouvel outil
        new_label = QLabel("Ou créez un nouvel outil:")
        new_label.setStyleSheet("color: #A0A0A0; font-size: 14px;")
        layout.addWidget(new_label)
        
        form_layout = QFormLayout()
        form_layout.setSpacing(8)
        
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("Nom de l'outil")
        self.new_name.setStyleSheet("""
            QLineEdit { padding: 10px; border: 1px solid #444; border-radius: 4px; background-color: #2B2B3D; color: white; }
        """)
        
        self.new_unit = QLineEdit()
        self.new_unit.setPlaceholderText("Unite (mm, µm, etc.)")
        self.new_unit.setStyleSheet("""
            QLineEdit { padding: 10px; border: 1px solid #444; border-radius: 4px; background-color: #2B2B3D; color: white; }
        """)
        
        self.new_type = QComboBox()
        self.new_type.addItems(["Numérique", "String", "Booléen"])
        self.new_type.setStyleSheet("""
            QComboBox { padding: 10px; border: 1px solid #444; border-radius: 4px; background-color: #2B2B3D; color: white; }
        """)
        
        form_layout.addRow("Nom:", self.new_name)
        form_layout.addRow("Unite:", self.new_unit)
        form_layout.addRow("Type:", self.new_type)
        
        layout.addLayout(form_layout)
        
        # Boutons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        cancel_btn = QPushButton("Annuler")
        cancel_btn.setStyleSheet("""
            QPushButton { background-color: #757575; color: white; padding: 10px 20px; border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #616161; }
        """)
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = QPushButton("Associer / Créer")
        save_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #45A049; }
        """)
        save_btn.clicked.connect(self.accept)
        
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        
        layout.addLayout(btn_layout)

    def _on_tool_selected(self, checked: bool, tool_id: int):
        """Gère la sélection d'un outil existant."""
        if checked:
            self.selected_tool = tool_id

    def get_result(self) -> Optional[Union[int, Tool]]:
        """Retourne le résultat du dialogue.

        Returns:
            ID de l'outil sélectionné (int) ou nouvel outil créé (Tool), None si annulé/erreur
        """
        if isinstance(self.selected_tool, int):
            return self.selected_tool
        
        # Sinon, créer un nouvel outil
        name = self.new_name.text().strip()
        unit = self.new_unit.text().strip()
        data_type = self.new_type.currentText()
        
        if not name:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Erreur", "Le nom de l'outil est requis.")
            return None
        
        new_tool = Tool(
            name=name,
            data_type=data_type,
            unit=unit,
            bluetooth_uuid=self.bluetooth_uuid,
            manufacturer="",  # Sera rempli par le profilage BLE plus tard si nécessaire
        )
        self.repository.add_tool(new_tool)
        return new_tool
