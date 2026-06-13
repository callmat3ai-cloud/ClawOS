"""
Computer Use Tools — screenshot, mouse, keyboard, app launching.
Cross-platform: macOS, Linux, Windows.
"""
from __future__ import annotations

import base64
import logging
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger("computer_use")


class ComputerUseTools:
    """
    Cross-platform computer use: screenshot, mouse, keyboard, app control.

    Usage:
        tools = ComputerUseTools()
        tools.screenshot()
        tools.open_app("Chrome")
        tools.click(500, 300)
        tools.type_text("Hello world")
    """

    def __init__(self):
        self._os = platform.system()
        self._pyautogui_available = False
        self._mss_available = False

        # Try pyautogui
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.1
            self._pyautogui = pyautogui
            self._pyautogui_available = True
            log.info("ComputerUse: pyautogui loaded")
        except ImportError:
            log.warning("pyautogui not installed — run: pip install pyautogui")

        # Try mss for screenshots
        try:
            import mss
            self._mss = mss
            self._mss_available = True
            log.info("ComputerUse: mss loaded")
        except ImportError:
            try:
                from PIL import ImageGrab
                self._ImageGrab = ImageGrab
                self._mss_available = True
                log.info("ComputerUse: PIL.ImageGrab loaded")
            except ImportError:
                log.warning("No screenshot library — install mss or Pillow")

    # ── Screenshot ──────────────────────────────────────────────────────

    def screenshot(self, path: str | None = None) -> str:
        """
        Take a screenshot. Returns path to saved PNG image.
        Falls back to base64-encoded data if no path provided.
        """
        if not self._mss_available:
            return "[Screenshot unavailable — install mss or Pillow]"

        try:
            if path is None:
                fd, path = tempfile.mkstemp(suffix=".png")
                os.close(fd)

            if hasattr(self, "_mss") and hasattr(self._mss, "Screenshot"):
                # mss
                with self._mss.mss() as s:
                    s.shot(output=path)
            else:
                # PIL fallback
                img = self._ImageGrab.grab()
                img.save(path)

            log.info(f"Screenshot saved: {path}")
            return path

        except Exception as e:
            log.error(f"Screenshot failed: {e}")
            return f"[Screenshot error: {e}]"

    def screenshot_base64(self) -> str:
        """Return screenshot as base64-encoded PNG data URI."""
        path = self.screenshot()
        if path.startswith("["):
            return path
        try:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            return f"data:image/png;base64,{data}"
        except Exception as e:
            return f"[Screenshot encode error: {e}]"

    # ── Mouse ──────────────────────────────────────────────────────────

    def click(self, x: int, y: int, button: str = "left") -> str:
        """Click at screen coordinates (x, y). button: 'left', 'right', 'middle'."""
        if not self._pyautogui_available:
            return f"[Mouse control unavailable — pyautogui not installed]"
        try:
            self._pyautogui.click(x, y, button=button)
            log.info(f"Clicked {button} at ({x}, {y})")
            return f"✅ Clicked {button} at ({x}, {y})"
        except Exception as e:
            return f"[Click failed: {e}]"

    def double_click(self, x: int, y: int) -> str:
        """Double-click at (x, y)."""
        if not self._pyautogui_available:
            return "[Mouse control unavailable]"
        try:
            self._pyautogui.doubleClick(x, y)
            return f"✅ Double-clicked at ({x}, {y})"
        except Exception as e:
            return f"[Double-click failed: {e}]"

    def move_mouse(self, x: int, y: int) -> str:
        """Move mouse to (x, y) without clicking."""
        if not self._pyautogui_available:
            return "[Mouse control unavailable]"
        try:
            self._pyautogui.moveTo(x, y)
            return f"✅ Moved mouse to ({x}, {y})"
        except Exception as e:
            return f"[Move failed: {e}]"

    def scroll(self, clicks: int) -> str:
        """Scroll up (positive) or down (negative)."""
        if not self._pyautogui_available:
            return "[Mouse control unavailable]"
        try:
            self._pyautogui.scroll(clicks)
            return f"✅ Scrolled {clicks} units"
        except Exception as e:
            return f"[Scroll failed: {e}]"

    def get_mouse_position(self) -> dict:
        """Return current mouse position as {x, y}."""
        if not self._pyautogui_available:
            return {"error": "pyautogui not available"}
        try:
            x, y = self._pyautogui.position()
            return {"x": x, "y": y}
        except Exception:
            return {"error": "Could not get position"}

    # ── Keyboard ───────────────────────────────────────────────────────

    def type_text(self, text: str, interval: float = 0.05) -> str:
        """Type text using keyboard. Strips markdown/formatting automatically."""
        if not self._pyautogui_available:
            return "[Keyboard control unavailable]"
        try:
            # Clean markdown before typing
            clean = (
                text.replace("**", "").replace("*", "")
                    .replace("`", "").replace("_", "")
                    .replace("#", "").replace('"', '"').replace('"', "'")
            )
            self._pyautogui.write(clean, interval=interval)
            log.info(f"Typed: {clean[:50]}")
            return f"✅ Typed: {clean[:80]}"
        except Exception as e:
            return f"[Type failed: {e}]"

    def press_key(self, key: str) -> str:
        """Press a key by name: enter, tab, escape, space, backspace, etc."""
        if not self._pyautogui_available:
            return "[Keyboard control unavailable]"
        try:
            # Normalize common aliases
            aliases = {
                "return": "enter", "esc": "escape",
                "ctrl": "ctrl", "alt": "alt", "cmd": "command",
            }
            key = aliases.get(key.lower(), key.lower())
            self._pyautogui.press(key)
            log.info(f"Pressed: {key}")
            return f"✅ Pressed: {key}"
        except Exception as e:
            return f"[Press failed: {e}]"

    def hotkey(self, *keys) -> str:
        """Press a combination: e.g. hotkey('cmd', 'c') for copy."""
        if not self._pyautogui_available:
            return "[Keyboard control unavailable]"
        try:
            self._pyautogui.hotkey(*keys)
            return f"✅ Hotkey: {'+'.join(keys)}"
        except Exception as e:
            return f"[Hotkey failed: {e}]"

    def key_down(self, key: str) -> str:
        """Hold a key down."""
        if not self._pyautogui_available:
            return "[Keyboard control unavailable]"
        try:
            self._pyautogui.keyDown(key.lower())
            return f"✅ Key down: {key}"
        except Exception as e:
            return f"[Key down failed: {e}]"

    def key_up(self, key: str) -> str:
        """Release a held key."""
        if not self._pyautogui_available:
            return "[Keyboard control unavailable]"
        try:
            self._pyautogui.keyUp(key.lower())
            return f"✅ Key up: {key}"
        except Exception as e:
            return f"[Key up failed: {e}]"

    # ── App Control ────────────────────────────────────────────────────

    def open_app(self, app_name: str) -> str:
        """Open an application by name."""
        try:
            if self._os == "Darwin":  # macOS
                # Try opening by app name first
                result = subprocess.run(
                    ["open", "-a", app_name],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    log.info(f"Opened app: {app_name}")
                    return f"✅ Opened: {app_name}"
                # Try generic open
                result = subprocess.run(
                    ["open", app_name],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    return f"✅ Opened: {app_name}"
                return f"⚠️ Could not open: {app_name}"

            elif self._os == "Linux":
                result = subprocess.run(
                    ["xdg-open", app_name],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    return f"✅ Opened: {app_name}"
                # Try directly
                result = subprocess.run(
                    [app_name],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    return f"✅ Opened: {app_name}"
                return f"⚠️ Could not open: {app_name}"

            elif self._os == "Windows":
                os.startfile(app_name)
                return f"✅ Opened: {app_name}"

            else:
                return f"⚠️ Unknown OS: {self._os}"

        except subprocess.TimeoutExpired:
            return f"⚠️ App open timed out: {app_name}"
        except FileNotFoundError:
            return f"⚠️ App not found: {app_name} (check the exact name)"
        except Exception as e:
            return f"⚠️ Open failed: {e}"

    def open_url(self, url: str) -> str:
        """Open a URL in the default browser."""
        try:
            if self._os == "Darwin":
                subprocess.run(["open", url], capture_output=True, timeout=10)
            elif self._os == "Linux":
                subprocess.run(["xdg-open", url], capture_output=True, timeout=10)
            elif self._os == "Windows":
                os.startfile(url)
            else:
                return f"⚠️ Unknown OS: {self._os}"
            log.info(f"Opened URL: {url}")
            return f"✅ Opened: {url}"
        except Exception as e:
            return f"⚠️ Open URL failed: {e}"

    def close_window(self) -> str:
        """Close the active window (Cmd+W on Mac, Alt+F4 on Windows)."""
        try:
            if self._os == "Darwin":
                self._pyautogui.hotkey("command", "w")
            elif self._os == "Linux":
                self._pyautogui.hotkey("alt", "f4")
            elif self._os == "Windows":
                self._pyautogui.hotkey("alt", "f4")
            return "✅ Closed active window"
        except Exception as e:
            return f"⚠️ Close window failed: {e}"

    # ── Screen Info ────────────────────────────────────────────────────

    def get_screen_size(self) -> dict:
        """Return primary screen dimensions as {width, height}."""
        try:
            if self._pyautogui_available:
                w, h = self._pyautogui.size()
                return {"width": w, "height": h}
            elif hasattr(self, "_mss") and self._mss_available:
                with self._mss.mss() as s:
                    monitor = s.monitors[0]
                    return {"width": monitor["width"], "height": monitor["height"]}
            return {"error": "No screen info library available"}
        except Exception as e:
            return {"error": str(e)}

    def get_active_window_title(self) -> str:
        """Get title of the currently focused window."""
        try:
            if self._os == "Darwin":
                result = subprocess.run(
                    ["osascript", "-e", 'tell app "System Events" to get name of first process whose frontmost is true'],
                    capture_output=True, text=True, timeout=5
                )
                return result.stdout.strip() or "Unknown"
            elif self._os == "Linux":
                result = subprocess.run(
                    ["xdotool", "getactivewindow", "getwindowname"],
                    capture_output=True, text=True, timeout=5
                )
                return result.stdout.strip() or "Unknown"
            return "[Window title not available on this OS]"
        except Exception:
            return "[Could not get window title]"


# ── Singleton ──────────────────────────────────────────────────────────

_computer_use_tools: ComputerUseTools | None = None


def get_computer_use_tools() -> ComputerUseTools:
    global _computer_use_tools
    if _computer_use_tools is None:
        _computer_use_tools = ComputerUseTools()
    return _computer_use_tools
