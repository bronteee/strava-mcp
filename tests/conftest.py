"""Pytest fixtures for strava-mcp tests."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from strava_mcp import tokens


@pytest.fixture(autouse=True)
def reset_tokens():
    """Reset in-memory tokens before each test."""
    tokens._tokens = None
    yield
    tokens._tokens = None


@pytest.fixture
def valid_tokens():
    """Return valid (non-expired) tokens."""
    return {
        "access_token": "test_access_token_12345",
        "refresh_token": "test_refresh_token_67890",
        "expires_at": (datetime.now() + timedelta(hours=6)).timestamp(),
        "token_type": "Bearer",
    }


@pytest.fixture
def expired_tokens():
    """Return expired tokens."""
    return {
        "access_token": "expired_access_token",
        "refresh_token": "test_refresh_token_67890",
        "expires_at": (datetime.now() - timedelta(hours=1)).timestamp(),
        "token_type": "Bearer",
    }


@pytest.fixture
def mock_athlete():
    """Return a mock Strava athlete."""
    athlete = MagicMock()
    athlete.id = 12345678
    athlete.firstname = "Test"
    athlete.lastname = "User"
    athlete.city = "San Francisco"
    athlete.state = "CA"
    athlete.country = "United States"
    athlete.sex = "M"
    athlete.premium = True
    athlete.created_at = datetime(2020, 1, 1)
    athlete.updated_at = datetime(2025, 1, 1)
    athlete.model_dump = MagicMock(
        return_value={
            "id": 12345678,
            "firstname": "Test",
            "lastname": "User",
            "city": "San Francisco",
            "state": "CA",
            "country": "United States",
            "sex": "M",
            "premium": True,
        }
    )
    return athlete


@pytest.fixture
def mock_activity():
    """Return a mock Strava activity."""
    activity = MagicMock()
    activity.id = 9876543210
    activity.name = "Morning Run"
    activity.type = "Run"
    activity.distance = 5000.0  # meters
    activity.moving_time = 1800  # seconds
    activity.elapsed_time = 1850
    activity.total_elevation_gain = 50.0
    activity.start_date = datetime(2025, 12, 28, 7, 0, 0)
    activity.start_date_local = datetime(2025, 12, 28, 7, 0, 0)
    activity.average_speed = 2.78  # m/s
    activity.max_speed = 3.5
    activity.average_heartrate = 145
    activity.max_heartrate = 165
    activity.model_dump = MagicMock(
        return_value={
            "id": 9876543210,
            "name": "Morning Run",
            "type": "Run",
            "distance": 5000.0,
            "moving_time": 1800,
            "elapsed_time": 1850,
            "total_elevation_gain": 50.0,
            "start_date": "2025-12-28T07:00:00Z",
            "average_speed": 2.78,
            "max_speed": 3.5,
        }
    )
    return activity


@pytest.fixture
def mock_athlete_stats():
    """Return mock athlete statistics."""
    stats = MagicMock()
    stats.model_dump = MagicMock(
        return_value={
            "recent_run_totals": {
                "count": 10,
                "distance": 50000.0,
                "moving_time": 18000,
                "elevation_gain": 500.0,
            },
            "ytd_run_totals": {
                "count": 150,
                "distance": 750000.0,
                "moving_time": 270000,
                "elevation_gain": 7500.0,
            },
            "all_run_totals": {
                "count": 500,
                "distance": 2500000.0,
                "moving_time": 900000,
                "elevation_gain": 25000.0,
            },
        }
    )
    return stats


@pytest.fixture
def mock_strava_client(
    mock_athlete,
    mock_activity,
    mock_athlete_stats,
    mock_segment,
    mock_segment_explorer_result,
    mock_route,
):
    """Return a fully mocked Strava client."""
    with patch("strava_mcp.server.Client") as mock_client:
        client_instance = MagicMock()

        # Mock get_athlete
        client_instance.get_athlete.return_value = mock_athlete

        # Mock get_activities - returns an iterator
        client_instance.get_activities.return_value = iter([mock_activity])

        # Mock get_activity
        client_instance.get_activity.return_value = mock_activity

        # Mock get_athlete_stats
        client_instance.get_athlete_stats.return_value = mock_athlete_stats

        # Mock explore_segments
        client_instance.explore_segments.return_value = [mock_segment_explorer_result]

        # Mock get_segment
        client_instance.get_segment.return_value = mock_segment

        # Mock get_routes - returns an iterator
        client_instance.get_routes.return_value = iter([mock_route])

        # Mock get_route
        client_instance.get_route.return_value = mock_route

        # Mock update_activity
        updated_activity = MagicMock()
        updated_activity.id = 9876543210
        updated_activity.name = "Morning Run"
        updated_activity.description = "Updated notes"
        client_instance.update_activity.return_value = updated_activity

        # Mock token refresh
        client_instance.refresh_access_token.return_value = {
            "access_token": "refreshed_token",
            "refresh_token": "new_refresh_token",
            "expires_at": (datetime.now() + timedelta(hours=6)).timestamp(),
        }

        # Mock authorization URL
        client_instance.authorization_url.return_value = (
            "https://www.strava.com/oauth/authorize?client_id=123&redirect_uri=..."
        )

        # Mock token exchange
        client_instance.exchange_code_for_token.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_at": (datetime.now() + timedelta(hours=6)).timestamp(),
        }

        # Return mock instance when Client() is called
        mock_client.return_value = client_instance

        yield mock_client


@pytest.fixture
def mock_env_vars():
    """Set up environment variables for tests."""
    with patch.dict(
        "os.environ",
        {
            "STRAVA_CLIENT_ID": "12345",
            "STRAVA_CLIENT_SECRET": "test_client_secret",
        },
    ):
        yield


@pytest.fixture
def mock_segment():
    """Return a mock Strava segment."""
    segment = MagicMock()
    segment.id = 12345
    segment.name = "Test Hill Climb"
    segment.activity_type = "Run"
    segment.distance = 1500.0
    segment.average_grade = 4.5
    segment.maximum_grade = 12.0
    segment.elevation_high = 150.0
    segment.elevation_low = 100.0
    segment.total_elevation_gain = 50.0
    segment.climb_category = 3
    segment.city = "San Francisco"
    segment.state = "CA"
    segment.country = "United States"
    segment.start_latlng = [37.7749, -122.4194]
    segment.end_latlng = [37.7850, -122.4094]
    segment.effort_count = 5000
    segment.athlete_count = 1500
    segment.star_count = 250
    segment.map = MagicMock()
    segment.map.polyline = "encoded_polyline_string"
    return segment


@pytest.fixture
def mock_segment_explorer_result():
    """Return a mock segment explorer result."""
    result = MagicMock()
    result.id = 12345
    result.name = "Test Hill Climb"
    result.climb_category = 3
    result.avg_grade = 4.5
    result.start_latlng = [37.7749, -122.4194]
    result.end_latlng = [37.7850, -122.4094]
    result.elev_difference = 50.0
    result.distance = 1500.0
    return result


@pytest.fixture
def mock_route():
    """Return a mock Strava route."""
    route = MagicMock()
    route.id = 98765
    route.name = "Morning Loop"
    route.description = "A nice morning run route"
    route.distance = 8000.0
    route.elevation_gain = 150.0
    route.type = 1  # Run
    route.sub_type = 1
    route.starred = False
    route.private = False
    route.timestamp = datetime(2025, 1, 1, 10, 0, 0)
    route.map = MagicMock()
    route.map.polyline = "route_polyline_string"
    route.map.summary_polyline = "route_summary_polyline"
    route.segments = []
    return route


@pytest.fixture
def mock_geocoder():
    """Return a mock geocoder."""
    with patch("strava_mcp.server.Nominatim") as mock_nom:
        mock_location = MagicMock()
        mock_location.latitude = 37.7749
        mock_location.longitude = -122.4194
        mock_location.address = "San Francisco, CA, USA"

        mock_geolocator = MagicMock()
        mock_geolocator.geocode.return_value = mock_location

        mock_nom.return_value = mock_geolocator
        yield mock_geolocator
