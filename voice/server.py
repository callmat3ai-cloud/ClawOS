#!/usr/bin/env python3
"""ClawOS Voice Pipeline — WebSocket server with wake-word routing."""
import asyncio, json, subprocess, time, os, secrets
from pathlib import Path
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import edge_tts

VOICE = "en-US-GuyNeural"
STATUS_FILE = '/opt/clawos/orb/status.json'
BASE_DIR = Path('/opt/clawos/voice')

AGENT_PROFILES = {
    "josh": ["josh", "boss", "chief"],
    "buyer-opportunity": ["buyer", "buyer opportunity", "opportunity"],
    "listing-intelligence": ["listing", "listing intelligence", "intelligence"],
    "pi-builder": ["pi builder", "builder", "pi"],
    "pi-intake": ["pi intake", "intake"],
    "pi-ops": ["pi ops", "ops"],
    "pi-records": ["pi records", "records"],
    "seo-content-geo": ["seo content", "content geo", "seo"],
    "seo-researcher": ["seo researcher", "researcher"],
    "seo-social": ["seo social", "social"],
}

app = FastAPI(title="ClawOS Voice")
app.mount('/orb', StaticFiles(directory='/opt/clawos/orb'), name='orb')

def set_status(status, message=""):
    try:
        Path(STATUS_FILE).write_text(json.dumps({"status": status, "message": message}))
    except Exception:
        pass

def detect_agent(text):
    text_lower = text.lower()
    for profile, wake_words in AGENT_PROFILES.items():
        for wake in wake_words:
            if wake in text_lower:
                return profile, text_lower.replace(wake, "").strip()
    return "josh", text

@app.get('/')
async def root():
    return HTMLResponse(open(BASE_DIR / 'index.html').read())

@app.get('/api/status')
async def status():
    try:
        return json.loads(Path(STATUS_FILE).read_text())
    except Exception:
        return {"status": "idle", "message": "ClawOS online"}

@app.get('/api/agents')
async def list_agents():
    return {"agents": list(AGENT_PROFILES.keys())}

@app.get('/api/tts')
async def tts(text: str = "Hello, I am ClawOS"):
    path = Path('/tmp/clawos-tts.mp3')
    try:
        communicate = edge_tts.Communicate(text, VOICE)
        await communicate.save(str(path))
        return FileResponse(path, media_type='audio/mpeg')
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.post('/api/chat')
async def chat_route(request: Request):
    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "empty text"})
    profile, clean_text = detect_agent(text)
    try:
        result = subprocess.run(
            ['hermes', '--profile', profile, 'chat', '-q', clean_text],
            capture_output=True, text=True, timeout=60
        )
        reply = result.stdout.strip()
        if not reply:
            reply = "[No response from agent]"
        set_status("idle", reply[:80])
        return JSONResponse({"reply": reply, "agent": profile, "model": "moonshotai/kimi-k3"})
    except subprocess.TimeoutExpired:
        return JSONResponse({"error": "timeout", "agent": profile})
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.websocket('/ws/voice')
async def voice_ws(ws: WebSocket):
    await ws.accept()
    processing = False
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("text", "")
            if not data:
                continue
            event = json.loads(data)
            if event.get("type") != "transcript":
                continue
            text = event.get("text", "").strip()
            if not text or processing:
                continue
            processing = True
            set_status("processing", f"Thinking: {text[:50]}")
            await ws.send_json({"type": "status", "status": "processing"})
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        "http://127.0.0.1:9001/api/chat",
                        json={"text": text},
                        timeout=60
                    )
                    data = resp.json()
                    reply = data.get("reply", "No response")
                    agent = data.get("agent", "josh")
                    await ws.send_json({
                        "type": "reply",
                        "text": reply,
                        "agent": agent,
                        "model": data.get("model", "moonshotai/kimi-k3")
                    })
                    set_status("idle", reply[:80])
            except Exception as e:
                await ws.send_json({"type": "error", "message": str(e)})
                set_status("error", str(e)[:80])
            finally:
                processing = False
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS error: {e}")

if __name__ == '__main__':
    import uvicorn
    set_status("idle", "ClawOS is online")
    uvicorn.run(app, host='0.0.0.0', port=9001, log_level='warning')
