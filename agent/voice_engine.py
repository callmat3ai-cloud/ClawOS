"""
Voice Engine — STT (speech-to-text) + TTS (text-to-speech)
Supports: Edge TTS (free), ElevenLabs, Kokoro (local), Whisper STT.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("voice_engine")


def _base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
CONFIG_DIR = BASE_DIR / "config"


def _load_settings() -> dict:
    settings_file = CONFIG_DIR / "app_settings_v2.json"
    if not settings_file.exists():
        return {}
    try:
        return json.loads(settings_file.read_text())
    except Exception:
        return {}


def _save_settings(data: dict):
    settings_file = CONFIG_DIR / "app_settings_v2.json"
    settings_file.write_text(json.dumps(data, indent=2))


# ── TTS Engines ───────────────────────────────────────────────────────

class TTSEngine:
    """Base class for TTS engines."""

    def speak(self, text: str, blocking: bool = True) -> str | None:
        raise NotImplementedError

    def speak_async(self, text: str, on_complete: Callable[[], None] = None):
        raise NotImplementedError

    def list_voices(self) -> list[dict]:
        return []


class EdgeTTS(TTSEngine):
    """Edge Text-to-Speech — free, cross-platform, works everywhere."""

    def speak(self, text: str, blocking: bool = True) -> str | None:
        import tempfile, subprocess, os

        try:
            voice = self._get_voice()
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                mp3_path = f.name

            cmd = [
                "edge-tts",
                "--text", text,
                "--voice", voice,
                "--write-media", mp3_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                log.warning(f"Edge TTS error: {result.stderr}")
                return None

            if blocking:
                # Play with afplay (macOS) or aplay (Linux) or mplayer
                player = self._find_player()
                if player:
                    subprocess.run([player, mp3_path], capture_output=True, timeout=60)
                os.unlink(mp3_path)
                return None
            return mp3_path

        except FileNotFoundError:
            log.warning("edge-tts not installed. Run: pip install edge-tts")
            return None
        except Exception as e:
            log.error(f"Edge TTS error: {e}")
            return None

    def speak_async(self, text: str, on_complete: Callable[[], None] = None):
        def run():
            self.speak(text, blocking=True)
            if on_complete:
                on_complete()
        threading.Thread(target=run, daemon=True).start()

    def list_voices(self) -> list[dict]:
        return [
            {"id": "en-US-AriaNeural", "name": "Aria (US)", "gender": "Female"},
            {"id": "en-US-GuyNeural", "name": "Guy (US)", "gender": "Male"},
            {"id": "en-GB-SoniaNeural", "name": "Sonia (UK)", "gender": "Female"},
            {"id": "en-GB-RyanNeural", "name": "Ryan (UK)", "gender": "Male"},
            {"id": "en-IN-NeerjaNeural", "name": "Neerja (IN)", "gender": "Female"},
            {"id": "en-IN-PrabhatNeural", "name": "Prabhat (IN)", "gender": "Male"},
        ]

    def _get_voice(self) -> str:
        settings = _load_settings()
        return settings.get("edge_tts_voice", "en-US-AriaNeural")

    def _find_player(self) -> str | None:
        import shutil
        for player in ["afplay", "aplay", "mpg123", "mplayer"]:
            if shutil.which(player):
                return player
        return None


class KokoroTTS(TTSEngine):
    """Kokoro local TTS — high quality, runs on CPU/GPU."""

    def __init__(self):
        self._ready = False
        self._client = None
        self._check()

    def _check(self):
        venv_path = Path.home() / "kokoro-venv"
        if not venv_path.exists():
            log.info("Kokoro venv not found. Install: python -m venv ~/kokoro-venv && ~/kokoro-venv/bin/pip install kokoro-onnx")
            return

        try:
            import sys
            sys.path.insert(0, str(venv_path / "lib" / "site-packages"))
            from kokoro_onnx import Kokoro

            settings = _load_settings()
            voice = settings.get("kokoro_voice", "af_heart")
            models_dir = Path.home() / ".kokoro" / "models"
            self._client = Kokoro(str(models_dir), voice)
            self._ready = True
            log.info("Kokoro TTS ready")
        except Exception as e:
            log.warning(f"Kokoro init failed: {e}")

    def speak(self, text: str, blocking: bool = True) -> str | None:
        if not self._ready:
            return None
        try:
            import numpy as np, soundfile as sf, tempfile, os, subprocess, shutil

            samples, sample_rate = self._client.create(text)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = f.name
            sf.write(wav_path, samples, sample_rate)

            if blocking:
                player = "afplay" if shutil.which("afplay") else "aplay"
                subprocess.run([player, wav_path], capture_output=True, timeout=60)
                os.unlink(wav_path)
                return None
            return wav_path
        except Exception as e:
            log.error(f"Kokoro TTS error: {e}")
            return None

    def speak_async(self, text: str, on_complete: Callable[[], None] = None):
        def run():
            self.speak(text, blocking=True)
            if on_complete:
                on_complete()
        threading.Thread(target=run, daemon=True).start()

    def list_voices(self) -> list[dict]:
        return [
            {"id": "af_heart", "name": "Heart (Female)", "gender": "Female"},
            {"id": "af_bella", "name": "Bella (Female)", "gender": "Female"},
            {"id": "af_nicole", "name": "Nicole (Female)", "gender": "Female"},
            {"id": "am_adam", "name": "Adam (Male)", "gender": "Male"},
            {"id": "am_michael", "name": "Michael (Male)", "gender": "Male"},
        ]


class ElevenLabsTTS(TTSEngine):
    """ElevenLabs cloud TTS — premium quality."""

    def speak(self, text: str, blocking: bool = True) -> str | None:
        try:
            import requests, tempfile, os, subprocess, shutil

            keys = self._load_keys()
            api_key = keys.get("elevenlabs_api_key", "")
            if not api_key:
                return None

            settings = _load_settings()
            voice_id = settings.get("elevenlabs_voice_id", "EXAVITQu4vr4xnSDxMaL")

            resp = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={"text": text, "model_id": "eleven_monolingual_v1"},
                timeout=30,
            )

            if resp.status_code != 200:
                return None

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(resp.content)
                mp3_path = f.name

            if blocking:
                player = "afplay" if shutil.which("afplay") else "aplay"
                subprocess.run([player, mp3_path], capture_output=True, timeout=60)
                os.unlink(mp3_path)
                return None
            return mp3_path

        except Exception as e:
            log.error(f"ElevenLabs TTS error: {e}")
            return None

    def speak_async(self, text: str, on_complete: Callable[[], None] = None):
        def run():
            self.speak(text, blocking=True)
            if on_complete:
                on_complete()
        threading.Thread(target=run, daemon=True).start()

    def list_voices(self) -> list[dict]:
        return [
            {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella", "gender": "Female"},
            {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi", "gender": "Female"},
            {"id": "VR6AewLTigWG4xSOukaG", "name": "Arnold", "gender": "Male"},
        ]

    def _load_keys(self) -> dict:
        f = CONFIG_DIR / "api_keys.json"
        return json.loads(f.read_text()) if f.exists() else {}


# ── STT Engines ───────────────────────────────────────────────────────

class STTEngine:
    """Base class for STT engines."""

    def listen(self, timeout: float = 10.0) -> str | None:
        raise NotImplementedError

    def listen_async(self, callback: Callable[[str], None], timeout: float = 10.0):
        raise NotImplementedError


class WhisperSTT(STTEngine):
    """Local Whisper STT — no internet required."""

    def __init__(self):
        self._model = None
        self._init_model()

    def _init_model(self):
        try:
            from faster_whisper import WhisperModel
            # Load tiny model for speed, upgrade to small/medium for quality
            settings = _load_settings()
            size = settings.get("whisper_model_size", "tiny")
            self._model = WhisperModel(size, device="cpu", compute_type="int8")
            log.info(f"Whisper STT ready ({size})")
        except ImportError:
            log.warning("faster-whisper not installed. Run: pip install faster-whisper")
        except Exception as e:
            log.warning(f"Whisper init: {e}")

    def listen(self, timeout: float = 10.0) -> str | None:
        if self._model is None:
            return None

        try:
            import sounddevice as sd, scipy.io.wavfile as wav
            import numpy as np, tempfile, os

            log.info("🎤 Listening... (speak now)")
            audio = sd.rec(int(timeout * 16000), samplerate=16000, channels=1, dtype="int16")
            sd.wait()

            # Save to temp WAV
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = f.name
            wav.write(wav_path, 16000, audio)

            # Transcribe
            segments, _ = self._model.transcribe(wav_path, language="en")
            text = " ".join(seg.text for seg in segments).strip()

            os.unlink(wav_path)
            return text if text else None

        except ImportError as e:
            log.warning(f"Audio libraries missing: {e}")
            return None
        except Exception as e:
            log.error(f"Whisper STT error: {e}")
            return None

    def listen_async(self, callback: Callable[[str], None], timeout: float = 10.0):
        def run():
            text = self.listen(timeout)
            if text:
                callback(text)
        threading.Thread(target=run, daemon=True).start()


class DeepgramSTT(STTEngine):
    """Deepgram cloud STT."""

    def listen(self, timeout: float = 10.0) -> str | None:
        try:
            import sounddevice as sd, requests, numpy as np

            keys = self._load_keys()
            api_key = keys.get("deepgram_api_key", "")
            if not api_key:
                return None

            log.info("🎤 Listening via Deepgram...")
            audio = sd.rec(int(timeout * 16000), samplerate=16000, channels=1, dtype="int16")
            sd.wait()

            files = {"file": ("audio.wav", np.int16(audio).tobytes(), "audio/wav")}
            resp = requests.post(
                "https://api.deepgram.com/v1/listen",
                headers={"Authorization": f"Token {api_key}"},
                data=files,
                timeout=15,
            )

            if resp.status_code == 200:
                data = resp.json()
                return data.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "")
            return None

        except Exception as e:
            log.error(f"Deepgram STT error: {e}")
            return None

    def listen_async(self, callback: Callable[[str], None], timeout: float = 10.0):
        def run():
            text = self.listen(timeout)
            if text:
                callback(text)
        threading.Thread(target=run, daemon=True).start()

    def _load_keys(self) -> dict:
        f = CONFIG_DIR / "api_keys.json"
        return json.loads(f.read_text()) if f.exists() else {}


# ── Voice Engine Manager ─────────────────────────────────────────────

class VoiceEngine:
    """
    Unified voice engine. Set engine in settings:
    - tts_engine: "Edge TTS (Free)", "ElevenLabs", "Kokoro (Local)"
    - stt_engine: "Local Whisper", "Deepgram"
    """

    def __init__(self):
        settings = _load_settings()
        tts_name = settings.get("tts_engine", "Edge TTS (Free)")
        stt_name = settings.get("stt_engine", "Local Whisper")

        self._tts: TTSEngine = self._make_tts(tts_name)
        self._stt: STTEngine = self._make_stt(stt_name)
        self._muted = False

    def _make_tts(self, name: str) -> TTSEngine:
        if "ElevenLabs" in name:
            return ElevenLabsTTS()
        elif "Kokoro" in name:
            return KokoroTTS()
        else:
            return EdgeTTS()

    def _make_stt(self, name: str) -> STTEngine:
        if "Deepgram" in name:
            return DeepgramSTT()
        else:
            return WhisperSTT()

    def speak(self, text: str, blocking: bool = True):
        if self._muted:
            return
        self._tts.speak_async(text)

    def listen(self, timeout: float = 10.0) -> str | None:
        return self._stt.listen(timeout)

    def listen_and_respond(self, on_transcript: Callable[[str], None], on_speech: Callable[[str], None]):
        """
        Full voice loop: listen → transcript callback → speak response.
        Call this in a thread.
        """
        while True:
            try:
                text = self.listen(timeout=8.0)
                if text:
                    log.info(f"You said: {text}")
                    on_transcript(text)
                    # The calling code should handle the AI response
            except Exception as e:
                log.error(f"Voice loop error: {e}")
                time.sleep(1)

    def set_muted(self, muted: bool):
        self._muted = muted

    def is_muted(self) -> bool:
        return self._muted


# ── Convenience helpers ──────────────────────────────────────────────

_VOICE_ENGINE: VoiceEngine | None = None


def get_voice_engine() -> VoiceEngine:
    global _VOICE_ENGINE
    if _VOICE_ENGINE is None:
        _VOICE_ENGINE = VoiceEngine()
    return _VOICE_ENGINE


def speak_text(text: str, blocking: bool = False):
    """Quick TTS helper."""
    get_voice_engine().speak(text, blocking=blocking)


def listen_speech(timeout: float = 8.0) -> str | None:
    """Quick STT helper."""
    return get_voice_engine().listen(timeout=timeout)
