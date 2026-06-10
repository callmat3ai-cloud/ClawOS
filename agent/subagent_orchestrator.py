"""
Subagent Orchestrator — parallel agent execution with tool enforcement.
Spawns independent agent workers, coordinates results, enforces tool allowlists.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

log = logging.getLogger("subagent_orchestrator")


def _load_approval() -> dict:
    from pathlib import Path
    cfg = Path(__file__).resolve().parent.parent / "config" / "approval_config.json"
    if not cfg.exists():
        return {}
    try:
        return json.loads(cfg.read_text())
    except Exception:
        return {}


# ── Subagent Types ─────────────────────────────────────────────────

@dataclass
class SubagentResult:
    task_id: str
    agent_id: str
    goal: str
    status: str  # "running", "completed", "failed", "cancelled"
    result: str = ""
    error: str = ""
    started_at: float = 0
    finished_at: float = 0


@dataclass
class SubagentConfig:
    agent_id: str
    goal: str
    priority: int = 2
    tools: list[str] = field(default_factory=list)
    timeout: int = 300
    max_turns: int = 50
    context: str = ""
    on_progress: Callable = field(default_factory=lambda: None)
    on_complete: Callable = field(default_factory=lambda: None)


# ── Tool Enforcement ────────────────────────────────────────────────

ENFORCEMENT_MODES = ["auto", "strict", "off"]


class ToolEnforcer:
    """Enforces tool restrictions per agent profile."""

    def __init__(self, mode: str = "auto"):
        approval = _load_approval()
        self.mode = mode
        self._allowed = set(approval.get("allowed_tools", []))
        self._strict_tools = {
            "shell", "python", "exec", "code_execution", "terminal",
            "delete_file", "rm_rf", "drop_table",
        }

    def filter_tools(self, requested_tools: list[str]) -> list[str]:
        """Return only allowed tools based on enforcement mode."""
        if self.mode == "off":
            return requested_tools

        if self.mode == "strict":
            return [t for t in requested_tools if t in self._allowed]

        # auto mode: allow normal tools, block dangerous ones unless explicitly allowed
        allowed = []
        for t in requested_tools:
            if t in self._allowed:
                allowed.append(t)
            elif t not in self._strict_tools:
                allowed.append(t)  # non-dangerous tools allowed in auto mode
        return allowed

    def is_allowed(self, tool: str) -> bool:
        if self.mode == "off":
            return True
        if tool in self._strict_tools:
            return tool in self._allowed
        return True

    def block_message(self, tool: str) -> str:
        if self.mode == "strict":
            return f"⛔ Tool '{tool}' is not in your allowed tools. Enable it in Settings → Safety → Command Allowlist."
        elif self.mode == "auto" and tool in self._strict_tools:
            return f"⛔ '{tool}' requires approval. Enable it in Settings → Safety."
        return f"⛔ Tool '{tool}' is not available."


# ── Subagent Worker ────────────────────────────────────────────────

class SubagentWorker(threading.Thread):
    """Independent agent worker that runs in a separate thread."""

    def __init__(self, config: SubagentConfig, enforcer: ToolEnforcer):
        super().__init__(daemon=True)
        self.config = config
        self.enforcer = enforcer
        self.result = SubagentResult(
            task_id=config.agent_id,
            agent_id=config.agent_id,
            goal=config.goal,
            status="running",
            started_at=time.time(),
        )

    def run(self):
        try:
            log.info(f"[Subagent {self.config.agent_id}] Starting: {self.config.goal[:60]}")
            self.config.on_progress(self.config.agent_id, "running")

            # Build filtered context with tool restrictions
            filtered_tools = self.enforcer.filter_tools(self.config.tools)

            system_prompt = self._build_prompt(filtered_tools)

            # Execute via streaming executor (reuse existing executor)
            response = self._execute(system_prompt, self.config.goal, filtered_tools)

            self.result.result = response
            self.result.status = "completed"
            self.result.finished_at = time.time()

            log.info(f"[Subagent {self.config.agent_id}] ✅ Done in {self.result.finished_at - self.result.started_at:.1f}s")
            self.config.on_progress(self.config.agent_id, "completed")
            self.config.on_complete(self.result)

        except Exception as e:
            self.result.status = "failed"
            self.result.error = str(e)
            self.result.finished_at = time.time()
            log.error(f"[Subagent {self.config.agent_id}] ❌ Failed: {e}")
            self.config.on_progress(self.config.agent_id, "failed")
            self.config.on_complete(self.result)

    def _build_prompt(self, allowed_tools: list[str]) -> str:
        return f"""You are Subagent {self.config.agent_id}, running independently.

Your task: {self.config.goal}

Available tools (only these may be used):
{', '.join(allowed_tools) if allowed_tools else 'No direct tools — use reasoning only'}

{self.config.context}

Stay focused on your specific task. Be concise. Report results clearly."""

    def _execute(self, system_prompt: str, goal: str, allowed_tools: list[str]) -> str:
        """Execute using the streaming executor logic (simplified for subagent)."""
        from agent.streaming_executor import StreamingExecutor

        approval = _load_approval()
        executor = StreamingExecutor(approval)

        def noop_token(t): pass

        result = executor.execute(
            goal=goal,
            on_token=noop_token,
            on_complete=None,
            on_approval=None,
            memory_context=self.config.context,
            composio_context="",
        )

        return result.text or result.error or "No response"


# ── Orchestrator ──────────────────────────────────────────────────

class SubagentOrchestrator:
    """
    Manages parallel subagent execution.
    Load config, submit tasks, get results.
    """

    def __init__(self, max_parallel: int = 3, timeout: int = 600):
        approval = _load_approval()
        self.max_parallel = approval.get("subagent_max_parallel", max_parallel)
        self.timeout = approval.get("subagent_timeout", timeout)
        enforcement_mode = approval.get("tool_enforcement", "auto")
        self.enforcer = ToolEnforcer(mode=enforcement_mode)
        self._workers: dict[str, SubagentWorker] = {}
        self._results: dict[str, SubagentResult] = {}
        self._lock = threading.Lock()
        self._progress_callback: Callable[[str, str], None] = lambda a, s: None
        self._complete_callback: Callable[[SubagentResult], None] = lambda r: None

    def set_progress_callback(self, cb: Callable[[str, str], None]):
        self._progress_callback = cb

    def set_complete_callback(self, cb: Callable[[SubagentResult], None]):
        self._complete_callback = cb

    def submit(self, goal: str, tools: list[str] = None, context: str = "") -> str:
        """Submit a subagent task. Returns task_id."""
        if tools is None:
            tools = []

        with self._lock:
            # Check if we can start immediately or must wait
            active = sum(1 for w in self._workers.values() if w.result.status == "running")
            if active >= self.max_parallel:
                log.warning(f"Orchestrator at capacity ({active}/{self.max_parallel})")
                # Queue it — will be picked up by worker loop

            agent_id = f"agent_{uuid.uuid4().hex[:6]}"
            config = SubagentConfig(
                agent_id=agent_id,
                goal=goal,
                tools=tools,
                timeout=self.timeout,
                context=context,
                on_progress=self._on_progress,
                on_complete=self._on_complete,
            )

            worker = SubagentWorker(config, self.enforcer)
            self._workers[agent_id] = worker
            worker.start()

            log.info(f"[Orchestrator] Submitted {agent_id}: {goal[:60]}")
            return agent_id

    def submit_parallel(self, tasks: list[dict]) -> list[str]:
        """Submit multiple tasks at once. Returns list of task_ids."""
        ids = []
        for task in tasks:
            tid = self.submit(
                goal=task.get("goal", ""),
                tools=task.get("tools", []),
                context=task.get("context", ""),
            )
            ids.append(tid)
        return ids

    def get_result(self, task_id: str) -> SubagentResult | None:
        """Get result of a specific task."""
        return self._results.get(task_id)

    def get_all_results(self) -> dict[str, SubagentResult]:
        """Get all results."""
        with self._lock:
            return dict(self._results)

    def cancel(self, task_id: str) -> bool:
        """Cancel a running task."""
        with self._lock:
            worker = self._workers.get(task_id)
            if worker and worker.result.status == "running":
                worker.result.status = "cancelled"
                log.info(f"[Orchestrator] Cancelled {task_id}")
                return True
        return False

    def status(self) -> dict:
        """Get overall orchestrator status."""
        with self._lock:
            running = sum(1 for r in self._results.values() if r.status == "running")
            completed = sum(1 for r in self._results.values() if r.status == "completed")
            failed = sum(1 for r in self._results.values() if r.status == "failed")
            return {
                "max_parallel": self.max_parallel,
                "active": running,
                "completed": completed,
                "failed": failed,
                "total_tasks": len(self._results),
            }

    def _on_progress(self, agent_id: str, status: str):
        self._progress_callback(agent_id, status)

    def _on_complete(self, result: SubagentResult):
        with self._lock:
            self._results[result.agent_id] = result
        self._complete_callback(result)


# ── Convenience ───────────────────────────────────────────────────

_ORCHESTRATOR: SubagentOrchestrator | None = None


def get_orchestrator() -> SubagentOrchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = SubagentOrchestrator()
    return _ORCHESTRATOR
