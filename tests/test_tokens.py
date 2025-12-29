"""Tests for token management."""

import json
from datetime import datetime, timedelta

from strava_mcp.tokens import (
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    delete_tokens,
    is_token_expired,
    load_tokens,
    save_tokens,
)


class TestLoadTokens:
    """Tests for load_tokens function."""

    def test_load_tokens_returns_none_when_no_tokens(self, mock_keyring):
        """Should return None when no tokens are stored."""
        result = load_tokens()
        assert result is None

    def test_load_tokens_returns_stored_tokens(self, mock_keyring, valid_tokens):
        """Should return tokens when they exist in keyring."""
        # Store tokens first
        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            valid_tokens
        )

        result = load_tokens()

        assert result is not None
        assert result["access_token"] == valid_tokens["access_token"]
        assert result["refresh_token"] == valid_tokens["refresh_token"]

    def test_load_tokens_parses_json_correctly(self, mock_keyring):
        """Should correctly parse JSON from keyring."""
        tokens = {"access_token": "abc", "refresh_token": "xyz", "expires_at": 12345}
        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            tokens
        )

        result = load_tokens()

        assert result == tokens


class TestSaveTokens:
    """Tests for save_tokens function."""

    def test_save_tokens_stores_in_keyring(self, mock_keyring, valid_tokens):
        """Should store tokens in keyring."""
        save_tokens(valid_tokens)

        stored = mock_keyring._storage.get(f"{KEYRING_SERVICE}:{KEYRING_USERNAME}")
        assert stored is not None
        assert json.loads(stored) == valid_tokens

    def test_save_tokens_overwrites_existing(self, mock_keyring, valid_tokens):
        """Should overwrite existing tokens."""
        # Store initial tokens
        save_tokens({"access_token": "old", "refresh_token": "old"})

        # Overwrite with new tokens
        save_tokens(valid_tokens)

        stored = json.loads(
            mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"]
        )
        assert stored["access_token"] == valid_tokens["access_token"]

    def test_save_tokens_serializes_as_json(self, mock_keyring):
        """Should serialize tokens as valid JSON."""
        tokens = {"access_token": "test", "nested": {"key": "value"}}
        save_tokens(tokens)

        stored = mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"]
        # Should be valid JSON
        parsed = json.loads(stored)
        assert parsed == tokens


class TestDeleteTokens:
    """Tests for delete_tokens function."""

    def test_delete_tokens_removes_from_keyring(self, mock_keyring, valid_tokens):
        """Should remove tokens from keyring."""
        # Store tokens first
        save_tokens(valid_tokens)
        assert f"{KEYRING_SERVICE}:{KEYRING_USERNAME}" in mock_keyring._storage

        # Delete tokens
        delete_tokens()

        assert f"{KEYRING_SERVICE}:{KEYRING_USERNAME}" not in mock_keyring._storage

    def test_delete_tokens_handles_missing_tokens(self, mock_keyring):
        """Should not raise error when no tokens exist."""
        # Should not raise
        delete_tokens()


class TestIsTokenExpired:
    """Tests for is_token_expired function."""

    def test_expired_token_returns_true(self):
        """Should return True for expired tokens."""
        tokens = {"expires_at": (datetime.now() - timedelta(hours=1)).timestamp()}
        assert is_token_expired(tokens) is True

    def test_valid_token_returns_false(self):
        """Should return False for valid tokens."""
        tokens = {"expires_at": (datetime.now() + timedelta(hours=1)).timestamp()}
        assert is_token_expired(tokens) is False

    def test_missing_expires_at_returns_true(self):
        """Should return True when expires_at is missing (treats as expired)."""
        tokens = {"access_token": "test"}
        assert is_token_expired(tokens) is True

    def test_zero_expires_at_returns_true(self):
        """Should return True when expires_at is 0."""
        tokens = {"expires_at": 0}
        assert is_token_expired(tokens) is True

    def test_just_expired_returns_true(self):
        """Should return True when token just expired."""
        tokens = {"expires_at": datetime.now().timestamp() - 1}
        assert is_token_expired(tokens) is True

    def test_about_to_expire_returns_false(self):
        """Should return False when token is about to expire but hasn't yet."""
        tokens = {"expires_at": datetime.now().timestamp() + 1}
        assert is_token_expired(tokens) is False
