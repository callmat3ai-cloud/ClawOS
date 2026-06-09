"""
memory/profile_manager.py — ClawOS Profile System

Multi-profile support with isolated SQLite databases per profile.
Work / Personal / Client profiles, each with own memory and settings.
"""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

_LOCK = threading.Lock()


def _base_dir() -> Path:
    frozen = getattr(sys := __import__("sys").modules["sys"], "frozen", False)
    if frozen:
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _profiles_dir() -> Path:
    return _base_dir() / "profiles"


def _get_profile_db_path(profile_id: str) -> Path:
    return _profiles_dir() / f"{profile_id}.db"


def _ensure_profiles_dir():
    _profiles_dir().mkdir(parents=True, exist_ok=True)


def _init_db(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        confidence REAL DEFAULT 1.0,
        source TEXT DEFAULT 'user',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        access_count INTEGER DEFAULT 0
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        profile_id TEXT NOT NULL,
        title TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS cron_jobs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cron_expr TEXT NOT NULL,
        action TEXT NOT NULL,
        enabled INTEGER DEFAULT 1,
        last_run TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


# ── Profile CRUD ───────────────────────────────────────────────

def list_profiles() -> list[dict]:
    _ensure_profiles_dir()
    profiles = []
    seen = set()

    for db_file in sorted(_profiles_dir().glob("*.db")):
        pid = db_file.stem
        if pid in seen:
            continue
        conn = sqlite3.connect(str(db_file))
        try:
            name_row = conn.execute(
                "SELECT value FROM settings WHERE key='profile_name'"
            ).fetchone()
            color_row = conn.execute(
                "SELECT value FROM settings WHERE key='profile_color'"
            ).fetchone()
            created_row = conn.execute(
                "SELECT created_at FROM memories ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            profiles.append({
                "id": pid,
                "name": name_row[0] if name_row else pid,
                "color": color_row[0] if color_row else "#00f5ff",
                "created_at": (created_row[0] if created_row else "")[:10],
            })
            seen.add(pid)
        finally:
            conn.close()

    for pf in _profiles_dir().glob("*.json"):
        pid = pf.stem
        if pid in seen or pid == "default":
            continue
        try:
            data = json.loads(pf.read_text())
            profiles.append({
                "id": pid,
                "name": data.get("name", pid),
                "color": data.get("color", "#00f5ff"),
                "created_at": data.get("created_at", "")[:10],
            })
        except Exception:
            profiles.append({"id": pid, "name": pid, "color": "#00f5ff", "created_at": ""})

    return profiles


def create_profile(name: str, color: str = "#00f5ff") -> str:
    pid = name.lower().replace(" ", "_") + "_" + uuid.uuid4().hex[:6]
    _ensure_profiles_dir()
    db_path = _get_profile_db_path(pid)
    _init_db(db_path)

    meta = {
        "profile_id": pid,
        "name": name,
        "color": color,
        "created_at": datetime.utcnow().isoformat(),
    }
    (_profiles_dir() / f"{pid}.json").write_text(json.dumps(meta, indent=2))

    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("profile_name", name))
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", ("profile_color", color))
    conn.commit()
    conn.close()
    return pid


def delete_profile(profile_id: str) -> bool:
    if profile_id == "default":
        return False
    db_path = _get_profile_db_path(profile_id)
    try:
        db_path.unlink(missing_ok=True)
        (_profiles_dir() / f"{profile_id}.json").unlink(missing_ok=True)
        return True
    except Exception:
        return False


def get_active_profile() -> str:
    profile_file = _profiles_dir() / "default.json"
    if profile_file.exists():
        return json.loads(profile_file.read_text()).get("active_profile", "default")
    return "default"


def set_active_profile(profile_id: str) -> bool:
    _ensure_profiles_dir()
    if profile_id not in [p["id"] for p in list_profiles()] and profile_id != "default":
        return False
    (_profiles_dir() / "default.json").write_text(
        json.dumps({"active_profile": profile_id}, indent=2)
    )
    return True


def _get_db_conn(profile_id: str | None = None):
    if profile_id is None:
        profile_id = get_active_profile()
    db_path = _get_profile_db_path(profile_id)
    if not db_path.exists():
        _init_db(db_path)
    return sqlite3.connect(str(db_path))


# ── Memory ─────────────────────────────────────────────────────

def save_memory(
    category: str,
    key: str,
    value: str,
    confidence: float = 1.0,
    source: str = "user",
    profile_id: str | None = None,
) -> None:
    conn = _get_db_conn(profile_id)
    try:
        conn.execute(
            """INSERT INTO memories (category, key, value, confidence, source, created_at, last_accessed, access_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value,
                   confidence=MAX(confidence, excluded.confidence),
                   last_accessed=CURRENT_TIMESTAMP,
                   access_count=access_count+1""",
            (category, key, value, confidence, source, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def recall_memory(
    category: str | None = None,
    key: str | None = None,
    profile_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    conn = _get_db_conn(profile_id)
    try:
        if key:
            rows = conn.execute(
                "SELECT * FROM memories WHERE key=? ORDER BY access_count DESC, last_accessed DESC LIMIT ?",
                (key, limit),
            ).fetchall()
        elif category:
            rows = conn.execute(
                "SELECT * FROM memories WHERE category=? ORDER BY access_count DESC, last_accessed DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY access_count DESC, last_accessed DESC LIMIT ?",
                (limit,),
            ).fetchall()
        cols = ["id", "category", "key", "value", "confidence",
                "source", "created_at", "last_accessed", "access_count"]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def forget_memory(key: str, profile_id: str | None = None) -> bool:
    conn = _get_db_conn(profile_id)
    try:
        cur = conn.execute("DELETE FROM memories WHERE key=?", (key,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def compress_old_memories(profile_id: str | None = None, days: int = 7) -> int:
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    conn = _get_db_conn(profile_id)
    try:
        rows = conn.execute(
            "SELECT id FROM memories WHERE last_accessed < ? AND access_count < 3",
            (cutoff,),
        ).fetchall()
        count = len(rows)
        if count:
            ids = [r[0] for r in rows]
            conn.execute(f"DELETE FROM memories WHERE id IN ({','.join('?' * len(ids))})", ids)
            conn.commit()
        return count
    finally:
        conn.close()


def format_memory_for_prompt(profile_id: str | None = None, limit: int = 40) -> str:
    mems = recall_memory(profile_id=profile_id, limit=limit)
    if not mems:
        return ""
    lines = ["[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]"]
    for m in mems:
        lines.append(f"  {m['category'].replace('_',' ').title()}: {m['value']}")
    result = "\n".join(lines)
    return result[:2000] + "\n"


# ── Sessions ───────────────────────────────────────────────────

def create_session(title: str = "", profile_id: str | None = None) -> str:
    sid = uuid.uuid4().hex[:12]
    conn = _get_db_conn(profile_id)
    try:
        conn.execute(
            "INSERT INTO sessions (id, profile_id, title) VALUES (?, ?, ?)",
            (sid, get_active_profile() if profile_id is None else profile_id, title or "New Chat"),
        )
        conn.commit()
    finally:
        conn.close()
    return sid


def get_sessions(profile_id: str | None = None) -> list[dict]:
    conn = _get_db_conn(profile_id)
    try:
        rows = conn.execute(
            "SELECT id, title, created_at, last_active FROM sessions ORDER BY last_active DESC"
        ).fetchall()
        return [{"id": r[0], "title": r[1], "created_at": r[2], "last_active": r[3]} for r in rows]
    finally:
        conn.close()


def save_message(session_id: str, role: str, content: str) -> None:
    conn = _get_db_conn()
    try:
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )
        conn.execute(
            "UPDATE sessions SET last_active=CURRENT_TIMESTAMP WHERE id=?", (session_id,)
        )
        conn.commit()
    finally:
        conn.close()


def get_messages(session_id: str, limit: int = 100) -> list[dict]:
    conn = _get_db_conn()
    try:
        rows = conn.execute(
            "SELECT role, content, timestamp FROM messages WHERE session_id=? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]
    finally:
        conn.close()
