"""
ClawOS v1.0 — Desktop AI Agent
Voice-first. Composio-powered. Futuristic UI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import traceback
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from ui.futuristic_ui import ClawOSWindow, C
from agent.executor import AgentExecutor, ExecutionResult
from integrations.composio_mcp import get_composio, is_configured as composio_configured
from memory.profile_manager import (
    save_memory, recall_memory, format_memory_for_prompt,
    create_session, get_sessions, save_message, get_active_profile,
)
from scheduler.cron_manager import get_cron_manager
from skills.skill_discovery import record_action_sequence, get_discovered_skills

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("clawos")


def get_base_dir() -> Path:
    frozen = getattr(sys, "frozen", False)
    if frozen:
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _load_api_keys() -> dict:
    path = CONFIG_DIR / "api_keys.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_gemini_key() -> str | None:
    return _load_api_keys().get("gemini_api_key", "").strip() or None


def _get_openrouter_key() -> str | None:
    return _load_api_keys().get("openrouter_api_key", "").strip() or None


class ClawOSApp:
    """
    Main ClawOS application controller.
    Bridges the UI, executor, memory, profiles, and scheduler.
    """

    def __init__(self):
        self._executor = AgentExecutor()
        self._current_session_id: str | None = None
        self._processing = False

    def start(self):
        app = QApplication(sys.argv)
        app.setApplicationName("ClawOS")
        app.setStyle("Fusion")

        self.window = ClawOSWindow()
        self.window._profile_manager = self._profile_mgr
        self.window._cron_manager = get_cron_manager()
        self.window._composio = get_composio()

        # Restore cron jobs on startup
        try:
            get_cron_manager().restore_all()
        except Exception as e:
            log.warning(f"Cron restore error: {e}")

        # Set window._profile_manager for callbacks
        from memory.profile_manager import list_profiles, get_active_profile
        self._profile_mgr = list_profiles

        self.window.show()
        self._print_banner()
        sys.exit(app.exec())

    def _print_banner(self):
        print()
        print("  ⚡ CLAWOS v1.0.0")
        print("  Desktop AI Agent — Voice · Composio · Memory · Cron")
        print(f"  Profile: {get_active_profile()}")
        print(f"  Composio: {'✅ Connected' if composio_configured() else '⚠️ No API key (go to Settings)'}")
        print()

    # ── Message processing ────────────────────────────────────

    def process_message(self, text: str, window: ClawOSWindow):
        """Handle incoming user message — planner → executor → response."""
        if self._processing:
            window._add_message("assistant", "⏳ Working on your previous request...")
            return

        self._processing = True
        try:
            # Show processing state
            if hasattr(window, 'voice_orb'):
                window.voice_orb.set_state("processing")

            # Build context
            memory_ctx = format_memory_for_prompt(limit=20)
            composio_ctx = ""
            if composio_configured():
                composio_ctx = get_composio().get_tools_for_prompt()

            # Get model
            api_keys = _load_api_keys()
            gemini_key = api_keys.get("gemini_api_key")
            openrouter_key = api_keys.get("openrouter_api_key")

            # Execute via executor (in thread to not block UI)
            def run_async():
                try:
                    result = self._executor.execute(
                        goal=text,
                        memory_context=memory_ctx,
                        composio_context=composio_ctx,
                        speak_callback=None,
                        gemini_key=gemini_key,
                        openrouter_key=openrouter_key,
                    )
                    # Update UI from main thread
                    QTimer.singleShot(0, lambda: self._on_result(result, text, window))
                except Exception as e:
                    log.error(f"Executor error: {traceback.format_exc()}")
                    QTimer.singleShot(0, lambda: self._on_error(str(e), window))

            thread = threading.Thread(target=run_async, daemon=True)
            thread.start()

        except Exception as e:
            log.error(f"Process error: {e}")
            self._processing = False
            if hasattr(window, 'voice_orb'):
                window.voice_orb.set_state("idle")

    def _on_result(self, result: ExecutionResult, user_text: str, window: ClawOSWindow):
        self._processing = False
        if hasattr(window, 'voice_orb'):
            window.voice_orb.set_state("idle")

        # Save messages
        if self._current_session_id:
            save_message(self._current_session_id, "user", user_text)
            save_message(self._current_session_id, "assistant", result.text)

        # Save memory from this interaction
        try:
            save_memory(
                category="conversation",
                key=f"interaction_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                value=f"User: {user_text[:200]} | ClawOS: {result.text[:200]}",
                confidence=0.8,
                source="auto",
            )
        except Exception:
            pass

        # Record action sequence for skill discovery
        try:
            if result.actions_used:
                record_action_sequence(result.actions_used, user_text[:100])
        except Exception:
            pass

        # Display response
        window._add_message("assistant", result.text or "Done.")

        # Show action results if any
        if result.action_results:
            for ar in result.action_results:
                window._add_message("assistant", f"🔧 {ar}")

    def _on_error(self, error: str, window: ClawOSWindow):
        self._processing = False
        if hasattr(window, 'voice_orb'):
            window.voice_orb.set_state("idle")
        window._add_message("assistant", f"⚠️ Error: {error[:200]}")


def main():
    app = ClawOSApp()
    app.start()


if __name__ == "__main__":
    main()
