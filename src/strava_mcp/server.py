"""Strava MCP Server - Main server implementation."""

from __future__ import annotations

import asyncio
import functools
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

import requests
import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from stravalib import Client

from .tokens import (
    TokenDict,
    delete_tokens,
    get_client_id,
    get_client_secret,
    is_token_expired,
    load_tokens,
    save_tokens,
    token_response_to_dict,
)

T = TypeVar("T")

load_dotenv(override=True)

mcp = FastMCP("strava-mcp")

# OAuth server configuration
OAUTH_SERVER_HOST = "127.0.0.1"
OAUTH_SERVER_PORT = 5050


class OAuthServerManager:
    """Manages the OAuth server lifecycle."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None

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
            return True
        except Exception:
            return False


_oauth_manager = OAuthServerManager()


def start_oauth_server() -> bool:
    """Start the OAuth server (convenience function).

    Returns:
        True if server started successfully, False otherwise.
    """
    return _oauth_manager.start()


# Lock for atomic token refresh to prevent concurrent refresh attempts
_refresh_lock = threading.Lock()


def get_authenticated_client() -> Client:
    """Create an authenticated Strava client using stored tokens.

    Thread-safe: Uses a lock to prevent concurrent token refresh attempts,
    which could cause race conditions with the refresh token.
    """
    with _refresh_lock:
        tokens = load_tokens()

        if not tokens or "refresh_token" not in tokens:
            raise ValueError(
                "Not authenticated. Use get_auth_url() to get the authorization URL, "
                "then authenticate() with the code from the callback."
            )

        # Check if token is expired and refresh if needed
        if is_token_expired(tokens):
            client = Client()
            token_response = client.refresh_access_token(
                client_id=get_client_id(),
                client_secret=get_client_secret(),
                refresh_token=tokens["refresh_token"],
            )
            # Save refreshed tokens
            tokens = token_response_to_dict(token_response)
            save_tokens(tokens)

    # Return client outside the lock (using the refreshed tokens)
    return Client(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_expires=tokens.get("expires_at"),
    )


# =============================================================================
# Error Handling
# =============================================================================


def handle_strava_errors(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to handle Strava API errors gracefully.

    Catches common exceptions and returns structured error responses
    instead of crashing the MCP session.
    """

    @functools.wraps(func)
    async def wrapper(
        *args: Any, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]]:
        try:
            return await func(*args, **kwargs)
        except ValueError as e:
            # Authentication or validation errors
            return {
                "error": "validation_error",
                "message": str(e),
                "action": "Check authentication status with get_auth_status()",
            }
        except requests.exceptions.HTTPError as e:
            if e.response is not None:
                status_code = e.response.status_code
                if status_code == 429:
                    return {
                        "error": "rate_limited",
                        "message": "Strava API rate limit exceeded",
                        "action": "Wait 15 minutes before retrying",
                        "retry_after_seconds": 900,
                    }
                elif status_code == 401:
                    return {
                        "error": "unauthorized",
                        "message": "Access token invalid or revoked",
                        "action": "Re-authenticate using get_auth_url()",
                    }
                elif status_code == 404:
                    return {
                        "error": "not_found",
                        "message": "Resource not found",
                        "action": "Verify the ID exists and you have access",
                    }
                elif status_code == 403:
                    return {
                        "error": "forbidden",
                        "message": "Access denied to this resource",
                        "action": "Check if you have permission to access this data",
                    }
            return {
                "error": "api_error",
                "message": str(e),
                "status_code": e.response.status_code if e.response else None,
            }
        except requests.exceptions.ConnectionError:
            return {
                "error": "network_error",
                "message": "Unable to connect to Strava API",
                "action": "Check your internet connection",
            }
        except requests.exceptions.Timeout:
            return {
                "error": "timeout",
                "message": "Strava API request timed out",
                "action": "Try again in a moment",
            }
        except Exception as e:
            # Catch-all for unexpected errors
            return {
                "error": "unexpected_error",
                "message": str(e),
                "type": type(e).__name__,
            }

    return wrapper


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


def _build_auth_url(redirect_uri: str) -> str:
    """Build Strava authorization URL (sync helper for asyncio.to_thread)."""
    client = Client()
    return client.authorization_url(
        client_id=get_client_id(),
        redirect_uri=redirect_uri,
        approval_prompt="auto",
        scope=["read", "activity:read", "activity:read_all", "profile:read_all"],
    )


@mcp.tool()
async def get_auth_url(
    redirect_uri: str = "http://127.0.0.1:5050/strava-oauth",
) -> dict[str, Any]:
    """Get the Strava authorization URL to start OAuth flow.

    The OAuth callback server is running automatically at http://127.0.0.1:5050.
    After authorization, tokens will be saved automatically in memory.

    Args:
        redirect_uri: The URL Strava should redirect to after authorization.
                      Default is http://127.0.0.1:5050/strava-oauth

    Returns:
        The authorization URL and instructions.
    """
    # Ensure OAuth server is running
    start_oauth_server()

    url = await asyncio.to_thread(_build_auth_url, redirect_uri)

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


def _exchange_and_get_athlete(code: str) -> tuple[TokenDict, Any]:
    """Exchange auth code for tokens and get athlete (sync helper)."""
    client = Client()
    token_response = client.exchange_code_for_token(
        client_id=get_client_id(),
        client_secret=get_client_secret(),
        code=code,
    )
    tokens = token_response_to_dict(token_response)
    save_tokens(tokens)

    authenticated_client = Client(access_token=tokens["access_token"])
    athlete = authenticated_client.get_athlete()
    return tokens, athlete


@mcp.tool()
@handle_strava_errors
async def authenticate(code: str) -> dict[str, Any]:
    """Exchange authorization code for access tokens.

    Call this after the user has authorized the app and you have the code
    from the redirect URL.

    Args:
        code: The authorization code from Strava's OAuth redirect.

    Returns:
        Success status and athlete information.
    """
    if not code or not code.strip():
        return {
            "error": "validation_error",
            "message": "Authorization code cannot be empty",
            "action": "Get a new authorization code from get_auth_url()",
        }

    tokens, athlete = await asyncio.to_thread(_exchange_and_get_athlete, code)

    return {
        "success": True,
        "message": f"Successfully authenticated as {athlete.firstname} {athlete.lastname}",
        "athlete_id": athlete.id,
        "expires_at": datetime.fromtimestamp(tokens["expires_at"]).isoformat(),
    }


@mcp.tool()
async def logout() -> dict[str, Any]:
    """Remove stored Strava tokens (logout).

    Returns:
        Confirmation message.
    """
    delete_tokens()
    return {
        "success": True,
        "message": "Logged out successfully. Tokens cleared.",
    }


# =============================================================================
# Activity Tools
# =============================================================================


def _fetch_activities(
    after_dt: datetime | None, before_dt: datetime | None, limit: int
) -> list[dict[str, Any]]:
    """Fetch activities from Strava (sync helper)."""
    client = get_authenticated_client()
    activities = client.get_activities(after=after_dt, before=before_dt, limit=limit)
    return [activity.model_dump() for activity in activities]


@mcp.tool()
@handle_strava_errors
async def get_activities(
    after: str | None = None,
    before: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Get recent Strava activities for the authenticated athlete.

    Args:
        after: Start date in YYYY-MM-DD format (e.g. '2025-12-01'). Only activities after this date.
        before: End date in YYYY-MM-DD format. Only activities before this date.
        limit: Maximum number of activities to return (default 10, max 200).

    Returns:
        List of activity summaries with key details.
    """
    # Validate limit
    if limit < 1:
        return {"error": "validation_error", "message": "limit must be at least 1"}
    limit = min(limit, 200)  # Cap at Strava's maximum

    # Validate and parse dates
    after_dt = None
    if after:
        try:
            after_dt = datetime.fromisoformat(after)
        except ValueError:
            return {
                "error": "validation_error",
                "message": f"Invalid date format '{after}'. Use ISO format: YYYY-MM-DD",
            }

    before_dt = None
    if before:
        try:
            before_dt = datetime.fromisoformat(before)
        except ValueError:
            return {
                "error": "validation_error",
                "message": f"Invalid date format '{before}'. Use ISO format: YYYY-MM-DD",
            }

    return await asyncio.to_thread(_fetch_activities, after_dt, before_dt, limit)


def _fetch_athlete() -> dict[str, Any]:
    """Fetch athlete profile from Strava (sync helper)."""
    client = get_authenticated_client()
    return client.get_athlete().model_dump()


@mcp.tool()
@handle_strava_errors
async def get_athlete() -> dict[str, Any]:
    """Get profile information for the authenticated Strava athlete.

    Returns:
        Athlete profile with name, stats, and other details.
    """
    return await asyncio.to_thread(_fetch_athlete)


def _fetch_athlete_stats(athlete_id: int | None) -> dict[str, Any]:
    """Fetch athlete stats from Strava (sync helper)."""
    client = get_authenticated_client()
    return client.get_athlete_stats(athlete_id=athlete_id).model_dump()


@mcp.tool()
@handle_strava_errors
async def get_athlete_stats(athlete_id: int | None = None) -> dict[str, Any]:
    """Get statistics for the authenticated athlete or a specific athlete.

    Args:
        athlete_id: The Strava ID of the athlete. If None, returns stats for the authenticated athlete.

    Returns:
        Athlete statistics including recent (last 4 weeks), year-to-date, and all-time totals.
    """
    if athlete_id is not None and athlete_id < 1:
        return {
            "error": "validation_error",
            "message": "athlete_id must be a positive integer",
        }

    return await asyncio.to_thread(_fetch_athlete_stats, athlete_id)


def _fetch_activity_details(activity_id: int) -> dict[str, Any]:
    """Fetch activity details from Strava (sync helper)."""
    client = get_authenticated_client()
    return client.get_activity(activity_id).model_dump()


@mcp.tool()
@handle_strava_errors
async def get_activity_details(activity_id: int) -> dict[str, Any]:
    """Get detailed information about a specific Strava activity.

    Args:
        activity_id: The unique ID of the activity.

    Returns:
        Detailed activity information including description, gear, and splits.
    """
    if activity_id < 1:
        return {
            "error": "validation_error",
            "message": "activity_id must be a positive integer",
        }

    return await asyncio.to_thread(_fetch_activity_details, activity_id)


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
