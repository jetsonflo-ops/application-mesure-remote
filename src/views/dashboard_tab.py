"""Dashboard tab - Vue d'ensemble des outils et mesures."""
import sys
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QFrame, QGridLayout)
from PySide6.QtCore import QTimer, Qt, Signal
from src.views.widgets import ShortcutsFooter


class DashboardTab(QWidget):
    """Onglet Dashboard - Vue d'ensemble en temps reel."""

    # Signal emis quand une action est demandee depuis le dashboard
    navigate_to_tab = Signal(int)  # index de l'onglet cible
    
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        
        # Etat
        self.last_measurements = []
        self.connected_tools_count = 0
        self.recent_measurements_data = []
        
        # Timer pour mise a jour auto — pause quand le tab est cache
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.refresh_data)
        self.update_timer.start(5000)
        
        self.setup_ui()

    def hideEvent(self, event):
        """Met en pause le timer quand l'onglet est cache."""
        self.update_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        """Reprend le timer quand l'onglet est visible."""
        self.update_timer.start(5000)
        super().showEvent(event)
    
    def setup_ui(self):
        """Configure l'interface du Dashboard."""
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Titre
        title = QLabel("Vue d'ensemble")
        title.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: white;
        """)
        layout.addWidget(title)
        
        # Cartes de statut (3 colonnes)
        stats_grid = QGridLayout()
        stats_grid.setSpacing(15)
        
        # Carte 1 - Outils connectes
        self.connected_card = self._create_stat_card("Outils Connectes", "0", "#4CAF50")
        self.connected_card.setToolTip("Nombre d'outils de mesure actuellement connectes")
        stats_grid.addWidget(self.connected_card, 0, 0)
        
        # Carte 2 - Dernieres mesures
        self.measures_card = self._create_stat_card("Mesures (10s)", "0", "#FF9800")
        self.measures_card.setToolTip("Nombre de mesures recues dans les 10 dernieres secondes")
        stats_grid.addWidget(self.measures_card, 0, 1)
        
        # Carte 3 - Systeme
        self.system_card = self._create_stat_card("Systeme", "En ligne", "#2196F3")
        self.system_card.setToolTip("Etat du systeme et du module Bluetooth")
        stats_grid.addWidget(self.system_card, 0, 2)
        
        layout.addLayout(stats_grid)
        
        # Section Dernieres mesures (tableau horizontal)
        recent_label = QLabel("Dernieres Mesures")
        recent_label.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: white;
            padding: 5px 0;
        """)
        layout.addWidget(recent_label)
        
        self.recent_table = QFrame()
        self.recent_table.setStyleSheet("""
            QFrame {
                background-color: #2B2B3D;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        recent_layout = QVBoxLayout(self.recent_table)
        
        # En-tetes du tableau
        headers = ["Outil", "Valeur", "Heure", "Statut"]
        header_row = QHBoxLayout()
        for header in headers:
            label = QLabel(header)
            label.setStyleSheet("font-weight: bold; color: white; padding: 5px;")
            header_row.addWidget(label)
        
        recent_layout.addLayout(header_row)
        
        # Contenu du tableau (rempli dynamiquement)
        self.measurements_list = QVBoxLayout()
        recent_layout.addLayout(self.measurements_list)
        
        layout.addWidget(self.recent_table)
        
        # Section Alertes
        alerts_label = QLabel("Alertes")
        alerts_label.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: white;
            padding: 5px 0;
        """)
        layout.addWidget(alerts_label)
        
        self.alerts_container = QFrame()
        self.alerts_container.setStyleSheet("""
            QFrame {
                background-color: #2B2B3D;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        alerts_layout = QVBoxLayout(self.alerts_container)
        
        self.alerts_list = QLabel("Aucune alerte.")
        self.alerts_list.setStyleSheet("color: #A0A0A0;")
        alerts_layout.addWidget(self.alerts_list)
        
        layout.addWidget(self.alerts_container)
        
        # Lexique de raccourcis clavier
        layout.addWidget(ShortcutsFooter([
            ("Ctrl+1-6", "Naviguer entre les onglets"),
            ("Ctrl+R", "Rafraichir"),
            ("Ctrl+Maj+L", "Deconnexion"),
        ]))
        
        self.setLayout(layout)
    
    def _create_stat_card(self, title: str, value: str, color: str):
        """Cree une carte de statistique."""
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: #2B2B3D;
                border-radius: 8px;
                padding: 15px;
                border-left: 4px solid {color};
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(15, 10, 15, 10)
        
        # Titre
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 14px; color: #A0A0A0;")
        layout.addWidget(title_label)
        
        # Valeur principale
        value_label = QLabel(value)
        value_label.setObjectName("value_label")
        value_label.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {color};")
        layout.addWidget(value_label)
        
        return card
    
    def refresh_data(self):
        """Rafraichit les donnees du Dashboard depuis les sources reelles."""
        # Mettre a jour les compteurs depuis le parent (MainWindow)
        parent = self.parent()
        if parent is None:
            return
            
        # Chercher la fenetre principale via le stack
        main_window = None
        if hasattr(parent, 'parent'):
            main_window = parent.parent()
        if main_window is None:
            main_window = parent
        
        # Compter les outils connectes depuis connection_tab
        connected_count = 0
        if hasattr(main_window, 'connection_tab'):
            try:
                connected_count = len(main_window.connection_tab.connected_tools)
            except Exception:
                pass
        
        # Mettre a jour la carte connectes
        self._update_card_value(self.connected_card, str(connected_count))
        
        # Mettre a jour les mesures recentes depuis measures_tab
        recent_count = 0
        if hasattr(main_window, 'measures_tab'):
            try:
                table = main_window.measures_tab.data_table
                recent_count = table.rowCount()
            except Exception:
                pass
        
        self._update_card_value(self.measures_card, str(recent_count))
    
    def _update_card_value(self, card: QFrame, value: str):
        """Met a jour la valeur d'une carte de statistique."""
        label = card.findChild(QLabel, "value_label")
        if label:
            label.setText(value)
    
    def add_measurement(self, tool_name: str, value: str, status: str):
        """Ajoute une mesure au tableau recent du dashboard."""
        from PySide6.QtCore import QDateTime
        
        row_layout = QHBoxLayout()
        
        name_label = QLabel(tool_name)
        name_label.setStyleSheet("padding: 5px; color: white;")
        row_layout.addWidget(name_label)
        
        value_label = QLabel(value)
        value_label.setStyleSheet("padding: 5px; color: white;")
        row_layout.addWidget(value_label)
        
        time_label = QLabel(QDateTime.currentDateTime().toString("HH:mm:ss"))
        time_label.setStyleSheet("padding: 5px; color: #A0A0A0;")
        row_layout.addWidget(time_label)
        
        status_colors = {"OK": "#4CAF50", "Alerte": "#FF9800", "Erreur": "#F44336"}
        status_label = QLabel(status)
        status_label.setStyleSheet(f"padding: 5px; color: {status_colors.get(status, '#757575')};")
        row_layout.addWidget(status_label)
        
        self.measurements_list.addLayout(row_layout)
        
        # Limiter a 10 lignes
        while self.measurements_list.count() > 10:
            item = self.measurements_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
    
    def update_stats(self, connected_count: int, recent_measurements: list):
        """Met a jour les statistiques du dashboard."""
        self.connected_tools_count = connected_count
        self.last_measurements = recent_measurements
        
        self._update_card_value(self.connected_card, str(connected_count))
        self._update_card_value(self.measures_card, str(len(recent_measurements)))

    def closeEvent(self, event):
        """Nettoyage a la fermeture."""
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()
        super().closeEvent(event)
