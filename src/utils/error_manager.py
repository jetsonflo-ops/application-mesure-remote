"""Gestionnaire central d'erreurs de l'application.

ErrorManager (singleton) :
  - Collecte les erreurs depuis tous les modules
  - Les achemine vers l'interface de notification
  - Assure le deduplicat (meme erreur = compteur + date)
  - Fournit une API simple : error_manager.error(...)

Utilisation:
    from src.utils.error_manager import error_manager

    # Depuis n'importe quel module :
    error_manager.error(
        category=ErrorCategory.BLUETOOTH,
        error_type="connection_failed"
    )

    # Avec message personnalise (remplace le message par defaut) :
    error_manager.error(
        category=ErrorCategory.BLUETOOTH,
        error_type="connection_failed",
        message="Le pied a coulisse ne repond pas."
    )
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Optional, Callable

from src.utils.error_types import (
    ErrorCategory,
    ErrorInfo,
    get_error_message,
)

logger = logging.getLogger(__name__)


class ErrorManager:
    """Gestionnaire central d'erreurs (singleton).

    Attributes:
        _errors: Dict des erreurs actives par cle (category, error_type).
        _ui_callback: Fonction appelee pour afficher l'erreur dans l'UI.
    """

    def __init__(self):
        self._errors: Dict[tuple, ErrorInfo] = {}
        self._ui_callback: Optional[Callable[[ErrorInfo], None]] = None

    def set_ui_callback(self, callback: Callable[[ErrorInfo], None]):
        """Definit la fonction d'affichage UI (appelee par l'overlay)."""
        self._ui_callback = callback

    def error(
        self,
        category: ErrorCategory,
        error_type: str,
        message: Optional[str] = None,
    ):
        """Signale une erreur.

        Si la meme erreur (categorie + type) a deja ete signalee
        et n'a pas ete fermee, le compteur est incremente.

        Args:
            category: Categorie de l'erreur (ex: ErrorCategory.BLUETOOTH).
            error_type: Type d'erreur interne (ex: "connection_failed").
            message: Message personnalise (optionnel). Si absent, le
                     message par defaut de error_types.py est utilise.
        """
        key = (category, error_type)

        if key in self._errors:
            # Erreur existante : mettre a jour compteur + date
            info = self._errors[key]
            info.count += 1
            info.last_seen = datetime.now()
            info.active = True
            if message:
                info.message = message
            logger.debug(
                "Erreur repetee %s/%s (x%d)",
                category.name, error_type, info.count,
            )
        else:
            # Nouvelle erreur
            msg = message or get_error_message(category, error_type)
            info = ErrorInfo(
                category=category,
                error_type=error_type,
                message=msg,
            )
            self._errors[key] = info
            logger.info("Erreur: [%s] %s - %s", category.name, error_type, msg)

        # Notifier l'UI (thread-safe: peut etre appele depuis un thread BLE)
        if self._ui_callback:
            try:
                from PySide6.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    self._ui_callback.__self__,
                    self._ui_callback.__name__,
                    Qt.QueuedConnection,
                )
            except (AttributeError, RuntimeError, TypeError):
                # Fallback direct si pas un slot Qt bindé
                try:
                    self._ui_callback(info)
                except Exception:
                    pass

    def clear(self, category: Optional[ErrorCategory] = None,
              error_type: Optional[str] = None):
        """Efface les erreurs.

        Args:
            category: Si fourni, efface toutes les erreurs de cette categorie.
            error_type: Si fourni (avec category), efface cette erreur specifique.
        """
        if category and error_type:
            self._errors.pop((category, error_type), None)
        elif category:
            self._errors = {
                k: v for k, v in self._errors.items()
                if k[0] != category
            }
        else:
            self._errors.clear()

    @property
    def active_errors(self) -> list[ErrorInfo]:
        """Retourne la liste des erreurs actives."""
        return [e for e in self._errors.values() if e.active]

    @property
    def all_errors(self) -> list[ErrorInfo]:
        """Retourne toutes les erreurs (meme fermees)."""
        return list(self._errors.values())


# Instance singleton
error_manager = ErrorManager()
