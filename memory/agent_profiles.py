"""
memory/agent_profiles.py — ClawOS Agent Profiles

Layer 2: Agent personality profiles that control AI behavior,
tone, model preference, and tool bias.
Layer 1 (User Profiles) is handled by profile_manager.py.
"""
from __future__ import annotations

import json
from pathlib import Path

_LOCK = None  # placeholder for threading import


def _base_dir() -> Path:
    frozen = getattr(sys := __import__("sys").modules["sys"], "frozen", False)
    if frozen:
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _profiles_dir() -> Path:
    return _base_dir() / "profiles"


def _agent_profiles_file() -> Path:
    return _profiles_dir() / "agent_profiles.json"


# ── Built-in Agent Profiles ────────────────────────────────────

BUILT_IN_AGENTS = {
    "professional": {
        "id": "professional",
        "name": "Professional",
        "emoji": "💼",
        "description": "Formal, business-focused. Uses concise, precise language.",
        "system_prompt": (
            "You are ClawOS Professional — a highly efficient, business-focused AI assistant. "
            "Your communication style: formal but warm, precise, and results-oriented. "
            "You prioritize actionable insights over verbose explanations. "
            "When given a task, you execute it directly and report outcomes clearly. "
            "You never use filler phrases. You do not make excuses. You deliver."
        ),
        "model_preference": "gemini-2.5-flash",
        "preferred_tools": ["composio_gmail", "composio_calendar", "composio_drive", "web_search"],
        "tone": "formal",
        "max_steps": 5,
    },
    "casual": {
        "id": "casual",
        "name": "Casual",
        "emoji": "😎",
        "description": "Friendly, relaxed, conversational. Asks clarifying questions.",
        "system_prompt": (
            "You are ClawOS Casual — a friendly, approachable AI companion. "
            "Your communication style: relaxed, warm, and conversational. "
            "You're like a smart friend who's always ready to help. "
            "You use natural language, occasional humor, and keep things light. "
            "You're not afraid to ask questions or share ideas. "
            "Your goal is to make interactions feel easy and enjoyable."
        ),
        "model_preference": "gemini-2.5-flash",
        "preferred_tools": ["composio_slack", "composio_discord", "chat"],
        "tone": "casual",
        "max_steps": 6,
    },
    "technical": {
        "id": "technical",
        "name": "Technical",
        "emoji": "⚙️",
        "description": "Developer-focused. Code-heavy, precise, architecture-minded.",
        "system_prompt": (
            "You are ClawOS Technical — a senior software engineer and technical architect. "
            "Your communication style: precise, technical, and code-first. "
            "You think in systems, APIs, and data flows. "
            "You write production-quality code with error handling and edge cases. "
            "You explain trade-offs, complexity, and best practices. "
            "You prefer working solutions over theoretical ones. "
            "When something is ambiguous, you make reasonable assumptions and state them clearly."
        ),
        "model_preference": "gemini-2.5-pro",
        "preferred_tools": ["code_helper", "dev_agent", "composio_github", "composio_linear"],
        "tone": "technical",
        "max_steps": 8,
    },
    "creative": {
        "id": "creative",
        "name": "Creative",
        "emoji": "🎨",
        "description": "Brainstorming, design-focused. Explores ideas freely.",
        "system_prompt": (
            "You are ClawOS Creative — an imaginative, design-forward AI collaborator. "
            "Your communication style: expansive, curious, and visually aware. "
            "You explore multiple angles before converging on solutions. "
            "You understand aesthetics, UX, and the emotional impact of design choices. "
            "You brainstorm freely, build on ideas, and aren't afraid of bold suggestions. "
            "You think in possibilities, not constraints. "
            "When a user describes a problem, you see the creative opportunity in it."
        ),
        "model_preference": "gemini-2.5-flash",
        "preferred_tools": ["office_builder", "composio_canva", "web_search", "file_controller"],
        "tone": "creative",
        "max_steps": 6,
    },
    "assistant": {
        "id": "assistant",
        "name": "Assistant",
        "emoji": "🤖",
        "description": "General-purpose helper. Balanced, helpful, always learning.",
        "system_prompt": (
            "You are ClawOS — a calm, direct, and highly capable AI assistant. "
            "You are concise, practical, and always focused on getting the job done. "
            "You adapt your tone to the situation: formal when needed, casual when appropriate. "
            "You use the right tools for the job, and you're always learning from interactions. "
            "You do not over-explain. You show working results. "
            "When you're unsure, you ask one clarifying question instead of guessing."
        ),
        "model_preference": "gemini-2.5-flash",
        "preferred_tools": ["web_search", "file_controller", "browser_control", "composio_gmail"],
        "tone": "balanced",
        "max_steps": 5,
    },
}


def list_agent_profiles() -> list[dict]:
    """Return all available agent profiles (built-in + custom)."""
    agents = list(BUILT_IN_AGENTS.values())

    # Load custom profiles
    custom_file = _agent_profiles_file()
    if custom_file.exists():
        try:
            custom = json.loads(custom_file.read_text(encoding="utf-8"))
            if isinstance(custom, list):
                for a in custom:
                    if a.get("id") and a["id"] not in BUILT_IN_AGENTS:
                        agents.append(a)
        except Exception:
            pass

    return agents


def get_agent_profile(profile_id: str) -> dict | None:
    """Get a specific agent profile by ID."""
    if profile_id in BUILT_IN_AGENTS:
        return BUILT_IN_AGENTS[profile_id]
    custom_file = _agent_profiles_file()
    if custom_file.exists():
        try:
            custom = json.loads(custom_file.read_text(encoding="utf-8"))
            if isinstance(custom, list):
                for a in custom:
                    if a.get("id") == profile_id:
                        return a
        except Exception:
            pass
    return None


def get_active_agent() -> str:
    """Get the currently active agent profile id."""
    state_file = _profiles_dir() / "agent_state.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8")).get("active_agent", "assistant")
        except Exception:
            pass
    return "assistant"


def set_active_agent(agent_id: str) -> bool:
    """Switch to a different agent profile."""
    if get_agent_profile(agent_id) is None:
        return False
    _profiles_dir().mkdir(parents=True, exist_ok=True)
    state_file = _profiles_dir() / "agent_state.json"
    state_file.write_text(json.dumps({"active_agent": agent_id}, indent=2))
    return True


def create_agent_profile(
    name: str,
    system_prompt: str,
    model_preference: str = "gemini-2.5-flash",
    emoji: str = "🧑‍💻",
    description: str = "",
    tone: str = "balanced",
    preferred_tools: list[str] | None = None,
) -> str:
    """Create a custom agent profile. Returns the new profile id."""
    import uuid
    import threading
    with threading.Lock():
        pid = name.lower().replace(" ", "_") + "_" + uuid.uuid4().hex[:6]

        custom_file = _agent_profiles_file()
        _profiles_dir().mkdir(parents=True, exist_ok=True)

        existing = []
        if custom_file.exists():
            try:
                existing = json.loads(custom_file.read_text(encoding="utf-8"))
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []

        new_profile = {
            "id": pid,
            "name": name,
            "emoji": emoji,
            "description": description,
            "system_prompt": system_prompt,
            "model_preference": model_preference,
            "preferred_tools": preferred_tools or [],
            "tone": tone,
            "max_steps": 5,
            "custom": True,
        }
        existing.append(new_profile)
        custom_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        return pid


def get_system_prompt_for_agent(agent_id: str | None = None) -> str:
    """Get the system prompt for the active (or specified) agent profile."""
    if agent_id is None:
        agent_id = get_active_agent()
    profile = get_agent_profile(agent_id)
    if profile:
        return profile["system_prompt"]
    return BUILT_IN_AGENTS["assistant"]["system_prompt"]


def format_agent_context_for_prompt() -> str:
    """Format active agent info as context for LLM prompts."""
    agent_id = get_active_agent()
    profile = get_agent_profile(agent_id)
    if not profile:
        return ""
    return (
        f"[AGENT MODE: {profile['emoji']} {profile['name']}] "
        f"Tone: {profile['tone']} | "
        f"Model: {profile['model_preference']} | "
        f"Focus: {profile['description']}"
    )
