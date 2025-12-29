"""Tests for MCP server tools."""

import json
from unittest.mock import patch

import pytest

from strava_mcp.tokens import KEYRING_SERVICE, KEYRING_USERNAME


class TestGetAuthStatus:
    """Tests for get_auth_status tool."""

    @pytest.mark.asyncio
    async def test_returns_not_authenticated_when_no_tokens(self, mock_keyring):
        """Should return not authenticated when no tokens exist."""
        from strava_mcp.server import get_auth_status

        result = await get_auth_status()

        assert result["authenticated"] is False
        assert "No tokens found" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_authenticated_with_valid_tokens(
        self, mock_keyring, valid_tokens
    ):
        """Should return authenticated when valid tokens exist."""
        from strava_mcp.server import get_auth_status

        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            valid_tokens
        )

        result = await get_auth_status()

        assert result["authenticated"] is True
        assert result["is_expired"] is False
        assert "ready" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_returns_expired_status_for_expired_tokens(
        self, mock_keyring, expired_tokens
    ):
        """Should indicate expired status when tokens are expired."""
        from strava_mcp.server import get_auth_status

        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            expired_tokens
        )

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
        self, mock_keyring, mock_strava_client, mock_env_vars, mock_athlete
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
        stored = mock_keyring._storage.get(f"{KEYRING_SERVICE}:{KEYRING_USERNAME}")
        assert stored is not None

    @pytest.mark.asyncio
    async def test_returns_athlete_info(
        self, mock_keyring, mock_strava_client, mock_env_vars, mock_athlete
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
    async def test_deletes_tokens(self, mock_keyring, valid_tokens):
        """Should delete tokens from keyring."""
        from strava_mcp.server import logout

        # Store tokens first
        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            valid_tokens
        )

        result = await logout()

        assert result["success"] is True
        assert f"{KEYRING_SERVICE}:{KEYRING_USERNAME}" not in mock_keyring._storage

    @pytest.mark.asyncio
    async def test_succeeds_when_no_tokens(self, mock_keyring):
        """Should succeed even when no tokens exist."""
        from strava_mcp.server import logout

        result = await logout()

        assert result["success"] is True


class TestGetActivities:
    """Tests for get_activities tool."""

    @pytest.mark.asyncio
    async def test_returns_activities(
        self,
        mock_keyring,
        mock_strava_client,
        mock_env_vars,
        valid_tokens,
        mock_activity,
    ):
        """Should return list of activities."""
        from strava_mcp.server import get_activities

        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            valid_tokens
        )

        result = await get_activities(limit=5)

        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["name"] == "Morning Run"

    @pytest.mark.asyncio
    async def test_parses_date_filters(
        self, mock_keyring, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should parse and apply date filters."""
        from strava_mcp.server import get_activities

        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            valid_tokens
        )

        await get_activities(after="2025-12-01", before="2025-12-31", limit=10)

        # Verify the client was called with datetime objects
        call_args = mock_strava_client.return_value.get_activities.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_raises_when_not_authenticated(self, mock_keyring):
        """Should raise error when not authenticated."""
        from strava_mcp.server import get_activities

        with pytest.raises(ValueError, match="Not authenticated"):
            await get_activities()


class TestGetAthlete:
    """Tests for get_athlete tool."""

    @pytest.mark.asyncio
    async def test_returns_athlete_profile(
        self,
        mock_keyring,
        mock_strava_client,
        mock_env_vars,
        valid_tokens,
        mock_athlete,
    ):
        """Should return athlete profile."""
        from strava_mcp.server import get_athlete

        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            valid_tokens
        )

        result = await get_athlete()

        assert result["firstname"] == "Test"
        assert result["lastname"] == "User"
        assert result["id"] == 12345678


class TestGetAthleteStats:
    """Tests for get_athlete_stats tool."""

    @pytest.mark.asyncio
    async def test_returns_stats(
        self,
        mock_keyring,
        mock_strava_client,
        mock_env_vars,
        valid_tokens,
        mock_athlete_stats,
    ):
        """Should return athlete statistics."""
        from strava_mcp.server import get_athlete_stats

        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            valid_tokens
        )

        result = await get_athlete_stats()

        assert "recent_run_totals" in result
        assert "ytd_run_totals" in result
        assert "all_run_totals" in result

    @pytest.mark.asyncio
    async def test_accepts_athlete_id(
        self, mock_keyring, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should accept an athlete_id parameter."""
        from strava_mcp.server import get_athlete_stats

        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            valid_tokens
        )

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
        mock_keyring,
        mock_strava_client,
        mock_env_vars,
        valid_tokens,
        mock_activity,
    ):
        """Should return detailed activity information."""
        from strava_mcp.server import get_activity_details

        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            valid_tokens
        )

        result = await get_activity_details(activity_id=9876543210)

        assert result["id"] == 9876543210
        assert result["name"] == "Morning Run"
        assert result["type"] == "Run"

    @pytest.mark.asyncio
    async def test_calls_client_with_activity_id(
        self, mock_keyring, mock_strava_client, mock_env_vars, valid_tokens
    ):
        """Should call client.get_activity with correct activity_id."""
        from strava_mcp.server import get_activity_details

        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            valid_tokens
        )

        await get_activity_details(activity_id=123456)

        mock_strava_client.return_value.get_activity.assert_called_with(123456)


class TestTokenRefresh:
    """Tests for automatic token refresh."""

    @pytest.mark.asyncio
    async def test_refreshes_expired_tokens(
        self, mock_keyring, mock_strava_client, mock_env_vars, expired_tokens
    ):
        """Should refresh tokens when they're expired."""
        from strava_mcp.server import get_athlete

        mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"] = json.dumps(
            expired_tokens
        )

        await get_athlete()

        # Verify refresh was called
        mock_strava_client.return_value.refresh_access_token.assert_called_once()

        # Verify new tokens were saved
        stored = json.loads(
            mock_keyring._storage[f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"]
        )
        assert stored["access_token"] == "refreshed_token"
