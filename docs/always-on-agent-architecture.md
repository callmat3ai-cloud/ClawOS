# Phase 2: Always-On Agent — macOS Menu Bar App

## Vision

A **native macOS menu bar agent** that:
- Lives in the background 24/7
- Responds to "Hey Josh" from anywhere on the Mac
- Speaks back via TTS
- Controls your Mac natively (AppleScript, accessibility APIs)
- Shares memory layer with ClawOS sub-agents
- Shows an animated avatar overlay when active

This is the **viral product** — users will share videos of their AI managing their workday.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│              macOS Menu Bar (Swift)                  │
│  ┌─────────────┐    ┌──────────────────────────────┐  │
│  │ 🟣 Icon    │    │ Hotkey: ⌘⇧J or "Hey Josh"  │  │
│  │ (always-on)│    │ AVAudioEngine (wake word)   │  │
│  └─────────────┘    └──────────────────────────────┘  │
│           │                    │                       │
│           │  "Hey Josh, set a meeting for 2pm"       │
│           └──────────────────────┘                     │
│                              │                         │
│                     ┌─────────▼─────────┐              │
│                     │  AppleScript /     │              │
│                     │  Accessibility API  │              │
│                     │  (Calendar, Mail,  │              │
│                     │   Reminders, etc.) │              │
│                     └─────────┬─────────┘              │
│                               │                         │
│                     ┌─────────▼─────────┐              │
│                     │  OpenAI / Anthropic │              │
│                     │  (minimal LLM call) │              │
│                     └─────────┬─────────┘              │
│                               │                         │
│                     ┌─────────▼─────────┐              │
│                     │  TTS (AVSpeech     │              │
│                     │   Synthesizer)     │              │
│                     └─────────┬─────────┘              │
│                               │                         │
│                     ┌─────────▼─────────┐              │
│                     │  Avatar Overlay    │              │
│                     │  (animated face)   │              │
│                     └───────────────────┘              │
└──────────────────────────────────────────────────────┘
                               │
                    Shared memory layer (SQLite)
                               │
              ┌────────────────┴────────────────┐
              │        ClawOS Sub-Agents       │
              │  (run in background when Mac   │
              │   is unlocked and app is open) │
              └───────────────────────────────┘
```

---

## Component Breakdown

### 1. Menu Bar App (Swift)

**Frameworks needed:**
- `AppKit` — menu bar icon, system tray
- `AVFoundation` — audio capture for wake word
- `Speech` — on-device speech recognition (SFSpeechRecognizer)
- `AVFAudio` — on-device TTS (AVSpeechSynthesizer)
- `AppleScript` — control Calendar, Mail, Reminders, Finder
- `Accessibility` — control mouse/keyboard at OS level

**UI:**
- Menu bar icon: 🟣 (always visible)
- Click → popup panel with recent activity + quick actions
- Settings gear → preferences window

**Hotkey:** `Cmd+Shift+J` to activate (global hotkey via `CGEvent`)

### 2. Wake Word Detection

**Option A — Porcupine (Picovoice):**
```swift
// $0 free-tier/month. Real-time, on-device, 2KB wake words.
// CocoaPod: Porcupine
import Porcupine

let handle = Porcupine(
    accessKey: "...",
    keywords: ["hey josh", "computer"],
)
handle.start { keywordIndex, keyword, audioLevel in
    // keywordIndex: 0 = "hey josh"
    activateAssistant()
}
```

**Option B — On-device Speech Recognition (free, built-in):**
```swift
// SFSpeechRecognizer — free, on-device, no API key needed
// But: requires user permission + internet for first use
// Better: use Apple's "Key Phrase" HotWord API
```

**Recommendation:** Use **Picovoice Porcupine** — 100% on-device, fast, no internet needed.

### 3. Memory Layer (Shared with ClawOS)

**SQLite database** at `~/.clawos/shared_memory.db`:

```sql
CREATE TABLE memory (
    id INTEGER PRIMARY KEY,
    category TEXT,
    key TEXT,
    value TEXT,
    confidence REAL,
    source TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT,
    started_at TIMESTAMP,
    ended_at TIMESTAMP
);

CREATE TABLE agent_state (
    agent_id TEXT PRIMARY KEY,
    state TEXT,
    last_active TIMESTAMP
);
```

Both the menu bar app AND ClawOS write to this DB. Agents read from it.

### 4. LLM Integration

**Lightweight API calls only** — the menu bar agent doesn't run the full agent loop.
- Uses **Claude API** directly (not through Hermes/Henry)
- System prompt: minimalist, fast, action-focused
- No tool use needed — direct AppleScript calls instead of MCP

### 5. Avatar Overlay (Optional — Phase 3 merge)

When "Hey Josh" fires, a translucent window overlays the screen:
- Animated face (SwiftUI or raw CALayer)
- Shows listening → thinking → speaking states
- Auto-hides after 10s of inactivity

---

## File Structure

```
always-on-agent/
├── Sources/
│   ├── App/
│   │   ├── main.swift              # @main entry point
│   │   ├── AppDelegate.swift       # NSApplicationDelegate
│   │   └── MenuBarController.swift # Menu bar icon + panel
│   ├── Audio/
│   │   ├── WakeWordEngine.swift    # Porcupine / Speech recognition
│   │   ├── AudioRecorder.swift     # AVAudioEngine capture
│   │   └── TTSEngine.swift         # AVSpeechSynthesizer
│   ├── AI/
│   │   ├── AgentBrain.swift       # LLM calls + response parsing
│   │   └── CommandRouter.swift     # Route intent → AppleScript
│   ├── Controls/
│   │   ├── CalendarControl.swift   # AppleScript: Calendar.app
│   │   ├── MailControl.swift       # AppleScript: Mail.app
│   │   ├── ReminderControl.swift   # AppleScript: Reminders.app
│   │   ├── FinderControl.swift     # AppleScript: Finder.app
│   │   └── MouseKeyboard.swift    # Accessibility API
│   ├── Memory/
│   │   └── SharedMemory.swift      # SQLite wrapper
│   └── UI/
│       ├── AvatarOverlay.swift     # CALayer animated face
│       └── SettingsWindow.swift     # Preferences
├── Resources/
│   └── Assets.xcassets
├── project.yml                    # XcodeGen config
└── Podfile                       # CocoaPods (Porcupine, etc.)
```

---

## XcodeGen Configuration

```yaml
name: ClawOSAgent
options:
  bundleIdPrefix: com.clawops
  deploymentTarget:
    macOS: "13.0"
targets:
  ClawOSAgent:
    type: application
    platform: macOS
    sources: [Sources]
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.clawops.always-on-agent
        INFOPLIST_FILE: Sources/App/Info.plist
        CODE_SIGN_ENTITLEMENTS: Sources/App/ClawOSAgent.entitlements
        SWIFT_VERSION: "5.9"
        MACOSX_DEPLOYMENT_TARGET: "13.0"
        LD_RUNPATH_SEARCH_PATHS: "@executable_path/../Frameworks"
        ENABLE_HARDENED_RUNTIME: YES
        CODE_SIGN_IDENTITY: "-"
```

---

## Info.plist Keys (Required)

```xml
<key>NSMicrophoneUsageDescription</key>
<string>ClawOS needs microphone access to hear "Hey Josh"</string>

<key>NSSpeechRecognitionUsageDescription</key>
<string>ClawOS uses speech recognition to understand your commands</string>

<key>NSCalendarsUsageDescription</key>
<string>ClawOS reads and creates calendar events</string>

<key>NSAppleEventsUsageDescription</key>
<string>ClawOS controls other apps via AppleScript</string>

<key>LSUIElement</key>
<true/>  <!-- Hide from Dock — menu bar only app -->
```

---

## Entitlements

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
    <key>com.apple.security.app-sandbox</key>
    <false/>
    <!-- Set to true + add specific entitlements for App Store -->
    <key>com.apple.security.automation.apple-events</key>
    <true/>
    <key>com.apple.security.device.audio-input</key>
    <true/>
</dict>
</plist>
```

---

## AppleScript Commands (No API key needed)

```swift
// Calendar — create event
func createCalendarEvent(title: String, at date: Date) throws {
    let script = """
    tell application "Calendar"
        tell calendar "Home"
            make new event at end of events with properties {
                summary: "\(title)",
                start date: date "\(date)"
            }
        end tell
    end tell
    """
    try NSAppleScript(source: script)?.executeAndReturnError(nil)
}

// Reminders — add reminder
func addReminder(text: String) throws {
    let script = """
    tell application "Reminders"
        tell list "Reminders"
            make new reminder with properties {name: "\(text)"}
        end tell
    end tell
    """
    try NSAppleScript(source: script)?.executeAndReturnError(nil)
}

// Mail — send email
func sendEmail(to: String, subject: String, body: String) throws {
    let script = """
    tell application "Mail"
        set msg to make new outgoing message with properties {
            subject: "\(subject)",
            content: "\(body)",
            visible: false
        }
        tell msg to set visible to false
        make new to recipient at end of to recipients of msg with properties {address: "\(to)"}
        send msg
    end tell
    """
    try NSAppleScript(source: script)?.executeAndReturnError(nil)
}

// Open app
func openApp(name: String) throws {
    try NSWorkspace.shared.launchApplication(name)
}
```

---

## Pricing / Licensing Model

### Standalone Sale
- **$29 one-time**: Always-On Agent (menu bar app)
- Includes: wake word, voice, calendar, reminders, mail, TTS
- Updates: 1 year free

### Bundle with ClawOS
- **$79 one-time**: ClawOS + Always-On Agent
- **$199/yr**: ClawOS + Always-On + Updates

### Enterprise / Agency
- **$499 one-time**: Full stack + custom agentic workflows
- **$999/yr**: White-label + multi-agent team + API access

---

## Build Steps

### Prerequisites
```bash
xcode-select --install  # Command line tools
brew install xcodegen   # XcodeGen
pod install             # CocoaPods
```

### Build
```bash
git clone https://github.com/callmat3ai-cloud/ClawOS-Agent.git
cd ClawOS-Agent
xcodegen generate
pod install
open ClawOSAgent.xcworkspace
# Build & Run in Xcode
```

### Distribute
- **TestFlight** for beta
- **DMG** for direct download
- **Mac App Store** (needs sandbox + specific entitlements)

---

## Status: Ready to Build

Pulkit can start coding this when back on Mac.
All architecture decisions documented above.
