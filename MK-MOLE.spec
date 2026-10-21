# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: portable one-folder build (fast startup).

The GUI folder excludes torch/CHGNet. The CHGNet engine is installed into
`chgnet_env` next to MK-MOLE.exe by install_chgnet.bat, and is detected at
runtime. The standalone runner/probe scripts are included as data files.
"""

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('mk_mole/assets', 'mk_mole/assets'),
        ('mk_mole/tools/chgnet_runner.py', 'mk_mole/tools'),
        ('mk_mole/tools/chgnet_probe.py', 'mk_mole/tools'),
    ],
    hiddenimports=[
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtSvg',
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
    [],
    exclude_binaries=True,
    name='MK-MOLE',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['mk_mole/assets/mk_mole.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='MK-MOLE',
)
