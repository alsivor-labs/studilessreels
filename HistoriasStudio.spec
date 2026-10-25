# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root = Path(SPECPATH)
vendor = root / 'build-native' / 'vendor'
sys.path.insert(0, str(vendor))
datas = [(str(root / 'static'), 'static')] + collect_data_files('webview') + collect_data_files('pythonnet') + collect_data_files('clr_loader')
binaries = collect_dynamic_libs('webview')
for name in ('workflow.json', 'workflow_video.json', 'workflow_music.json'):
    datas.append((str(root / name), '.'))

a = Analysis(
    [str(root / 'launcher.py')],
    pathex=[str(root), str(vendor)],
    binaries=binaries,
    datas=datas,
    hiddenimports=['server', 'pipeline', 'narrative', 'music_generation', 'score', 'local_auth', 'runtime_paths', 'diagnostics', 'webview.platforms.edgechromium', 'webview.platforms.winforms', 'clr', 'clr_loader', 'pythonnet'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='HistoriasStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='x86_64',
    codesign_identity=None,
    entitlements_file=None,
)