"""Symbol-level semantic differential analysis between code versions."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from cognit.core.models import Symbol
from cognit.semantic.parser import ASTParser


@dataclass
class SymbolDiff:
    """Represents a change to an individual AST symbol."""

    name: str
    kind: str
    change_type: str  # "added", "deleted", "modified", "renamed"
    old_symbol: Optional[Symbol] = None
    new_symbol: Optional[Symbol] = None
    lines_added: int = 0
    lines_deleted: int = 0
    summary: str = ""

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "change_type": self.change_type,
            "lines_added": self.lines_added,
            "lines_deleted": self.lines_deleted,
            "summary": self.summary,
            "old_signature": self.old_symbol.signature if self.old_symbol else None,
            "new_signature": self.new_symbol.signature if self.new_symbol else None,
        }


@dataclass
class FileDiffResult:
    """Diff results for a single file."""

    file_path: str
    is_binary: bool = False
    is_new: bool = False
    is_deleted: bool = False
    symbol_diffs: List[SymbolDiff] = field(default_factory=list)
    raw_unified_diff: str = ""
    total_added: int = 0
    total_deleted: int = 0

    def to_dict(self) -> Dict:
        return {
            "file_path": self.file_path,
            "is_binary": self.is_binary,
            "is_new": self.is_new,
            "is_deleted": self.is_deleted,
            "total_added": self.total_added,
            "total_deleted": self.total_deleted,
            "symbol_diffs": [s.to_dict() for s in self.symbol_diffs],
            "raw_unified_diff": self.raw_unified_diff,
        }

    def format_summary(self) -> str:
        """Token-efficient one-line summary for agents."""
        if self.is_new:
            return f"{self.file_path}: [NEW FILE] (+{self.total_added} lines)"
        if self.is_deleted:
            return f"{self.file_path}: [DELETED] (-{self.total_deleted} lines)"

        parts = []
        for s in self.symbol_diffs:
            if s.change_type == "modified":
                parts.append(f"~{s.name}(+{s.lines_added}/-{s.lines_deleted})")
            elif s.change_type == "added":
                parts.append(f"+{s.name}(+{s.lines_added})")
            elif s.change_type == "deleted":
                parts.append(f"-{s.name}(-{s.lines_deleted})")

        sym_str = ", ".join(parts) if parts else f"+{self.total_added}/-{self.total_deleted} lines"
        return f"{self.file_path}: {sym_str}"


class SemanticDiffer:
    """Computes semantic symbol-aware diffs between file contents."""

    @classmethod
    def diff_content(cls, file_path: str, old_content: str, new_content: str) -> FileDiffResult:
        if old_content == new_content:
            return FileDiffResult(file_path=file_path)

        old_symbols = {s.name: s for s in ASTParser.parse_file(file_path, old_content)}
        new_symbols = {s.name: s for s in ASTParser.parse_file(file_path, new_content)}

        symbol_diffs: List[SymbolDiff] = []
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        unified = "".join(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}"
        ))

        total_added = sum(1 for line in unified.splitlines() if line.startswith("+") and not line.startswith("+++"))
        total_deleted = sum(1 for line in unified.splitlines() if line.startswith("-") and not line.startswith("---"))

        # Find added symbols
        for name, sym in new_symbols.items():
            if name not in old_symbols:
                lines_cnt = sym.end_line - sym.start_line + 1
                symbol_diffs.append(SymbolDiff(
                    name=name,
                    kind=sym.kind,
                    change_type="added",
                    new_symbol=sym,
                    lines_added=lines_cnt,
                    summary=f"Added {sym.kind} '{name}'",
                ))

        # Find deleted symbols
        for name, sym in old_symbols.items():
            if name not in new_symbols:
                lines_cnt = sym.end_line - sym.start_line + 1
                symbol_diffs.append(SymbolDiff(
                    name=name,
                    kind=sym.kind,
                    change_type="deleted",
                    old_symbol=sym,
                    lines_deleted=lines_cnt,
                    summary=f"Removed {sym.kind} '{name}'",
                ))

        # Find modified symbols
        for name, old_sym in old_symbols.items():
            if name in new_symbols:
                new_sym = new_symbols[name]
                if old_sym.body_hash != new_sym.body_hash:
                    # Extract symbol lines
                    s_old = "".join(old_lines[old_sym.start_line - 1 : old_sym.end_line])
                    s_new = "".join(new_lines[new_sym.start_line - 1 : new_sym.end_line])
                    s_diff = list(difflib.unified_diff(s_old.splitlines(), s_new.splitlines()))
                    s_add = sum(1 for l in s_diff if l.startswith("+") and not l.startswith("+++"))
                    s_del = sum(1 for l in s_diff if l.startswith("-") and not l.startswith("---"))

                    symbol_diffs.append(SymbolDiff(
                        name=name,
                        kind=new_sym.kind,
                        change_type="modified",
                        old_symbol=old_sym,
                        new_symbol=new_sym,
                        lines_added=s_add,
                        lines_deleted=s_del,
                        summary=f"Modified {new_sym.kind} '{name}' (+{s_add}/-{s_del})",
                    ))

        return FileDiffResult(
            file_path=file_path,
            symbol_diffs=symbol_diffs,
            raw_unified_diff=unified,
            total_added=total_added,
            total_deleted=total_deleted,
        )
