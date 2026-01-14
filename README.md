# Strava MCP Server

An MCP (Model Context Protocol) server that connects Claude to your Strava data. Query your activities, stats, and athlete profile directly from Claude Desktop or any MCP-compatible client.

## Features

- **OAuth Authentication**: Secure authentication with automatic token refresh
- **Activity Data**: Get recent activities, detailed activity info, and stats
- **Athlete Profile**: Access your Strava profile and statistics
- **Segments & Routes**: Explore running segments by location, view route details
- **Clubs & Community**: Browse your clubs, members, and club activities
- **Social**: View kudos, comments, KOMs, and starred segments

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

### Authentication

1. Ask Claude: "Connect to my Strava account"
2. Claude will provide an authorization URL
3. Open the URL in your browser and authorize the app
4. You're connected for the current session

**Note**: Tokens are stored in memory only. You'll need to re-authenticate each time Claude Desktop restarts.

### Available Tools

#### Authentication
| Tool | Description |
|------|-------------|
| `get_auth_status` | Check if you're authenticated |
| `get_auth_url` | Get the Strava authorization URL |
| `authenticate` | Exchange auth code for tokens (usually automatic) |
| `logout` | Remove stored tokens |

#### Activities & Athletes
| Tool | Description |
|------|-------------|
| `get_activities` | Get recent activities with optional date filters |
| `get_activity_details` | Get detailed info for a specific activity |
| `get_athlete` | Get your athlete profile |
| `get_athlete_stats` | Get your running/cycling/swimming stats |

#### Segments & Routes
| Tool | Description |
|------|-------------|
| `geocode_location` | Convert location name to coordinates for segment search |
| `explore_running_segments` | Find running segments in an area |
| `get_segment` | Get detailed segment info with polyline |
| `get_my_routes` | List your created routes |
| `get_route` | Get detailed route info with embedded segments |

#### Clubs & Community
| Tool | Description |
|------|-------------|
| `get_my_clubs` | List clubs you're a member of |
| `get_club` | Get detailed club info |
| `get_club_members` | List members of a club |
| `get_club_activities` | Get recent activities from club members |

#### Social & Engagement
| Tool | Description |
|------|-------------|
| `get_activity_kudos` | See who gave kudos to an activity |
| `get_activity_comments` | Get comments on an activity |
| `get_my_koms` | Get your KOMs (King/Queen of the Mountain) |
| `get_starred_segments` | Get your starred segments |

### Example Prompts

- "Show me my last 5 Strava activities"
- "What were my running stats this year?"
- "Get details for my most recent ride"
- "How many miles did I run last month?"
- "Find running segments near Central Park"
- "What clubs am I in?"
- "Show me who gave kudos on my last run"
- "What are my KOMs?"

## Development

### Setup

```bash
git clone https://github.com/bronteee/strava-mcp.git
cd strava-mcp
uv sync --dev
```

### Run Tests

```bash
uv run pytest
```

### Type Check

```bash
uv run ty check src
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

- Tokens are stored in memory only and cleared when the server stops
- Client credentials are passed via environment variables, never stored in files
- OAuth flow uses localhost callback - no external servers involved

## License

MIT
