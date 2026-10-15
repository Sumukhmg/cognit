"""Agent explainability and code lineage analysis."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from cognit.core.database import Database
from cognit.core.models import Checkpoint


@dataclass
class SymbolLineageRecord:
    """Historical record of an agent modifying a code symbol."""

    checkpoint_id: str
    timestamp: str
    author: str
    agent_id: str
    model: str
    goal: str
    reasoning: str
    test_status: str
    message: str
    start_line: int
    end_line: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExplainEngine:
    """Explains why code exists and traces agent prompts and reasoning."""

    def __init__(self, db: Database, repo: Any) -> None:
        self.db = db
        self.repo = repo

    def explain_symbol(self, file_path: str, symbol_name: str) -> List[SymbolLineageRecord]:
        """Trace the full prompt, model, reasoning, and test history for a symbol."""
        history = self.db.find_symbol_history(file_path, symbol_name)
        records: List[SymbolLineageRecord] = []

        for row in history:
            cp = self.db.get_checkpoint(row["checkpoint_id"])
            if cp:
                records.append(SymbolLineageRecord(
                    checkpoint_id=cp.id,
                    timestamp=cp.timestamp,
                    author=cp.author,
                    agent_id=cp.agent_metadata.agent_id,
                    model=cp.agent_metadata.model,
                    goal=cp.agent_metadata.goal,
                    reasoning=cp.agent_metadata.reasoning,
                    test_status=cp.agent_metadata.test_status,
                    message=cp.message,
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                ))

        return records

    def explain_file(self, file_path: str) -> Dict[str, Any]:
        """Aggregate summary of all agents, models, goals, and changes to a file."""
        all_checkpoints = self.db.get_all_checkpoints(limit=200)
        file_checkpoints: List[Checkpoint] = []

        for cp in all_checkpoints:
            # Check if tree contains file
            tree_entries = self.repo.storage.read_tree(cp.tree_hash)
            if any(e.path == file_path for e in tree_entries):
                file_checkpoints.append(cp)

        models_used = set()
        agents_used = set()
        total_tokens = 0
        goals: List[str] = []

        for cp in file_checkpoints:
            if cp.agent_metadata.model and cp.agent_metadata.model != "unknown":
                models_used.add(cp.agent_metadata.model)
            if cp.agent_metadata.agent_id:
                agents_used.add(cp.agent_metadata.agent_id)
            total_tokens += cp.agent_metadata.tokens_used
            if cp.agent_metadata.goal:
                goals.append(f"[{cp.timestamp[:10]}] {cp.agent_metadata.goal}")

        return {
            "file_path": file_path,
            "checkpoints_count": len(file_checkpoints),
            "agents_involved": list(agents_used),
            "models_used": list(models_used),
            "total_tokens_invested": total_tokens,
            "recent_goals": goals[:10],
            "recent_checkpoints": [
                {
                    "id": cp.id[:8],
                    "message": cp.message,
                    "agent": cp.agent_metadata.agent_id,
                    "model": cp.agent_metadata.model,
                    "goal": cp.agent_metadata.goal,
                    "test_status": cp.agent_metadata.test_status,
                }
                for cp in file_checkpoints[:5]
            ],
        }
