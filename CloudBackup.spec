# -*- mode: python ; coding: utf-8 -*-
"""
CloudBackup.spec — PyInstaller x64 one-folder distribution specification file for CloudBackup.
"""

import sys
import os
from pathlib import Path

block_cipher = None

repo_root = Path('.').resolve()

datas = [
    (str(repo_root / 'windows' / 'web_static'), 'windows/web_static'),
    (str(repo_root / 'shared' / 'schema.sql'), 'shared'),
    (str(repo_root / 'shared' / 'rclone_manifest.json'), 'shared'),
    (str(repo_root / 'config.example.yaml'), '.'),
    (str(repo_root / 'BOOTSTRAP.txt'), '.'),
]

# Include bundled rclone binary if present at build time
bundled_rclone = repo_root / 'bin' / 'rclone.exe'
if bundled_rclone.exists():
    datas.append((str(bundled_rclone), 'bin'))

hiddenimports = [
    'pyotp',
    'qrcode',
    'bcrypt',
    'yaml',
    'dotenv',
    'requests',
    'waitress',
    'sqlite3',
    'pathlib',
]

if sys.platform == 'win32':
    hiddenimports.extend([
        'win32timezone',
        'win32service',
        'win32serviceutil',
    ])

a = Analysis(
    ['windows/cli.py'],
    pathex=[str(repo_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PIL', 'scipy', 'numpy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CloudBackup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CloudBackup',
)
