"""Autonomous Conflict Resolver and LLM Synthesis Assistant."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from cognit.semantic.semantic_merge import ConflictDetail, MergeResult


class ConflictResolver:
    """Automates and guides the resolution of structural merge conflicts."""

    def __init__(self, repo: Any) -> None:
        self.repo = repo

    @staticmethod
    def generate_synthesis_prompt(conflict: ConflictDetail, goal_a: str = "", goal_b: str = "") -> str:
        """Generate a structured synthesis prompt for an LLM to resolve a symbol conflict."""
        prompt = [
            "### COGNIT AUTONOMOUS CONFLICT RESOLUTION REQUEST ###",
            f"File: {conflict.file_path}",
            f"Symbol: {conflict.symbol_name} ({conflict.kind})",
            f"Reason: {conflict.reason}",
            "",
            "--- BASE IMPLEMENTATION ---",
            conflict.base_snippet.strip() or "(None / Newly introduced)",
            "",
            f"--- BRANCH A (OURS) --- [Goal: {goal_a or 'Branch A enhancement'}]",
            conflict.ours_snippet.strip(),
            "",
            f"--- BRANCH B (THEIRS) --- [Goal: {goal_b or 'Branch B enhancement'}]",
            conflict.theirs_snippet.strip(),
            "",
            "--- INSTRUCTIONS FOR AI SYNTHESIS ---",
            "1. Combine the functionality of both Branch A and Branch B into a single, cohesive implementation.",
            "2. Preserve parameter signatures, error handling, and performance improvements from both sides.",
            "3. Output ONLY the resolved code block with no markdown formatting or commentary.",
            "### END PROMPT ###"
        ]
        return "\n".join(prompt)

    @classmethod
    def try_auto_resolve(cls, conflict: ConflictDetail) -> Optional[str]:
        """Attempt heuristic auto-resolution for common non-colliding patterns (e.g. imports, docstrings)."""
        # Case 1: Import lists (union them)
        if conflict.kind == "import":
            lines_a = [l.strip() for l in conflict.ours_snippet.splitlines() if l.strip()]
            lines_b = [l.strip() for l in conflict.theirs_snippet.splitlines() if l.strip()]
            union_imports = sorted(list(set(lines_a) | set(lines_b)))
            return "\n".join(union_imports) + "\n"

        # Case 2: One side only touched docstring/comments and other modified logic
        lines_base = [l.strip() for l in conflict.base_snippet.splitlines() if l.strip() and not l.strip().startswith("#")]
        lines_a = [l.strip() for l in conflict.ours_snippet.splitlines() if l.strip() and not l.strip().startswith("#")]
        lines_b = [l.strip() for l in conflict.theirs_snippet.splitlines() if l.strip() and not l.strip().startswith("#")]

        if lines_a == lines_base and lines_b != lines_base:
            # Branch A only changed comments/docstrings, Branch B changed logic
            return conflict.theirs_snippet
        elif lines_b == lines_base and lines_a != lines_base:
            # Branch B only changed comments/docstrings, Branch A changed logic
            return conflict.ours_snippet

        return None

    def apply_symbol_resolution(
        self,
        file_path: str,
        symbol_name: str,
        resolved_code: str,
    ) -> bool:
        """Replace a conflicting symbol in the file with the resolved implementation."""
        full_path = (self.repo.root_dir / file_path).resolve()
        if not full_path.is_relative_to(self.repo.root_dir.resolve()) or not full_path.is_file():
            return False

        content = full_path.read_text(encoding="utf-8", errors="replace")

        # Pattern to find structured conflict marker for this symbol
        marker_pattern = re.compile(
            rf"// =================== CONFLICT: {re.escape(symbol_name)}.*?// =================== END CONFLICT: {re.escape(symbol_name)} ===================\n?",
            re.DOTALL
        )

        if marker_pattern.search(content):
            new_content = marker_pattern.sub(resolved_code.strip() + "\n", content)
            # Remove header if no more conflicts remain
            if "// =================== CONFLICT:" not in new_content:
                new_content = re.sub(r"/\* <<< COGNIT SEMANTIC CONFLICT MARKER >>>.*?\*/\n*", "", new_content, flags=re.DOTALL)
                new_content = re.sub(r"/\* --- ORIGINAL OURS FILE CONTENT --- \*/\n*", "", new_content)

            full_path.write_text(new_content, encoding="utf-8")
            return True

        # Fallback: if conflict marker not found, append or update
        return False
