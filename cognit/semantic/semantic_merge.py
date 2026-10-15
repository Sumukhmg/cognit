"""AST-aware 3-way semantic merge resolver."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from cognit.core.models import Symbol
from cognit.semantic.parser import ASTParser


@dataclass
class ConflictDetail:
    """Detailed structural conflict information for an agent to resolve."""

    file_path: str
    symbol_name: str
    kind: str
    base_snippet: str
    ours_snippet: str
    theirs_snippet: str
    reason: str

    def to_dict(self) -> Dict:
        return {
            "file_path": self.file_path,
            "symbol_name": self.symbol_name,
            "kind": self.kind,
            "reason": self.reason,
            "base_snippet": self.base_snippet,
            "ours_snippet": self.ours_snippet,
            "theirs_snippet": self.theirs_snippet,
        }


@dataclass
class MergeResult:
    """Result of merging two versions against a common base."""

    file_path: str
    merged_content: str
    clean: bool
    conflicts: List[ConflictDetail] = field(default_factory=list)
    auto_resolved_symbols: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "file_path": self.file_path,
            "clean": self.clean,
            "auto_resolved_symbols": self.auto_resolved_symbols,
            "conflicts": [c.to_dict() for c in self.conflicts],
        }


class SemanticMerger:
    """Performs AST-aware 3-way merges between Base, Ours, and Theirs."""

    @classmethod
    def merge_files(
        cls,
        file_path: str,
        base_content: str,
        ours_content: str,
        theirs_content: str,
    ) -> MergeResult:
        """Merge ours and theirs against base using AST symbol analysis."""
        # Trivial cases:
        if ours_content == theirs_content:
            return MergeResult(file_path=file_path, merged_content=ours_content, clean=True)
        if ours_content == base_content:
            return MergeResult(file_path=file_path, merged_content=theirs_content, clean=True)
        if theirs_content == base_content:
            return MergeResult(file_path=file_path, merged_content=ours_content, clean=True)

        base_symbols = {s.name: s for s in ASTParser.parse_file(file_path, base_content)}
        ours_symbols = {s.name: s for s in ASTParser.parse_file(file_path, ours_content)}
        theirs_symbols = {s.name: s for s in ASTParser.parse_file(file_path, theirs_content)}

        conflicts: List[ConflictDetail] = []
        auto_resolved: List[str] = []

        # Find changes in Ours vs Base
        ours_modified = {
            name: s for name, s in ours_symbols.items()
            if name not in base_symbols or s.body_hash != base_symbols[name].body_hash
        }
        ours_deleted = {name for name in base_symbols if name not in ours_symbols}

        # Find changes in Theirs vs Base
        theirs_modified = {
            name: s for name, s in theirs_symbols.items()
            if name not in base_symbols or s.body_hash != base_symbols[name].body_hash
        }
        theirs_deleted = {name for name in base_symbols if name not in theirs_symbols}

        # Identify symbol collisions:
        colliding_names = set(ours_modified.keys()).intersection(set(theirs_modified.keys()))
        for name in colliding_names:
            s_ours = ours_modified[name]
            s_theirs = theirs_modified[name]
            if s_ours.body_hash == s_theirs.body_hash:
                # Both made the identical change! Clean merge
                auto_resolved.append(f"{name} (identical change on both branches)")
                continue

            # If this is a container (e.g. class), check if changes are solely within disjoint child methods
            if s_ours.kind == "class":
                our_child_mods = {k for k in ours_modified if k.startswith(f"{name}.")}
                their_child_mods = {k for k in theirs_modified if k.startswith(f"{name}.")}
                if (our_child_mods or their_child_mods) and not (our_child_mods & their_child_mods):
                    # Disjoint method edits within this class: let child method splicing handle it!
                    auto_resolved.append(f"{name} (disjoint method modifications within class)")
                    continue

            # Real conflict on this symbol!
            base_snip = cls._extract_snippet(base_content, base_symbols.get(name))
            ours_snip = cls._extract_snippet(ours_content, s_ours)
            theirs_snip = cls._extract_snippet(theirs_content, s_theirs)
            conflicts.append(ConflictDetail(
                file_path=file_path,
                symbol_name=name,
                kind=s_ours.kind,
                base_snippet=base_snip,
                ours_snippet=ours_snip,
                theirs_snippet=theirs_snip,
                reason=f"Both branches modified symbol '{name}' with different implementations.",
            ))

        # Check deletion collisions
        del_coll = (set(ours_modified.keys()) & theirs_deleted) | (set(theirs_modified.keys()) & ours_deleted)
        for name in del_coll:
            conflicts.append(ConflictDetail(
                file_path=file_path,
                symbol_name=name,
                kind="symbol",
                base_snippet="",
                ours_snippet="[MODIFIED]" if name in ours_modified else "[DELETED]",
                theirs_snippet="[MODIFIED]" if name in theirs_modified else "[DELETED]",
                reason=f"Symbol '{name}' modified on one branch and deleted on the other.",
            ))

        # If there are NO symbol collisions, we can synthesize the merged content cleanly!
        if not conflicts:
            merged = cls._splice_non_colliding(
                file_path, base_content, ours_content, theirs_content,
                base_symbols, ours_symbols, theirs_symbols,
                ours_modified, theirs_modified, ours_deleted, theirs_deleted
            )
            return MergeResult(
                file_path=file_path,
                merged_content=merged,
                clean=True,
                auto_resolved_symbols=list(ours_modified.keys()) + list(theirs_modified.keys()),
            )

        # If there are conflicts, build a clear merged representation with structured conflict annotations
        conflict_rendered = cls._render_conflicts(ours_content, theirs_content, conflicts)
        return MergeResult(
            file_path=file_path,
            merged_content=conflict_rendered,
            clean=False,
            conflicts=conflicts,
            auto_resolved_symbols=auto_resolved,
        )

    @staticmethod
    def _extract_snippet(content: str, symbol: Optional[Symbol]) -> str:
        if not symbol:
            return ""
        lines = content.splitlines(keepends=True)
        return "".join(lines[symbol.start_line - 1 : symbol.end_line])

    @classmethod
    def _splice_non_colliding(
        cls,
        file_path: str,
        base_content: str,
        ours_content: str,
        theirs_content: str,
        base_symbols: Dict[str, Symbol],
        ours_symbols: Dict[str, Symbol],
        theirs_symbols: Dict[str, Symbol],
        ours_modified: Dict[str, Symbol],
        theirs_modified: Dict[str, Symbol],
        ours_deleted: set,
        theirs_deleted: set,
    ) -> str:
        """Splice modifications from both sides cleanly when symbols are disjoint."""
        # If theirs modified nothing, take ours
        if not theirs_modified and not theirs_deleted:
            return ours_content
        # If ours modified nothing, take theirs
        if not ours_modified and not ours_deleted:
            return theirs_content

        # For Python/code files:
        # Start with ours_content. Apply Theirs' changes (added symbols, modified symbols, deleted symbols)
        result_lines = ours_content.splitlines(keepends=True)

        # Collect replacements and deletions on existing symbols
        # Sorting in reverse order (bottom-to-top) prevents line offset drift!
        edits: List[Tuple[int, int, List[str]]] = []

        # 1. Any symbol modified in Theirs (and untouched in Ours) gets substituted
        for name, their_sym in theirs_modified.items():
            if name in base_symbols and name in ours_symbols and name not in ours_modified:
                # If this is a class, but Ours modified a method inside it, do NOT substitute the entire class
                if their_sym.kind == "class" and any(k.startswith(f"{name}.") for k in ours_modified):
                    continue
                our_sym = ours_symbols[name]
                their_code = cls._extract_snippet(theirs_content, their_sym)
                edits.append((our_sym.start_line, our_sym.end_line, [their_code]))

        # 2. Any symbol deleted in Theirs (and untouched in Ours) gets removed
        for name in theirs_deleted:
            if name in base_symbols and name in ours_symbols and name not in ours_modified:
                if any(k.startswith(f"{name}.") for k in ours_modified):
                    continue
                our_sym = ours_symbols[name]
                edits.append((our_sym.start_line, our_sym.end_line, []))

        # Filter out overlapping edits to prevent range corruption
        non_overlapping_edits: List[Tuple[int, int, List[str]]] = []
        # Sort by smaller range first so specific method edits take precedence over enclosing blocks
        edits.sort(key=lambda x: (x[1] - x[0]))
        for s_line, e_line, rep in edits:
            overlaps = False
            for os_line, oe_line, _ in non_overlapping_edits:
                if not (e_line < os_line or s_line > oe_line):
                    overlaps = True
                    break
            if not overlaps:
                non_overlapping_edits.append((s_line, e_line, rep))

        # Sort descending by start_line so earlier line offsets are unaffected
        non_overlapping_edits.sort(key=lambda x: x[0], reverse=True)
        for s_line, e_line, replacement in non_overlapping_edits:
            s_idx = max(0, s_line - 1)
            e_idx = min(len(result_lines), e_line)
            result_lines[s_idx:e_idx] = replacement

        # 3. Any symbol newly added in Theirs (not in Base and not in Ours)
        added_in_theirs = [
            their_sym for name, their_sym in theirs_modified.items()
            if name not in base_symbols and name not in ours_symbols
        ]
        # Sort additions by their original line order in their file
        added_in_theirs.sort(key=lambda s: s.start_line)
        for their_sym in added_in_theirs:
            their_code = cls._extract_snippet(theirs_content, their_sym)
            if not their_code.endswith("\n"):
                their_code += "\n"
            # If it's an import, put at top, otherwise append cleanly
            if their_sym.kind == "import":
                result_lines.insert(0, their_code)
            else:
                result_lines.append("\n" + their_code)

        return "".join(result_lines)

    @classmethod
    def _render_conflicts(cls, ours_content: str, theirs_content: str, conflicts: List[ConflictDetail]) -> str:
        """Generate a structured conflict file designed for AI agents to easily inspect and resolve."""
        header = "/* <<< COGNIT SEMANTIC CONFLICT MARKER >>>\n"
        header += "AI Agent Instructions: The following symbols have conflicting changes.\n"
        header += "Review the structured blocks below and choose the optimal implementation.\n*/\n\n"

        body = []
        for c in conflicts:
            body.append(f"// =================== CONFLICT: {c.symbol_name} ({c.kind}) ===================")
            body.append(f"// Reason: {c.reason}\n")
            body.append("/* <<< OURS >>> */")
            body.append(c.ours_snippet.strip())
            body.append("\n/* <<< THEIRS >>> */")
            body.append(c.theirs_snippet.strip())
            body.append(f"// =================== END CONFLICT: {c.symbol_name} ===================\n")

        return header + "\n".join(body) + "\n\n/* --- ORIGINAL OURS FILE CONTENT --- */\n" + ours_content
