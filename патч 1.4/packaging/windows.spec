# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
build = Path(os.environ.get('NARYADAI_BUILD_DIR', str(root / 'build/windows')))
voice_data, voice_binaries, voice_imports = collect_all('vosk')
a = Analysis(
    [str(root / 'windows_entry.py')],
    pathex=[str(root)],
    binaries=voice_binaries,
    datas=voice_data + [
        (str(root / 'assets'), 'assets'),
        (str(root / 'web/icons'), 'web/icons'),
        (str(root / 'voice_models/vosk-model-small-ru-0.22'), 'voice_models/vosk-model-small-ru-0.22'),
    ],
    hiddenimports=voice_imports + ['sounddevice', 'tzdata', 'PySide6.QtSvg'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'tkinter', 'matplotlib', 'IPython'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='NaryadAI',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          icon=str(build / 'naryadai.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='NaryadAI')
