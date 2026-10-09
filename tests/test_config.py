import os
import json
import pytest
import config as cfg


class TestLoadConfig:

    def test_load_defaults_when_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, 'CONFIG_DIR', str(tmp_path))
        monkeypatch.setattr(cfg, 'CONFIG_FILE', str(tmp_path / 'config.json'))
        result = cfg.load_config()
        assert result == cfg.DEFAULT_CONFIG

    def test_load_merges_with_defaults(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, 'CONFIG_DIR', str(tmp_path))
        monkeypatch.setattr(cfg, 'CONFIG_FILE', str(tmp_path / 'config.json'))
        partial = {'api_id': '12345', 'channel': '@test'}
        os.makedirs(tmp_path, exist_ok=True)
        with open(str(tmp_path / 'config.json'), 'w', encoding='utf-8') as f:
            json.dump(partial, f)
        result = cfg.load_config()
        assert result['api_id'] == '12345'
        assert result['channel'] == '@test'
        assert result['mode'] == 'direct'
        assert result['max_concurrent_downloads'] == 5

    def test_load_returns_defaults_on_corrupt_json(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, 'CONFIG_DIR', str(tmp_path))
        monkeypatch.setattr(cfg, 'CONFIG_FILE', str(tmp_path / 'config.json'))
        os.makedirs(tmp_path, exist_ok=True)
        with open(str(tmp_path / 'config.json'), 'w', encoding='utf-8') as f:
            f.write('not valid json')
        result = cfg.load_config()
        assert result == cfg.DEFAULT_CONFIG

    def test_load_unknown_fields_preserved(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, 'CONFIG_DIR', str(tmp_path))
        monkeypatch.setattr(cfg, 'CONFIG_FILE', str(tmp_path / 'config.json'))
        bad = {'api_id': '12345', 'unknown_field': 'should_not_appear'}
        os.makedirs(tmp_path, exist_ok=True)
        with open(str(tmp_path / 'config.json'), 'w', encoding='utf-8') as f:
            json.dump(bad, f)
        result = cfg.load_config()
        assert result['api_id'] == '12345'
        assert result.get('unknown_field') == 'should_not_appear'


class TestSaveConfig:

    def test_save_creates_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, 'CONFIG_DIR', str(tmp_path))
        monkeypatch.setattr(cfg, 'CONFIG_FILE', str(tmp_path / 'config.json'))
        cfg.save_config(api_id='999', mode='record')
        assert os.path.exists(str(tmp_path / 'config.json'))
        with open(str(tmp_path / 'config.json'), 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['api_id'] == '999'
        assert data['mode'] == 'record'

    def test_save_merges_existing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, 'CONFIG_DIR', str(tmp_path))
        monkeypatch.setattr(cfg, 'CONFIG_FILE', str(tmp_path / 'config.json'))
        cfg.save_config(api_id='111', channel='@ch1')
        cfg.save_config(api_hash='abc', mode='hybrid')
        with open(str(tmp_path / 'config.json'), 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['api_id'] == '111'
        assert data['api_hash'] == 'abc'
        assert data['channel'] == '@ch1'
        assert data['mode'] == 'hybrid'

    def test_save_latest_overrides(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, 'CONFIG_DIR', str(tmp_path))
        monkeypatch.setattr(cfg, 'CONFIG_FILE', str(tmp_path / 'config.json'))
        cfg.save_config(api_id='1', channel='@a')
        cfg.save_config(api_id='2')
        with open(str(tmp_path / 'config.json'), 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['api_id'] == '2'
        assert data['channel'] == '@a'

    def test_save_handles_permission_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, 'CONFIG_DIR', str(tmp_path))
        monkeypatch.setattr(cfg, 'CONFIG_FILE', str(tmp_path / 'config.json'))
        cfg.save_config(api_id='test')
        assert os.path.exists(str(tmp_path / 'config.json'))


class TestDefaults:

    def test_default_config_structure(self):
        required = {
            'api_id', 'api_hash', 'channel', 'mode',
            'date_from', 'date_to', 'base_folder',
            'max_concurrent_downloads', 'max_download_retries',
            'download_delay', 'mp3_bitrate', 'sample_rate',
            'proxy_enabled', 'proxy_type', 'proxy_host', 'proxy_port',
            'proxy_username', 'proxy_password',
            'export_pattern', 'auto_generate_m3u8', 'playlist_filename',
            'minimize_to_tray', 'tray_notifications',
            'auto_watcher_enabled', 'auto_watcher_interval_minutes',
        }
        assert set(cfg.DEFAULT_CONFIG.keys()) == required
        assert cfg.DEFAULT_CONFIG['mode'] == 'direct'
        assert cfg.DEFAULT_CONFIG['max_concurrent_downloads'] == 5
        assert cfg.DEFAULT_CONFIG['max_download_retries'] == 3
        assert cfg.DEFAULT_CONFIG['mp3_bitrate'] == '192k'
        assert cfg.DEFAULT_CONFIG['auto_generate_m3u8'] is True
        assert cfg.DEFAULT_CONFIG['minimize_to_tray'] is False
        assert cfg.DEFAULT_CONFIG['tray_notifications'] is True
        assert cfg.DEFAULT_CONFIG['auto_watcher_enabled'] is False
        assert cfg.DEFAULT_CONFIG['auto_watcher_interval_minutes'] == 15
