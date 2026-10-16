"""Тесты на сервис настроек (шаг 3 рефакторинга).

Настройки читаются и пишутся только через ``Settings``. Кэша внутри
нет намеренно: приложение перезаписывает config.json из памяти, и
закешированная копия разошлась бы с тем, что показано в интерфейсе.

Отдельно проверяется синхронизация вложенного ``proxy`` и плоских
``proxy_*``: при наличии вложенного словаря загрузчик читает именно его,
и молчаливый разрыв этих двух записей означал бы, что прокси в интерфейсе
настроен одним адресом, а реально используется другим.
"""

import json

import pytest

import config


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Настройки, пишущие во временный каталог."""
    base = tmp_path / "telegram_audio"
    base.mkdir()
    monkeypatch.setattr(config, "BASE_PATH", str(base))
    monkeypatch.setattr(config, "CONFIG_DIR", str(base))
    monkeypatch.setattr(config, "CONFIG_FILE", str(base / "config.json"))
    return config.Settings()


def _stored(store):
    with open(store.CONFIG_FILE if hasattr(store, "CONFIG_FILE")
              else config.CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


class TestRead:
    """Чтение настроек."""

    def test_defaults_when_no_file(self, store):
        assert store.read()["channel"] == ""
        assert store.read()["max_concurrent_downloads"] == 5

    def test_stored_values_win_over_defaults(self, store):
        store.write({"channel": "@akmpool"})
        assert store.read()["channel"] == "@akmpool"
        # остальные значения остаются умолчаниями
        assert store.read()["max_download_retries"] == 3

    def test_missing_file_returns_defaults(self, store):
        assert store.read() == dict(config.DEFAULT_CONFIG)

    def test_broken_file_does_not_raise(self, store):
        """Битый config.json не должен мешать запуску."""
        store.write({"channel": "@akmpool"})
        with open(config.CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write("{ это не json")
        assert store.read() == dict(config.DEFAULT_CONFIG)

    def test_get_falls_back_to_default(self, store):
        assert store.get("mp3_bitrate") == "192k"

    def test_get_unknown_key_returns_none(self, store):
        assert store.get("такого_ключа_нет") is None

    def test_get_reads_current_file(self, store):
        """Кэша нет: изменение файла видно сразу."""
        store.write({"channel": "@akmpool"})
        assert store.get("channel") == "@akmpool"
        store.write({"channel": "@primetimedj"})
        assert store.get("channel") == "@primetimedj"


class TestWrite:
    """Запись настроек."""

    def test_creates_directory(self, store, tmp_path, monkeypatch):
        fresh = tmp_path / "новое"
        monkeypatch.setattr(config, "CONFIG_DIR", str(fresh))
        monkeypatch.setattr(config, "CONFIG_FILE", str(fresh / "config.json"))
        assert store.write({"channel": "@akmpool"}) is True
        assert (fresh / "config.json").exists()

    def test_partial_update_keeps_the_rest(self, store):
        store.write({"channel": "@akmpool", "mode": "direct"})
        store.write({"mode": "record"})
        saved = _stored(store)
        assert saved["channel"] == "@akmpool"
        assert saved["mode"] == "record"

    def test_report_of_success(self, store):
        assert store.write({"channel": "@akmpool"}) is True

    def test_unwritable_target_reports_failure(self, store, tmp_path,
                                               monkeypatch):
        """Ошибка записи возвращается, а не теряется молча."""
        blocker = tmp_path / "файл-а-не-папка"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(config, "CONFIG_DIR", str(blocker))
        monkeypatch.setattr(config, "CONFIG_FILE",
                            str(blocker / "config.json"))
        assert store.write({"channel": "@akmpool"}) is False


class TestProxySync:
    """Вложенный proxy и плоские proxy_* не должны расходиться."""

    def test_flat_host_creates_nested(self, store):
        store.write({"proxy_host": "1.2.3.4"})
        saved = _stored(store)
        assert saved["proxy_host"] == "1.2.3.4"
        assert saved["proxy"]["host"] == "1.2.3.4"

    def test_port_is_stored_as_text(self, store):
        """Порт хранится строкой: так уже было, иначе он не совпадал бы."""
        store.write({"proxy_port": 10808})
        saved = _stored(store)
        assert saved["proxy"]["port"] == "10808"

    def test_later_flat_write_syncs_nested_back(self, store):
        """Плоское обновление обязано снова вести вложенное за собой.

        Загрузчик читает вложенный ``proxy``, поэтому если бы плоская
        запись его не трогала, прокси в интерфейсе и в работе разошлись
        бы навсегда.
        """
        store.write({"proxy": {"host": "9.9.9.9"}})
        store.write({"proxy_host": "1.2.3.4"})
        saved = _stored(store)
        assert saved["proxy"]["host"] == "1.2.3.4"
        assert saved["proxy_host"] == "1.2.3.4"

    def test_explicit_nested_replaces_flat_as_well(self, store):
        """Явный вложенный словарь задаёт все поля разом."""
        store.write({"proxy_host": "1.2.3.4"})
        store.write({"proxy": {"host": "9.9.9.9", "port": "1080"}})
        saved = _stored(store)
        assert saved["proxy"]["host"] == "9.9.9.9"
        assert saved["proxy"]["port"] == "1080"

    def test_unrelated_update_keeps_proxy(self, store):
        store.write({"proxy_host": "1.2.3.4"})
        store.write({"channel": "@akmpool"})
        assert _stored(store)["proxy"]["host"] == "1.2.3.4"

    def test_no_proxy_write_creates_no_nested_key(self, store):
        store.write({"channel": "@akmpool"})
        assert "proxy" not in _stored(store)


class TestCompatibilityWrappers:
    """Старые функции должны вести себя как раньше."""

    def test_load_config_returns_full_dict(self, store):
        cfg = config.load_config()
        assert isinstance(cfg, dict)
        assert set(config.DEFAULT_CONFIG) <= set(cfg)

    def test_save_config_writes(self, store):
        config.save_config(channel="@akmpool")
        assert config.load_config()["channel"] == "@akmpool"

    def test_save_config_merges_proxy(self, store):
        config.save_config(proxy_host="1.2.3.4")
        assert config.load_config()["proxy"]["host"] == "1.2.3.4"

    def test_save_config_does_not_erase_others(self, store):
        config.save_config(channel="@akmpool")
        config.save_config(mode="record")
        cfg = config.load_config()
        assert cfg["channel"] == "@akmpool"
        assert cfg["mode"] == "record"


class TestDefaultsAreSingleSource:
    """Контроль регрессии: значения по умолчанию не должны расползаться."""

    def test_pattern_lives_only_in_config(self):
        import media_utils
        import recorder
        from ui import sidebar  # noqa: F401

        root = str(config.__file__).rsplit("config.py", 1)[0]
        literal = '{"date}/{artist} - {title}.mp3"'
        offenders = []
        for name in ("media_utils.py", "recorder.py", "ui/sidebar.py"):
            with open(root + name.replace("/", "\\"), encoding="utf-8") as f:
                code = [l for l in f if not l.lstrip().startswith("#")]
            if literal in "".join(code):
                offenders.append(name)
        assert not offenders, f"шаблон имени продублирован в: {offenders}"

    def test_embed_default_is_not_hardcoded(self):
        """Значение по умолчанию для тегов берётся из DEFAULT_CONFIG."""
        root = str(config.__file__).rsplit("config.py", 1)[0]
        with open(root + "recorder.py", encoding="utf-8") as f:
            source = f.read()
        assert 'load_config().get("embed_id3_tags", True)' not in source