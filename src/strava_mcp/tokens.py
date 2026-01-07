"""Token management and shared configuration for Strava MCP server.

Stores tokens in memory only. Tokens are lost when the MCP server restarts,
requiring re-authentication each Claude Desktop session.

Thread-safe: All operations are protected by a lock since the OAuth server
runs in a separate thread from the MCP server.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Any, TypedDict


class TokenDict(TypedDict):
    """Type-safe dictionary for Strava OAuth tokens."""

    access_token: str
    refresh_token: str
    expires_at: float


# Thread-safe in-memory token storage
_tokens: TokenDict | None = None
_lock = threading.Lock()


# =============================================================================
# Shared Configuration Functions
# =============================================================================


def get_client_id() -> int:
    """Get Strava client ID from environment, converting to int."""
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    if not client_id:
        raise ValueError("STRAVA_CLIENT_ID environment variable not set")
    return int(client_id)


def get_client_secret() -> str:
    """Get Strava client secret from environment."""
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    if not client_secret:
        raise ValueError("STRAVA_CLIENT_SECRET environment variable not set")
    return client_secret


def has_credentials() -> bool:
    """Check if Strava credentials are configured."""
    return bool(
        os.environ.get("STRAVA_CLIENT_ID") and os.environ.get("STRAVA_CLIENT_SECRET")
    )


def token_response_to_dict(token_response: Any) -> TokenDict:
    """Convert stravalib token response to a dictionary for storage."""
    return {
        "access_token": token_response["access_token"],
        "refresh_token": token_response["refresh_token"],
        "expires_at": token_response["expires_at"],
    }


# =============================================================================
# Token Storage Functions
# =============================================================================


def load_tokens() -> TokenDict | None:
    """Load tokens from memory (thread-safe).

    Returns:
        A copy of the token dictionary, or None if not set.
        Returns a copy to prevent external mutation of internal state.
    """
    with _lock:
        return dict(_tokens) if _tokens else None  # type: ignore[return-value]


def save_tokens(tokens: TokenDict) -> None:
    """Save tokens to memory (thread-safe).

    Args:
        tokens: Token dictionary with access_token, refresh_token, expires_at.
    """
    global _tokens
    with _lock:
        _tokens = dict(tokens)  # type: ignore[assignment]


def delete_tokens() -> None:
    """Clear tokens from memory (thread-safe)."""
    global _tokens
    with _lock:
        _tokens = None


def is_token_expired(tokens: TokenDict) -> bool:
    """Check if the access token is expired.

    Args:
        tokens: Token dictionary with expires_at timestamp.

    Returns:
        True if token is expired, False otherwise.
    """
    return tokens["expires_at"] < datetime.now().timestamp()
