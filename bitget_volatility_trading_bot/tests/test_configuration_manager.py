"""Tests for configuration_manager.py using temporary YAML files."""
import pytest
import yaml

from configuration_manager import (
    ConfigurationManager,
    ConfigurationError,
    ConfigurationFileNotFoundError,
    ConfigurationLoadError,
    CredentialsFileNotFoundError,
    IncompleteCredentialsError,
)


@pytest.fixture
def config_file(tmp_path):
    data = {
        "trading_options": {
            "PAIR_WITH": "USDT",
            "TRADE_TOTAL": 500,
            "TRADE_SLOTS": 10,
            "STOP_LOSS": 5.0,
            "TAKE_PROFIT": 5.0,
            "TRAILING_STOP_LOSS": 2.0,
        },
        "script_options": {"TEST_MODE": True, "UTA_MODE": True},
        "data_options": {"DB_TRANSACTIONS_FILE_NAME": "test.db"},
    }
    f = tmp_path / "config.yml"
    f.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(f)


@pytest.fixture
def creds_file(tmp_path):
    data = {
        "api_key": " bg_testkey ",
        "api_secret": " secret123 ",
        "api_passphrase": " mypass ",
        "telegram": {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "TELEGRAM_CHAT_ID": "-100",
        },
    }
    f = tmp_path / "creds.yml"
    f.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(f)


@pytest.fixture
def manager(config_file, creds_file):
    return ConfigurationManager(config_file, creds_file)


class TestFileLoading:
    def test_missing_config_file_raises(self, tmp_path, creds_file):
        with pytest.raises(ConfigurationFileNotFoundError):
            ConfigurationManager(str(tmp_path / "nope.yml"), creds_file)

    def test_missing_creds_file_raises(self, config_file, tmp_path):
        with pytest.raises(CredentialsFileNotFoundError):
            ConfigurationManager(config_file, str(tmp_path / "nope.yml"))

    def test_invalid_yaml_raises_load_error(self, tmp_path, creds_file):
        bad = tmp_path / "bad.yml"
        bad.write_text("key: [unclosed", encoding="utf-8")
        with pytest.raises(ConfigurationLoadError):
            ConfigurationManager(str(bad), creds_file)

    def test_empty_config_raises_load_error(self, tmp_path, creds_file):
        empty = tmp_path / "empty.yml"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ConfigurationLoadError):
            ConfigurationManager(str(empty), creds_file)


class TestApiCredentials:
    def test_returns_three_values_stripped(self, manager):
        key, secret, passphrase = manager.get_api_credentials()
        assert (key, secret, passphrase) == ("bg_testkey", "secret123", "mypass")

    def test_missing_passphrase_raises(self, config_file, tmp_path):
        creds = tmp_path / "creds.yml"
        creds.write_text(
            yaml.safe_dump({"api_key": "k", "api_secret": "s"}), encoding="utf-8"
        )
        cm = ConfigurationManager(config_file, str(creds))
        with pytest.raises(IncompleteCredentialsError, match="api_passphrase"):
            cm.get_api_credentials()

    def test_blank_values_raise(self, config_file, tmp_path):
        creds = tmp_path / "creds.yml"
        creds.write_text(
            yaml.safe_dump(
                {"api_key": "  ", "api_secret": "s", "api_passphrase": "p"}
            ),
            encoding="utf-8",
        )
        cm = ConfigurationManager(config_file, str(creds))
        with pytest.raises(IncompleteCredentialsError):
            cm.get_api_credentials()


class TestTelegramCredentials:
    def test_returns_token_and_chat_id(self, manager):
        token, chat_id = manager.get_telegram_credentials()
        assert token == "123:abc"
        assert chat_id == "-100"

    def test_missing_telegram_section_raises(self, config_file, tmp_path):
        creds = tmp_path / "creds.yml"
        creds.write_text(
            yaml.safe_dump(
                {"api_key": "k", "api_secret": "s", "api_passphrase": "p"}
            ),
            encoding="utf-8",
        )
        cm = ConfigurationManager(config_file, str(creds))
        with pytest.raises(IncompleteCredentialsError):
            cm.get_telegram_credentials()


class TestConfigAccess:
    def test_get_trading_config(self, manager):
        config = manager.get_trading_config()
        assert config["PAIR_WITH"] == "USDT"
        assert config["TRADE_SLOTS"] == 10

    def test_missing_trading_options_raises(self, tmp_path, creds_file):
        cfg = tmp_path / "config.yml"
        cfg.write_text(yaml.safe_dump({"script_options": {}}), encoding="utf-8")
        cm = ConfigurationManager(str(cfg), creds_file)
        with pytest.raises(ConfigurationError, match="trading_options"):
            cm.get_trading_config()

    def test_validate_configuration_ok(self, manager):
        assert manager.validate_configuration() is True

    def test_validate_configuration_missing_params(self, tmp_path, creds_file):
        cfg = tmp_path / "config.yml"
        cfg.write_text(
            yaml.safe_dump({"trading_options": {"PAIR_WITH": "USDT"}}),
            encoding="utf-8",
        )
        cm = ConfigurationManager(str(cfg), creds_file)
        with pytest.raises(ConfigurationError, match="Missing required"):
            cm.validate_configuration()

    def test_get_script_option_with_default(self, manager):
        assert manager.get_script_option("TEST_MODE") is True
        assert manager.get_script_option("NONEXISTENT", "fallback") == "fallback"

    def test_set_take_profit_persists(self, manager, config_file):
        manager.set_take_profit(7.5)
        with open(config_file, encoding="utf-8") as f:
            reloaded = yaml.safe_load(f)
        assert reloaded["trading_options"]["TAKE_PROFIT"] == 7.5

    def test_set_stop_loss_persists(self, manager, config_file):
        manager.set_stop_loss(3.0)
        with open(config_file, encoding="utf-8") as f:
            reloaded = yaml.safe_load(f)
        assert reloaded["trading_options"]["STOP_LOSS"] == 3.0
