import sys
sys.path.insert(0, 'C:/Users/flori/application_mesure_remote')

from src.models.user import AuthManager

am = AuthManager()

# Test Superviseur
u1 = am.authenticate('Superviseur', 'SPlate-shop')
print(f"Test Superviseur: {u1.username if u1 else 'Echec'}")

# Test Operateur
u2 = am.authenticate('operateur', 'Plate-shop')
print(f"Test Operateur: {u2.username if u2 else 'Echec'}")
