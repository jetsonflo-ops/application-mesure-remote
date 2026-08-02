"""Main window - Fenetre principale de l'application."""
import sys
import asyncio
import logging
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QTabWidget, QLabel, QPushButton, QMessageBox,
                               QStackedWidget, QComboBox, QDialog, QLineEdit,
                               QFormLayout)
from PySide6.QtCore import Signal, Qt, QTimer, QDateTime
from PySide6.QtGui import QFont, QAction, QShortcut, QKeySequence

logger = logging.getLogger(__name__)

# Import des vues
from .login_view import LoginView
from .dashboard_tab import DashboardTab
from .connection_tab import ConnectionTab
from .measures_tab import MeasuresTab
from .tools_tab import ToolsTab
from .export_tab import ExportTab
from .settings_tab import SettingsTab
from src.utils.font_manager import FontManager
from src.utils.error_manager import error_manager
from src.utils.error_types import ErrorCategory
from src.views.widgets.error_notifier import ErrorOverlayWidget
from src.views.widgets import make_password_with_toggle
from src.utils.secure_clear import secure_clear_string


class PasswordRenewalDialog(QDialog):
    """Dialogue de renouvellement force de mot de passe.

    Utilise apres deverrouillage pour forcer le changement de mot de passe.
    """

    def __init__(self, target_username: str, target_display: str,
                 parent=None):
        super().__init__(parent)
        self.target_username = target_username
        self.setWindowTitle(f"Renouvellement mot de passe - {target_display}")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog { background-color: #1E1E2E; }
            QLabel { color: white; font-size: 14px; }
            QLineEdit {
                padding: 10px;
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #2B2B3D;
                color: white;
                font-size: 14px;
            }
            QLineEdit:focus { border: 1px solid #4CAF50; }
        """)
        self._result = False
        self._setup_ui(target_display)
        self._pw = None

    def _setup_ui(self, target_display: str):
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)

        # Titre
        title = QLabel(
            f"Renouvellement obligatoire du mot de passe\n"
            f"pour {target_display}"
        )
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            font-size: 16px; font-weight: bold; color: #FF9800;
            padding: 10px; border: 1px solid #FF9800; border-radius: 6px;
        """)
        layout.addWidget(title)

        # Explication
        info = QLabel(
            "Le compte a ete deverrouille. Veuillez definir\n"
            "un nouveau mot de passe pour securiser l'acces."
        )
        info.setAlignment(Qt.AlignCenter)
        info.setStyleSheet("color: #A0A0A0; font-size: 13px;")
        layout.addWidget(info)

        # Nouveau mot de passe
        layout.addWidget(QLabel("Nouveau mot de passe:"))
        self.new_pw_frame, self.new_pw, _ = make_password_with_toggle(
            "Minimum 4 caracteres"
        )
        layout.addWidget(self.new_pw_frame)

        # Confirmation
        layout.addWidget(QLabel("Confirmer le mot de passe:"))
        self.confirm_pw_frame, self.confirm_pw, _ = make_password_with_toggle(
            "Saisir a nouveau"
        )
        layout.addWidget(self.confirm_pw_frame)

        # Bouton valider
        self.submit_btn = QPushButton("VALIDER LE CHANGEMENT")
        self.submit_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
                padding: 12px; border: none; border-radius: 4px;
                font-weight: bold; font-size: 15px;
            }
            QPushButton:hover { background-color: #45A049; }
            QPushButton:disabled { background-color: #3D3D50; color: #757575; }
        """)
        self.submit_btn.clicked.connect(self._on_submit)
        layout.addWidget(self.submit_btn)

        # Erreur
        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setStyleSheet("color: #F44336; font-size: 13px;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.setLayout(layout)

    def _on_submit(self):
        pw = self.new_pw.text()
        confirm = self.confirm_pw.text()

        if len(pw) < 4:
            self.error_label.setText("Minimum 4 caracteres requis.")
            self.error_label.setVisible(True)
            return

        if pw != confirm:
            self.error_label.setText("Les mots de passe ne correspondent pas.")
            self.error_label.setVisible(True)
            return

        self._pw = pw
        self._result = True
        self.accept()

    def get_password(self) -> str:
        """Retourne le nouveau mot de passe valide."""
        return self._pw

    def get_result(self) -> bool:
        return self._result

    def done(self, r):
        """Nettoyer les mots de passe en memoire a la fermeture."""
        if hasattr(self, 'new_pw'):
            self.new_pw.clear()
        if hasattr(self, 'confirm_pw'):
            self.confirm_pw.clear()
        if self._pw:
            secure_clear_string(self._pw)
            self._pw = None
        super().done(r)


class MainWindow(QMainWindow):
    """Fenêtre principale de l'application."""

    def __init__(self, user=None):
        super().__init__()

        # État utilisateur
        self.current_user = user

        # Configuration de la fenêtre
        self.setWindowTitle("Application de Mesure - Industrial Edition")
        self.setMinimumSize(1280, 720)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1E1E2E;
            }
            QWidget {
                color: white;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """)

        # Ensemble de taches asyncio — strong reference pour eviter GC Python 3.13+
        self._bg_tasks: set = set()

        # Initialisation des composants
        self.setup_ui()

        if user is None:
            self.stack.setCurrentIndex(0)  # Affiche login view par défaut
        else:
            self.stack.setCurrentIndex(1)  # Affiche main view par défaut

    def setup_ui(self):
        """Configure l'interface utilisateur."""
        # Widget central - QStackedWidget pour alternance login/main
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        layout = QVBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # === VUE DE CONNEXION (index 0) ===
        self.login_view = LoginView()
        self.login_view.login_success.connect(self.handle_login_success)
        self.login_view.root_unlock_success.connect(self.handle_root_unlock_success)

        # === VUE PRINCIPALE (index 1) ===
        # Barre supérieure (header)
        header = QHBoxLayout()
        header.setContentsMargins(15, 15, 15, 10)

        # Logo/Titre
        title_label = QLabel("🏭 Application de Mesure")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: white;")
        header.addWidget(title_label)

        # Espace flexible pour centrer le contenu
        header.addStretch()

        # Information utilisateur (caché si non connecté)
        self.user_info = QLabel("")
        self.user_info.setStyleSheet("color: #A0A0A0; font-size: 14px;")
        header.addWidget(self.user_info)

        # Bouton changement de mot de passe (accessible aux deux roles)
        self.pw_change_btn = QPushButton("  Changer mot de passe")
        self.pw_change_btn.setToolTip(
            "Changer votre mot de passe"
        )
        self.pw_change_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #A0A0A0;
                padding: 8px 12px;
                border: 1px solid #3D3D50;
                border-radius: 4px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2B2B3D;
                color: white;
                border: 1px solid #4CAF50;
            }
        """)
        self.pw_change_btn.clicked.connect(self._show_password_dialog)
        header.addWidget(self.pw_change_btn)

        # Bouton déconnexion (caché si non connecté)
        self.logout_button = QPushButton("🔓 Déconnexion")
        self.logout_button.setToolTip(
            "Se deconnecter (Ctrl+Maj+L)"
        )
        self.logout_button.setStyleSheet("""
            QPushButton {
                background-color: #F44336;
                color: white;
                padding: 8px 15px;
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #E91E63;
            }
        """)
        self.logout_button.clicked.connect(self.handle_logout)
        header.addWidget(self.logout_button)

        layout.addLayout(header)

        # Barre de navigation (onglets)
        nav_bar = QHBoxLayout()
        nav_bar.setContentsMargins(15, 0, 15, 0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                background-color: #2B2B3D;
                border-radius: 8px;
                padding: 10px;
            }
            QTabBar {
                background-color: #1E1E2E;
                padding-left: 10px;
            }
            QTabBar::tab {
                background-color: #3D3D50;
                color: white;
                padding: 12px 24px;
                margin-right: 5px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:hover {
                background-color: #4D4D60;
            }
            QTabBar::tab:selected {
                background-color: #4CAF50;
            }
        """)

        # Propager le gestionnaire d'authentification à tous les onglets
        auth_mgr = getattr(self.login_view, 'auth_manager', None)
        self.auth_manager = auth_mgr

        self.dashboard_tab = DashboardTab(self, auth_manager=auth_mgr)
        self.connection_tab = ConnectionTab(self, auth_manager=auth_mgr)
        self.measures_tab = MeasuresTab(self, auth_manager=auth_mgr)
        self.tools_tab = ToolsTab(self, auth_manager=auth_mgr)
        self.export_tab = ExportTab(self, auth_manager=auth_mgr)
        self.settings_tab = SettingsTab(self, auth_manager=auth_mgr)
        # Peupler la liste des utilisateurs dans la section mot de passe
        if hasattr(self.settings_tab, '_populate_pw_users'):
            self.settings_tab._populate_pw_users()

        # Connecter le pipeline d'export automatique :
        # Quand une mesure est recue dans MeasuresTab, elle est
        # automatiquement exportee par ExportTab selon les formats actifs.
        self.measures_tab.new_measurement.connect(
            self.export_tab.new_measurement.emit
        )

        # Ajouter les onglets (ordre: Dashboard, Connexion, Mesures, Outils, Export, Paramètres)
        self.tab_widget.addTab(self.dashboard_tab, "📊 Dashboard")
        self.tab_widget.addTab(self.connection_tab, "🔗 Connexion")
        self.tab_widget.addTab(self.measures_tab, "📈 Mesures")
        self.tab_widget.addTab(self.tools_tab, "🔧 Outils")
        self.tab_widget.addTab(self.export_tab, "📤 Export")
        self.tab_widget.addTab(self.settings_tab, "⚙️ Paramètres")

        # Initialiser le systeme de notification d'erreur
        self._error_overlay = ErrorOverlayWidget(self.tab_widget)
        error_manager.set_ui_callback(self._error_overlay.show_error)

        # Synchroniser la date et l'heure avec le systeme
        self._sync_datetime()

        # Redimensionnement du parent => repositionner l'overlay
        self.tab_widget.resizeEvent = self._on_tab_resize

        # Style des onglets basé sur le rôle utilisateur (Supervision vs Opérateur)
        self.update_tab_visibility()

        # Ajuster les polices des combobox apres affichage
        QTimer.singleShot(200, self._refresh_all_fonts)

        nav_bar.addWidget(self.tab_widget)

        # Créer un widget pour la vue principale (header + tabs)
        main_view = QWidget()
        main_layout = QVBoxLayout(main_view)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addLayout(header)
        main_layout.addLayout(nav_bar)

        # Ajouter les deux vues à la pile
        self.stack.addWidget(self.login_view)  # index 0
        self.stack.addWidget(main_view)       # index 1

        # --- Barre de statut ---
        self._setup_status_bar()

        # --- Raccourcis clavier ---
        self._setup_shortcuts()

        # Timer de rafraichissement de la barre de statut (toutes les 5s)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status_bar)
        self._status_timer.start(5000)

        # === Timer d'inactivite — verrouillage automatique ===
        self.IDLE_TIMEOUT_MS = 10 * 60 * 1000  # 10 minutes (configurable)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._lock_session)

        # Installer le filtre d'evenements sur toute la fenetre
        self.installEventFilter(self)

        # Demarrer le timer si l'utilisateur est deja connecte
        if self.current_user is not None:
            self._reset_idle_timer()

    def _reset_idle_timer(self):
        """Reinitialise le timer d'inactivite."""
        self._idle_timer.stop()
        if self.current_user is not None:
            self._idle_timer.start(self.IDLE_TIMEOUT_MS)

    def eventFilter(self, obj, event):
        """Capture les evenements utilisateur pour reinitialiser le timer d'inactivite."""
        event_type = event.type()
        # Toute interaction utilisateur reset le timer
        if event_type in (
            event.Type.MouseButtonPress,
            event.Type.MouseMove,
            event.Type.KeyPress,
            event.Type.Wheel,
            event.Type.TouchBegin,
            event.Type.FocusIn,
        ):
            self._reset_idle_timer()
        return super().eventFilter(obj, event)

    def _lock_session(self):
        """Verrouille la session pour inactivite."""
        if self.current_user is None or self.stack.currentIndex() == 0:
            return
        logger.info("Session verrouillee pour inactivite (%d min)",
                     self.IDLE_TIMEOUT_MS // 60000)
        username = self.current_user.username
        # Arreter le timer — plus besoin
        self._idle_timer.stop()
        # Afficher l'ecran de connexion en mode verrouille
        self.login_view.set_locked_mode(True, username)
        self.stack.setCurrentIndex(0)
        # Audit
        from src.utils.audit_logger import audit
        audit("SESSION_LOCK", username, "Verrouillage automatique pour inactivite")

    def _setup_status_bar(self):
        """Configure la barre de statut avec infos permanentes."""
        status = self.statusBar()
        status.setStyleSheet("""
            QStatusBar {
                background-color: #1A1A2A;
                border-top: 1px solid #2B2B3D;
                color: #A0A0A0;
                font-size: 12px;
            }
            QStatusBar::item {
                border: none;
            }
        """)
        # Widget permanent a gauche — statut BLE
        self._ble_status_label = QLabel("● BLE: pret")
        self._ble_status_label.setStyleSheet("color: #757575; padding: 0 10px;")
        status.addPermanentWidget(self._ble_status_label)

        # Widget permanent a droite — connexions + utilisateur
        self._conn_count_label = QLabel("0 connecte(s)")
        self._conn_count_label.setStyleSheet("color: #757575; padding: 0 10px;")
        status.addPermanentWidget(self._conn_count_label)

        # Message temporaire "Pret"
        status.showMessage("Application de Mesure prete", 3000)

    def _setup_shortcuts(self):
        """Raccourcis clavier globaux de l'application.

        Ctrl+1-6   : basculer entre les onglets
        Ctrl+R     : rafraichir / scanner (onglet actif)
        Ctrl+Maj+L : deconnexion
        Esc        : retour au dashboard
        """
        # Ctrl+1..6 → onglets
        tab_labels = ["Dashboard", "Connexion", "Mesures", "Outils", "Export", "Parametres"]
        for i, lbl in enumerate(tab_labels):
            sc = QShortcut(QKeySequence(f"Ctrl+{i+1}"), self)
            sc.activated.connect(lambda idx=i, name=lbl: self._switch_tab(idx, name))

        # Ctrl+R → rafraichir/relancer scan selon l'onglet actif
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(
            self._refresh_current_tab
        )

        # Ctrl+Maj+L → deconnexion
        sc_logout = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        sc_logout.activated.connect(self._shortcut_logout)

    def _switch_tab(self, index: int, name: str):
        """Bascule vers un onglet et affiche un message dans la barre de statut."""
        if self.stack.currentIndex() == 1:  # seulement en mode principal
            self.tab_widget.setCurrentIndex(index)
            self.statusBar().showMessage(f"Onglet: {name}", 2000)

    def _refresh_current_tab(self):
        """Relance l'action principale de l'onglet actif."""
        if self.stack.currentIndex() != 1:
            return
        idx = self.tab_widget.currentIndex()
        tabs = [self.dashboard_tab, self.connection_tab, self.measures_tab,
                self.tools_tab, self.export_tab, self.settings_tab]
        if idx < len(tabs):
            widget = tabs[idx]
            # Scanner pour l'onglet connexion, rafraichir pour outils
            if hasattr(widget, "scan_devices"):
                widget.scan_devices()
                self.statusBar().showMessage("Scan BLE lance", 2000)
            elif hasattr(widget, "_refresh"):
                widget._refresh()
                self.statusBar().showMessage("Liste raffraichie", 2000)

    def _refresh_status_bar(self):
        """Met a jour les widgets de la barre de statut."""
        if self.stack.currentIndex() == 0:
            return  # login view passee

        # Statut BLE depuis l'onglet connexion
        try:
            ble_status = self.connection_tab.update_ble_status()
            color = "#4CAF50" if "actif" in ble_status else "#757575"
            self._ble_status_label.setText(f"● {ble_status}")
            self._ble_status_label.setStyleSheet(f"color: {color}; padding: 0 10px;")
        except Exception:
            pass

        # Nombre de connexions
        connected = len(self.connection_tab.connected_tools) if hasattr(
            self.connection_tab, "connected_tools"
        ) else 0
        self._conn_count_label.setText(f"{connected} connecte(s)")

    def _shortcut_logout(self):
        """Deconnexion via raccourci clavier."""
        if self.stack.currentIndex() == 1:
            self.handle_logout()

    def _sync_datetime(self):
        """Synchronise la date et l'heure du programme avec le systeme.

        Qt utilise deja QDateTime.currentDateTime() qui lit l'horloge
        systeme. Cette methode explicite la synchronisation au demarrage
        et verifie que l'horloge est correcte.
        """
        now = QDateTime.currentDateTime()
        app_dt = now.toPython()
        logger.info(
            "Horloge synchronisee: %s",
            app_dt.strftime("%Y-%m-%d %H:%M:%S"),
        )
        # Verifier que la date est plausible (pas avant 2020)
        if app_dt.year < 2020:
            logger.warning(
                "Horloge systeme invalide (%d) — verifiez la date systeme.",
                app_dt.year,
            )
            error_manager.error(
                category=ErrorCategory.APPLICATION,
                error_type="startup",
                message="La date du systeme semble incorrecte. "
                        "Verifiez les parametres de date et heure.",
            )

    def _on_tab_resize(self, event):
        """Redimensionne l'overlay d'erreur quand l'onglet change de taille."""
        # Appeler la methode originale de resizeEvent
        QTabWidget.resizeEvent(self.tab_widget, event)
        if hasattr(self, '_error_overlay'):
            self._error_overlay.parent_resized()

    def update_tab_visibility(self):
        """Mise a jour de la visibilite des onglets selon le role."""
        if self.current_user:
            role = self.current_user.role
            # Les onglets outil et parametres sont reserves a la supervision
            tools_tab_index = 3  # L'index de l'onglet Outils
            settings_tab_index = 5  # L'index de l'onglet Parametres

            is_supervisor = (role == "supervision")

            self.tab_widget.setTabEnabled(tools_tab_index, is_supervisor)
            self.tab_widget.setTabToolTip(
                tools_tab_index,
                "Reserve au Superviseur" if not is_supervisor else "Gestion des outils de mesure"
            )

            self.tab_widget.setTabEnabled(settings_tab_index, is_supervisor)
            self.tab_widget.setTabToolTip(
                settings_tab_index,
                "Reserve au Superviseur" if not is_supervisor else "Configuration de l'application"
            )
        else:
            # Par defaut, tout visible
            for i in range(self.tab_widget.count()):
                self.tab_widget.setTabEnabled(i, True)
                self.tab_widget.setTabToolTip(i, "")

    def show_login(self):
        """Affiche l'écran de connexion (index 0 du stack)."""
        self.stack.setCurrentIndex(0)

    def show_main_view(self):
        """Affiche l'interface principale (index 1 du stack)."""
        if self.current_user:
            role_label = "Superviseur" if self.current_user.role == "supervision" else "Operateur"
            self.user_info.setText(f"  {self.current_user.username} ({role_label})")
            self.pw_change_btn.setVisible(True)

        # Basculer vers la vue principale (déjà ajoutée à l'index 1 dans setup_ui)
        self.stack.setCurrentIndex(1)

        # Mettre à jour la visibilité des onglets selon le rôle
        self.update_tab_visibility()

    def handle_login_success(self, user):
        """Gère la connexion réussie."""
        self.current_user = user

        # Reinitialiser le mode verrouillage
        self.login_view.set_locked_mode(False)

        # Verifier si l'operateur est bloque → forcer le renouvellement
        if (user.role == "supervision"
                and self.auth_manager
                and self.auth_manager.is_operator_blocked()):
            self._show_operator_renewal_dialog()
            # Apres le renouvellement, l'operateur est deverrouille
            # mais on reste connecte en tant que superviseur

        self.show_main_view()

        # Demarrer le timer d'inactivite
        self._reset_idle_timer()

        # Demarrer le gestionnaire Bluetooth en tache asynchrone (non bloquant)
        from src.models.bluetooth_manager import BluetoothManager
        manager = BluetoothManager()
        task = asyncio.create_task(manager.start())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def handle_root_unlock_success(self, user):
        """Gère la connexion apres deverrouillage par mot de passe root.

        Ouvre immediatement le dialogue de renouvellement du mot de passe
        superviseur avant de montrer la vue principale.
        """
        self.current_user = user
        self.login_view.set_locked_mode(False)

        # Forcer le renouvellement du mot de passe superviseur
        self._show_supervisor_renewal_dialog()

        self.show_main_view()
        self._reset_idle_timer()

        # Demarrer le gestionnaire Bluetooth
        from src.models.bluetooth_manager import BluetoothManager
        manager = BluetoothManager()
        task = asyncio.create_task(manager.start())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _show_operator_renewal_dialog(self):
        """Ouvre le dialogue de renouvellement du mot de passe operateur.

        Le superviseur definit un nouveau mot de passe pour l'operateur,
        ce qui deverrouille automatiquement le compte.
        """
        dialog = PasswordRenewalDialog(
            target_username="operateur",
            target_display="Operateur",
            parent=self
        )
        # Titre et message personnalises
        dialog.setWindowTitle("Deverrouillage Operateur")
        title = dialog.findChild(QLabel)
        # On modifie la description
        for child in dialog.findChildren(QLabel):
            if "obligatoire" in child.text():
                child.setText(
                    "Le compte Operateur est bloque.\n"
                    "Definissez un nouveau mot de passe\n"
                    "pour le deverrouiller."
                )
                break

        result = dialog.exec()
        if result == QDialog.Accepted:
            new_password = dialog.get_password()
            ok, msg = self.auth_manager.change_password_admin(
                "operateur", new_password
            )
            if ok:
                # Deverrouiller le compte operateur
                self.auth_manager.unlock_operator()
                QMessageBox.information(
                    self, "Succes",
                    "Compte Operateur deverrouille.\n"
                    "Nouveau mot de passe defini."
                )
            else:
                QMessageBox.warning(self, "Erreur", msg)

    def _show_supervisor_renewal_dialog(self):
        """Ouvre le dialogue de renouvellement du mot de passe superviseur.

        Apres deverrouillage root, le superviseur doit changer son mot de passe.
        """
        dialog = PasswordRenewalDialog(
            target_username="Superviseur",
            target_display="Superviseur",
            parent=self
        )
        dialog.setWindowTitle("Renouvellement mot de passe Superviseur")
        for child in dialog.findChildren(QLabel):
            if "obligatoire" in child.text():
                child.setText(
                    "Compte deverrouille par APU.\n"
                    "Veuillez definir un nouveau mot de passe."
                )
                break

        result = dialog.exec()
        if result == QDialog.Accepted:
            new_password = dialog.get_password()
            ok, msg = self.auth_manager.change_password_admin(
                "Superviseur", new_password
            )
            if ok:
                QMessageBox.information(
                    self, "Succes",
                    "Mot de passe Superviseur mis a jour.\n"
                    "L'application est prete."
                )
            else:
                QMessageBox.warning(self, "Erreur", msg)

    def handle_logout(self):
        """Gère la déconnexion."""
        reply = QMessageBox.question(
            self,
            "Déconnexion",
            "Voulez-vous vraiment vous déconnecter ?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # Arreter le timer d'inactivite
            self._idle_timer.stop()

            # Reinitialiser le mode verrouillage
            self.login_view.set_locked_mode(False)

            # Nettoyer l'état utilisateur
            self.current_user = None

            # Arreter le gestionnaire Bluetooth
            from src.models.bluetooth_manager import BluetoothManager
            manager = BluetoothManager()
            task = asyncio.create_task(manager.stop())
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

            # Retour à la connexion
            self.show_login()

    def _show_password_dialog(self):
        """Ouvre un dialogue de changement de mot de passe (accessible aux deux roles)."""
        if not self.current_user or not self.auth_manager:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Changer le mot de passe")
        dialog.setFixedSize(380, 250)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        # Titre
        title = QLabel(f"Changement de mot de passe — {self.current_user.username}")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: white;")
        layout.addWidget(title)

        # Formulaire
        form = QFormLayout()
        form.setSpacing(10)

        current_pw = QLineEdit()
        current_pw.setEchoMode(QLineEdit.Password)
        current_pw.setPlaceholderText("Mot de passe actuel")
        current_pw.setStyleSheet("padding: 8px; border: 1px solid #444; border-radius: 4px; background-color: #2B2B3D; color: white;")
        form.addRow("Mot de passe actuel:", current_pw)

        new_pw = QLineEdit()
        new_pw.setEchoMode(QLineEdit.Password)
        new_pw.setPlaceholderText("Nouveau mot de passe (min 4 car.)")
        new_pw.setStyleSheet("padding: 8px; border: 1px solid #444; border-radius: 4px; background-color: #2B2B3D; color: white;")
        form.addRow("Nouveau mot de passe:", new_pw)

        confirm_pw = QLineEdit()
        confirm_pw.setEchoMode(QLineEdit.Password)
        confirm_pw.setPlaceholderText("Confirmation")
        confirm_pw.setStyleSheet("padding: 8px; border: 1px solid #444; border-radius: 4px; background-color: #2B2B3D; color: white;")
        form.addRow("Confirmer:", confirm_pw)

        layout.addLayout(form)

        # Boutons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Annuler")
        cancel_btn.setStyleSheet("background-color: #757575; color: white; padding: 8px 20px; border: none; border-radius: 4px;")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        submit_btn = QPushButton("Valider")
        submit_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px 20px; border: none; border-radius: 4px; font-weight: bold;")
        btn_layout.addWidget(submit_btn)

        layout.addLayout(btn_layout)

        status_label = QLabel("")
        status_label.setStyleSheet("color: #FF9800; font-size: 12px;")
        layout.addWidget(status_label)

        def on_submit():
            current = current_pw.text()
            new = new_pw.text()
            confirm = confirm_pw.text()

            if not current or not new or not confirm:
                status_label.setText("Tous les champs sont obligatoires.")
                return
            if new != confirm:
                status_label.setText("Les nouveaux mots de passe ne correspondent pas.")
                return
            if len(new) < 4:
                status_label.setText("Le nouveau mot de passe doit contenir au moins 4 caracteres.")
                return

            success, msg = self.auth_manager.change_password(
                self.current_user.username, current, new
            )
            if success:
                QMessageBox.information(dialog, "Succes", "Mot de passe modifie avec succes.")
                dialog.accept()
            else:
                status_label.setText(msg)

        submit_btn.clicked.connect(on_submit)
        new_pw.returnPressed.connect(confirm_pw.setFocus)
        confirm_pw.returnPressed.connect(submit_btn.click)

        dialog.exec()

    def _refresh_all_fonts(self):
        """Recalibre les polices de tous les combobox et widgets.

        Parcourt recursivement tous les enfants pour :
          - QComboBox : adapter la police de la popup (QListView)
          - QPushButton important : forcer le gras + taille
        """
        font = FontManager.scaled(window=self)
        self._apply_font_recursive(self, font)

    def _apply_font_recursive(self, widget: QWidget, base_font: QFont):
        """Applique la police a un widget et ses enfants recursivement.

        Args:
            widget: Widget racine.
            base_font: Police de base a utiliser.
        """
        # QComboBox : popup + font
        if isinstance(widget, QComboBox):
            combo = widget
            combo.setFont(base_font)
            view = combo.view()
            if view:
                view.setFont(base_font)

        # QPushButton important : plus gros + gras
        elif isinstance(widget, QPushButton):
            btn = widget
            txt = btn.text().lower()
            if any(kw in txt for kw in ("scan", "connect", "ajout", "sauvegard",
                                         "deconnect", "arreter", "ajouter")):
                bold_font = FontManager.scaled(base=14, bold=True, window=self)
                btn.setFont(bold_font)

        # Parcourir les enfants
        for child in widget.children():
            if isinstance(child, QWidget):
                self._apply_font_recursive(child, base_font)
