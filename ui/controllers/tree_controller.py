"""
Tree Controller Mixin for MainWindow (BEATSTORM DJ Pool Library).

Encapsulates:
- Hierarchical QTreeWidget rendering (Date -> Channel -> Tracks);
- Fast batch appending of new tracks with update freeze;
- Waveform and status badge generation and cached placeholder assignment;
- Batch selection actions (all, none, only new);
- Search text filtering and channel filtering;
- Tree item interaction (double click preview, checkbox propagation, prefetch scroll).
"""

import os
from collections import Counter
from datetime import datetime, timedelta
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QBrush
from PyQt6.QtWidgets import (
    QTreeWidgetItem,
    QListWidgetItem,
    QLabel,
    QMenu,
    QFileDialog,
)

import database as db_module
from media_utils import (
    generate_m3u8_playlist,
    extract_key_meta,
    get_camelot_color,
    read_audio_id3_meta,
)
from ui.widgets import (
    extract_bpm_meta,
    create_waveform_pixmap,
    get_cached_waveform_placeholder,
)


class TreeControllerMixin:
    """Управление деревом библиотеки треков, вейвформами и фильтрацией."""

    def _create_single_track_item(self, chan_item, t, ch_key, init_check_state=None):
        """Создает и настраивает один QTreeWidgetItem трека с бейджем и кэшированным вейвформом."""
        msg_id = t["id"]
        self._track_by_id[msg_id] = t

        track_item = QTreeWidgetItem(chan_item)
        track_item.setFlags(
            track_item.flags()
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEnabled
        )

        if init_check_state is None:
            init_check_state = (
                Qt.CheckState.Checked
                if not t.get("already_exists")
                else Qt.CheckState.Unchecked
            )
        track_item.setCheckState(0, init_check_state)
        track_item.setData(0, Qt.ItemDataRole.UserRole, msg_id)
        track_item.setData(1, Qt.ItemDataRole.UserRole, t)

        # TITLE & ARTIST
        raw_title = t.get("title", "Unknown Track")
        raw_perf = t.get("performer", "Unknown Artist")
        from media_utils import clean_track_metadata
        clean_perf, clean_tit = clean_track_metadata(raw_perf, raw_title)
        disp_title = clean_tit if clean_tit != "UnknownTitle" else raw_title
        disp_perf = clean_perf if clean_perf != "UnknownArtist" else raw_perf

        track_item.setText(1, disp_title)
        track_item.setFont(1, QFont("Segoe UI", 9, QFont.Weight.Bold))
        track_item.setForeground(1, QBrush(QColor("#FFFFFF")))

        track_item.setText(2, disp_perf)
        track_item.setForeground(2, QBrush(QColor("#CBD5E1")))

        # BPM & KEY
        bpm_val = t.get("bpm") or extract_bpm_meta(t.get("title", ""), t.get("performer", ""))
        key_val = t.get("key") or extract_key_meta(t.get("title", ""), t.get("performer", ""))

        if (bpm_val == "—" or key_val == "—" or not bpm_val or not key_val) and (t.get("already_exists") or t.get("filepath") or t.get("file_path")):
            fp = t.get("filepath") or t.get("file_path")
            if fp and os.path.exists(fp):
                f_bpm, f_key = read_audio_id3_meta(fp)
                if (bpm_val == "—" or not bpm_val) and f_bpm != "—":
                    bpm_val = f_bpm
                    t["bpm"] = f_bpm
                if (key_val == "—" or not key_val) and f_key != "—":
                    key_val = f_key
                    t["key"] = f_key

        if bpm_val != "—" and key_val != "—":
            disp_bpm_key = f"{bpm_val} • {key_val}"
            col_color = get_camelot_color(key_val)
        elif key_val != "—":
            disp_bpm_key = key_val
            col_color = get_camelot_color(key_val)
        else:
            disp_bpm_key = bpm_val
            col_color = "#FFFFFF" if bpm_val != "—" else "#64748B"

        track_item.setText(3, disp_bpm_key)
        track_item.setTextAlignment(3, Qt.AlignmentFlag.AlignCenter)
        track_item.setForeground(3, QBrush(QColor(col_color)))
        if key_val != "—":
            track_item.setFont(3, QFont("Segoe UI", 9, QFont.Weight.Bold))
        track_item.setToolTip(
            3,
            f"BPM: {bpm_val} | Тональность: {key_val} (Camelot Wheel)"
            if (bpm_val != "—" or key_val != "—")
            else "BPM и тональность не указаны",
        )

        # DUR.
        dur_secs = t.get("duration", 0) or 0
        dur_str = f"{dur_secs // 60:02d}:{dur_secs % 60:02d}" if dur_secs else "—"
        track_item.setText(4, dur_str)
        track_item.setTextAlignment(4, Qt.AlignmentFlag.AlignCenter)
        track_item.setForeground(4, QBrush(QColor("#94A3B8")))

        # CHANNEL
        track_item.setText(5, ch_key)
        track_item.setTextAlignment(5, Qt.AlignmentFlag.AlignCenter)
        track_item.setForeground(5, QBrush(QColor("#64748B")))

        # STATUS Badge
        status_lbl = QLabel()
        status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if t.get("is_duplicate"):
            status_lbl.setText("DUP")
            status_lbl.setStyleSheet("""
                background-color: #2D1537;
                border: 1px solid #9B51E0;
                border-radius: 9px;
                color: #D6A4FF;
                font-size: 9px;
                font-weight: 800;
                padding: 1px 6px;
            """)
            dup_ch = t.get("duplicate_channel") or "другом канале"
            status_lbl.setToolTip(f"Дубликат трека, уже скачанного из @{dup_ch}")
            wf_pix = create_waveform_pixmap(150, 22, "#9B51E0", seed=msg_id)
            wf_tip = f"Дубликат из @{dup_ch}"
        elif t.get("already_exists"):
            status_lbl.setText("SAVED")
            status_lbl.setStyleSheet("""
                background-color: #0E2B18;
                border: 1px solid #2ECC71;
                border-radius: 9px;
                color: #2ECC71;
                font-size: 9px;
                font-weight: 800;
                padding: 1px 6px;
            """)
            status_lbl.setToolTip("Файл уже сохранен на диске")
            wf_pix = create_waveform_pixmap(150, 22, "#2ECC71", seed=msg_id)
            wf_tip = "Файл сохранен на диске"
        else:
            status_lbl.setText("READY")
            status_lbl.setStyleSheet("""
                background-color: #0D1B2A;
                border: 1px solid #1E3A5F;
                border-radius: 9px;
                color: #38BDF8;
                font-size: 9px;
                font-weight: 800;
                padding: 1px 6px;
            """)
            status_lbl.setToolTip("Трек обнаружен в Telegram и готов к загрузке")
            wf_pix = get_cached_waveform_placeholder(150, 22)
            wf_tip = "Волна рассчитывается после скачивания аудиофайла"

        self.library_tree.setItemWidget(track_item, 6, status_lbl)
        self._track_status_badges[msg_id] = status_lbl

        # WAVEFORM
        wf_lbl = QLabel()
        wf_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wf_lbl.setPixmap(wf_pix)
        wf_lbl.setToolTip(wf_tip)
        self.library_tree.setItemWidget(track_item, 7, wf_lbl)
        self._track_waveforms[msg_id] = wf_lbl

        self._track_item_by_id[msg_id] = track_item
        return track_item

    def _render_tracks_in_tree(self, tracks, preserve_state=False):
        """Отображает треки в древовидной структуре с группировкой: Дата -> Канал -> Треки."""
        self._updating_tree = True
        if hasattr(self, "library_tree"):
            self.library_tree.setUpdatesEnabled(False)
        try:
            saved_checks = {}
            saved_expanded = {}
            if preserve_state:
                for mid, item in getattr(self, "_track_item_by_id", {}).items():
                    try:
                        saved_checks[mid] = item.checkState(0)
                    except Exception:
                        pass
                if hasattr(self, "library_tree"):
                    for i in range(self.library_tree.topLevelItemCount()):
                        top = self.library_tree.topLevelItem(i)
                        d_txt = top.text(0).split("   (")[0].strip()
                        saved_expanded[d_txt] = top.isExpanded()
                        for j in range(top.childCount()):
                            c_child = top.child(j)
                            c_txt = c_child.text(0).split("   (")[0].strip()
                            saved_expanded[(d_txt, c_txt)] = c_child.isExpanded()

            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtCore import QEvent

            for w in getattr(self, "_track_status_badges", {}).values():
                try:
                    w.setParent(None)
                    w.deleteLater()
                    QApplication.sendPostedEvents(w, QEvent.Type.DeferredDelete)
                except Exception:
                    pass
            for w in getattr(self, "_track_waveforms", {}).values():
                try:
                    w.setParent(None)
                    w.deleteLater()
                    QApplication.sendPostedEvents(w, QEvent.Type.DeferredDelete)
                except Exception:
                    pass
            self.library_tree.clear()

            self._track_status_badges = {}
            self._track_waveforms = {}
            self._track_item_by_id = {}
            self._track_row_by_id = {}
            self._track_by_id = {}
            self._track_list_item_by_id = {}
            self._date_tree_items = {}
            self._chan_tree_items = {}
            self._date_track_counts = Counter()
            self._chan_track_counts = Counter()

            today_str = datetime.now().strftime("%Y-%m-%d")
            yest_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

            grouped_by_date = {}
            for t in tracks:
                raw_d = str(t.get("date", ""))[:10]
                d_key = raw_d if len(raw_d) == 10 and raw_d[0].isdigit() else "Архив"
                ch_key = t.get("channel") or self.channel_input.text().strip() or "Общий канал"
                if d_key not in grouped_by_date:
                    grouped_by_date[d_key] = {}
                if ch_key not in grouped_by_date[d_key]:
                    grouped_by_date[d_key][ch_key] = []
                grouped_by_date[d_key][ch_key].append(t)

            def date_sort_key(d):
                if d == today_str:
                    return (3, d)
                elif d == yest_str:
                    return (2, d)
                elif d == "Архив":
                    return (0, "")
                else:
                    return (1, d)

            sorted_dates = sorted(grouped_by_date.keys(), key=date_sort_key, reverse=True)

            for d_key in sorted_dates:
                channels_map = grouped_by_date[d_key]
                total_date_tracks = sum(len(tr_list) for tr_list in channels_map.values())
                self._date_track_counts[d_key] = total_date_tracks

                if d_key == today_str:
                    d_header = f"📅 СЕГОДНЯ • {d_key}   ({total_date_tracks} треков)"
                elif d_key == yest_str:
                    d_header = f"📅 ВЧЕРА • {d_key}   ({total_date_tracks} треков)"
                elif d_key == "Архив":
                    d_header = f"📅 РАНЕЕ / АРХИВ   ({total_date_tracks} треков)"
                else:
                    d_header = f"📅 {d_key}   ({total_date_tracks} треков)"

                d_prefix = d_header.split("   (")[0].strip()
                date_item = QTreeWidgetItem(self.library_tree)
                date_item.setText(0, d_header)
                date_item.setFirstColumnSpanned(True)
                date_item.setFlags(date_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                date_item.setCheckState(0, Qt.CheckState.Checked)
                date_item.setBackground(0, QBrush(QColor("#0B132B")))
                date_item.setForeground(0, QBrush(QColor("#00E5FF")))
                date_item.setFont(0, QFont("Segoe UI", 10, QFont.Weight.Bold))
                date_item.setExpanded(saved_expanded.get(d_prefix, True) if preserve_state else True)
                date_item.setData(0, Qt.ItemDataRole.UserRole, d_key)
                self._date_tree_items[d_key] = date_item

                for ch_key, ch_tracks in channels_map.items():
                    self._chan_track_counts[(d_key, ch_key)] = len(ch_tracks)
                    chan_item = QTreeWidgetItem(date_item)
                    chan_header = f"  ✈ {ch_key}   ({len(ch_tracks)} треков)"
                    chan_item.setText(0, chan_header)
                    chan_item.setFirstColumnSpanned(True)
                    chan_item.setFlags(chan_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    chan_item.setCheckState(0, Qt.CheckState.Checked)
                    chan_item.setBackground(0, QBrush(QColor("#111C35")))
                    chan_item.setForeground(0, QBrush(QColor("#38BDF8")))
                    chan_item.setFont(0, QFont("Segoe UI", 9, QFont.Weight.Bold))
                    c_prefix = chan_header.split("   (")[0].strip()
                    chan_item.setExpanded(saved_expanded.get((d_prefix, c_prefix), True) if preserve_state else True)
                    chan_item.setData(0, Qt.ItemDataRole.UserRole, ch_key)
                    self._chan_tree_items[(d_key, ch_key)] = chan_item

                    ch_tracks.sort(key=lambda x: x.get("id", 0), reverse=True)

                    for t in ch_tracks:
                        msg_id = t["id"]
                        init_state = (
                            saved_checks[msg_id]
                            if msg_id in saved_checks
                            else None
                        )
                        self._create_single_track_item(chan_item, t, ch_key, init_state)

            self.track_list.clear()
            new_count = 0
            for idx, t in enumerate(tracks):
                msg_id = t["id"]
                self._track_row_by_id[msg_id] = idx

                size_str = ""
                if t.get("size"):
                    size_mb = t["size"] / (1024 * 1024)
                    size_str = f"  [{size_mb:.1f} MB]"
                label = f"{t.get('performer', '')} - {t.get('title', '')}  [{t.get('date', '')}]{size_str}"
                if t.get("already_exists"):
                    label += "  ✓ уже есть"
                else:
                    new_count += 1

                item = QListWidgetItem(label)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if not t.get("already_exists")
                    else Qt.CheckState.Unchecked
                )
                item.setData(Qt.ItemDataRole.UserRole, msg_id)
                self.track_list.addItem(item)
                self._track_list_item_by_id[msg_id] = item

            existing_count = len(tracks) - new_count
            if hasattr(self, "stats_label"):
                self.stats_label.setText(
                    f"Всего: {len(tracks)} • Новых: {new_count} • На диске: {existing_count}"
                )

        finally:
            if hasattr(self, "library_tree"):
                self.library_tree.setUpdatesEnabled(True)
            self._updating_tree = False

    def _append_tracks_to_tree(self, new_tracks):
        """Быстрое инкрементальное добавление новых треков без перерисовки всего дерева."""
        if not new_tracks:
            return

        self._updating_tree = True
        if hasattr(self, "library_tree"):
            self.library_tree.setUpdatesEnabled(False)
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            yest_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

            def date_sort_key(d):
                if d == today_str:
                    return (3, d)
                elif d == yest_str:
                    return (2, d)
                elif d == "Архив":
                    return (0, "")
                else:
                    return (1, d)

            if not hasattr(self, "_date_tree_items"):
                self._date_tree_items = {}
            if not hasattr(self, "_chan_tree_items"):
                self._chan_tree_items = {}
            if not hasattr(self, "_date_track_counts"):
                self._date_track_counts = Counter()
            if not hasattr(self, "_chan_track_counts"):
                self._chan_track_counts = Counter()

            grouped = {}
            for t in new_tracks:
                raw_d = str(t.get("date", ""))[:10]
                d_key = raw_d if len(raw_d) == 10 and raw_d[0].isdigit() else "Архив"
                ch_key = t.get("channel") or self.channel_input.text().strip() or "Общий канал"
                if d_key not in grouped:
                    grouped[d_key] = {}
                if ch_key not in grouped[d_key]:
                    grouped[d_key][ch_key] = []
                grouped[d_key][ch_key].append(t)

            for d_key, channels_map in grouped.items():
                date_item = self._date_tree_items.get(d_key)
                if date_item is None:
                    date_item = QTreeWidgetItem()
                    date_item.setFlags(date_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    date_item.setCheckState(0, Qt.CheckState.Checked)
                    date_item.setBackground(0, QBrush(QColor("#0B132B")))
                    date_item.setForeground(0, QBrush(QColor("#00E5FF")))
                    date_item.setFont(0, QFont("Segoe UI", 10, QFont.Weight.Bold))
                    date_item.setData(0, Qt.ItemDataRole.UserRole, d_key)

                    insert_idx = self.library_tree.topLevelItemCount()
                    target_key = date_sort_key(d_key)
                    for idx in range(self.library_tree.topLevelItemCount()):
                        existing_top = self.library_tree.topLevelItem(idx)
                        existing_d_key = existing_top.data(0, Qt.ItemDataRole.UserRole)
                        if not existing_d_key:
                            raw_t = existing_top.text(0).split(" • ")[-1].split("   (")[0].strip()
                            existing_d_key = raw_t.replace("📅", "").strip()
                        if target_key > date_sort_key(existing_d_key):
                            insert_idx = idx
                            break
                    self.library_tree.insertTopLevelItem(insert_idx, date_item)
                    date_item.setFirstColumnSpanned(True)
                    date_item.setExpanded(True)
                    self._date_tree_items[d_key] = date_item

                for ch_key, ch_tracks in channels_map.items():
                    chan_item = self._chan_tree_items.get((d_key, ch_key))
                    if chan_item is None:
                        chan_item = QTreeWidgetItem(date_item)
                        chan_item.setFirstColumnSpanned(True)
                        chan_item.setFlags(chan_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        chan_item.setCheckState(0, Qt.CheckState.Checked)
                        chan_item.setBackground(0, QBrush(QColor("#111C35")))
                        chan_item.setForeground(0, QBrush(QColor("#38BDF8")))
                        chan_item.setFont(0, QFont("Segoe UI", 9, QFont.Weight.Bold))
                        chan_item.setExpanded(True)
                        chan_item.setData(0, Qt.ItemDataRole.UserRole, ch_key)
                        self._chan_tree_items[(d_key, ch_key)] = chan_item

                    ch_tracks.sort(key=lambda x: x.get("id", 0), reverse=True)

                    for t in ch_tracks:
                        track_item = self._create_single_track_item(chan_item, t, ch_key)
                        if getattr(self, "_selected_channel_filter", None):
                            f_ch = self._selected_channel_filter.strip().lower()
                            if ch_key.strip().lower() != f_ch:
                                track_item.setHidden(True)
                        query = ""
                        if hasattr(self, "top_search_input"):
                            query = self.top_search_input.text().strip().lower()
                        elif hasattr(self, "search_filter_input"):
                            query = self.search_filter_input.text().strip().lower()
                        if query:
                            title = track_item.text(1).lower()
                            artist = track_item.text(2).lower()
                            if query not in f"{artist} {title}":
                                track_item.setHidden(True)

                    self._chan_track_counts[(d_key, ch_key)] += len(ch_tracks)
                    self._date_track_counts[d_key] += len(ch_tracks)

                    c_cnt = self._chan_track_counts[(d_key, ch_key)]
                    chan_item.setText(0, f"  ✈ {ch_key}   ({c_cnt} треков)")

                d_cnt = self._date_track_counts[d_key]
                if d_key == today_str:
                    d_header = f"📅 СЕГОДНЯ • {d_key}   ({d_cnt} треков)"
                elif d_key == yest_str:
                    d_header = f"📅 ВЧЕРА • {d_key}   ({d_cnt} треков)"
                elif d_key == "Архив":
                    d_header = f"📅 РАНЕЕ / АРХИВ   ({d_cnt} треков)"
                else:
                    d_header = f"📅 {d_key}   ({d_cnt} треков)"
                date_item.setText(0, d_header)

            start_row = self.track_list.count()
            for idx_offset, t in enumerate(new_tracks):
                msg_id = t["id"]
                current_idx = start_row + idx_offset
                self._track_row_by_id[msg_id] = current_idx

                size_str = ""
                if t.get("size"):
                    size_mb = t["size"] / (1024 * 1024)
                    size_str = f"  [{size_mb:.1f} MB]"
                label = f"{t.get('performer', '')} - {t.get('title', '')}  [{t.get('date', '')}]{size_str}"
                if t.get("already_exists"):
                    label += "  ✓ уже есть"

                item = QListWidgetItem(label)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if not t.get("already_exists")
                    else Qt.CheckState.Unchecked
                )
                item.setData(Qt.ItemDataRole.UserRole, msg_id)
                self.track_list.addItem(item)
                self._track_list_item_by_id[msg_id] = item

            all_tracks = getattr(self, "_scan_results", [])
            new_count = sum(1 for tr in all_tracks if not tr.get("already_exists"))
            existing_count = len(all_tracks) - new_count
            if hasattr(self, "stats_label"):
                self.stats_label.setText(
                    f"Всего: {len(all_tracks)} • Новых: {new_count} • На диске: {existing_count}"
                )
            self._update_download_button_counter()

        finally:
            if hasattr(self, "library_tree"):
                self.library_tree.setUpdatesEnabled(True)
            self._updating_tree = False

    def _sync_table_from_track_list(self):
        """Совместимость: синхронизирует состояние чекбоксов дерева из track_list."""
        self._updating_tree = True
        try:
            for i in range(self.track_list.count()):
                l_item = self.track_list.item(i)
                msg_id = l_item.data(Qt.ItemDataRole.UserRole)
                if msg_id and msg_id in getattr(self, "_track_item_by_id", {}):
                    self._track_item_by_id[msg_id].setCheckState(0, l_item.checkState())
        finally:
            self._updating_tree = False

    def _on_table_cell_changed(self, row, col):
        pass

    def _on_table_row_double_clicked(self, item):
        if hasattr(item, "row"):
            row = item.row()
            if row < len(self._scan_results):
                self._on_track_double_clicked(self.track_list.item(row))

    def _update_download_button_counter(self, item=None):
        selected_count = sum(
            1
            for i in range(self.track_list.count())
            if self.track_list.item(i).checkState() == Qt.CheckState.Checked
        )
        if selected_count > 0:
            self.download_button.setText(f"⚡ Скачать выбранное ({selected_count})")
            if getattr(self, "btn_lib_download", None):
                self.btn_lib_download.setText(f"⬇ Download ({selected_count})")
        else:
            self.download_button.setText("Скачать выбранное")
            if getattr(self, "btn_lib_download", None):
                self.btn_lib_download.setText("⬇ Download All")

    def _expand_all_groups(self):
        if hasattr(self, "library_tree"):
            self.library_tree.expandAll()

    def _collapse_all_groups(self):
        if hasattr(self, "library_tree"):
            self.library_tree.collapseAll()

    def _select_only_new_tracks(self):
        self._updating_tree = True
        try:
            for i in range(self.track_list.count()):
                item = self.track_list.item(i)
                is_existing = "✓ уже есть" in item.text()
                item.setCheckState(
                    Qt.CheckState.Unchecked if is_existing else Qt.CheckState.Checked
                )
            for track_item in getattr(self, "_track_item_by_id", {}).values():
                t_data = track_item.data(1, Qt.ItemDataRole.UserRole) or {}
                is_existing = t_data.get("already_exists", False)
                track_item.setCheckState(
                    0,
                    Qt.CheckState.Unchecked if is_existing else Qt.CheckState.Checked,
                )
        finally:
            self._updating_tree = False
        self._update_download_button_counter()

    def _select_all_tracks(self):
        self._updating_tree = True
        try:
            for i in range(self.track_list.count()):
                item = self.track_list.item(i)
                item.setCheckState(Qt.CheckState.Checked)
            for track_item in getattr(self, "_track_item_by_id", {}).values():
                track_item.setCheckState(0, Qt.CheckState.Checked)
            if hasattr(self, "library_tree"):
                for i in range(self.library_tree.topLevelItemCount()):
                    top = self.library_tree.topLevelItem(i)
                    top.setCheckState(0, Qt.CheckState.Checked)
                    for j in range(top.childCount()):
                        top.child(j).setCheckState(0, Qt.CheckState.Checked)
        finally:
            self._updating_tree = False
        self._update_download_button_counter()

    def _clear_selection(self):
        self._updating_tree = True
        try:
            for i in range(self.track_list.count()):
                item = self.track_list.item(i)
                item.setCheckState(Qt.CheckState.Unchecked)
            for track_item in getattr(self, "_track_item_by_id", {}).values():
                track_item.setCheckState(0, Qt.CheckState.Unchecked)
            if hasattr(self, "library_tree"):
                for i in range(self.library_tree.topLevelItemCount()):
                    top = self.library_tree.topLevelItem(i)
                    top.setCheckState(0, Qt.CheckState.Unchecked)
                    for j in range(top.childCount()):
                        top.child(j).setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self._updating_tree = False
        self._update_download_button_counter()

    def _reset_dj_filters(self):
        """Сбрасывает все диджейские фильтры в состояние по умолчанию."""
        self._active_camelot_key = None
        if hasattr(self, "camelot_wheel") and self.camelot_wheel:
            self.camelot_wheel.clear_selection()
        if hasattr(self, "combo_filter_status"):
            self.combo_filter_status.setCurrentIndex(0)
        if hasattr(self, "combo_filter_duration"):
            self.combo_filter_duration.setCurrentIndex(0)
        if hasattr(self, "combo_filter_bpm"):
            self.combo_filter_bpm.setCurrentIndex(0)
        if hasattr(self, "combo_filter_bitrate"):
            self.combo_filter_bitrate.setCurrentIndex(0)
        if hasattr(self, "search_filter_input"):
            self.search_filter_input.clear()
        if hasattr(self, "top_search_input"):
            self.top_search_input.clear()
        self._apply_all_filters()

    def _apply_harmonic_filter(self, key_str: str | None = None):
        """Фильтрует треки библиотеки по гармонической совместимости колеса Камелота."""
        self._active_camelot_key = key_str if key_str else None
        self._apply_all_filters()

    def _on_tree_selection_changed(self):
        """Синхронизирует выбор трека в дереве библиотеки с Bento Track Inspector."""
        if not hasattr(self, "library_tree"):
            return
        items = self.library_tree.selectedItems()
        if not items:
            return
        item = items[0]
        track = item.data(1, Qt.ItemDataRole.UserRole)
        if not track:
            track_id = item.data(0, Qt.ItemDataRole.UserRole)
            track = next(
                (t for t in getattr(self, "_scan_results", []) if t.get("id") == track_id),
                None,
            )
        if track and hasattr(self, "track_inspector") and self.track_inspector:
            self.track_inspector.display_track(track)

    def _filter_tracks_text(self, text=""):
        if hasattr(self, "top_search_input") and hasattr(self, "search_filter_input"):
            for s_inp in (self.top_search_input, self.search_filter_input):
                if s_inp.text() != text:
                    s_inp.blockSignals(True)
                    s_inp.setText(text)
                    s_inp.blockSignals(False)
        self._apply_all_filters(text)

    def _apply_all_filters(self, _arg=None):
        query = ""
        if hasattr(self, "search_filter_input") and self.search_filter_input.text():
            query = self.search_filter_input.text().strip().lower()
        elif hasattr(self, "top_search_input") and self.top_search_input.text():
            query = self.top_search_input.text().strip().lower()

        channel_filter = getattr(self, "_selected_channel_filter", None)
        if channel_filter:
            channel_filter = channel_filter.strip().lower()

        status_idx = self.combo_filter_status.currentIndex() if hasattr(self, "combo_filter_status") else 0
        dur_idx = self.combo_filter_duration.currentIndex() if hasattr(self, "combo_filter_duration") else 0
        bpm_idx = self.combo_filter_bpm.currentIndex() if hasattr(self, "combo_filter_bpm") else 0
        bitrate_idx = self.combo_filter_bitrate.currentIndex() if hasattr(self, "combo_filter_bitrate") else 0

        for i in range(self.track_list.count()):
            item = self.track_list.item(i)
            msg_id = item.data(Qt.ItemDataRole.UserRole)
            t_obj = getattr(self, "_track_by_id", {}).get(msg_id, {})
            matches = self._check_track_filter_match(
                t_obj, query, channel_filter, status_idx, dur_idx, bpm_idx, bitrate_idx
            )
            item.setHidden(not matches)

        visible_count = 0
        visible_new = 0
        visible_existing = 0

        if hasattr(self, "library_tree"):
            for i in range(self.library_tree.topLevelItemCount()):
                date_item = self.library_tree.topLevelItem(i)
                date_has_visible = False

                for j in range(date_item.childCount()):
                    chan_item = date_item.child(j)
                    chan_has_visible = False

                    for k in range(chan_item.childCount()):
                        track_item = chan_item.child(k)
                        t_data = track_item.data(1, Qt.ItemDataRole.UserRole) or {}
                        track_matches = self._check_track_filter_match(
                            t_data, query, channel_filter, status_idx, dur_idx, bpm_idx, bitrate_idx
                        )
                        track_item.setHidden(not track_matches)
                        if track_matches:
                            chan_has_visible = True
                            date_has_visible = True
                            visible_count += 1
                            if t_data.get("already_exists"):
                                visible_existing += 1
                            else:
                                visible_new += 1

                    chan_item.setHidden(not chan_has_visible)
                date_item.setHidden(not date_has_visible)

        if hasattr(self, "stats_label") and hasattr(self, "_scan_results") and self._scan_results:
            total_count = len(self._scan_results)
            has_active_filter = bool(query or channel_filter or status_idx or dur_idx or bpm_idx or bitrate_idx)
            if has_active_filter:
                filt_info = f" [{channel_filter}]" if channel_filter else ""
                self.stats_label.setText(
                    f"Найдено{filt_info}: {visible_count} • Новых: {visible_new} • На диске: {visible_existing} (Всего: {total_count})"
                )
            else:
                new_count = sum(1 for t in self._scan_results if not t.get("already_exists"))
                exist_count = total_count - new_count
                self.stats_label.setText(
                    f"Всего: {total_count} • Новых: {new_count} • На диске: {exist_count}"
                )

    def _check_track_filter_match(
        self, t_data, query, channel_filter, status_idx, dur_idx, bpm_idx, bitrate_idx
    ) -> bool:
        if not t_data:
            return True

        # 1. Текстовый поиск
        if query:
            artist = str(t_data.get("performer", "")).lower()
            title = str(t_data.get("title", "")).lower()
            if query not in f"{artist} {title}":
                return False

        # 2. Фильтр по каналу
        if channel_filter:
            t_chan = str(t_data.get("channel", "")).lower()
            if t_chan != channel_filter:
                return False

        # 3. Фильтр по статусу
        # 0: Все, 1: Новые, 2: На диске, 3: Дубликаты
        if status_idx == 1:
            if t_data.get("already_exists") or t_data.get("is_duplicate"):
                return False
        elif status_idx == 2:
            if not t_data.get("already_exists") or t_data.get("is_duplicate"):
                return False
        elif status_idx == 3:
            if not t_data.get("is_duplicate"):
                return False

        # 4. Фильтр по длительности
        dur = t_data.get("duration", 0) or 0
        if dur_idx == 1:  # DJ Tracks (3:00 - 8:00)
            if not (180 <= dur <= 480):
                return False
        elif dur_idx == 2:  # Extended Mix (> 5:00)
            if dur < 300:
                return False
        elif dur_idx == 3:  # Radio Edit (< 3:30)
            if not (0 < dur <= 210):
                return False
        elif dur_idx == 4:  # DJ Set / Mix (> 20:00)
            if dur < 1200:
                return False

        # 5. Фильтр по BPM
        if bpm_idx > 0:
            bpm_raw = t_data.get("bpm") or extract_bpm_meta(t_data.get("title", ""), t_data.get("performer", ""))
            try:
                bpm_val = int(bpm_raw)
            except (ValueError, TypeError):
                return False

            if bpm_idx == 1 and not (120 <= bpm_val <= 130):
                return False
            elif bpm_idx == 2 and not (115 <= bpm_val <= 124):
                return False
            elif bpm_idx == 3 and not (130 <= bpm_val <= 145):
                return False
            elif bpm_idx == 4 and not (160 <= bpm_val <= 180):
                return False
            elif bpm_idx == 5 and bpm_val >= 115:
                return False

        # 6. Фильтр по качеству / битрейту
        if bitrate_idx > 0:
            fname = str(t_data.get("filename", "")).lower()
            tit = str(t_data.get("title", "")).lower()
            size_mb = (t_data.get("size", 0) or 0) / (1024 * 1024)
            if bitrate_idx == 1:  # HQ 320 kbps
                if not ("320" in fname or "320" in tit or (size_mb >= 8.5 and dur <= 360)):
                    return False
            elif bitrate_idx == 2:  # Lossless
                if not fname.endswith((".flac", ".wav", ".alac")):
                    return False
            elif bitrate_idx == 3:  # Standard >= 192k
                if size_mb < 4.5 and dur > 120:
                    return False

        # 7. Фильтр по Camelot Key (гармоническая совместимость)
        camelot_filter = getattr(self, "_active_camelot_key", None)
        if camelot_filter:
            from media_utils import extract_key_meta
            from ui.bento_widgets import CamelotWheelWidget
            track_key = t_data.get("key") or extract_key_meta(t_data.get("title", ""), t_data.get("performer", ""))
            if not track_key or track_key == "—":
                return False
            compatible_keys = CamelotWheelWidget.get_compatible_keys(camelot_filter)
            if track_key.upper() not in compatible_keys:
                return False

        return True

    def _on_tree_item_changed(self, item, col):
        if col != 0 or getattr(self, "_updating_tree", False):
            return

        self._updating_tree = True
        try:
            state = item.checkState(0)

            def set_children_state(parent_item, target_state):
                for idx in range(parent_item.childCount()):
                    child = parent_item.child(idx)
                    child.setCheckState(0, target_state)
                    msg_id = child.data(0, Qt.ItemDataRole.UserRole)
                    if msg_id and msg_id in getattr(self, "_track_list_item_by_id", {}):
                        self._track_list_item_by_id[msg_id].setCheckState(target_state)
                    if child.childCount() > 0:
                        set_children_state(child, target_state)

            if item.childCount() > 0:
                set_children_state(item, state)
            else:
                msg_id = item.data(0, Qt.ItemDataRole.UserRole)
                if msg_id and msg_id in getattr(self, "_track_list_item_by_id", {}):
                    self._track_list_item_by_id[msg_id].setCheckState(state)

                parent = item.parent()
                if parent:
                    all_ch_checked = all(
                        parent.child(c).checkState(0) == Qt.CheckState.Checked
                        for c in range(parent.childCount())
                    )
                    parent.setCheckState(
                        0,
                        Qt.CheckState.Checked if all_ch_checked else Qt.CheckState.Unchecked,
                    )
                    grandparent = parent.parent()
                    if grandparent:
                        all_date_checked = all(
                            grandparent.child(c).checkState(0) == Qt.CheckState.Checked
                            for c in range(grandparent.childCount())
                        )
                        grandparent.setCheckState(
                            0,
                            Qt.CheckState.Checked if all_date_checked else Qt.CheckState.Unchecked,
                        )
        finally:
            self._updating_tree = False

        self._update_download_button_counter()

    def _on_tree_item_double_clicked(self, item, col):
        if item.childCount() > 0:
            item.setExpanded(not item.isExpanded())
            return

        track = item.data(1, Qt.ItemDataRole.UserRole)
        if not track:
            track_id = item.data(0, Qt.ItemDataRole.UserRole)
            track = next(
                (t for t in getattr(self, "_scan_results", []) if t.get("id") == track_id),
                None,
            )
        if track:
            if hasattr(self, "play_or_preview_track"):
                self.play_or_preview_track(track)
            else:
                filepath = track.get("filepath", "")
                title = f"{track.get('performer', '')} - {track.get('title', '')}".strip(" -")
                if os.path.exists(filepath):
                    self.player_bar.setVisible(True)
                    self.play_audio_file(filepath, title=title)
                    self.log(f"▶ Воспроизведение: {title}")
                else:
                    self.player_bar.setVisible(True)
                    self.player_title_label.setText(f"⏳ Файл ещё не скачан: {title}")

    def _on_tree_scroll(self, value):
        if not hasattr(self, "library_tree"):
            return
        sb = self.library_tree.verticalScrollBar()
        if sb.maximum() > 0 and value >= max(0, sb.maximum() - 250):
            self._load_more_tracks()

    def _refresh_table_statuses(self):
        if not hasattr(self, "_track_status_badges") or not self._scan_results:
            return
        chan = self.channel_input.text().strip()
        for row, t in enumerate(self._scan_results):
            m_id = t.get("id")
            fpath = t.get("filepath", "")
            exists = (fpath and os.path.exists(fpath)) or db_module.is_downloaded(chan, m_id)
            if exists:
                t["already_exists"] = True
                if m_id in self._track_status_badges:
                    badge = self._track_status_badges[m_id]
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
                    badge.setToolTip("Файл сохранен на диске")
                if m_id in getattr(self, "_track_waveforms", {}):
                    self._track_waveforms[m_id].setPixmap(
                        create_waveform_pixmap(150, 22, "#2ECC71", seed=m_id)
                    )
                    self._track_waveforms[m_id].setToolTip("Файл сохранен на диске")

    def _toggle_filter_bar(self):
        if hasattr(self, "batch_bar"):
            is_vis = self.batch_bar.isVisible()
            self.batch_bar.setVisible(not is_vis)
            if not is_vis:
                self.search_filter_input.setFocus()

    def toggle_item_check_state(self, item=None):
        """Переключает состояние выбора (чекбокс) для указанного элемента дерева или текущего выбранного."""
        if item is None and hasattr(self, "library_tree"):
            item = self.library_tree.currentItem()
        if not item:
            return
        current_state = item.checkState(0)
        new_state = (
            Qt.CheckState.Unchecked
            if current_state == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        item.setCheckState(0, new_state)

    def get_checked_tracks(self) -> list[dict]:
        """Возвращает список данных треков, отмеченных пользователем чекбоксами."""
        checked = []
        if hasattr(self, "track_list") and hasattr(self, "_track_by_id"):
            for i in range(self.track_list.count()):
                it = self.track_list.item(i)
                if it.checkState() == Qt.CheckState.Checked:
                    m_id = it.data(Qt.ItemDataRole.UserRole)
                    t_data = self._track_by_id.get(m_id)
                    if t_data:
                        checked.append(t_data)
        return checked

    def _show_tree_context_menu(self, pos):
        """Отображает контекстное меню для элементов дерева треков."""
        item = self.library_tree.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #0E1624;
                border: 1px solid #243142;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                color: #F1F5F9;
                padding: 6px 20px;
                border-radius: 4px;
                font-size: 11px;
            }
            QMenu::item:selected {
                background-color: #00D2BE;
                color: #080D15;
                font-weight: 700;
            }
        """)

        act_toggle = menu.addAction("☑ Отметить / Снять выбор")
        act_toggle.triggered.connect(lambda: self.toggle_item_check_state(item))

        track_data = item.data(1, Qt.ItemDataRole.UserRole)
        if track_data:
            act_play = menu.addAction("▶ Воспроизвести превью")
            act_play.triggered.connect(lambda: self._on_tree_item_double_clicked(item, 1))

        menu.addSeparator()
        act_export = menu.addAction("🎶 Экспорт в M3U8 плейлист...")
        act_export.triggered.connect(lambda: self.export_selected_to_m3u8())

        menu.exec(self.library_tree.viewport().mapToGlobal(pos))

    def export_selected_to_m3u8(self, target_filepath=None):
        """Экспортирует выбранные (или все доступные) треки в стандартный файл M3U8."""
        checked_tracks = self.get_checked_tracks()
        if not checked_tracks:
            curr = getattr(self, "library_tree", None) and self.library_tree.currentItem()
            if curr:
                t_curr = curr.data(1, Qt.ItemDataRole.UserRole)
                if t_curr:
                    checked_tracks = [t_curr]
            if not checked_tracks:
                checked_tracks = getattr(self, "_scan_results", [])

        if not checked_tracks:
            self.log("⚠ Нет треков для экспорта в M3U8.")
            return None

        if not target_filepath:
            from config import BASE_FOLDER
            today = datetime.now().strftime("%Y-%m-%d")
            chan = self.channel_input.text().strip().lstrip("@") or "tracks"
            default_name = os.path.join(BASE_FOLDER, f"{chan}_{today}.m3u8")
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить M3U8 плейлист",
                default_name,
                "M3U8 Playlist (*.m3u8);;All Files (*.*)",
            )
            if not file_path:
                return None
            target_filepath = file_path

        try:
            entries = []
            for t in checked_tracks:
                entries.append({
                    "filepath": t.get("filepath", ""),
                    "artist": t.get("performer", ""),
                    "title": t.get("title", ""),
                    "duration": t.get("duration", 0),
                })
            out = generate_m3u8_playlist(target_filepath, entries, relative=True)
            self.log(f"🎶 Экспортирован M3U8 плейлист: {out} ({len(entries)} треков)")
            return out
        except Exception as e:
            self.log(f"⚠ Ошибка при экспорте M3U8: {e}")
            return None


