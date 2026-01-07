"""OAuth callback server for Strava authentication."""

from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from stravalib import Client

from .tokens import (
    get_client_id,
    get_client_secret,
    has_credentials,
    save_tokens,
    token_response_to_dict,
)

load_dotenv(override=True)

# Get the directory where this file is located (for absolute paths)
PACKAGE_DIR = Path(__file__).parent

app = FastAPI()


# =============================================================================
# Security Headers Middleware
# =============================================================================


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
    )
    return response


# =============================================================================
# CSRF Protection - In-Memory State Storage
# =============================================================================

# Thread-safe state storage for CSRF protection
_pending_states: dict[str, float] = {}  # state -> timestamp
_state_lock = threading.Lock()
STATE_TTL_SECONDS = 600  # 10 minutes


def _cleanup_expired_states() -> None:
    """Remove expired states from storage."""
    cutoff = time.time() - STATE_TTL_SECONDS
    expired = [k for k, v in _pending_states.items() if v < cutoff]
    for k in expired:
        del _pending_states[k]


def generate_oauth_state() -> str:
    """Generate a cryptographically secure state parameter for CSRF protection."""
    with _state_lock:
        _cleanup_expired_states()
        state = secrets.token_urlsafe(32)
        _pending_states[state] = time.time()
        return state


def validate_oauth_state(state: str | None) -> bool:
    """Validate and consume an OAuth state parameter.

    Returns True if valid, False otherwise.
    State is single-use - it's removed after validation.
    """
    if not state:
        return False
    with _state_lock:
        _cleanup_expired_states()
        if state not in _pending_states:
            return False
        # Check if expired (should already be cleaned, but double-check)
        if time.time() - _pending_states[state] > STATE_TTL_SECONDS:
            del _pending_states[state]
            return False
        # Valid - consume the state (single-use)
        del _pending_states[state]
        return True


# Mount static files using absolute path
app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

# Setup templates using absolute path
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def login(request: Request) -> HTMLResponse:
    """Render the login page with Strava authorization link."""
    # Check if Strava credentials are configured
    if not has_credentials():
        return templates.TemplateResponse(
            request=request,
            name="login_error.html",
            context={
                "error": (
                    "Strava API credentials not configured. "
                    "Please set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in your .env file. "
                    "Get these from https://www.strava.com/settings/api"
                )
            },
        )

    # Generate CSRF protection state
    state = generate_oauth_state()

    client = Client()
    redirect_uri = str(request.url_for("logged_in"))
    url = client.authorization_url(
        client_id=get_client_id(),
        redirect_uri=redirect_uri,
        approval_prompt="auto",
        state=state,
    )
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"authorize_url": url},
    )


@app.get("/strava-oauth", response_class=HTMLResponse)
def logged_in(
    request: Request,
    error: str | None = None,
    state: str | None = None,
    code: str | None = None,
) -> HTMLResponse:
    """Handle OAuth callback from Strava.

    Args:
        request: FastAPI request object.
        error: Error message from Strava if authorization failed.
        state: OAuth state parameter for CSRF protection.
        code: Authorization code from Strava.

    Returns:
        HTML response showing success or error.
    """
    if error:
        return templates.TemplateResponse(
            request=request,
            name="login_error.html",
            context={"error": error},
        )

    # Validate CSRF state parameter
    if not validate_oauth_state(state):
        return templates.TemplateResponse(
            request=request,
            name="login_error.html",
            context={
                "error": (
                    "Invalid or expired OAuth state. This could be a CSRF attack "
                    "or your session expired. Please try logging in again."
                )
            },
        )

    if not code:
        return templates.TemplateResponse(
            request=request,
            name="login_error.html",
            context={
                "error": "Missing authorization code. Please try logging in again."
            },
        )

    # Exchange code for tokens with error handling
    try:
        client = Client()
        token_response = client.exchange_code_for_token(
            client_id=get_client_id(),
            client_secret=get_client_secret(),
            code=code,
        )
    except requests.exceptions.HTTPError as e:
        error_msg = "Failed to exchange authorization code for tokens."
        if e.response is not None:
            if e.response.status_code == 400:
                error_msg = "Invalid or expired authorization code. Please try logging in again."
            elif e.response.status_code == 401:
                error_msg = "Invalid client credentials. Check your STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET."
        return templates.TemplateResponse(
            request=request,
            name="login_error.html",
            context={"error": error_msg},
        )
    except requests.exceptions.ConnectionError:
        return templates.TemplateResponse(
            request=request,
            name="login_error.html",
            context={
                "error": "Unable to connect to Strava. Please check your internet connection."
            },
        )
    except requests.exceptions.Timeout:
        return templates.TemplateResponse(
            request=request,
            name="login_error.html",
            context={"error": "Connection to Strava timed out. Please try again."},
        )
    except Exception as e:
        return templates.TemplateResponse(
            request=request,
            name="login_error.html",
            context={"error": f"An unexpected error occurred: {e}"},
        )

    # Convert to dict and save tokens in memory for MCP server to use
    tokens = token_response_to_dict(token_response)
    save_tokens(tokens)

    # Get athlete info using the new access token
    try:
        authenticated_client = Client(access_token=tokens["access_token"])
        strava_athlete = authenticated_client.get_athlete()
    except Exception:
        # Tokens saved successfully, but couldn't get athlete info
        # Still show success since authentication worked
        strava_athlete = None

    return templates.TemplateResponse(
        request=request,
        name="login_results.html",
        context={
            "athlete": strava_athlete,
            "mcp_ready": True,  # Indicates MCP server can now use these tokens
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5050)
