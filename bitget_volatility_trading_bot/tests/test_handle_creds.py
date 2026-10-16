"""Tests for helpers/handle_creds.py."""
from unittest.mock import MagicMock

import pytest

from helpers.handle_creds import (
    test_api_key as check_api_key,
    load_correct_creds,
    load_discord_creds,
)
from helpers.bitget_client import (
    BitgetAPIException,
    ERR_AUTH,
    ERR_TIMESTAMP,
)


class TestApiKey:
    def test_valid_key_returns_true(self):
        client = MagicMock()
        ok, msg = check_api_key(client, BitgetAPIException)
        assert ok is True
        assert "validated" in msg

    def test_auth_error_mentions_credentials_and_ip(self):
        client = MagicMock()
        client.get_account.side_effect = BitgetAPIException("bad key", code=ERR_AUTH)
        ok, msg = check_api_key(client, BitgetAPIException)
        assert ok is False
        assert "passphrase" in msg
        assert "IP whitelist" in msg

    def test_timestamp_error_suggests_ntp(self):
        client = MagicMock()
        client.get_account.side_effect = BitgetAPIException(
            "ts", code=ERR_TIMESTAMP
        )
        ok, msg = check_api_key(client, BitgetAPIException)
        assert ok is False
        assert "ntp" in msg.lower()

    def test_unknown_error_reported(self):
        client = MagicMock()
        client.get_account.side_effect = BitgetAPIException("x", code="OTHER")
        ok, msg = check_api_key(client, BitgetAPIException)
        assert ok is False

    def test_non_api_exception_caught_as_fallback(self):
        client = MagicMock()
        client.get_account.side_effect = ValueError("boom")
        ok, msg = check_api_key(client, BitgetAPIException)
        assert ok is False
        assert "Fallback" in msg


class TestLegacyCredLoaders:
    def test_load_correct_creds(self):
        creds = {"prod": {"access_key": "a", "secret_key": "s"}}
        assert load_correct_creds(creds) == ("a", "s")

    def test_malformed_creds_exits(self):
        with pytest.raises(SystemExit):
            load_correct_creds(None)

    def test_load_discord_creds(self):
        creds = {"discord": {"DISCORD_WEBHOOK": "https://hook"}}
        assert load_discord_creds(creds) == "https://hook"
