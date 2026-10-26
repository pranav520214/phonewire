"""
Authoritative SQLite storage for PhoneMic LAN.
Handles device pairing tokens, streaming sessions, transcripts, and insertion history.
"""

import sqlite3
import hashlib
import secrets
import time
import os
from typing import Optional, List, Dict, Any

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "phonemic.db")

def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initializes tables for devices, pairing codes, sessions, and transcripts."""
    with get_connection(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS pairing_codes (
            code TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            used INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            device_name TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            paired_at REAL NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            device_id TEXT,
            started_at REAL NOT NULL,
            ended_at REAL,
            status TEXT NOT NULL,
            FOREIGN KEY (device_id) REFERENCES devices (id)
        );

        CREATE TABLE IF NOT EXISTS transcripts (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            raw_text TEXT NOT NULL,
            refined_text TEXT,
            language TEXT NOT NULL DEFAULT 'en',
            model_name TEXT NOT NULL,
            created_at REAL NOT NULL,
            inserted INTEGER NOT NULL DEFAULT 0,
            insertion_status TEXT NOT NULL DEFAULT 'PENDING',
            error TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions (session_id)
        );

        CREATE INDEX IF NOT EXISTS idx_transcripts_created_at ON transcripts(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_transcripts_raw_text ON transcripts(raw_text);
        """)

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def create_enrollment_code(db_path: str = DEFAULT_DB_PATH, ttl_seconds: int = 300) -> str:
    """Generates a 6-digit temporary enrollment code."""
    code = f"{secrets.randbelow(900000) + 100000}"
    now = time.time()
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pairing_codes (code, created_at, expires_at, used) VALUES (?, ?, ?, 0)",
            (code, now, now + ttl_seconds)
        )
    return code

def verify_enrollment_code(code: str, device_name: str, db_path: str = DEFAULT_DB_PATH) -> Optional[str]:
    """
    Verifies code. If valid, generates a long-lived Bearer token,
    hashes and stores it, and returns the raw token to the client.
    """
    now = time.time()
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM pairing_codes WHERE code = ? AND used = 0 AND expires_at > ?",
            (code, now)
        ).fetchone()
        if not row:
            return None
        
        # Mark code used
        conn.execute("UPDATE pairing_codes SET used = 1 WHERE code = ?", (code,))
        
        # Create device token
        device_id = secrets.token_hex(8)
        raw_token = f"pm_{secrets.token_urlsafe(32)}"
        token_hash = hash_token(raw_token)
        
        conn.execute(
            "INSERT INTO devices (id, device_name, token_hash, paired_at, revoked) VALUES (?, ?, ?, ?, 0)",
            (device_id, device_name, token_hash, now)
        )
        return raw_token

def validate_bearer_token(raw_token: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Checks if bearer token exists and is not revoked."""
    token_hash = hash_token(raw_token)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE token_hash = ? AND revoked = 0",
            (token_hash,)
        ).fetchone()
        return dict(row) if row else None

def create_session(session_id: str, device_id: Optional[str] = None, db_path: str = DEFAULT_DB_PATH) -> None:
    now = time.time()
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, device_id, started_at, status) VALUES (?, ?, ?, 'ACTIVE')",
            (session_id, device_id, now)
        )

def close_session(session_id: str, status: str = "COMPLETED", db_path: str = DEFAULT_DB_PATH) -> None:
    now = time.time()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET ended_at = ?, status = ? WHERE session_id = ?",
            (now, status, session_id)
        )

def save_transcript(
    transcript_id: str,
    session_id: Optional[str],
    raw_text: str,
    refined_text: Optional[str],
    model_name: str,
    language: str = "en",
    inserted: bool = False,
    insertion_status: str = "PENDING",
    error: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    now = time.time()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO transcripts 
            (id, session_id, raw_text, refined_text, language, model_name, created_at, inserted, insertion_status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transcript_id, session_id, raw_text, refined_text,
                language, model_name, now, int(inserted), insertion_status, error
            )
        )

def update_insertion_status(
    transcript_id: str,
    status: str,
    error: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    inserted = 1 if status == "SUCCESS" else 0
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE transcripts SET inserted = ?, insertion_status = ?, error = ? WHERE id = ?",
            (inserted, status, error, transcript_id)
        )

def get_transcripts(query: Optional[str] = None, limit: int = 50, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        if query:
            sql = """
                SELECT * FROM transcripts 
                WHERE raw_text LIKE ? OR refined_text LIKE ?
                ORDER BY created_at DESC LIMIT ?
            """
            rows = conn.execute(sql, (f"%{query}%", f"%{query}%", limit)).fetchall()
        else:
            sql = "SELECT * FROM transcripts ORDER BY created_at DESC LIMIT ?"
            rows = conn.execute(sql, (limit,)).fetchall()
        return [dict(r) for r in rows]
