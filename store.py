"""Evidence store for Hermes Detox.

Saves original tool outputs to a local SQLite database in WAL mode.
Provides exact line retrieval and aggregate status metrics.
"""

from __future__ import annotations

import datetime
import logging
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid

logger = logging.getLogger("hermes_detox.store")

# Storage directory override (used primarily by tests)
_LOCAL_STORAGE_OVERRIDE: Optional[Path] = None


def set_storage_dir_override(path: Optional[Path]) -> None:
    """Override storage directory (used primarily by tests)."""
    global _LOCAL_STORAGE_OVERRIDE
    _LOCAL_STORAGE_OVERRIDE = path
    # Reset instance when storage path changes
    EvidenceStore.reset_instance()


def resolve_data_dir() -> Path:
    """Resolve the persistent data directory for hermes-detox.
    
    Tries the official plugins.plugin_storage helper first, then falls back
    to the standard Hermes home path, never writing inside the plugin directory.
    """
    if _LOCAL_STORAGE_OVERRIDE is not None:
        _LOCAL_STORAGE_OVERRIDE.mkdir(parents=True, exist_ok=True)
        return _LOCAL_STORAGE_OVERRIDE

    # 1. Try documented plugin_data_dir helper if available
    try:
        from plugins.plugin_storage import plugin_data_dir
        path = Path(plugin_data_dir("hermes-detox"))
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        pass

    # 2. Try hermes_constants get_hermes_home
    try:
        from hermes_constants import get_hermes_home
        base = get_hermes_home()
        path = base / "plugin-data" / "hermes-detox"
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        pass

    # 3. Fallback to ~/.hermes/plugin-data/hermes-detox
    base = Path.home() / ".hermes"
    path = base / "plugin-data" / "hermes-detox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path() -> Path:
    """Return the absolute path to the detox evidence database."""
    return resolve_data_dir() / "detox.db"


def _init_db_connection(db_path: Path) -> sqlite3.Connection:
    """Open and configure a SQLite connection in WAL mode with restrictive permissions."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        os.chmod(db_path.parent, 0o700)
    except Exception:
        pass

    conn = sqlite3.connect(
        str(db_path),
        timeout=30.0,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row

    # Enforce WAL mode for safe concurrent access
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")

    try:
        if db_path.exists():
            os.chmod(db_path, 0o600)
    except Exception:
        pass

    # Create schema
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                original_output TEXT NOT NULL,
                original_size INTEGER NOT NULL,
                transformed_size INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                status TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_evidence_session_time 
            ON evidence(session_id, timestamp);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_evidence_tool 
            ON evidence(tool_name);
        """)

    return conn


class EvidenceStore:
    """Thread-safe evidence storage backed by SQLite in WAL mode."""

    _instance: Optional["EvidenceStore"] = None
    _lock = threading.RLock()  # Re-entrant lock prevents recursive deadlocks

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_db_path()
        self._local = threading.local()
        self._connections: List[sqlite3.Connection] = []

    @classmethod
    def get_instance(cls) -> "EvidenceStore":
        """Get or create singleton store instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(get_db_path())
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton store and close connections."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = _init_db_connection(self.db_path)
            self._local.conn = conn
            with self._lock:
                self._connections.append(conn)
        return conn

    def close(self) -> None:
        """Close all opened connections."""
        with self._lock:
            for conn in self._connections:
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()
        if hasattr(self._local, "conn"):
            self._local.conn = None

    def save(
        self,
        session_id: str,
        tool_name: str,
        original_output: str,
        transformed_size: int,
        content_type: str = "text/plain",
        status: str = "success",
        evidence_id: Optional[str] = None,
    ) -> str:
        """Save evidence record to database. Returns the generated or passed evidence ID."""
        ev_id = evidence_id or f"ev_{uuid.uuid4().hex[:12]}"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        orig_size = len(original_output)

        conn = self._get_conn()
        with conn:
            conn.execute(
                """
                INSERT INTO evidence (
                    id, session_id, tool_name, timestamp, 
                    original_output, original_size, transformed_size, 
                    content_type, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev_id,
                    session_id or "default",
                    tool_name,
                    now,
                    original_output,
                    orig_size,
                    transformed_size,
                    content_type,
                    status,
                ),
            )
        logger.info(
            "Saved evidence %s for tool %s (%d chars -> %d chars)",
            ev_id,
            tool_name,
            orig_size,
            transformed_size,
        )
        return ev_id

    def get(self, evidence_id: str, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve full evidence record by ID. Enforces session isolation when session_id is provided."""
        conn = self._get_conn()
        if session_id:
            cursor = conn.execute(
                "SELECT * FROM evidence WHERE id = ? AND session_id = ?",
                (evidence_id, session_id),
            )
        else:
            cursor = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

    def get_lines(
        self,
        evidence_id: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
        max_chars: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retrieve exact 1-based line slice from stored evidence."""
        record = self.get(evidence_id, session_id=session_id)
        if not record:
            return {
                "success": False,
                "error": f"Evidence not found: {evidence_id}" + (f" for session {session_id}" if session_id else ""),
                "id": evidence_id,
            }

        original = record["original_output"]
        all_lines = original.splitlines()
        total_lines = len(all_lines)

        start = max(1, start_line)
        end = total_lines if end_line is None else min(total_lines, max(start, end_line))

        selected_lines = all_lines[start - 1 : end]
        content = "\n".join(selected_lines)

        if max_chars is not None and max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars] + f"\n... [Truncated to {max_chars} chars] ..."

        return {
            "success": True,
            "id": evidence_id,
            "tool_name": record["tool_name"],
            "session_id": record["session_id"],
            "timestamp": record["timestamp"],
            "total_lines": total_lines,
            "start_line": start,
            "end_line": end,
            "line_count": len(selected_lines),
            "lines": selected_lines,
            "content": content,
        }

    def search_lines(
        self,
        query: str,
        evidence_id: Optional[str] = None,
        session_id: Optional[str] = None,
        case_sensitive: bool = False,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Search lines in stored evidence matching a query string."""
        conn = self._get_conn()
        results: List[Dict[str, Any]] = []

        if evidence_id:
            if session_id:
                cursor = conn.execute(
                    "SELECT id, tool_name, session_id, original_output FROM evidence WHERE id = ? AND session_id = ?",
                    (evidence_id, session_id),
                )
            else:
                cursor = conn.execute(
                    "SELECT id, tool_name, session_id, original_output FROM evidence WHERE id = ?",
                    (evidence_id,),
                )
        else:
            if session_id:
                cursor = conn.execute(
                    "SELECT id, tool_name, session_id, original_output FROM evidence WHERE session_id = ? ORDER BY timestamp DESC LIMIT 50",
                    (session_id,),
                )
            else:
                cursor = conn.execute(
                    "SELECT id, tool_name, session_id, original_output FROM evidence ORDER BY timestamp DESC LIMIT 50"
                )

        target = query if case_sensitive else query.lower()

        for row in cursor.fetchall():
            row_id = row["id"]
            row_tool = row["tool_name"]
            lines = row["original_output"].splitlines()
            for line_no, line in enumerate(lines, start=1):
                comparison = line if case_sensitive else line.lower()
                if target in comparison:
                    results.append({
                        "evidence_id": row_id,
                        "tool_name": row_tool,
                        "line_number": line_no,
                        "line": line,
                    })
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break

        return {
            "success": True,
            "query": query,
            "matches_count": len(results),
            "limit": limit,
            "results": results,
        }

    def status(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Calculate aggregate interception metrics."""
        conn = self._get_conn()
        if session_id:
            cursor = conn.execute(
                """
                SELECT 
                    COUNT(*) as total_intercepted,
                    COALESCE(SUM(original_size), 0) as chars_in,
                    COALESCE(SUM(transformed_size), 0) as chars_out
                FROM evidence
                WHERE session_id = ?
                """,
                (session_id,),
            )
        else:
            cursor = conn.execute(
                """
                SELECT 
                    COUNT(*) as total_intercepted,
                    COALESCE(SUM(original_size), 0) as chars_in,
                    COALESCE(SUM(transformed_size), 0) as chars_out
                FROM evidence
                """
            )
        row = cursor.fetchone()
        chars_in = int(row["chars_in"])
        chars_out = int(row["chars_out"])
        chars_saved = max(0, chars_in - chars_out)
        saved_pct = (chars_saved / chars_in * 100.0) if chars_in > 0 else 0.0

        return {
            "success": True,
            "session_id": session_id or "all",
            "outputs_intercepted": int(row["total_intercepted"]),
            "characters_in": chars_in,
            "characters_out": chars_out,
            "characters_saved": chars_saved,
            "saved_percentage": round(saved_pct, 1),
        }
