# Project Instructions

## Before Committing

Always run these checks before creating any commit:

```bash
# Lint and format
uv run --extra dev ruff check src/ tests/ --fix
uv run --extra dev ruff format src/ tests/

# Type check
uv run --extra dev ty check src/

# Run tests
uv run --extra dev pytest
```

All checks must pass before committing.

## Development Commands

- **Run server**: `uv run strava-mcp`
- **Run tests**: `uv run --extra dev pytest -v`
- **Lint**: `uv run --extra dev ruff check src/ tests/`
- **Format**: `uv run --extra dev ruff format src/ tests/`
- **Type check**: `uv run --extra dev ty check src/`

## Project Structure

- `src/strava_mcp/` - Main package
  - `server.py` - MCP server with tools
  - `oauth.py` - OAuth callback server
  - `tokens.py` - Token storage and shared config
- `tests/` - Test files

## Key Dependencies

- **stravalib**: Use [stravalib docs](https://stravalib.readthedocs.io/en/stable/reference/api/stravalib.client.Client.html) for Strava API integration
- **FastMCP**: MCP server framework with async tools

## Stravalib Reference

Key Client methods for segments/routes:
- `explore_segments(bounds, activity_type, min_cat, max_cat)` - Search segments in area (returns max 10)
- `get_segment(segment_id)` - Get segment details
- `get_routes(athlete_id, limit)` - List athlete's routes
- `get_route(route_id)` - Get route details
- `get_route_streams(route_id)` - Get route GPS data
