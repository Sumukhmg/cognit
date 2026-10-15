"""Semantic code understanding, diffing, and merging modules."""

from cognit.semantic.parser import ASTParser
from cognit.semantic.semantic_diff import SemanticDiffer, FileDiffResult, SymbolDiff
from cognit.semantic.semantic_merge import SemanticMerger, MergeResult, ConflictDetail
from cognit.semantic.graph import DependencyGraph, ImpactReport

__all__ = [
    "ASTParser",
    "SemanticDiffer",
    "FileDiffResult",
    "SymbolDiff",
    "SemanticMerger",
    "MergeResult",
    "ConflictDetail",
    "DependencyGraph",
    "ImpactReport",
]
