"""Agentic version control modules: speculative branches, intent locks, and explainability."""

from cognit.agentic.speculative import SpeculativeManager
from cognit.agentic.intent_locks import IntentLockManager
from cognit.agentic.explain import ExplainEngine, SymbolLineageRecord
from cognit.agentic.recorder import FlightRecorder, MicroSnapshot
from cognit.agentic.resolver import ConflictResolver
from cognit.agentic.workspace import WorkspaceManager, AgentWorkspace
from cognit.agentic.tournament import SpeculativeTournament, CandidateScorecard

__all__ = [
    "SpeculativeManager",
    "IntentLockManager",
    "ExplainEngine",
    "SymbolLineageRecord",
    "FlightRecorder",
    "MicroSnapshot",
    "ConflictResolver",
    "WorkspaceManager",
    "AgentWorkspace",
    "SpeculativeTournament",
    "CandidateScorecard",
]
