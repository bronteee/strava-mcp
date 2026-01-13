"""Tests for MCP server tools."""

from unittest.mock import MagicMock, patch

import pytest

from strava_mcp.tokens import load_tokens, save_tokens


class TestGetAuthStatus:
    """Tests for get_auth_status tool."""

    @pytest.mark.asyncio
    async def test_returns_not_authenticated_when_no_tokens(self):
        """Should return not authenticated when no tokens exist."""
        from strava_mcp.server import get_auth_status

        result = await get_auth_status()

        assert result["authenticated"] is False
        assert "No tokens found" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_authenticated_with_valid_tokens(self, valid_tokens):
        """Should return authenticated when valid tokens exist."""
        from strava_mcp.server import get_auth_status

        save_tokens(valid_tokens)

        result = await get_auth_status()

        assert result["authenticated"] is True
        assert result["is_expired"] is False
        assert "ready" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_returns_expired_status_for_expired_tokens(self, expired_tokens):
        """Should indicate expired status when tokens are expired."""
        from strava_mcp.server import get_auth_status

        save_tokens(expired_tokens)

        result = await get_auth_status()

        assert result["authenticated"] is True
        assert result["is_expired"] is True
        assert "expired" in result["message"].lower()


class TestGetAuthUrl:
    """Tests for get_auth_url tool."""

    @pytest.mark.asyncio
    async def test_returns_authorization_url(self, mock_strava_client, mock_env_vars):
        """Should return a Strava authorization URL."""
        from strava_mcp.server import get_auth_url

        # Patch the oauth server start to avoid actually starting it
        with patch("strava_mcp.server.start_oauth_server", return_value=True):
            result = await get_auth_url()

        assert "auth_url" in result
        assert "strava.com" in result["auth_url"]
        assert "instructions" in result

    @pytest.mark.asyncio
    async def test_includes_oauth_server_info(self, mock_strava_client, mock_env_vars):
        """Should include OAuth server information."""
        from strava_mcp.server import get_auth_url

        with patch("strava_mcp.server.start_oauth_server", return_value=True):
            result = await get_auth_url()

        assert "oauth_server" in result
        assert "127.0.0.1" in result["oauth_server"]


class TestAuthenticate:
    """Tests for authenticate tool."""

    @pytest.mark.asyncio
    async def test_exchanges_code_and_saves_tokens(
        self, mock_strava_client, mock_env_vars, mock_athlete
    ):
        """Should exchange code for tokens and save them."""
        from strava_mcp.server import authenticate

        # Configure mock to return athlete on get_athlete call
        mock_strava_client.return_value.get_athlete.return_value = mock_athlete

        result = await authenticate(code="test_auth_code")

        assert result["success"] is True
        assert "Test User" in result["message"]
        assert result["athlete_id"] == mock_athlete.id

        # Verify tokens were saved
        stored = load_tokens()
        assert stored is not None

    @pytest.mark.asyncio
    async def test_returns_athlete_info(
        self, mock_strava_client, mock_env_vars, mock_athlete
    ):
        """Should return athlete information after authentication."""
        from strava_mcp.server import authenticate

        mock_strava_client.return_value.get_athlete.return_value = mock_athlete

        result = await authenticate(code="test_auth_code")

        assert result["athlete_id"] == 12345678
        assert "expires_at" in result


class TestLogout:
    """Tests for logout tool."""

    @pytest.mark.asyncio
    async def test_deletes_tokens(self, valid_tokens):
        """Should delete tokens from memory."""
        from strava_mcp.server import logout

        # Store tokens first
        save_tokens(valid_tokens)

        result = await logout()

        assert result["success"] is True
        assert load_tokens() is None

    @pytest.mark.asyncio
    async def test_succeeds_when_no_tokens(self):
        """Should succeed even when no tokens exist."""
        from strava_mcp.server import logout

        result = await logout()

        assert result["success"] is True


class TestGetActivities:
    """Tests for get_activities tool."""

    @pytest.mark.asyncio
    async def test_returns_activities(
        self,
        mock_strava_client,
        mock_env_vars,
        valid_tokens,
        mock_activity,
    ):
        """Should return list of activities."""
        from strava_mcp.server import get_activities

        save_tokens(valid_tokens)

        result = await get_activities(limit=5)

        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["name"] == "Morning Run"

    @pytest.mark.asyncio
    async def test_parses_date_filters(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should parse and apply date filters."""
        from strava_mcp.server import get_activities

        save_tokens(valid_tokens)

        await get_activities(after="2025-12-01", before="2025-12-31", limit=10)

        # Verify the client was called with datetime objects
        call_args = mock_strava_client.return_value.get_activities.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_returns_error_when_not_authenticated(self):
        """Should return error dict when not authenticated."""
        from strava_mcp.server import get_activities

        result = await get_activities()
        assert isinstance(result, dict)
        assert "error" in result
        assert result["error"] == "validation_error"
        assert "Not authenticated" in result["message"]


class TestGetAthlete:
    """Tests for get_athlete tool."""

    @pytest.mark.asyncio
    async def test_returns_athlete_profile(
        self,
        mock_strava_client,
        mock_env_vars,
        valid_tokens,
        mock_athlete,
    ):
        """Should return athlete profile."""
        from strava_mcp.server import get_athlete

        save_tokens(valid_tokens)

        result = await get_athlete()

        assert result["firstname"] == "Test"
        assert result["lastname"] == "User"
        assert result["id"] == 12345678


class TestGetAthleteStats:
    """Tests for get_athlete_stats tool."""

    @pytest.mark.asyncio
    async def test_returns_stats(
        self,
        mock_strava_client,
        mock_env_vars,
        valid_tokens,
        mock_athlete_stats,
    ):
        """Should return athlete statistics."""
        from strava_mcp.server import get_athlete_stats

        save_tokens(valid_tokens)

        result = await get_athlete_stats()

        assert "recent_run_totals" in result
        assert "ytd_run_totals" in result
        assert "all_run_totals" in result

    @pytest.mark.asyncio
    async def test_accepts_athlete_id(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should accept an athlete_id parameter."""
        from strava_mcp.server import get_athlete_stats

        save_tokens(valid_tokens)

        await get_athlete_stats(athlete_id=12345678)

        # Verify client was called with athlete_id
        mock_strava_client.return_value.get_athlete_stats.assert_called_with(
            athlete_id=12345678
        )


class TestGetActivityDetails:
    """Tests for get_activity_details tool."""

    @pytest.mark.asyncio
    async def test_returns_activity_details(
        self,
        mock_strava_client,
        mock_env_vars,
        valid_tokens,
        mock_activity,
    ):
        """Should return detailed activity information."""
        from strava_mcp.server import get_activity_details

        save_tokens(valid_tokens)

        result = await get_activity_details(activity_id=9876543210)

        assert result["id"] == 9876543210
        assert result["name"] == "Morning Run"
        assert result["type"] == "Run"

    @pytest.mark.asyncio
    async def test_calls_client_with_activity_id(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should call client.get_activity with correct activity_id."""
        from strava_mcp.server import get_activity_details

        save_tokens(valid_tokens)

        await get_activity_details(activity_id=123456)

        mock_strava_client.return_value.get_activity.assert_called_with(123456)


class TestTokenRefresh:
    """Tests for automatic token refresh."""

    @pytest.mark.asyncio
    async def test_refreshes_expired_tokens(
        self, mock_strava_client, mock_env_vars, expired_tokens
    ):
        """Should refresh tokens when they're expired."""
        from strava_mcp.server import get_athlete

        save_tokens(expired_tokens)

        await get_athlete()

        # Verify refresh was called
        mock_strava_client.return_value.refresh_access_token.assert_called_once()

        # Verify new tokens were saved
        stored = load_tokens()
        assert stored["access_token"] == "refreshed_token"


class TestGeocodeLocation:
    """Tests for geocode_location tool."""

    @pytest.mark.asyncio
    async def test_returns_location_and_bounds(self):
        """Should return location details and bounding box."""
        from strava_mcp.server import geocode_location

        with patch("strava_mcp.server._geocoder") as mock_geocoder:
            mock_location = MagicMock()
            mock_location.latitude = 37.7749
            mock_location.longitude = -122.4194
            mock_location.address = "San Francisco, CA, USA"
            mock_geocoder.geocode.return_value = mock_location

            result = await geocode_location("San Francisco", radius_km=5.0)

        assert result["query"] == "San Francisco"
        assert result["location"]["latitude"] == 37.7749
        assert result["location"]["longitude"] == -122.4194
        assert "bounds" in result
        assert "sw_lat" in result["bounds"]
        assert "ne_lat" in result["bounds"]

    @pytest.mark.asyncio
    async def test_returns_error_for_empty_query(self):
        """Should return error for empty query."""
        from strava_mcp.server import geocode_location

        result = await geocode_location("")

        assert "error" in result
        assert result["error"] == "validation_error"

    @pytest.mark.asyncio
    async def test_returns_error_for_invalid_radius(self):
        """Should return error for invalid radius."""
        from strava_mcp.server import geocode_location

        result = await geocode_location("San Francisco", radius_km=-5.0)

        assert "error" in result
        assert "radius_km must be positive" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_error_for_too_large_radius(self):
        """Should return error for radius > 50km."""
        from strava_mcp.server import geocode_location

        result = await geocode_location("San Francisco", radius_km=100.0)

        assert "error" in result
        assert "50km" in result["message"]


class TestExploreRunningSegments:
    """Tests for explore_running_segments tool."""

    @pytest.mark.asyncio
    async def test_returns_segments_with_bounds(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should return segments when using bounds."""
        from strava_mcp.server import explore_running_segments

        save_tokens(valid_tokens)

        result = await explore_running_segments(bounds=[37.7, -122.5, 37.8, -122.4])

        assert "count" in result
        assert "segments" in result
        assert len(result["segments"]) >= 1
        assert result["segments"][0]["name"] == "Test Hill Climb"
        assert "links" in result["segments"][0]
        assert "web" in result["segments"][0]["links"]

    @pytest.mark.asyncio
    async def test_returns_segments_with_location(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should return segments when using location name."""
        from strava_mcp.server import explore_running_segments

        save_tokens(valid_tokens)

        with patch("strava_mcp.server._geocoder") as mock_geocoder:
            mock_location = MagicMock()
            mock_location.latitude = 37.7749
            mock_location.longitude = -122.4194
            mock_location.address = "San Francisco, CA, USA"
            mock_geocoder.geocode.return_value = mock_location

            result = await explore_running_segments(location="San Francisco")

        assert "count" in result
        assert "segments" in result
        assert "searched_location" in result

    @pytest.mark.asyncio
    async def test_returns_error_when_neither_location_nor_bounds(self):
        """Should return error when neither location nor bounds provided."""
        from strava_mcp.server import explore_running_segments

        result = await explore_running_segments()

        assert "error" in result
        assert "Provide either" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_error_when_both_location_and_bounds(self):
        """Should return error when both location and bounds provided."""
        from strava_mcp.server import explore_running_segments

        result = await explore_running_segments(
            location="San Francisco", bounds=[37.7, -122.5, 37.8, -122.4]
        )

        assert "error" in result
        assert "not both" in result["message"]

    @pytest.mark.asyncio
    async def test_includes_deeplinks(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should include web and app deeplinks."""
        from strava_mcp.server import explore_running_segments

        save_tokens(valid_tokens)

        result = await explore_running_segments(bounds=[37.7, -122.5, 37.8, -122.4])

        segment = result["segments"][0]
        assert "strava.com/segments" in segment["links"]["web"]
        assert "strava://segments" in segment["links"]["app"]


class TestGetSegment:
    """Tests for get_segment tool."""

    @pytest.mark.asyncio
    async def test_returns_segment_details(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should return full segment details."""
        from strava_mcp.server import get_segment

        save_tokens(valid_tokens)

        result = await get_segment(segment_id=12345)

        assert result["id"] == 12345
        assert result["name"] == "Test Hill Climb"
        assert "map_polyline" in result
        assert "links" in result

    @pytest.mark.asyncio
    async def test_returns_error_for_invalid_id(self):
        """Should return error for invalid segment_id."""
        from strava_mcp.server import get_segment

        result = await get_segment(segment_id=0)

        assert "error" in result
        assert "positive integer" in result["message"]

    @pytest.mark.asyncio
    async def test_calls_client_with_segment_id(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should call client.get_segment with correct ID."""
        from strava_mcp.server import get_segment

        save_tokens(valid_tokens)

        await get_segment(segment_id=99999)

        mock_strava_client.return_value.get_segment.assert_called_with(99999)


class TestGetMyRoutes:
    """Tests for get_my_routes tool."""

    @pytest.mark.asyncio
    async def test_returns_routes(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should return list of routes."""
        from strava_mcp.server import get_my_routes

        save_tokens(valid_tokens)

        result = await get_my_routes(limit=10)

        assert "count" in result
        assert "routes" in result
        assert len(result["routes"]) >= 1
        assert result["routes"][0]["name"] == "Morning Loop"
        assert "links" in result["routes"][0]

    @pytest.mark.asyncio
    async def test_returns_error_for_invalid_limit(self):
        """Should return error for invalid limit."""
        from strava_mcp.server import get_my_routes

        result = await get_my_routes(limit=0)

        assert "error" in result
        assert "at least 1" in result["message"]

    @pytest.mark.asyncio
    async def test_includes_deeplinks(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should include web and app deeplinks."""
        from strava_mcp.server import get_my_routes

        save_tokens(valid_tokens)

        result = await get_my_routes()

        route = result["routes"][0]
        assert "strava.com/routes" in route["links"]["web"]
        assert "strava://routes" in route["links"]["app"]


class TestGetRoute:
    """Tests for get_route tool."""

    @pytest.mark.asyncio
    async def test_returns_route_details(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should return full route details."""
        from strava_mcp.server import get_route

        save_tokens(valid_tokens)

        result = await get_route(route_id=98765)

        assert result["id"] == 98765
        assert result["name"] == "Morning Loop"
        assert "map_polyline" in result
        assert "links" in result

    @pytest.mark.asyncio
    async def test_returns_error_for_invalid_id(self):
        """Should return error for invalid route_id."""
        from strava_mcp.server import get_route

        result = await get_route(route_id=-1)

        assert "error" in result
        assert "positive integer" in result["message"]

    @pytest.mark.asyncio
    async def test_calls_client_with_route_id(
        self, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should call client.get_route with correct ID."""
        from strava_mcp.server import get_route

        save_tokens(valid_tokens)

        await get_route(route_id=11111)

        mock_strava_client.return_value.get_route.assert_called_with(11111)
