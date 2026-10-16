# -*- mode: python ; coding: utf-8 -*-
# Спецификация сборки PyInstaller для TelegramAudioDownloader.
# Точка входа — main.py (раньше ошибочно указывался несуществующий audio_downloader.py).

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Telethon и PyQt6 активно используют динамические импорты — собираем подмодули.
hiddenimports = []
hiddenimports += collect_submodules('telethon')
hiddenimports += collect_submodules('pydub')
hiddenimports += collect_submodules('mutagen')

# numpy требует явного перечисления подмодулей
hiddenimports += collect_submodules('numpy')

# sounddevice и scipy больше не собираются. Ими пользовался только
# audio_capture (режим «Запись звука»), который удалён вместе с
# режимами: модуль остался в репозитории, но приложение его не
# импортирует, поэтому тянется в сборку незачем -- это была заметная
# часть размера готового файла.

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
    # Загрузка вынесена из recorder.py; импорт статический, но модуль
    # перечислен явно -- молчаливая потеря его дала бы EXE, который
    # падает только при первой загрузке трека.
    'recorder_download',
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
    # pydub умеет фильтры верхних/низких частот через scipy, но этот
    # модуль никто не импортирует: collect_submodules('pydub') перечисляет
    # все подмодули подряд и тянул scipy целиком. Ядро конвертации
    # (from_file/export) от scipy не зависит.
    excludes=['scipy', 'pydub.scipy_effects'],
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
