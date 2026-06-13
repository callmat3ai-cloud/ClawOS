"""
Web Search Tool — Brave Search API integration.
Free tier: 2000 queries/month. Falls back to mock data when no API key.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger("web_search")

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
API_KEYS_FILE = CONFIG_DIR / "api_keys.json"


def _load_keys() -> dict:
    if not API_KEYS_FILE.exists():
        return {}
    try:
        return json.loads(API_KEYS_FILE.read_text())
    except Exception:
        return {}


def _get_api_key() -> str:
    """Try config file first, then env var."""
    keys = _load_keys()
    key = keys.get("brave_search_api_key", "")
    if key:
        return key
    return os.environ.get("BRAVE_SEARCH_API_KEY", "")


# ── Mock data for when no API key is set ────────────────────────────────

_MOCK_RESULTS = {
    "news": [
        {
            "title": "Anthropic Releases Claude 4 with Extended Memory and Real-Time Reasoning",
            "url": "https://www.anthropic.com/news/claude-4",
            "description": "The latest Claude model features 1M token context, real-time web access, and native agentic tool use built directly into the model architecture.",
            "age": "2 hours ago",
        },
        {
            "title": "OpenAI Launches Operator — AI That Controls Your Browser and Desktop",
            "url": "https://openai.com/operator",
            "description": "Operator lets GPT-5 agents browse the web, fill forms, book appointments, and control desktop applications using computer-use technology.",
            "age": "1 day ago",
        },
        {
            "title": "Apple Intelligence Expands to Mac With 'Hey Siri' Overhaul and App Actions",
            "url": "https://www.apple.com/apple-intelligence",
            "description": "macOS Sequoia brings persistent AI agents that remember your preferences, proactively schedule meetings, and control third-party apps.",
            "age": "3 days ago",
        },
        {
            "title": "Meta Releases Open-Source AI Agent Framework for Consumer Products",
            "url": "https://ai.meta.com/agent-framework",
            "description": "Meta open-sources its agentic AI stack, enabling developers to build persistent personal AI assistants with memory and tool use.",
            "age": "5 days ago",
        },
        {
            "title": "GitHub Copilot Now Acts as Your Coding Agent — Autonomously Writes and Tests Code",
            "url": "https://github.blog/copilot",
            "description": "The next evolution of Copilot can now run tests, debug errors, create PRs, and manage entire feature branches autonomously.",
            "age": "1 week ago",
        },
    ],
    "general": [
        {
            "title": "AI Agents Market to Reach $47B by 2027 — Here's What's Driving Growth",
            "url": "https://www.mckinsey.com/ai-agents-market",
            "description": "Enterprise adoption of AI agents is accelerating, with logistics, customer service, and software development as the top three use cases.",
            "age": "1 day ago",
        },
        {
            "title": "How to Build Your Own Personal AI Assistant: A Practical Guide",
            "url": "https://towardsdatascience.com/personal-ai-assistant",
            "description": "Step-by-step guide to building a persistent AI agent with memory, tool access, and voice control using open-source models.",
            "age": "2 days ago",
        },
        {
            "title": "The Future of Work: AI Agents as Your Digital Coworkers",
            "url": "https://hbr.org/ai-agents-work",
            "description": "Harvard Business Review explores how AI agents are reshaping knowledge work, with 67% of executives planning to deploy agentic AI by 2026.",
            "age": "4 days ago",
        },
        {
            "title": "Best AI Coding Agents in 2025: Claude Code vs Copilot vs Devin",
            "url": "https://www.techreview.com/ai-coding-agents",
            "description": "Head-to-head comparison of autonomous coding agents, with benchmarks on code quality, speed, and multi-step task completion.",
            "age": "1 week ago",
        },
        {
            "title": "Voice-First AI: Why Spoken Conversation is the Next Interface",
            "url": "https://www.wired.com/voice-ai-interface",
            "description": "The shift from typing to speaking with AI is accelerating, with Whisper STT and edge TTS making voice interaction practical at scale.",
            "age": "2 weeks ago",
        },
    ],
}


def _get_mock_results(query: str, count: int = 5) -> list[dict]:
    """Return relevant mock results based on query keywords."""
    q = query.lower()
    if any(kw in q for kw in ["news", "latest", "recent", "update", "today"]):
        results = _MOCK_RESULTS["news"]
    else:
        results = _MOCK_RESULTS["general"]

    # Simple relevance filter
    filtered = []
    keywords = [w for w in q.split() if len(w) > 3]
    for r in results:
        score = sum(1 for kw in keywords if kw in r["title"].lower() or kw in r["description"].lower())
        if score > 0 or len(filtered) < 2:
            filtered.append(r)

    return filtered[:count]


class WebSearchTool:
    """
    Brave Search integration. Set API key in config/api_keys.json as 'brave_search_api_key'.
    Falls back to mock data when no key is configured.
    """

    def __init__(self):
        self.api_key = _get_api_key()
        self.base_url = "https://api.search.brave.com/res/v1/web/search"
        self.news_url = "https://api.search.brave.com/res/v1/news/search"
        self._has_key = bool(self.api_key)

    def is_configured(self) -> bool:
        return self._has_key

    def search(self, query: str, count: int = 10) -> dict:
        """
        Search the web. Returns dict with query, results, total.
        Falls back to mock data if no API key.
        """
        if not self._has_key:
            results = _get_mock_results(query, count)
            return {
                "query": query,
                "results": results,
                "total": len(results),
                "source": "mock",
                "note": "No Brave Search API key — using demo results. Add key in Settings.",
            }

        try:
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            }
            params = {
                "q": query,
                "count": min(count, 20),
            }
            resp = requests.get(
                self.base_url,
                headers=headers,
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            web_results = data.get("web", {}).get("results", [])
            results = []
            for item in web_results[:count]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                    "age": item.get("age", ""),
                })

            log.info(f"Brave search: '{query}' → {len(results)} results")
            return {
                "query": query,
                "results": results,
                "total": data.get("web", {}).get("total", len(results)),
                "source": "brave",
            }

        except requests.exceptions.Timeout:
            log.error(f"Brave search timeout for: {query}")
            return {
                "query": query,
                "results": _get_mock_results(query, count),
                "total": 0,
                "source": "mock",
                "error": "Search timed out — falling back to demo results.",
            }
        except Exception as e:
            log.error(f"Brave search error: {e}")
            return {
                "query": query,
                "results": _get_mock_results(query, count),
                "total": 0,
                "source": "mock",
                "error": str(e),
            }

    def search_news(self, query: str, count: int = 5) -> dict:
        """Search news specifically via Brave News API."""
        if not self._has_key:
            return self.search(query, count)

        try:
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            }
            params = {"q": query, "count": min(count, 20)}
            resp = requests.get(self.news_url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            news_items = data.get("results", [])
            results = []
            for item in news_items[:count]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                    "age": item.get("page_age", ""),
                    "source": item.get("meta_url", {}).get("netloc", ""),
                })

            return {"query": query, "results": results, "source": "brave_news"}

        except Exception as e:
            log.error(f"Brave news search error: {e}")
            return self.search(query, count)

    def format_for_llm(self, results: dict) -> str:
        """
        Format search results as clean markdown for LLM context injection.
        """
        if not results.get("results"):
            return "No results found."

        note = ""
        if results.get("source") == "mock":
            note = f" ⚠️ Demo results (no API key configured). {results.get('note', '')}\n"
        elif results.get("error"):
            note = f" ⚠️ {results['error']}\n"

        lines = [note, f"## Search results for: *{results['query']}*", ""]
        for i, r in enumerate(results["results"], 1):
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            desc = r.get("description", "")
            age = r.get("age", "")
            source = r.get("source", "")

            lines.append(f"**{i}.** [{title}]({url})")
            if desc:
                lines.append(f"   {desc[:200]}{'...' if len(desc) > 200 else ''}")
            meta = []
            if age:
                meta.append(age)
            if source:
                meta.append(source)
            if meta:
                lines.append(f"   *{' · '.join(meta)}*")
            lines.append("")

        return "\n".join(lines)


# ── Singleton ──────────────────────────────────────────────────────────

_web_search_tool: WebSearchTool | None = None


def get_web_search_tool() -> WebSearchTool:
    global _web_search_tool
    if _web_search_tool is None:
        _web_search_tool = WebSearchTool()
    return _web_search_tool


def is_available() -> bool:
    """Check if search API key is configured."""
    return get_web_search_tool().is_configured()
