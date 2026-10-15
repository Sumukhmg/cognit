"""Data models for Cognit version control system."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def current_iso_timestamp() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentMetadata:
    """Rich provenance and reasoning metadata for AI agent changes."""

    agent_id: str = "human"
    model: str = "unknown"
    goal: str = ""
    reasoning: str = ""
    tools_used: List[str] = field(default_factory=list)
    test_status: str = "untested"  # "passed", "failed", "skipped", "untested"
    test_output: str = ""
    tokens_used: int = 0
    confidence_score: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentMetadata:
        if not data:
            return cls()
        return cls(
            agent_id=data.get("agent_id", "human"),
            model=data.get("model", "unknown"),
            goal=data.get("goal", ""),
            reasoning=data.get("reasoning", ""),
            tools_used=data.get("tools_used", []),
            test_status=data.get("test_status", "untested"),
            test_output=data.get("test_output", ""),
            tokens_used=data.get("tokens_used", 0),
            confidence_score=data.get("confidence_score"),
            extra=data.get("extra", {}),
        )


@dataclass
class TreeEntry:
    """Represents a file snapshot inside a tree."""

    path: str  # POSIX relative path, e.g. "src/main.py"
    blob_hash: str  # SHA-256 hash of object
    size: int
    mode: int = 0o644
    is_binary: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TreeEntry:
        return cls(
            path=data["path"],
            blob_hash=data["blob_hash"],
            size=data.get("size", 0),
            mode=data.get("mode", 0o644),
            is_binary=data.get("is_binary", False),
        )


@dataclass
class Checkpoint:
    """An immutable, content-addressed commit/checkpoint in Cognit."""

    id: str  # SHA-256 of canonical checkpoint payload
    parent_ids: List[str]
    tree_hash: str
    timestamp: str = field(default_factory=current_iso_timestamp)
    author: str = "Agent"
    message: str = ""
    branch: str = "main"
    agent_metadata: AgentMetadata = field(default_factory=AgentMetadata)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "parent_ids": self.parent_ids,
            "tree_hash": self.tree_hash,
            "timestamp": self.timestamp,
            "author": self.author,
            "message": self.message,
            "branch": self.branch,
            "agent_metadata": self.agent_metadata.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Checkpoint:
        return cls(
            id=data["id"],
            parent_ids=data.get("parent_ids", []),
            tree_hash=data["tree_hash"],
            timestamp=data.get("timestamp", current_iso_timestamp()),
            author=data.get("author", "Agent"),
            message=data.get("message", ""),
            branch=data.get("branch", "main"),
            agent_metadata=AgentMetadata.from_dict(data.get("agent_metadata", {})),
        )


@dataclass
class Symbol:
    """An AST-level code symbol (function, class, method, import)."""

    name: str
    kind: str  # "function", "class", "method", "import", "variable"
    start_line: int
    end_line: int
    signature: str = ""
    docstring: Optional[str] = None
    body_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Symbol:
        if not data:
            return cls(name="", kind="function", start_line=1, end_line=1)
        return cls(
            name=data.get("name", ""),
            kind=data.get("kind", "function"),
            start_line=data.get("start_line", 1),
            end_line=data.get("end_line", 1),
            signature=data.get("signature", ""),
            docstring=data.get("docstring"),
            body_hash=data.get("body_hash", ""),
        )


@dataclass
class FileStatus:
    """Status of a file in the working directory compared to HEAD."""

    path: str
    status: str  # "unmodified", "modified", "added", "deleted", "untracked"
    staged: bool = False
    size: int = 0
    symbols_changed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SpeculativeTrial:
    """A speculative branch created by an agent during exploration."""

    name: str
    base_checkpoint_id: str
    current_checkpoint_id: str
    status: str = "active"  # "active", "accepted", "discarded"
    created_at: str = field(default_factory=current_iso_timestamp)
    score: Optional[float] = None
    evaluation_notes: str = ""
    test_passed: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SpeculativeTrial:
        if not data:
            return cls(name="", base_checkpoint_id="", current_checkpoint_id="")
        return cls(
            name=data["name"],
            base_checkpoint_id=data["base_checkpoint_id"],
            current_checkpoint_id=data["current_checkpoint_id"],
            status=data.get("status", "active"),
            created_at=data.get("created_at", current_iso_timestamp()),
            score=data.get("score"),
            evaluation_notes=data.get("evaluation_notes", ""),
            test_passed=data.get("test_passed"),
        )
