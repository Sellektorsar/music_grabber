"""UI package for Telegram Audio Downloader (BEATSTORM Workstation)."""

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
)
from ui.player import AudioPlayerBar
from ui.views import create_home_view, create_channels_view
from ui.navbar import setup_deck_header
from ui.sidebar import setup_api_drawer, setup_channels_sidebar
from ui.monitor import setup_download_monitor
from ui.library import setup_library_panel
from ui.tray import setup_system_tray, show_tray_notification
from ui.bento_widgets import CamelotWheelWidget, TrackInspectorCard

__all__ = [
    "DARK_STYLESHEET",
    "InputCodeDialog",
    "QRCodeDialog",
    "ProxySettingsDialog",
    "is_ffmpeg_available",
    "SpeedMeterWidget",
    "create_beatstorm_logo_pixmap",
    "create_user_avatar_pixmap",
    "create_waveform_pixmap",
    "create_waveform_placeholder",
    "get_cached_waveform_placeholder",
    "extract_bpm_meta",
    "AudioPlayerBar",
    "create_home_view",
    "create_channels_view",
    "setup_deck_header",
    "setup_api_drawer",
    "setup_channels_sidebar",
    "setup_download_monitor",
    "setup_library_panel",
    "setup_system_tray",
    "show_tray_notification",
    "CamelotWheelWidget",
    "TrackInspectorCard",
]

