"""Модуль GUI Telegram Audio Downloader в стиле BEATSTORM DJ Pool Workstation.

Содержит:
- Трехколоночную компоновку рабочего стола диджея (Channels, Library, Download Monitor);
- Верхнюю панель навигации (BEATSTORM, вкладки, поиск, профиль);
- Мульти-колоночную библиотеку треков с вейвформами и статусами;
- Панель мониторинга загрузок с графиком скорости и активными потоками;
- Встроенный аудиоплеер для предпрослушивания;
- Полную обратную совместимость со всеми существующими сигналами и тестами.
"""

import os
import sys
import logging

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QSystemTrayIcon,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut

from downloader import DownloadThread
from config import BASE_PATH, load_config, save_config
import database as db_module
from ui.tray import setup_system_tray, show_tray_notification

logger = logging.getLogger(__name__)

# Хранилище ссылок на фоновые потоки, еще не успевшие завершиться при закрытии окна,
# для предотвращения краша 'QThread: Destroyed while thread is still running'
_LINGERING_THREADS: set = set()

# Re-exports for 100% backward compatibility
from ui.theme import DARK_STYLESHEET
from ui.dialogs import (
    InputCodeDialog,
    QRCodeDialog,
    ProxySettingsDialog,
    is_ffmpeg_available,
)
from ui.widgets import (
    SpeedMeterWidget,
    create_beatstorm_logo_pixmap,
    create_user_avatar_pixmap,
    create_waveform_pixmap,
    create_waveform_placeholder,
    get_cached_waveform_placeholder,
    extract_bpm_meta,
    _PLACEHOLDER_CACHE,
)
from ui.player import AudioPlayerBar
from ui.navbar import setup_deck_header
from ui.sidebar import setup_api_drawer, setup_channels_sidebar
from ui.monitor import setup_download_monitor
from ui.library import setup_library_panel

from ui.controllers.channels_controller import (
    ChannelsMixin,
    DEFAULT_CHANNELS,
    load_saved_channels,
    save_saved_channels,
)
from ui.controllers.tree_controller import TreeControllerMixin
from ui.controllers.download_controller import DownloadControllerMixin


class MainWindow(
    QWidget,
    ChannelsMixin,
    TreeControllerMixin,
    DownloadControllerMixin,
):
    """Главное окно приложения TelegramAudioDownloader (BEATSTORM DJ Pool Workstation)."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Audio Downloader")
        self.setStyleSheet(DARK_STYLESHEET)
        self.resize(1280, 750)
        self.setMinimumSize(1020, 680)

        # -------------------------------------------------------------
        # 0. BEATSTORM Верхний навбар (Master Deck Header)
        setup_deck_header(self)

        # 1. API & Proxy Settings Drawer (Collapsible)
        setup_api_drawer(self)

        # 2. Левая колонка: TELEGRAM CHANNELS
        setup_channels_sidebar(self)

        # 3. Центральная колонка: MUSIC LIBRARY
        setup_library_panel(self)

        # 4. Правая колонка: DOWNLOAD MONITOR
        setup_download_monitor(self)

        # 6. Нижний Preview-плеер (Master Deck Audio Player)
        # -------------------------------------------------------------
        self.player_bar = AudioPlayerBar(parent=self, log_callback=self.log)
        self.btn_play_pause = self.player_bar.btn_play_pause
        self.btn_player_stop = self.player_bar.btn_player_stop
        self.player_title_label = self.player_bar.player_title_label
        self.player_slider = self.player_bar.player_slider
        self.player_time_label = self.player_bar.player_time_label
        self.volume_slider = self.player_bar.volume_slider
        self._player = self.player_bar._player
        self._audio_output = self.player_bar._audio_output

        # -------------------------------------------------------------
        # 7. Сборка всей 3-колоночной композиции
        # -------------------------------------------------------------
        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self.deck_header)
        root_layout.addWidget(self.api_group)

        # 3 колонки по горизонтали (Рабочий стол DJ Library)
        self.body_widget = QWidget()
        body_layout = QHBoxLayout(self.body_widget)
        body_layout.setContentsMargins(10, 8, 10, 8)
        body_layout.setSpacing(10)

        body_layout.addWidget(self.left_panel)
        body_layout.addWidget(self.center_panel, 1)
        body_layout.addWidget(self.right_panel)

        # Стек для вкладок Home / Channels / Library
        self.main_stack = QStackedWidget()
        self.home_view = self._create_home_view()
        self.main_stack.addWidget(self.home_view)    # Index 0: Bento Grid Studio (Default Active Workstation)
        self.main_stack.addWidget(self.body_widget)  # Index 1: Classic Library
        self.channels_view = self._create_channels_view()
        self.main_stack.addWidget(self.channels_view)  # Index 2: Channels

        root_layout.addWidget(self.main_stack, 1)

        # Прогресс-бар перед плеером
        progress_container = QWidget()
        prog_layout = QVBoxLayout(progress_container)
        prog_layout.setContentsMargins(12, 0, 12, 2)
        prog_layout.addWidget(self.progress_bar)
        prog_layout.addWidget(self.progress_label)
        root_layout.addWidget(progress_container)

        # Нижний плеер
        root_layout.addWidget(self.player_bar)

        self.setLayout(root_layout)

        # Сигналы кнопок
        self.scan_button.clicked.connect(self.start_scan)
        self.download_button.clicked.connect(self.start_download)
        self.stop_button.clicked.connect(self.stop_download)
        self.proxy_button.clicked.connect(self.open_proxy_settings)

        self._load_settings()
        if hasattr(self, "bento_channel_input") and hasattr(self, "channel_input"):
            self.bento_channel_input.setText(self.channel_input.text())
        self.switch_tab("home")

        self._api_settings_open = not bool(self.api_id_input.text().strip())
        self.api_group.setVisible(self._api_settings_open)
        self._log_open = False
        self.log_output.setVisible(False)

        self.download_thread = None
        self.input_dialog = None
        self.qr_dialog = None
        self._input_answered = False
        self._scan_results = []
        self._updating_table = False
        self._updating_tree = False
        self._channel_offsets = {}
        self._no_more_tracks = False
        self._current_scan_channels = []
        self._track_status_badges = {}
        self._track_waveforms = {}
        self._track_item_by_id = {}
        self._track_row_by_id = {}
        self._track_by_id = {}
        self._track_list_item_by_id = {}

        self._current_audio_path = None
        self._is_seeking = False

        # Инициализация фонового наблюдателя каналов и системного трея
        self._force_close = False
        self._tray_minimized_notified = False
        self._init_background_watcher()
        setup_system_tray(self)

        # QTreeWidget перехватывает «X» под свой type-ahead поиск, поэтому
        # горячая клавиша выбора трека не доходила до keyPressEvent окна.
        # Фильтр событий возвращает управление клавише X в окно.
        tree = getattr(self, "library_tree", None)
        if tree is not None:
            tree.installEventFilter(self)
            tree.viewport().installEventFilter(self)

        # keyPressEvent окна не срабатывает, когда фокус удерживает дочерний
        # виджет: QPushButton и подобные поглощают буквенные клавиши, и до окна
        # событие не доходит. QShortcut срабатывает на уровне окна всегда,
        # поэтому горячие клавиши очистки поиска и загрузки вешаются на него.
        self._dj_shortcuts = []
        for seq, slot in (
            ("Shift+C", self._dj_clear_search),
            ("Shift+D", self._dj_start_download),
        ):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)
            self._dj_shortcuts.append(sc)

        # Автоматическое сканирование сохраненных каналов при запуске приложения (по умолчанию выключено)
        cfg = load_config()
        if cfg.get("auto_scan_on_startup", False) and not os.environ.get("PYTEST_CURRENT_TEST"):
            QTimer.singleShot(700, self._auto_start_scan)

    def log(self, text):
        logger.info(text)
        self.log_output.append(text)

    def _init_background_watcher(self):
        """Инициализирует таймер фонового мониторинга каналов."""
        self._watcher_timer = QTimer(self)
        self._watcher_timer.timeout.connect(self._on_watcher_tick)
        cfg = load_config()
        self._watcher_enabled = bool(cfg.get("auto_watcher_enabled", False))
        interval_min = int(cfg.get("auto_watcher_interval_minutes", 15))
        if self._watcher_enabled and not os.environ.get("PYTEST_CURRENT_TEST"):
            self._watcher_timer.start(interval_min * 60 * 1000)

    def toggle_background_watcher(self, enabled=None):
        """Включает или выключает фоновый мониторинг каналов."""
        if enabled is None:
            self._watcher_enabled = not getattr(self, "_watcher_enabled", False)
        else:
            self._watcher_enabled = bool(enabled)

        cfg = load_config()
        interval_min = int(cfg.get("auto_watcher_interval_minutes", 15))
        save_config(auto_watcher_enabled=self._watcher_enabled)

        if self._watcher_enabled:
            self._watcher_timer.start(interval_min * 60 * 1000)
            self.log(f"🔔 Фоновый мониторинг каналов включен (интервал: {interval_min} мин).")
            self.show_tray_notification(
                "BEATSTORM Watcher",
                f"Фоновый мониторинг каналов включен ({interval_min} мин).",
            )
            if hasattr(self, "btn_notif"):
                self.btn_notif.setStyleSheet("QPushButton#chipButton { color: #00E676; border-color: #1A5432; }")
        else:
            self._watcher_timer.stop()
            self.log("🔕 Фоновый мониторинг каналов выключен.")
            self.show_tray_notification("BEATSTORM Watcher", "Фоновый мониторинг отключен.")
            if hasattr(self, "btn_notif"):
                self.btn_notif.setStyleSheet("")

        if hasattr(self, "action_tray_watcher") and self.action_tray_watcher:
            self.action_tray_watcher.blockSignals(True)
            self.action_tray_watcher.setChecked(self._watcher_enabled)
            self.action_tray_watcher.blockSignals(False)

    def check_channel_updates_now(self):
        """Ручной запуск быстрой проверки обновлений каналов."""
        if self.download_thread and self.download_thread.isRunning():
            self.log("⚠️ Операция уже выполняется. Проверка отложена.")
            return
        channels = getattr(self, "_saved_channels", [])
        if not channels:
            ch = self.channel_input.text().strip()
            channels = [ch] if ch else []
        if not channels:
            self.log("⚠️ Нет сохранённых каналов для проверки.")
            return
        self.log(f"🔍 Быстрая проверка обновлений ({len(channels)} каналов)...")
        self.start_scan(channels=channels, limit_per_channel=50)

    def _on_watcher_tick(self):
        """Периодический тик фонового наблюдателя каналов."""
        if self.download_thread and self.download_thread.isRunning():
            return
        api_id = self.api_id_input.text().strip()
        api_hash = self.api_hash_input.text().strip()
        if not api_id or not api_hash:
            return
        channels = getattr(self, "_saved_channels", [])
        if not channels:
            return
        self.log(f"⏰ Фоновая проверка обновлений каналов ({len(channels)})...")
        self.start_scan(channels=channels, limit_per_channel=50)

    def _show_notifications_menu(self):
        """Отображает контекстное меню управления уведомлениями и фоновым мониторингом."""
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction, QCursor
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #121620;
                color: #FFFFFF;
                border: 1px solid #1E293B;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 18px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #00D2BE;
                color: #000000;
                font-weight: 600;
            }
            QMenu::separator {
                height: 1px;
                background-color: #1E293B;
                margin: 4px 8px;
            }
        """)
        cfg = load_config()

        act_watcher = QAction(
            f"Фоновый мониторинг: {'ВКЛ' if self._watcher_enabled else 'ВЫКЛ'}",
            self,
        )
        act_watcher.setCheckable(True)
        act_watcher.setChecked(self._watcher_enabled)
        act_watcher.triggered.connect(lambda: self.toggle_background_watcher())
        menu.addAction(act_watcher)

        act_check = QAction("Проверить каналы сейчас", self)
        act_check.triggered.connect(self.check_channel_updates_now)
        menu.addAction(act_check)

        menu.addSeparator()

        min_tray = cfg.get("minimize_to_tray", True)
        act_min_tray = QAction("Сворачивать в трей при закрытии", self)
        act_min_tray.setCheckable(True)
        act_min_tray.setChecked(min_tray)
        act_min_tray.triggered.connect(lambda checked: save_config(minimize_to_tray=checked))
        menu.addAction(act_min_tray)

        tray_notif = cfg.get("tray_notifications", True)
        act_notif = QAction("Уведомления на рабочем столе", self)
        act_notif.setCheckable(True)
        act_notif.setChecked(tray_notif)
        act_notif.triggered.connect(lambda checked: save_config(tray_notifications=checked))
        menu.addAction(act_notif)

        if hasattr(self, "btn_notif"):
            menu.exec(self.btn_notif.mapToGlobal(self.btn_notif.rect().bottomLeft()))
        else:
            menu.exec(QCursor.pos())

    def show_and_activate_window(self):
        """Восстанавливает и активирует главное окно приложения."""
        self.show()
        self.setWindowState(
            (self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
        )
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        """Обработка клика по иконке трея."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.isVisible() and not self.isMinimized():
                self.show_and_activate_window()
            else:
                self.show_and_activate_window()

    def show_tray_notification(
        self,
        title: str,
        message: str,
        icon=QSystemTrayIcon.MessageIcon.Information,
        timeout_ms: int = 4000,
    ):
        """Отправляет уведомление в системный трей."""
        show_tray_notification(self, title, message, icon=icon, timeout_ms=timeout_ms)

    def quit_application(self):
        """Чистый выход из приложения с закрытием окна."""
        self._force_close = True
        self.close()

    def closeEvent(self, event):
        cfg = load_config()
        minimize_to_tray = cfg.get("minimize_to_tray", False)
        if (
            not getattr(self, "_force_close", False)
            and minimize_to_tray
            and hasattr(self, "tray_icon")
            and self.tray_icon
            and self.tray_icon.isVisible()
        ):
            event.ignore()
            self.hide()
            if not getattr(self, "_tray_minimized_notified", False):
                self._tray_minimized_notified = True
                self.show_tray_notification(
                    "BEATSTORM свёрнут в трей",
                    "Приложение работает в фоновом режиме. Кликните по иконке в трее для восстановления.",
                )
            return

        self._cleanup_on_exit()
        event.accept()

    def _cleanup_on_exit(self):
        """Очистка ресурсов при завершении работы приложения."""
        if hasattr(self, "_watcher_timer") and self._watcher_timer.isActive():
            self._watcher_timer.stop()
        if hasattr(self, "player_bar") and self.player_bar:
            try:
                self.player_bar.stop_playback()
            except Exception:
                pass
        if hasattr(self, "_player") and self._player:
            try:
                self._player.stop()
            except Exception:
                pass
        self.stop_download()
        th = getattr(self, "download_thread", None)
        if th is not None:
            is_running_fn = getattr(th, "isRunning", None)
            if callable(is_running_fn) and is_running_fn():
                wait_fn = getattr(th, "wait", None)
                finished_cleanly = False
                if callable(wait_fn):
                    try:
                        finished_cleanly = bool(wait_fn(2000))
                    except Exception:
                        pass
                if not finished_cleanly and is_running_fn():
                    _LINGERING_THREADS.add(th)
                    finished_sig = getattr(th, "finished", None)
                    if finished_sig and hasattr(finished_sig, "connect"):
                        try:
                            finished_sig.connect(lambda: _LINGERING_THREADS.discard(th))
                        except Exception:
                            pass
        if hasattr(self, "tray_icon") and self.tray_icon:
            self.tray_icon.hide()

    def show_qr_dialog(self, url):
        logger.debug("show_qr_dialog called")
        if self.qr_dialog:
            self.qr_dialog.close()
        self.qr_dialog = QRCodeDialog(url, self)
        self.qr_dialog.rejected.connect(lambda: self.stop_download())
        self.qr_dialog.show()
        self.qr_dialog.raise_()
        self.qr_dialog.activateWindow()
        if self.input_dialog:
            self.input_dialog.close()

    def show_input_dialog(self, prompt):
        logger.debug(f"show_input_dialog called with prompt: {prompt}")
        if self.input_dialog is None:
            self.input_dialog = InputCodeDialog(prompt, self)
            self.input_dialog.code_entered.connect(self.on_code_entered)
            self.input_dialog.finished.connect(self.on_dialog_closed)
            self.input_dialog.show()
            self.input_dialog.raise_()
            self.input_dialog.activateWindow()
        else:
            self.input_dialog.label.setText(prompt)
            self.input_dialog.input.clear()
            self.input_dialog.show()
            self.input_dialog.raise_()
            self.input_dialog.activateWindow()
        self._input_answered = False

    def on_code_entered(self, text):
        logger.debug(f"on_code_entered received: {text}")
        if self._input_answered:
            return
        if self.download_thread and text:
            self._input_answered = True
            self.download_thread.code_response_signal.emit(text)
        if self.input_dialog:
            self.input_dialog.close()

    def on_dialog_closed(self):
        logger.debug("Input dialog closed")
        if self._input_answered:
            return
        if self.download_thread:
            self._input_answered = True
            self.download_thread.code_response_signal.emit("")

    # -------------------------------------------------------------
    # Логика аудиоплеера (Preview Audio Player)
    # -------------------------------------------------------------
    def play_audio_file(self, filepath: str, title: str = ""):
        """Воспроизводит аудиофайл через встроенный QMediaPlayer."""
        self.player_bar.play_audio_file(filepath, title=title)

    def _toggle_playback(self):
        self.player_bar.toggle_playback()

    def _stop_playback(self):
        self.player_bar.stop_playback()

    def _on_media_state_changed(self, state):
        self.player_bar._on_media_state_changed(state)

    def _on_media_position_changed(self, position_ms):
        self.player_bar._on_media_position_changed(position_ms)

    def _on_media_duration_changed(self, duration_ms):
        self.player_bar._on_media_duration_changed(duration_ms)

    def _on_seek_slider_moved(self, value):
        self.player_bar._on_seek_slider_moved(value)

    def _on_volume_changed(self, value):
        self.player_bar._on_volume_changed(value)

    @staticmethod
    def _format_time_ms(ms: int) -> str:
        return AudioPlayerBar.format_time_ms(ms)

    def _on_track_double_clicked(self, item):
        track_id = item.data(Qt.ItemDataRole.UserRole)
        scan_tracks = getattr(self, "_scan_results", []) or []
        track = next((t for t in scan_tracks if t.get("id") == track_id), None)
        if not track:
            return
        self.play_or_preview_track(track)

    def _on_recent_table_double_clicked(self, item):
        """Воспроизводит трек из таблицы Recent Releases в Bento Studio при двойном клике или кнопке Play."""
        if not item or not hasattr(self, "home_recent_table"):
            return
        row = item.row()
        t_item = self.home_recent_table.item(row, 0)
        a_item = self.home_recent_table.item(row, 1)
        if not t_item:
            return
        user_data = t_item.data(Qt.ItemDataRole.UserRole)
        if isinstance(user_data, dict):
            self.play_or_preview_track(user_data)
        else:
            filepath = str(user_data) if user_data else ""
            artist = a_item.text() if a_item else ""
            title_text = t_item.text() if t_item else ""
            title = f"{artist} - {title_text}".strip(" -")
            if filepath and os.path.exists(filepath):
                self.player_bar.setVisible(True)
                self.play_audio_file(filepath, title=title)
                self.log(f"▶ Воспроизведение: {title}")
            else:
                self.log(f"⚠️ Аудиофайл не найден на диске: {filepath or title}")

    def play_or_preview_track(self, track):
        """Воспроизводит локальный файл или инициирует потоковое предпрослушивание чанков."""
        filepath = track.get("filepath") or track.get("file_path") or ""
        title = f"{track.get('performer') or track.get('artist', '')} - {track.get('title', '')}".strip(" -")
        msg_id = track.get("id") or track.get("message_id")
        chan = track.get("channel") or track.get("channel_id") or (self.channel_input.text().strip() if hasattr(self, "channel_input") else "")

        # 1. Если файл уже полностью сохранен на диске
        if filepath and os.path.isfile(filepath):
            self.player_bar.setVisible(True)
            self.play_audio_file(filepath, title=title)
            self.log(f"▶ Воспроизведение: {title}")
            return

        # 2. Если уже есть скачанное превью в кэше
        # Каталог кэша обязан совпадать с recorder.py (там: BASE_PATH + "previews"),
        # иначе при запуске из dist/ относительный путь не найдёт кэш.
        base = getattr(self, "base_folder", None) or BASE_PATH
        preview_dir = os.path.join(base, "previews")
        if msg_id and os.path.exists(preview_dir):
            for ext in (".mp3", ".m4a", ".ogg", ".flac", ".wav"):
                cand = os.path.join(preview_dir, f"preview_{msg_id}{ext}")
                if os.path.isfile(cand) and os.path.getsize(cand) >= 32 * 1024:
                    self.player_bar.setVisible(True)
                    self.play_audio_file(cand, title=f"⚡ [PREVIEW] {title}")
                    self.log(f"🎧 Воспроизведение из кэша превью: {title}")
                    return

        # 3. Если загрузка или сканирование заняты
        if self.download_thread and self.download_thread.isRunning():
            if getattr(self.download_thread, "preview_track_id", None):
                try:
                    self.download_thread.cancel()
                    self.download_thread.wait(400)
                except Exception:
                    pass
            else:
                self.player_bar.setVisible(True)
                self.player_title_label.setText(f"⏳ Файл ещё не скачан: {title}")
                self.log(f"Поток занят. Файл ещё не скачан: {title}")
                return

        # 4. Запускаем потоковую буферизацию превью через DownloadThread
        if msg_id:
            self.player_bar.setVisible(True)
            self.player_title_label.setText(f"⚡ Буферизация превью: {title}...")
            self.log(f"⚡ Запрос потокового предпрослушивания для «{title}»...")
            self.start_preview_stream(chan, msg_id, title)
        else:
            self.player_bar.setVisible(True)
            self.player_title_label.setText(f"⏳ Файл ещё не скачан: {title}")
            self.log(f"Файл ещё не скачан: {title}")

    def start_preview_stream(self, channel, track_id, title=""):
        """Запускает фоновый поток буферизации превью через DownloadThread."""
        params = self._validate_inputs(require_channel=False)
        if not params:
            self.player_title_label.setText(f"⏳ Файл ещё не скачан: {title}")
            self.log(f"Для превью укажите API ID и API Hash. Файл ещё не скачан: {title}")
            return
        api_id, api_hash, default_ch, mode, date_from, date_to = params
        target_channel = channel or default_ch

        th = getattr(self, "download_thread", None)
        if th is not None and getattr(th, "isRunning", lambda: False)():
            self.log("⚠️ Предыдущая операция ещё выполняется. Дождитесь завершения или нажмите «Стоп».")
            return

        old_th = getattr(self, "download_thread", None)
        if old_th is not None:
            _LINGERING_THREADS.add(old_th)
            try:
                finished_sig = getattr(old_th, "finished", None)
                if finished_sig and hasattr(finished_sig, "connect"):
                    finished_sig.connect(lambda t=old_th: _LINGERING_THREADS.discard(t))
            except Exception:
                pass
            self.download_thread = None

        proxy_cfg = self._get_proxy_config() if hasattr(self, "_get_proxy_config") else getattr(self, "_proxy_config", None)
        self.download_thread = DownloadThread(
            api_id,
            api_hash,
            target_channel,
            mode,
            date_from,
            date_to,
            proxy_config=proxy_cfg,
            preview_track_id=track_id,
        )
        self.download_thread.log_signal.connect(self.log)
        self.download_thread.preview_signal.connect(self._on_preview_ready)
        self.download_thread.finished_signal.connect(self._on_preview_finished)
        self.download_thread.request_code_signal.connect(self.show_input_dialog)
        self.download_thread.qr_login_signal.connect(self.show_qr_dialog)
        self.download_thread.start()

    def _on_preview_ready(self, track_id, preview_path):
        """Вызывается при получении первых чанков потокового превью."""
        if not preview_path:
            return
        scan_tracks = getattr(self, "_scan_results", []) or []
        track = next((t for t in scan_tracks if t.get("id") == track_id), None)
        title = (
            f"{track.get('performer', '')} - {track.get('title', '')}".strip(" -")
            if track
            else f"Трек #{track_id}"
        )
        self.play_audio_file(preview_path, title=f"⚡ [PREVIEW] {title}")
        self.log(f"🎧 Воспроизведение потокового превью: {title}")

    def _on_preview_finished(self):
        """Очистка ссылки на поток после завершения буферизации превью."""
        sender = self.sender() if hasattr(self, "sender") else None
        curr_th = getattr(self, "download_thread", None)
        if sender is not None and curr_th is not None and sender is not curr_th:
            return
        if self.download_thread and getattr(self.download_thread, "preview_track_id", None):
            old_th = self.download_thread
            _LINGERING_THREADS.add(old_th)
            try:
                finished_sig = getattr(old_th, "finished", None)
                if finished_sig and hasattr(finished_sig, "connect"):
                    finished_sig.connect(lambda t=old_th: _LINGERING_THREADS.discard(t))
            except Exception:
                pass
            self.download_thread = None

    def _dj_text_input_focused(self):
        """True, если фокус в поле ввода — тогда горячие клавиши не применяются."""
        from PyQt6.QtWidgets import (
            QLineEdit,
            QTextEdit,
            QPlainTextEdit,
            QSpinBox,
            QDoubleSpinBox,
            QComboBox,
        )

        return isinstance(
            self.focusWidget(),
            (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox),
        )

    def _dj_clear_search(self):
        """Shift+C — сброс поиска по всем полям и снятие фильтра."""
        if self._dj_text_input_focused():
            return
        for attr in (
            "top_search_input",
            "search_filter_input",
            "channel_search_input",
            "home_search_input",
        ):
            field = getattr(self, attr, None)
            if field is not None and hasattr(field, "clear"):
                field.clear()
        if hasattr(self, "_filter_tracks_text"):
            self._filter_tracks_text("")

    def _dj_start_download(self):
        """Shift+D — запуск загрузки отмеченных треков."""
        if self._dj_text_input_focused():
            return
        if hasattr(self, "start_download"):
            self.start_download()

    def keyPressEvent(self, event):
        """DJ Hotkeys: Space (Play/Pause), X/Enter (Toggle check), Arrows (Seek +-10s), Shift+D (Download), Shift+C (Clear search)."""
        focused = self.focusWidget()
        from PyQt6.QtWidgets import (
            QLineEdit,
            QTextEdit,
            QPlainTextEdit,
            QSpinBox,
            QDoubleSpinBox,
            QComboBox,
        )

        is_text_input = isinstance(
            focused,
            (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox),
        )

        key = event.key()
        modifiers = event.modifiers()

        if is_text_input:
            super().keyPressEvent(event)
            return

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            if key == Qt.Key.Key_D:
                self._dj_start_download()
                event.accept()
                return
            elif key == Qt.Key.Key_C:
                self._dj_clear_search()
                event.accept()
                return

        if key == Qt.Key.Key_Space:
            if hasattr(self, "player_bar"):
                if (
                    self.player_bar._current_audio_path
                    and self.player_bar._player
                    and os.path.exists(self.player_bar._current_audio_path)
                ):
                    self._toggle_playback()
                else:
                    cur_item = (
                        self.library_tree.currentItem()
                        if hasattr(self, "library_tree")
                        else None
                    )
                    if cur_item:
                        self._on_tree_item_double_clicked(cur_item, 0)
            event.accept()
            return

        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            delta = -10000 if key == Qt.Key.Key_Left else 10000
            if hasattr(self, "player_bar"):
                self.player_bar.seek_relative(delta)
            event.accept()
            return

        if key in (Qt.Key.Key_X, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Shift+X не переключает чекбокс: заглавная «X» нужна для
            # перехода по первой букве, как и в eventFilter ниже.
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            cur_item = (
                self.library_tree.currentItem()
                if hasattr(self, "library_tree")
                else None
            )
            if cur_item and hasattr(self, "toggle_item_check_state"):
                self.toggle_item_check_state(cur_item)
                event.accept()
                return

        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        """Перехватывает DJ-горячие клавиши, когда фокус в дереве библиотеки.

        keyPressEvent окна не срабатывает: QTreeWidget обрабатывает буквенные
        клавиши сам (переход к элементу по первой букве) и событие до окна
        не доходит. Здесь «X»/Enter переключают чекбокс выделенного трека,
        Space — запускает воспроизведение.
        """
        from PyQt6.QtCore import QEvent

        tree = getattr(self, "library_tree", None)
        if (
            event.type() == QEvent.Type.KeyPress
            and tree is not None
            and obj in (tree, tree.viewport())
        ):
            if event.modifiers() & (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
            ):
                return False
            key = event.key()
            cur_item = tree.currentItem()
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if key in (Qt.Key.Key_X, Qt.Key.Key_Return, Qt.Key.Key_Enter) and not shift:
                if cur_item is not None and hasattr(self, "toggle_item_check_state"):
                    self.toggle_item_check_state(cur_item)
                    return True
            elif key == Qt.Key.Key_Space and cur_item is not None:
                if hasattr(self, "_on_tree_item_double_clicked"):
                    self._on_tree_item_double_clicked(cur_item, 0)
                    return True
        return super().eventFilter(obj, event)

