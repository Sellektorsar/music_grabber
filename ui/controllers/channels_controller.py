"""
Channels & Navigation Controller Mixin for MainWindow (BEATSTORM DJ Pool).

Encapsulates:
- Saved channels management (load, save, populate, context menu, add, remove);
- Tab and view switching (Home, Channels, Library);
- Settings loading, saving, and auto-saving;
- Date presets and proxy button styling.
"""

import os
import shutil
import logging
from datetime import datetime, timedelta
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QListWidgetItem,
    QTableWidgetItem,
    QMenu,
    QMessageBox,
)

from config import BASE_PATH, DEFAULT_CONFIG, load_config, save_config
import database as db_module
from ui.theme import DARK_STYLESHEET
from ui.dialogs import InputCodeDialog

logger = logging.getLogger(__name__)

DEFAULT_CHANNELS = [
    "@TechHouseDaily",
    "@Underground_Minimal",
    "@HouseVibes",
    "@BassMassive",
    "@TechnoPulse",
    "@kutsuevpool",
]


def _channels_file() -> str:
    """Путь к списку каналов.

    Берётся от BASE_PATH, а не от текущего рабочего каталога: при запуске
    из ярлыка рабочим каталогом оказывается System32, и список каналов
    молча сбрасывался бы на значения по умолчанию, а правки сохранялись
    в посторонней папке.
    """
    return os.path.join(BASE_PATH, "channels.json")


def load_saved_channels() -> list[str]:
    import json
    ch_file = _channels_file()
    if os.path.exists(ch_file):
        try:
            with open(ch_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return data
        except Exception as e:
            logger.debug(f"Ошибка чтения channels.json: {e}")
    return list(DEFAULT_CHANNELS)


def save_saved_channels(channels: list[str]) -> None:
    import json
    ch_file = _channels_file()
    try:
        os.makedirs(BASE_PATH, exist_ok=True)
        with open(ch_file, "w", encoding="utf-8") as f:
            json.dump(channels, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug(f"Ошибка записи channels.json: {e}")


class ChannelsMixin:
    """Управление каналами, навигацией по вкладкам и настройками приложения."""

    def switch_tab(self, tab_name: str):
        """Переключает активную вкладку между Home, Channels и Library."""
        self._current_tab = tab_name
        self.tab_home.setObjectName("navTabActive" if tab_name == "home" else "navTab")
        self.tab_channels.setObjectName("navTabActive" if tab_name == "channels" else "navTab")
        self.tab_library.setObjectName("navTabActive" if tab_name == "library" else "navTab")

        for btn in (self.tab_home, self.tab_channels, self.tab_library):
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if tab_name == "home":
            self._refresh_home_view()
            self.main_stack.setCurrentWidget(self.home_view)
        elif tab_name == "library":
            self.main_stack.setCurrentWidget(self.body_widget)
        elif tab_name == "channels":
            self._refresh_channels_view()
            self.main_stack.setCurrentWidget(self.channels_view)

    def _init_saved_channels(self):
        """Загружает сохраненные каналы из channels.json или дефолтных значений."""
        self._saved_channels = load_saved_channels()
        self._populate_saved_channels()

    def _populate_saved_channels(self):
        """Заполняет виджет списка каналов с кнопками удаления."""
        self.saved_channels_list.clear()
        colors = ["#00D2BE", "#E040FB", "#FFB300", "#7C4DFF", "#00E5FF", "#38BDF8"]
        icons = ["✈", "〰", "🏠", "💿", "⚡", "🎵"]

        if hasattr(self, "btn_all_channels"):
            cnt = len(self._saved_channels) if hasattr(self, "_saved_channels") else 0
            self.btn_all_channels.setText(f"🌟 Все каналы ({cnt})")

        for idx, chan_name in enumerate(self._saved_channels):
            item = QListWidgetItem()
            item.setSizeHint(QSize(190, 26))
            item.setData(Qt.ItemDataRole.UserRole, chan_name)

            item_widget = QWidget()
            i_layout = QHBoxLayout(item_widget)
            i_layout.setContentsMargins(2, 1, 2, 1)
            i_layout.setSpacing(6)

            ico_color = colors[idx % len(colors)]
            ico_sym = icons[idx % len(icons)]

            ico_lbl = QLabel(ico_sym)
            ico_lbl.setFixedSize(18, 18)
            ico_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ico_lbl.setStyleSheet(f"""
                background-color: {ico_color};
                color: #06090E;
                font-size: 10px;
                font-weight: bold;
                border-radius: 9px;
            """)

            name_lbl = QLabel(chan_name)
            name_lbl.setStyleSheet("color: #CBD5E1; font-size: 11px; font-weight: 600;")
            name_lbl.setToolTip(f"Нажмите, чтобы выбрать канал {chan_name}")

            del_btn = QPushButton("✕")
            del_btn.setFixedSize(16, 16)
            del_btn.setToolTip(f"Удалить {chan_name} из сохраненных")
            del_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #475569;
                    border: none;
                    border-radius: 8px;
                    font-size: 9px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #EF4444;
                    color: #FFFFFF;
                }
            """)
            del_btn.clicked.connect(lambda _, c=chan_name: self._remove_saved_channel(c))

            i_layout.addWidget(ico_lbl)
            i_layout.addWidget(name_lbl)
            i_layout.addStretch()
            i_layout.addWidget(del_btn)

            self.saved_channels_list.addItem(item)
            self.saved_channels_list.setItemWidget(item, item_widget)

    def _show_channel_context_menu(self, pos):
        item = self.saved_channels_list.itemAt(pos)
        if not item:
            return
        chan_name = item.data(Qt.ItemDataRole.UserRole) or item.text()
        menu = QMenu(self)
        menu.setStyleSheet(DARK_STYLESHEET)
        act_select = menu.addAction(f"⚡ Выбрать {chan_name}")
        act_delete = menu.addAction(f"🗑 Удалить {chan_name}")
        action = menu.exec(self.saved_channels_list.mapToGlobal(pos))
        if action == act_select:
            self._on_saved_channel_clicked(item)
        elif action == act_delete:
            self._remove_saved_channel(chan_name)

    def _remove_saved_channel(self, chan_name: str):
        if not chan_name:
            return
        if hasattr(self, "_saved_channels") and chan_name in self._saved_channels:
            self._saved_channels.remove(chan_name)
            save_saved_channels(self._saved_channels)
            self._populate_saved_channels()
            self.log(f"Канал {chan_name} удален из сохраненных.")
            # Активный канал не должен оставаться ссылкой на удалённый канал:
            # иначе поле канала хранит несуществующее имя, статус в таблице
            # Channels у остальных каналов становится «В пуле», а интерфейс
            # расходится с config.json, который этот канал не меняет.
            if (
                hasattr(self, "channel_input")
                and self.channel_input.text().strip().lower() == str(chan_name).lower()
            ):
                self.channel_input.clear()
            if hasattr(self, "channels_view"):
                self._refresh_channels_view()

    def _remove_selected_channel(self):
        curr_item = self.saved_channels_list.currentItem()
        if not curr_item:
            return
        chan_name = curr_item.data(Qt.ItemDataRole.UserRole) or curr_item.text()
        self._remove_saved_channel(chan_name)

    def _prompt_add_channel(self):
        """Диалог быстрого добавления канала в список сохраненных."""
        dlg = InputCodeDialog("Введите ссылку или @username канала:", self)
        dlg.setWindowTitle("Добавить канал")

        def _on_add(text):
            text = text.strip()
            if text:
                if not text.startswith("@") and not text.startswith("http"):
                    text = f"@{text}"
                if not hasattr(self, "_saved_channels"):
                    self._saved_channels = []
                if text not in self._saved_channels:
                    self._saved_channels.append(text)
                    save_saved_channels(self._saved_channels)
                    self._populate_saved_channels()
                self.channel_input.setText(text)
                self.log(f"Канал {text} добавлен в сохраненные.")
                if hasattr(self, "channels_view"):
                    self._refresh_channels_view()

        dlg.code_entered.connect(_on_add)
        dlg.exec()

    def _filter_tree_by_channel(self, channel_name):
        """Фильтрует дерево треков по выбранному каналу или сбрасывает фильтр (None)."""
        self._selected_channel_filter = channel_name if (channel_name and channel_name != "__ALL__") else None
        current_text = ""
        if hasattr(self, "search_filter_input"):
            current_text = self.search_filter_input.text()
        elif hasattr(self, "top_search_input"):
            current_text = self.top_search_input.text()
        self._filter_tracks_text(current_text)

    def _select_all_channels_view(self):
        """Сброс фильтра по каналу и отображение всех сохраненных каналов."""
        if hasattr(self, "saved_channels_list"):
            self.saved_channels_list.clearSelection()
        self._filter_tree_by_channel(None)
        saved = getattr(self, "_saved_channels", [])
        self.log(f"Отображаются все каналы ({len(saved)})")

    def _on_saved_channel_clicked(self, item):
        """Выбор канала из левого сайдбара."""
        data_name = item.data(Qt.ItemDataRole.UserRole)
        if data_name == "__ALL__":
            self.channel_input.clear()
            self._filter_tree_by_channel(None)
            self.log(f"Отображаются все каналы ({len(self._saved_channels)})")
            return
        if data_name:
            chan_str = str(data_name)
            self.channel_input.setText(chan_str)
            self._filter_tree_by_channel(chan_str)
            self.log(f"Фильтр по каналу: {chan_str}")
        else:
            txt = item.text().split()[1] if len(item.text().split()) > 1 else item.text()
            chan_str = txt.strip()
            self.channel_input.setText(chan_str)
            self._filter_tree_by_channel(chan_str)

    def _create_home_view(self) -> QWidget:
        """Создает экран Home Dashboard с ключевыми метриками и быстрыми действиями."""
        from ui.views import create_home_view
        return create_home_view(self)

    def _create_channels_view(self) -> QWidget:
        """Создает экран Channels Manager для удобного управления сохраненными каналами."""
        from ui.views import create_channels_view
        return create_channels_view(self)

    def _add_channel_from_manager(self):
        text = self.chan_view_input.text().strip()
        if not text:
            return
        if not text.startswith("@") and not text.startswith("http"):
            text = f"@{text}"
        if not hasattr(self, "_saved_channels"):
            self._saved_channels = []
        if text not in self._saved_channels:
            self._saved_channels.append(text)
            save_saved_channels(self._saved_channels)
            self._populate_saved_channels()
            self._refresh_channels_view()
            self.channel_input.setText(text)
            self.chan_view_input.clear()
            self.log(f"Канал {text} успешно добавлен в сохраненные.")

    def _refresh_home_view(self):
        """Обновляет статистику на экране Home Dashboard."""
        if hasattr(self, "home_tracks_val"):
            try:
                cnt = db_module.get_download_count()
                self.home_tracks_val.setText(f"{cnt} треков")
            except Exception as e:
                logger.debug(f"Ошибка подсчета треков: {e}")
                self.home_tracks_val.setText("0 треков")

        if hasattr(self, "home_chan_val"):
            cur = self.channel_input.text().strip()
            self.home_chan_val.setText(cur if cur else "Не выбран")

        if hasattr(self, "home_disk_val"):
            try:
                # Тот же BASE_PATH, что и в _update_storage_stats: относительный
                # путь разрешался бы от рабочего каталога процесса.
                total, used, free = shutil.disk_usage(BASE_PATH)
                free_gb = free / (1024 ** 3)
                self.home_disk_val.setText(f"{free_gb:.1f} GB свободно")
            except Exception as e:
                logger.debug(f"Ошибка получения инфо о диске: {e}")
                self.home_disk_val.setText("— GB")

        if hasattr(self, "home_recent_table"):
            try:
                if getattr(self, "_scan_results", None):
                    records = self._scan_results[:100]
                else:
                    records = db_module.get_downloads(limit=25)
                self.home_recent_table.blockSignals(True)
                self.home_recent_table.setRowCount(len(records))
                for row_idx, r in enumerate(records):
                    tit = r.get("title") or r.get("raw_title") or "—"
                    perf = r.get("performer") or r.get("raw_performer") or r.get("artist") or "—"
                    chan = r.get("channel") or r.get("channel_id") or "—"
                    fpath = r.get("filepath") or r.get("file_path") or ""
                    fname = r.get("filename") or (os.path.basename(fpath) if fpath else "—")

                    t_item = QTableWidgetItem(tit)
                    t_item.setData(Qt.ItemDataRole.UserRole, r)
                    mid = r.get("id") or r.get("message_id")
                    if mid and hasattr(self, "_track_list_item_by_id"):
                        l_item = self._track_list_item_by_id.get(mid)
                        if l_item:
                            t_item.setCheckState(l_item.checkState())
                        else:
                            t_item.setCheckState(Qt.CheckState.Unchecked)
                    elif mid:
                        t_item.setCheckState(Qt.CheckState.Unchecked)

                    a_item = QTableWidgetItem(perf)
                    c_item = QTableWidgetItem(chan)
                    f_item = QTableWidgetItem(fname)
                    for it in (t_item, a_item, c_item, f_item):
                        it.setForeground(QColor("#CBD5E1"))
                    self.home_recent_table.setItem(row_idx, 0, t_item)
                    self.home_recent_table.setItem(row_idx, 1, a_item)
                    self.home_recent_table.setItem(row_idx, 2, c_item)
                    self.home_recent_table.setItem(row_idx, 3, f_item)
                self.home_recent_table.blockSignals(False)
            except Exception as e:
                logger.debug(f"Ошибка загрузки недавних треков: {e}")

        if hasattr(self, "home_dup_val") or hasattr(self, "home_hq_val"):
            try:
                all_recs = db_module.get_downloads(limit=100)
                if hasattr(self, "home_dup_val"):
                    dups = sum(1 for r in all_recs if r.get("status") == "duplicate" or r.get("is_duplicate"))
                    self.home_dup_val.setText(f"{dups} DUP")
                if hasattr(self, "home_hq_val"):
                    hq_cnt = 0
                    for r in all_recs:
                        dur = r.get("duration") or 0
                        sz = r.get("file_size") or 0
                        if dur > 0 and (sz * 8 / dur) >= 280000:
                            hq_cnt += 1
                        elif "320" in (r.get("filename") or "") or "320" in (r.get("title") or ""):
                            hq_cnt += 1
                    self.home_hq_val.setText(f"{hq_cnt} HQ")
            except Exception as e:
                logger.debug(f"Ошибка обновления DUP/HQ в Bento: {e}")

    def _refresh_channels_view(self):
        """Обновляет таблицу сохраненных каналов на вкладке Channels."""
        if not hasattr(self, "channels_mgr_table") or not hasattr(self, "_saved_channels"):
            return
        self.channels_mgr_table.setRowCount(len(self._saved_channels))
        cur_chan = self.channel_input.text().strip()

        for row_idx, chan in enumerate(self._saved_channels):
            ico_item = QTableWidgetItem("✈")
            ico_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            ico_item.setForeground(QColor("#00D2BE"))
            self.channels_mgr_table.setItem(row_idx, 0, ico_item)

            c_item = QTableWidgetItem(chan)
            c_item.setForeground(QColor("#FFFFFF"))
            c_item.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            self.channels_mgr_table.setItem(row_idx, 1, c_item)

            is_active = (chan.lower() == cur_chan.lower())
            st_text = "● АКТИВНЫЙ" if is_active else "В пуле"
            st_item = QTableWidgetItem(st_text)
            st_item.setForeground(QColor("#00E5FF" if is_active else "#64748B"))
            self.channels_mgr_table.setItem(row_idx, 2, st_item)

            act_widget = QWidget()
            act_layout = QHBoxLayout(act_widget)
            act_layout.setContentsMargins(4, 2, 4, 2)
            act_layout.setSpacing(6)

            btn_select = QPushButton("🎵 В библиотеку")
            btn_select.setObjectName("chipButton")
            btn_select.setFixedHeight(24)
            btn_select.clicked.connect(lambda _, c=chan: self._select_channel_and_open_library(c))

            btn_scan = QPushButton("⚡ Сканировать")
            btn_scan.setObjectName("primaryButton")
            btn_scan.setFixedHeight(24)
            btn_scan.clicked.connect(lambda _, c=chan: self._scan_channel_from_manager(c))

            btn_del = QPushButton("🗑 Удалить")
            btn_del.setObjectName("stopButton")
            btn_del.setFixedHeight(24)
            btn_del.clicked.connect(lambda _, c=chan: self._confirm_delete_channel(c))

            act_layout.addWidget(btn_select)
            act_layout.addWidget(btn_scan)
            act_layout.addWidget(btn_del)
            act_layout.addStretch()

            self.channels_mgr_table.setCellWidget(row_idx, 3, act_widget)

    def _select_channel_and_open_library(self, chan: str):
        self.channel_input.setText(chan)
        self.switch_tab("library")

    def _scan_channel_from_manager(self, chan: str):
        self.channel_input.setText(chan)
        self.switch_tab("library")
        self.start_scan()

    def _confirm_delete_channel(self, chan: str):
        reply = QMessageBox.question(
            self,
            "Удаление канала",
            f"Вы уверены, что хотите удалить канал {chan} из сохраненных?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._remove_saved_channel(chan)

    def _on_recent_table_item_clicked(self, item):
        """Отображение выбранного трека в TrackInspectorCard."""
        row = item.row()
        t_item = self.home_recent_table.item(row, 0)
        if not t_item:
            return
        track_data = t_item.data(Qt.ItemDataRole.UserRole)
        if isinstance(track_data, dict) and hasattr(self, "track_inspector") and self.track_inspector:
            self.track_inspector.display_track(track_data)
        elif isinstance(track_data, str) and hasattr(self, "track_inspector") and self.track_inspector:
            self.track_inspector.display_track({
                "title": t_item.text(),
                "filepath": track_data,
                "file_path": track_data,
            })

    def _on_recent_table_item_changed(self, item):
        """Синхронизирует выбор чекбокса из таблицы Bento Studio с деревом и списком треков."""
        if not item or item.column() != 0:
            return
        track_data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(track_data, dict):
            return
        mid = track_data.get("id") or track_data.get("message_id")
        if not mid:
            return
        state = item.checkState()
        if hasattr(self, "_track_list_item_by_id") and mid in self._track_list_item_by_id:
            l_item = self._track_list_item_by_id[mid]
            if l_item.checkState() != state:
                l_item.setCheckState(state)
        if hasattr(self, "_track_item_by_id") and mid in self._track_item_by_id:
            tr_item = self._track_item_by_id[mid]
            if tr_item.checkState(0) != state:
                tr_item.setCheckState(0, state)
        if hasattr(self, "_update_download_button_counter"):
            self._update_download_button_counter()

    def _load_settings(self):
        cfg = load_config()
        if cfg.get("api_id"):
            # Приведение к строке обязательно: в config.json поле могло
            # оказаться числом (правка руками, перенос из другого конфига),
            # и QLineEdit.setText на числе падал с TypeError прямо в
            # конструкторе -- приложение не запускалось вовсе.
            self.api_id_input.setText(str(cfg["api_id"]))
        if cfg.get("api_hash"):
            self.api_hash_input.setText(str(cfg["api_hash"]))
        if cfg.get("channel"):
            self.channel_input.setText(str(cfg["channel"]))
        mode = cfg.get("mode", "direct")
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        if cfg.get("date_from"):
            self.date_from_input.setText(cfg["date_from"])
        if cfg.get("date_to"):
            self.date_to_input.setText(cfg["date_to"])

        if cfg.get("max_concurrent_downloads"):
            try:
                self.threads_spin.blockSignals(True)
                self.threads_spin.setValue(int(cfg["max_concurrent_downloads"]))
            except (ValueError, TypeError):
                pass
            finally:
                self.threads_spin.blockSignals(False)
        if cfg.get("mp3_bitrate"):
            idx_b = self.bitrate_combo.findText(cfg["mp3_bitrate"])
            if idx_b >= 0:
                self.bitrate_combo.blockSignals(True)
                self.bitrate_combo.setCurrentIndex(idx_b)
                self.bitrate_combo.blockSignals(False)

        if hasattr(self, "export_pattern_input"):
            self.export_pattern_input.setText(cfg.get("export_pattern", "{channel}/{artist} - {title}.mp3"))
        if hasattr(self, "auto_m3u8_check"):
            self.auto_m3u8_check.setChecked(bool(cfg.get("auto_generate_m3u8", False)))
        if hasattr(self, "embed_id3_check"):
            self.embed_id3_check.setChecked(
            bool(cfg.get("embed_id3_tags", DEFAULT_CONFIG["embed_id3_tags"])))
        if hasattr(self, "watcher_interval_spin"):
            self.watcher_interval_spin.setValue(int(cfg.get("auto_watcher_interval_minutes", 15)))

        # Загрузка прокси с поддержкой словаря 'proxy' и плоских ключей 'proxy_*'
        p_dict = cfg.get("proxy")
        if isinstance(p_dict, dict) and p_dict and ("enabled" in p_dict or "host" in p_dict):
            self._proxy_config = {
                "enabled": bool(p_dict.get("enabled", False)),
                "type": p_dict.get("type", "socks5"),
                "host": p_dict.get("host", "127.0.0.1"),
                "port": str(p_dict.get("port", 10808)),
                "username": p_dict.get("username", ""),
                "password": p_dict.get("password", ""),
            }
        else:
            self._proxy_config = {
                "enabled": bool(cfg.get("proxy_enabled", False)),
                "type": cfg.get("proxy_type", "socks5"),
                "host": cfg.get("proxy_host", "127.0.0.1"),
                "port": str(cfg.get("proxy_port", 10808)),
                "username": cfg.get("proxy_username", ""),
                "password": cfg.get("proxy_password", ""),
            }
        self._update_proxy_button_label()

    def _get_proxy_config(self):
        """Возвращает текущую конфигурацию прокси."""
        return getattr(self, "_proxy_config", None)

    def _update_proxy_button_label(self):
        if not hasattr(self, "proxy_button"):
            return
        p_cfg = getattr(self, "_proxy_config", {}) or {}
        if p_cfg.get("enabled"):
            ptype = str(p_cfg.get("type", "socks5")).upper()
            host = p_cfg.get("host", "127.0.0.1")
            port = p_cfg.get("port", "10808")
            self.proxy_button.setText(f"🟢 Прокси: {ptype} ({host}:{port})")
            self.proxy_button.setStyleSheet("color: #10B981; font-weight: bold;")
            self.proxy_button.setToolTip(f"Прокси включен: {ptype} {host}:{port}. Нажмите для изменения настроек.")
        else:
            self.proxy_button.setText("⚙️ Прокси: Выключен (настроить...)")
            self.proxy_button.setStyleSheet("")
            self.proxy_button.setToolTip("Прокси выключен. Если прямое подключение к Telegram блокируется, включите SOCKS5 или MTProto прокси.")

    def _save_settings(self):
        p_cfg = getattr(self, "_proxy_config", {}) or {}
        cfg = {
            "api_id": self.api_id_input.text().strip(),
            "api_hash": self.api_hash_input.text().strip(),
            "channel": self.channel_input.text().strip(),
            "mode": self.mode_combo.currentData(),
            "date_from": self.date_from_input.text().strip(),
            "date_to": self.date_to_input.text().strip(),
            "max_concurrent_downloads": self.threads_spin.value(),
            "mp3_bitrate": self.bitrate_combo.currentText(),
            "proxy": p_cfg,
            "proxy_enabled": bool(p_cfg.get("enabled", False)),
            "proxy_type": p_cfg.get("type", "socks5"),
            "proxy_host": p_cfg.get("host", "127.0.0.1"),
            "proxy_port": int(p_cfg.get("port", 10808)) if str(p_cfg.get("port", "")).isdigit() else 10808,
            "proxy_username": p_cfg.get("username", ""),
            "proxy_password": p_cfg.get("password", ""),
        }
        if hasattr(self, "export_pattern_input"):
            cfg["export_pattern"] = self.export_pattern_input.text().strip()
        if hasattr(self, "auto_m3u8_check"):
            cfg["auto_generate_m3u8"] = self.auto_m3u8_check.isChecked()
        if hasattr(self, "embed_id3_check"):
            cfg["embed_id3_tags"] = self.embed_id3_check.isChecked()
        if hasattr(self, "watcher_interval_spin"):
            cfg["auto_watcher_interval_minutes"] = self.watcher_interval_spin.value()
        save_config(**cfg)

    def _toggle_api_settings(self):
        self._api_settings_open = not self._api_settings_open
        self.api_group.setVisible(self._api_settings_open)
        self.toggle_api_btn.setText(
            "⚙️ Скрыть настройки API"
            if self._api_settings_open
            else "⚙️ Настройки Telegram API"
        )

    def _preset_dates_all(self):
        self.date_from_input.clear()
        self.date_to_input.clear()

    def _preset_dates_30d(self):
        now = datetime.now()
        thirty_days_ago = now - timedelta(days=30)
        self.date_to_input.setText(now.strftime("%Y-%m-%d"))
        self.date_from_input.setText(thirty_days_ago.strftime("%Y-%m-%d"))

    def _toggle_log(self):
        self._log_open = not getattr(self, "_log_open", True)
        self.log_output.setVisible(self._log_open)
        self.btn_toggle_log.setText("🎛 Скрыть лог" if self._log_open else "🎛 Монитор консоли")

    def _save_settings_with_feedback(self):
        self._save_settings()
        if hasattr(self, "save_feedback_lbl"):
            self.save_feedback_lbl.setText("✓ Настройки сохранены")
            QTimer.singleShot(2500, lambda: self.save_feedback_lbl.setText(""))
        self.log(
            f"Настройки сохранены: Качество={self.bitrate_combo.currentText()}, "
            f"Потоков={self.threads_spin.value()}"
        )

    def _on_setting_changed(self, *args):
        self._save_settings()
        if hasattr(self, "save_feedback_lbl"):
            self.save_feedback_lbl.setText("✓ Автосохранено")
            QTimer.singleShot(2000, lambda: self.save_feedback_lbl.setText(""))
        # Сообщение не упоминает качество и потоки: сигнал приходит и от
        # полей канала и дат, и от кнопок пресетов, и называть там «Качество»
        # было бы прямой неправдой.
        self.log("Настройка обновлена и сохранена.")

    def _update_storage_stats(self):
        try:
            # Путь берётся от BASE_PATH, а не от текущего рабочего каталога:
            # при запуске из ярлыка с чужим «рабочим каталогом» относительный
            # путь создавал лишнюю папку telegram_audio и считал свободное
            # место не на том диске. Тот же класс, что был DEFECT-013.
            target_dir = os.path.join(BASE_PATH)
            os.makedirs(target_dir, exist_ok=True)
            total_b, used_b, free_b = shutil.disk_usage(target_dir)
            free_gb = free_b / (1024 ** 3)
            pct_used = int(used_b / max(1, total_b) * 100)
            drive = os.path.splitdrive(target_dir)[0] or "C:"
            if hasattr(self, "storage_usage_lbl"):
                self.storage_usage_lbl.setText(f"{pct_used}% full")
            if hasattr(self, "storage_bar"):
                self.storage_bar.setValue(pct_used)
            if hasattr(self, "storage_info_lbl"):
                self.storage_info_lbl.setText(f"{free_gb:.1f} GB доступно\nна {drive}")
        except Exception as e:
            logger.debug(f"Ошибка получения данных диска: {e}")
