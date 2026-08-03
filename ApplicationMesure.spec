# -*- mode: python ; coding: utf-8 -*-

# Spec PyInstaller complet — source de vérité pour le build.
# Correspond aux paramètres de build_remote.ps1 :
#   --onefile --windowed --icon=app.ico --add-data "src;src"
#   --hidden-import PySide6.QtCore/QtWidgets --hidden-import bleak

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('src', 'src'),          # code source complet (modules, data/)
        ('app.ico', '.'),        # icône
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtWidgets',
        'PySide6.QtGui',
        'PySide6.QtMultimedia',
        'bleak',
        'bleak_retry_connector',
        'construct',
        'bcrypt',
        'cryptography',
        'openpyxl',
        'xlsxwriter',
        'reportlab',
        'pandas',
        'winrt',
        'winrt.windows.devices.bluetooth',
        'winrt.windows.devices.enumeration',
        'qasync',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ApplicationMesure',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,               # --windowed (pas de console)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app.ico',
)
