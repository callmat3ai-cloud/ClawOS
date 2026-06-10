"""
Slash command registry for ClawOS.
Each command is a callable that returns (response_text, handled).
If handled=True, the message is not passed to the LLM.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

log = logging.getLogger("slash_commands")

# Registry: command name → handler function
# Handler signature: (args: str, ctx: SlashContext) → tuple[str, bool]
#   returns (response_text, was_handled)

_registry: dict[str, Callable] = {}


class SlashContext:
    """
    Provides access to ClawOS state for slash command handlers.
    Passed to every handler.
    """

    def __init__(
        self,
        window=None,
        main_app=None,
        executor=None,
        settings_path=None,
    ):
        self.window = window  # ClawOSWindow
        self.main_app = main_app  # ClawOSApp
        self.executor = executor  # StreamingExecutor
        self._settings_path = settings_path

    def _load_settings(self) -> dict:
        try:
            from pathlib import Path
            p = Path(self._settings_path)
            return json.loads(p.read_text()) if p.exists() else {}
        except Exception:
            return {}

    def _save_settings(self, data: dict):
        try:
            from pathlib import Path
            p = Path(self._settings_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.warning(f"Failed to save settings: {e}")

    def _load_keys(self) -> dict:
        try:
            from pathlib import Path
            keys_file = Path(self._settings_path).parent / "api_keys.json"
            return json.loads(keys_file.read_text()) if keys_file.exists() else {}
        except Exception:
            return {}

    def get_model(self) -> str:
        s = self._load_settings()
        return s.get("llm_model", "claude-sonnet-4-6-20250514")

    def get_provider(self) -> str:
        s = self._load_settings()
        return s.get("llm_provider", "anthropic")

    def set_model(self, model: str) -> bool:
        s = self._load_settings()
        s["llm_model"] = model
        self._save_settings(s)
        return True

    def set_provider(self, provider: str) -> bool:
        s = self._load_settings()
        s["llm_provider"] = provider
        self._save_settings(s)
        return True

    def get_providers_info(self) -> list[dict]:
        try:
            from integrations.providers import PROVIDERS
            return [
                {
                    "name": p["name"],
                    "display": p.get("display_name", p["name"]),
                    "default": p.get("default_model", ""),
                }
                for p in PROVIDERS
            ]
        except Exception:
            return []

    def clear_chat(self):
        if self.window:
            try:
                self.window._clear_chat()
            except Exception:
                pass

    def retry_last(self):
        if self.window:
            try:
                self.window._retry_last_message()
            except Exception:
                pass

    def get_memory_usage(self) -> dict:
        try:
            from memory.memory_engine import get_memory_engine
            me = get_memory_engine()
            return {
                "total_tokens": me._total_tokens if hasattr(me, "_total_tokens") else 0,
                "budget": me._budget if hasattr(me, "_budget") else 0,
                "messages": len(me._messages) if hasattr(me, "_messages") else 0,
            }
        except Exception:
            return {"total_tokens": 0, "budget": 0, "messages": 0}

    def get_profile(self) -> str:
        s = self._load_settings()
        return s.get("agent_profile", "claude")

    def set_profile(self, profile: str) -> bool:
        s = self._load_settings()
        s["agent_profile"] = profile
        self._save_settings(s)
        if self.window:
            try:
                self.window._on_agent_profile_changed(profile)
            except Exception:
                pass
        return True

    def available_profiles(self) -> list[str]:
        try:
            from agent.agent_profiles import BUILTIN_PROFILES
            return list(BUILTIN_PROFILES.keys())
        except Exception:
            return ["claude", "architect", "operator", "creative", "minimal"]


def _build_context(window=None, main_app=None, executor=None) -> SlashContext:
    from pathlib import Path
    import sys
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    settings_path = base / "config" / "app_settings_v2.json"
    return SlashContext(
        window=window,
        main_app=main_app,
        executor=executor,
        settings_path=str(settings_path),
    )


# ── Handlers ──────────────────────────────────────────────────────────

def _cmd_model(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Switch model: /model claude-sonnet-4-6-20250514"""
    if not args.strip():
        current = ctx.get_model()
        return f"Current model: `{current}`\n\nUsage: `/model <model_name>`", True
    model = args.strip()
    ctx.set_model(model)
    return f"✅ Model set to: `{model}`", True


def _cmd_provider(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Switch provider: /provider anthropic"""
    if not args.strip():
        current = ctx.get_provider()
        return f"Current provider: `{current}`\n\nUsage: `/provider <name>`", True
    provider = args.strip().lower()
    ctx.set_provider(provider)
    return f"✅ Provider set to: `{provider}`", True


def _cmd_providers(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """List available providers: /providers"""
    providers = ctx.get_providers_info()
    if not providers:
        return "⚠️ Could not load provider list.", True
    lines = ["**Available Providers:**"]
    for p in providers:
        current = "← current" if p["name"] == ctx.get_provider() else ""
        lines.append(f"• `{p['name']}` — {p['display']} {current}")
    return "\n".join(lines), True


def _cmd_streaming(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Toggle or check streaming: /streaming on /streaming off /streaming"""
    s = ctx._load_settings()
    if not args.strip():
        state = s.get("streaming_enabled", True)
        return f"Streaming: **{'ON' if state else 'OFF'}**", True
    arg = args.strip().lower()
    if arg in ("on", "1", "true"):
        s["streaming_enabled"] = True
        ctx._save_settings(s)
        if ctx.window:
            ctx.window._streaming_enabled = True
        return "✅ Streaming **enabled**", True
    elif arg in ("off", "0", "false"):
        s["streaming_enabled"] = False
        ctx._save_settings(s)
        if ctx.window:
            ctx.window._streaming_enabled = False
        return "✅ Streaming **disabled**", True
    return "Usage: `/streaming on` or `/streaming off`", True


def _cmd_clear(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Clear chat: /clear"""
    ctx.clear_chat()
    return "🗑️ Chat cleared.", True


def _cmd_retry(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Retry last message: /retry"""
    ctx.retry_last()
    return "🔄 Retrying last message...", True


def _cmd_memory(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Show memory budget usage: /memory"""
    usage = ctx.get_memory_usage()
    total = usage.get("total_tokens", 0)
    budget = usage.get("budget", 0)
    messages = usage.get("messages", 0)
    pct = f"{(total/budget*100):.1f}%" if budget else "N/A"
    return (
        f"**Memory Stats**\n"
        f"• Messages in context: {messages}\n"
        f"• Tokens used: {total:,}\n"
        f"• Budget: {budget:,}\n"
        f"• Usage: {pct}"
    ), True


def _cmd_profile(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Switch agent profile: /profile architect"""
    profiles = ctx.available_profiles()
    if not args.strip():
        current = ctx.get_profile()
        return (
            f"Current profile: `{current}`\n\n"
            f"Available: {', '.join(f'`{p}`' for p in profiles)}\n\n"
            f"Usage: `/profile <name>`"
        ), True
    profile = args.strip().lower()
    if profile not in profiles:
        return (
            f"Unknown profile: `{profile}`\n\n"
            f"Available: {', '.join(f'`{p}`' for p in profiles)}"
        ), True
    ctx.set_profile(profile)
    return f"✅ Agent profile set to: `{profile}`", True


def _cmd_theme(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Switch theme: /theme dark /theme light"""
    arg = args.strip().lower()
    if arg == "dark":
        if ctx.window:
            ctx.window._apply_theme("dark")
        return "🌑 Theme: **Dark**", True
    elif arg == "light":
        if ctx.window:
            ctx.window._apply_theme("light")
        return "☀️ Theme: **Light**", True
    return "Usage: `/theme dark` or `/theme light`", True


def _cmd_cancel(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Cancel current task: /cancel"""
    if ctx.main_app:
        ctx.main_app._processing = False
        ctx.main_app._pending_executor = None
    if ctx.window:
        ctx.window._set_orb_state("idle")
    return "🚫 Current task cancelled.", True


def _cmd_status(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Show system status: /status"""
    s = ctx._load_settings()
    model = ctx.get_model()
    provider = ctx.get_provider()
    profile = ctx.get_profile()
    streaming = s.get("streaming_enabled", True)
    proactive_status = ""
    try:
        if hasattr(ctx.main_app, "_proactive") and ctx.main_app._proactive:
            ps = ctx.main_app._proactive.get_status()
            proactive_status = (
                f"**Proactive Agent**\n"
                f"• Active: {'YES ⚡' if ps['active'] else 'No'}\n"
                f"• Tasks: {ps['tasks']['active']}/{ps['tasks']['total']}\n"
                f"• Monitors: {ps['monitors']['total']}\n"
                f"• Unread alerts: {ps['alerts']['unread']}\n"
            )
    except Exception:
        proactive_status = ""

    return (
        f"**ClawOS Status**\n\n"
        f"**Model**\n"
        f"• Provider: `{provider}`\n"
        f"• Model: `{model}`\n"
        f"• Streaming: {'ON' if streaming else 'OFF'}\n\n"
        f"**Agent**\n"
        f"• Profile: `{profile}`\n\n"
        f"{proactive_status}"
        f"**Slash Commands**\n"
        f"`/model` `/provider` `/providers` `/streaming`\n"
        f"`/clear` `/retry` `/cancel` `/status`\n"
        f"`/memory` `/profile` `/theme` `/yolo`\n"
        f"`/cron` `/monitor` `/help`"
    ), True


def _cmd_help(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Show all slash commands: /help"""
    return (
        "**ClawOS Slash Commands**\n\n"
        "**Model & Provider**\n"
        "• `/model <name>` — Switch model\n"
        "• `/provider <name>` — Switch provider\n"
        "• `/providers` — List available providers\n\n"
        "**UI Controls**\n"
        "• `/streaming on/off` — Toggle token streaming\n"
        "• `/theme dark/light` — Switch theme\n"
        "• `/profile <name>` — Switch agent personality\n"
        "• `/clear` — Clear chat history\n"
        "• `/retry` — Retry last message\n"
        "• `/cancel` — Cancel current task\n\n"
        "**Info**\n"
        "• `/status` — Full system status\n"
        "• `/memory` — Memory budget usage\n"
        "• `/help` — Show this menu\n\n"
        "**Proactive**\n"
        "• `/yolo` — Bypass all approvals\n"
        "• `/cron <natural>` — Schedule a task\n"
        "• `/monitor <target> every N` — Create a monitor\n\n"
        "**Quick Examples**\n"
        "• `/model claude-opus-4-7-20250514`\n"
        "• `/provider openai`\n"
        "• `/theme dark`\n"
        "• `/cron every 10 minutes check google.com`"
    ), True


def _cmd_cron(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Schedule a task: /cron every 5 minutes remind me to drink water"""
    if not args.strip():
        return (
            "⏰ Schedule a task from natural language.\n\n"
            "Examples:\n"
            "• `/cron every 5 minutes remind me to drink water`\n"
            "• `/cron daily at 9am check email`\n"
            "• `/cron every Monday at 10am team sync`"
        ), True
    try:
        if hasattr(ctx.main_app, "_proactive") and ctx.main_app._proactive:
            task_id = ctx.main_app._proactive.schedule_task(args, task_type="reminder")
            if task_id:
                return f"✅ Task scheduled: *{args}*\nID: `{task_id}`", True
            return "⚠️ Could not parse that schedule. Try: `every 5 minutes...` or `daily at 9am...`", True
    except Exception as e:
        return f"⚠️ Scheduler error: {e}", True
    return "⚠️ Proactive agent not ready.", True


def _cmd_monitor(args: str, ctx: SlashContext) -> tuple[str, bool]:
    """Create a monitor: /monitor google.com every 10 minutes"""
    if not args.strip():
        return (
            "👁️ Create a URL, file, or process monitor.\n\n"
            "Examples:\n"
            "• `/monitor google.com every 10 minutes`\n"
            "• `/monitor /tmp/log.txt`\n"
            "• `/monitor nginx every 5 minutes`"
        ), True
    # Simple parser: first arg is target, look for "every N minutes/hours"
    import re
    parts = args.strip().split()
    target = parts[0] if parts else ""
    interval = 300  # default 5 min
    m = re.search(r"every\s+(\d+)\s*(minute|minutes|hour|hours|second|seconds)", args)
    if m:
        count = int(m.group(1))
        unit = m.group(2)
        multipliers = {"second": 1, "seconds": 1, "minute": 60, "minutes": 60,
                       "hour": 3600, "hours": 3600}
        interval = count * multipliers.get(unit, 60)
    try:
        if hasattr(ctx.main_app, "_proactive") and ctx.main_app._proactive:
            mid = ctx.main_app._proactive.add_url_monitor(target, interval=interval)
            return f"✅ Monitor created: `{target}` (every {interval//60} min)\nID: `{mid}`", True
    except Exception as e:
        return f"⚠️ Monitor error: {e}", True
    return "⚠️ Proactive agent not ready.", True


# ── Register all commands ─────────────────────────────────────────────

_registry = {
    "model": _cmd_model,
    "provider": _cmd_provider,
    "providers": _cmd_providers,
    "streaming": _cmd_streaming,
    "clear": _cmd_clear,
    "retry": _cmd_retry,
    "memory": _cmd_memory,
    "profile": _cmd_profile,
    "theme": _cmd_theme,
    "cancel": _cmd_cancel,
    "status": _cmd_status,
    "help": _cmd_help,
    "cron": _cmd_cron,
    "monitor": _cmd_monitor,
}


def get_all_commands() -> list[str]:
    """Return sorted list of all registered commands."""
    return sorted(_registry.keys())


def execute_slash_command(
    text: str,
    window=None,
    main_app=None,
    executor=None,
) -> tuple[str, bool]:
    """
    Parse and execute a slash command from user input.
    Returns (response_text, was_handled).
    was_handled=True means don't pass to LLM.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return "", False

    parts = stripped[1:].split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd not in _registry:
        return (
            f"Unknown command: `/{cmd}`\n\n"
            f"Type `/help` to see all available commands."
        ), True

    ctx = _build_context(window=window, main_app=main_app, executor=executor)
    try:
        return _registry[cmd](args, ctx)
    except Exception as e:
        log.error(f"Slash command /{cmd} failed: {e}")
        return f"⚠️ `/.{cmd}` failed: {e}", True
