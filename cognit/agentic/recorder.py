"""Agent Flight Recorder and Continuous Micro-Versioning Engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from cognit.core.models import TreeEntry, current_iso_timestamp


@dataclass
class MicroSnapshot:
    """An ephemeral micro-version recorded during agent execution."""

    step_index: int
    timestamp: str
    agent_id: str
    action: str
    tree_hash: str
    modified_files: List[str]
    syntax_valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> MicroSnapshot:
        if not d:
            return cls(step_index=0, timestamp="", agent_id="agent", action="", tree_hash="", modified_files=[])
        return cls(
            step_index=d.get("step_index", 0),
            timestamp=d.get("timestamp", ""),
            agent_id=d.get("agent_id", "agent"),
            action=d.get("action", ""),
            tree_hash=d.get("tree_hash", ""),
            modified_files=d.get("modified_files", []),
            syntax_valid=d.get("syntax_valid", True),
        )


class FlightRecorder:
    """Records millisecond-level code snapshots during agent execution steps."""

    def __init__(self, repo: Any) -> None:
        self.repo = repo
        self.recorder_dir = self.repo.cognit_dir / "recorder"
        self.recorder_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.recorder_dir / "flight_log.json"
        self._ensure_log()

    def _ensure_log(self) -> None:
        if not self.index_file.exists():
            self.index_file.write_text("[]", encoding="utf-8")

    def _read_log(self) -> List[MicroSnapshot]:
        try:
            data = json.loads(self.index_file.read_text(encoding="utf-8"))
            return [MicroSnapshot.from_dict(d) for d in data]
        except Exception:
            return []

    def _write_log(self, snapshots: List[MicroSnapshot]) -> None:
        self.index_file.write_text(
            json.dumps([s.to_dict() for s in snapshots], indent=2),
            encoding="utf-8"
        )

    def record_step(self, action: str, agent_id: str = "agent") -> MicroSnapshot:
        """Capture current working directory tree as a micro-snapshot."""
        working_files = self.repo.list_working_files()
        tree_entries: List[TreeEntry] = []
        syntax_ok = True

        for rel_path in working_files:
            full_p = self.repo.root_dir / rel_path
            raw_bytes = full_p.read_bytes()
            blob_hash = self.repo.storage.write_blob(raw_bytes)

            # Check Python syntax if python file
            if rel_path.endswith(".py"):
                try:
                    import ast
                    ast.parse(raw_bytes.decode("utf-8", errors="replace"))
                except SyntaxError:
                    syntax_ok = False

            tree_entries.append(TreeEntry(
                path=rel_path,
                blob_hash=blob_hash,
                size=len(raw_bytes),
            ))

        tree_hash = self.repo.storage.write_tree(tree_entries)
        log = self._read_log()
        next_idx = len(log) + 1

        # Determine modified files compared to last step
        mod_files = []
        if log:
            last_entries = {e.path: e.blob_hash for e in self.repo.storage.read_tree(log[-1].tree_hash)}
            for entry in tree_entries:
                if entry.path not in last_entries or last_entries[entry.path] != entry.blob_hash:
                    mod_files.append(entry.path)
        else:
            mod_files = [e.path for e in tree_entries]

        snapshot = MicroSnapshot(
            step_index=next_idx,
            timestamp=current_iso_timestamp(),
            agent_id=agent_id,
            action=action,
            tree_hash=tree_hash,
            modified_files=mod_files,
            syntax_valid=syntax_ok,
        )

        log.append(snapshot)
        # Cap flight recorder at last 100 micro-steps to stay lightweight
        if len(log) > 100:
            log = log[-100:]
        self._write_log(log)
        return snapshot

    def rollback(self, steps: int = 1) -> Optional[MicroSnapshot]:
        """Roll back working directory by N micro-steps."""
        log = self._read_log()
        if not log or steps <= 0:
            return None

        target_idx = max(0, len(log) - 1 - steps)
        target_snap = log[target_idx]

        # Restore tree
        self._restore_tree(target_snap.tree_hash)

        # Truncate log to target
        self._write_log(log[: target_idx + 1])
        return target_snap

    def restore_last_valid_syntax(self) -> Optional[MicroSnapshot]:
        """Roll back to the most recent micro-snapshot with valid syntax."""
        log = self._read_log()
        for idx in range(len(log) - 1, -1, -1):
            if log[idx].syntax_valid:
                target_snap = log[idx]
                self._restore_tree(target_snap.tree_hash)
                self._write_log(log[: idx + 1])
                return target_snap
        return None

    def _restore_tree(self, tree_hash: str) -> None:
        """Apply tree to working directory."""
        tree_entries = self.repo.storage.read_tree(tree_hash)
        expected = {e.path: e for e in tree_entries}

        # Remove deleted
        for f in self.repo.list_working_files():
            if f not in expected:
                p = self.repo.root_dir / f
                if p.is_file():
                    try:
                        p.unlink()
                    except OSError:
                        pass
                parent = p.parent
                while parent != self.repo.root_dir and parent.exists():
                    try:
                        if not any(parent.iterdir()):
                            parent.rmdir()
                            parent = parent.parent
                        else:
                            break
                    except OSError:
                        break

        # Write current safely
        for path, entry in expected.items():
            full_p = (self.repo.root_dir / path).resolve()
            if not full_p.is_relative_to(self.repo.root_dir.resolve()):
                raise ValueError(f"Path traversal detected in snapshot tree: '{path}'")
            full_p.parent.mkdir(parents=True, exist_ok=True)
            blob = self.repo.storage.read_blob(entry.blob_hash)
            full_p.write_bytes(blob)
            stat = full_p.stat()
            self.repo.db.update_file_cache(path, stat.st_mtime, stat.st_size, entry.blob_hash)

    def get_timeline(self) -> List[MicroSnapshot]:
        """Return the flight recorder step timeline."""
        return self._read_log()
