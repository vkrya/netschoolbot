"""Тесты конфигурации.

Отдельное внимание — тому, что приложение стартует на минимальном наборе
переменных. Требование настройки, которая ни на что не влияет, однажды уже
не дало службе подняться.
"""

import pytest

from app.settings import SettingsError, load_settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for key in list(__import__("os").environ):
        if key.startswith(("NETSCHOOL_", "TG_", "CHECK_INTERVAL", "DEBUG_MODE", "VOLGOGRAD_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NETSCHOOL_DATA_DIR", str(tmp_path))


class TestMinimalConfig:
    def test_bot_token_alone_is_enough(self, monkeypatch):
        # Ровно тот случай, который однажды не дал службе подняться.
        monkeypatch.setenv("NETSCHOOL_BOT_TOKEN", "123:abc")
        settings = load_settings()
        assert settings.telegram.bot_token == "123:abc"
        assert settings.web.enabled is True

    def test_missing_bot_token_is_reported(self, monkeypatch):
        with pytest.raises(SettingsError, match="NETSCHOOL_BOT_TOKEN"):
            load_settings()

    def test_bot_token_optional_for_import(self):
        # Перенос данных не требует токена: он не ходит в Telegram.
        assert load_settings(require_bot_token=False).telegram.bot_token == ""


class TestValidation:
    def test_interval_out_of_range(self, monkeypatch):
        monkeypatch.setenv("NETSCHOOL_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("CHECK_INTERVAL", "5")
        with pytest.raises(SettingsError, match="CHECK_INTERVAL"):
            load_settings()

    def test_non_numeric_interval(self, monkeypatch):
        monkeypatch.setenv("NETSCHOOL_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("CHECK_INTERVAL", "быстро")
        with pytest.raises(SettingsError, match="целое число"):
            load_settings()

    def test_inline_comment_in_value(self, monkeypatch):
        # Рукописные .env часто содержат "300  # комментарий".
        monkeypatch.setenv("NETSCHOOL_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("CHECK_INTERVAL", "600  # каждые 10 минут")
        assert load_settings().netschool.default_check_interval == 600

    def test_bad_boolean(self, monkeypatch):
        monkeypatch.setenv("NETSCHOOL_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("NETSCHOOL_WEB_ENABLED", "может быть")
        with pytest.raises(SettingsError, match="да/нет"):
            load_settings()


class TestProxyHosts:
    def test_default_keeps_volgograd(self, monkeypatch):
        monkeypatch.setenv("NETSCHOOL_BOT_TOKEN", "123:abc")
        settings = load_settings()
        assert settings.netschool.proxy_for("https://sgo.volganet.ru/x") is not None
        assert settings.netschool.proxy_for("https://sgo.example.ru") is None

    def test_explicit_list(self, monkeypatch):
        monkeypatch.setenv("NETSCHOOL_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("NETSCHOOL_PROXY_HOSTS", "a.ru=socks5://1:1080,b.ru=socks5://2:1080")
        settings = load_settings()
        assert settings.netschool.proxy_for("https://a.ru/x") == "socks5://1:1080"

    def test_empty_host_is_rejected(self, monkeypatch):
        monkeypatch.setenv("NETSCHOOL_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("NETSCHOOL_PROXY_HOSTS", "=socks5://1:1080")
        with pytest.raises(SettingsError, match="пустое имя хоста"):
            load_settings()


class TestUrls:
    def test_miniapp_url_is_composed(self, monkeypatch):
        monkeypatch.setenv("NETSCHOOL_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("NETSCHOOL_PUBLIC_URL", "https://example.ru/")
        monkeypatch.setenv("NETSCHOOL_MINIAPP_PATH", "mini/x/")
        settings = load_settings()
        # Лишние слэши с обеих сторон не должны давать "//" в ссылке.
        assert settings.web.miniapp_url == "https://example.ru/mini/x"
