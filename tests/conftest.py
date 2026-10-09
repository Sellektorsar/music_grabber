import sys
import os
from unittest.mock import MagicMock, PropertyMock

_telethon_mock = MagicMock()
sys.modules['telethon'] = _telethon_mock

sys.modules['sounddevice'] = MagicMock()


def _make_async_client(*args, **kwargs):
    client = AsyncMock()
    client.connect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=True)
    client.send_code_request = AsyncMock()
    client.sign_in = AsyncMock()
    client.get_me = AsyncMock()
    client.get_entity = AsyncMock()
    client.iter_messages = MagicMock()
    client.disconnect = AsyncMock()
    client.is_connected = MagicMock(return_value=False)
    return client


_telethon_mock.TelegramClient = _make_async_client

_telethon_errors = MagicMock()
sys.modules['telethon.errors'] = _telethon_errors
_telethon_errors.SessionPasswordNeededError = type('SessionPasswordNeededError', (Exception,), {})
_telethon_errors.FloodWaitError = type('FloodWaitError', (Exception,), {'seconds': 1})

_telethon_tl = MagicMock()
sys.modules['telethon.tl'] = _telethon_tl

_telethon_tl_types = MagicMock()
sys.modules['telethon.tl.types'] = _telethon_tl_types

_MockAudioAttr = type('DocumentAttributeAudio', (), {
    'duration': 0,
    'performer': '',
    'title': '',
})
_telethon_tl_types.DocumentAttributeAudio = _MockAudioAttr

from PyQt6.QtWidgets import QApplication
_qapp = QApplication.instance() or QApplication([])

import warnings
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pydub")

import pytest
import tempfile
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, PropertyMock, AsyncMock

import config as cfg_module
import recorder as rec_module
from recorder import TelegramAudioRecorder


def _get_doc_attr(duration=30, performer='TestArtist', title='TestTitle'):
    return MagicMock(spec=_MockAudioAttr, duration=duration, performer=performer, title=title)


@pytest.fixture(autouse=True)
def isolate_base_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(rec_module, 'BASE_FOLDER', str(tmp_path / "telegram_audio"))
    monkeypatch.setattr(cfg_module, 'DB_FILE', str(tmp_path / "telegram_audio" / "downloads.db"))
    monkeypatch.setattr(cfg_module, 'CONFIG_FILE', str(tmp_path / "telegram_audio" / "config.json"))
    return tmp_path


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get_entity = AsyncMock()
    client.iter_messages = MagicMock()
    client.connect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=True)
    client.send_code_request = AsyncMock()
    client.sign_in = AsyncMock()
    client.get_me = AsyncMock()
    client.disconnect = AsyncMock()
    return client


@pytest.fixture
def recorder(mock_client):
    rec = TelegramAudioRecorder(mock_client, '@testchannel')
    return rec


def make_message(
    audio=None,
    document=None,
    date=None,
    msg_id=1,
    raw_text='',
    file=None,
    buttons=None,
):
    msg = MagicMock()
    msg.audio = audio
    msg.document = document
    msg.date = date or datetime.now(timezone.utc)
    msg.id = msg_id
    msg.raw_text = raw_text
    msg.file = file
    msg.buttons = buttons
    return msg


def make_audio(mime_type='audio/mpeg', duration=30, performer='TestArtist', title='TestTitle'):
    audio = MagicMock()
    audio.mime_type = mime_type
    audio.duration = duration
    audio.performer = performer
    audio.title = title
    return audio


def make_document(mime_type='audio/mpeg', attrs=None):
    doc = MagicMock()
    doc.mime_type = mime_type
    doc.attributes = attrs or []
    return doc
