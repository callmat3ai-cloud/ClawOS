"""
Messaging Hub — incoming message polling for WhatsApp, Telegram, Email, GHL.
Monitors all connected platforms and surfaces incoming messages to the UI.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("messaging_hub")


def _base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
CONFIG_DIR = BASE_DIR / "config"


def _load_keys() -> dict:
    f = CONFIG_DIR / "api_keys.json"
    return json.loads(f.read_text()) if f.exists() else {}


# ── Message Types ─────────────────────────────────────────────────

@dataclass
class IncomingMessage:
    platform: str          # "whatsapp" | "telegram" | "email" | "ghl"
    sender: str            # phone number, username, or email
    sender_name: str        # display name
    body: str               # message text
    timestamp: str          # ISO timestamp
    message_id: str         # platform message ID
    thread_id: str          # conversation/chat ID
    media_url: str = ""     # optional attachment URL


# ── Platform Adapters ─────────────────────────────────────────────

class WhatsAppAdapter:
    """Evolution API v2.3.7 WhatsApp adapter."""

    POLL_INTERVAL = 15  # seconds

    def __init__(self):
        self._last_check: datetime = datetime.now() - timedelta(minutes=5)
        self._seen_ids: set[str] = set()
        self._instance: str = ""

    def configure(self, url: str, api_key: str, instance: str):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self._instance = instance

    def is_configured(self) -> bool:
        return bool(self.url and self.api_key and self._instance)

    def poll(self) -> list[IncomingMessage]:
        """Poll for new messages since last check."""
        if not self.is_configured():
            return []

        try:
            import requests

            # Get messages via Evolution API
            since = self._last_check.strftime("%Y-%m-%dT%H:%M:%S")
            self._last_check = datetime.now()

            resp = requests.get(
                f"{self.url}/message/list",
                params={
                    "instanceName": self._instance,
                    "pageSize": 20,
                },
                headers={"apiKey": self.api_key},
                timeout=10,
            )

            if resp.status_code != 200:
                return []

            data = resp.json()
            messages = []

            for msg in data.get("messages", []):
                msg_id = msg.get("key", {}).get("id", "")
                if msg_id in self._seen_ids:
                    continue
                self._seen_ids.add(msg_id)

                # Only process incoming messages (not sent by us)
                if msg.get("key", {}).get("fromMe", False):
                    continue

                sender = msg.get("key", {}).get("remoteJid", "")
                body = msg.get("message", {}).get("conversation", "")
                if not body:
                    body = msg.get("message", {}).get("extendedTextMessage", {}).get("text", "")

                messages.append(IncomingMessage(
                    platform="whatsapp",
                    sender=sender,
                    sender_name=sender.split("@")[0] if sender else "Unknown",
                    body=body,
                    timestamp=msg.get("messageTimestamp", ""),
                    message_id=msg_id,
                    thread_id=sender,
                ))

            return messages

        except Exception as e:
            log.warning(f"WhatsApp poll error: {e}")
            return []

    def send(self, recipient: str, body: str) -> dict:
        """Send a WhatsApp message."""
        try:
            import requests
            resp = requests.post(
                f"{self.url}/message/sendText/{self._instance}",
                headers={"apiKey": self.api_key},
                json={"number": recipient, "text": body},
                timeout=10,
            )
            return {"success": resp.status_code == 200, "response": resp.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_status(self) -> dict:
        """Check connection status."""
        try:
            import requests
            resp = requests.get(
                f"{self.url}/instance/connectionState/{self._instance}",
                headers={"apiKey": self.api_key},
                timeout=5,
            )
            if resp.status_code == 200:
                state = resp.json().get("state", "unknown")
                return {"connected": state == "open", "state": state}
        except Exception:
            pass
        return {"connected": False, "state": "error"}


class TelegramAdapter:
    """Telegram Bot API adapter."""

    POLL_INTERVAL = 10

    def __init__(self):
        self._offset = 0
        self._seen_ids: set[int] = set()

    def configure(self, bot_token: str):
        self.bot_token = bot_token

    def is_configured(self) -> bool:
        return bool(self.bot_token)

    def poll(self) -> list[IncomingMessage]:
        if not self.is_configured():
            return []

        try:
            import requests

            updates = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/getUpdates",
                params={
                    "offset": self._offset,
                    "timeout": 5,
                    "limit": 10,
                },
                timeout=15,
            ).json()

            messages = []

            for update in updates.get("result", []):
                uid = update.get("update_id", 0)
                if uid in self._seen_ids:
                    continue
                self._seen_ids.add(uid)
                self._offset = uid + 1

                msg = update.get("message", {})
                if not msg:
                    continue

                chat = msg.get("chat", {})
                sender = msg.get("from", {})

                messages.append(IncomingMessage(
                    platform="telegram",
                    sender=str(chat.get("id", "")),
                    sender_name=chat.get("first_name", "Unknown"),
                    body=msg.get("text", ""),
                    timestamp=datetime.fromtimestamp(msg.get("date", 0)).isoformat(),
                    message_id=str(uid),
                    thread_id=str(chat.get("id", "")),
                ))

            return messages

        except Exception as e:
            log.warning(f"Telegram poll error: {e}")
            return []

    def send(self, chat_id: str, body: str) -> dict:
        try:
            import requests
            resp = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": body},
                timeout=10,
            )
            result = resp.json()
            return {"success": result.get("ok", False), "response": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_status(self) -> dict:
        try:
            import requests
            resp = requests.get(
                f"https://api.telegram.org/bot{self.bot_token}/getMe",
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {"connected": data.get("ok", False), "bot_name": data.get("result", {}).get("first_name", "")}
        except Exception:
            pass
        return {"connected": False, "state": "error"}


class EmailAdapter:
    """SMTP/IMAP email adapter."""

    POLL_INTERVAL = 60

    def __init__(self):
        self._last_uid = 0
        self._connected = False

    def configure(self, smtp_host: str, email: str, app_password: str):
        self.smtp_host = smtp_host
        self.email = email
        self.app_password = app_password

    def is_configured(self) -> bool:
        return bool(self.smtp_host and self.email and self.app_password)

    def poll(self) -> list[IncomingMessage]:
        if not self.is_configured():
            return []

        try:
            import imaplib, email as email_lib

            conn = imaplib.IMAP4_SSL(self.smtp_host)
            conn.login(self.email, self.app_password)
            conn.select("INBOX")

            # Search for unseen emails since last check
            status, data = conn.search(None, "UNSEEN")
            if status != "OK":
                return []

            messages = []
            for uid in data[0].split():
                uid_int = int(uid)
                if uid_int <= self._last_uid:
                    continue
                self._last_uid = uid_int

                _, msg_data = conn.fetch(uid, "(RFC822)")
                msg_raw = email_lib.message_from_bytes(msg_data[0][1])

                sender = email_lib.utils.parseaddr(msg_raw.get("From", ""))[1]
                subject = msg_raw.get("Subject", "(no subject)")
                body = self._extract_body(msg_raw)

                messages.append(IncomingMessage(
                    platform="email",
                    sender=sender,
                    sender_name=sender.split("@")[0],
                    body=f"{subject}\n\n{body[:500]}",
                    timestamp=msg_raw.get("Date", ""),
                    message_id=str(uid_int),
                    thread_id=sender,
                ))

            conn.logout()
            return messages

        except Exception as e:
            log.warning(f"Email poll error: {e}")
            return []

    def _extract_body(self, msg) -> str:
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain":
                    try:
                        charset = part.get_content_charset() or "utf-8"
                        body = part.get_payload(decode=True).decode(charset, errors="replace")
                        break
                    except Exception:
                        pass
        else:
            try:
                charset = msg.get_content_charset() or "utf-8"
                body = msg.get_payload(decode=True).decode(charset, errors="replace")
            except Exception:
                pass
        return body[:500]

    def send(self, to: str, subject: str, body: str) -> dict:
        try:
            import smtplib
            from email.message import EmailMessage

            msg = EmailMessage()
            msg["From"] = self.email
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body)

            with smtplib.SMTP(self.smtp_host, 587) as server:
                server.starttls()
                server.login(self.email, self.app_password)
                server.send_message(msg)

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_status(self) -> dict:
        try:
            import imaplib
            conn = imaplib.IMAP4_SSL(self.smtp_host)
            conn.login(self.email, self.app_password)
            conn.logout()
            return {"connected": True, "email": self.email}
        except Exception:
            return {"connected": False, "state": "error"}


class GHLAdapter:
    """GoHighLevel CRM adapter."""

    POLL_INTERVAL = 30

    def __init__(self):
        self.api_key = ""
        self.location_id = ""

    def configure(self, api_key: str, location_id: str):
        self.api_key = api_key
        self.location_id = location_id

    def is_configured(self) -> bool:
        return bool(self.api_key and self.location_id)

    def poll(self) -> list[IncomingMessage]:
        if not self.is_configured():
            return []

        try:
            import requests

            # Get conversations
            resp = requests.get(
                "https://services.leadconnectorhq.com/conversations/search",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Version": "2021-07-28",
                },
                params={
                    "locationId": self.location_id,
                    "limit": 20,
                },
                timeout=10,
            )

            if resp.status_code != 200:
                return []

            messages = []
            for conv in resp.json().get("conversations", []):
                cid = conv.get("id", "")
                for msg in conv.get("messages", []):
                    mid = msg.get("id", "")
                    if msg.get("direction") != "inbound":
                        continue

                    messages.append(IncomingMessage(
                        platform="ghl",
                        sender=msg.get("contactId", ""),
                        sender_name=msg.get("contactName", "Unknown"),
                        body=msg.get("body", ""),
                        timestamp=msg.get("createdAt", ""),
                        message_id=mid,
                        thread_id=cid,
                    ))

            return messages

        except Exception as e:
            log.warning(f"GHL poll error: {e}")
            return []

    def send(self, contact_id: str, body: str) -> dict:
        try:
            import requests
            resp = requests.post(
                "https://services.leadconnectorhq.com/conversations/message",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Version": "2021-07-28",
                    "Content-Type": "application/json",
                },
                json={
                    "locationId": self.location_id,
                    "contactId": contact_id,
                    "type": "SMS",
                    "body": body,
                },
                timeout=10,
            )
            return {"success": resp.status_code in (200, 201), "response": resp.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_status(self) -> dict:
        try:
            import requests
            resp = requests.get(
                "https://services.leadconnectorhq.com/locations/" + self.location_id,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=5,
            )
            return {"connected": resp.status_code == 200}
        except Exception:
            return {"connected": False, "state": "error"}


# ── Messaging Hub ─────────────────────────────────────────────────

class MessagingHub:
    """
    Unified messaging hub that polls all connected platforms.
    Callbacks: on_message, on_status_change
    """

    def __init__(self):
        self._keys = _load_keys()

        self.wa = WhatsAppAdapter()
        self.tg = TelegramAdapter()
        self.email = EmailAdapter()
        self.ghl = GHLAdapter()

        self._configure()

        self.on_message: Callable[[IncomingMessage], None] = lambda m: None
        self.on_status_change: Callable[[str, dict], None] = lambda p, s: None

        self._running = False
        self._poll_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _configure(self):
        """Load credentials and configure adapters."""
        keys = _load_keys()
        self._keys = keys

        self.wa.configure(
            url=keys.get("evolution_api_url", "http://161.97.173.78.nip.io:8081"),
            api_key=keys.get("evolution_api_key", ""),
            instance=keys.get("evolution_instance", "pulkit-wa-final"),
        )

        self.tg.configure(bot_token=keys.get("telegram_bot_token", ""))

        self.email.configure(
            smtp_host=keys.get("smtp_host", ""),
            email=keys.get("smtp_user", ""),
            app_password=keys.get("smtp_pass", ""),
        )

        self.ghl.configure(
            api_key=keys.get("ghl_api_key", ""),
            location_id=keys.get("ghl_location_id", ""),
        )

    def start(self):
        """Start polling all platforms in background thread."""
        if self._running:
            return
        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        log.info("MessagingHub started")

    def stop(self):
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=3)
        log.info("MessagingHub stopped")

    def _poll_loop(self):
        """Background polling loop."""
        while self._running:
            try:
                # Check WhatsApp
                for msg in self.wa.poll():
                    self._handle_message(msg)

                # Check Telegram
                for msg in self.tg.poll():
                    self._handle_message(msg)

                # Check Email (less frequent)
                for msg in self.email.poll():
                    self._handle_message(msg)

                # Check GHL
                for msg in self.ghl.poll():
                    self._handle_message(msg)

            except Exception as e:
                log.error(f"Poll loop error: {e}")

            time.sleep(5)  # Sleep between poll cycles

    def _handle_message(self, msg: IncomingMessage):
        """Handle incoming message — surface to UI."""
        with self._lock:
            ts = datetime.fromisoformat(msg.timestamp).strftime("%H:%M") if msg.timestamp else "??:??"
            log.info(f"[{msg.platform.upper()}] {msg.sender_name}: {msg.body[:60]}")
        self.on_message(msg)

    def send_message(self, platform: str, recipient: str, body: str) -> dict:
        """Send a message via the specified platform."""
        if platform == "whatsapp":
            return self.wa.send(recipient, body)
        elif platform == "telegram":
            return self.tg.send(recipient, body)
        elif platform == "email":
            parts = recipient.split("@")
            if len(parts) == 2:
                return self.email.send(recipient, "ClawOS", body)
            return {"success": False, "error": "Invalid email address"}
        elif platform == "ghl":
            return self.ghl.send(recipient, body)
        else:
            return {"success": False, "error": f"Unknown platform: {platform}"}

    def get_all_status(self) -> dict:
        """Get connection status for all platforms."""
        return {
            "whatsapp": self.wa.get_status(),
            "telegram": self.tg.get_status(),
            "email": self.email.get_status(),
            "ghl": self.ghl.get_status(),
        }

    def is_connected(self, platform: str) -> bool:
        status = self.get_all_status().get(platform, {})
        return status.get("connected", False)


# ── Convenience ──────────────────────────────────────────────────

_MESSAGING_HUB: MessagingHub | None = None


def get_messaging_hub() -> MessagingHub:
    global _MESSAGING_HUB
    if _MESSAGING_HUB is None:
        _MESSAGING_HUB = MessagingHub()
    return _MESSAGING_HUB
