"""Cognit: The Intelligent, Agent-Native Version Control System.

Built from the ground up for autonomous AI agents, multi-agent swarms,
and modern developers.
"""

__version__ = "0.1.0"

from cognit.core.models import (
    AgentMetadata,
    Checkpoint,
    TreeEntry,
    FileStatus,
    Symbol,
    SpeculativeTrial,
)
from cognit.core.repo import CognitRepo

__all__ = [
    "CognitRepo",
    "AgentMetadata",
    "Checkpoint",
    "TreeEntry",
    "FileStatus",
    "Symbol",
    "SpeculativeTrial",
    "__version__",
]
