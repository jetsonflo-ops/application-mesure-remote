"""User model and authentication manager."""
import base64
import bcrypt
import hmac
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from src.utils.secure_config import get_pepper
from src.utils.audit_logger import audit
from src.utils.file_crypto import encrypt_json, decrypt_json

logger = logging.getLogger(__name__)


class User:
    """Représentation d'un utilisateur du système."""

    def __init__(self, username: str, role: str, user_id: int = None):
        self.user_id = user_id
        self.username = username
        self.role = role  # 'operateur' ou 'supervision'
        self.created_at = datetime.now()
        self.last_login = None
        # Indique si c'est le mot de passe initial par défaut (doit être changé)
        self.is_initial_password = True

    def to_dict(self) -> dict:
        return {
            'user_id': self.user_id,
            'username': self.username,
            'role': self.role,
            'created_at': self.created_at.isoformat(),
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'is_initial_password': self.is_initial_password
        }

    @classmethod
    def from_dict(cls, data: dict):
        user = cls(
            user_id=data.get('user_id'),
            username=data['username'],
            role=data['role']
        )
        # Restaurer les champs optionnels
        user.is_initial_password = data.get('is_initial_password', True)  # Par défaut: vrai pour compatibilité
        if 'created_at' in data:
            try:
                user.created_at = datetime.fromisoformat(data['created_at'])
            except (ValueError, TypeError):
                pass
        ts = data.get('last_login')
        if ts:
            try:
                user.last_login = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass
        return user


class AuthManager:
    """Gère l'authentification et les sessions utilisateurs."""

    # Mot de passe root pour déverrouillage superviseur (connu de l'APU uniquement)
    ROOT_PASSWORD_HASH = "$2b$12$XgaRzIm68WgjqFSaQ.NZRedUZGH13G8RyRma6H69XdJdarhZpuy1a"

    def __init__(self, db_path: str = None):
        # Chemin absolu : ~/.application_mesure/users.json (compatible Windows/Linux/PyInstaller)
        app_dir = os.path.join(os.path.expanduser("~"), ".application_mesure")
        self.db_path = db_path or os.path.join(app_dir, "users.json")
        self.current_user: Optional[User] = None
        self.session_timeout = timedelta(minutes=30)  # 30 minutes d'inactivité

        # Rate limiting
        self._login_attempts: Dict[str, List[datetime]] = {}
        self._last_attempt_time: Dict[str, datetime] = {}  # Timestamp de la dernière tentative

        # Blocages permanents
        self._operator_blocked = False
        self._supervisor_blocked = False
        self._supervisor_failures: int = 0  # Compteur permanent

        # Utilisateurs par défaut
        self.default_users = [
            User(user_id=1, username="Superviseur", role="supervision"),
            User(user_id=2, username="operateur", role="operateur")
        ]

        self._init_db()

    def _init_db(self):
        """Initialise la base de données avec les utilisateurs par défaut."""
        # Vérifier que le pepper existe avant de hasher les mots de passe
        # (crée pepper.key si nécessaire — appel systématique pour isolation)
        from src.utils.secure_config import get_pepper
        get_pepper()  # Garantit que pepper.key existe

        if not os.path.exists(self.db_path):
            self._create_default_users()
            return

        # Si le fichier existe mais est corrompu (mauvais pepper, etc.),
        # on le réinitialise
        test = self._load_users()
        if not test:
            logger.warning("users.json corrompu ou illisible — réinitialisation")
            self._create_default_users()

    def _create_default_users(self):
        """Crée les utilisateurs par défaut dans la base de données."""
        users = [u.to_dict() for u in self.default_users]
        # Mots de passe par défaut : Superviseur=SPlate-shop, Operateur=Plate-shop
        passwords = {"Superviseur": "SPlate-shop", "operateur": "Plate-shop"}

        for user in users:
            user['password_hash'] = self._hash_password(
                passwords[user['username']]
            ).decode('utf-8')
            # Marquer comme mot de passe initial
            user['is_initial_password'] = True

        self._save_users(users)
        logger.info("Utilisateurs par défaut créés dans %s", self.db_path)

    # --- Gestion des blocages ---

    def is_operator_blocked(self) -> bool:
        """Vérifie si le compte operateur est bloqué."""
        return self._operator_blocked

    def is_supervisor_blocked(self) -> bool:
        """Vérifie si le compte superviseur est bloqué."""
        return self._supervisor_blocked

    def unlock_operator(self):
        """Déverrouille le compte operateur (action superviseur)."""
        self._operator_blocked = False
        self._login_attempts.pop('operateur', None)
        audit("OPERATOR_UNLOCK", "Superviseur", "Compte operateur déverrouillé par superviseur")

    def verify_root_password(self, password: str) -> bool:
        """Vérifie le mot de passe root pour déverrouiller le superviseur.

        Args:
            password: Mot de passe root en clair

        Returns:
            True si le mot de passe root est correct
        """
        pepper = get_pepper()
        h = hmac.new(pepper, password.encode("utf-8"), hashlib.sha384)
        pre_hashed = base64.b64encode(h.digest()).decode("ascii")
        try:
            return bcrypt.checkpw(
                pre_hashed.encode("utf-8"),
                self.ROOT_PASSWORD_HASH.encode("utf-8")
            )
        except (ValueError, AttributeError):
            return False

    def unlock_supervisor(self, username: str = "Superviseur"):
        """Déverrouille le compte superviseur (action root).

        Args:
            username: Nom de l'utilisateur superviseur
        """
        self._supervisor_blocked = False
        self._supervisor_failures = 0
        self._login_attempts.pop(username, None)
        self._last_attempt_time.pop(username, None)
        audit("SUPERVISOR_UNLOCK", username,
              "Compte superviseur déverrouillé par mot de passe root")

    # --- Rate limiting ---

    def check_rate_limit(self, username: str) -> tuple[bool, int]:
        """Vérifie le rate limiting par rôle.

        Operateur: 3 tentatives max → blocage permanent
        Superviseur: 3 rapides + 3 avec 30s → blocage permanent

        Retourne (autorise, secondes_restantes).
        """
        # Si déjà bloqué, rejeter immédiatement
        if username == "operateur" and self._operator_blocked:
            return False, 0
        if username == "Superviseur" and self._supervisor_blocked:
            return False, 0

        now = datetime.now()
        attempts = self._login_attempts.get(username, [])

        if username == "operateur":
            # 3 tentatives MAX → blocage permanent
            if len(attempts) >= 3:
                self._operator_blocked = True
                audit("OPERATOR_BLOCKED", username,
                      "Compte bloqué après 3 tentatives échouées")
                return False, 0
            return True, 0

        else:  # superviseur
            total = self._supervisor_failures

            # Phase 1: premières 3 tentatives → immédiates
            if total < 3:
                return True, 0

            # Phase 3: après 6 total → blocage permanent
            if total >= 6:
                self._supervisor_blocked = True
                audit("SUPERVISOR_BLOCKED", username,
                      "Compte bloqué après 6 tentatives échouées")
                return False, 0

            # Phase 2: tentatives 4-6 → 30s entre chaque tentative
            last_time = self._last_attempt_time.get(username)
            if last_time is not None:
                elapsed = (datetime.now() - last_time).total_seconds()
                if elapsed < 30:
                    remaining = int(30 - elapsed)
                    return False, max(1, remaining)

            return True, 0

    def _record_failed_attempt(self, username: str):
        """Enregistre une tentative échouée."""
        if username not in self._login_attempts:
            self._login_attempts[username] = []
        self._login_attempts[username].append(datetime.now())
        self._last_attempt_time[username] = datetime.now()

        if username == "Superviseur":
            self._supervisor_failures += 1

    def authenticate(self, username: str, password: str) -> Optional[User]:
        """Vérifie les identifiants et retourne l'utilisateur si valide."""
        # Vérifier les blocages permanents
        if username == "operateur" and self._operator_blocked:
            return None
        if username == "Superviseur" and self._supervisor_blocked:
            return None

        # Rate limiting superviseur (Phase 2): cooldown 30s entre tentatives 4-6
        if username == "Superviseur":
            if 3 <= self._supervisor_failures < 6:
                last_time = self._last_attempt_time.get(username)
                if last_time is not None:
                    elapsed = (datetime.now() - last_time).total_seconds()
                    if elapsed < 30:
                        remaining = int(30 - elapsed)
                        audit("LOGIN_RATE_LIMITED", username,
                              f"Trop de tentatives. Réessayez dans {remaining}s")
                        return None

        users = self._load_users()

        for user_data in users:
            if user_data['username'] == username:
                if self._hash_verify(password, user_data['password_hash']):
                    user = User.from_dict(user_data)
                    user.last_login = datetime.now()
                    audit("LOGIN", username, "Authentification réussie")

                    # Reinitialiser les compteurs
                    self._supervisor_failures = 0
                    self._login_attempts.pop(username, None)
                    self._last_attempt_time.pop(username, None)

                    # Si c'est un mot de passe initial, forcer le changement
                    if user.is_initial_password:
                        audit("FIRST_LOGIN", username, "Première connexion - mot de passe à changer")
                        return user  # On retourne l'utilisateur pour déclencher le flux de changement

                    return user

        # Echec — enregistrer pour rate limiting
        self._record_failed_attempt(username)
        audit("LOGIN_FAILED", username, "Mot de passe incorrect")

        # Verifier blocage permanent operateur apres 3 echecs
        if username == "operateur":
            attempts = self._login_attempts.get(username, [])
            if len(attempts) >= 3:
                self._operator_blocked = True
                audit("OPERATOR_BLOCKED", username,
                      "Compte bloque apres 3 tentatives echouees")

        # Verifier blocage permanent superviseur apres 6 echecs
        if username == "Superviseur" and self._supervisor_failures >= 6:
            self._supervisor_blocked = True
            audit("SUPERVISOR_BLOCKED", username,
                  "Compte bloque apres 6 tentatives echouees")

        return None

    # --- Session ---

    def create_session(self, user: User) -> str:
        """Cree une session pour l'utilisateur."""
        self.current_user = user
        return f"session_{user.user_id}_{secrets.token_urlsafe(16)}"

    def logout(self):
        """Deconnecte l'utilisateur actuel."""
        self.current_user = None

    def is_current_user_supervisor(self) -> bool:
        """Vérifie si l'utilisateur connecté a le role supervision."""
        return self.current_user and self.current_user.role == "supervision"

    def has_permission(self, required_role: str) -> bool:
        """Vérifie les permissions de l'utilisateur actuel."""
        if not self.current_user:
            return False
        if required_role == "supervision":
            return self.current_user.role == "supervision"
        return True

    # --- Hashing ---

    @staticmethod
    def _hash_password(password: str, pepper: bytes = None) -> bytes:
        """Hache un mot de passe avec pepper HMAC-SHA384 + bcrypt rounds=12.

        Schema:
            bcrypt(base64(hmac-sha384(password, pepper)), salt, cost=12)

        Args:
            password: Mot de passe en clair
            pepper: Cle de pepper (defaut: get_pepper())

        Returns:
            Hash bcrypt (bytes)
        """
        if pepper is None:
            pepper = get_pepper()
        h = hmac.new(pepper, password.encode("utf-8"), hashlib.sha384)
        pre_hashed = base64.b64encode(h.digest()).decode("ascii")
        return bcrypt.hashpw(
            pre_hashed.encode("utf-8"),
            bcrypt.gensalt(rounds=12)
        )

    def _hash_verify(self, password: str, stored_hash: str) -> bool:
        """Vérifie un mot de passe contre un hash bcrypt avec pepper."""
        pepper = get_pepper()
        h = hmac.new(pepper, password.encode("utf-8"), hashlib.sha384)
        pre_hashed = base64.b64encode(h.digest()).decode("ascii")
        try:
            return bcrypt.checkpw(
                pre_hashed.encode("utf-8"),
                stored_hash.encode("utf-8")
            )
        except (ValueError, AttributeError):
            return False

    # --- Changement de mot de passe ---

    def change_password(self, username: str, current_password: str,
                        new_password: str) -> tuple[bool, str]:
        """Change le mot de passe d'un utilisateur (avec verification ancien).

        Args:
            username: Nom d'utilisateur interne (admin/operateur)
            current_password: Mot de passe actuel pour verification
            new_password: Nouveau mot de passe (min 4 caracteres)

        Returns:
            (succes, message_erreur)
        """
        if len(new_password) < 4:
            return False, "Le nouveau mot de passe doit contenir au moins 4 caracteres."

        users = self._load_users()
        found = False

        for user_data in users:
            if user_data.get('username') == username:
                if not self._hash_verify(current_password, user_data['password_hash']):
                    return False, "Mot de passe actuel incorrect."

                user_data['password_hash'] = self._hash_password(new_password).decode('utf-8')
                # Marquer comme mot de passe changé (plus initial)
                user_data['is_initial_password'] = False
                found = True

                audit("PASSWORD_CHANGE", username,
                      f"Par {self.current_user.username if self.current_user else 'inconnu'}")
                break

        if not found:
            return False, f"Utilisateur '{username}' introuvable."

        self._save_users(users)
        return True, "Mot de passe modifie avec succes."

    def change_password_admin(self, username: str, new_password: str) -> tuple[bool, str]:
        """Change le mot de passe sans verification (usage superviseur/root).

        Utilise pour le déverrouillage force par superviseur ou root.
        """
        if len(new_password) < 4:
            return False, "Le nouveau mot de passe doit contenir au moins 4 caracteres."

        users = self._load_users()
        found = False

        for user_data in users:
            if user_data.get('username') == username:
                user_data['password_hash'] = self._hash_password(new_password).decode('utf-8')
                # Marquer comme mot de passe changé (plus initial)
                user_data['is_initial_password'] = False
                found = True

                audit("PASSWORD_FORCE_CHANGE", username,
                      f"Par {self.current_user.username if self.current_user else 'root'}")
                break

        if not found:
            return False, f"Utilisateur '{username}' introuvable."

        self._save_users(users)
        return True, "Mot de passe modifie avec succes."

    def get_user_display_names(self) -> list[dict]:
        """Retourne la liste des utilisateurs avec leur nom d'affichage et nom interne."""
        users = self._load_users()
        display_map = {"Superviseur": "Superviseur", "operateur": "Operateur"}
        result = []
        for u in users:
            uname = u.get('username', '')
            result.append({
                'username': uname,
                'display_name': display_map.get(uname, uname),
            })
        return result

    # --- Persistance ---

    def _save_users(self, users: list):
        """Sauvegarde les utilisateurs dans un fichier JSON chiffre AES-256-GCM."""
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        if not encrypt_json(self.db_path, users):
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(users, f, indent=2)

    def _load_users(self):
        """Charge les utilisateurs depuis un fichier JSON chiffre.

        Retourne: liste de dicts utilisateurs
        """
        if not os.path.exists(self.db_path):
            return []
        try:
            data = decrypt_json(self.db_path)
            if data is not None:
                return data
        except Exception:
            pass

        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, ValueError):
            return []