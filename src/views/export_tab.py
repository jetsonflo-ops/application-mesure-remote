"""Export tab - Export multi-format automatique des mesures.

Configuration :
  1. Choix du dossier de destination
  2. Selection des formats actifs (XLSX, CSV, JSON, XML, PDF, SQLite)
  3. Activation de l'export automatique des la reception d'une mesure
  4. Historique des exports

L'export est 100% automatique : des qu'une mesure arrive du pipeline
BLE, elle est exportee dans tous les formats actifs. Pas d'export
manuel — tout est declenche par le signal `new_measurement`.
"""

from __future__ import annotations

import os
import logging
from datetime import datetime
from typing import List, Dict, Optional, Set, Callable

from PySide6.QtCore import Qt, Signal, QTimer, QMetaObject
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QFileDialog,
    QCheckBox,
    QLineEdit,
    QScrollArea,
    QGroupBox,
    QGridLayout,
    QSizePolicy,
)

from src.utils.data_exporter import (
    DataExporter,
    FORMAT_NAMES,
    FORMAT_ORDER,
)
from src.utils.qt_async_executor import create_task
from src.utils.font_manager import FontManager
from src.views.widgets import ShortcutsFooter

logger = logging.getLogger(__name__)


class FormatCard(QFrame):
    """Carte de selection pour un format d'export.

    Affiche le nom du format, une checkbox, et un indicateur visuel.
    """

    toggled = Signal(str, bool)  # format, actif

    def __init__(self, fmt: str, parent=None):
        super().__init__(parent)
        self.fmt = fmt
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("""
            FormatCard {
                background-color: #1E1E2E;
                border-radius: 8px;
                padding: 8px;
                border: 1px solid #3D3D50;
            }
            FormatCard:hover {
                background-color: #252538;
                border: 1px solid #4CAF50;
            }
        """)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.checkbox = QCheckBox("")
        self.checkbox.setChecked(True)
        self.checkbox.setStyleSheet("""
            QCheckBox::indicator {
                width: 18px; height: 18px;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border-radius: 3px;
            }
        """)
        self.checkbox.stateChanged.connect(self._on_toggle)
        layout.addWidget(self.checkbox)

        # Nom du format
        name = FORMAT_NAMES.get(self.fmt, self.fmt.upper())
        self.name_label = QLabel(name)
        self.name_label.setStyleSheet("font-size: 14px; font-weight: bold; color: white;")
        layout.addWidget(self.name_label)

        # Extension
        ext = f".{self.fmt}"
        self.ext_label = QLabel(ext)
        self.ext_label.setStyleSheet("font-size: 12px; color: #757575;")
        layout.addWidget(self.ext_label)

        layout.addStretch()

        # Indicateur visuel
        self.indicator = QLabel("●")
        self.indicator.setStyleSheet("color: #4CAF50; font-size: 10px;")
        layout.addWidget(self.indicator)

        # Clic sur la carte = toggle checkbox
        self.mousePressEvent = lambda e: self._toggle()

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, checked: bool):
        self.checkbox.setChecked(checked)
        self._update_indicator(checked)

    def _toggle(self):
        self.checkbox.setChecked(not self.checkbox.isChecked())

    def _on_toggle(self, state):
        checked = state == Qt.CheckState.Checked.value
        self._update_indicator(checked)
        self.toggled.emit(self.fmt, checked)

    def _update_indicator(self, checked: bool):
        if checked:
            self.indicator.setStyleSheet("color: #4CAF50; font-size: 10px;")
        else:
            self.indicator.setStyleSheet("color: #757575; font-size: 10px;")


class ExportHistoryItem(QFrame):
    """Element de l'historique des exports."""

    def __init__(self, filepath: str, fmt: str, timestamp: str, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.fmt = fmt
        self.timestamp = timestamp

        self.setStyleSheet("""
            ExportHistoryItem {
                background-color: #1E1E2E;
                border-radius: 6px;
                padding: 8px;
                margin-bottom: 4px;
            }
            ExportHistoryItem:hover {
                background-color: #252538;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        # Format badge — convertir 'db' en 'sqlite' pour l'affichage
        fmt_display = fmt.lower()
        if fmt_display == "db":
            fmt_display = "sqlite"
        badge = QLabel(f"[{fmt_display.upper()}]")
        badge.setStyleSheet("""
            font-weight: bold; color: #4CAF50; font-size: 12px;
            background-color: #1E3A1E; padding: 2px 6px; border-radius: 3px;
        """)
        layout.addWidget(badge)

        # Nom du fichier
        name_label = QLabel(os.path.basename(filepath))
        name_label.setStyleSheet("color: white; font-size: 12px;")
        layout.addWidget(name_label)

        layout.addStretch()

        # Horodatage
        time_label = QLabel(timestamp)
        time_label.setStyleSheet("color: #757575; font-size: 11px;")
        layout.addWidget(time_label)

        # Bouton ouvrir
        open_btn = QPushButton("Ouvrir")
        open_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #2196F3;
                padding: 2px 8px;
                border: 1px solid #2196F3;
                border-radius: 3px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #2196F3; color: white; }
        """)
        open_btn.clicked.connect(self._open_file)
        layout.addWidget(open_btn)

    def _open_file(self):
        """Ouvre le fichier avec l'application par defaut."""
        import subprocess
        try:
            if os.name == "nt":  # Windows
                os.startfile(self.filepath)
            else:
                subprocess.Popen(["xdg-open", self.filepath])
        except Exception as e:
            logger.error("Impossible d'ouvrir %s: %s", self.filepath, e)


class ExportTab(QWidget):
    """Onglet d'export multi-format avec auto-export.

    Signaux:
        new_measurement: Emis par le pipeline BLE pour declencher l'export.
    """

    # Signal recu par l'onglet quand une nouvelle mesure arrive
    new_measurement = Signal(dict)

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)

        self.exporter = DataExporter()
        self._history: List[Dict] = []

        # Connecter le signal d'export automatique
        self.new_measurement.connect(self._on_new_measurement)

        self.setup_ui()

        # Restaurer la configuration
        self._load_settings()

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 16, 20, 16)

        # --- En-tete ---
        header = QHBoxLayout()

        title = QLabel("Export des Mesures")
        title_font = QFont("Segoe UI", 24, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: white;")
        header.addWidget(title)

        header.addStretch()

        self.status_label = QLabel("Prets")
        self.status_label.setStyleSheet("font-size: 13px; color: #A0A0A0;")
        header.addWidget(self.status_label)

        layout.addLayout(header)

        # --- Zone scrollable ---
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
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setSpacing(14)

        # --- Section 1 : Destination ---
        dest_group = self._make_group("Dossier de destination", "#2196F3")
        dest_layout = QVBoxLayout()

        path_layout = QHBoxLayout()
        self.output_path = QLineEdit()
        self.output_path.setText(self.exporter.output_dir)
        self.output_path.setReadOnly(True)
        self.output_path.setStyleSheet("""
            QLineEdit {
                padding: 12px; border: 1px solid #444;
                border-radius: 4px; background-color: #2B2B3D;
                color: white; font-size: 14px;
            }
        """)
        path_layout.addWidget(self.output_path)

        browse_btn = QPushButton(" Parcourir ")
        browse_btn.setToolTip(
            "Choisir un dossier de destination pour les fichiers exportes"
        )
        browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3; color: white;
                padding: 12px 18px; border: none;
                border-radius: 4px; font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1E88E5; }
        """)
        browse_btn.clicked.connect(self._browse_output)
        path_layout.addWidget(browse_btn)

        dest_layout.addLayout(path_layout)

        # Stats dossier
        dir_info = QHBoxLayout()
        self.dir_stats = QLabel("Espace disponible: --")
        self.dir_stats.setStyleSheet("font-size: 12px; color: #757575;")
        dir_info.addWidget(self.dir_stats)
        dir_info.addStretch()
        dest_layout.addLayout(dir_info)

        dest_group.layout().addLayout(dest_layout)
        content_layout.addWidget(dest_group)

        # --- Section 2 : Formats ---
        fmt_group = self._make_group("Formats d'export", "#4CAF50")
        fmt_layout = QGridLayout()
        fmt_layout.setSpacing(8)

        self._format_cards: Dict[str, FormatCard] = {}
        for i, fmt in enumerate(FORMAT_ORDER):
            card = FormatCard(fmt)
            card.toggled.connect(self._on_format_toggle)
            fmt_layout.addWidget(card, i // 3, i % 3)
            self._format_cards[fmt] = card

        fmt_group.layout().addLayout(fmt_layout)
        content_layout.addWidget(fmt_group)

        # --- Section 3 : Auto-export ---
        auto_group = self._make_group("Export automatique", "#FF9800")
        auto_layout = QVBoxLayout()

        self.auto_check = QCheckBox(
            "Exporter automatiquement chaque mesure des sa reception"
        )
        self.auto_check.setChecked(True)
        self.auto_check.setStyleSheet("""
            QCheckBox { color: white; font-size: 14px; spacing: 10px; }
            QCheckBox::indicator { width: 20px; height: 20px; }
            QCheckBox::indicator:checked {
                background-color: #4CAF50; border-radius: 4px;
            }
        """)
        auto_layout.addWidget(self.auto_check)

        # Sous-options
        sub_opts = QHBoxLayout()
        self.notify_check = QCheckBox("Notification a chaque export")
        self.notify_check.setChecked(True)
        self.notify_check.setStyleSheet("color: #A0A0A0; font-size: 13px;")
        sub_opts.addWidget(self.notify_check)

        self.open_after = QCheckBox("Ouvrir le dossier apres export")
        self.open_after.setChecked(False)
        self.open_after.setStyleSheet("color: #A0A0A0; font-size: 13px;")
        sub_opts.addWidget(self.open_after)

        sub_opts.addStretch()
        auto_layout.addLayout(sub_opts)

        auto_group.layout().addLayout(auto_layout)
        content_layout.addWidget(auto_group)

        # --- Separateur ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #3D3D50;")
        content_layout.addWidget(sep)

        # --- Section 4 : Historique ---
        hist_group = self._make_group("Historique des exports", "#A0A0A0")
        self._history_layout = QVBoxLayout()
        self._history_layout.setSpacing(4)

        # Label par defaut
        self._history_empty = QLabel("Aucun export recent.")
        self._history_empty.setStyleSheet("color: #757575; padding: 16px; font-size: 13px;")
        self._history_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._history_layout.addWidget(self._history_empty)

        hist_group.layout().addLayout(self._history_layout)
        content_layout.addWidget(hist_group)

        content_layout.addStretch()

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Lexique de raccourcis clavier
        layout.addWidget(ShortcutsFooter([
            ("Ctrl+1-6", "Naviguer entre les onglets"),
            ("Ctrl+Maj+L", "Deconnexion"),
        ]))

    # ------------------------------------------------------------------
    # Sections de l'interface
    # ------------------------------------------------------------------

    def _make_group(self, title: str, color: str) -> QGroupBox:
        """Cree un groupe avec titre colore."""
        group = QGroupBox(title)
        group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold; font-size: 15px;
                color: {color};
                border: 1px solid #3D3D50;
                border-radius: 8px;
                margin-top: 16px;
                padding: 16px 12px 12px 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 16px;
                padding: 0 8px;
                color: {color};
            }}
        """)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)
        return group

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _browse_output(self):
        """Ouvre le selecteur de dossier."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choisir le dossier d'export",
            self.exporter.output_dir,
        )
        if folder:
            self.exporter.set_output_dir(folder)
            self.output_path.setText(folder)
            self._update_dir_stats()
            self._save_settings()

    def _update_dir_stats(self):
        """Affiche l'espace disque disponible."""
        import shutil
        try:
            path = self.exporter.output_dir
            os.makedirs(path, exist_ok=True)
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024 ** 3)
            self.dir_stats.setText(f"Espace libre: {free_gb:.1f} Go")
        except Exception:
            self.dir_stats.setText("Espace disponible: --")

    def _on_format_toggle(self, fmt: str, active: bool):
        """Active/desactive un format."""
        if active:
            self.exporter.enable_format(fmt)
        else:
            self.exporter.disable_format(fmt)
        self._save_settings()
        self._update_status()

    def _update_status(self):
        """Met a jour la barre de statut."""
        active = self.exporter.active_formats
        names = [FORMAT_NAMES.get(f, f.upper()) for f in FORMAT_ORDER if f in active]
        auto = " AUTO" if self.auto_check.isChecked() else ""
        if names:
            self.status_label.setText(f"Actifs: {', '.join(names)}{auto}")
        else:
            self.status_label.setText("Aucun format actif")

    # ------------------------------------------------------------------
    # Auto-export (connecte au pipeline BLE)
    # ------------------------------------------------------------------

    def _on_new_measurement(self, measurement_data: Dict):
        """Declenche l'export automatique a la reception d'une mesure.

        Appele via le signal new_measurement emis par le pipeline BLE.
        """
        if not self.auto_check.isChecked():
            return

        if not self.exporter.active_formats:
            return

        async def _do_export():
            try:
                files = await self.exporter.async_export_measurement(measurement_data)

                for fp in files:
                    ext = os.path.splitext(fp)[1].lstrip(".")
                    self._add_history(fp, ext)

                if files and self.notify_check.isChecked():
                    self._flash_status(f"Exporte: {', '.join(files)}")

                if files and self.open_after.isChecked():
                    self._open_folder()
            except Exception as e:
                logger.error("Erreur auto-export: %s", e)

        create_task(_do_export())

    def _flash_status(self, text: str):
        """Affiche temporairement un message de statut."""
        self.status_label.setStyleSheet("font-size: 13px; color: #4CAF50;")
        self.status_label.setText(text)
        QTimer.singleShot(3000, self._restore_status)

    def _restore_status(self):
        self.status_label.setStyleSheet("font-size: 13px; color: #A0A0A0;")
        self._update_status()

    def _open_folder(self):
        """Ouvre le dossier d'export dans l'explorateur."""
        import subprocess
        path = self.exporter.output_dir
        try:
            if os.name == "nt":
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            logger.error("Impossible d'ouvrir le dossier: %s", e)

    # ------------------------------------------------------------------
    # Historique
    # ------------------------------------------------------------------

    def _add_history(self, filepath: str, fmt: str):
        """Ajoute un element a l'historique."""
        now = datetime.now().strftime("%H:%M:%S")

        # Supprimer le label "aucun"
        if self._history_empty is not None:
            self._history_empty.deleteLater()
            self._history_empty = None

        item = ExportHistoryItem(filepath, fmt, now)
        self._history_layout.addWidget(item)

        self._history.append({
            "filepath": filepath,
            "fmt": fmt,
            "timestamp": now,
        })

        # Limiter a 20 elements
        if len(self._history) > 20:
            old = self._history.pop(0)
            # Enlever le widget correspondant (premier enfant apres le label)
            item = self._history_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    # ------------------------------------------------------------------
    # Persistance
    # ------------------------------------------------------------------

    def _save_settings(self):
        """Sauvegarde la configuration dans un fichier."""
        try:
            import json
            path = os.path.join(
                os.path.expanduser("~"), ".application_mesure", "export_config.json"
            )
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = {
                "output_dir": self.exporter.output_dir,
                "active_formats": sorted(self.exporter.active_formats),
                "auto_export": self.auto_check.isChecked(),
                "notify": self.notify_check.isChecked(),
                "open_after": self.open_after.isChecked(),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Erreur sauvegarde config export: %s", e)

    def _load_settings(self):
        """Charge la configuration depuis le fichier."""
        try:
            import json
            path = os.path.join(
                os.path.expanduser("~"), ".application_mesure", "export_config.json"
            )
            if not os.path.exists(path):
                return

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Dossier
            output_dir = data.get("output_dir", self.exporter.output_dir)
            self.exporter.set_output_dir(output_dir)
            self.output_path.setText(output_dir)

            # Formats actifs
            active = data.get("active_formats", ["xlsx", "csv"])
            self.exporter.set_active_formats(set(active))
            for fmt, card in self._format_cards.items():
                card.set_checked(fmt in active)

            # Options
            self.auto_check.setChecked(data.get("auto_export", True))
            self.notify_check.setChecked(data.get("notify", True))
            self.open_after.setChecked(data.get("open_after", False))

            self._update_dir_stats()
            self._update_status()
        except Exception as e:
            logger.error("Erreur chargement config export: %s", e)
