import sys
sys.path.insert(0, 'C:/Users/flori/application_mesure_remote')

from src.models.user import AuthManager
import os

# Supprimer l'ancien fichier corrompu
db_path = "C:\\Users\\flori\\.application_mesure\\users.json"
if os.path.exists(db_path):
    os.remove(db_path)
    print("Ancien users.json supprime")

# Créer de nouveaux utilisateurs avec mots de passe hashés
am = AuthManager()
print("AuthManager initialise")
print(f"Chemin base: {am.db_path}")

# Verifier la creation
users = am._load_users()
print(f"Utilisateurs ({len(users)}):")
for u in users:
    print(f" - {u['username']} (role: {u.get('role')}, initial: {u.get('is_initial_password')})")
