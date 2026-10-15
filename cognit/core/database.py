"""SQLite index and query database for high-speed metadata and symbol indexing."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cognit.core.models import Checkpoint, Symbol, SpeculativeTrial


from contextlib import contextmanager


class Database:
    """Manages the SQLite database at .cognit/index.db"""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS file_cache (
                    path TEXT PRIMARY KEY,
                    mtime REAL,
                    size INTEGER,
                    blob_hash TEXT,
                    staged INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    parent_ids TEXT,
                    tree_hash TEXT,
                    timestamp TEXT,
                    author TEXT,
                    message TEXT,
                    branch TEXT,
                    agent_id TEXT,
                    model TEXT,
                    goal TEXT,
                    reasoning TEXT,
                    tools_used TEXT,
                    test_status TEXT,
                    test_output TEXT,
                    tokens_used INTEGER,
                    confidence_score REAL,
                    extra TEXT
                );

                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checkpoint_id TEXT,
                    file_path TEXT,
                    name TEXT,
                    kind TEXT,
                    start_line INTEGER,
                    end_line INTEGER,
                    signature TEXT,
                    docstring TEXT,
                    body_hash TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_symbols_checkpoint ON symbols(checkpoint_id);
                CREATE INDEX IF NOT EXISTS idx_symbols_file_name ON symbols(file_path, name);

                CREATE TABLE IF NOT EXISTS speculative_trials (
                    name TEXT PRIMARY KEY,
                    base_checkpoint_id TEXT,
                    current_checkpoint_id TEXT,
                    status TEXT,
                    created_at TEXT,
                    score REAL,
                    evaluation_notes TEXT,
                    test_passed INTEGER
                );

                CREATE TABLE IF NOT EXISTS intent_locks (
                    target TEXT PRIMARY KEY,
                    agent_id TEXT,
                    goal TEXT,
                    acquired_at TEXT,
                    expires_at TEXT
                );
            """)
            conn.commit()

    # File cache operations
    def get_cached_file(self, path: str) -> Optional[sqlite3.Row]:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM file_cache WHERE path = ?", (path,))
            return cur.fetchone()

    def update_file_cache(self, path: str, mtime: float, size: int, blob_hash: str, staged: int = 0) -> None:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO file_cache (path, mtime, size, blob_hash, staged)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime=excluded.mtime,
                    size=excluded.size,
                    blob_hash=excluded.blob_hash,
                    staged=excluded.staged
            """, (path, mtime, size, blob_hash, staged))
            conn.commit()

    def remove_file_cache(self, path: str) -> None:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM file_cache WHERE path = ?", (path,))
            conn.commit()

    def get_all_cached_files(self) -> Dict[str, sqlite3.Row]:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM file_cache")
            return {row["path"]: row for row in cur.fetchall()}

    # Checkpoint operations
    def record_checkpoint(self, cp: Checkpoint) -> None:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO checkpoints (
                    id, parent_ids, tree_hash, timestamp, author, message, branch,
                    agent_id, model, goal, reasoning, tools_used,
                    test_status, test_output, tokens_used, confidence_score, extra
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cp.id,
                json.dumps(cp.parent_ids),
                cp.tree_hash,
                cp.timestamp,
                cp.author,
                cp.message,
                cp.branch,
                cp.agent_metadata.agent_id,
                cp.agent_metadata.model,
                cp.agent_metadata.goal,
                cp.agent_metadata.reasoning,
                json.dumps(cp.agent_metadata.tools_used),
                cp.agent_metadata.test_status,
                cp.agent_metadata.test_output,
                cp.agent_metadata.tokens_used,
                cp.agent_metadata.confidence_score,
                json.dumps(cp.agent_metadata.extra),
            ))
            conn.commit()

    def get_checkpoint(self, cp_id: str) -> Optional[Checkpoint]:
        if not cp_id:
            return None
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM checkpoints WHERE id = ?", (cp_id,))
            row = cur.fetchone()
            if row:
                return self._row_to_checkpoint(row)

            # Fallback to unique prefix match (min 4 characters)
            if len(cp_id) >= 4:
                safe_prefix = cp_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                cur.execute("SELECT * FROM checkpoints WHERE id LIKE ? ESCAPE '\\' LIMIT 2", (f"{safe_prefix}%",))
                rows = cur.fetchall()
                if len(rows) == 1:
                    return self._row_to_checkpoint(rows[0])
                elif len(rows) > 1:
                    raise ValueError(f"Ambiguous checkpoint ID prefix: '{cp_id}' matches multiple checkpoints.")
            return None

    def find_checkpoints_by_prefix(self, prefix: str) -> List[Checkpoint]:
        if not prefix:
            return []
        safe_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM checkpoints WHERE id LIKE ? ESCAPE '\\' ORDER BY timestamp DESC", (f"{safe_prefix}%",))
            return [self._row_to_checkpoint(r) for r in cur.fetchall()]

    def get_all_checkpoints(self, limit: int = 100, branch: Optional[str] = None) -> List[Checkpoint]:
        with self._connection() as conn:
            cur = conn.cursor()
            if branch:
                cur.execute("SELECT * FROM checkpoints WHERE branch = ? ORDER BY timestamp DESC LIMIT ?", (branch, limit))
            else:
                cur.execute("SELECT * FROM checkpoints ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [self._row_to_checkpoint(r) for r in cur.fetchall()]

    def _row_to_checkpoint(self, r: sqlite3.Row) -> Checkpoint:
        from cognit.core.models import AgentMetadata
        return Checkpoint(
            id=r["id"],
            parent_ids=json.loads(r["parent_ids"] or "[]"),
            tree_hash=r["tree_hash"],
            timestamp=r["timestamp"],
            author=r["author"],
            message=r["message"],
            branch=r["branch"],
            agent_metadata=AgentMetadata(
                agent_id=r["agent_id"] or "human",
                model=r["model"] or "unknown",
                goal=r["goal"] or "",
                reasoning=r["reasoning"] or "",
                tools_used=json.loads(r["tools_used"] or "[]"),
                test_status=r["test_status"] or "untested",
                test_output=r["test_output"] or "",
                tokens_used=r["tokens_used"] or 0,
                confidence_score=r["confidence_score"],
                extra=json.loads(r["extra"] or "{}"),
            )
        )

    # Symbol indexing
    def record_symbols(self, checkpoint_id: str, file_path: str, symbols: List[Symbol]) -> None:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM symbols WHERE checkpoint_id = ? AND file_path = ?", (checkpoint_id, file_path))
            for s in symbols:
                cur.execute("""
                    INSERT INTO symbols (checkpoint_id, file_path, name, kind, start_line, end_line, signature, docstring, body_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    checkpoint_id, file_path, s.name, s.kind, s.start_line, s.end_line, s.signature, s.docstring, s.body_hash
                ))
            conn.commit()

    def find_symbol_history(self, file_path: str, symbol_name: str) -> List[Tuple[str, str, int, int]]:
        """Return history (checkpoint_id, timestamp, start_line, end_line) of a symbol."""
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT s.checkpoint_id, c.timestamp, s.start_line, s.end_line, c.message, c.agent_id, c.model, c.goal
                FROM symbols s
                JOIN checkpoints c ON s.checkpoint_id = c.id
                WHERE s.file_path = ? AND s.name = ?
                ORDER BY c.timestamp DESC
            """, (file_path, symbol_name))
            return cur.fetchall()

    # Speculative Trials
    def record_trial(self, trial: SpeculativeTrial) -> None:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO speculative_trials
                (name, base_checkpoint_id, current_checkpoint_id, status, created_at, score, evaluation_notes, test_passed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trial.name, trial.base_checkpoint_id, trial.current_checkpoint_id,
                trial.status, trial.created_at, trial.score, trial.evaluation_notes,
                1 if trial.test_passed else 0 if trial.test_passed is not None else None
            ))
            conn.commit()

    def get_trial(self, name: str) -> Optional[SpeculativeTrial]:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM speculative_trials WHERE name = ?", (name,))
            row = cur.fetchone()
            if not row:
                return None
            return SpeculativeTrial(
                name=row["name"],
                base_checkpoint_id=row["base_checkpoint_id"],
                current_checkpoint_id=row["current_checkpoint_id"],
                status=row["status"],
                created_at=row["created_at"],
                score=row["score"],
                evaluation_notes=row["evaluation_notes"] or "",
                test_passed=bool(row["test_passed"]) if row["test_passed"] is not None else None
            )

    def list_trials(self) -> List[SpeculativeTrial]:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM speculative_trials ORDER BY created_at DESC")
            return [
                SpeculativeTrial(
                    name=r["name"],
                    base_checkpoint_id=r["base_checkpoint_id"],
                    current_checkpoint_id=r["current_checkpoint_id"],
                    status=r["status"],
                    created_at=r["created_at"],
                    score=r["score"],
                    evaluation_notes=r["evaluation_notes"] or "",
                    test_passed=bool(r["test_passed"]) if r["test_passed"] is not None else None
                )
                for r in cur.fetchall()
            ]

    # Intent locks for multi-agent swarm collaboration
    def acquire_lock(self, target: str, agent_id: str, goal: str, expires_at: str) -> bool:
        from cognit.core.models import current_iso_timestamp
        with self._connection() as conn:
            cur = conn.cursor()
            # Clean expired locks first
            cur.execute("DELETE FROM intent_locks WHERE expires_at < ?", (current_iso_timestamp(),))
            # Try to acquire
            try:
                cur.execute("""
                    INSERT INTO intent_locks (target, agent_id, goal, acquired_at, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (target, agent_id, goal, current_iso_timestamp(), expires_at))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Check if already held by this agent
                cur.execute("SELECT agent_id FROM intent_locks WHERE target = ?", (target,))
                row = cur.fetchone()
                if row and row["agent_id"] == agent_id:
                    cur.execute("""
                        UPDATE intent_locks SET goal = ?, expires_at = ? WHERE target = ?
                    """, (goal, expires_at, target))
                    conn.commit()
                    return True
                return False

    def release_lock(self, target: str, agent_id: str) -> bool:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM intent_locks WHERE target = ? AND agent_id = ?", (target, agent_id))
            conn.commit()
            return cur.rowcount > 0

    def list_locks(self) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM intent_locks")
            return [dict(r) for r in cur.fetchall()]
