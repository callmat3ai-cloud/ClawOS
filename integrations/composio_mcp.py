"""
integrations/composio_mcp.py — ClawOS Composio MCP Integration

One API key → 500+ app integrations.
OAuth held server-side by Composio.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

_http = None
_HTTP_OK = False

try:
    import httpx as _http
    _HTTP_OK = True
except ImportError:
    try:
        import requests as _http
        _HTTP_OK = True
    except ImportError:
        _http = None
        _HTTP_OK = False

_LOCK = threading.Lock()


def _base_dir() -> Path:
    frozen = getattr(sys := __import__("sys").modules["sys"], "frozen", False)
    if frozen:
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_config_dir() -> Path:
    return _base_dir() / "config"


def get_api_key() -> str | None:
    """Load Composio API key from config/api_keys.json."""
    config_file = _get_config_dir() / "api_keys.json"
    if not config_file.exists():
        return None
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
        key = data.get("composio_api_key", "") or data.get("COMPOSIO_API_KEY", "")
        return key.strip() or None
    except Exception:
        return None


def get_server_url() -> str:
    """Get the per-server MCP URL (OAuth) or unified endpoint."""
    config_file = _get_config_dir() / "api_keys.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            return data.get("composio_server_url", "https://connect.composio.dev/mcp")
        except Exception:
            pass
    return "https://connect.composio.dev/mcp"


class ComposioMCP:
    """
    Composio MCP client — wraps all 500+ integrations behind one connector.

    Usage:
        composio = ComposioMCP()
        tools = composio.list_tools()          # All available tools
        result = composio.execute(action, params)  # Execute a tool
    """

    def __init__(self, api_key: str | None = None, server_url: str | None = None):
        self._api_key = api_key or get_api_key()
        self._server_url = server_url or get_server_url()
        self._tools_cache: list[dict] | None = None
        self._connected_apps: list[str] = []

    @property
    def connected(self) -> bool:
        return bool(self._api_key)

    # ── Tool catalog ────────────────────────────────────────────

    def list_tools(self, force_refresh: bool = False) -> list[dict]:
        """Return all available Composio tools. Cached unless force_refresh=True."""
        with _LOCK:
            if self._tools_cache and not force_refresh:
                return self._tools_cache

        if not self._api_key:
            return [{"name": "composio_error", "description": "Composio API key not configured"}]

        # Call Composio's tool listing endpoint
        tools = self._fetch_tools_from_api()
        with _LOCK:
            self._tools_cache = tools
        return tools

    def _fetch_tools_from_api(self) -> list[dict]:
        """Fetch available tools from Composio MCP server."""
        if not _HTTP_OK:
            return [{"name": "error", "description": "httpx/requests not installed"}]

        try:
            # Try Composio's tool list endpoint
            resp = _http.post(
                f"{self._server_url}/tools",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                raw = data.get("tools", data.get("data", []))
                return self._normalize_tools(raw)

            # Try the actions endpoint
            resp2 = _http.post(
                f"{self._server_url}/actions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={},
                timeout=15,
            )
            if resp2.status_code == 200:
                data2 = resp2.json()
                return self._normalize_tools(data2.get("actions", data2.get("data", [])))
        except Exception as e:
            pass

        # Fallback: curated tool catalog from known Composio integrations
        return self._curated_tool_catalog()

    def _normalize_tools(self, raw: list) -> list[dict]:
        tools = []
        for item in raw:
            if isinstance(item, dict):
                tools.append({
                    "name": item.get("name", item.get("action", "unknown")),
                    "description": item.get("description", item.get("title", "")),
                    "app": item.get("app", item.get("provider", "unknown")),
                    "category": self._categorize_tool(item.get("name", "")),
                })
        return tools

    def _categorize_tool(self, name: str) -> str:
        name_l = name.lower()
        categories = {
            "Communication": ["gmail", "slack", "discord", "whatsapp", "telegram", "outlook", "email"],
            "Productivity": ["calendar", "notion", "linear", "asana", "jira", "trello", "todoist", "monday"],
            "Documents": ["docs", "sheets", "drive", "dropbox", "onedrive", "confluence", "sharepoint"],
            "Social": ["twitter", "linkedin", "instagram", "facebook", "reddit", "tiktok"],
            "Development": ["github", "gitlab", "vercel", "netlify", "circleci", "railway"],
            "Media": ["spotify", "youtube", "figma", "canva", "obsidian", "twitch"],
            "Finance": ["stripe", "paypal", "xero", "quickbooks", "hubspot", "salesforce"],
            "Research": ["arxiv", "pubmed", "scholar"],
        }
        for cat, keywords in categories.items():
            if any(k in name_l for k in keywords):
                return cat
        return "Other"

    def _curated_tool_catalog(self) -> list[dict]:
        """Fallback curated catalog when API is unreachable."""
        return [
            # Communication
            {"name": "gmail.search_emails", "description": "Search Gmail inbox", "app": "Gmail", "category": "Communication"},
            {"name": "gmail.send_email", "description": "Send email via Gmail", "app": "Gmail", "category": "Communication"},
            {"name": "gmail.get_recent", "description": "Get recent emails", "app": "Gmail", "category": "Communication"},
            {"name": "slack.send_message", "description": "Send Slack message", "app": "Slack", "category": "Communication"},
            {"name": "slack.get_channels", "description": "List Slack channels", "app": "Slack", "category": "Communication"},
            {"name": "discord.send_message", "description": "Send Discord message", "app": "Discord", "category": "Communication"},
            # Productivity
            {"name": "calendar.get_events", "description": "Get calendar events", "app": "Google Calendar", "category": "Productivity"},
            {"name": "calendar.create_event", "description": "Create calendar event", "app": "Google Calendar", "category": "Productivity"},
            {"name": "notion.create_page", "description": "Create Notion page", "app": "Notion", "category": "Productivity"},
            {"name": "notion.query_database", "description": "Query Notion database", "app": "Notion", "category": "Productivity"},
            {"name": "linear.create_issue", "description": "Create Linear issue", "app": "Linear", "category": "Productivity"},
            {"name": "linear.list_issues", "description": "List Linear issues", "app": "Linear", "category": "Productivity"},
            {"name": "asana.create_task", "description": "Create Asana task", "app": "Asana", "category": "Productivity"},
            # Documents
            {"name": "drive.search_files", "description": "Search Google Drive", "app": "Google Drive", "category": "Documents"},
            {"name": "docs.edit_document", "description": "Edit Google Doc", "app": "Google Docs", "category": "Documents"},
            {"name": "sheets.read_spreadsheet", "description": "Read Google Sheet", "app": "Google Sheets", "category": "Documents"},
            # Social
            {"name": "twitter.post_tweet", "description": "Post a tweet", "app": "Twitter/X", "category": "Social"},
            {"name": "linkedin.create_post", "description": "Post to LinkedIn", "app": "LinkedIn", "category": "Social"},
            # Development
            {"name": "github.list_repos", "description": "List GitHub repos", "app": "GitHub", "category": "Development"},
            {"name": "github.create_issue", "description": "Create GitHub issue", "app": "GitHub", "category": "Development"},
            {"name": "github.create_pr", "description": "Create GitHub PR", "app": "GitHub", "category": "Development"},
            # Media
            {"name": "spotify.play", "description": "Play music on Spotify", "app": "Spotify", "category": "Media"},
            {"name": "spotify.search", "description": "Search Spotify", "app": "Spotify", "category": "Media"},
        ]

    # ── Execute ────────────────────────────────────────────────

    def execute(self, action: str, params: dict | None = None) -> dict:
        """Execute a Composio tool action."""
        params = params or {}
        if not self._api_key:
            return {"error": "Composio API key not configured"}

        # Try real MCP endpoint first
        result = self._call_mcp(action, params)
        if result is not None:
            return result

        return {"error": f"Composio execution failed for: {action}"}

    def _call_mcp(self, action: str, params: dict) -> dict | None:
        """Call Composio MCP server."""
        if not _HTTP_OK:
            return None
        try:
            resp = _http.post(
                f"{self._server_url}/execute",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"action": action, "parameters": params},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                return {"error": "Composio auth failed — check API key in Settings > Integrations"}
            return {"error": f"Composio HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"error": f"Composio call failed: {str(e)[:200]}"}

    def get_tools_for_prompt(self) -> str:
        """Format available tools as LLM context string."""
        tools = self.list_tools()
        if not tools:
            return ""
        lines = ["[COMPOSIO TOOLS — use these when the user asks for app-level actions]\n"]
        current_cat = ""
        for t in sorted(tools, key=lambda x: (x.get("category", ""), x.get("name", ""))):
            cat = t.get("category", "Other")
            if cat != current_cat:
                lines.append(f"\n  [{cat}]")
                current_cat = cat
            lines.append(f"  • {t['name']}: {t.get('description', '')}")
        return "\n".join(lines)


# Singleton
_composio: ComposioMCP | None = None


def get_composio() -> ComposioMCP:
    global _composio
    if _composio is None:
        _composio = ComposioMCP()
    return _composio


def is_configured() -> bool:
    return bool(get_api_key())
