"""Widgets de notification d'erreur pour l'application.

ErrorOverlayWidget :
  - S'affiche en bas a droite de la fenetre principale
  - Chaque erreur est un bloc independant avec compteur + horodatage
  - Meme erreur = meme bloc, incrementation du compteur
  - Bouton X pour fermer individuellement chaque bloc
  - Messages humains, sans code technique
  - Fond semi-transparent avec effet de glisse (QPropertyAnimation)
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from PySide6.QtCore import Qt, QPropertyAnimation, QPoint, QEasingCurve, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy, QGraphicsOpacityEffect,
)

from src.utils.error_types import ErrorCategory, ErrorInfo


class ErrorBlock(QFrame):
    """Un bloc d'erreur individuel dans le panneau de notifications.

    Affiche :
      - Message humain clair
      - Compteur si la meme erreur se reproduit
      - Derniere date/heure d'occurrence
      - Bouton X pour fermer
    """

    CATEGORY_COLORS = {
        ErrorCategory.BLUETOOTH: "#2196F3",
        ErrorCategory.EXPORT: "#FF9800",
        ErrorCategory.FICHIER: "#9C27B0",
        ErrorCategory.BASE_DONNEES: "#E91E63",
        ErrorCategory.RESEAU: "#00BCD4",
        ErrorCategory.APPLICATION: "#F44336",
        ErrorCategory.MATERIEL: "#795548",
    }

    CATEGORY_LABELS = {
        ErrorCategory.BLUETOOTH: "Bluetooth",
        ErrorCategory.EXPORT: "Export",
        ErrorCategory.FICHIER: "Fichier",
        ErrorCategory.BASE_DONNEES: "Base de donnees",
        ErrorCategory.RESEAU: "Reseau",
        ErrorCategory.APPLICATION: "Application",
        ErrorCategory.MATERIEL: "Materiel",
    }

    def __init__(self, error: ErrorInfo, parent=None):
        super().__init__(parent)
        self.error_key = (error.category, error.error_type)
        self._error = error
        self._dismissed = False

        self.setup_ui()
        self.refresh(error)

    def setup_ui(self):
        self.setStyleSheet("""
            ErrorBlock {
                background-color: #1A1A2E;
                border: 1px solid #333366;
                border-radius: 8px;
                margin: 2px 0px;
            }
            ErrorBlock:hover {
                background-color: #222244;
            }
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(4)

        # Ligne superieure : badge + compteur + X
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        # Badge de categorie
        self.badge = QLabel()
        self.badge.setStyleSheet(
            "font-weight: bold; font-size: 10px; "
            "padding: 2px 6px; border-radius: 3px; color: white;"
        )
        top_row.addWidget(self.badge)

        # Compteur
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(
            "font-size: 11px; color: #FF9800; font-weight: bold;"
        )
        top_row.addWidget(self.count_label)

        top_row.addStretch()

        # Horodatage
        self.time_label = QLabel("")
        self.time_label.setStyleSheet("font-size: 10px; color: #888888;")
        top_row.addWidget(self.time_label)

        # Bouton fermer (X)
        close_btn = QPushButton("X")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888888;
                border: none;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                color: #F44336;
                background-color: rgba(244, 67, 54, 0.1);
                border-radius: 11px;
            }
        """)
        close_btn.clicked.connect(self._on_dismiss)
        top_row.addWidget(close_btn)

        layout.addLayout(top_row)

        # Message d'erreur
        self.msg_label = QLabel("")
        self.msg_label.setWordWrap(True)
        self.msg_label.setStyleSheet(
            "font-size: 12px; color: #E0E0E0; padding: 2px 0px;"
        )
        layout.addWidget(self.msg_label)

    def refresh(self, error: ErrorInfo):
        """Met a jour l'affichage avec les donnees actuelles."""
        self._error = error
        color = self.CATEGORY_COLORS.get(error.category, "#888888")
        label = self.CATEGORY_LABELS.get(error.category, "Erreur")

        self.badge.setText(f" {label} ")
        self.badge.setStyleSheet(
            f"font-weight: bold; font-size: 10px; "
            f"padding: 2px 6px; border-radius: 3px; color: white; "
            f"background-color: {color};"
        )

        if error.count > 1:
            self.count_label.setText(f"x{error.count}")
            self.count_label.setVisible(True)
        else:
            self.count_label.setVisible(False)

        self.time_label.setText(error.last_seen.strftime("%H:%M:%S"))
        self.msg_label.setText(error.message)

    def _on_dismiss(self):
        self._dismissed = True
        # Animation de disparition
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(200)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self._on_animation_done)
        anim.start()

    def _on_animation_done(self):
        self.deleteLater()

    @property
    def is_dismissed(self) -> bool:
        return self._dismissed

    @property
    def error(self) -> ErrorInfo:
        return self._error


class ErrorOverlayWidget(QFrame):
    """Panneau de notification d'erreur en bas a droite.

    Se positionne automatiquement dans le coin inferieur droit
    de son parent. Les erreurs s'empilent de bas en haut.
    """

    OVERLAY_WIDTH = 380
    OVERLAY_MAX_HEIGHT = 400
    OVERLAY_MARGIN = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self._blocks: Dict[tuple, ErrorBlock] = {}

        self.setup_ui()
        self._position_overlay()
        self.hide()

    def setup_ui(self):
        self.setStyleSheet("""
            ErrorOverlayWidget {
                background-color: transparent;
            }
        """)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        self._layout = layout

        self.setFixedWidth(self.OVERLAY_WIDTH)

    def _position_overlay(self):
        """Positionne le widget en bas a droite du parent."""
        parent = self.parent()
        if parent is None:
            return
        pw = parent.width()
        ph = parent.height()
        x = pw - self.OVERLAY_WIDTH - self.OVERLAY_MARGIN
        y = ph - self.OVERLAY_MARGIN - 60  # laisser place a la barre d'onglets
        # Ajuster la hauteur au contenu
        self.move(int(x), int(y))

    def show_error(self, error: ErrorInfo):
        """Affiche ou met a jour une notification d'erreur.

        Si une erreur avec la meme cle (categorie + type) existe
        deja, on incremente le compteur et on met a jour la date.
        Sinon, on cree un nouveau bloc.
        """
        key = (error.category, error.error_type)

        if key in self._blocks and not self._blocks[key].is_dismissed:
            # Erreur existante : mise a jour
            block = self._blocks[key]
            block.refresh(error)
        else:
            # Nouvelle erreur : creer un bloc
            block = ErrorBlock(error, self)
            self._blocks[key] = block
            self._layout.addWidget(block)

            # Animation d'apparition
            effect = QGraphicsOpacityEffect(block)
            block.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity")
            anim.setDuration(300)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()

        self.show()
        self._position_overlay()

        # Nettoyer les blocs fermes apres 2s
        QTimer.singleShot(2000, self._cleanup_dismissed)

    def _cleanup_dismissed(self):
        """Retire les blocs fermes."""
        to_remove = []
        for key, block in self._blocks.items():
            if block.is_dismissed:
                to_remove.append(key)
        for key in to_remove:
            del self._blocks[key]

        # Masquer le panneau si vide
        if len(self._blocks) == 0:
            self.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_overlay()

    def parent_resized(self):
        """Appeler quand le parent change de taille."""
        self._position_overlay()
