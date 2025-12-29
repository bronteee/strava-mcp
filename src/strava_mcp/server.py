"""Strava MCP Server - Main server implementation."""

from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Any

import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from stravalib import Client

from .tokens import delete_tokens, is_token_expired, load_tokens, save_tokens

load_dotenv(override=True)

mcp = FastMCP("strava-mcp")

# OAuth server configuration
OAUTH_SERVER_HOST = "127.0.0.1"
OAUTH_SERVER_PORT = 5050


def get_client_id() -> int:
    """Get Strava client ID from environment, converting to int."""
    client_id = os.getenv("STRAVA_CLIENT_ID")
    if not client_id:
        raise ValueError("STRAVA_CLIENT_ID environment variable not set")
    return int(client_id)


def get_client_secret() -> str:
    """Get Strava client secret from environment."""
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    if not client_secret:
        raise ValueError("STRAVA_CLIENT_SECRET environment variable not set")
    return client_secret


def token_response_to_dict(token_response: Any) -> dict[str, Any]:
    """Convert stravalib token response to a dictionary for storage."""
    # stravalib returns AccessInfo which has dict-like access
    return {
        "access_token": token_response["access_token"],
        "refresh_token": token_response["refresh_token"],
        "expires_at": token_response["expires_at"],
    }


class OAuthServerManager:
    """Manages the OAuth server lifecycle."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._error: str | None = None

    def start(self) -> bool:
        """Start the FastAPI OAuth server in a background thread.

        Returns:
            True if server started successfully, False otherwise.
        """
        if self._thread is not None and self._thread.is_alive():
            return True  # Already running

        try:
            from .oauth import app

            config = uvicorn.Config(
                app,
                host=OAUTH_SERVER_HOST,
                port=OAUTH_SERVER_PORT,
                log_level="warning",
            )
            server = uvicorn.Server(config)

            self._thread = threading.Thread(target=server.run, daemon=True)
            self._thread.start()
            self._error = None
            return True
        except Exception as e:
            self._error = str(e)
            return False

    def is_running(self) -> bool:
        """Check if the OAuth server is running."""
        return self._thread is not None and self._thread.is_alive()

    def get_error(self) -> str | None:
        """Get the last error message if startup failed."""
        return self._error


_oauth_manager = OAuthServerManager()


def start_oauth_server() -> bool:
    """Start the OAuth server (convenience function).

    Returns:
        True if server started successfully, False otherwise.
    """
    return _oauth_manager.start()


def get_authenticated_client() -> Client:
    """Create an authenticated Strava client using stored tokens."""
    tokens = load_tokens()

    if not tokens or "refresh_token" not in tokens:
        raise ValueError(
            "Not authenticated. Use get_auth_url() to get the authorization URL, "
            "then authenticate() with the code from the callback."
        )

    client = Client()

    # Check if token is expired and refresh if needed
    if is_token_expired(tokens):
        token_response = client.refresh_access_token(
            client_id=get_client_id(),
            client_secret=get_client_secret(),
            refresh_token=tokens["refresh_token"],
        )
        # Save refreshed tokens
        tokens = token_response_to_dict(token_response)
        save_tokens(tokens)

    return Client(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_expires=tokens.get("expires_at"),
    )


# =============================================================================
# Authentication Tools
# =============================================================================


@mcp.tool()
async def get_auth_status() -> dict[str, Any]:
    """Check current Strava authentication status.

    Returns:
        Authentication status including whether tokens exist and expiry info.
    """
    tokens = load_tokens()

    if not tokens:
        return {
            "authenticated": False,
            "message": "No tokens found. Use get_auth_url() to start authentication.",
        }

    expires_at = tokens.get("expires_at", 0)
    is_expired = is_token_expired(tokens)

    return {
        "authenticated": True,
        "token_expires_at": (
            datetime.fromtimestamp(expires_at).isoformat() if expires_at else None
        ),
        "is_expired": is_expired,
        "message": (
            "Token expired, will auto-refresh on next API call."
            if is_expired
            else "Authenticated and ready."
        ),
    }


@mcp.tool()
async def get_auth_url(
    redirect_uri: str = "http://127.0.0.1:5050/strava-oauth",
) -> dict[str, Any]:
    """Get the Strava authorization URL to start OAuth flow.

    The OAuth callback server is running automatically at http://127.0.0.1:5050.
    After authorization, tokens will be saved automatically to the system keychain.

    Args:
        redirect_uri: The URL Strava should redirect to after authorization.
                      Default is http://127.0.0.1:5050/strava-oauth

    Returns:
        The authorization URL and instructions.
    """
    # Ensure OAuth server is running
    start_oauth_server()

    client = Client()
    url = client.authorization_url(
        client_id=get_client_id(),
        redirect_uri=redirect_uri,
        approval_prompt="auto",
        scope=["read", "activity:read", "activity:read_all", "profile:read_all"],
    )

    return {
        "auth_url": url,
        "oauth_server": f"http://{OAUTH_SERVER_HOST}:{OAUTH_SERVER_PORT}",
        "instructions": (
            "1. Open the auth_url in your browser\n"
            "2. Authorize the application on Strava\n"
            "3. Tokens will be saved automatically - no code copying needed!\n"
            "4. Return here and use get_activities() or other tools"
        ),
    }


@mcp.tool()
async def authenticate(code: str) -> dict[str, Any]:
    """Exchange authorization code for access tokens.

    Call this after the user has authorized the app and you have the code
    from the redirect URL.

    Args:
        code: The authorization code from Strava's OAuth redirect.

    Returns:
        Success status and athlete information.
    """
    client = Client()

    token_response = client.exchange_code_for_token(
        client_id=get_client_id(),
        client_secret=get_client_secret(),
        code=code,
    )

    # Convert to dict and save tokens securely to system keychain
    tokens = token_response_to_dict(token_response)
    save_tokens(tokens)

    # Get athlete info to confirm authentication worked
    authenticated_client = Client(access_token=tokens["access_token"])
    athlete = authenticated_client.get_athlete()

    return {
        "success": True,
        "message": f"Successfully authenticated as {athlete.firstname} {athlete.lastname}",
        "athlete_id": athlete.id,
        "expires_at": datetime.fromtimestamp(tokens["expires_at"]).isoformat(),
        "storage": "Tokens stored securely in system keychain",
    }


@mcp.tool()
async def logout() -> dict[str, Any]:
    """Remove stored Strava tokens from system keychain (logout).

    Returns:
        Confirmation message.
    """
    delete_tokens()
    return {
        "success": True,
        "message": "Logged out successfully. Tokens removed from keychain.",
    }


# =============================================================================
# Activity Tools
# =============================================================================


@mcp.tool()
async def get_activities(
    after: str | None = None,
    before: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Get recent Strava activities for the authenticated athlete.

    Args:
        after: Start date in YYYY-MM-DD format (e.g. '2025-12-01'). Only activities after this date.
        before: End date in YYYY-MM-DD format. Only activities before this date.
        limit: Maximum number of activities to return (default 10).

    Returns:
        List of activity summaries with key details.
    """
    client = get_authenticated_client()

    # Parse date strings to datetime if provided
    after_dt = datetime.fromisoformat(after) if after else None
    before_dt = datetime.fromisoformat(before) if before else None

    activities = client.get_activities(after=after_dt, before=before_dt, limit=limit)

    results = []
    for activity in activities:
        results.append(activity.model_dump())

    return results


@mcp.tool()
async def get_athlete() -> dict[str, Any]:
    """Get profile information for the authenticated Strava athlete.

    Returns:
        Athlete profile with name, stats, and other details.
    """
    client = get_authenticated_client()
    athlete = client.get_athlete()

    return athlete.model_dump()


@mcp.tool()
async def get_athlete_stats(athlete_id: int | None = None) -> dict[str, Any]:
    """Get statistics for the authenticated athlete or a specific athlete.

    Args:
        athlete_id: The Strava ID of the athlete. If None, returns stats for the authenticated athlete.

    Returns:
        Athlete statistics including recent (last 4 weeks), year-to-date, and all-time totals.
    """
    client = get_authenticated_client()
    stats = client.get_athlete_stats(athlete_id=athlete_id)

    return stats.model_dump()


@mcp.tool()
async def get_activity_details(activity_id: int) -> dict[str, Any]:
    """Get detailed information about a specific Strava activity.

    Args:
        activity_id: The unique ID of the activity.

    Returns:
        Detailed activity information including description, gear, and splits.
    """
    client = get_authenticated_client()
    activity = client.get_activity(activity_id)

    return activity.model_dump()


def main() -> None:
    """Main entry point for the MCP server."""
    # Try to start OAuth server when MCP server loads (non-blocking on failure)
    try:
        start_oauth_server()
    except Exception:
        pass  # OAuth server is optional - manual auth still works

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
