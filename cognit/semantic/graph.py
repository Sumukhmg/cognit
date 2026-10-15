"""Code dependency graph, call hierarchy, and change impact analysis for AI agents."""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from cognit.core.models import Symbol
from cognit.semantic.parser import ASTParser


@dataclass
class ImpactReport:
    """Comprehensive change impact analysis for a file or code symbol."""

    target: str
    target_type: str  # "file" or "symbol"
    direct_dependents: List[str] = field(default_factory=list)
    transitive_dependents: List[str] = field(default_factory=list)
    affected_tests: List[str] = field(default_factory=list)
    affected_symbols: List[str] = field(default_factory=list)
    risk_level: str = "low"  # "low", "medium", "high", "critical"

    def to_dict(self) -> Dict:
        return asdict(self)

    def summary(self) -> str:
        return (
            f"Impact on '{self.target}' ({self.risk_level.upper()} RISK):\n"
            f"  - Direct Dependents ({len(self.direct_dependents)}): {', '.join(self.direct_dependents) or 'none'}\n"
            f"  - Transitive Dependents ({len(self.transitive_dependents)}): {', '.join(self.transitive_dependents) or 'none'}\n"
            f"  - Tests to Re-run ({len(self.affected_tests)}): {', '.join(self.affected_tests) or 'none'}\n"
            f"  - Affected Symbols ({len(self.affected_symbols)}): {', '.join(self.affected_symbols) or 'none'}"
        )


class DependencyGraph:
    """Builds and queries cross-file import dependencies and symbol call graphs."""

    def __init__(self, root_dir: Path | str, repo: Optional[Any] = None) -> None:
        self.root_dir = Path(root_dir)
        self.repo = repo
        # Adjacency maps:
        # file -> set of files it imports
        self.file_imports: Dict[str, Set[str]] = {}
        # file -> set of files that import it (reverse dependencies)
        self.file_imported_by: Dict[str, Set[str]] = {}
        # file -> list of parsed symbols
        self.file_symbols: Dict[str, List[Symbol]] = {}

    def build_graph(self) -> None:
        """Scan working files in repo and extract cross-file imports and symbols."""
        if self.repo:
            files = self.repo.list_working_files()
        else:
            files = []
            for root, _, fs in os.walk(self.root_dir):
                for f in fs:
                    rel = os.path.relpath(os.path.join(root, f), self.root_dir).replace("\\", "/")
                    if not any(ign in rel for ign in [".cognit", ".git", "node_modules", "__pycache__"]):
                        files.append(rel)

        # Initialize structures
        for f in files:
            self.file_imports[f] = set()
            self.file_imported_by[f] = set()
            self.file_symbols[f] = []

        # Parse each file
        for rel_path in files:
            full_path = self.root_dir / rel_path
            if not full_path.is_file():
                continue

            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # Extract symbols
            symbols = ASTParser.parse_file(rel_path, content)
            self.file_symbols[rel_path] = symbols

            # Extract imports based on file type
            ext = rel_path.lower().split(".")[-1] if "." in rel_path else ""
            imported_files = set()

            if ext == "py":
                imported_files = self._extract_python_imports(rel_path, content, files)
            elif ext in ("js", "jsx", "ts", "tsx"):
                imported_files = self._extract_js_imports(rel_path, content, files)

            self.file_imports[rel_path] = imported_files
            for target in imported_files:
                if target in self.file_imported_by:
                    self.file_imported_by[target].add(rel_path)

    def _extract_python_imports(self, rel_path: str, content: str, all_files: List[str]) -> Set[str]:
        imported: Set[str] = set()
        try:
            tree = ast.parse(content)
        except Exception:
            return imported

        # Map module paths to repo files
        # e.g. "cognit.core.models" -> "cognit/core/models.py"
        module_file_map = {}
        for f in all_files:
            if f.endswith(".py"):
                mod_name = f[:-3].replace("/", ".").replace("\\", ".")
                module_file_map[mod_name] = f
                # Also handle __init__.py package name
                if mod_name.endswith(".__init__"):
                    module_file_map[mod_name[:-9]] = f

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in module_file_map:
                        imported.add(module_file_map[alias.name])
            elif isinstance(node, ast.ImportFrom):
                mod = node.module
                if mod:
                    # Direct module match
                    if mod in module_file_map:
                        imported.add(module_file_map[mod])
                    else:
                        # Check prefix matches
                        parts = mod.split(".")
                        for i in range(len(parts), 0, -1):
                            sub = ".".join(parts[:i])
                            if sub in module_file_map:
                                imported.add(module_file_map[sub])

        return imported

    def _extract_js_imports(self, rel_path: str, content: str, all_files: List[str]) -> Set[str]:
        imported: Set[str] = set()
        # Regex for ES imports and CommonJS requires
        import_regex = re.compile(r'(?:import\s+.*?from\s+[\'"](.*?)[\'"]|require\([\'"](.*?)[\'"]\))')
        curr_dir = os.path.dirname(rel_path)

        for match in import_regex.finditer(content):
            path_str = match.group(1) or match.group(2)
            if not path_str or not path_str.startswith("."):
                continue  # External package

            # Resolve relative path
            resolved = os.path.normpath(os.path.join(curr_dir, path_str)).replace("\\", "/")
            # Try extensions
            for candidate in [resolved, f"{resolved}.ts", f"{resolved}.js", f"{resolved}.tsx", f"{resolved}.jsx", f"{resolved}/index.ts", f"{resolved}/index.js"]:
                if candidate in all_files:
                    imported.add(candidate)
                    break

        return imported

    def analyze_impact(self, target: str) -> ImpactReport:
        """Analyze the blast radius and downstream dependents of changing target."""
        # Check if target is a file or a symbol "file.py:symbol_name"
        if ":" in target:
            file_part, sym_part = target.split(":", 1)
            target_type = "symbol"
        else:
            file_part = target
            sym_part = ""
            target_type = "file"

        direct = sorted(list(self.file_imported_by.get(file_part, set())))

        # Transitive dependents BFS
        transitive = set()
        queue = list(direct)
        visited = set(queue) | {file_part}

        while queue:
            curr = queue.pop(0)
            for dep in self.file_imported_by.get(curr, set()):
                if dep not in visited:
                    visited.add(dep)
                    transitive.add(dep)
                    queue.append(dep)

        transitive_list = sorted(list(transitive))

        # Detect affected tests
        all_dependents = set(direct) | set(transitive_list) | {file_part}
        affected_tests = []
        for dep in all_dependents:
            fname = os.path.basename(dep).lower()
            if fname.startswith("test_") or fname.endswith("_test.py") or ".test." in fname or ".spec." in fname or dep.startswith("tests/"):
                affected_tests.append(dep)

        # Detect affected symbols if symbol target
        affected_symbols = []
        if sym_part:
            # Search which files contain references to sym_part
            for dep in direct:
                dep_path = self.root_dir / dep
                if dep_path.is_file():
                    content = dep_path.read_text(encoding="utf-8", errors="replace")
                    if sym_part in content:
                        affected_symbols.append(f"{dep} calls {sym_part}")

        # Compute risk level
        total_impact = len(direct) + len(transitive_list)
        if total_impact == 0:
            risk = "low"
        elif total_impact <= 3:
            risk = "medium"
        elif total_impact <= 8:
            risk = "high"
        else:
            risk = "critical"

        return ImpactReport(
            target=target,
            target_type=target_type,
            direct_dependents=direct,
            transitive_dependents=transitive_list,
            affected_tests=sorted(affected_tests),
            affected_symbols=affected_symbols,
            risk_level=risk,
        )

    def build_compact_context(self, goal: str, max_tokens: int = 1500) -> str:
        """Extract a token-optimized symbol context block for an agent prompt."""
        # Find matching symbols by keyword relevance
        keywords = set(re.findall(r'[a-zA-Z0-9_]{3,}', goal.lower()))
        matched_symbols: List[Tuple[int, str, Symbol]] = []

        for fpath, syms in self.file_symbols.items():
            for s in syms:
                score = 0
                sname_lower = s.name.lower()
                for kw in keywords:
                    if kw in sname_lower:
                        score += 3
                    if s.docstring and kw in s.docstring.lower():
                        score += 1
                if score > 0:
                    matched_symbols.append((score, fpath, s))

        # Sort by relevance score
        matched_symbols.sort(key=lambda x: x[0], reverse=True)

        # Assemble compact context within token budget (~4 chars per token)
        char_budget = max_tokens * 4
        lines = [
            "### COGNIT COMPACT REPOSITORY CONTEXT ###",
            f"Task Goal: {goal}",
            "Relevant Code Symbols & Signatures:",
        ]

        chars_used = sum(len(l) for l in lines)

        for score, fpath, s in matched_symbols[:15]:
            entry = f"\n[{fpath}] {s.signature}"
            if s.docstring:
                first_doc = s.docstring.strip().splitlines()[0]
                entry += f"  # {first_doc}"

            if chars_used + len(entry) < char_budget:
                lines.append(entry)
                chars_used += len(entry)
            else:
                break

        lines.append("\n### END CONTEXT ###")
        return "\n".join(lines)
