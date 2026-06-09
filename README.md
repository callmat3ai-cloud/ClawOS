# ClawOS — Desktop AI Agent

Voice-first AI desktop assistant with Composio-powered app integrations, persistent memory, and a futuristic UI.

```
⚡ ClawOS v1.0.0
Desktop AI Agent — Voice · Composio · Memory · Cron
```

---

## Features

- **🎤 Voice Input** — Speak naturally, get spoken responses
- **💬 Chat Interface** — Full conversation history with persistent memory
- **🛠️ 500+ App Integrations** — Gmail, Notion, GitHub, Slack, Linear, and more via Composio
- **🧠 Memory** — Remembers context across sessions, auto-extraction
- **👤 Profiles** — Isolated work/personal/client profiles
- **📅 Cron Jobs** — Natural language scheduling ("every morning at 9")
- **🧠 Skill Auto-Discovery** — Learns repeated workflows and creates reusable skills
- **🌙 Futuristic Dark UI** — Cyan/purple cyberpunk aesthetic

---

## Requirements

- macOS (Apple Silicon or Intel)
- Python 3.10+
- Gemini API key (free tier available)
- Composio API key (free tier: 20k tool calls/mo)

---

## Install

```bash
# 1. Clone the repo
git clone https://github.com/callmat3ai-cloud/ClawOS.git
cd ClawOS

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API keys
mkdir -p config
cat > config/api_keys.json << 'EOF'
{
  "gemini_api_key": "YOUR_GEMINI_KEY_HERE",
  "composio_api_key": "YOUR_COMPOSIO_KEY_HERE"
}
EOF

# 5. Install Composio CLI (for OAuth connections)
pip install composio-py
composio login

# 6. Run
python main.py
```

---

## API Keys

| Service | Get API Key | Free Tier |
|---------|------------|-----------|
| Gemini | aistudio.google.com | 1,500 req/min |
| Composio | composio.dev | 20,000 calls/mo |

---

## Project Structure

```
ClawOS/
├── main.py                     # App entry point
├── ui/futuristic_ui.py         # PyQt6 UI — orb, chat, tools, profiles
├── agent/
│   ├── planner.py               # LLM task decomposition
│   ├── executor.py              # Step-by-step execution + retry
│   └── error_handler.py        # Auto-recovery
├── memory/
│   ├── memory_manager.py        # From Brahma (extraction + compression)
│   └── profile_manager.py       # Profile isolation + session persistence
├── integrations/
│   ├── composio_mcp.py         # 500+ app integrations
│   └── openrouter_client.py    # Fallback model routing
├── scheduler/
│   └── cron_manager.py         # APScheduler cron jobs
├── skills/
│   ├── skill_discovery.py      # Auto-learn workflows
│   └── auto/                   # Auto-generated skill files
└── actions/                    # Brahma action modules (22 total)
    ├── browser_control.py
    ├── computer_control.py
    └── ...
```

---

## Roadmap

- [ ] Voice pipeline full integration with PyQt6 UI
- [ ] Composio OAuth connection wizard in Settings
- [ ] mcporter integration for n8n/Zapier webhooks
- [ ] macOS .app bundling with PyInstaller
- [ ] Skill marketplace sharing

---

## License

Proprietary — ClawOps Studio
