import sys
sys.path.insert(0, 'C:/Users/flori/application_mesure_remote')

from src.models.user import AuthManager
import os

# Reset users.json if exists
db_path = "C:\\Users\\flori\\.application_mesure\\users.json"
if os.path.exists(db_path):
    os.remove(db_path)

am = AuthManager()
print("=== TEST BLOCAGE APRES FIX - Début ===")

# Test Operateur - 3 échecs
print("\n--- TEST OPERATEUR ---")
for i in range(4):
    can_proceed, remaining = am.check_rate_limit("operateur")
    print(f"Tentative {i+1}: Rate limit: {can_proceed}, Cooldown: {remaining}s", end=" -> ")
    user = am.authenticate("operateur", "wrong_password")
    blocked = am.is_operator_blocked()
    print(f"{'Echec' if not user else 'Succes'} - Bloqué: {blocked}")

# Reset pour test superviseur
am._supervisor_failures = 0
am._login_attempts.clear()
am._last_attempt_time.clear()

# Test Superviseur - plusieurs échecs
print("\n--- TEST SUPERVISEUR ---")
for i in range(10):
    can_proceed, remaining = am.check_rate_limit("Superviseur")
    print(f"Tentative {i+1}: Rate limit: {can_proceed}, Cooldown: {remaining}s", end=" -> ")
    user = am.authenticate("Superviseur", "wrong_password")
    blocked = am.is_supervisor_blocked()
    print(f"{'Echec' if not user else 'Succes'} - Bloqué: {blocked}")

print("\n=== TEST FINI ===")
