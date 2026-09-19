"""
High-Performance SQLite Storage Engine for Audio Fact-Checker.
Replaces the monolithic 9MB verifier_cache.json with an indexed, atomic SQLite
database with WAL (Write-Ahead Logging) for zero-lag resumes and instant writes.
Includes automatic zero-loss migration from existing verifier_cache.json.
"""

import json
import os
import sqlite3
import sys
import threading
import time
from typing import Dict, List, Optional, Tuple


def _trim_raw_blob(result: Dict) -> Dict:
    """Removes unused raw Shazam API payloads from result dictionary to keep cache lightweight."""
    if not isinstance(result, dict):
        return result
    cleaned = dict(result)
    rec = cleaned.get("recognized")
    if isinstance(rec, dict) and "raw" in rec:
        rec_copy = dict(rec)
        rec_copy.pop("raw", None)
        cleaned["recognized"] = rec_copy
    return cleaned


class VerifierDatabase:
    """Thread-safe SQLite database manager for audio verification cache."""

    _instance = None
    _init_lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or self.get_default_db_path()
        self._lock = threading.Lock()
        self._conn = None
        self._init_db()
        self._auto_migrate_from_json()

    @classmethod
    def get_default_db_path(cls) -> str:
        exe_dir = (
            os.path.dirname(sys.executable)
            if getattr(sys, 'frozen', False)
            else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        return os.path.join(exe_dir, "verifier_cache.db")

    @classmethod
    def get_instance(cls, db_path: Optional[str] = None) -> "VerifierDatabase":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls(db_path)
            return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=20.0
            )
            # Enable WAL mode for non-blocking concurrent reads and writes
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA temp_store=MEMORY")
        return self._conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS verifier_cache (
                    file_path TEXT PRIMARY KEY,
                    mtime REAL,
                    size INTEGER,
                    status TEXT,
                    result_json TEXT,
                    updated_at REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_status ON verifier_cache(status)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS library_index (
                    file_path TEXT PRIMARY KEY,
                    mtime REAL,
                    size INTEGER,
                    artist TEXT,
                    title TEXT,
                    album TEXT,
                    duration_s REAL,
                    is_lossless INTEGER,
                    updated_at REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lib_artist ON library_index(artist)")
            conn.commit()

    def _auto_migrate_from_json(self):
        """Automatically migrates legacy verifier_cache.json into SQLite if DB is empty."""
        try:
            exe_dir = os.path.dirname(self.db_path)
            json_path = os.path.join(exe_dir, "verifier_cache.json")
            if not os.path.exists(json_path):
                return

            with self._lock:
                conn = self._get_connection()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM verifier_cache")
                count = cur.fetchone()[0]
                if count > 0:
                    # Already populated, skip migration
                    return

                print(f"[VerifierDatabase] Migrating legacy verifier_cache.json to SQLite database...")
                with open(json_path, "r", encoding="utf-8") as f:
                    legacy_data = json.load(f)

                rows = []
                now = time.time()
                for fp, entry in legacy_data.items():
                    res = _trim_raw_blob(entry.get("result", {}))
                    rows.append((
                        fp,
                        float(entry.get("mtime", 0.0)),
                        int(entry.get("size", 0)),
                        str(res.get("status", "")),
                        json.dumps(res, ensure_ascii=False),
                        now
                    ))

                if rows:
                    conn.executemany(
                        "INSERT OR REPLACE INTO verifier_cache VALUES (?, ?, ?, ?, ?, ?)",
                        rows
                    )
                    conn.commit()
                    print(f"[VerifierDatabase] Successfully migrated {len(rows)} tracks to SQLite cache ({self.db_path}).")
        except Exception as e:
            print(f"[VerifierDatabase] Migration warning: {e}")

    def get_track(self, file_path: str) -> Optional[Dict]:
        """Fetches a single cached track entry by file path."""
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT mtime, size, result_json FROM verifier_cache WHERE file_path = ?",
                (file_path,)
            )
            row = cur.fetchone()
            if row:
                mtime, size, r_json = row
                try:
                    res = json.loads(r_json)
                    return {"mtime": mtime, "size": size, "result": res}
                except Exception:
                    pass
        return None

    def put_track(self, file_path: str, mtime: float, size: int, result: Dict):
        """Inserts or updates a single track record atomically."""
        trimmed = _trim_raw_blob(result)
        status = str(trimmed.get("status", ""))
        r_json = json.dumps(trimmed, ensure_ascii=False)
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO verifier_cache VALUES (?, ?, ?, ?, ?, ?)",
                (file_path, float(mtime), int(size), status, r_json, time.time())
            )
            conn.commit()

    def delete_track(self, file_path: str):
        """Removes a track entry from the cache."""
        with self._lock:
            conn = self._get_connection()
            conn.execute("DELETE FROM verifier_cache WHERE file_path = ?", (file_path,))
            conn.commit()

    def load_all(self) -> Dict[str, Dict]:
        """Loads all cached records into a dictionary for backward compatibility."""
        cache_dict: Dict[str, Dict] = {}
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT file_path, mtime, size, result_json FROM verifier_cache")
            for fp, mtime, size, r_json in cur.fetchall():
                try:
                    res = json.loads(r_json)
                    cache_dict[fp] = {
                        "mtime": mtime,
                        "size": size,
                        "result": res
                    }
                except Exception:
                    pass
        return cache_dict

    def save_all(self, cache_dict: Dict[str, Dict]):
        """Persists a full dictionary of track entries in a single batch transaction."""
        rows = []
        now = time.time()
        for fp, entry in cache_dict.items():
            res = _trim_raw_blob(entry.get("result", {}))
            rows.append((
                fp,
                float(entry.get("mtime", 0.0)),
                int(entry.get("size", 0)),
                str(res.get("status", "")),
                json.dumps(res, ensure_ascii=False),
                now
            ))
        if rows:
            with self._lock:
                conn = self._get_connection()
                conn.executemany(
                    "INSERT OR REPLACE INTO verifier_cache VALUES (?, ?, ?, ?, ?, ?)",
                    rows
                )
                conn.commit()

    def clear(self):
        """Clears all entries from the verification cache."""
        with self._lock:
            conn = self._get_connection()
            conn.execute("DELETE FROM verifier_cache")
            conn.commit()

    def count(self) -> int:
        """Returns total number of cached records."""
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM verifier_cache")
            return cur.fetchone()[0]

    def checkpoint(self):
        """Flushes WAL journal writes to the main database file."""
        with self._lock:
            if self._conn:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                except Exception:
                    pass

    def get_library_index_map(self, prefix: str = "") -> Dict[str, Dict]:
        """Loads cached library tracks, optionally filtered by root directory prefix."""
        out: Dict[str, Dict] = {}
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            if prefix:
                norm_prefix = os.path.normpath(prefix)
                # Search using normalized prefix with like pattern
                cur.execute(
                    "SELECT file_path, mtime, size, artist, title, album, duration_s, is_lossless FROM library_index WHERE file_path LIKE ?",
                    (f"{norm_prefix}%",)
                )
            else:
                cur.execute("SELECT file_path, mtime, size, artist, title, album, duration_s, is_lossless FROM library_index")

            for row in cur.fetchall():
                fp, mtime, size, artist, title, album, dur_s, is_loss = row
                out[fp] = {
                    "file_path": fp,
                    "filename": os.path.basename(fp),
                    "mtime": mtime,
                    "size_bytes": size,
                    "artist": artist,
                    "title": title,
                    "album": album,
                    "duration_s": dur_s,
                    "is_lossless": bool(is_loss)
                }
        return out

    def put_library_tracks(self, tracks: List[Dict]):
        """Persists a batch of scanned library tracks into the library index."""
        if not tracks:
            return
        now = time.time()
        rows = []
        for t in tracks:
            rows.append((
                t["file_path"],
                float(t.get("mtime", 0.0)),
                int(t.get("size_bytes", 0)),
                str(t.get("artist", "")),
                str(t.get("title", "")),
                str(t.get("album", "")),
                float(t.get("duration_s", 0.0)),
                1 if t.get("is_lossless") else 0,
                now
            ))
        with self._lock:
            conn = self._get_connection()
            conn.executemany(
                "INSERT OR REPLACE INTO library_index VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows
            )
            conn.commit()
