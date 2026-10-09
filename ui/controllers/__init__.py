"""
UI Controllers package for Telegram Audio Downloader (BEATSTORM DJ Pool).

Provides mixins for MainWindow:
- ChannelsMixin: Channel management, settings, tabs and views navigation.
- TreeControllerMixin: Track tree rendering, grouping, waveforms, search and selection.
- DownloadControllerMixin: Scanning, download threads orchestration, progress & speed tracking.
"""

from ui.controllers.channels_controller import ChannelsMixin
from ui.controllers.tree_controller import TreeControllerMixin
from ui.controllers.download_controller import DownloadControllerMixin

__all__ = [
    "ChannelsMixin",
    "TreeControllerMixin",
    "DownloadControllerMixin",
]
