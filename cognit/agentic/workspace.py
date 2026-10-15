"""Multi-Agent Virtual Workspace Manager for concurrent agent execution."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from cognit.core.models import (
    AgentMetadata,
    Checkpoint,
    TreeEntry,
    current_iso_timestamp,
)


@dataclass
class AgentWorkspace:
    """An isolated working directory for an agent running in parallel."""

    agent_id: str
    branch_name: str
    workspace_dir: str
    created_at: str
    active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AgentWorkspace:
        if not d:
            return cls(agent_id="", branch_name="", workspace_dir="", created_at="")
        return cls(
            agent_id=d.get("agent_id", ""),
            branch_name=d.get("branch_name", ""),
            workspace_dir=d.get("workspace_dir", ""),
            created_at=d.get("created_at", ""),
            active=d.get("active", True),
        )


class WorkspaceManager:
    """Manages isolated workspaces for multi-agent swarm parallelism."""

    def __init__(self, repo: Any) -> None:
        self.repo = repo
        self.workspaces_root = self.repo.cognit_dir / "workspaces"
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.workspaces_root / "registry.json"
        self._ensure_registry()

    def _ensure_registry(self) -> None:
        if not self.registry_file.exists():
            self.registry_file.write_text("{}", encoding="utf-8")

    def _read_registry(self) -> Dict[str, Dict]:
        try:
            return json.loads(self.registry_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_registry(self, data: Dict[str, Dict]) -> None:
        self.registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def create_workspace(self, agent_id: str, branch_name: Optional[str] = None) -> AgentWorkspace:
        """Create an isolated workspace folder populated from branch HEAD."""
        clean_id = agent_id.strip() if agent_id else ""
        if not clean_id or ".." in clean_id or clean_id.startswith(("/", "\\")) or ":" in clean_id:
            raise ValueError(f"Invalid agent_id '{agent_id}': contains invalid characters or path traversal.")

        branch = branch_name or f"agents/{clean_id}"
        ws_dir = (self.workspaces_root / clean_id).resolve()
        if not ws_dir.is_relative_to(self.workspaces_root.resolve()) or ws_dir == self.workspaces_root.resolve():
            raise ValueError(f"Path traversal detected in agent_id '{agent_id}'.")

        # Ensure branch exists in repo
        if not self.repo.get_branch_checkpoint(branch):
            self.repo.create_branch(branch)

        # Populate workspace directory from branch tree
        cid = self.repo.get_branch_checkpoint(branch)
        if ws_dir.exists():
            shutil.rmtree(ws_dir, ignore_errors=True)
        ws_dir.mkdir(parents=True, exist_ok=True)

        if cid:
            cp = self.repo.storage.read_checkpoint(cid)
            tree_entries = self.repo.storage.read_tree(cp.tree_hash)
            for entry in tree_entries:
                out_p = (ws_dir / entry.path).resolve()
                if not out_p.is_relative_to(ws_dir):
                    raise ValueError(f"Path traversal detected in tree entry: '{entry.path}'")
                out_p.parent.mkdir(parents=True, exist_ok=True)
                blob = self.repo.storage.read_blob(entry.blob_hash)
                out_p.write_bytes(blob)

        ws = AgentWorkspace(
            agent_id=clean_id,
            branch_name=branch,
            workspace_dir=str(ws_dir),
            created_at=current_iso_timestamp(),
            active=True,
        )

        reg = self._read_registry()
        reg[clean_id] = ws.to_dict()
        self._write_registry(reg)
        return ws

    def commit_workspace(
        self,
        agent_id: str,
        message: str,
        metadata: Optional[AgentMetadata] = None,
    ) -> Checkpoint:
        """Commit changes inside an agent workspace onto its designated branch."""
        reg = self._read_registry()
        if agent_id not in reg:
            raise ValueError(f"Workspace for agent '{agent_id}' does not exist.")

        ws_info = reg[agent_id]
        ws_path = Path(ws_info["workspace_dir"])
        branch = ws_info["branch_name"]

        # Temporarily use CognitRepo operations on ws_path
        working_files = []
        for root, _, files in os.walk(ws_path):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), ws_path).replace("\\", "/")
                working_files.append(rel)

        tree_entries = []
        for rel in working_files:
            fp = ws_path / rel
            data = fp.read_bytes()
            blob_hash = self.repo.storage.write_blob(data)
            tree_entries.append(TreeEntry(path=rel, blob_hash=blob_hash, size=len(data)))

        tree_hash = self.repo.storage.write_tree(tree_entries)
        parent_id = self.repo.get_branch_checkpoint(branch)

        meta = metadata or AgentMetadata(agent_id=agent_id)
        cp = Checkpoint(
            id="",
            parent_ids=[parent_id] if parent_id else [],
            tree_hash=tree_hash,
            timestamp=current_iso_timestamp(),
            author=f"Agent:{agent_id}",
            message=message,
            branch=branch,
            agent_metadata=meta,
        )

        cid = self.repo.storage.write_checkpoint(cp)
        self.repo.db.record_checkpoint(cp)

        # Index symbols for agent search & explainability
        for entry in tree_entries:
            if not entry.is_binary:
                try:
                    content = (ws_path / entry.path).read_text(encoding="utf-8", errors="replace")
                    from cognit.semantic.parser import ASTParser
                    symbols = ASTParser.parse_file(entry.path, content)
                    if symbols:
                        self.repo.db.record_symbols(cid, entry.path, symbols)
                except Exception:
                    pass

        self.repo.set_branch_checkpoint(branch, cid)
        return cp

    def list_workspaces(self) -> List[AgentWorkspace]:
        reg = self._read_registry()
        return [AgentWorkspace.from_dict(v) for v in reg.values()]

    def destroy_workspace(self, agent_id: str) -> bool:
        reg = self._read_registry()
        clean_id = agent_id.strip() if agent_id else ""
        if clean_id in reg:
            ws_path = Path(reg[clean_id]["workspace_dir"]).resolve()
            if ws_path.is_relative_to(self.workspaces_root.resolve()) and ws_path != self.workspaces_root.resolve() and ws_path.exists():
                shutil.rmtree(ws_path, ignore_errors=True)
            del reg[clean_id]
            self._write_registry(reg)
            return True
        return False
