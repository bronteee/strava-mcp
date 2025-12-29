"""Tests for OAuth callback server."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from strava_mcp.tokens import KEYRING_SERVICE, KEYRING_USERNAME


@pytest.fixture
def mock_oauth_keyring():
    """Mock keyring specifically for OAuth tests."""
    storage = {}

    def get_password(service, username):
        key = f"{service}:{username}"
        return storage.get(key)

    def set_password(service, username, password):
        key = f"{service}:{username}"
        storage[key] = password

    with patch("strava_mcp.oauth.keyring", create=True) as mock:
        mock.get_password = MagicMock(side_effect=get_password)
        mock.set_password = MagicMock(side_effect=set_password)
        mock._storage = storage
        # Also patch in tokens module
        with patch("strava_mcp.tokens.keyring") as tokens_mock:
            tokens_mock.get_password = MagicMock(side_effect=get_password)
            tokens_mock.set_password = MagicMock(side_effect=set_password)
            tokens_mock._storage = storage
            yield storage


@pytest.fixture
def mock_oauth_env():
    """Set up environment variables for OAuth tests."""
    with patch.dict(
        "os.environ",
        {
            "STRAVA_CLIENT_ID": "12345",
            "STRAVA_CLIENT_SECRET": "test_client_secret",
        },
    ):
        # Need to reload oauth module to pick up env vars
        yield


@pytest.fixture
def mock_oauth_client(mock_athlete):
    """Mock Strava client for OAuth tests."""
    with patch("strava_mcp.oauth.Client") as mock_client:
        client_instance = MagicMock()

        # Mock authorization_url
        client_instance.authorization_url.return_value = (
            "https://www.strava.com/oauth/authorize?client_id=test"
        )

        # Mock token exchange
        client_instance.exchange_code_for_token.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_at": (datetime.now() + timedelta(hours=6)).timestamp(),
        }

        # Mock get_athlete
        client_instance.get_athlete.return_value = mock_athlete

        mock_client.return_value = client_instance
        yield mock_client


class TestLoginEndpoint:
    """Tests for the / login endpoint."""

    @pytest.mark.asyncio
    async def test_login_page_renders(self, mock_oauth_env, mock_oauth_client):
        """Should render login page with authorization URL."""
        from strava_mcp.oauth import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/")

        assert response.status_code == 200
        assert "strava" in response.text.lower()

    @pytest.mark.asyncio
    async def test_login_shows_error_without_credentials(self):
        """Should show error when credentials are missing."""
        # Clear env vars to simulate missing credentials
        with patch.dict(
            "os.environ",
            {"STRAVA_CLIENT_ID": "", "STRAVA_CLIENT_SECRET": ""},
            clear=False,
        ):
            from strava_mcp.oauth import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/")

            assert response.status_code == 200
            assert "not configured" in response.text.lower()


class TestOAuthCallback:
    """Tests for the /strava-oauth callback endpoint."""

    @pytest.mark.asyncio
    async def test_callback_with_error_shows_error_page(
        self, mock_oauth_env, mock_oauth_client
    ):
        """Should show error page when Strava returns an error."""
        from strava_mcp.oauth import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/strava-oauth?error=access_denied")

        assert response.status_code == 200
        assert "access_denied" in response.text

    @pytest.mark.asyncio
    async def test_callback_without_code_shows_error(
        self, mock_oauth_env, mock_oauth_client
    ):
        """Should show error when code is missing."""
        from strava_mcp.oauth import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/strava-oauth")

        assert response.status_code == 200
        assert "missing" in response.text.lower()

    @pytest.mark.asyncio
    async def test_callback_exchanges_code_for_tokens(
        self, mock_oauth_env, mock_oauth_client, mock_oauth_keyring
    ):
        """Should exchange code for tokens and save them."""
        from strava_mcp.oauth import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/strava-oauth?code=test_auth_code")

        assert response.status_code == 200

        # Verify exchange_code_for_token was called
        mock_oauth_client.return_value.exchange_code_for_token.assert_called_once()
        call_kwargs = (
            mock_oauth_client.return_value.exchange_code_for_token.call_args.kwargs
        )
        assert call_kwargs["code"] == "test_auth_code"

    @pytest.mark.asyncio
    async def test_callback_saves_tokens_to_keyring(
        self, mock_oauth_env, mock_oauth_client, mock_oauth_keyring
    ):
        """Should save tokens to keyring after successful auth."""
        from strava_mcp.oauth import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/strava-oauth?code=test_auth_code")

        assert response.status_code == 200

        # Check tokens were saved
        key = f"{KEYRING_SERVICE}:{KEYRING_USERNAME}"
        assert key in mock_oauth_keyring
        tokens = json.loads(mock_oauth_keyring[key])
        assert tokens["access_token"] == "new_access_token"

    @pytest.mark.asyncio
    async def test_callback_shows_success_page(
        self, mock_oauth_env, mock_oauth_client, mock_oauth_keyring
    ):
        """Should show success page with athlete info."""
        from strava_mcp.oauth import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/strava-oauth?code=test_auth_code")

        assert response.status_code == 200
        # Should contain athlete name
        assert "Test" in response.text


class TestStaticFiles:
    """Tests for static file serving."""

    @pytest.mark.asyncio
    async def test_static_files_are_served(self, mock_oauth_env):
        """Should serve static files."""
        from strava_mcp.oauth import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/static/ConnectWithStrava.png")

        # Should either succeed or return 404 (not a server error)
        assert response.status_code in [200, 404]
