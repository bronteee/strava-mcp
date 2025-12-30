"""Token management for Strava MCP server.

Stores tokens in memory only. Tokens are lost when the MCP server restarts,
requiring re-authentication each Claude Desktop session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# In-memory token storage
_tokens: dict[str, Any] | None = None


def load_tokens() -> dict[str, Any] | None:
    """Load tokens from memory.

    Returns:
        Token dictionary with access_token, refresh_token, expires_at, or None if not set.
    """
    return _tokens


def save_tokens(tokens: dict[str, Any]) -> None:
    """Save tokens to memory.

    Args:
        tokens: Token dictionary with access_token, refresh_token, expires_at.
    """
    global _tokens
    _tokens = tokens


def delete_tokens() -> None:
    """Clear tokens from memory."""
    global _tokens
    _tokens = None


def is_token_expired(tokens: dict[str, Any]) -> bool:
    """Check if the access token is expired.

    Args:
        tokens: Token dictionary with expires_at timestamp.

    Returns:
        True if token is expired, False otherwise.
    """
    expires_at = tokens.get("expires_at", 0)
    return expires_at < datetime.now().timestamp()
