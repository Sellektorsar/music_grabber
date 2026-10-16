# -*- mode: python ; coding: utf-8 -*-
# Спецификация сборки PyInstaller для TelegramAudioDownloader.
# Точка входа — main.py (раньше ошибочно указывался несуществующий audio_downloader.py).

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Telethon и PyQt6 активно используют динамические импорты — собираем подмодули.
hiddenimports = []
hiddenimports += collect_submodules('telethon')
hiddenimports += collect_submodules('pydub')
hiddenimports += collect_submodules('mutagen')

# numpy/scipy/sounddevice тоже требуют явного перечисления подмодулей
hiddenimports += collect_submodules('scipy')
hiddenimports += collect_submodules('sounddevice')
hiddenimports += collect_submodules('numpy')

# Дополнительные модули, которые PyInstaller может не обнаружить автоматически
hiddenimports += [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtWidgets',
    'PyQt6.QtGui',
    'PyQt6.QtMultimedia',
    'PyQt6.QtNetwork',
    'qrcode',
    'socks',
    'sqlite3',
]

datas = []
# Данные telethon (схемы TL и т.п.)
datas += collect_data_files('telethon')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TelegramAudioDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,  # Оконный режим: без консоли
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='music_grabber.ico',
)
