"""Token management for Strava MCP server."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import keyring
import keyring.errors

# Keyring service name for secure token storage
KEYRING_SERVICE = "strava-mcp-server"
KEYRING_USERNAME = "strava_tokens"


def load_tokens() -> dict[str, Any] | None:
    """Load saved tokens from system keychain.

    Returns:
        Token dictionary with access_token, refresh_token, expires_at, or None if not found.
    """
    tokens_json = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    if tokens_json:
        return json.loads(tokens_json)
    return None


def save_tokens(tokens: dict[str, Any]) -> None:
    """Save tokens to system keychain.

    Args:
        tokens: Token dictionary with access_token, refresh_token, expires_at.
    """
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps(tokens))


def delete_tokens() -> None:
    """Delete tokens from system keychain."""
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass  # Token doesn't exist, nothing to delete


def is_token_expired(tokens: dict[str, Any]) -> bool:
    """Check if the access token is expired.

    Args:
        tokens: Token dictionary with expires_at timestamp.

    Returns:
        True if token is expired, False otherwise.
    """
    expires_at = tokens.get("expires_at", 0)
    return expires_at < datetime.now().timestamp()
