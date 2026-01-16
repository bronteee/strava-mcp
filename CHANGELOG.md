# Changelog

## 2026-01-16

### Activity Editing

Added ability to update activity notes/description:

- `update_activity_notes` - Update the notes/description of an activity

**Breaking change**: OAuth scope now includes `activity:write`. Existing users will need to re-authenticate to use the new tool.

### Contributors

- Claude Opus 4.5

---

## 2026-01-14

### Community Features

Added 8 new tools for Strava's social and community features:

**Clubs**
- `get_my_clubs` - List clubs you're a member of
- `get_club` - Get detailed club information
- `get_club_members` - List members of a club
- `get_club_activities` - Recent activities from club members

**Engagement**
- `get_activity_kudos` - See who gave kudos to an activity
- `get_activity_comments` - Get comments on an activity

**Social**
- `get_my_koms` - Your KOMs (King/Queen of the Mountain) and CRs
- `get_starred_segments` - Your starred segments

All tools include Strava web/app deeplinks and follow existing patterns for async handling, error handling, and input validation.

### Contributors

- bronte-audere
- Claude Opus 4.5

---

## 2026-01-07

### Security Hardening

The `strava-mcp` server got a major security overhaul! CSRF protection now guards the OAuth flow with in-memory state storage, and we've added security headers middleware including `X-Frame-Options`, `Content-Security-Policy`, and `Referrer-Policy`. Token exposure in HTML templates has been removed.

### New Features

- **Graceful error handling** - New decorator wraps Strava API calls with structured error responses instead of crashing the MCP session
- **Thread-safe token refresh** - `threading.Lock` prevents race conditions during concurrent token refresh attempts
- **Input validation** - All MCP tools now validate inputs before making API calls
- **Type-safe tokens** - `TokenDict` TypedDict ensures compile-time type checking
- **PEP 561 compliance** - Added `py.typed` marker for downstream type checkers

### Code Quality

- Consolidated shared functions into `tokens.py` (goodbye, code duplication!)
- Wrapped blocking `stravalib` calls with `asyncio.to_thread` for proper async handling
- Removed unused `OAuthServerManager` methods

### Impact

9 files changed, 506 insertions, 187 deletions across OAuth, server, tokens, and tests

### Contributors

- bronte-audere
- Claude Opus 4.5
