import sys
sys.path.insert(0, 'C:/Users/flori/application_mesure_remote')

from src.models.user import AuthManager
import os

# Reset users.json if exists
db_path = "C:\\Users\\flori\\.application_mesure\\users.json"
if os.path.exists(db_path):
    os.remove(db_path)

am = AuthManager()
print("=== TEST BLOCAGE - Début ===")
print(f"Database: {am.db_path}")

# Test Operateur - 3 échecs
print("\n--- TEST OPERATEUR ---")
for i in range(4):
    user = am.authenticate("operateur", "wrong_password")
    print(f"Tentative {i+1}: {'Echec' if not user else 'Succes'}")
    if user:
        print(f"  User: {user.username}")

# Test Superviseur - plusieurs échecs
print("\n--- TEST SUPERVISEUR ---")
for i in range(8):
    user = am.authenticate("Superviseur", "wrong_password")
    blocked = am.is_supervisor_blocked()
    print(f"Tentative {i+1}: {'Echec' if not user else 'Succes'} - Bloqué: {blocked}")

print("\n=== TEST FINI ===")
