#!/usr/bin/env python3
"""ClawOS Voice Pipeline — WebSocket server for voice I/O."""
import asyncio, json, subprocess, time
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import edge_tts

VOICE = "en-US-GuyNeural"
STATUS_FILE = '/opt/clawos/orb/status.json'
BASE_DIR = Path('/opt/clawos/voice')
app = FastAPI(title="ClawOS Voice")
app.mount('/orb', StaticFiles(directory='/opt/clawos/orb'), name='orb')

def set_status(status, message=""):
    try:
        Path(STATUS_FILE).write_text(json.dumps({"status": status, "message": message}))
    except Exception:
        pass

@app.get('/')
async def root():
    return HTMLResponse(open(BASE_DIR / 'index.html').read())

@app.get('/api/status')
async def status():
    try:
        return json.loads(Path(STATUS_FILE).read_text())
    except Exception:
        return {"status": "idle", "message": "ClawOS online"}

@app.get('/api/tts')
async def tts(text: str = "Hello, I am ClawOS"):
    path = Path('/tmp/clawos-tts.mp3')
    try:
        communicate = edge_tts.Communicate(text, VOICE)
        await communicate.save(str(path))
        return FileResponse(path, media_type='audio/mpeg')
    except Exception as e:
        return {"error": str(e)}

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
                result = subprocess.run(
                    ['hermes', '--profile', 'josh', 'chat', '-q', text],
                    capture_output=True, text=True, timeout=60
                )
                reply = result.stdout.strip()
                if not reply:
                    reply = "I heard you, but I couldn't generate a response."
            except Exception as e:
                reply = f"Error: {str(e)}"
            set_status("speaking", reply[:60])
            await ws.send_json({"type": "status", "status": "speaking", "message": reply[:80]})
            try:
                communicate = edge_tts.Communicate(reply, VOICE)
                audio_path = BASE_DIR / 'tmp_reply.mp3'
                await communicate.save(str(audio_path))
                audio_b64 = __import__('base64').b64encode(audio_path.read_bytes()).decode()
                await ws.send_json({"type": "audio", "format": "mp3", "data": audio_b64})
                audio_path.unlink(missing_ok=True)
            except Exception as e:
                await ws.send_json({"type": "text_reply", "text": reply})
            set_status("idle", "ClawOS is online")
            processing = False
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS error: {e}")

if __name__ == '__main__':
    import uvicorn
    set_status("idle", "ClawOS is online")
    uvicorn.run(app, host='0.0.0.0', port=9001, log_level='warning')
