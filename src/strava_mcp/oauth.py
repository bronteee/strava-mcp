"""OAuth callback server for Strava authentication."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from stravalib import Client

from .tokens import save_tokens

load_dotenv(override=True)

# Get the directory where this file is located (for absolute paths)
PACKAGE_DIR = Path(__file__).parent

app = FastAPI()

# Mount static files using absolute path
app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

# Setup templates using absolute path
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")


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


def token_response_to_dict(token_response: Any) -> dict[str, Any]:
    """Convert stravalib token response to a dictionary for storage."""
    return {
        "access_token": token_response["access_token"],
        "refresh_token": token_response["refresh_token"],
        "expires_at": token_response["expires_at"],
    }


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

    c = Client()
    redirect_uri = str(request.url_for("logged_in"))
    url = c.authorization_url(
        client_id=get_client_id(),
        redirect_uri=redirect_uri,
        approval_prompt="auto",
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
    state: str | None = None,  # noqa: ARG001 - OAuth parameter for CSRF protection
    code: str | None = None,
) -> HTMLResponse:
    """Handle OAuth callback from Strava.

    Args:
        request: FastAPI request object.
        error: Error message from Strava if authorization failed.
        state: OAuth state parameter (unused but required by OAuth spec).
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

    if not code:
        return templates.TemplateResponse(
            request=request,
            name="login_error.html",
            context={
                "error": "Missing authorization code. Please try logging in again."
            },
        )

    client = Client()
    token_response = client.exchange_code_for_token(
        client_id=get_client_id(),
        client_secret=get_client_secret(),
        code=code,
    )

    # Convert to dict and save tokens to system keychain for MCP server to use
    tokens = token_response_to_dict(token_response)
    save_tokens(tokens)

    # Get athlete info using the new access token
    authenticated_client = Client(access_token=tokens["access_token"])
    strava_athlete = authenticated_client.get_athlete()

    return templates.TemplateResponse(
        request=request,
        name="login_results.html",
        context={
            "athlete": strava_athlete,
            "access_token": tokens,
            "mcp_ready": True,  # Indicates MCP server can now use these tokens
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5050)
