"""Login view - Ecran de connexion utilisateur."""
import os
import sys
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QLineEdit, QPushButton, QComboBox, QMessageBox)
from PySide6.QtCore import Signal, Qt, QTimer
from src.models.user import AuthManager
from src.views.widgets import ShortcutsFooter, make_password_with_toggle
from src.utils.secure_clear import secure_clear_string

# Mapping : affichage → nom interne
DISPLAY_TO_USERNAME = {
    "Superviseur": "Superviseur",
    "Operateur": "operateur",
}

USERNAME_TO_DISPLAY = {
    "Superviseur": "Superviseur",
    "operateur": "Operateur",
}


class LoginView(QWidget):
    """Vue d'authentification de l'utilisateur."""

    login_success = Signal(object)       # Emet l'objet User connecte
    root_unlock_success = Signal(object)  # Emet l'objet User apres deverrouillage root

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application de Mesure - Connexion")
        self.setMinimumSize(400, 350)
        self._locked_mode = False
        self._locked_user = None
        self.setup_ui()

        # Initialiser le gestionnaire d'authentification
        self.auth_manager = AuthManager()

    def setup_ui(self):
        """Configure l'interface utilisateur."""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(40, 40, 40, 40)

        # Titre
        title = QLabel("Application de Mesure")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: white;
            padding: 10px;
        """)
        layout.addWidget(title)

        # Sous-titre
        subtitle = QLabel("v1.0 - Connexion securisee")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("""
            font-size: 14px;
            color: #A0A0A0;
            margin-bottom: 20px;
        """)
        layout.addWidget(subtitle)

        # === Formulaire de connexion ===
        form_layout = QVBoxLayout()
        form_layout.setSpacing(12)

        # Selection de l'utilisateur
        user_label = QLabel("Utilisateur:")
        user_label.setStyleSheet("color: white; font-weight: bold;")
        form_layout.addWidget(user_label)

        self.user_combo = QComboBox()
        self.user_combo.addItems(["Superviseur", "Operateur"])
        self.user_combo.setStyleSheet("""
            QComboBox {
                padding: 10px;
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #2B2B3D;
                color: white;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 10px;
            }
            QComboBox::down-arrow {
                image: none;
                border: solid #A0A0A0;
                border-width: 0 2px 2px 0;
                padding: 3px;
                transform: rotate(45deg);
            }
            QComboBox:hover {
                border: 1px solid #4CAF50;
            }
            QComboBox QAbstractItemView {
                background-color: #2B2B3D;
                color: white;
                selection-background-color: #4CAF50;
                border: 1px solid #444;
            }
        """)
        form_layout.addWidget(self.user_combo)

        # Mot de passe
        password_label = QLabel("Mot de passe:")
        password_label.setStyleSheet("color: white; font-weight: bold;")
        form_layout.addWidget(password_label)

        self.pw_frame, self.password_input, self.pw_toggle = make_password_with_toggle(
            "Entrez votre mot de passe"
        )
        self.password_input.returnPressed.connect(self._on_return_pressed)
        form_layout.addWidget(self.pw_frame)

        # === Messages d'etat ===

        # Message de verrouillage session (orange)
        self.lock_msg = QLabel("")
        self.lock_msg.setAlignment(Qt.AlignCenter)
        self.lock_msg.setStyleSheet("""
            font-size: 14px;
            color: #FF9800;
            font-weight: bold;
            padding: 8px;
            background-color: #1E1E2E;
            border: 1px solid #FF9800;
            border-radius: 6px;
            margin-top: 10px;
        """)
        self.lock_msg.setVisible(False)
        form_layout.addWidget(self.lock_msg)

        # Message blocage operateur (rouge)
        self.operator_block_msg = QLabel(
            "Session Operateur bloquee.\n"
            "Veuillez contacter votre Superviseur\n"
            "pour deverrouiller le compte."
        )
        self.operator_block_msg.setAlignment(Qt.AlignCenter)
        self.operator_block_msg.setStyleSheet("""
            font-size: 14px;
            color: #F44336;
            font-weight: bold;
            padding: 10px;
            background-color: #2D1B1B;
            border: 1px solid #F44336;
            border-radius: 6px;
            margin-top: 10px;
        """)
        self.operator_block_msg.setVisible(False)
        form_layout.addWidget(self.operator_block_msg)

        # Message blocage superviseur (rouge)
        self.supervisor_block_msg = QLabel(
            "Compte Superviseur verrouille.\n"
            "Veuillez contacter votre APU\n"
            "pour deverrouiller l'application."
        )
        self.supervisor_block_msg.setAlignment(Qt.AlignCenter)
        self.supervisor_block_msg.setStyleSheet("""
            font-size: 14px;
            color: #F44336;
            font-weight: bold;
            padding: 10px;
            background-color: #2D1B1B;
            border: 1px solid #F44336;
            border-radius: 6px;
            margin-top: 10px;
        """)
        self.supervisor_block_msg.setVisible(False)
        form_layout.addWidget(self.supervisor_block_msg)

        # === Bouton de connexion ===
        self.login_button = QPushButton("SE CONNECTER")
        self.login_button.setDefault(True)
        self.login_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 12px;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #45A049;
            }
            QPushButton:pressed {
                background-color: #3D8B40;
            }
            QPushButton:disabled {
                background-color: #3D3D50;
                color: #757575;
            }
        """)
        self.login_button.clicked.connect(self.handle_login)
        form_layout.addWidget(self.login_button)

        # === Section deverrouillage root (cachée par defaut) ===
        self.root_unlock_layout = QVBoxLayout()
        self.root_unlock_layout.setSpacing(8)

        self.root_label = QLabel("Mot de passe APU (deverrouillage):")
        self.root_label.setStyleSheet("color: #FF9800; font-weight: bold;")
        self.root_label.setVisible(False)
        self.root_unlock_layout.addWidget(self.root_label)

        self.root_pw_frame, self.root_password_input, self.root_pw_toggle = make_password_with_toggle(
            "Entrez le mot de passe APU"
        )
        # Surligner en orange pour le mode root
        self.root_password_input.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 1px solid #FF9800;
                border-radius: 4px;
                background-color: #2B2B3D;
                color: white;
            }
            QLineEdit:focus {
                border: 1px solid #F44336;
            }
        """)
        self.root_password_input.returnPressed.connect(self._try_root_unlock)
        self.root_pw_frame.setVisible(False)
        self.root_unlock_layout.addWidget(self.root_pw_frame)

        self.root_unlock_btn = QPushButton("DEVERROUILLER")
        self.root_unlock_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                padding: 10px;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        self.root_unlock_btn.setVisible(False)
        self.root_unlock_btn.clicked.connect(self._try_root_unlock)
        self.root_unlock_layout.addWidget(self.root_unlock_btn)

        form_layout.addLayout(self.root_unlock_layout)

        # === Bouton OK pour prendre acte du blocage operateur ===
        self.operator_ack_btn = QPushButton("OK")
        self.operator_ack_btn.setStyleSheet("""
            QPushButton {
                background-color: #3D3D50;
                color: white;
                padding: 8px 20px;
                border: 1px solid #F44336;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4D4D60;
            }
        """)
        self.operator_ack_btn.setVisible(False)
        self.operator_ack_btn.clicked.connect(self._acknowledge_operator_block)
        form_layout.addWidget(self.operator_ack_btn)

        layout.addLayout(form_layout)

        # Instructions pour les tests si DEV_MODE est active
        if os.environ.get("DEV_MODE", "false").lower() in ("true", "1", "yes"):
            help_label = QLabel("Tests: Superviseur -> SPlate-shop, Operateur -> Plate-shop")
            help_label.setAlignment(Qt.AlignCenter)
            help_label.setStyleSheet("color: #FF9800; font-size: 12px; margin-top: 20px;")
            layout.addWidget(help_label)

        # Lexique de raccourcis clavier
        layout.addStretch()
        layout.addWidget(ShortcutsFooter([
            ("Enter", "Valider la connexion"),
        ]))

        self.setLayout(layout)

    # --- Appels bloquants Qt ---

    def _show_operator_block_dialog(self):
        """Affiche la boite de dialogue de blocage operateur."""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Compte bloque")
        msg.setText(
            "Session Operateur bloquee.\n\n"
            "Veuillez contacter votre Superviseur\n"
            "pour deverrouiller le compte."
        )
        msg.exec()

    def _show_operator_block_ui(self):
        """Passe l'interface en mode blocage operateur."""
        self.operator_block_msg.setVisible(True)
        self.operator_ack_btn.setVisible(True)
        # Desactiver les controles de login pour operateur
        self.pw_frame.setVisible(False)
        self.login_button.setVisible(False)
        # Le combo reste visible mais on le desactive
        self.user_combo.setEnabled(False)
        self.user_combo.clear()

    def _acknowledge_operator_block(self):
        """L'utilisateur a pris connaissance du blocage operateur."""
        self.operator_block_msg.setVisible(False)
        self.operator_ack_btn.setVisible(False)

        # Remettre le formulaire dans un etat fonctionnel pour le superviseur
        self.user_combo.setEnabled(True)
        self.user_combo.clear()
        self.user_combo.addItem("Superviseur")
        self.user_combo.setCurrentIndex(0)

        self.pw_frame.setVisible(True)
        self.login_button.setVisible(True)

        # Re-afficher le message bloque en permanence
        self.operator_block_msg.setText(
            "Compte Operateur bloque en attente\n"
            "de deverrouillage par le Superviseur."
        )
        self.operator_block_msg.setStyleSheet("""
            font-size: 12px;
            color: #FF9800;
            font-weight: bold;
            padding: 6px;
            background-color: #1E1E2E;
            border: 1px solid #FF9800;
            border-radius: 6px;
            margin-top: 10px;
        """)
        self.operator_block_msg.setVisible(True)

    def _show_root_unlock_ui(self):
        """Passe l'interface en mode deverrouillage root."""
        # Cacher le formulaire normal
        self.user_combo.setEnabled(False)
        self.pw_frame.setVisible(False)
        self.login_button.setVisible(False)

        # Afficher le message
        self.supervisor_block_msg.setVisible(True)

        # Afficher la section root
        self.root_label.setVisible(True)
        self.root_pw_frame.setVisible(True)
        self.root_unlock_btn.setVisible(True)
        self.root_password_input.setFocus()

    def _try_root_unlock(self):
        """Tente le deverrouillage root."""
        root_password = self.root_password_input.text()
        auth = self.auth_manager

        if auth.verify_root_password(root_password):
            # Deverrouiller le superviseur
            auth.unlock_supervisor("Superviseur")

            # Creer l'utilisateur superviseur
            from src.models.user import User
            user = User(username="Superviseur", role="supervision")
            user.last_login = __import__('datetime').datetime.now()
            auth.current_user = user

            # Audit
            from src.utils.audit_logger import audit
            audit("ROOT_UNLOCK", "Superviseur",
                  "Deverrouillage reussi par mot de passe root")

            # Effacer le mot de passe
            self.root_password_input.clear()
            secure_clear_string(root_password)

            # Emettre le signal special
            self.root_unlock_success.emit(user)

        else:
            # Mot de passe root incorrect
            self.root_password_input.clear()
            secure_clear_string(root_password)
            QMessageBox.critical(
                self,
                "Erreur",
                "Mot de passe APU incorrect.\n"
                "Veuillez reessayer."
            )

    def _show_force_password_change_dialog(self, username: str):
        """Affiche un dialogue pour forcer le changement de mot de passe."""
        # Creer une boite modale avec deux champs (nouveau + confirmation)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Mot de passe initial")
        dialog.setIcon(QMessageBox.Information)
        dialog.setText(f"Utilisateur {username} - Premier connexion")
        dialog.setInformativeText(
            "Le mot de passe par defaut a ete detecte.\n"
            "Veuillez le modifier pour securiser votre compte."
        )

        # Champs de saisie
        pw_layout = QVBoxLayout()

        label_new = QLabel("Nouveau mot de passe:")
        label_new.setStyleSheet("font-weight: bold;")
        pw_layout.addWidget(label_new)

        self.new_password_input = QLineEdit()
        self.new_password_input.setEchoMode(QLineEdit.Password)
        self.new_password_input.returnPressed.connect(self._handle_force_password_change)
        pw_layout.addWidget(self.new_password_input)

        label_confirm = QLabel("Confirmer le nouveau mot de passe:")
        label_confirm.setStyleSheet("font-weight: bold;")
        pw_layout.addWidget(label_confirm)

        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input.returnPressed.connect(self._handle_force_password_change)
        pw_layout.addWidget(self.confirm_password_input)

        dialog.setLayout(pw_layout)

        # Ajouter des boutons (OK + Cancel)
        ok_btn = dialog.addButton("VALIDER", QMessageBox.YesRole)
        cancel_btn = dialog.addButton("ANNULER", QMessageBox.NoRole)

        dialog.exec()

        if dialog.clickedButton() == ok_btn:
            self._handle_force_password_change(username)

    def _handle_force_password_change(self, username: str):
        """Traite le changement de mot de passe force."""
        new_pw = self.new_password_input.text()
        confirm_pw = self.confirm_password_input.text()

        # Nettoyer les champs
        self.new_password_input.clear()
        self.confirm_password_input.clear()
        secure_clear_string(new_pw)
        secure_clear_string(confirm_pw)

        if not new_pw or not confirm_pw:
            QMessageBox.warning(
                self,
                "Erreur",
                "Veuillez saisir un nouveau mot de passe et une confirmation."
            )
            return

        if len(new_pw) < 4:
            QMessageBox.warning(
                self,
                "Erreur",
                "Le nouveau mot de passe doit contenir au moins 4 caracteres."
            )
            return

        if new_pw != confirm_pw:
            QMessageBox.warning(
                self,
                "Erreur",
                "Les deux mots de passe ne correspondent pas."
            )
            return

        # Changer le mot de passe via l'AuthManager (en tant que superviseur ou root)
        success, message = self.auth_manager.change_password_admin(username, new_pw)

        if success:
            QMessageBox.information(
                self,
                "Succes",
                "Mot de passe modifie avec succes.\n"
                "Vous pouvez maintenant vous connecter."
            )
            # Cacher le dialogue (on continue avec la connexion normale)
            pass
        else:
            QMessageBox.critical(
                self,
                "Erreur",
                f"Echec du changement de mot de passe:\n{message}"
            )

    # --- Gestion des tentatives echouees ---

    def _handle_failed_login(self, username: str):
        """Gere l'affichage apres un echec de connexion.

        Verifie les blocages et adapte l'interface en consequence.
        """
        auth = self.auth_manager

        if username == "operateur" and auth.is_operator_blocked():
            self._show_operator_block_dialog()
            self._show_operator_block_ui()
            return

        if username == "Superviseur" and auth.is_supervisor_blocked():
            self._show_root_unlock_ui()
            return

        # Message generique pour un echec normal
        QMessageBox.critical(
            self,
            "Erreur",
            "Identifiants incorrects.\n"
            "Veuillez reessayer."
        )

    # --- Connexion ---

    def handle_login(self):
        """Gere la soumission du formulaire de connexion."""
        display_name = self.user_combo.currentText()
        username = DISPLAY_TO_USERNAME.get(display_name, display_name)
        password = self.password_input.text()

        if not username or not password:
            secure_clear_string(password)
            QMessageBox.warning(
                self, 
                "Erreur", 
                "Veuillez selectionner un utilisateur et saisir le mot de passe."
            )
            return

        # Authentifier l'utilisateur
        user = self.auth_manager.authenticate(username, password)

        # Effacer le mot de passe en memoire quoi qu'il arrive
        self.password_input.clear()
        secure_clear_string(password)

        if user:
            # Si c'est un mot de passe initial, forcer le changement AVANT connexion
            if getattr(user, 'is_initial_password', True):
                self._show_force_password_change_dialog(username)
                return  # Ne pas emitter login_success ici - attendre que l'utilisateur change

            self.login_success.emit(user)
        else:
            self._handle_failed_login(username)

    def _on_return_pressed(self):
        """Appuye sur Entree dans un champ = soumettre le formulaire."""
        # Si on est en mode root unlock, le root_password_input a son propre handler
        self.handle_login()

    def set_locked_mode(self, locked: bool, username: str = None):
        """Active ou desactive le mode verrouillage session.

        En mode verrouille, un message orange indique que la session
        a ete verrouillee pour cause d'inactivite.
        """
        self._locked_mode = locked
        self._locked_user = username
        if locked:
            self.lock_msg.setText(
                f"Session verrouillee pour inactivite.\n"
                f"Veuillez vous reconnecter, {username}."
            )
            self.lock_msg.setVisible(True)
            # Preselectionner l'utilisateur verrouille
            display = USERNAME_TO_DISPLAY.get(username, "Superviseur")
            self.user_combo.clear()
            self.user_combo.addItems(["Superviseur", "Operateur"])
            idx = self.user_combo.findText(display)
            if idx >= 0:
                self.user_combo.setCurrentIndex(idx)
            self.pw_frame.setVisible(True)
            self.login_button.setVisible(True)
            self.password_input.setFocus()
        else:
            self.lock_msg.setVisible(False)
            self.lock_msg.setText("")
            self.user_combo.clear()
            self.user_combo.addItems(["Superviseur", "Operateur"])
            self.user_combo.setCurrentIndex(0)

