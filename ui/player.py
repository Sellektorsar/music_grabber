"""
Audio player widget and controller for Beatstorm DJ Pool.
"""

import os
import logging
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QSlider,
)

logger = logging.getLogger(__name__)


class ClickableSlider(QSlider):
    """QSlider с мгновенным перемещением к позиции клика (1-Click Seek / Scrub)."""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            width = self.width()
            if width > 0:
                pos_x = event.position().x()
                ratio = max(0.0, min(1.0, pos_x / width))
                new_val = int(self.minimum() + ratio * (self.maximum() - self.minimum()))
                self.setValue(new_val)
                self.sliderMoved.emit(new_val)
                event.accept()
                return
        super().mousePressEvent(event)


class AudioPlayerBar(QWidget):
    """Нижний Preview-плеер (Master Deck Audio Player) для прослушивания треков."""

    def __init__(self, parent=None, log_callback=None):
        super().__init__(parent)
        self.setObjectName("playerBar")
        self.setFixedHeight(50)
        self.setVisible(False)
        self.setStyleSheet("""
            QWidget#playerBar {
                background-color: #0A0D15;
                border-top: 1px solid #162030;
                padding: 4px 14px;
            }
        """)

        self.log_callback = log_callback or (lambda msg: None)
        self._current_audio_path = None
        self._is_seeking = False

        player_layout = QHBoxLayout(self)
        player_layout.setContentsMargins(16, 4, 16, 4)
        player_layout.setSpacing(12)

        self.btn_play_pause = QPushButton("▶")
        self.btn_play_pause.setFixedSize(32, 32)
        self.btn_play_pause.setStyleSheet("""
            QPushButton {
                background-color: #00E5FF;
                color: #06090E;
                font-size: 14px;
                font-weight: bold;
                border-radius: 16px;
                border: none;
            }
            QPushButton:hover {
                background-color: #33EBFF;
            }
        """)
        self.btn_play_pause.clicked.connect(self.toggle_playback)

        self.btn_player_stop = QPushButton("⏹")
        self.btn_player_stop.setFixedSize(28, 28)
        self.btn_player_stop.setObjectName("chipButton")
        self.btn_player_stop.clicked.connect(self.stop_playback)

        self.player_title_label = QLabel("🎵 Двойной клик на треке для воспроизведения")
        self.player_title_label.setStyleSheet("color: #E2E8F0; font-size: 12px; font-weight: 600;")
        self.player_title_label.setMinimumWidth(180)
        self.player_title_label.setMaximumWidth(450)

        self.player_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.player_slider.setRange(0, 1000)
        self.player_slider.setValue(0)
        self.player_slider.sliderMoved.connect(self._on_seek_slider_moved)
        self.player_slider.sliderPressed.connect(self._on_seek_pressed)
        self.player_slider.sliderReleased.connect(self._on_seek_released)
        self.player_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: none;
                height: 4px;
                background: #141C2A;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #00E5FF;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #FFFFFF;
                border: 1px solid #00E5FF;
                width: 10px;
                margin-top: -3px;
                margin-bottom: -3px;
                border-radius: 5px;
            }
        """)

        self.player_time_label = QLabel("00:00 / 00:00")
        self.player_time_label.setStyleSheet("color: #64748B; font-size: 11px; font-family: monospace;")

        vol_layout = QHBoxLayout()
        vol_layout.setSpacing(4)
        vol_icon = QLabel("🔊")
        vol_icon.setStyleSheet("font-size: 11px;")
        self.volume_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(60)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        vol_layout.addWidget(vol_icon)
        vol_layout.addWidget(self.volume_slider)

        player_layout.addWidget(self.btn_play_pause)
        player_layout.addWidget(self.btn_player_stop)
        player_layout.addWidget(self.player_title_label)
        player_layout.addWidget(self.player_slider, stretch=1)
        player_layout.addWidget(self.player_time_label)
        player_layout.addLayout(vol_layout)

        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

            self._audio_output = QAudioOutput(self)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._audio_output)
            self._audio_output.setVolume(0.8)
            self._player.positionChanged.connect(self._on_media_position_changed)
            self._player.durationChanged.connect(self._on_media_duration_changed)
            self._player.playbackStateChanged.connect(self._on_media_state_changed)
            self._player.errorOccurred.connect(self._on_player_error)
        except Exception as player_init_err:
            logger.debug(f"QtMultimedia недоступен: {player_init_err}")
            self._audio_output = None
            self._player = None

    def play_audio_file(self, filepath: str, title: str = ""):
        """Воспроизводит аудиофайл через встроенный QMediaPlayer."""
        if not self._player:
            if callable(self.log_callback):
                self.log_callback("Аудиоплеер недоступен в данной системе.")
            return
        if not filepath or not isinstance(filepath, str) or not os.path.isfile(filepath):
            if filepath and callable(self.log_callback):
                self.log_callback(f"Файл не найден на диске: {filepath}")
            return
        self._current_audio_path = filepath
        self.setVisible(True)
        display_title = title or os.path.basename(filepath)
        self.player_title_label.setText(f"🎵 {display_title}")
        self.player_title_label.setToolTip(display_title)
        self._player.setSource(QUrl.fromLocalFile(os.path.abspath(filepath)))
        self._player.play()

    def load_track(self, filepath: str, title: str = "", artist: str = ""):
        """Загружает и запускает трек в аудиоплеере (алиас для обратной совместимости)."""
        display = f"{artist} - {title}" if artist and title else (title or artist)
        return self.play_audio_file(filepath, display)

    def toggle_playback(self):
        if not self._player:
            return
        from PyQt6.QtMultimedia import QMediaPlayer

        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def stop_playback(self):
        if not self._player:
            return
        self._player.stop()
        self.player_slider.setValue(0)
        self.btn_play_pause.setText("▶")

    def seek_relative(self, delta_ms: int):
        """Перемещает позицию воспроизведения относительно текущей на delta_ms миллисекунд."""
        if not self._player:
            return
        cur_pos = self._player.position()
        dur = self._player.duration()
        new_pos = max(0, cur_pos + delta_ms)
        if dur > 0:
            new_pos = min(new_pos, dur)
        self._player.setPosition(new_pos)

    def _on_media_state_changed(self, state):
        from PyQt6.QtMultimedia import QMediaPlayer

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play_pause.setText("⏸")
        else:
            self.btn_play_pause.setText("▶")

    def _on_media_position_changed(self, position_ms):
        if self._is_seeking or not self._player:
            return
        duration_ms = self._player.duration()
        if duration_ms > 0:
            val = int((position_ms / duration_ms) * 1000)
            self.player_slider.blockSignals(True)
            self.player_slider.setValue(val)
            self.player_slider.blockSignals(False)
        pos_str = self.format_time_ms(position_ms)
        dur_str = self.format_time_ms(duration_ms)
        self.player_time_label.setText(f"{pos_str} / {dur_str}")

    def _on_media_duration_changed(self, duration_ms):
        pos_ms = self._player.position() if self._player else 0
        pos_str = self.format_time_ms(pos_ms)
        dur_str = self.format_time_ms(duration_ms)
        self.player_time_label.setText(f"{pos_str} / {dur_str}")

    def _on_seek_pressed(self):
        self._is_seeking = True

    def _on_seek_released(self):
        self._is_seeking = False
        self._on_seek_slider_moved(self.player_slider.value())

    def _on_seek_slider_moved(self, value):
        if not self._player:
            return
        duration_ms = self._player.duration()
        if duration_ms > 0:
            new_pos = int((value / 1000.0) * duration_ms)
            self._player.setPosition(new_pos)

    def _on_volume_changed(self, value):
        if self._audio_output:
            self._audio_output.setVolume(value / 100.0)

    @staticmethod
    def format_time_ms(ms: int) -> str:
        total_seconds = max(0, int(ms // 1000))
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def _on_player_error(self, error, error_string=""):
        err_msg = f"Ошибка воспроизведения ({error}): {error_string}" if error_string else f"Ошибка воспроизведения ({error})"
        logger.warning(err_msg)
        if callable(self.log_callback):
            try:
                self.log_callback(f"⚠️ {err_msg}")
            except Exception as e:
                logger.debug(f"Ошибка в log_callback: {e}")
        self.btn_play_pause.setText("▶")
