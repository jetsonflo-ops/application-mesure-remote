"""Settings tab - Configuration generale et seuils d'alerte."""
import os
import json
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QPushButton, QFrame, QComboBox, QLineEdit, 
                               QGroupBox, QCheckBox, QMessageBox, QScrollArea)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator, QDoubleValidator, QShortcut, QKeySequence
from src.views.widgets import ShortcutsFooter, make_password_with_toggle
from src.utils.secure_clear import secure_clear_string
from src.utils.file_crypto import encrypt_json, decrypt_json

class SettingsTab(QWidget):
    """Onglet de configuration des parametres."""
    
    def __init__(self, parent=None, auth_manager=None):
        super().__init__(parent)
        
        # Gestionnaire d'authentification (pour changement de mot de passe)
        self.auth_manager = auth_manager
        
        # Chemin de persistance
        app_dir = os.path.join(os.path.expanduser("~"), ".application_mesure")
        self.settings_path = os.path.join(app_dir, "settings.json")
        
        # Charger les parametres depuis le fichier
        self.settings = self._load_settings()
        
        self.setup_ui()
    
    def _load_settings(self) -> dict:
        """Charge les parametres depuis le fichier JSON chiffre."""
        defaults = {
            'bluetooth_enabled': True,
            'discovery_mode': 'auto',
            'auto_reconnect': True,
            'max_reconnect_delay': 60,
            'roughness_threshold': 1.0,
            'flatness_threshold': 2.0,
            'sound_notifications': True,
            'email_alerts': False,
            'auto_export_interval': 30
        }

        if not os.path.exists(self.settings_path):
            return defaults

        try:
            # Tentative dechiffrement AES-256-GCM
            data = decrypt_json(self.settings_path)
            if isinstance(data, dict):
                defaults.update(data)
                return defaults
        except Exception:
            pass

        # Fallback: fichier plaintext (migration silencieuse)
        try:
            with open(self.settings_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    defaults.update(loaded)
        except (json.JSONDecodeError, IOError):
            pass

        return defaults
    
    def _save_settings(self):
        """Sauvegarde les parametres dans un fichier JSON chiffre AES-256-GCM."""
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        if not encrypt_json(self.settings_path, self.settings):
            # Fallback plaintext si le chiffrement echoue
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)
    
    def setup_ui(self):
        """Configure l'interface des parametres."""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Titre
        title = QLabel("Parametres Generaux")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: white;")
        layout.addWidget(title)

        # Création de la zone de défilement (Scroll Area)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
        """)

        # Widget conteneur pour le contenu défilable
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background-color: transparent;")
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(15)
        scroll_layout.setContentsMargins(0, 0, 10, 0)
        
        # Groupe: Connexion Bluetooth
        bt_group = QGroupBox("Parametres de Connexion")
        bt_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: white;
                border: 1px solid #444;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 20px;
            }
        """)
        
        bt_layout = QVBoxLayout(bt_group)
        
        # Bluetooth active
        self.bt_enabled_check = QCheckBox("Bluetooth active")
        self.bt_enabled_check.setToolTip("Activer ou desactiver le module Bluetooth")
        self.bt_enabled_check.setChecked(self.settings['bluetooth_enabled'])
        self.bt_enabled_check.setStyleSheet("color: white;")
        bt_layout.addWidget(self.bt_enabled_check)
        
        # Mode de decouverte
        discovery_label = QLabel("Mode de decouverte:")
        discovery_label.setToolTip("Mode de decouverte des appareils BLE")
        discovery_label.setStyleSheet("color: white; font-weight: bold; padding-bottom: 5px;")
        bt_layout.addWidget(discovery_label)
        
        self.discovery_combo = QComboBox()
        self.discovery_combo.setToolTip("Auto: detection automatique, Actif: scan permanent, Passif: ecoute seule")
        self.discovery_combo.addItems(["Auto", "Actif", "Passif"])
        self.discovery_combo.setStyleSheet("""
            QComboBox {
                padding: 10px;
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #2B2B3D;
                color: white;
            }
        """)
        bt_layout.addWidget(self.discovery_combo)
        
        # Reconnexion automatique
        reconnect_label = QLabel("Reconnexion automatique:")
        reconnect_label.setStyleSheet("color: white; font-weight: bold; padding-bottom: 5px;")
        bt_layout.addWidget(reconnect_label)
        
        self.reconnect_combo = QComboBox()
        self.reconnect_combo.addItems(["Oui (backoff exponentiel)", "Non"])
        self.reconnect_combo.setStyleSheet("""
            QComboBox {
                padding: 10px;
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #2B2B3D;
                color: white;
            }
        """)
        bt_layout.addWidget(self.reconnect_combo)
        
        # Delai max de reconnexion
        delay_label = QLabel("Delai max de reconnexion (secondes):")
        delay_label.setStyleSheet("color: white; font-weight: bold; padding-bottom: 5px;")
        bt_layout.addWidget(delay_label)
        
        self.delay_input = QLineEdit(str(self.settings['max_reconnect_delay']))
        self.delay_input.setValidator(QIntValidator(1, 300))
        self.delay_input.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #2B2B3D;
                color: white;
            }
        """)
        bt_layout.addWidget(self.delay_input)
        
        scroll_layout.addWidget(bt_group)
        
        # Groupe: Seuils d'alerte
        threshold_group = QGroupBox("Seuils d'Alerte")
        threshold_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: white;
                border: 1px solid #444;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 20px;
            }
        """)
        
        threshold_layout = QVBoxLayout(threshold_group)
        
        # Seuil de rugosite
        roughness_label = QLabel("Rugosite maximale (um Ra):")
        roughness_label.setStyleSheet("color: white; font-weight: bold; padding-bottom: 5px;")
        threshold_layout.addWidget(roughness_label)
        
        self.roughness_input = QLineEdit(str(self.settings['roughness_threshold']))
        self.roughness_input.setValidator(QDoubleValidator(0.01, 100.0, 2))
        self.roughness_input.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #2B2B3D;
                color: white;
            }
        """)
        threshold_layout.addWidget(self.roughness_input)
        
        # Seuil de deviation planéite
        flatness_label = QLabel("Deviation planéite maximale (mm):")
        flatness_label.setStyleSheet("color: white; font-weight: bold; padding-bottom: 5px;")
        threshold_layout.addWidget(flatness_label)
        
        self.flatness_input = QLineEdit(str(self.settings['flatness_threshold']))
        self.flatness_input.setValidator(QDoubleValidator(0.01, 10.0, 2))
        self.flatness_input.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #2B2B3D;
                color: white;
            }
        """)
        threshold_layout.addWidget(self.flatness_input)
        
        scroll_layout.addWidget(threshold_group)
        
        # Groupe: Notifications
        notification_group = QGroupBox("Notifications et Alertes")
        notification_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: white;
                border: 1px solid #444;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 20px;
            }
        """)
        
        notification_layout = QVBoxLayout(notification_group)
        
        # Notifications sonores
        self.sound_check = QCheckBox("Activer les notifications sonores")
        self.sound_check.setChecked(self.settings['sound_notifications'])
        self.sound_check.setStyleSheet("color: white;")
        notification_layout.addWidget(self.sound_check)
        
        # Alertes email
        self.email_check = QCheckBox("Envoyer des alertes par email")
        self.email_check.setChecked(self.settings['email_alerts'])
        self.email_check.setStyleSheet("color: white;")
        notification_layout.addWidget(self.email_check)
        
        scroll_layout.addWidget(notification_group)
        
        # Groupe: Export automatique
        auto_export_group = QGroupBox("Export Automatique")
        auto_export_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: white;
                border: 1px solid #444;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 20px;
            }
        """)
        
        auto_export_layout = QVBoxLayout(auto_export_group)
        
        # Intervalle d'export automatique
        interval_label = QLabel("Intervalle d'export (minutes):")
        interval_label.setStyleSheet("color: white; font-weight: bold; padding-bottom: 5px;")
        auto_export_layout.addWidget(interval_label)
        
        self.interval_input = QLineEdit(str(self.settings['auto_export_interval']))
        self.interval_input.setValidator(QIntValidator(1, 1440))
        self.interval_input.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 1px solid #444;
                border-radius: 4px;
                background-color: #2B2B3D;
                color: white;
            }
        """)
        auto_export_layout.addWidget(self.interval_input)
        
        scroll_layout.addWidget(auto_export_group)
        
        # NOUVEAU: Groupe de chiffrement modulaire (superviseur uniquement)
        encryption_group = QGroupBox("Chiffrement Modulaire")
        encryption_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: white;
                border: 1px solid #444;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 20px;
            }
        """)
        
        encryption_layout = QVBoxLayout(encryption_group)
        
        # Chiffrement réception BLE
        self.ble_encryption_check = QCheckBox("Chiffrer la réception Bluetooth (AES-256-GCM)")
        self.ble_encryption_check.setToolTip(
            "Active le chiffrement des données reçues du BLE. Désactivé par défaut pour performance."
        )
        # Utiliser les paramètres chargés ou les valeurs par défaut
        ble_encrypted = self.settings.get('ble_receive_encryption', False)
        self.ble_encryption_check.setChecked(ble_encrypted)
        self.ble_encryption_check.setStyleSheet("color: white;")
        encryption_layout.addWidget(self.ble_encryption_check)
        
        # Chiffrement export fichier
        self.file_encryption_check = QCheckBox("Chiffrer les exports de fichiers (AES-256-GCM)")
        self.file_encryption_check.setToolTip(
            "Active le chiffrement des fichiers Excel/CSV exportés. Activé par défaut pour sécurité."
        )
        file_encrypted = self.settings.get('file_export_encryption', True)
        self.file_encryption_check.setChecked(file_encrypted)
        self.file_encryption_check.setStyleSheet("color: white;")
        encryption_layout.addWidget(self.file_encryption_check)
        
        scroll_layout.addWidget(encryption_group)
        
        # Groupe: Gestion des mots de passe (depliable)
        if self.auth_manager:
            # Bouton toggle pour ouvrir/fermer le panneau mot de passe
            self.pw_toggle_btn = QPushButton("  Changer le mot de passe")
            self.pw_toggle_btn.setCheckable(True)
            self.pw_toggle_btn.setChecked(False)
            self.pw_toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2B2B3D;
                    color: white;
                    text-align: left;
                    padding: 12px 15px;
                    border: 1px solid #444;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #3D3D50;
                    border: 1px solid #2196F3;
                }
                QPushButton:checked {
                    background-color: #1A1A2E;
                    border: 1px solid #2196F3;
                }
            """)
            scroll_layout.addWidget(self.pw_toggle_btn)
            
            # Conteneur des champs mot de passe (caché par défaut)
            self.pw_container = QFrame()
            self.pw_container.setStyleSheet("""
                QFrame {
                    background-color: #1E1E2E;
                    border: 1px solid #333;
                    border-radius: 0 0 8px 8px;
                    border-top: none;
                    padding: 5px;
                }
            """)
            self.pw_container.setVisible(False)
            
            pw_layout = QVBoxLayout(self.pw_container)
            pw_layout.setSpacing(12)
            pw_layout.setContentsMargins(15, 10, 15, 15)
            
            # Selection de l'utilisateur
            user_pw_label = QLabel("Utilisateur:")
            user_pw_label.setStyleSheet("color: #A0A0A0; font-weight: bold;")
            pw_layout.addWidget(user_pw_label)
            
            self.pw_user_combo = QComboBox()
            self.pw_user_combo.setStyleSheet("""
                QComboBox {
                    padding: 8px;
                    border: 1px solid #444;
                    border-radius: 4px;
                    background-color: #2B2B3D;
                    color: white;
                }
                QComboBox:hover {
                    border: 1px solid #4CAF50;
                }
                QComboBox QAbstractItemView {
                    background-color: #2B2B3D;
                    color: white;
                    selection-background-color: #4CAF50;
                }
            """)
            pw_layout.addWidget(self.pw_user_combo)
            
            # Mot de passe actuel
            current_pw_label = QLabel("Mot de passe actuel:")
            current_pw_label.setStyleSheet("color: #A0A0A0; font-weight: bold;")
            pw_layout.addWidget(current_pw_label)

            self.current_pw_frame, self.current_pw_input, _ = make_password_with_toggle(
                "Saisissez votre mot de passe actuel"
            )
            pw_layout.addWidget(self.current_pw_frame)

            # Nouveau mot de passe
            new_pw_label = QLabel("Nouveau mot de passe:")
            new_pw_label.setStyleSheet("color: #A0A0A0; font-weight: bold;")
            pw_layout.addWidget(new_pw_label)

            self.new_pw_frame, self.new_pw_input, _ = make_password_with_toggle(
                "Au moins 4 caracteres"
            )
            pw_layout.addWidget(self.new_pw_frame)

            # Confirmation
            confirm_pw_label = QLabel("Confirmer le nouveau mot de passe:")
            confirm_pw_label.setStyleSheet("color: #A0A0A0; font-weight: bold;")
            pw_layout.addWidget(confirm_pw_label)

            self.confirm_pw_frame, self.confirm_pw_input, _ = make_password_with_toggle(
                "Retapez le nouveau mot de passe"
            )
            pw_layout.addWidget(self.confirm_pw_frame)
            
            # Bouton Valider
            change_pw_btn = QPushButton("Valider le changement")
            change_pw_btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                    padding: 10px;
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #1976D2;
                }
            """)
            change_pw_btn.clicked.connect(self.change_password)
            pw_layout.addWidget(change_pw_btn)
            
            scroll_layout.addWidget(self.pw_container)
            
            # Connecter le toggle
            self.pw_toggle_btn.toggled.connect(self._toggle_pw_panel)
        
        # Associer le widget conteneur au scroll area
        scroll.setWidget(scroll_widget)
        
        # Ajouter le scroll area au layout principal de l'onglet
        layout.addWidget(scroll, 1)
        
        # Bouton d'enregistrement
        save_btn = QPushButton("Enregistrer les modifications")
        save_btn.setToolTip(
            "Sauvegarder les parametres (Ctrl+S)"
        )
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 15px 30px;
                border: none;
                border-radius: 6px;
                font-weight: bold;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #45A049;
            }
        """)
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)

        # Lexique de raccourcis clavier
        layout.addWidget(ShortcutsFooter([
            ("Ctrl+S", "Sauvegarder"),
            ("Ctrl+1-6", "Naviguer entre les onglets"),
            ("Ctrl+Maj+L", "Deconnexion"),
        ]))

        self.setLayout(layout)

        # Raccourci Ctrl+S pour sauvegarder
        sc_save = QShortcut(QKeySequence("Ctrl+S"), self)
        sc_save.activated.connect(self.save_settings)
    
    def _is_supervisor(self) -> bool:
        """Verifie si l'utilisateur courant est superviseur."""
        return (self.auth_manager is not None
                and self.auth_manager.current_user is not None
                and self.auth_manager.current_user.role == "supervision")

    def save_settings(self):
        """Sauvegarde les parametres dans le fichier JSON (superviseur seulement)."""
        # Verifier le role — securite backend
        if not self._is_supervisor():
            QMessageBox.warning(self, "Acces refuse",
                                "Reserve au Superviseur.")
            return
        # Recuperer les valeurs depuis l'interface
        self.settings['bluetooth_enabled'] = self.bt_enabled_check.isChecked()
        self.settings['discovery_mode'] = self.discovery_combo.currentText().lower()
        self.settings['auto_reconnect'] = self.reconnect_combo.currentIndex() == 0
        
        try:
            self.settings['max_reconnect_delay'] = int(self.delay_input.text())
        except ValueError:
            pass
        
        try:
            self.settings['roughness_threshold'] = float(self.roughness_input.text())
        except ValueError:
            pass
        
        try:
            self.settings['flatness_threshold'] = float(self.flatness_input.text())
        except ValueError:
            pass
        
        self.settings['sound_notifications'] = self.sound_check.isChecked()
        self.settings['email_alerts'] = self.email_check.isChecked()
        
        try:
            self.settings['auto_export_interval'] = int(self.interval_input.text())
        except ValueError:
            pass
        
        # NOUVEAU: Parametres de chiffrement modulaire
        self.settings['ble_receive_encryption'] = self.ble_encryption_check.isChecked()
        self.settings['file_export_encryption'] = self.file_encryption_check.isChecked()
        
        # Persister
        self._save_settings()
        
        QMessageBox.information(
            self,
            "Succes",
            "Parametres enregistres avec succes!"
        )
    
    def _toggle_pw_panel(self, visible: bool):
        """Affiche ou masque le panneau de changement de mot de passe."""
        self.pw_container.setVisible(visible)
        if visible:
            self.pw_toggle_btn.setText("▼  Changer le mot de passe")
            self._populate_pw_users()
        else:
            self.pw_toggle_btn.setText("  Changer le mot de passe")
            # Secure clear des champs mot de passe
            for field in ('current_pw_input', 'new_pw_input', 'confirm_pw_input'):
                widget = getattr(self, field, None)
                if widget:
                    secure_clear_string(widget.text())
                    widget.clear()
    
    def _populate_pw_users(self):
        """Remplit le combo de selection utilisateur pour le changement de mot de passe."""
        if not self.auth_manager or not hasattr(self, 'pw_user_combo'):
            return
        self.pw_user_combo.clear()
        users = self.auth_manager.get_user_display_names()
        for u in users:
            self.pw_user_combo.addItem(u['display_name'], u['username'])
    
    def change_password(self):
        """Change le mot de passe de l'utilisateur selectionne."""
        if not self.auth_manager:
            QMessageBox.warning(self, "Erreur", "Authentification non disponible.")
            return

        display_name = self.pw_user_combo.currentText()
        username = self.pw_user_combo.currentData()
        current_pw = self.current_pw_input.text()
        new_pw = self.new_pw_input.text()
        confirm_pw = self.confirm_pw_input.text()

        # Helper pour nettoyer les mots de passe quoi qu'il arrive
        def _clear():
            for txt in (current_pw, new_pw, confirm_pw):
                secure_clear_string(txt)
            for field in ('current_pw_input', 'new_pw_input', 'confirm_pw_input'):
                widget = getattr(self, field, None)
                if widget:
                    widget.clear()

        if not current_pw:
            _clear()
            QMessageBox.warning(self, "Erreur", "Veuillez saisir votre mot de passe actuel.")
            return

        if not new_pw:
            _clear()
            QMessageBox.warning(self, "Erreur", "Veuillez saisir un nouveau mot de passe.")
            return

        if new_pw != confirm_pw:
            _clear()
            QMessageBox.warning(
                self, 
                "Erreur", 
                "Les deux saisies du nouveau mot de passe ne correspondent pas."
            )
            return

        if len(new_pw) < 4:
            _clear()
            QMessageBox.warning(
                self,
                "Erreur",
                "Le nouveau mot de passe doit contenir au moins 4 caracteres."
            )
            return

        success, message = self.auth_manager.change_password(username, current_pw, new_pw)
        _clear()

        if success:
            QMessageBox.information(
                self,
                "Succes",
                f"Mot de passe modifie pour {display_name}.\n{message}"
            )
        else:
            QMessageBox.critical(self, "Erreur", message)