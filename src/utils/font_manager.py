"""Gestionnaire de police adaptative — Ajuste la taille des polices
en fonction de la largeur de la fenetre principale.

Principe :
  - Taille de base : 13pt (vs 9pt par defaut dans Qt)
  - Facteur d'echelle : base * min(1.4, max(0.8, window_width / REF_WIDTH))
  - Les polices des boutons importants sont en gras + 1pt supplementaire
  - Les QComboBox dropdown lists recoivent leur propre police via view().setFont()

Utilisation :
    from src.utils.font_manager import FontManager
    FontManager.apply(app)  # Applique la police globale au demarrage
    FontManager.scaled(base=15, bold=True)  # Cree une police adaptee
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QWidget,
)

# Largeur de reference pour l'echelle 1.0
REF_WIDTH = 1280
# Police de base
FONT_FAMILY = "Segoe UI"
# Taille de base (points)
BASE_SIZE = 13
# Taille minimale absolue
MIN_SIZE = 10
# Taille maximale
MAX_SIZE = 22


class FontManager:
    """Gere la police adaptative dans toute l'application."""

    _current_scale = 1.0

    @classmethod
    def apply(cls, app: QApplication, base_size: int = BASE_SIZE):
        """Applique la police globale au demarrage.

        Args:
            app: Instance QApplication.
            base_size: Taille de base en points.
        """
        font = QFont(FONT_FAMILY, base_size)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        app.setFont(font)
        cls._current_scale = 1.0

    @classmethod
    def scaled(
        cls,
        base: Optional[int] = None,
        bold: bool = False,
        window: Optional[QWidget] = None,
    ) -> QFont:
        """Cree une police avec echelle adaptative.

        Args:
            base: Taille de base (defaut = BASE_SIZE).
            bold: True si la police doit etre en gras.
            window: Widget Qt dont la largeur sert de reference.
                    Si None, utilise l'echelle actuelle.

        Retourne:
            QFont configure.
        """
        size = base or BASE_SIZE

        if window:
            width = window.width()
            scale = max(0.8, min(1.4, width / REF_WIDTH))
        else:
            scale = cls._current_scale

        scaled_size = max(MIN_SIZE, min(MAX_SIZE, round(size * scale)))
        font = QFont(FONT_FAMILY, scaled_size)

        if bold:
            font.setBold(True)

        return font

    @classmethod
    def setup_combobox_popup(cls, combo: QComboBox, window: Optional[QWidget] = None):
        """Applique la police adaptative a la liste deroulante d'un QComboBox.

        Les QComboBox heritent de la police du widget mais leur popup
        (QListView) utilise une police separee qui ne suit pas toujours
        le theme. Cette methode la synchronise.

        Args:
            combo: Le QComboBox a ajuster.
            window: Reference pour l'echelle (defaut = parent).
        """
        view = combo.view()
        if view:
            font = cls.scaled(base=12, window=window or combo.window())
            view.setFont(font)

    @classmethod
    def connect_resize(cls, window: QWidget, callback=None):
        """Connecte un slot de recalibrage au redimensionnement.

        Reemet la police globale si la fenetre change de taille
        significativement (plus de 5% de variation).

        Args:
            window: La fenetre a surveiller.
            callback: Fonction supplementaire a appeler apres recalibrage.
        """
        last_width = [window.width()]

        def on_resize():
            nonlocal last_width
            new_width = window.width()
            ratio = new_width / last_width[0] if last_width[0] else 1.0
            if ratio < 0.95 or ratio > 1.05:
                last_width[0] = new_width
                # Re-appliquer la police globale
                scaled_size = max(
                    MIN_SIZE,
                    min(MAX_SIZE, round(BASE_SIZE * new_width / REF_WIDTH)),
                )
                font = QFont(FONT_FAMILY, scaled_size)
                app = QApplication.instance()
                if app:
                    app.setFont(font)

                if callback:
                    callback()

                # Re-appliquer aux widgets si la fenetre a une methode _refresh
                if hasattr(window, '_refresh_all_fonts'):
                    window._refresh_all_fonts()

        # Timer differe pour ne pas flooder le resize
        timer = QTimer(window)
        timer.setSingleShot(True)

        def delayed_resize():
            timer.start(150)

        timer.timeout.connect(on_resize)
        old_resize = window.resizeEvent
        def new_resize(event):
            if old_resize and old_resize != type(window).resizeEvent:
                old_resize(event)
            else:
                type(window).resizeEvent(window, event)
            delayed_resize()
        window.resizeEvent = new_resize

    @classmethod
    def boost_font(cls, widget: QWidget, base: int = 14, bold: bool = True):
        """Augmente la police d'un widget specifique.

        Utilise pour les boutons d'action importants ou les labels
        qui doivent etre plus visibles.

        Args:
            widget: Le widget a modifier.
            base: Taille de base.
            bold: Gras ou non.
        """
        font = cls.scaled(base=base, bold=bold, window=widget.window())
        widget.setFont(font)

    @classmethod
    def stylesheet_with_font(
        cls,
        widget_type: str,
        props: dict,
        base_size: int = 12,
        bold: bool = False,
    ) -> str:
        """Genere une feuille de style avec taille de police echelonnee.

        Exemple:
            FontManager.stylesheet_with_font(
                "QPushButton",
                {"background-color": "#4CAF50", "color": "white"},
                base_size=13, bold=True
            )

        Args:
            widget_type: Type Qt du widget (ex: 'QPushButton', 'QLabel').
            props: Proprietes CSS (dict key: value).
            base_size: Taille de police de base.
            bold: Gras ou non.

        Retourne:
            Chaine CSS complete.
        """
        font = cls.scaled(base=base_size, bold=bold)
        css = f"""{widget_type} {{
            font-size: {font.pointSize()}pt;
            font-weight: {"bold" if bold else "normal"};
        """
        for key, value in props.items():
            css += f"    {key}: {value};\n"
        css += "}"
        return css


# ===================================================================
# Helper rapide — echelle de police depuis le ratio fenetre
# ===================================================================


def font_scale(window_width: int) -> float:
    """Retourne le facteur d'echelle pour une largeur de fenetre donnee.

    Args:
        window_width: Largeur en pixels de la fenetre.

    Retourne:
        Facteur entre 0.8 et 1.4.
    """
    return max(0.8, min(1.4, window_width / REF_WIDTH))


def scaled_font_size(base: int, window_width: int) -> int:
    """Calcule la taille de police echelonnee.

    Args:
        base: Taille de base en points.
        window_width: Largeur de la fenetre en pixels.

    Retourne:
        Taille ajustee, comprise entre MIN_SIZE et MAX_SIZE.
    """
    scale = font_scale(window_width)
    return max(MIN_SIZE, min(MAX_SIZE, round(base * scale)))
