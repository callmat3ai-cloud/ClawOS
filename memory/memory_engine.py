"""
Memory Engine — context compression, token budgets, file checkpoints.
Keeps the most relevant memories while staying within budget.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("memory_engine")


def _base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
CHECKPOINT_DIR = BASE_DIR / "checkpoints"


def _load_settings() -> dict:
    f = CONFIG_DIR / "app_settings_v2.json"
    return json.loads(f.read_text()) if f.exists() else {}


# ── Token Estimator ─────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English."""
    return max(1, len(text) // 4)


# ── Memory Compression Engine ────────────────────────────────────────

@dataclass
class CompressedMemory:
    summary: str
    original_size: int
    compressed_size: int
    key: str
    timestamp: str


class MemoryCompressor:
    """
    Compresses old conversation history into summaries.
    Strategy: keep last N messages uncompressed (protected window),
    compress everything older into a summary.
    """

    def __init__(self, threshold: float = 0.5, target_ratio: float = 0.2):
        settings = _load_settings()
        self.threshold = threshold  # compress when usage > threshold%
        self.target_ratio = target_ratio  # target compressed size = original * ratio
        self._compressed: dict[str, CompressedMemory] = {}

    def should_compress(self, total_chars: int, budget_chars: int) -> bool:
        """Return True if compression should run."""
        if budget_chars <= 0:
            return False
        return (total_chars / budget_chars) > self.threshold

    def compress_messages(
        self,
        messages: list[dict],
        protected_count: int = 20,
    ) -> list[dict]:
        """
        Keep last `protected_count` messages, compress the rest.

        Returns:
            protected_messages + [summary_of_old_messages]
        """
        if len(messages) <= protected_count:
            return messages

        protected = messages[-protected_count:]
        older = messages[:-protected_count]

        if not older:
            return messages

        # Build summary text
        summary_text = self._build_summary(older)
        compressed_size = estimate_tokens(summary_text)

        summary_msg = {
            "role": "system",
            "content": f"[Earlier conversation summary ({len(older)} messages compressed): {summary_text}]",
            "compressed": True,
            "original_count": len(older),
            "compressed_tokens": compressed_size,
        }

        return [summary_msg] + protected

    def _build_summary(self, messages: list[dict]) -> str:
        """Build a text summary of old messages."""
        topics = []
        actions = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")[:200]

            if not content:
                continue

            if role == "user":
                # Extract key topics/actions
                words = content.lower().split()
                if any(w in words for w in ["search", "find", "look"]):
                    topics.append(f"searched for: {content[:60]}")
                elif any(w in words for w in ["send", "email", "whatsapp"]):
                    actions.append(f"sent a message")
                elif any(w in words for w in ["remind", "schedule"]):
                    actions.append(f"set a reminder")
                elif any(w in words for w in ["open", "launch", "start"]):
                    actions.append(f"opened an app")
                else:
                    topics.append(content[:80])
            elif role == "assistant":
                if "✅" in content or "complete" in content.lower():
                    pass  # skip status updates

        parts = []
        if topics[:3]:
            parts.append(f"Topics discussed: {'; '.join(topics[:3])}")
        if actions[:3]:
            parts.append(f"Actions taken: {'; '.join(actions[:3])}")

        if not parts:
            parts.append(f"{len(messages)} messages exchanged")

        return " | ".join(parts) if parts else f"{len(messages)} earlier messages"


# ── Token Budget Manager ─────────────────────────────────────────────

@dataclass
class BudgetStatus:
    total_budget: int
    used_chars: int
    protected_chars: int
    compressible_chars: int
    within_budget: bool
    compression_needed: bool


class MemoryBudget:
    """
    Tracks memory usage against budget.
    Ensures the system never exceeds the token limit.
    """

    def __init__(self):
        settings = _load_settings()
        self.budget_chars = settings.get("memory_budget", 2200)
        self.protected_recent = settings.get("protected_recent", 20)
        self.auto_compress = settings.get("auto_compression", True)

    def check(self, messages: list[dict]) -> BudgetStatus:
        """Calculate current memory usage vs budget."""
        total = sum(len(m.get("content", "")) for m in messages)

        # Protected recent messages (don't touch these)
        protected = sum(
            len(m.get("content", ""))
            for m in messages[-self.protected_recent:]
        )

        # Compressible = everything before protected window
        compressible = total - protected

        compression_needed = (
            self.auto_compress and
            self.should_compress(total, self.budget_chars)
        )

        return BudgetStatus(
            total_budget=self.budget_chars,
            used_chars=total,
            protected_chars=protected,
            compressible_chars=compressible,
            within_budget=total <= self.budget_chars,
            compression_needed=compression_needed,
        )

    def should_compress(self, total_chars: int, budget_chars: int | None = None) -> bool:
        if budget_chars is None:
            budget_chars = self.budget_chars
        bc = budget_chars or 1
        if bc <= 0:
            return False
        return (total_chars / bc) > 0.5


# ── File Checkpoints ─────────────────────────────────────────────────

@dataclass
class Checkpoint:
    id: str
    timestamp: str
    description: str
    path: str
    size_kb: float


class CheckpointManager:
    """
    Save snapshots of conversation/memory state before major actions.
    Restore if something goes wrong.
    """

    def __init__(self, max_checkpoints: int = 10):
        settings = _load_settings()
        self.max_checkpoints = settings.get("max_checkpoints", 10)
        self._checkpoints: list[Checkpoint] = []
        self._load_index()
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        description: str,
        data: dict,
        profile_id: str = "default",
    ) -> str:
        """Save a checkpoint. Returns checkpoint ID."""
        checkpoint_id = hashlib.md5(
            f"{time.time()}{description}".encode()
        ).hexdigest()[:12]

        ts = datetime.now().isoformat()

        # Save data file
        data_file = CHECKPOINT_DIR / f"{checkpoint_id}.json"
        data_file.write_text(json.dumps(data, indent=2))

        # Add to index
        cp = Checkpoint(
            id=checkpoint_id,
            timestamp=ts,
            description=description,
            path=str(data_file),
            size_kb=data_file.stat().st_size / 1024,
        )
        self._checkpoints.append(cp)
        self._prune()
        self._save_index()

        log.info(f"💾 Checkpoint saved: [{checkpoint_id}] {description}")
        return checkpoint_id

    def save_conversation(
        self,
        messages: list[dict],
        description: str = "conversation snapshot",
    ) -> str:
        """Save current conversation state as checkpoint."""
        return self.save(description, {"messages": messages, "type": "conversation"})

    def save_memory(
        self,
        memories: list[dict],
        description: str = "memory snapshot",
    ) -> str:
        """Save current memory state as checkpoint."""
        return self.save(description, {"memories": memories, "type": "memory"})

    def restore(self, checkpoint_id: str) -> dict | None:
        """Restore a checkpoint by ID. Returns data or None."""
        data_file = CHECKPOINT_DIR / f"{checkpoint_id}.json"
        if not data_file.exists():
            return None
        try:
            return json.loads(data_file.read_text())
        except Exception:
            return None

    def list_checkpoints(self) -> list[Checkpoint]:
        """List all available checkpoints, newest first."""
        return sorted(self._checkpoints, key=lambda c: c.timestamp, reverse=True)

    def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        data_file = CHECKPOINT_DIR / f"{checkpoint_id}.json"
        try:
            data_file.unlink(missing_ok=True)
            self._checkpoints = [c for c in self._checkpoints if c.id != checkpoint_id]
            self._save_index()
            return True
        except Exception:
            return False

    def _prune(self):
        """Remove oldest checkpoints if over limit."""
        while len(self._checkpoints) > self.max_checkpoints:
            oldest = self._checkpoints.pop(0)
            self.delete(oldest.id)

    def _index_file(self) -> Path:
        return CHECKPOINT_DIR / "index.json"

    def _load_index(self):
        idx = self._index_file()
        if not idx.exists():
            return
        try:
            data = json.loads(idx.read_text())
            self._checkpoints = [
                Checkpoint(**c) for c in data.get("checkpoints", [])
            ]
        except Exception:
            pass

    def _save_index(self):
        idx = self._index_file()
        idx.write_text(json.dumps({
            "checkpoints": [
                {"id": c.id, "timestamp": c.timestamp, "description": c.description,
                 "path": c.path, "size_kb": c.size_kb}
                for c in self._checkpoints
            ]
        }, indent=2))


# ── Unified Memory Engine ─────────────────────────────────────────────

class MemoryEngine:
    """
    Unified memory manager combining compression, budgets, and checkpoints.
    Use this instead of raw profile_manager calls.
    """

    def __init__(self):
        self.compressor = MemoryCompressor()
        self.budget = MemoryBudget()
        self.checkpoints = CheckpointManager()

    def format_context(
        self,
        messages: list[dict],
        max_chars: int | None = None,
    ) -> str:
        """
        Format conversation for LLM prompt — respects budget,
        auto-compresses if needed.
        """
        if max_chars is None:
            max_chars = self.budget.budget_chars

        status = self.budget.check(messages)

        # Auto-compress if needed
        if status.compression_needed:
            log.info(f"Memory: compressing {status.compressible_chars} chars (budget: {status.total_budget})")
            messages = self.compressor.compress_messages(
                messages,
                protected_count=self.budget.protected_recent,
            )

        # Build context string
        lines = []
        for msg in messages:
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            is_compressed = msg.get("compressed", False)

            if is_compressed:
                lines.append(f"[Summary] {content}")
            else:
                lines.append(f"{role.upper()}: {content}")

        full_text = "\n".join(lines)

        # Truncate if still over budget
        if len(full_text) > max_chars:
            full_text = full_text[-max_chars:]
            # Find a good cut point
            cut = full_text.find("\n", full_text.find("SYSTEM:"))
            if cut > 0:
                full_text = full_text[cut:]

        return full_text

    def save_checkpoint(
        self,
        checkpoint_type: str,
        data: dict,
        description: str = "",
    ) -> str:
        """Convenience: save a checkpoint."""
        return self.checkpoints.save(f"{checkpoint_type}: {description}", data)


# ── Convenience ────────────────────────────────────────────────────

_MEMORY_ENGINE: MemoryEngine | None = None


def get_memory_engine() -> MemoryEngine:
    global _MEMORY_ENGINE
    if _MEMORY_ENGINE is None:
        _MEMORY_ENGINE = MemoryEngine()
    return _MEMORY_ENGINE


def format_messages_with_budget(messages: list[dict]) -> str:
    """Quick helper for formatting messages within budget."""
    return get_memory_engine().format_context(messages)


def save_conversation_checkpoint(messages: list[dict], description: str = "") -> str:
    """Save conversation checkpoint."""
    return get_memory_engine().save_checkpoint("conversation", {"messages": messages}, description)
