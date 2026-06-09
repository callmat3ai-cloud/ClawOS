"""
skills/skill_discovery.py — ClawOS Skill Auto-Discovery

Detects repeated 3+ step action sequences used 3+ times
and auto-generates reusable skill files.
"""
from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_LOCK = threading.Lock()
_MIN_LENGTH = 2          # min steps in sequence
_MIN_COUNT = 3           # min times seen before creating skill
_SKILLS_DIR = Path(__file__).resolve().parent


def _base_dir() -> Path:
    frozen = getattr(sys := __import__("sys").modules["sys"], "frozen", False)
    if frozen:
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


# ── Sequence tracking ─────────────────────────────────────────

_sequence_counts: dict[str, int] = defaultdict(int)
_sequence_examples: dict[str, list] = defaultdict(list)


def record_action_sequence(actions: list[str], context: str = "") -> str | None:
    """
    Record an action sequence. Returns skill name if auto-created, None otherwise.
    Call this from the executor after a successful run.
    """
    if len(actions) < _MIN_LENGTH:
        return None

    # Normalize: sort actions to detect patterns regardless of order
    normalized = tuple(sorted(actions))
    key = " → ".join(normalized)

    with _LOCK:
        _sequence_counts[key] += 1
        if len(_sequence_examples[key]) < 3:
            _sequence_examples[key].append(context or f"Example {_sequence_counts[key]}")

        if _sequence_counts[key] >= _MIN_COUNT:
            return _create_skill(key, actions, context)

    return None


def _create_skill(key: str, actions: list[str], example: str) -> str:
    """Auto-generate a skill file from a detected sequence."""
    safe_name = re.sub(r"[^a-z0-9_]+", "_", key.lower())[:40]
    skill_name = f"auto_{safe_name}"
    skill_path = _SKILLS_DIR / "auto" / f"{skill_name}.py"

    # Don't overwrite existing
    if skill_path.exists():
        return skill_name

    _SKILLS_DIR.joinpath("auto").mkdir(parents=True, exist_ok=True)

    # Build skill function body
    action_calls = "\n    ".join(
        f'result = _exec_action("{a}", params)' for a in actions
    )

    code = f'''"""
Skill: {skill_name}
Auto-discovered from repeated usage pattern: {key}
Generated: {datetime.utcnow().isoformat()}
Usage count threshold: {_MIN_COUNT}
"""
from __future__ import annotations

import json
from pathlib import Path


def run(params: dict | None = None) -> str:
    """
    Auto-discovered skill: {key}
    Example usage: {example[:80]}
    """
    from integrations.composio_mcp import get_composio
    composio = get_composio()

    results = []
    params = params or {{}}

    # Step-by-step execution
{chr(10).join(f'    # Step {i+1}: {a}' for i, a in enumerate(actions))}
{action_calls}
    return json.dumps({{"results": results}}, indent=2)


def _exec_action(action: str, params: dict) -> dict:
    from integrations.composio_mcp import get_composio
    composio = get_composio()
    return composio.execute(action=action, params=params)
'''

    skill_path.write_text(code, encoding="utf-8")
    print(f"[Skills] ✨ New skill discovered: {skill_name}.py")
    return skill_name


def get_discovered_skills() -> list[dict]:
    """Return all auto-discovered skills."""
    auto_dir = _SKILLS_DIR / "auto"
    if not auto_dir.exists():
        return []
    skills = []
    for f in sorted(auto_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        skills.append({
            "name": f.stem,
            "path": str(f),
            "actions": _extract_actions(f),
        })
    return skills


def _extract_actions(path: Path) -> list[str]:
    """Extract action names from a skill file."""
    actions = []
    try:
        text = path.read_text(encoding="utf-8")
        matches = re.findall(r'"([a-z_]+\.[a-z_]+)"', text)
        actions = list(set(matches))
    except Exception:
        pass
    return actions


def get_sequence_stats() -> list[dict]:
    """Return statistics on detected sequences."""
    with _LOCK:
        return [
            {
                "sequence": key,
                "count": count,
                "skill": f"auto_{re.sub(r'[^a-z0-9_]+', '_', key.lower())[:40]}",
            }
            for key, count in sorted(_sequence_counts.items(), key=lambda x: -x[1])
        ]
