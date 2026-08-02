"""Script de build pour generer l'executable Windows (.exe).

Utilise le spec file ApplicationMesure.spec (source unique de verite).
Pour personnaliser le build, modifiez le .spec, pas ce script.

Usage:
    python build.py
    # ou directement :
    pyinstaller ApplicationMesure.spec --noconfirm
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path


def main():
    root_dir = Path(__file__).parent
    dist_dir = root_dir / "dist"

    print("Demarrage du build via ApplicationMesure.spec...")

    # Nettoyer
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
        print("Nettoyage de dist/ termine")

    # Verifier PyInstaller
    try:
        import PyInstaller
        print(f"PyInstaller {PyInstaller.__version__} trouve")
    except ImportError:
        print("Installation de PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Build via spec
    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", "ApplicationMesure.spec", "--noconfirm"],
        cwd=str(root_dir),
    )

    # Copier dans installer/ avec version horodatée (pas d'écrasement)
    exe_path = dist_dir / "ApplicationMesure.exe"
    if exe_path.exists():
        print(f"Executable genere: {exe_path}")
        installer_dir = root_dir / "installer"
        installer_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        versioned_name = f"ApplicationMesure_{stamp}.exe"
        shutil.copy2(exe_path, installer_dir / versioned_name)
        # Copie "latest" pour point d'entrée stable
        shutil.copy2(exe_path, installer_dir / "ApplicationMesure.exe")
        print("Build termine avec succes!")
        print(f"Executable versionne: {installer_dir / versioned_name}")
        print(f"Executable stable: {installer_dir / 'ApplicationMesure.exe'}")
    else:
        print(f"Erreur : {exe_path} n'a pas ete cree")
        sys.exit(1)


if __name__ == "__main__":
    main()
