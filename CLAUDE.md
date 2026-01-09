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
