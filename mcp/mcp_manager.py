"""
MCP Server Manager — dynamic MCP server loading, connection management,
and tool registry for the ClawOS MCP integration.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("mcp_manager")


def _base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
CONFIG_DIR = BASE_DIR / "config"


def _load_settings() -> dict:
    f = CONFIG_DIR / "app_settings_v2.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _save_settings(data: dict):
    f = CONFIG_DIR / "app_settings_v2.json"
    f.write_text(json.dumps(data, indent=2))


# ── MCP Server Types ─────────────────────────────────────────────

@dataclass
class MCPServer:
    id: str
    name: str
    url: str
    api_key: str
    transport: str = "http"     # "http" | "stdio"
    enabled: bool = True
    connected: bool = False
    last_error: str = ""
    tool_count: int = 0
    connected_at: str = ""


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict
    server_id: str


# ── HTTP MCP Client ───────────────────────────────────────────────

class HTTP_MCP_Client:
    """HTTP-based MCP client for connecting to remote MCP servers."""

    def __init__(self, url: str, api_key: str = ""):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self._session_id: str | None = None

    def connect(self) -> dict:
        """Initialize MCP session."""
        try:
            import requests

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            resp = requests.post(
                f"{self.url}/initialize",
                headers=headers,
                json={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"roots": {"listChanged": True}, "sampling": {}},
                    "clientInfo": {"name": "ClawOS", "version": "2.0"},
                },
                timeout=10,
            )

            if resp.status_code == 200:
                data = resp.json()
                self._session_id = data.get("sessionId", "")
                return {"success": True, "session_id": self._session_id, "server_info": data.get("serverInfo", {})}
            return {"success": False, "error": f"HTTP {resp.status_code}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_tools(self) -> list[MCPTool]:
        """List available tools from the MCP server."""
        try:
            import requests

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id

            resp = requests.post(
                f"{self.url}/tools/list",
                headers=headers,
                json={},
                timeout=10,
            )

            if resp.status_code != 200:
                return []

            data = resp.json()
            return [
                MCPTool(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server_id=getattr(self, "_server_id", ""),
                )
                for t in data.get("tools", [])
            ]

        except Exception as e:
            log.warning(f"MCP list_tools error: {e}")
            return []

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a tool on the MCP server."""
        try:
            import requests

            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id

            resp = requests.post(
                f"{self.url}/tools/call",
                headers=headers,
                json={
                    "name": tool_name,
                    "arguments": arguments,
                },
                timeout=30,
            )

            if resp.status_code == 200:
                return {"success": True, "result": resp.json()}
            return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def ping(self) -> bool:
        """Health check."""
        try:
            import requests
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            resp = requests.get(f"{self.url}/health", headers=headers, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def disconnect(self):
        self._session_id = None


# ── Stdio MCP Client ─────────────────────────────────────────────

class StdioMCPClient:
    """Stdio-based MCP client for local MCP server processes."""

    def __init__(self, command: str, args: list[str] = None, env: dict = None):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._proc = None
        self._tools: list[MCPTool] = []
        self._server_id = ""

    def connect(self) -> dict:
        """Start the MCP server process and initialize."""
        try:
            import subprocess, json as json_lib

            self._proc = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                text=True,
            )

            # Send initialize request
            req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ClawOS", "version": "2.0"},
                },
            }
            self._send(req)

            # Read response
            resp = self._recv()
            if resp:
                self._server_id = resp.get("result", {}).get("serverInfo", {}).get("name", self.command)
                return {"success": True}
            return {"success": False, "error": "No response from server"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_tools(self) -> list[MCPTool]:
        try:
            import json as json_lib

            req = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }
            self._send(req)
            resp = self._recv()
            if resp:
                self._tools = [
                    MCPTool(
                        name=t.get("name", ""),
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {}),
                        server_id=self._server_id,
                    )
                    for t in resp.get("result", {}).get("tools", [])
                ]
            return self._tools
        except Exception as e:
            log.warning(f"Stdio list_tools error: {e}")
            return []

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        try:
            import json as json_lib

            req = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
            self._send(req)
            resp = self._recv()
            return {"success": True, "result": resp} if resp else {"success": False}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def ping(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def disconnect(self):
        if self._proc:
            self._proc.terminate()
            self._proc = None

    def _send(self, req: dict):
        if self._proc and self._proc.stdin:
            import json
            self._proc.stdin.write(json.dumps(req) + "\n")
            self._proc.stdin.flush()

    def _recv(self) -> dict | None:
        if self._proc and self._proc.stdout:
            import json
            try:
                line = self._proc.stdout.readline()
                if line:
                    return json.loads(line)
            except Exception:
                pass
        return None


# ── MCP Manager ─────────────────────────────────────────────────

class MCPManager:
    """
    Manages MCP server connections — add, remove, connect, disconnect,
    list tools, call tools.
    """

    def __init__(self):
        self._servers: dict[str, MCPServer] = {}
        self._clients: dict[str, HTTP_MCP_Client | StdioMCPClient] = {}
        self._tools: dict[str, list[MCPTool]] = {}  # server_id -> tools
        self._lock = threading.Lock()
        self._load_servers()

    def _load_servers(self):
        """Load saved servers from settings."""
        settings = _load_settings()
        servers = settings.get("mcp_servers", [])

        # Add default Composio server if not present
        default_servers = [
            {
                "id": "composio",
                "name": "Composio",
                "url": "https://backend.composio.dev/v3/mcp/",
                "key": "",
                "transport": "http",
                "enabled": True,
            }
        ]

        all_servers = default_servers + [s for s in servers if s.get("name", "") != "Composio"]

        for srv in all_servers:
            sid = srv.get("id", srv.get("name", "unknown").lower().replace(" ", "_"))
            self._servers[sid] = MCPServer(
                id=sid,
                name=srv.get("name", sid),
                url=srv.get("url", ""),
                api_key=srv.get("key", ""),
                transport=srv.get("transport", "http"),
                enabled=srv.get("enabled", True),
            )

    def _save_servers(self):
        """Persist servers to settings."""
        settings = _load_settings()
        settings["mcp_servers"] = [
            {
                "id": s.id,
                "name": s.name,
                "url": s.url,
                "key": s.api_key,
                "transport": s.transport,
                "enabled": s.enabled,
            }
            for s in self._servers.values()
        ]
        _save_settings(settings)

    def add_server(self, name: str, url: str, api_key: str = "", transport: str = "http") -> str:
        """Add and connect a new MCP server. Returns server ID."""
        sid = name.lower().replace(" ", "_")
        with self._lock:
            self._servers[sid] = MCPServer(
                id=sid,
                name=name,
                url=url,
                api_key=api_key,
                transport=transport,
            )
        self._save_servers()
        self.connect(sid)
        return sid

    def remove_server(self, server_id: str) -> bool:
        """Disconnect and remove a server."""
        with self._lock:
            if server_id in self._clients:
                self._clients[server_id].disconnect()
                del self._clients[server_id]
            if server_id in self._servers:
                del self._servers[server_id]
            if server_id in self._tools:
                del self._tools[server_id]
        self._save_servers()
        return True

    def connect(self, server_id: str) -> bool:
        """Connect to a server and list its tools."""
        with self._lock:
            srv = self._servers.get(server_id)
            if not srv:
                return False

        try:
            if srv.transport == "http":
                client = HTTP_MCP_Client(srv.url, srv.api_key)
            else:
                client = StdioMCPClient(srv.url, env={"API_KEY": srv.api_key})

            result = client.connect()
            if not result.get("success"):
                srv.last_error = result.get("error", "Connection failed")
                srv.connected = False
                return False

            # List tools
            tools = client.list_tools()
            srv.tool_count = len(tools)
            srv.connected = True
            srv.last_error = ""
            srv.connected_at = time.strftime("%Y-%m-%dT%H:%M:%S")

            with self._lock:
                self._clients[server_id] = client
                self._tools[server_id] = tools

            log.info(f"[MCP] Connected to {srv.name} with {len(tools)} tools")
            return True

        except Exception as e:
            srv.last_error = str(e)
            srv.connected = False
            log.warning(f"[MCP] Failed to connect to {server_id}: {e}")
            return False

    def disconnect(self, server_id: str):
        """Disconnect from a server."""
        with self._lock:
            if server_id in self._clients:
                self._clients[server_id].disconnect()
                del self._clients[server_id]
            if server_id in self._servers:
                self._servers[server_id].connected = False
            if server_id in self._tools:
                del self._tools[server_id]

    def connect_all(self):
        """Connect all enabled servers."""
        for sid in list(self._servers.keys()):
            if self._servers[sid].enabled:
                self.connect(sid)

    def disconnect_all(self):
        """Disconnect all servers."""
        for sid in list(self._clients.keys()):
            self.disconnect(sid)

    def list_servers(self) -> list[MCPServer]:
        """List all servers."""
        with self._lock:
            return list(self._servers.values())

    def list_tools(self, server_id: str | None = None) -> list[MCPTool]:
        """List tools from all servers or a specific server."""
        with self._lock:
            if server_id:
                return self._tools.get(server_id, [])
            all_tools = []
            for tools in self._tools.values():
                all_tools.extend(tools)
            return all_tools

    def call_tool(self, server_id: str, tool_name: str, arguments: dict = None) -> dict:
        """Call a tool on a connected server."""
        with self._lock:
            client = self._clients.get(server_id)
            if not client:
                return {"success": False, "error": f"Server '{server_id}' not connected"}

        if hasattr(client, "call_tool"):
            return client.call_tool(tool_name, arguments or {})
        return {"success": False, "error": "Tool calling not supported"}

    def call_tool_by_name(self, tool_name: str, arguments: dict = None) -> dict:
        """Call a tool by name — searches all servers."""
        with self._lock:
            for sid, tools in self._tools.items():
                for tool in tools:
                    if tool.name == tool_name:
                        return self.call_tool(sid, tool_name, arguments)
        return {"success": False, "error": f"Tool '{tool_name}' not found on any server"}

    def get_tools_for_prompt(self) -> str:
        """Format all connected tools as a prompt string for LLM."""
        lines = []
        for sid, tools in self._tools.items():
            srv = self._servers.get(sid)
            srv_name = srv.name if srv else sid
            for tool in tools:
                lines.append(f"  {tool.name}: {tool.description}")
        if not lines:
            return ""
        return "\n[MCP TOOLS AVAILABLE]\n" + "\n".join(lines) + "\n"

    def get_status(self) -> dict:
        """Get connection status of all servers."""
        with self._lock:
            return {
                sid: {
                    "name": srv.name,
                    "connected": srv.connected,
                    "tool_count": srv.tool_count,
                    "last_error": srv.last_error,
                }
                for sid, srv in self._servers.items()
            }


# ── Convenience ─────────────────────────────────────────────────

_MCP_MANAGER: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    global _MCP_MANAGER
    if _MCP_MANAGER is None:
        _MCP_MANAGER = MCPManager()
    return _MCP_MANAGER
