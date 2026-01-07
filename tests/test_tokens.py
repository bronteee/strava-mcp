"""Tests for token management."""

from datetime import datetime, timedelta

import pytest

from strava_mcp.tokens import (
    delete_tokens,
    is_token_expired,
    load_tokens,
    save_tokens,
)


@pytest.fixture
def valid_tokens():
    """Return valid (non-expired) tokens."""
    return {
        "access_token": "test_access_token_12345",
        "refresh_token": "test_refresh_token_67890",
        "expires_at": (datetime.now() + timedelta(hours=6)).timestamp(),
    }


class TestLoadTokens:
    """Tests for load_tokens function."""

    def test_load_tokens_returns_none_when_no_tokens(self):
        """Should return None when no tokens are stored."""
        result = load_tokens()
        assert result is None

    def test_load_tokens_returns_stored_tokens(self, valid_tokens):
        """Should return tokens when they exist."""
        save_tokens(valid_tokens)
        result = load_tokens()

        assert result is not None
        assert result["access_token"] == valid_tokens["access_token"]
        assert result["refresh_token"] == valid_tokens["refresh_token"]


class TestSaveTokens:
    """Tests for save_tokens function."""

    def test_save_tokens_stores_tokens(self, valid_tokens):
        """Should store tokens in memory."""
        save_tokens(valid_tokens)

        result = load_tokens()
        assert result == valid_tokens

    def test_save_tokens_overwrites_existing(self, valid_tokens):
        """Should overwrite existing tokens."""
        save_tokens({"access_token": "old", "refresh_token": "old"})
        save_tokens(valid_tokens)

        result = load_tokens()
        assert result["access_token"] == valid_tokens["access_token"]


class TestDeleteTokens:
    """Tests for delete_tokens function."""

    def test_delete_tokens_clears_tokens(self, valid_tokens):
        """Should clear tokens from memory."""
        save_tokens(valid_tokens)
        delete_tokens()

        assert load_tokens() is None

    def test_delete_tokens_handles_no_tokens(self):
        """Should not raise error when no tokens exist."""
        delete_tokens()  # Should not raise


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

    def test_zero_expires_at_returns_true(self):
        """Should return True when expires_at is 0."""
        tokens = {"expires_at": 0}
        assert is_token_expired(tokens) is True
