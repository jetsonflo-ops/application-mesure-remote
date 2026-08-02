"""Main entry point for the Bluetooth Measurement Application."""
import sys
import os
import traceback
import logging
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon
from src.views.main_window import MainWindow
from src.utils.logger import ApplicationLogger
from src.utils.qt_async_executor import QtAsyncExecutor


# ---------------------------------------------------------------------------
# Hook global d'exception — Qt avale silencieusement les exceptions dans
# les slots. Ce hook les intercepte, les logge et affiche un dialogue.
# Source: timlehr.com/python-exception-hooks-with-qt-message-box
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


def global_excepthook(exc_type, exc_value, exc_tb):
    """Intercepte les exceptions non rattrapees (y compris dans les slots Qt)."""
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("Exception non rattrapee:\n%s", tb)
    try:
        QMessageBox.critical(
            None,
            "Erreur Critique",
            f"Une erreur inattendue s'est produite.\n\n"
            f"{exc_type.__name__}: {exc_value}\n\n"
            f"Consultez les logs pour plus de details.",
        )
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def main():
    """Fonction principale de l'application."""

    # Installer le hook global AVANT tout
    sys.excepthook = global_excepthook

    # Initialiser le logger
    app_logger = ApplicationLogger()
    app_logger.log("info", "Application de Mesure - Demarrage")

    # Creer l'application Qt AVANT tout
    app = QApplication(sys.argv)

    # Initialiser l'executor async centralise AVANT de creer la fenetre
    QtAsyncExecutor.initialize(app)

    # Permettre la propagation des polices meme avec des style sheets
    from PySide6.QtCore import Qt
    app.setAttribute(Qt.AA_UseStyleSheetPropagationInWidgetStyles, True)

    # Appliquer un theme global (Fusion)
    app.setStyle("Fusion")

    # Icone de l'application — compatible dev et PyInstaller
    icon_dirs = [
        getattr(sys, '_MEIPASS', None),       # PyInstaller --onefile (temp dir)
        os.path.dirname(__file__),             # Dev / source
        os.path.join(os.path.dirname(__file__), 'src', 'assets'),  # Fallback assets
    ]
    for d in icon_dirs:
        if d and os.path.exists(os.path.join(d, 'app.ico')):
            icon_path = os.path.join(d, 'app.ico')
            app.setWindowIcon(QIcon(icon_path))
            break

    # Police adaptative globale
    from src.utils.font_manager import FontManager
    FontManager.apply(app, base_size=13)

    # Creer la fenetre principale
    window = MainWindow()

    # Afficher la fenetre
    window.show()

    app_logger.log("info", "Application de Mesure - Interface affichee")

    # Enregistrer shutdown propre
    _shutdown_task = None

    def _on_about_to_quit():
        import asyncio
        loop = QtAsyncExecutor.get_loop()
        if loop.is_running():
            # Référence forte : la tâche ne doit pas être garbage-collectée
            # avant la fin du shutdown (docs Python : asyncio.create_task).
            global _shutdown_task
            _shutdown_task = asyncio.ensure_future(
                QtAsyncExecutor.instance().shutdown()
            )

    app.aboutToQuit.connect(_on_about_to_quit)

    # Lancer le cycle d'evenements Qt (avec asyncio integre via QtAsyncExecutor)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
