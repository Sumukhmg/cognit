"""AST and structural parser for code symbol extraction across major programming languages."""

from __future__ import annotations

import ast
import hashlib
import re
from typing import List, Optional

from cognit.core.models import Symbol


class ASTParser:
    """Extracts symbols (functions, classes, interfaces, imports) from source code."""

    @classmethod
    def parse_file(cls, file_path: str, content: str) -> List[Symbol]:
        """Parse source content based on file extension."""
        ext = file_path.lower().split(".")[-1] if "." in file_path else ""
        if ext == "py":
            return cls.parse_python(content)
        elif ext in ("js", "jsx", "ts", "tsx", "mjs"):
            return cls.parse_javascript(content)
        elif ext == "go":
            return cls.parse_go(content)
        elif ext == "rs":
            return cls.parse_rust(content)
        elif ext in ("json", "yaml", "yml", "toml"):
            return cls.parse_config(content, ext)
        elif ext in ("md", "markdown"):
            return cls.parse_markdown(content)
        else:
            return cls.parse_generic(content)

    @staticmethod
    def _compute_hash(text: str) -> str:
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _find_matching_brace_end(lines: List[str], start_idx: int) -> int:
        """Find the matching closing brace line (1-indexed) for C-style blocks."""
        open_braces = 0
        found_brace = False
        for i in range(start_idx - 1, len(lines)):
            line = lines[i]
            for ch in line:
                if ch == "{":
                    open_braces += 1
                    found_brace = True
                elif ch == "}":
                    open_braces -= 1
                    if found_brace and open_braces <= 0:
                        return i + 1
        return len(lines) if found_brace else start_idx

    @classmethod
    def parse_python(cls, content: str) -> List[Symbol]:
        """Extract Python functions, classes, methods, and imports via ast."""
        symbols: List[Symbol] = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return cls.parse_generic(content)

        lines = content.splitlines(keepends=True)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = getattr(node, "end_lineno", node.lineno)
                body_text = "".join(lines[node.lineno - 1 : end_line])
                docstring = ast.get_docstring(node)
                args = [arg.arg for arg in node.args.args]
                sig = f"def {node.name}({', '.join(args)})"
                if isinstance(node, ast.AsyncFunctionDef):
                    sig = "async " + sig

                symbols.append(Symbol(
                    name=node.name,
                    kind="function",
                    start_line=node.lineno,
                    end_line=end_line,
                    signature=sig,
                    docstring=docstring,
                    body_hash=cls._compute_hash(body_text),
                ))

            elif isinstance(node, ast.ClassDef):
                end_line = getattr(node, "end_lineno", node.lineno)
                body_text = "".join(lines[node.lineno - 1 : end_line])
                docstring = ast.get_docstring(node)
                bases = [ast.unparse(b) for b in node.bases] if hasattr(ast, "unparse") else []
                sig = f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")

                symbols.append(Symbol(
                    name=node.name,
                    kind="class",
                    start_line=node.lineno,
                    end_line=end_line,
                    signature=sig,
                    docstring=docstring,
                    body_hash=cls._compute_hash(body_text),
                ))

                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_end = getattr(item, "end_lineno", item.lineno)
                        m_text = "".join(lines[item.lineno - 1 : m_end])
                        m_args = [arg.arg for arg in item.args.args]
                        m_sig = f"{node.name}.{item.name}({', '.join(m_args)})"
                        symbols.append(Symbol(
                            name=f"{node.name}.{item.name}",
                            kind="method",
                            start_line=item.lineno,
                            end_line=m_end,
                            signature=m_sig,
                            docstring=ast.get_docstring(item),
                            body_hash=cls._compute_hash(m_text),
                        ))

            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                end_line = getattr(node, "end_lineno", node.lineno)
                imp_text = "".join(lines[node.lineno - 1 : end_line])
                symbols.append(Symbol(
                    name=f"import_{node.lineno}",
                    kind="import",
                    start_line=node.lineno,
                    end_line=end_line,
                    signature=imp_text.strip(),
                    body_hash=cls._compute_hash(imp_text),
                ))

        return symbols

    @classmethod
    def parse_javascript(cls, content: str) -> List[Symbol]:
        """Extract JavaScript/TypeScript functions, classes, interfaces, and imports."""
        symbols: List[Symbol] = []
        lines = content.splitlines()

        func_pattern = re.compile(r'^(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\((.*?)\)')
        arrow_pattern = re.compile(r'^(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\((.*?)\)\s*=>')
        class_pattern = re.compile(r'^(?:export\s+)?class\s+([a-zA-Z0-9_$]+)(?:\s+extends\s+([a-zA-Z0-9_$]+))?')
        interface_pattern = re.compile(r'^(?:export\s+)?interface\s+([a-zA-Z0-9_$]+)')
        type_pattern = re.compile(r'^(?:export\s+)?type\s+([a-zA-Z0-9_$]+)\s*=')
        import_pattern = re.compile(r'^import\s+.*?(?:from\s+[\'"].*?[\'"]|[\'"].*?[\'"])')

        for idx, line in enumerate(lines, start=1):
            sline = line.strip()

            m_func = func_pattern.match(sline)
            if m_func:
                name, args = m_func.groups()
                end_line = cls._find_matching_brace_end(lines, idx)
                body_text = "\n".join(lines[idx - 1 : end_line])
                symbols.append(Symbol(
                    name=name,
                    kind="function",
                    start_line=idx,
                    end_line=end_line,
                    signature=f"function {name}({args})",
                    body_hash=cls._compute_hash(body_text),
                ))
                continue

            m_arrow = arrow_pattern.match(sline)
            if m_arrow:
                name, args = m_arrow.groups()
                end_line = cls._find_matching_brace_end(lines, idx)
                body_text = "\n".join(lines[idx - 1 : end_line])
                symbols.append(Symbol(
                    name=name,
                    kind="function",
                    start_line=idx,
                    end_line=end_line,
                    signature=f"const {name} = ({args}) =>",
                    body_hash=cls._compute_hash(body_text),
                ))
                continue

            m_class = class_pattern.match(sline)
            if m_class:
                name, parent = m_class.groups()
                sig = f"class {name}" + (f" extends {parent}" if parent else "")
                end_line = cls._find_matching_brace_end(lines, idx)
                body_text = "\n".join(lines[idx - 1 : end_line])
                symbols.append(Symbol(
                    name=name,
                    kind="class",
                    start_line=idx,
                    end_line=end_line,
                    signature=sig,
                    body_hash=cls._compute_hash(body_text),
                ))
                continue

            m_iface = interface_pattern.match(sline)
            if m_iface:
                name = m_iface.group(1)
                end_line = cls._find_matching_brace_end(lines, idx)
                body_text = "\n".join(lines[idx - 1 : end_line])
                symbols.append(Symbol(
                    name=name,
                    kind="interface",
                    start_line=idx,
                    end_line=end_line,
                    signature=f"interface {name}",
                    body_hash=cls._compute_hash(body_text),
                ))
                continue

            m_type = type_pattern.match(sline)
            if m_type:
                name = m_type.group(1)
                symbols.append(Symbol(
                    name=name,
                    kind="type",
                    start_line=idx,
                    end_line=idx,
                    signature=f"type {name}",
                    body_hash=cls._compute_hash(sline),
                ))
                continue

            if import_pattern.match(sline):
                symbols.append(Symbol(
                    name=f"import_{idx}",
                    kind="import",
                    start_line=idx,
                    end_line=idx,
                    signature=sline,
                    body_hash=cls._compute_hash(sline),
                ))

        return symbols

    @classmethod
    def parse_go(cls, content: str) -> List[Symbol]:
        """Extract Go functions, methods, structs, and interfaces."""
        symbols: List[Symbol] = []
        lines = content.splitlines()

        func_pattern = re.compile(r'^func\s+(?:\((.*?)\)\s+)?([a-zA-Z0-9_]+)\s*\((.*?)\)')
        type_pattern = re.compile(r'^type\s+([a-zA-Z0-9_]+)\s+(struct|interface)')

        for idx, line in enumerate(lines, start=1):
            sline = line.strip()

            m_func = func_pattern.match(sline)
            if m_func:
                recv, name, args = m_func.groups()
                kind = "method" if recv else "function"
                sig = f"func ({recv}) {name}({args})" if recv else f"func {name}({args})"
                end_line = cls._find_matching_brace_end(lines, idx)
                body_text = "\n".join(lines[idx - 1 : end_line])
                symbols.append(Symbol(
                    name=f"{recv.split()[-1]}.{name}" if recv and len(recv.split()) > 1 else name,
                    kind=kind,
                    start_line=idx,
                    end_line=end_line,
                    signature=sig,
                    body_hash=cls._compute_hash(body_text),
                ))
                continue

            m_type = type_pattern.match(sline)
            if m_type:
                name, kind = m_type.groups()
                end_line = cls._find_matching_brace_end(lines, idx)
                body_text = "\n".join(lines[idx - 1 : end_line])
                symbols.append(Symbol(
                    name=name,
                    kind=kind,
                    start_line=idx,
                    end_line=end_line,
                    signature=f"type {name} {kind}",
                    body_hash=cls._compute_hash(body_text),
                ))

        return symbols

    @classmethod
    def parse_rust(cls, content: str) -> List[Symbol]:
        """Extract Rust functions, structs, enums, traits, and impl blocks."""
        symbols: List[Symbol] = []
        lines = content.splitlines()

        fn_pattern = re.compile(r'^(?:pub(?:\(.*?\))?\s+)?(?:async\s+)?fn\s+([a-zA-Z0-9_]+)\s*(?:<.*?>)?\s*\((.*?)\)')
        type_pattern = re.compile(r'^(?:pub(?:\(.*?\))?\s+)?(struct|enum|trait)\s+([a-zA-Z0-9_]+)')
        impl_pattern = re.compile(r'^impl(?:<.*?>)?\s+(?:([a-zA-Z0-9_]+)\s+for\s+)?([a-zA-Z0-9_]+)')

        for idx, line in enumerate(lines, start=1):
            sline = line.strip()

            m_fn = fn_pattern.match(sline)
            if m_fn:
                name, args = m_fn.groups()
                end_line = cls._find_matching_brace_end(lines, idx)
                body_text = "\n".join(lines[idx - 1 : end_line])
                symbols.append(Symbol(
                    name=name,
                    kind="function",
                    start_line=idx,
                    end_line=end_line,
                    signature=f"fn {name}({args})",
                    body_hash=cls._compute_hash(body_text),
                ))
                continue

            m_type = type_pattern.match(sline)
            if m_type:
                kind, name = m_type.groups()
                end_line = cls._find_matching_brace_end(lines, idx)
                body_text = "\n".join(lines[idx - 1 : end_line])
                symbols.append(Symbol(
                    name=name,
                    kind=kind,
                    start_line=idx,
                    end_line=end_line,
                    signature=f"{kind} {name}",
                    body_hash=cls._compute_hash(body_text),
                ))
                continue

            m_impl = impl_pattern.match(sline)
            if m_impl:
                trait, target = m_impl.groups()
                sig = f"impl {trait} for {target}" if trait else f"impl {target}"
                end_line = cls._find_matching_brace_end(lines, idx)
                body_text = "\n".join(lines[idx - 1 : end_line])
                symbols.append(Symbol(
                    name=sig,
                    kind="impl",
                    start_line=idx,
                    end_line=end_line,
                    signature=sig,
                    body_hash=cls._compute_hash(body_text),
                ))

        return symbols

    @classmethod
    def parse_markdown(cls, content: str) -> List[Symbol]:
        """Extract top-level headings as symbols in markdown."""
        symbols: List[Symbol] = []
        lines = content.splitlines()
        for idx, line in enumerate(lines, start=1):
            if line.startswith("#"):
                header_text = line.lstrip("#").strip()
                level = len(line) - len(line.lstrip("#"))
                symbols.append(Symbol(
                    name=header_text,
                    kind=f"h{level}",
                    start_line=idx,
                    end_line=idx,
                    signature=line.strip(),
                    body_hash=cls._compute_hash(line),
                ))
        return symbols

    @classmethod
    def parse_config(cls, content: str, ext: str) -> List[Symbol]:
        """Extract top-level keys as symbols for configs."""
        symbols: List[Symbol] = []
        lines = content.splitlines()
        key_pattern = re.compile(r'^["\']?([a-zA-Z0-9_\-\.]+)["\']?\s*[:=]')
        for idx, line in enumerate(lines, start=1):
            m = key_pattern.match(line.strip())
            if m:
                key = m.group(1)
                symbols.append(Symbol(
                    name=key,
                    kind="config_key",
                    start_line=idx,
                    end_line=idx,
                    signature=line.strip(),
                    body_hash=cls._compute_hash(line),
                ))
        return symbols

    @classmethod
    def parse_generic(cls, content: str) -> List[Symbol]:
        """Fallback chunker for unknown file types."""
        symbols: List[Symbol] = []
        lines = content.splitlines()
        chunk_size = 50
        for i in range(0, len(lines), chunk_size):
            chunk_lines = lines[i : i + chunk_size]
            start = i + 1
            end = i + len(chunk_lines)
            chunk_text = "\n".join(chunk_lines)
            symbols.append(Symbol(
                name=f"block_{start}_{end}",
                kind="block",
                start_line=start,
                end_line=end,
                signature=f"lines {start}-{end}",
                body_hash=cls._compute_hash(chunk_text),
            ))
        return symbols
