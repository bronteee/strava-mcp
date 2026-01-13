"""Strava MCP Server - Main server implementation."""

from __future__ import annotations

import asyncio
import functools
import math
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, ParamSpec

import requests
import uvicorn
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
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

P = ParamSpec("P")

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
        token_expires=int(tokens["expires_at"]),
    )


# =============================================================================
# Error Handling
# =============================================================================


def handle_strava_errors(
    func: Callable[P, Awaitable[dict[str, Any] | list[dict[str, Any]]]],
) -> Callable[P, Awaitable[dict[str, Any] | list[dict[str, Any]]]]:
    """Decorator to handle Strava API errors gracefully.

    Catches common exceptions and returns structured error responses
    instead of crashing the MCP session.
    """

    @functools.wraps(func)
    async def wrapper(
        *args: P.args, **kwargs: P.kwargs
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


# =============================================================================
# Geocoding Tools
# =============================================================================

# Nominatim geocoder (uses OpenStreetMap - free, no API key required)
_geocoder = Nominatim(user_agent="strava-mcp/1.0")


def _geocode_location(query: str, radius_km: float) -> dict[str, Any]:
    """Geocode a location and return bounds (sync helper)."""
    location = _geocoder.geocode(query, exactly_one=True)

    if not location:
        raise ValueError(f"Could not find location: {query}")

    lat, lng = location.latitude, location.longitude

    # Calculate bounds from center point and radius
    # Rough approximation: 1 degree latitude ≈ 111km
    # 1 degree longitude ≈ 111km * cos(latitude)
    lat_offset = radius_km / 111.0
    lng_offset = radius_km / (111.0 * math.cos(math.radians(lat)))

    return {
        "query": query,
        "location": {
            "name": location.address,
            "latitude": lat,
            "longitude": lng,
        },
        "bounds": {
            "sw_lat": lat - lat_offset,
            "sw_lng": lng - lng_offset,
            "ne_lat": lat + lat_offset,
            "ne_lng": lng + lng_offset,
        },
        "radius_km": radius_km,
    }


@mcp.tool()
@handle_strava_errors
async def geocode_location(
    query: str,
    radius_km: float = 5.0,
) -> dict[str, Any]:
    """Convert a location name to geographic bounds for segment search.

    Args:
        query: Location name (e.g., "Central Park, NYC", "Golden Gate Park, SF").
        radius_km: Search radius in kilometers from center (default 5.0).

    Returns:
        Location details and bounding box coordinates for use with explore_running_segments.
    """
    if not query or not query.strip():
        return {"error": "validation_error", "message": "Query cannot be empty"}

    if radius_km <= 0:
        return {
            "error": "validation_error",
            "message": "radius_km must be positive",
        }

    if radius_km > 50:
        return {
            "error": "validation_error",
            "message": "radius_km must be <= 50km to avoid too large search areas",
        }

    return await asyncio.to_thread(_geocode_location, query.strip(), radius_km)


# =============================================================================
# Segment Tools
# =============================================================================

STRAVA_SEGMENT_WEB_URL = "https://www.strava.com/segments"
STRAVA_SEGMENT_APP_URL = "strava://segments"


def _explore_segments(
    bounds: tuple[float, float, float, float],
    activity_type: str,
    min_cat: int | None,
    max_cat: int | None,
) -> list[dict[str, Any]]:
    """Explore segments in an area (sync helper)."""
    client = get_authenticated_client()
    segments = client.explore_segments(
        bounds=bounds,
        activity_type=activity_type,
        min_cat=min_cat,
        max_cat=max_cat,
    )

    results = []
    for seg in segments:
        segment_data = {
            "id": seg.id,
            "name": seg.name,
            "climb_category": seg.climb_category,
            "avg_grade": seg.avg_grade,
            "start_latlng": list(seg.start_latlng) if seg.start_latlng else None,
            "end_latlng": list(seg.end_latlng) if seg.end_latlng else None,
            "elev_difference": seg.elev_difference,
            "distance": seg.distance,
            "links": {
                "web": f"{STRAVA_SEGMENT_WEB_URL}/{seg.id}",
                "app": f"{STRAVA_SEGMENT_APP_URL}/{seg.id}",
            },
        }
        results.append(segment_data)

    return results


@mcp.tool()
@handle_strava_errors
async def explore_running_segments(
    location: str | None = None,
    bounds: list[float] | None = None,
    radius_km: float = 5.0,
    min_cat: int | None = None,
    max_cat: int | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Search for running segments in an area.

    Provide either a location name OR bounds coordinates.

    Args:
        location: Location name (e.g., "Central Park, NYC"). Will be geocoded automatically.
        bounds: Bounding box as [sw_lat, sw_lng, ne_lat, ne_lng]. Use instead of location.
        radius_km: Search radius in km when using location (default 5.0, max 50).
        min_cat: Minimum climb category filter (0-5, where 0 is hardest).
        max_cat: Maximum climb category filter (0-5).

    Returns:
        List of up to 10 running segments with details and deeplinks.
    """
    # Validate inputs
    if not location and not bounds:
        return {
            "error": "validation_error",
            "message": "Provide either 'location' or 'bounds'",
        }

    if location and bounds:
        return {
            "error": "validation_error",
            "message": "Provide either 'location' or 'bounds', not both",
        }

    # Get bounds from location if needed
    if location:
        geo_result = await geocode_location(location, radius_km)
        if "error" in geo_result:
            return geo_result
        bounds_dict = geo_result["bounds"]
        bounds_tuple = (
            bounds_dict["sw_lat"],
            bounds_dict["sw_lng"],
            bounds_dict["ne_lat"],
            bounds_dict["ne_lng"],
        )
        location_info = geo_result["location"]
    else:
        if not bounds or len(bounds) != 4:
            return {
                "error": "validation_error",
                "message": "bounds must be [sw_lat, sw_lng, ne_lat, ne_lng]",
            }
        bounds_tuple = (bounds[0], bounds[1], bounds[2], bounds[3])
        location_info = None

    # Validate climb categories
    if min_cat is not None and (min_cat < 0 or min_cat > 5):
        return {
            "error": "validation_error",
            "message": "min_cat must be between 0 and 5",
        }
    if max_cat is not None and (max_cat < 0 or max_cat > 5):
        return {
            "error": "validation_error",
            "message": "max_cat must be between 0 and 5",
        }

    segments = await asyncio.to_thread(
        _explore_segments, bounds_tuple, "running", min_cat, max_cat
    )

    result: dict[str, Any] = {
        "count": len(segments),
        "segments": segments,
    }
    if location_info:
        result["searched_location"] = location_info

    return result


def _fetch_segment(segment_id: int) -> dict[str, Any]:
    """Fetch segment details (sync helper)."""
    client = get_authenticated_client()
    segment = client.get_segment(segment_id)

    return {
        "id": segment.id,
        "name": segment.name,
        "activity_type": segment.activity_type,
        "distance": segment.distance,
        "average_grade": segment.average_grade,
        "maximum_grade": segment.maximum_grade,
        "elevation_high": segment.elevation_high,
        "elevation_low": segment.elevation_low,
        "total_elevation_gain": segment.total_elevation_gain,
        "climb_category": segment.climb_category,
        "city": segment.city,
        "state": segment.state,
        "country": segment.country,
        "start_latlng": list(segment.start_latlng) if segment.start_latlng else None,
        "end_latlng": list(segment.end_latlng) if segment.end_latlng else None,
        "effort_count": segment.effort_count,
        "athlete_count": segment.athlete_count,
        "star_count": segment.star_count,
        "map_polyline": segment.map.polyline if segment.map else None,
        "links": {
            "web": f"{STRAVA_SEGMENT_WEB_URL}/{segment.id}",
            "app": f"{STRAVA_SEGMENT_APP_URL}/{segment.id}",
        },
    }


@mcp.tool()
@handle_strava_errors
async def get_segment(segment_id: int) -> dict[str, Any]:
    """Get detailed information about a specific segment.

    Args:
        segment_id: The unique ID of the segment.

    Returns:
        Full segment details including polyline, stats, and deeplinks.
    """
    if segment_id < 1:
        return {
            "error": "validation_error",
            "message": "segment_id must be a positive integer",
        }

    return await asyncio.to_thread(_fetch_segment, segment_id)


# =============================================================================
# Route Tools
# =============================================================================

STRAVA_ROUTE_WEB_URL = "https://www.strava.com/routes"
STRAVA_ROUTE_APP_URL = "strava://routes"


def _format_timestamp(ts: Any) -> str | None:
    """Format a timestamp to ISO string, handling various types."""
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        return ts.isoformat()  # type: ignore[no-any-return]
    return str(ts)


def _fetch_routes(athlete_id: int | None, limit: int) -> list[dict[str, Any]]:
    """Fetch athlete routes (sync helper)."""
    client = get_authenticated_client()
    routes = client.get_routes(athlete_id=athlete_id, limit=limit)

    results = []
    for route in routes:
        route_data = {
            "id": route.id,
            "name": route.name,
            "description": route.description,
            "distance": route.distance,
            "elevation_gain": route.elevation_gain,
            "type": route.type,
            "sub_type": route.sub_type,
            "starred": route.starred,
            "timestamp": _format_timestamp(route.timestamp),
            "links": {
                "web": f"{STRAVA_ROUTE_WEB_URL}/{route.id}",
                "app": f"{STRAVA_ROUTE_APP_URL}/{route.id}",
            },
        }
        results.append(route_data)

    return results


@mcp.tool()
@handle_strava_errors
async def get_my_routes(
    limit: int = 20,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Get routes created by the authenticated athlete.

    Args:
        limit: Maximum number of routes to return (default 20, max 200).

    Returns:
        List of routes with details and deeplinks.
    """
    if limit < 1:
        return {"error": "validation_error", "message": "limit must be at least 1"}
    limit = min(limit, 200)

    routes = await asyncio.to_thread(_fetch_routes, None, limit)

    return {
        "count": len(routes),
        "routes": routes,
    }


def _fetch_route(route_id: int) -> dict[str, Any]:
    """Fetch route details (sync helper)."""
    client = get_authenticated_client()
    route = client.get_route(route_id)

    return {
        "id": route.id,
        "name": route.name,
        "description": route.description,
        "distance": route.distance,
        "elevation_gain": route.elevation_gain,
        "type": route.type,
        "sub_type": route.sub_type,
        "starred": route.starred,
        "private": route.private,
        "timestamp": _format_timestamp(route.timestamp),
        "map_polyline": route.map.polyline if route.map else None,
        "map_summary_polyline": route.map.summary_polyline if route.map else None,
        "segments": [
            {
                "id": seg.id,
                "name": seg.name,
                "links": {
                    "web": f"{STRAVA_SEGMENT_WEB_URL}/{seg.id}",
                    "app": f"{STRAVA_SEGMENT_APP_URL}/{seg.id}",
                },
            }
            for seg in (route.segments or [])
        ],
        "links": {
            "web": f"{STRAVA_ROUTE_WEB_URL}/{route.id}",
            "app": f"{STRAVA_ROUTE_APP_URL}/{route.id}",
        },
    }


@mcp.tool()
@handle_strava_errors
async def get_route(route_id: int) -> dict[str, Any]:
    """Get detailed information about a specific route.

    Args:
        route_id: The unique ID of the route.

    Returns:
        Full route details including polyline, segments, and deeplinks.
    """
    if route_id < 1:
        return {
            "error": "validation_error",
            "message": "route_id must be a positive integer",
        }

    return await asyncio.to_thread(_fetch_route, route_id)


# =============================================================================
# Club Tools
# =============================================================================

STRAVA_CLUB_WEB_URL = "https://www.strava.com/clubs"
STRAVA_CLUB_APP_URL = "strava://clubs"


def _fetch_athlete_clubs(limit: int | None) -> list[dict[str, Any]]:
    """Fetch athlete's clubs (sync helper)."""
    client = get_authenticated_client()
    clubs = client.get_athlete_clubs(limit=limit)

    results = []
    for club in clubs:
        club_data = {
            "id": club.id,
            "name": club.name,
            "sport_type": club.sport_type,
            "city": club.city,
            "state": club.state,
            "country": club.country,
            "member_count": club.member_count,
            "private": club.private,
            "profile_medium": club.profile_medium,
            "links": {
                "web": f"{STRAVA_CLUB_WEB_URL}/{club.id}",
                "app": f"{STRAVA_CLUB_APP_URL}/{club.id}",
            },
        }
        results.append(club_data)

    return results


@mcp.tool()
@handle_strava_errors
async def get_my_clubs(
    limit: int | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Get clubs the authenticated athlete is a member of.

    Args:
        limit: Maximum number of clubs to return (optional).

    Returns:
        List of clubs with details and deeplinks.
    """
    if limit is not None and limit < 1:
        return {"error": "validation_error", "message": "limit must be at least 1"}

    clubs = await asyncio.to_thread(_fetch_athlete_clubs, limit)

    return {
        "count": len(clubs),
        "clubs": clubs,
    }


def _fetch_club(club_id: int) -> dict[str, Any]:
    """Fetch club details (sync helper)."""
    client = get_authenticated_client()
    club = client.get_club(club_id)

    return {
        "id": club.id,
        "name": club.name,
        "description": club.description,
        "sport_type": club.sport_type,
        "city": club.city,
        "state": club.state,
        "country": club.country,
        "member_count": club.member_count,
        "private": club.private,
        "verified": club.verified,
        "profile_medium": club.profile_medium,
        "cover_photo": club.cover_photo,
        "links": {
            "web": f"{STRAVA_CLUB_WEB_URL}/{club.id}",
            "app": f"{STRAVA_CLUB_APP_URL}/{club.id}",
        },
    }


@mcp.tool()
@handle_strava_errors
async def get_club(club_id: int) -> dict[str, Any]:
    """Get detailed information about a specific club.

    Args:
        club_id: The unique ID of the club.

    Returns:
        Full club details including description and deeplinks.
    """
    if club_id < 1:
        return {
            "error": "validation_error",
            "message": "club_id must be a positive integer",
        }

    return await asyncio.to_thread(_fetch_club, club_id)


def _fetch_club_members(club_id: int, limit: int | None) -> list[dict[str, Any]]:
    """Fetch club members (sync helper)."""
    client = get_authenticated_client()
    members = client.get_club_members(club_id, limit=limit)

    results = []
    for member in members:
        member_data = {
            "firstname": member.firstname,
            "lastname": member.lastname,
            "admin": member.admin,
            "owner": member.owner,
        }
        results.append(member_data)

    return results


@mcp.tool()
@handle_strava_errors
async def get_club_members(
    club_id: int,
    limit: int = 30,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Get members of a specific club.

    Args:
        club_id: The unique ID of the club.
        limit: Maximum number of members to return (default 30, max 200).

    Returns:
        List of club members with basic profile info.
    """
    if club_id < 1:
        return {
            "error": "validation_error",
            "message": "club_id must be a positive integer",
        }
    if limit < 1:
        return {"error": "validation_error", "message": "limit must be at least 1"}
    limit = min(limit, 200)

    members = await asyncio.to_thread(_fetch_club_members, club_id, limit)

    return {
        "club_id": club_id,
        "count": len(members),
        "members": members,
    }


def _fetch_club_activities(club_id: int, limit: int | None) -> list[dict[str, Any]]:
    """Fetch club activities (sync helper)."""
    client = get_authenticated_client()
    activities = client.get_club_activities(club_id, limit=limit)

    results = []
    for activity in activities:
        activity_data = {
            "name": activity.name,
            "type": activity.type,
            "distance": activity.distance,
            "moving_time": activity.moving_time,
            "total_elevation_gain": activity.total_elevation_gain,
            "athlete": {
                "firstname": activity.athlete.firstname if activity.athlete else None,
                "lastname": activity.athlete.lastname if activity.athlete else None,
            },
        }
        results.append(activity_data)

    return results


@mcp.tool()
@handle_strava_errors
async def get_club_activities(
    club_id: int,
    limit: int = 30,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Get recent activities from club members.

    Args:
        club_id: The unique ID of the club.
        limit: Maximum number of activities to return (default 30, max 200).

    Returns:
        List of recent club activities with athlete info.
    """
    if club_id < 1:
        return {
            "error": "validation_error",
            "message": "club_id must be a positive integer",
        }
    if limit < 1:
        return {"error": "validation_error", "message": "limit must be at least 1"}
    limit = min(limit, 200)

    activities = await asyncio.to_thread(_fetch_club_activities, club_id, limit)

    return {
        "club_id": club_id,
        "count": len(activities),
        "activities": activities,
    }


# =============================================================================
# Activity Engagement Tools
# =============================================================================

STRAVA_ATHLETE_WEB_URL = "https://www.strava.com/athletes"


def _fetch_activity_kudos(activity_id: int, limit: int | None) -> list[dict[str, Any]]:
    """Fetch activity kudos (sync helper)."""
    client = get_authenticated_client()
    kudoers = client.get_activity_kudos(activity_id, limit=limit)

    results = []
    for athlete in kudoers:
        kudoer_data = {
            "id": athlete.id,
            "firstname": athlete.firstname,
            "lastname": athlete.lastname,
            "profile_medium": athlete.profile_medium,
            "links": {
                "web": f"{STRAVA_ATHLETE_WEB_URL}/{athlete.id}",
            },
        }
        results.append(kudoer_data)

    return results


@mcp.tool()
@handle_strava_errors
async def get_activity_kudos(
    activity_id: int,
    limit: int = 30,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Get athletes who gave kudos to an activity.

    Args:
        activity_id: The unique ID of the activity.
        limit: Maximum number of kudoers to return (default 30, max 200).

    Returns:
        List of athletes who gave kudos with profile links.
    """
    if activity_id < 1:
        return {
            "error": "validation_error",
            "message": "activity_id must be a positive integer",
        }
    if limit < 1:
        return {"error": "validation_error", "message": "limit must be at least 1"}
    limit = min(limit, 200)

    kudoers = await asyncio.to_thread(_fetch_activity_kudos, activity_id, limit)

    return {
        "activity_id": activity_id,
        "count": len(kudoers),
        "kudoers": kudoers,
    }


def _fetch_activity_comments(
    activity_id: int, limit: int | None
) -> list[dict[str, Any]]:
    """Fetch activity comments (sync helper)."""
    client = get_authenticated_client()
    comments = client.get_activity_comments(activity_id, limit=limit)

    results = []
    for comment in comments:
        comment_data = {
            "id": comment.id,
            "text": comment.text,
            "created_at": _format_timestamp(comment.created_at),
            "athlete": {
                "id": comment.athlete.id if comment.athlete else None,
                "firstname": comment.athlete.firstname if comment.athlete else None,
                "lastname": comment.athlete.lastname if comment.athlete else None,
                "links": {
                    "web": f"{STRAVA_ATHLETE_WEB_URL}/{comment.athlete.id}"
                    if comment.athlete
                    else None,
                },
            },
        }
        results.append(comment_data)

    return results


@mcp.tool()
@handle_strava_errors
async def get_activity_comments(
    activity_id: int,
    limit: int = 30,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Get comments on an activity.

    Args:
        activity_id: The unique ID of the activity.
        limit: Maximum number of comments to return (default 30, max 200).

    Returns:
        List of comments with text, timestamps, and athlete info.
    """
    if activity_id < 1:
        return {
            "error": "validation_error",
            "message": "activity_id must be a positive integer",
        }
    if limit < 1:
        return {"error": "validation_error", "message": "limit must be at least 1"}
    limit = min(limit, 200)

    comments = await asyncio.to_thread(_fetch_activity_comments, activity_id, limit)

    return {
        "activity_id": activity_id,
        "count": len(comments),
        "comments": comments,
    }


# =============================================================================
# Athlete Social Tools
# =============================================================================


def _fetch_athlete_koms(athlete_id: int | None, limit: int) -> list[dict[str, Any]]:
    """Fetch athlete KOMs/CRs (sync helper)."""
    client = get_authenticated_client()

    # If no athlete_id provided, get the authenticated athlete's ID
    resolved_athlete_id: int
    if athlete_id is None:
        athlete = client.get_athlete()
        resolved_athlete_id = athlete.id  # type: ignore[assignment]
    else:
        resolved_athlete_id = athlete_id

    efforts = client.get_athlete_koms(resolved_athlete_id, limit=limit)

    results = []
    for effort in efforts:
        effort_data = {
            "id": effort.id,
            "name": effort.name,
            "elapsed_time": effort.elapsed_time,
            "moving_time": effort.moving_time,
            "start_date": _format_timestamp(effort.start_date),
            "distance": effort.distance,
            "segment": {
                "id": effort.segment.id if effort.segment else None,
                "name": effort.segment.name if effort.segment else None,
                "links": {
                    "web": f"{STRAVA_SEGMENT_WEB_URL}/{effort.segment.id}"
                    if effort.segment
                    else None,
                    "app": f"{STRAVA_SEGMENT_APP_URL}/{effort.segment.id}"
                    if effort.segment
                    else None,
                },
            },
            "activity": {
                "id": effort.activity.id if effort.activity else None,
            },
        }
        results.append(effort_data)

    return results


@mcp.tool()
@handle_strava_errors
async def get_my_koms(
    limit: int = 30,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Get KOMs (King/Queen of the Mountain) and CRs (Course Records) for the authenticated athlete.

    Args:
        limit: Maximum number of KOMs to return (default 30, max 200).

    Returns:
        List of segment efforts where the athlete holds the KOM/CR.
    """
    if limit < 1:
        return {"error": "validation_error", "message": "limit must be at least 1"}
    limit = min(limit, 200)

    koms = await asyncio.to_thread(_fetch_athlete_koms, None, limit)

    return {
        "count": len(koms),
        "koms": koms,
    }


def _fetch_starred_segments(limit: int | None) -> list[dict[str, Any]]:
    """Fetch starred segments (sync helper)."""
    client = get_authenticated_client()
    segments = client.get_starred_segments(limit=limit)

    results = []
    for segment in segments:
        segment_data = {
            "id": segment.id,
            "name": segment.name,
            "activity_type": segment.activity_type,
            "distance": segment.distance,
            "average_grade": segment.average_grade,
            "climb_category": segment.climb_category,
            "city": segment.city,
            "state": segment.state,
            "country": segment.country,
            "links": {
                "web": f"{STRAVA_SEGMENT_WEB_URL}/{segment.id}",
                "app": f"{STRAVA_SEGMENT_APP_URL}/{segment.id}",
            },
        }
        results.append(segment_data)

    return results


@mcp.tool()
@handle_strava_errors
async def get_starred_segments(
    limit: int = 30,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Get segments starred by the authenticated athlete.

    Args:
        limit: Maximum number of segments to return (default 30, max 200).

    Returns:
        List of starred segments with details and deeplinks.
    """
    if limit < 1:
        return {"error": "validation_error", "message": "limit must be at least 1"}
    limit = min(limit, 200)

    segments = await asyncio.to_thread(_fetch_starred_segments, limit)

    return {
        "count": len(segments),
        "segments": segments,
    }


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
