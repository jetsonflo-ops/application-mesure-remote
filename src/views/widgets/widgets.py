"""Widgets personnalises pour l'interface de l'application de mesure.

Contient :
  - StatusIndicator : voyant lumineux anime (connecte/deconnecte/erreur/scan)
  - SignalStrengthBars : barres de puissance RSSI (type telephonie)
  - DeviceCard : carte complete pour un peripherique (nom, adresse, RSSI, statut)
  - ScanProgressBar : barre de progression du scan BLE
"""

from __future__ import annotations

import math
import warnings
from enum import Enum, auto
from typing import Optional, Callable

from PySide6.QtCore import (
    Qt,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    Property,
    Signal,
    QSize,
    QRectF,
)
from PySide6.QtGui import (
    QPainter,
    QColor,
    QBrush,
    QPen,
    QFont,
    QLinearGradient,
    QRadialGradient,
    QFontMetrics,
)
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QSizePolicy,
)


# ===================================================================
# Couleurs du thème (accord avec le style existant)
# ===================================================================

COLOR_BG_DARK = QColor("#1E1E2E")
COLOR_BG_CARD = QColor("#2B2B3D")
COLOR_BG_INNER = QColor("#1E1E2E")
COLOR_TEXT_PRIMARY = QColor("#FFFFFF")
COLOR_TEXT_SECONDARY = QColor("#A0A0A0")
COLOR_TEXT_MUTED = QColor("#757575")

COLOR_GREEN = QColor("#4CAF50")
COLOR_GREEN_LIGHT = QColor("#81C784")
COLOR_RED = QColor("#F44336")
COLOR_RED_LIGHT = QColor("#E57373")
COLOR_ORANGE = QColor("#FF9800")
COLOR_ORANGE_LIGHT = QColor("#FFB74D")
COLOR_BLUE = QColor("#2196F3")
COLOR_BLUE_LIGHT = QColor("#64B5F6")
COLOR_GRAY = QColor("#757575")
COLOR_GRAY_LIGHT = QColor("#BDBDBD")

COLOR_RSSI_BAR_FULL = QColor("#4CAF50")  # Vert
COLOR_RSSI_BAR_MED = QColor("#FF9800")  # Orange
COLOR_RSSI_BAR_LOW = QColor("#F44336")  # Rouge
COLOR_RSSI_BAR_OFF = QColor("#3D3D50")  # Inactif


# ===================================================================
# StatusIndicator — Voyant lumineux anime
# ===================================================================


class StatusState(Enum):
    """État du voyant de statut."""

    DISCONNECTED = auto()  # Grisé — aucun signal
    DISCOVERED = auto()  # Bleu fade — visible mais pas connecté
    CONNECTING = auto()  # Orange — pulsation en cours
    CONNECTED = auto()  # Vert — pulsatation lente (connecté)
    ERROR = auto()  # Rouge — clignotement
    RECONNECTING = auto()  # Orange — pulsation rapide
    SCANNING = auto()  # Bleu — pulsation


class StatusIndicator(QWidget):
    """Voyant lumineux animé indiquant l'état de connexion BLE.

    Utilise QPropertyAnimation pour une animation fluide :
      - DISCONNECTED : cercle gris fixe
      - CONNECTING : pulsation orange (transition)
      - CONNECTED : pulsation verte lente (respirations)
      - ERROR : clignotement rouge
      - SCANNING : pulsation bleue
    """

    def __init__(self, parent: Optional[QWidget] = None, size: int = 16):
        super().__init__(parent)
        self._state = StatusState.DISCONNECTED
        self._pulse_value = 0.0  # 0.0 → 1.0 en boucle
        self._fixed_size = size

        # Animation de pulsation continue
        self._pulse_anim = QPropertyAnimation(self, b"pulse_value")
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setLoopCount(-1)  # Infini
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.SineCurve)

        self.setFixedSize(size + 4, size + 4)
        self.set_state(StatusState.DISCONNECTED)

    # -- Propriété animée ------------------------------------------------

    def get_pulse_value(self) -> float:
        return self._pulse_value

    def set_pulse_value(self, value: float):
        self._pulse_value = value
        self.update()

    pulse_value = Property(float, get_pulse_value, set_pulse_value)

    # -- Changement d'état ------------------------------------------------

    def set_state(self, state: StatusState):
        self._state = state
        self._pulse_anim.stop()

        if state == StatusState.DISCONNECTED:
            self._pulse_value = 0.0
            self.update()
        elif state == StatusState.DISCOVERED:
            self._pulse_value = 0.3
            self.update()
        elif state == StatusState.CONNECTING:
            self._pulse_anim.setDuration(800)
            self._pulse_anim.start()
        elif state == StatusState.CONNECTED:
            self._pulse_anim.setDuration(2000)  # Respiration lente
            self._pulse_anim.start()
        elif state == StatusState.ERROR:
            self._pulse_anim.setDuration(500)  # Clignotement rapide
            self._pulse_anim.start()
        elif state == StatusState.RECONNECTING:
            self._pulse_anim.setDuration(400)  # Rapide
            self._pulse_anim.start()
        elif state == StatusState.SCANNING:
            self._pulse_anim.setDuration(1200)
            self._pulse_anim.start()

    @property
    def state(self) -> StatusState:
        return self._state

    # -- Peinture ----------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        center = rect.center()
        radius = min(rect.width(), rect.height()) / 2 - 2

        # Couleur de base selon l'état
        base_color = self._get_base_color()
        # Intensité selon pulse
        intensity = self._pulse_value if self._state not in (
            StatusState.DISCONNECTED, StatusState.DISCOVERED
        ) else (0.3 if self._state == StatusState.DISCOVERED else 0.0)

        # Cercle extérieur (halo) — visible pendant pulsation
        if intensity > 0.05:
            halo_color = QColor(base_color)
            halo_color.setAlphaF(intensity * 0.3)
            painter.setBrush(QBrush(halo_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center, radius + 3, radius + 3)

        # Cercle intérieur (plein)
        fill_color = QColor(base_color)
        if self._state in (StatusState.CONNECTING, StatusState.SCANNING,
                           StatusState.RECONNECTING):
            # Pulsation : intensité variable
            fill_color.setAlphaF(0.5 + 0.5 * intensity)
        else:
            fill_color.setAlphaF(0.8 + 0.2 * intensity)

        painter.setBrush(QBrush(fill_color))
        painter.setPen(QPen(QColor(base_color).lighter(130), 1))
        painter.drawEllipse(center, radius - 1, radius - 1)

        # Point lumineux central (effet 3D)
        if intensity > 0.1:
            from PySide6.QtCore import QPointF
            focal = QPointF(center.x() - radius * 0.3, center.y() - radius * 0.3)
            highlight = QRadialGradient(focal, radius * 0.5)
            highlight.setColorAt(0.0, QColor(255, 255, 255, 80))
            highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(QBrush(highlight))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center, radius - 1, radius - 1)

    def _get_base_color(self) -> QColor:
        if self._state == StatusState.CONNECTED:
            return COLOR_GREEN
        elif self._state == StatusState.ERROR:
            return COLOR_RED
        elif self._state in (StatusState.CONNECTING, StatusState.RECONNECTING):
            return COLOR_ORANGE
        elif self._state == StatusState.SCANNING:
            return COLOR_BLUE
        elif self._state == StatusState.DISCOVERED:
            return COLOR_BLUE_LIGHT
        else:  # DISCONNECTED
            return COLOR_GRAY


# ===================================================================
# SignalStrengthBars — Barres de puissance RSSI
# ===================================================================


class SignalStrengthBars(QWidget):
    """Barres de puissance du signal RSSI (type téléphonie).

    Affiche de 0 à 5 barres selon l'intensité du signal.
    Couleur : vert (fort) → orange (moyen) → rouge (faible).
    """

    # Seuils RSSI pour le nombre de barres
    # RSSI typique BLE : -30 (tres fort) à -100 (tres faible)
    RSSI_THRESHOLDS = [-85, -75, -65, -55, -45]

    def __init__(self, parent: Optional[QWidget] = None, bars: int = 5):
        super().__init__(parent)
        self._rssi: Optional[int] = None
        self._num_bars = bars
        self.setFixedSize(bars * 10 + 4, 18)
        self.setMinimumWidth(bars * 10 + 4)

    def set_rssi(self, rssi: Optional[int]):
        """Met à jour l'affichage avec une valeur RSSI."""
        self._rssi = rssi
        self.update()

    def _bars_active(self) -> int:
        if self._rssi is None:
            return 0
        for i, threshold in enumerate(self.RSSI_THRESHOLDS):
            if self._rssi >= threshold:
                return i + 1
        return 0

    def _bar_color(self, bar_index: int) -> QColor:
        active = self._bars_active()
        if bar_index >= active:
            return COLOR_RSSI_BAR_OFF
        # Dégradé : si >= 4 barres = vert, 2-3 = orange, 1 = rouge
        if active >= 4:
            return COLOR_RSSI_BAR_FULL
        elif active >= 2:
            return COLOR_RSSI_BAR_MED
        else:
            return COLOR_RSSI_BAR_LOW

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        bar_w = 6
        gap = 3
        max_h = h - 4

        for i in range(self._num_bars):
            x = 2 + i * (bar_w + gap)
            # Hauteur croissante : chaque barre est plus haute
            bar_h = max_h * (0.3 + 0.7 * (i + 1) / self._num_bars)
            y = h - 2 - bar_h

            color = self._bar_color(i)
            painter.setBrush(QBrush(color))

            # Barre active = pleine, barre inactive = contour
            if self._bars_active() > i:
                painter.setPen(Qt.PenStyle.NoPen)
            else:
                painter.setPen(QPen(QColor("#555555"), 1))

            # Coins arrondis
            painter.drawRoundedRect(
                QRectF(x, y, bar_w, bar_h), 2, 2
            )

        # Texte RSSI a droite des barres
        if self._rssi is not None:
            painter.setPen(COLOR_TEXT_MUTED)
            font = QFont("Segoe UI", 9)
            painter.setFont(font)
            text = f"{self._rssi} dBm"
            painter.drawText(
                self._num_bars * (bar_w + gap) + 4, 2,
                w - self._num_bars * (bar_w + gap) - 4, h,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )


# ===================================================================
# DeviceTypeIcon — Icône selon le type d'appareil
# ===================================================================


class DeviceTypeIcon(QLabel):
    """Icône représentant le type d'appareil (règle, pied à coulisse, etc.).

    Affiche un pictogramme simple via QPainter.
    """

    TYPES = {
        "rule": "R",
        "caliper": "C",
        "micrometer": "M",
        "roughness": "S",
        "thermometer": "T",
        "pressure": "P",
        "generic": "?",
    }

    def __init__(self, device_type: str = "generic", size: int = 40, parent=None):
        super().__init__(parent)
        self._dev_type = device_type
        self._letter = self.TYPES.get(device_type.lower(), "?")
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont("Segoe UI", size // 2, QFont.Weight.Bold)
        self.setFont(font)

    def set_device_type(self, device_type: str):
        self._dev_type = device_type
        self._letter = self.TYPES.get(device_type.lower(), "?")
        self.setText(self._letter)


# ===================================================================
# DeviceCard — Carte complète pour un périphérique
# ===================================================================


class DeviceCard(QFrame):
    """Carte graphique pour un périphérique BLE.

    Affiche :
      - StatusIndicator anime
      - Nom + adresse + fabricant
      - SignalStrengthBars RSSI
      - Type d'appareil (icône)
      - Bouton Connecter / Deconnecter / Oublier
    """

    connect_requested = Signal(str, str)  # adresse, nom
    disconnect_requested = Signal(str)
    forget_requested = Signal(str)
    rescan_requested = Signal()

    def __init__(
        self,
        address: str = "",
        name: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.address = address
        self.device_name = name
        self.manufacturer: Optional[str] = None
        self.device_type: str = "generic"
        self.state: StatusState = StatusState.DISCONNECTED
        self.rssi: Optional[int] = None
        self.is_paired: bool = False

        self.setup_ui()
        self.set_state(StatusState.DISCOVERED)

    def setup_ui(self):
        self.setStyleSheet("""
            DeviceCard {
                background-color: #1E1E2E;
                border-radius: 8px;
                padding: 10px;
                margin-bottom: 5px;
            }
            DeviceCard:hover {
                background-color: #252538;
                border: 1px solid #3D3D50;
            }
        """)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # 1. Statut anime
        self.status_indicator = StatusIndicator(self, size=14)
        main_layout.addWidget(self.status_indicator)

        # 2. Icône type d'appareil
        self.type_icon = QLabel()
        self.type_icon.setFixedSize(36, 36)
        self.type_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.type_icon.setStyleSheet("""
            QLabel {
                background-color: #2B2B3D;
                border-radius: 18px;
                font-size: 18px;
                font-weight: bold;
                color: #A0A0A0;
            }
        """)
        main_layout.addWidget(self.type_icon)

        # 3. Infos (nom, adresse, fabricant)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(1)

        self.name_label = QLabel(self.device_name or "Appareil inconnu")
        self.name_label.setStyleSheet("font-size: 15px; font-weight: bold; color: white;")
        info_layout.addWidget(self.name_label)

        self.detail_label = QLabel(self.address)
        self.detail_label.setStyleSheet("font-size: 12px; color: #757575;")
        info_layout.addWidget(self.detail_label)

        self.manufacturer_label = QLabel("")
        self.manufacturer_label.setStyleSheet("font-size: 12px; color: #FF9800;")
        info_layout.addWidget(self.manufacturer_label)

        main_layout.addLayout(info_layout)
        main_layout.addStretch()

        # 4. RSSI
        self.signal_bars = SignalStrengthBars(self, bars=5)
        main_layout.addWidget(self.signal_bars)

        # 5. Boutons d'action
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(4)

        self.connect_btn = QPushButton("Connecter")
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px 18px;
                border: none;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #45A049; }
            QPushButton:disabled { background-color: #3D3D50; color: #757575; }
        """)
        btn_layout.addWidget(self.connect_btn)

        self.action_btn = QPushButton("...")
        self.action_btn.setFixedWidth(32)
        self.action_btn.setStyleSheet("""
            QPushButton {
                background-color: #3D3D50;
                color: #A0A0A0;
                padding: 4px;
                border: none;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #4D4D60; color: white; }
        """)
        self.action_btn.clicked.connect(self._on_action)
        btn_layout.addWidget(self.action_btn)

        main_layout.addLayout(btn_layout)

    # -- Mise à jour -------------------------------------------------------

    def set_info(
        self,
        address: str,
        name: str,
        rssi: Optional[int] = None,
        manufacturer: Optional[str] = None,
        device_type: str = "generic",
        is_paired: bool = False,
    ):
        self.address = address
        self.device_name = name
        self.rssi = rssi
        self.manufacturer = manufacturer
        self.device_type = device_type
        self.is_paired = is_paired

        self.name_label.setText(name or "Appareil inconnu")
        self.detail_label.setText(address)
        self.manufacturer_label.setText(
            f"Fabricant: {manufacturer}" if manufacturer else ""
        )

        # Icône type
        type_map = {
            "RULE_500": "R500", "RULE_1000": "R1000", "RULE": "R",
            "CALIPER": "C", "MICROMETER": "M", "ROUGHNESS": "S",
            "THERMOMETER": "T", "PRESSURE": "P",
        }
        icon_text = type_map.get(device_type, "?")
        self.type_icon.setText(icon_text)

        if rssi is not None:
            self.signal_bars.set_rssi(rssi)

    def set_state(self, state: StatusState):
        self.state = state
        self.status_indicator.set_state(state)

        # Ajuster le bouton selon l'état
        if state == StatusState.CONNECTED:
            self.connect_btn.setText("Deconnecter")
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    background-color: #F44336; color: white;
                    padding: 8px 18px; border: none; border-radius: 4px;
                    font-size: 14px; font-weight: bold;
                }
                QPushButton:hover { background-color: #D32F2F; }
            """)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    self.connect_btn.clicked.disconnect()
                except (TypeError, RuntimeError):
                    pass
            self.connect_btn.clicked.connect(self._on_disconnect)
        else:
            self.connect_btn.setText("Connecter")
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50; color: white;
                    padding: 8px 18px; border: none; border-radius: 4px;
                    font-size: 14px; font-weight: bold;
                }
                QPushButton:hover { background-color: #45A049; }
                QPushButton:disabled { background-color: #3D3D50; color: #757575; }
            """)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    self.connect_btn.clicked.disconnect()
                except (TypeError, RuntimeError):
                    pass
            self.connect_btn.clicked.connect(self._on_connect)

        # Desactiver le bouton pendant les transitions
        if state in (StatusState.CONNECTING, StatusState.RECONNECTING,
                     StatusState.SCANNING):
            self.connect_btn.setEnabled(False)
        else:
            self.connect_btn.setEnabled(True)

    def set_rssi(self, rssi: Optional[int]):
        self.rssi = rssi
        self.signal_bars.set_rssi(rssi)

    # -- Boutons -----------------------------------------------------------

    def _on_connect(self):
        self.connect_requested.emit(self.address, self.device_name)

    def _on_disconnect(self):
        self.disconnect_requested.emit(self.address)

    def _on_action(self):
        """Menu contextuel: oublier l'appareil."""
        self.forget_requested.emit(self.address)


# ===================================================================
# ScanProgressBar — Barre de progression du scan BLE
# ===================================================================


class ScanProgressBar(QWidget):
    """Barre de progression pour le scan BLE.

    Affiche :
      - Barre de progression animée pendant le scan
      - Texte (ex: "Scan en cours... 5 appareils trouves")
      - Bouton d'arret du scan
    """

    scan_cancelled = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._progress = 0
        self._device_count = 0
        self._phase_text = "Pret"
        self._scanning = False

        self.setup_ui()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        self.label = QLabel("Pret")
        self.label.setStyleSheet("font-size: 14px; color: #A0A0A0;")
        layout.addWidget(self.label)

        layout.addStretch()

        self.cancel_btn = QPushButton("Annuler")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #F44336; color: white;
                padding: 6px 14px; border: none; border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #D32F2F; }
        """)
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(self.scan_cancelled.emit)
        layout.addWidget(self.cancel_btn)

    def start_scan(self, timeout: float = 8.0):
        self._scanning = True
        self._progress = 0
        self._device_count = 0
        self.cancel_btn.show()
        self.label.setStyleSheet("font-size: 12px; color: #2196F3;")

    def set_progress(self, value: float):
        self._progress = value
        self._update_text()

    def set_device_count(self, count: int):
        self._device_count = count
        self._update_text()

    def set_phase(self, text: str):
        self._phase_text = text
        self._update_text()

    def finish_scan(self, device_count: int = 0):
        self._scanning = False
        self._device_count = device_count
        self.cancel_btn.hide()
        self.label.setStyleSheet("font-size: 12px; color: #4CAF50;")
        self.label.setText(
            f"Scan termine: {device_count} appareil(s) trouve(s)"
            if device_count else "Scan termine: aucun appareil trouve"
        )

    def set_error(self, text: str):
        self._scanning = False
        self.cancel_btn.hide()
        self.label.setStyleSheet("font-size: 12px; color: #F44336;")
        self.label.setText(f"Erreur: {text}")

    def _update_text(self):
        if self._scanning:
            self.label.setText(
                f"Scan en cours... {self._device_count} appareil(s)"
                if self._device_count
                else "Scan en cours..."
            )


# ===================================================================
# EmptyState — État vide (quand aucun appareil)
# ===================================================================


class EmptyState(QWidget):
    """Widget affiché quand il n'y a aucun appareil."""

    rescan_requested = Signal()

    def __init__(self, text: str = "Aucun appareil trouve", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        self.icon_label = QLabel("[ ]")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 48px; color: #3D3D50;")
        layout.addWidget(self.icon_label)

        self.text_label = QLabel(text)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setStyleSheet("font-size: 16px; color: #757575;")
        layout.addWidget(self.text_label)

        self.scan_btn = QPushButton("Lancer un scan Bluetooth")
        self.scan_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3; color: white;
                padding: 14px 28px; border: none; border-radius: 4px;
                font-size: 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1E88E5; }
        """)
        self.scan_btn.clicked.connect(self.rescan_requested.emit)
        layout.addWidget(self.scan_btn)

        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)


# ===================================================================
# ShortcutsFooter — Lexique de raccourcis clavier de la page
# ===================================================================


class ShortcutsFooter(QFrame):
    """Pied de page affichant les raccourcis clavier disponibles.

    S'inspire du pattern des applications modernes (VS Code, Figma,
    JetBrains) qui affichent une barre d'info semi-transparente
    en bas de chaque vue.

    2026 design pattern: fond sombre subtil, texte gris clair,
    pastilles clavier `[Ctrl+N]` grisees, separeteur fin.
    """

    def __init__(
        self,
        shortcuts: list[tuple[str, str]],
        parent: Optional[QWidget] = None,
    ):
        """
        Args:
            shortcuts: Liste de tuples (touche, description).
                       Ex: [("Ctrl+N", "Ajouter"), ("Esc", "Fermer")]
        """
        super().__init__(parent)
        self._shortcuts = shortcuts
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("""
            ShortcutsFooter {
                background-color: transparent;
                border-top: 1px solid #2B2B3D;
                margin-top: 4px;
            }
        """)
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 4)
        layout.setSpacing(4)

        # Icône clavier
        icon = QLabel("⌨")
        icon.setStyleSheet("font-size: 12px; color: #555555;")
        icon.setToolTip("Raccourcis clavier de cette page")
        layout.addWidget(icon)

        layout.addSpacing(4)

        # Separateur vertical
        sep = QLabel("|")
        sep.setStyleSheet("color: #2B2B3D; font-size: 11px;")
        layout.addWidget(sep)

        layout.addSpacing(4)

        # Chaque raccourci
        for i, (key, desc) in enumerate(self._shortcuts):
            if i > 0:
                # Point separateur
                dot = QLabel("·")
                dot.setStyleSheet("color: #3D3D50; font-size: 10px;")
                layout.addWidget(dot)
                layout.addSpacing(2)

            # Pastille touche
            key_label = QLabel(f"[{key}]")
            key_label.setStyleSheet("""
                QLabel {
                    color: #666666;
                    font-size: 10px;
                    font-family: 'Segoe UI', 'Consolas', monospace;
                    font-weight: bold;
                    padding: 1px 4px;
                    background-color: #1A1A2A;
                    border: 1px solid #2B2B3D;
                    border-radius: 3px;
                }
            """)
            layout.addWidget(key_label)

            # Description
            desc_label = QLabel(desc)
            desc_label.setStyleSheet("""
                QLabel {
                    color: #555555;
                    font-size: 10px;
                }
            """)
            layout.addWidget(desc_label)

            layout.addSpacing(2)

        layout.addStretch()

        self.setFixedHeight(28)


class EyeToggleButton(QPushButton):
    """Bouton oeil pour afficher/masquer un mot de passe.

    Dessine un oeil ouvert (visible) ou un oeil barre (cache).
    Utilise QPainter pour un rendu fiable sur Windows et Linux.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(False)
        self.setFixedSize(36, 36)
        self.setToolTip("Afficher / masquer le mot de passe")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        cx = rect.center().x()
        cy = rect.center().y()

        # Fond
        bg = QColor("#2B2B3D")
        border_color = QColor("#444")

        if self._hovered and not self.isChecked():
            bg = QColor("#3D3D50")
            border_color = QColor("#4CAF50")
        elif self.isChecked():
            bg = QColor("#1A3A1A")
            border_color = QColor("#4CAF50")

        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(border_color, 1))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)

        # Dessiner l'œil
        color = QColor("#4CAF50") if self.isChecked() else QColor("#A0A0A0")

        if self.isChecked():
            # Œil ouvert (visible)
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(QColor(0, 0, 0, 0)))
            painter.drawEllipse(cx - 8, cy - 5, 16, 10)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(cx - 2, cy - 2, 4, 4)
        else:
            # Œil fermé / barré (caché)
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(QColor(0, 0, 0, 0)))
            painter.drawArc(cx - 8, cy - 3, 16, 6, 0, 180 * 16)
            painter.setPen(QPen(QColor("#F44336"), 2))
            painter.drawLine(cx - 8, cy - 3, cx + 8, cy + 3)


def make_password_with_toggle(placeholder: str = "",
                              echo_mode=None,
                              on_change_callback=None) -> tuple[QFrame, QLineEdit, EyeToggleButton]:
    """Cree un champ mot de passe avec bouton oeil pour afficher/masquer.

    Retourne (frame_contenant, line_edit, toggle_button).
    """
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton

    if echo_mode is None:
        echo_mode = QLineEdit.Password

    frame = QFrame()
    frame.setObjectName("pwFieldFrame")

    hlayout = QHBoxLayout(frame)
    hlayout.setContentsMargins(0, 0, 0, 0)
    hlayout.setSpacing(4)

    line_edit = QLineEdit()
    line_edit.setPlaceholderText(placeholder)
    line_edit.setEchoMode(echo_mode)
    line_edit.setStyleSheet("""
        QLineEdit {
            padding: 10px;
            border: 1px solid #444;
            border-radius: 4px;
            background-color: #2B2B3D;
            color: white;
        }
        QLineEdit:focus {
            border: 1px solid #4CAF50;
        }
    """)

    toggle_btn = EyeToggleButton()

    def _toggle_visibility(checked: bool):
        line_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        toggle_btn.update()

    toggle_btn.toggled.connect(_toggle_visibility)

    if on_change_callback:
        line_edit.textChanged.connect(on_change_callback)

    hlayout.addWidget(line_edit)
    hlayout.addWidget(toggle_btn)

    return frame, line_edit, toggle_btn
