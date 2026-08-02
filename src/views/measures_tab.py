"""Measures tab - Affichage temps reel des mesures."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QFrame, QTableWidget, QTableWidgetItem,
                               QHeaderView, QAbstractItemView)
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QBrush
from src.views.widgets import ShortcutsFooter


class MeasuresTab(QWidget):
    """Onglet de visualisation des mesures en temps reel.

    Signaux:
        new_measurement: Emis quand une nouvelle mesure est recue,
                         pour declencher l'export automatique.
    """

    new_measurement = Signal(dict)
    
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        
        # Timer pour mise a jour auto (toutes les 2 secondes)
        # Desactive tant que refresh_measurements() n'est pas connecte aux donnees BLE
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.refresh_measurements)
        
        self.setup_ui()
    
    def setup_ui(self):
        """Configure l'interface des mesures."""
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Titre et controles
        header_layout = QHBoxLayout()
        
        title = QLabel("Mesures en Temps Reel")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: white;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Boutons de contrôle
        export_btn = QPushButton("Exporter")
        export_btn.setToolTip(
            "Acceder a l'onglet Export (Ctrl+5)"
        )
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45A049;
            }
        """)
        parent = self.parent()
        if parent and hasattr(parent, 'tab_widget'):
            export_btn.clicked.connect(
                lambda: parent.tab_widget.setCurrentIndex(4)
            )
        header_layout.addWidget(export_btn)
        
        layout.addLayout(header_layout)
        
        # Tableau des mesures
        self.measures_table = QFrame()
        self.measures_table.setStyleSheet("""
            QFrame {
                background-color: #2B2B3D;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        table_layout = QVBoxLayout(self.measures_table)
        
        # Tableau de donnees (rempli dynamiquement)
        headers = ["Horodatage", "Outil", "Valeur", "Unite", "Statut", "Notes"]
        self.data_table = QTableWidget()
        self.data_table.setColumnCount(len(headers))
        self.data_table.setHorizontalHeaderLabels(headers)
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSortingEnabled(True)
        
        header_view = self.data_table.horizontalHeader()
        header_view.setStretchLastSection(True)
        for i in range(len(headers) - 1):
            header_view.setSectionResizeMode(i, QHeaderView.Stretch)
        
        self.data_table.verticalHeader().setVisible(False)
        self.data_table.verticalHeader().setDefaultSectionSize(40) # Hauteur de ligne confortable pour police adaptative
        header_view.setMinimumHeight(45) # Hauteur minimale de l'en-tête pour éviter l'écrasement
        self.data_table.setShowGrid(False)
        
        self.data_table.setStyleSheet("""
            QTableWidget {
                background-color: #1E1E2E;
                color: white;
                gridline-color: #3D3D50;
                alternate-background-color: #252538;
                border: none;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QHeaderView::section {
                background-color: #2B2B3D;
                color: white;
                padding: 10px;
                border: none;
                border-bottom: 2px solid #4CAF50;
                font-weight: bold;
            }
        """)
        self.data_table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )
        self.data_table.setSelectionMode(
            QAbstractItemView.SingleSelection
        )
        
        table_layout.addWidget(self.data_table)
        
        layout.addWidget(self.measures_table, 1)
        
        # Lexique de raccourcis clavier
        layout.addWidget(ShortcutsFooter([
            ("Ctrl+1-6", "Naviguer entre les onglets"),
            ("Ctrl+5", "Aller a l'export"),
            ("Ctrl+Maj+L", "Deconnexion"),
        ]))
        
        self.setLayout(layout)
    
    def refresh_measurements(self):
        """Rafraîchit les mesures (simulation)."""
        pass
    
    def add_measurement_row(self, timestamp: str, tool_name: str, value: float,
                           unit: str, status: str, note: str = ""):
        """Ajoute une ligne au tableau des mesures et emet le signal d'export."""
        row = self.data_table.rowCount()
        self.data_table.insertRow(row)
        
        # Horodatage
        timestamp_item = QTableWidgetItem(timestamp)
        self.data_table.setItem(row, 0, timestamp_item)
        
        # Outil
        tool_item = QTableWidgetItem(tool_name)
        self.data_table.setItem(row, 1, tool_item)
        
        # Valeur
        try:
            value_text = f"{float(value):.3f}" if value is not None else "---"
        except (ValueError, TypeError):
            value_text = str(value)
        value_item = QTableWidgetItem(value_text)
        self.data_table.setItem(row, 2, value_item)
        
        # Unité
        unit_item = QTableWidgetItem(unit)
        self.data_table.setItem(row, 3, unit_item)
        
        # Statut (avec couleur)
        status_item = QTableWidgetItem(status)
        if status == "OK":
            color = QColor("#4CAF50")
        elif status == "Alerte":
            color = QColor("#FF9800")
        else:
            color = QColor("#F44336")
        
        # Appliquer la couleur via QBrush
        status_item.setForeground(QBrush(color))
        self.data_table.setItem(row, 4, status_item)
        
        # Notes
        note_item = QTableWidgetItem(note)
        self.data_table.setItem(row, 5, note_item)

        # Emettre le signal pour l'export automatique
        self.new_measurement.emit({
            "timestamp": timestamp,
            "tool_name": tool_name,
            "tool_id": None,
            "value": value,
            "unit": unit,
            "status": status,
            "note": note,
        })
