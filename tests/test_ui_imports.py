"""Test d'import des vues pour détecter les erreurs de dépendances."""
import sys
import os
from pathlib import Path

# Ajouter le dossier parent (src/) au path Python
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Créer QApplication nécessaire pour les widgets Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

errors = []

def _test_import(mod_name, symbol):
    try:
        __import__(f"views.{mod_name}", fromlist=[symbol])
        print(f"OK: views.{mod_name}.{symbol}")
    except Exception as e:
        print(f"FAIL: views.{mod_name}.{symbol}: {e}")
        errors.append(f"views.{mod_name}.{symbol}: {e}")

_test_import("login_view", "LoginView")
_test_import("main_window", "MainWindow")
_test_import("dashboard_tab", "DashboardTab")
_test_import("connection_tab", "ConnectionTab")
_test_import("measures_tab", "MeasuresTab")
_test_import("tools_tab", "ToolsTab")
_test_import("export_tab", "ExportTab")
_test_import("settings_tab", "SettingsTab")

if errors:
    print(f"\n{len(errors)} ERREUR(S):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nTous les imports OK")
    sys.exit(0)
