"""
Download Controller Mixin for MainWindow (TelegramAudioDownloader).

Encapsulates:
- Input validation (API ID, API Hash, channel, date range);
- Channel scanning and progressive prefetch pagination;
- Multi-threaded download execution (start, stop, cancel);
- Multi-stream progress tracking and live speed monitoring;
- Proxy dialog and download folder launcher.
"""

import os
import re
import sys
import logging
from PyQt6.QtWidgets import QMessageBox

from downloader import DownloadThread
from config import BASE_PATH
from ui.dialogs import ProxySettingsDialog, is_ffmpeg_available
from ui.widgets import create_waveform_pixmap

logger = logging.getLogger(__name__)


def _get_download_thread_cls():
    if "gui" in sys.modules and hasattr(sys.modules["gui"], "DownloadThread"):
        return sys.modules["gui"].DownloadThread
    return DownloadThread


def _check_ffmpeg_available() -> bool:
    if "gui" in sys.modules and hasattr(sys.modules["gui"], "is_ffmpeg_available"):
        return sys.modules["gui"].is_ffmpeg_available()
    return is_ffmpeg_available()



class DownloadControllerMixin:
    """Управление процессами сканирования и скачивания аудиофайлов."""

    def _validate_inputs(self, require_channel=True):
        api_id = self.api_id_input.text().strip()
        api_hash = self.api_hash_input.text().strip()
        channel = self.channel_input.text().strip()
        if not api_id or not api_hash or (require_channel and not channel):
            QMessageBox.warning(
                self, "Ошибка", "Пожалуйста, заполните API ID, API Hash и канал."
            )
            return None
        try:
            api_id = int(api_id)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "API ID должен быть числом.")
            return None
        mode = self.mode_combo.currentData() or "direct"
        date_from = self.date_from_input.text().strip() or None
        date_to = self.date_to_input.text().strip() or None

        date_pattern = r"^\d{4}-\d{2}-\d{2}$"

        if date_from and not re.match(date_pattern, date_from):
            QMessageBox.warning(
                self, "Ошибка", "Формат даты начала неверен. Используйте ГГГГ-ММ-ДД."
            )
            return None
        if date_to and not re.match(date_pattern, date_to):
            QMessageBox.warning(
                self, "Ошибка", "Формат конечной даты неверен. Используйте ГГГГ-ММ-ДД."
            )
            return None

        if date_from and date_to and date_from > date_to:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Начальная дата не может быть позже конечной.",
            )
            return None

        self._save_settings()
        return api_id, api_hash, channel, mode, date_from, date_to

    def open_proxy_settings(self):
        dlg = ProxySettingsDialog(self)
        dlg.set_proxy_config(getattr(self, "_proxy_config", {}))
        if dlg.exec():
            self._proxy_config = dlg.get_proxy_config()
            self._update_proxy_button_label()
            self._save_settings()
            status_text = "включен" if self._proxy_config.get("enabled") else "отключен"
            self.log(f"Настройки прокси сохранены ({status_text}).")

    def open_download_folder(self):
        channel = self.channel_input.text().strip()
        # Единый абсолютный путь из config: относительный путь разрешался бы
        # от текущего каталога процесса, и при запуске из ярлыка кнопка
        # открывала бы не ту папку, а os.makedirs оставлял бы пустую копию.
        base_dir = BASE_PATH
        folder = base_dir
        if channel:
            clean_name = (
                channel.lstrip("@")
                .replace("https://t.me/", "")
                .replace("http://t.me/", "")
                .split("/")[0]
            )
            channel_folder = os.path.join(base_dir, clean_name)
            if os.path.exists(channel_folder):
                folder = os.path.abspath(channel_folder)
        os.makedirs(folder, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", folder])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            logger.warning(f"Не удалось открыть папку: {e}")
            QMessageBox.information(
                self, "Папка загрузок", f"Путь к папке:\n{folder}"
            )

    def _auto_start_scan(self):
        """Автоматический запуск сканирования сохраненных каналов при старте приложения."""
        api_id = self.api_id_input.text().strip()
        api_hash = self.api_hash_input.text().strip()
        if not api_id or not api_hash:
            logger.info("Авто-сканирование отложено: API ID / Hash не заполнены.")
            self.log("💡 Для авто-сканирования каналов укажите API ID и API Hash в настройках.")
            return

        channels = getattr(self, "_saved_channels", [])
        if not channels:
            logger.info("Авто-сканирование: сохраненных каналов нет.")
            return

        self.log(f"🚀 Авто-сканирование сохраненных каналов ({len(channels)})...")
        self.start_scan(channels=channels, limit_per_channel=100)

    def start_scan(self, channels=None, limit_per_channel=100, search_query=None):
        th = getattr(self, "download_thread", None)
        if th is not None and getattr(th, "isRunning", lambda: False)():
            self.log("⚠️ Предыдущая операция ещё выполняется. Дождитесь завершения или нажмите «Стоп».")
            return
        if isinstance(channels, bool):
            channels = None
        req_ch = (channels is None)
        params = self._validate_inputs(require_channel=req_ch)
        if not params:
            return
        api_id, api_hash, channel, mode, date_from, date_to = params
        saved = getattr(self, "_saved_channels", []) or []

        if channels:
            target_channels = list(channels)
        else:
            if saved:
                target_channels = list(saved)
                if channel and channel not in target_channels and channel != "__ALL__":
                    target_channels.append(channel)
            elif channel and channel != "__ALL__":
                target_channels = [channel]
            else:
                target_channels = []

        self._current_scan_channels = list(target_channels)
        self._channel_offsets = {}
        self._no_more_tracks = False
        sq = search_query.strip() if search_query and isinstance(search_query, str) else None
        self._current_search_query = sq

        self.log_output.clear()
        self.progress_label.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.track_list.clear()
        if hasattr(self, "library_tree"):
            self.library_tree.clear()
        if hasattr(self, "btn_load_more"):
            self.btn_load_more.setText("⬇ Загрузить ещё треки (более ранние даты)...")
            self.btn_load_more.setEnabled(True)
            self.btn_load_more.setVisible(False)
        if hasattr(self, "batch_bar"):
            self.batch_bar.setVisible(False)
            if not sq:
                self.search_filter_input.clear()
        self.download_button.setEnabled(False)

        ch_disp = (
            ", ".join(target_channels)
            if len(target_channels) > 1
            else (target_channels[0] if target_channels else (channel or "—"))
        )

        if sq:
            self.log(f"🔎 Глобальный поиск по запросу '{sq}' в ({ch_disp})...")
            if hasattr(self, "status_badge"):
                self.status_badge.setText("● SEARCHING...")
                self.status_badge.setStyleSheet(
                    "background-color: #261E10; border: 1px solid #784E10; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 700; color: #FFB300;"
                )
        else:
            if len(target_channels) > 1:
                self.log(f"Сканирование сохраненных каналов ({len(target_channels)}): {ch_disp}...")
            else:
                self.log(f"Сканирование канала {ch_disp}...")

            if hasattr(self, "status_badge"):
                self.status_badge.setText("● SCANNING POOL...")
                self.status_badge.setStyleSheet(
                    "background-color: #261E10; border: 1px solid #784E10; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 700; color: #FFB300;"
                )

        old_th = getattr(self, "download_thread", None)
        if old_th is not None:
            from gui import _LINGERING_THREADS
            _LINGERING_THREADS.add(old_th)
            try:
                finished_sig = getattr(old_th, "finished", None)
                if finished_sig and hasattr(finished_sig, "connect"):
                    finished_sig.connect(lambda t=old_th: _LINGERING_THREADS.discard(t))
            except Exception:
                pass
            self.download_thread = None

        self.download_thread = _get_download_thread_cls()(
            api_id,
            api_hash,
            channel or (target_channels[0] if target_channels else ""),
            mode,
            date_from,
            date_to,
            self._proxy_config,
            scan_only=True,
            channels=target_channels,
            limit_per_channel=limit_per_channel,
            channel_offsets=self._channel_offsets,
            search_query=sq,
        )
        self.download_thread.log_signal.connect(self.log)
        self.download_thread.finished_signal.connect(self._scan_finished)
        self.download_thread.scan_signal.connect(self._on_scan_results)
        self.download_thread.request_code_signal.connect(self.show_input_dialog)
        self.download_thread.qr_login_signal.connect(self.show_qr_dialog)
        self.download_thread.start()

        self.scan_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        if hasattr(self, "bento_btn_scan"):
            self.bento_btn_scan.setEnabled(False)
        if hasattr(self, "bento_btn_stop"):
            self.bento_btn_stop.setEnabled(True)

    def _search_channel_history(self, query=None):
        """Запуск поиска по всей истории Telegram-канала через MTProto."""
        if not isinstance(query, str) or not query.strip():
            candidates = []
            if hasattr(self, "search_filter_input"):
                candidates.append(self.search_filter_input.text().strip())
            if hasattr(self, "top_search_input"):
                candidates.append(self.top_search_input.text().strip())
            if hasattr(self, "home_search_input"):
                candidates.append(self.home_search_input.text().strip())
            query = next((c for c in candidates if c), "")

        query = query.strip()
        if not query:
            self.log("⚠️ Введите запрос для поиска по всей истории канала.")
            return

        if hasattr(self, "search_filter_input") and self.search_filter_input.text() != query:
            self.search_filter_input.blockSignals(True)
            self.search_filter_input.setText(query)
            self.search_filter_input.blockSignals(False)
        if hasattr(self, "top_search_input") and self.top_search_input.text() != query:
            self.top_search_input.blockSignals(True)
            self.top_search_input.setText(query)
            self.top_search_input.blockSignals(False)
        if hasattr(self, "home_search_input") and self.home_search_input.text() != query:
            self.home_search_input.blockSignals(True)
            self.home_search_input.setText(query)
            self.home_search_input.blockSignals(False)

        from config import DEFAULT_SEARCH_LIMIT

        chan = self.channel_input.text().strip() if hasattr(self, "channel_input") else ""
        saved = getattr(self, "_saved_channels", []) or []
        target_channels = None
        if chan and chan != "__ALL__":
            target_channels = [chan]
        elif saved:
            target_channels = list(saved)

        self.start_scan(channels=target_channels, limit_per_channel=DEFAULT_SEARCH_LIMIT, search_query=query)

    def _load_more_tracks(self):
        """Прогрессивная подгрузка следующей порции треков из каналов по мере скроллинга."""
        if getattr(self, "download_thread", None) is not None:
            return
        if getattr(self, "_no_more_tracks", False):
            return
        if getattr(self, "_is_paginating", False):
            return

        active_channels = getattr(self, "_current_scan_channels", None) or self._saved_channels
        if not active_channels:
            return

        api_id = self.api_id_input.text().strip()
        api_hash = self.api_hash_input.text().strip()
        if not api_id or not api_hash:
            return

        mode = self.mode_combo.currentData() or "direct"
        date_from = self.date_from_input.text().strip() or None
        date_to = self.date_to_input.text().strip() or None

        self.log("⏳ Прогрузка следующей порции треков из каналов...")
        if hasattr(self, "status_badge"):
            self.status_badge.setText("● LOADING MORE...")
            self.status_badge.setStyleSheet(
                "background-color: #261E10; border: 1px solid #784E10; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 700; color: #FFB300;"
            )

        self._is_paginating = True
        self.download_thread = _get_download_thread_cls()(
            api_id,
            api_hash,
            active_channels[0] if active_channels else "",
            mode,
            date_from,
            date_to,
            self._proxy_config,
            scan_only=True,
            channels=active_channels,
            limit_per_channel=100,
            channel_offsets=getattr(self, "_channel_offsets", {}),
            search_query=getattr(self, "_current_search_query", None),
        )
        self.download_thread.log_signal.connect(self.log)
        self.download_thread.finished_signal.connect(self._scan_finished)
        self.download_thread.scan_signal.connect(self._on_scan_results_page)
        self.download_thread.request_code_signal.connect(self.show_input_dialog)
        self.download_thread.qr_login_signal.connect(self.show_qr_dialog)
        self.download_thread.start()
        self.stop_button.setEnabled(True)

    def _on_scan_results_page(self, new_tracks):
        """Обработка прибывшей страницы треков при скролле (быстрое инкрементальное добавление)."""
        self._is_paginating = False
        if not new_tracks:
            self._no_more_tracks = True
            self.log("✅ Вся доступная история каналов загружена.")
            if hasattr(self, "btn_load_more"):
                self.btn_load_more.setText("✓ Вся история каналов загружена")
                self.btn_load_more.setEnabled(False)
            return

        existing_keys = {
            (t.get("channel", ""), t.get("id"))
            for t in getattr(self, "_scan_results", [])
        }
        truly_new = [
            t for t in new_tracks
            if (t.get("channel", ""), t.get("id")) not in existing_keys
        ]

        if not truly_new:
            self._no_more_tracks = True
            self.log("✅ Достигнут конец доступной истории каналов.")
            if hasattr(self, "btn_load_more"):
                self.btn_load_more.setText("✓ Вся история каналов загружена")
                self.btn_load_more.setEnabled(False)
            return

        for t in truly_new:
            ch = t.get("channel", "")
            tid = t.get("id")
            scanned_last = t.get("channel_last_scanned_id")
            cand = scanned_last if (scanned_last and scanned_last > 0) else tid
            if ch and cand:
                cur = self._channel_offsets.get(ch, cand)
                self._channel_offsets[ch] = min(cur, cand)

        self._scan_results.extend(truly_new)
        self._append_tracks_to_tree(truly_new)
        self.log(f"Загружено ещё {len(truly_new)} треков (Всего в пуле: {len(self._scan_results)})")

    def _on_scan_results(self, tracks):
        self._scan_results = list(tracks)

        self._channel_offsets = {}
        for t in tracks:
            ch = t.get("channel", "")
            tid = t.get("id")
            scanned_last = t.get("channel_last_scanned_id")
            cand = scanned_last if (scanned_last and scanned_last > 0) else tid
            if ch and cand:
                cur = self._channel_offsets.get(ch, cand)
                self._channel_offsets[ch] = min(cur, cand)

        self._render_tracks_in_tree(self._scan_results)
        if getattr(self, "_selected_channel_filter", None):
            self._filter_tree_by_channel(self._selected_channel_filter)
        if hasattr(self, "_refresh_home_view"):
            self._refresh_home_view()

        self.track_list.setVisible(False)
        if hasattr(self, "batch_bar"):
            self.batch_bar.setVisible(len(tracks) > 0)
        if hasattr(self, "btn_load_more"):
            self.btn_load_more.setVisible(len(tracks) > 0)

        if hasattr(self, "status_badge"):
            if getattr(self, "_current_search_query", None):
                self.status_badge.setText(f"● FOUND: {len(tracks)}" if tracks else "● NOT FOUND")
            else:
                self.status_badge.setText("● POOL READY" if tracks else "● STANDBY")
            self.status_badge.setStyleSheet(
                "background-color: #161A24; border: 1px solid #252D3D; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 700; color: #00E5FF;"
            )

        if tracks:
            self.download_button.setEnabled(True)
            if hasattr(self, "bento_btn_download"):
                self.bento_btn_download.setEnabled(True)
            self._update_download_button_counter()
            if getattr(self, "_current_search_query", None):
                self.log(
                    f"🔎 Найдено {len(tracks)} треков по запросу '{self._current_search_query}'."
                )
            else:
                self.log(
                    f"Найдено {len(tracks)} треков. Выберите нужные и нажмите «Скачать выбранное»."
                )
            if hasattr(self, "show_tray_notification") and not self.isVisible():
                self.show_tray_notification(
                    "BEATSTORM Watcher",
                    f"Обнаружено {len(tracks)} новых треков в канале!",
                )
        elif getattr(self, "_current_search_query", None):
            self.log(f"ℹ️ По запросу '{self._current_search_query}' треков в канале не найдено.")

    def _scan_finished(self):
        sender = self.sender() if hasattr(self, "sender") else None
        curr_th = getattr(self, "download_thread", None)
        if sender is not None and curr_th is not None and sender is not curr_th:
            return

        self._is_paginating = False
        self.scan_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if hasattr(self, "bento_btn_scan"):
            self.bento_btn_scan.setEnabled(True)
        if hasattr(self, "bento_btn_stop"):
            self.bento_btn_stop.setEnabled(False)

        th = getattr(self, "download_thread", None)
        if th is not None:
            from gui import _LINGERING_THREADS
            _LINGERING_THREADS.add(th)
            try:
                finished_sig = getattr(th, "finished", None)
                if finished_sig and hasattr(finished_sig, "connect"):
                    finished_sig.connect(lambda t=th: _LINGERING_THREADS.discard(t))
            except Exception:
                pass
            self.download_thread = None

        if hasattr(self, "status_badge"):
            self.status_badge.setText("● POOL READY" if self._scan_results else "● STANDBY")
            self.status_badge.setStyleSheet(
                "background-color: #161A24; border: 1px solid #252D3D; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 700; color: #00E5FF;"
            )
        if self.qr_dialog:
            self.qr_dialog.blockSignals(True)
            self.qr_dialog.close()
            self.qr_dialog = None

    def start_download(self):
        th = getattr(self, "download_thread", None)
        if th is not None and getattr(th, "isRunning", lambda: False)():
            self.log("⚠️ Предыдущая операция ещё выполняется. Дождитесь завершения или нажмите «Стоп».")
            return
        params = self._validate_inputs()
        if not params:
            return
        api_id, api_hash, channel, mode, date_from, date_to = params

        if not _check_ffmpeg_available():
            if mode == "record":
                QMessageBox.critical(
                    self,
                    "ffmpeg не найден",
                    "ffmpeg не обнаружен в PATH. Режим записи звука требует ffmpeg "
                    "для конвертации в MP3.\n\nОперация не может быть выполнена.",
                )
                return
            reply = QMessageBox.warning(
                self,
                "ffmpeg не найден",
                "ffmpeg не обнаружен в PATH. Конвертация в MP3 будет недоступна "
                "(скачанные файлы сохранятся в исходном формате).\n\nПродолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        from PyQt6.QtCore import Qt

        selected_ids = []
        selected_channel_map = {}

        def _collect(mid, ch):
            if mid in selected_ids:
                return
            selected_ids.append(mid)
            if ch:
                selected_channel_map.setdefault(ch, []).append(mid)

        # Приоритет у library_tree: на вкладке Library пользователь оставляет
        # галочки именно в дереве, а скрытый track_list — его зеркало с
        # устаревшим состоянием. Раньше выбор игнорировался и скачивались
        # ВСЕ треки диапазона вместо отмеченных.
        tree_ids = []
        if hasattr(self, "library_tree") and self.library_tree:
            tree = self.library_tree
            known = getattr(self, "_track_by_id", {})

            def _walk(parent):
                for idx in range(parent.childCount()):
                    child = parent.child(idx)
                    _walk(child)
                    raw = child.data(0, Qt.ItemDataRole.UserRole)
                    # Элемент трека — только тот, чей UserRole содержит msg_id,
                    # присутствующий в _track_by_id. Группы дат и каналов
                    # хранят там строки, их в выборку не включаем.
                    if isinstance(raw, int) and raw in known:
                        if child.checkState(0) == Qt.CheckState.Checked:
                            tree_ids.append(raw)

            for top in range(tree.topLevelItemCount()):
                _walk(tree.topLevelItem(top))

        if tree_ids or (hasattr(self, "library_tree") and self.library_tree.topLevelItemCount()):
            for mid in tree_ids:
                t_data = getattr(self, "_track_by_id", {}).get(mid, {})
                _collect(mid, t_data.get("channel") or channel or "")
            # Пользователь действует в дереве Library: home_recent_table здесь
            # не при чём — он отмечен по умолчанию и добавлял ВСЕ треки,
            # из-за чего выбор снова игнорировался.
            tree_is_source = True
        else:
            for i in range(self.track_list.count()):
                item = self.track_list.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    mid = item.data(Qt.ItemDataRole.UserRole)
                    t_data = getattr(self, "_track_by_id", {}).get(mid, {})
                    _collect(mid, t_data.get("channel") or channel or "")
            tree_is_source = False

        if not tree_is_source and hasattr(self, "home_recent_table") and self.home_recent_table:
            for r in range(self.home_recent_table.rowCount()):
                t_it = self.home_recent_table.item(r, 0)
                if t_it and t_it.checkState() == Qt.CheckState.Checked:
                    t_data = t_it.data(Qt.ItemDataRole.UserRole)
                    if isinstance(t_data, dict):
                        mid = t_data.get("id") or t_data.get("message_id")
                        ch = t_data.get("channel") or t_data.get("channel_id") or channel or ""
                        if mid:
                            _collect(mid, ch)

        if not selected_ids:
            QMessageBox.warning(
                self, "Ошибка", "Не выбрано ни одного трека для загрузки."
            )
            return

        self.log_output.clear()
        self.progress_label.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.log(f"Загрузка {len(selected_ids)} треков...")
        if hasattr(self, "status_badge"):
            self.status_badge.setText("● DOWNLOADING...")
            self.status_badge.setStyleSheet(
                "background-color: #10241A; border: 1px solid #1A5432; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 700; color: #00E676;"
            )

        if hasattr(self, "_track_status_badges"):
            for m_id in selected_ids:
                if m_id in self._track_status_badges:
                    badge = self._track_status_badges[m_id]
                    badge.setText("QUEUED")
                    badge.setStyleSheet("""
                        background-color: #2D2208;
                        border: 1px solid #B45309;
                        border-radius: 9px;
                        color: #F59E0B;
                        font-size: 9px;
                        font-weight: 800;
                        padding: 1px 6px;
                    """)
                    badge.setToolTip("Трек находится в очереди на скачивание")

        active_channels = list(selected_channel_map.keys()) if selected_channel_map else (
            getattr(self, "_current_scan_channels", None) or ([channel] if channel else getattr(self, "_saved_channels", []))
        )
        old_th = getattr(self, "download_thread", None)
        if old_th is not None:
            from gui import _LINGERING_THREADS
            _LINGERING_THREADS.add(old_th)
            try:
                finished_sig = getattr(old_th, "finished", None)
                if finished_sig and hasattr(finished_sig, "connect"):
                    finished_sig.connect(lambda t=old_th: _LINGERING_THREADS.discard(t))
            except Exception:
                pass
            self.download_thread = None

        self.download_thread = _get_download_thread_cls()(
            api_id,
            api_hash,
            channel or (active_channels[0] if active_channels else ""),
            mode,
            date_from,
            date_to,
            self._proxy_config,
            selected_ids=selected_ids,
            max_concurrent_downloads=self.threads_spin.value(),
            mp3_bitrate=self.bitrate_combo.currentText(),
            channels=active_channels,
            selected_channel_map=selected_channel_map,
        )
        self.download_thread.log_signal.connect(self.log)
        self.download_thread.finished_signal.connect(self.download_finished)
        self.download_thread.request_code_signal.connect(self.show_input_dialog)
        self.download_thread.qr_login_signal.connect(self.show_qr_dialog)
        self.download_thread.progress_signal.connect(self.update_progress)
        self.download_thread.start()

        self.scan_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.track_list.setEnabled(False)
        self.stop_button.setEnabled(True)
        if hasattr(self, "bento_btn_scan"):
            self.bento_btn_scan.setEnabled(False)
        if hasattr(self, "bento_btn_download"):
            self.bento_btn_download.setEnabled(False)
        if hasattr(self, "bento_btn_stop"):
            self.bento_btn_stop.setEnabled(True)

    def stop_download(self):
        if self.download_thread:
            self.log("Запрос на остановку загрузки...")
            self.download_thread.cancel()
            self.scan_button.setEnabled(True)
            self.download_button.setEnabled(bool(self._scan_results))
            self.track_list.setEnabled(True)
            self.stop_button.setEnabled(False)
            if hasattr(self, "bento_btn_scan"):
                self.bento_btn_scan.setEnabled(True)
            if hasattr(self, "bento_btn_download"):
                self.bento_btn_download.setEnabled(bool(self._scan_results))
            if hasattr(self, "bento_btn_stop"):
                self.bento_btn_stop.setEnabled(False)
        if hasattr(self, "status_badge"):
            self.status_badge.setText("● STOPPED")
            self.status_badge.setStyleSheet(
                "background-color: #261214; border: 1px solid #5C1D24; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 700; color: #EF4444;"
            )
        if self.qr_dialog:
            self.qr_dialog.close()
            self.qr_dialog = None

    def update_progress(self, data):
        scanned = data.get("total_scanned", 0)
        audio = data.get("audio_found", 0)
        downloaded = data.get("downloaded", 0)
        skipped = data.get("skipped", 0)
        exists = data.get("already_exists", 0)
        total_tasks = data.get("total_tasks", 0)
        eta_sec = data.get("eta_seconds", 0)
        eta_str = (
            f"{int(eta_sec // 60)} мин {int(eta_sec % 60)} сек" if eta_sec > 0 else "—"
        )

        total = audio - exists - skipped
        if total > 0 and downloaded > 0 and total_tasks > 0:
            pct = int(downloaded / max(total_tasks, 1) * 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setVisible(True)
        elif total_tasks > 0:
            pct = int(downloaded / max(total_tasks, 1) * 100)
            self.progress_bar.setValue(pct)
            self.progress_bar.setVisible(True)

        parts = [
            f"Просмотрено: {scanned}",
            f"Аудио: {audio}",
            f"Загружено: {downloaded}/{max(total_tasks, total)}",
            f"Пропущено: {skipped}",
            f"Уже есть: {exists}",
            f"ETA: {eta_str}",
        ]
        current = data.get("current_file", "")
        if current:
            parts.append(f"Файл: {current}")

        self.progress_label.setText(" | ".join(parts))

        # 1. Обновление статусов в таблице треков
        active_downloads = data.get("active_downloads", [])
        if hasattr(self, "_track_status_badges"):
            for dl in active_downloads:
                m_id = dl.get("id")
                if m_id and m_id in self._track_status_badges:
                    badge = self._track_status_badges[m_id]
                    pct = dl.get("percent", 0)
                    badge.setText(f"DOWNLOADING {pct}%" if pct > 0 else "DOWNLOADING")
                    badge.setStyleSheet("""
                        background-color: #2E220E;
                        border: 1px solid #E5A93C;
                        border-radius: 9px;
                        color: #E5A93C;
                        font-size: 9px;
                        font-weight: 800;
                        padding: 1px 6px;
                    """)
                    badge.setToolTip("Файл активно скачивается...")

            completed_id = data.get("last_completed_id")
            if completed_id and completed_id in self._track_status_badges:
                badge = self._track_status_badges[completed_id]
                badge.setText("SAVED")
                badge.setStyleSheet("""
                    background-color: #0E2B18;
                    border: 1px solid #2ECC71;
                    border-radius: 9px;
                    color: #2ECC71;
                    font-size: 9px;
                    font-weight: 800;
                    padding: 1px 6px;
                """)
                badge.setToolTip("Файл успешно скачан и сохранен")
                if completed_id in getattr(self, "_track_waveforms", {}):
                    self._track_waveforms[completed_id].setPixmap(
                        create_waveform_pixmap(150, 22, "#2ECC71", seed=completed_id)
                    )
                    self._track_waveforms[completed_id].setToolTip("Файл сохранен на диске")
                row = getattr(self, "_track_row_by_id", {}).get(completed_id)
                if row is not None and row < len(self._scan_results):
                    self._scan_results[row]["already_exists"] = True

            failed_ids = data.get("failed_ids") or []
            if not failed_ids and data.get("last_failed_id"):
                failed_ids = [data.get("last_failed_id")]
            for m_id in failed_ids:
                if m_id in self._track_status_badges:
                    badge = self._track_status_badges[m_id]
                    badge.setText("FAILED")
                    badge.setStyleSheet("""
                        background-color: #2B0E14;
                        border: 1px solid #EF4444;
                        border-radius: 9px;
                        color: #EF4444;
                        font-size: 9px;
                        font-weight: 800;
                        padding: 1px 6px;
                    """)
                    badge.setToolTip("Не удалось скачать аудиофайл")

        # 2. Обновление панели ACTIVE DOWNLOADS справа
        if hasattr(self, "stream_widgets"):
            if not active_downloads:
                if hasattr(self, "stream_empty_lbl"):
                    self.stream_empty_lbl.setVisible(True)
                    self.stream_empty_lbl.setText(
                        "Нет активных загрузок"
                        if not self.download_thread
                        else "Ожидание потоков..."
                    )
                for item in self.stream_widgets:
                    item[0].setVisible(False)
            else:
                if hasattr(self, "stream_empty_lbl"):
                    self.stream_empty_lbl.setVisible(False)
                for idx, (container, s_lbl, s_spd, s_pbar) in enumerate(self.stream_widgets):
                    if idx < len(active_downloads):
                        dl = active_downloads[idx]
                        container.setVisible(True)
                        fname = dl.get("filename", "")
                        disp_name = (fname[:20] + "…") if len(fname) > 22 else fname
                        s_lbl.setText(disp_name)
                        s_lbl.setToolTip(fname)
                        s_spd.setText(f"{dl.get('speed', 0.0):.1f} MB/s")
                        s_pbar.setValue(int(dl.get("percent", 0)))
                    else:
                        container.setVisible(False)

        # 3. Обновление MULTI-THREAD STATUS и SPEED METERS
        total_speed = sum(dl.get("speed", 0.0) for dl in active_downloads)
        active_cnt = len(active_downloads)
        max_th = self.threads_spin.value()
        if hasattr(self, "thread_val"):
            self.thread_val.setText(f"{active_cnt}/{max_th}" if active_cnt > 0 else "IDLE")
        if hasattr(self, "thread_bar"):
            self.thread_bar.setValue(int(active_cnt / max(1, max_th) * 100))

        if hasattr(self, "spd_current"):
            self.spd_current.setText(f"Current:   {total_speed:.1f} MB/s")
        if hasattr(self, "speed_meter"):
            self.speed_meter.add_speed_point(total_speed)
        if hasattr(self, "spd_total"):
            self.spd_total.setText(f"Total DL:  {downloaded} треков")

        # 4. Обновление STORAGE STATS
        if hasattr(self, "_update_storage_stats"):
            self._update_storage_stats()

    def download_finished(self):
        sender = self.sender() if hasattr(self, "sender") else None
        curr_th = getattr(self, "download_thread", None)
        if sender is not None and curr_th is not None and sender is not curr_th:
            return

        self.log("Загрузка завершена.")
        # Финальный проход: треки, оставшиеся в QUEUED/DOWNLOADING, реально не
        # были сохранены (успешным проставляется SAVED по ходу выполнения).
        # Раньше такие треки навсегда залипали в оранжевом состоянии.
        if hasattr(self, "_track_status_badges"):
            stale = 0
            for badge in self._track_status_badges.values():
                if badge.text().startswith(("QUEUED", "DOWNLOADING")):
                    badge.setText("FAILED")
                    badge.setStyleSheet("""
                        background-color: #2B0E14;
                        border: 1px solid #EF4444;
                        border-radius: 9px;
                        color: #EF4444;
                        font-size: 9px;
                        font-weight: 800;
                        padding: 1px 6px;
                    """)
                    badge.setToolTip("Файл не был сохранен")
                    stale += 1
            if stale:
                self.log(f"Не сохранено треков: {stale}")
        if hasattr(self, "show_tray_notification"):
            self.show_tray_notification("BEATSTORM DJ Pool", "Загрузка аудио треков завершена!")
        self.scan_button.setEnabled(True)
        self.download_button.setEnabled(bool(self._scan_results))
        self.track_list.setEnabled(True)
        self.stop_button.setEnabled(False)
        if hasattr(self, "bento_btn_scan"):
            self.bento_btn_scan.setEnabled(True)
        if hasattr(self, "bento_btn_download"):
            self.bento_btn_download.setEnabled(bool(self._scan_results))
        if hasattr(self, "bento_btn_stop"):
            self.bento_btn_stop.setEnabled(False)
        self.download_thread = None
        if hasattr(self, "status_badge"):
            self.status_badge.setText("● COMPLETED")
            self.status_badge.setStyleSheet(
                "background-color: #10241A; border: 1px solid #1A5432; border-radius: 12px; padding: 4px 12px; font-size: 11px; font-weight: 700; color: #00E676;"
            )
        if self.qr_dialog:
            self.qr_dialog.blockSignals(True)
            self.qr_dialog.close()
            self.qr_dialog = None

        if hasattr(self, "_refresh_table_statuses"):
            self._refresh_table_statuses()
        if hasattr(self, "stream_empty_lbl"):
            self.stream_empty_lbl.setVisible(True)
            self.stream_empty_lbl.setText("Все загрузки завершены")
        if hasattr(self, "stream_widgets"):
            for item in self.stream_widgets:
                item[0].setVisible(False)
        if hasattr(self, "speed_meter"):
            self.speed_meter.set_idle()
        if hasattr(self, "spd_current"):
            self.spd_current.setText("Current:   0.0 MB/s")
        if hasattr(self, "thread_val"):
            self.thread_val.setText("IDLE")
        if hasattr(self, "thread_bar"):
            self.thread_bar.setValue(0)
