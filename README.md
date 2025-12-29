# Strava MCP Server

An MCP (Model Context Protocol) server that connects Claude to your Strava data. Query your activities, stats, and athlete profile directly from Claude Desktop or any MCP-compatible client.

## Features

- **OAuth Authentication**: Secure authentication with automatic token refresh
- **Activity Data**: Get recent activities, detailed activity info, and stats
- **Athlete Profile**: Access your Strava profile and statistics
- **Secure Storage**: Tokens stored in your system keychain

## Installation

### Prerequisites

1. **Python 3.10+** installed
2. **Strava API Application**: Create one at https://www.strava.com/settings/api
   - Set the "Authorization Callback Domain" to `127.0.0.1`

### Install from GitHub

```bash
pip install git+https://github.com/bronteee/strava-mcp.git
```

Or with uv:

```bash
uv pip install git+https://github.com/bronteee/strava-mcp.git
```

### Configure Claude Desktop

Add to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "strava": {
      "command": "strava-mcp",
      "env": {
        "STRAVA_CLIENT_ID": "your_client_id",
        "STRAVA_CLIENT_SECRET": "your_client_secret"
      }
    }
  }
}
```

If installed with uv, use:

```json
{
  "mcpServers": {
    "strava": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bronteee/strava-mcp.git", "strava-mcp"],
      "env": {
        "STRAVA_CLIENT_ID": "your_client_id",
        "STRAVA_CLIENT_SECRET": "your_client_secret"
      }
    }
  }
}
```

## Usage

### First-Time Authentication

1. Ask Claude: "Connect to my Strava account"
2. Claude will provide an authorization URL
3. Open the URL in your browser and authorize the app
4. Tokens are saved automatically to your system keychain

### Available Tools

| Tool | Description |
|------|-------------|
| `get_auth_status` | Check if you're authenticated |
| `get_auth_url` | Get the Strava authorization URL |
| `authenticate` | Exchange auth code for tokens (usually automatic) |
| `logout` | Remove stored tokens |
| `get_activities` | Get recent activities with optional date filters |
| `get_activity_details` | Get detailed info for a specific activity |
| `get_athlete` | Get your athlete profile |
| `get_athlete_stats` | Get your running/cycling/swimming stats |

### Example Prompts

- "Show me my last 5 Strava activities"
- "What were my running stats this year?"
- "Get details for my most recent ride"
- "How many miles did I run last month?"

## Development

### Setup

```bash
git clone https://github.com/bronteee/strava-mcp.git
cd strava-mcp
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
```

### Run the Server Manually

```bash
# Set environment variables
export STRAVA_CLIENT_ID=your_client_id
export STRAVA_CLIENT_SECRET=your_client_secret

# Run the server
strava-mcp
```

## Security

- Tokens are stored in your system keychain (macOS Keychain, Windows Credential Manager, etc.)
- Client credentials are passed via environment variables, never stored in files
- OAuth flow uses localhost callback - no external servers involved

## License

MIT
