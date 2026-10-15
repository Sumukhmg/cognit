"""Core repository operations for Cognit version control system."""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from cognit.core.database import Database
from cognit.core.models import (
    AgentMetadata,
    Checkpoint,
    FileStatus,
    TreeEntry,
    current_iso_timestamp,
)
from cognit.core.storage import ObjectStorage
from cognit.semantic.parser import ASTParser
from cognit.semantic.semantic_diff import FileDiffResult, SemanticDiffer
from cognit.semantic.semantic_merge import MergeResult, SemanticMerger

DEFAULT_IGNORES = [
    ".cognit",
    ".cognit/*",
    ".git",
    ".git/*",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "node_modules",
    "node_modules/*",
    ".venv",
    ".venv/*",
    "venv",
    "venv/*",
    ".DS_Store",
    "Thumbs.db",
    "*.egg-info",
    "build",
    "dist",
]


class CognitRepo:
    """High-level repository manager for Cognit version control."""

    def __init__(self, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.cognit_dir = self.root_dir / ".cognit"
        self.storage = ObjectStorage(self.root_dir)
        self.db = Database(self.cognit_dir / "index.db")

    @classmethod
    def find_repo(cls, start_dir: Path | str = ".") -> CognitRepo:
        """Find the nearest parent directory containing a .cognit repository."""
        curr = Path(start_dir).resolve()
        while True:
            if (curr / ".cognit").is_dir():
                return cls(curr)
            parent = curr.parent
            if parent == curr:
                raise FileNotFoundError(f"No Cognit repository found at or above {start_dir}")
            curr = parent

    @classmethod
    def init(cls, root_dir: Path | str = ".", default_branch: str = "main") -> CognitRepo:
        """Initialize a new Cognit repository."""
        rdir = Path(root_dir).resolve()
        cdir = rdir / ".cognit"

        if cdir.exists():
            return cls(rdir)

        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "objects").mkdir(parents=True, exist_ok=True)
        (cdir / "refs" / "heads").mkdir(parents=True, exist_ok=True)
        (cdir / "refs" / "tags").mkdir(parents=True, exist_ok=True)
        (cdir / "tmp").mkdir(parents=True, exist_ok=True)

        # Config
        config = {
            "version": "1.0",
            "default_branch": default_branch,
            "created_at": current_iso_timestamp(),
        }
        (cdir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

        # HEAD ref points to refs/heads/<default_branch>
        (cdir / "HEAD").write_text(f"ref: refs/heads/{default_branch}\n", encoding="utf-8")

        # Default ignore file
        ignore_file = rdir / ".cognitignore"
        if not ignore_file.exists():
            ignore_file.write_text("\n".join(DEFAULT_IGNORES) + "\n", encoding="utf-8")

        repo = cls(rdir)
        return repo

    # Ref & Branch Management

    def get_head_ref(self) -> str:
        """Read .cognit/HEAD and return ref path (e.g. 'refs/heads/main') or raw commit hash."""
        head_path = self.cognit_dir / "HEAD"
        if not head_path.exists():
            return "refs/heads/main"
        content = head_path.read_text(encoding="utf-8").strip()
        if content.startswith("ref:"):
            return content[4:].strip()
        return content

    def get_active_branch(self) -> str:
        """Return the name of the active branch, or 'DETACHED'."""
        head_ref = self.get_head_ref()
        if head_ref.startswith("refs/heads/"):
            return head_ref[len("refs/heads/"):]
        return "DETACHED"

    def _validate_ref_name(self, name: str, ref_type: str = "branch") -> None:
        """Validate branch or tag name against path traversal and invalid characters."""
        if not name or not isinstance(name, str):
            raise ValueError(f"Invalid {ref_type} name: cannot be empty.")
        clean = name.strip()
        if not clean or ".." in clean or clean.startswith(("/", "\\")) or ":" in clean or "~" in clean or "^" in clean:
            raise ValueError(f"Invalid {ref_type} name '{name}': contains invalid characters or path traversal.")
        base_dir = self.cognit_dir / "refs" / ("heads" if ref_type == "branch" else "tags")
        target_path = (base_dir / clean).resolve()
        if not target_path.is_relative_to(base_dir.resolve()):
            raise ValueError(f"Path traversal detected in {ref_type} name: '{name}'")

    def get_branch_checkpoint(self, branch_name: str) -> Optional[str]:
        """Return the checkpoint hash for a given branch name."""
        try:
            self._validate_ref_name(branch_name, "branch")
        except ValueError:
            return None
        branch_file = self.cognit_dir / "refs" / "heads" / branch_name
        if branch_file.exists():
            return branch_file.read_text(encoding="utf-8").strip()
        return None

    def get_head_checkpoint_id(self) -> Optional[str]:
        """Return the checkpoint hash of current HEAD."""
        ref = self.get_head_ref()
        if ref.startswith("refs/heads/"):
            return self.get_branch_checkpoint(ref[len("refs/heads/"):])
        # Direct hash (detached HEAD)
        return ref if ref else None

    def get_head_checkpoint(self) -> Optional[Checkpoint]:
        """Load and return current HEAD Checkpoint object."""
        cid = self.get_head_checkpoint_id()
        if not cid:
            return None
        return self.storage.read_checkpoint(cid)

    def resolve_ref(self, query: str) -> str:
        """Resolve a query (branch, HEAD, HEAD~N, tag, 64-char hash, or short hash) to a 64-char checkpoint ID."""
        if not query:
            raise ValueError("Reference query cannot be empty.")

        clean_q = query.strip()

        # 1. Handle HEAD and HEAD~N
        if clean_q == "HEAD":
            cid = self.get_head_checkpoint_id()
            if not cid:
                raise ValueError("HEAD does not point to any checkpoint (empty repository).")
            return cid

        if clean_q.startswith("HEAD~"):
            try:
                n = int(clean_q[len("HEAD~"):])
            except ValueError:
                raise ValueError(f"Invalid HEAD relative reference: '{clean_q}'")
            if n < 0:
                raise ValueError(f"Invalid HEAD relative reference: '{clean_q}'")
            curr = self.get_head_checkpoint_id()
            if not curr:
                raise ValueError("HEAD does not point to any checkpoint.")
            for _ in range(n):
                cp = self.storage.read_checkpoint(curr)
                if not cp.parent_ids:
                    raise ValueError(f"Reference '{clean_q}' exceeds root checkpoint.")
                curr = cp.parent_ids[0]
            return curr

        # 2. Check branch
        branch_cid = self.get_branch_checkpoint(clean_q)
        if branch_cid:
            return branch_cid

        # 3. Check tag
        try:
            self._validate_ref_name(clean_q, "tag")
            tag_file = self.cognit_dir / "refs" / "tags" / clean_q
            if tag_file.is_file():
                return tag_file.read_text(encoding="utf-8").strip()
        except ValueError:
            pass

        # 4. Check if exact 64-char hash in storage
        if len(clean_q) == 64 and self.storage.has_object(clean_q):
            return clean_q

        # 5. Check database index (exact or unique short-hash prefix)
        try:
            db_cp = self.db.get_checkpoint(clean_q)
            if db_cp:
                return db_cp.id
        except ValueError as e:
            raise e

        # 6. Check storage prefix
        full_hash = self.storage.find_object_by_prefix(clean_q)
        if full_hash:
            return full_hash

        raise ValueError(f"Cannot resolve reference or checkpoint ID: '{clean_q}'")

    def set_branch_checkpoint(self, branch_name: str, checkpoint_id: str) -> None:
        """Update branch reference to a checkpoint hash."""
        self._validate_ref_name(branch_name, "branch")
        branch_file = self.cognit_dir / "refs" / "heads" / branch_name
        branch_file.parent.mkdir(parents=True, exist_ok=True)
        branch_file.write_text(checkpoint_id.strip() + "\n", encoding="utf-8")

    def create_branch(self, branch_name: str, start_checkpoint_id: Optional[str] = None) -> None:
        """Create a new branch pointing to start_checkpoint_id or HEAD."""
        self._validate_ref_name(branch_name, "branch")
        target_cid = self.resolve_ref(start_checkpoint_id) if start_checkpoint_id else self.get_head_checkpoint_id()
        if not target_cid:
            raise ValueError("Cannot branch from empty repository without any checkpoints.")
        self.set_branch_checkpoint(branch_name, target_cid)

    def switch_branch(self, branch_name: str, auto_stash: bool = True) -> None:
        """Switch active branch and update working directory."""
        self._validate_ref_name(branch_name, "branch")
        branch_file = self.cognit_dir / "refs" / "heads" / branch_name
        if not branch_file.exists():
            raise ValueError(f"Branch '{branch_name}' does not exist.")

        # Update HEAD ref
        (self.cognit_dir / "HEAD").write_text(f"ref: refs/heads/{branch_name}\n", encoding="utf-8")

        target_cid = branch_file.read_text(encoding="utf-8").strip()
        self._checkout_tree(target_cid)

    def list_branches(self) -> List[Dict[str, Any]]:
        """List all branches with their latest checkpoint info."""
        heads_dir = self.cognit_dir / "refs" / "heads"
        active = self.get_active_branch()
        results = []

        if heads_dir.exists():
            for p in heads_dir.glob("**/*"):
                if p.is_file():
                    bname = p.relative_to(heads_dir).as_posix()
                    cid = p.read_text(encoding="utf-8").strip()
                    cp = self.storage.read_checkpoint(cid) if cid else None
                    results.append({
                        "name": bname,
                        "is_active": (bname == active),
                        "checkpoint_id": cid,
                        "message": cp.message if cp else "",
                        "timestamp": cp.timestamp if cp else "",
                        "author": cp.author if cp else "",
                    })
        return results

    # Ignore and File Filtering

    def get_ignore_patterns(self) -> List[str]:
        """Load patterns from .cognitignore and .gitignore."""
        patterns = list(DEFAULT_IGNORES)
        for name in [".cognitignore", ".gitignore"]:
            ign_p = self.root_dir / name
            if ign_p.exists():
                for line in ign_p.read_text(encoding="utf-8").splitlines():
                    sline = line.strip()
                    if sline and not sline.startswith("#"):
                        patterns.append(sline)
        return patterns

    def is_ignored(self, rel_path: str, patterns: List[str]) -> bool:
        """Check if a POSIX relative path matches ignore patterns."""
        norm_path = rel_path.replace("\\", "/")
        parts = norm_path.split("/")

        for pat in patterns:
            clean_pat = pat.rstrip("/")
            # Check full path match
            if fnmatch.fnmatch(norm_path, clean_pat) or fnmatch.fnmatch(norm_path, pat):
                return True
            # Check any path component (e.g. folder name)
            for part in parts:
                if fnmatch.fnmatch(part, clean_pat):
                    return True
        return False

    def list_working_files(self) -> List[str]:
        """Scan working directory and return all non-ignored relative file paths."""
        ignores = self.get_ignore_patterns()
        file_list: List[str] = []

        for root, dirs, files in os.walk(self.root_dir):
            rel_dir = os.path.relpath(root, self.root_dir).replace("\\", "/")
            if rel_dir == ".":
                rel_dir = ""

            # Filter out ignored directories in-place to avoid walking them
            dirs[:] = [
                d for d in dirs
                if not self.is_ignored(f"{rel_dir}/{d}" if rel_dir else d, ignores)
            ]

            for f in files:
                rel_file = f"{rel_dir}/{f}" if rel_dir else f
                if not self.is_ignored(rel_file, ignores):
                    file_list.append(rel_file)

        return sorted(file_list)

    # Status & Working Tree Analysis

    def status(self) -> List[FileStatus]:
        """Compute working directory status compared to HEAD."""
        head_cp = self.get_head_checkpoint()
        head_entries: Dict[str, TreeEntry] = {}
        if head_cp:
            head_entries = {e.path: e for e in self.storage.read_tree(head_cp.tree_hash)}

        working_files = set(self.list_working_files())
        all_paths = sorted(set(head_entries.keys()).union(working_files))
        results: List[FileStatus] = []

        cached_files = self.db.get_all_cached_files()

        for path in all_paths:
            full_path = self.root_dir / path

            if path in head_entries and path not in working_files:
                # Deleted from working tree
                results.append(FileStatus(path=path, status="deleted"))
                continue

            if path not in head_entries and path in working_files:
                # Untracked / newly added
                sz = full_path.stat().st_size
                results.append(FileStatus(path=path, status="added", size=sz))
                continue

            # In both HEAD and working tree: check modification
            stat = full_path.stat()
            head_entry = head_entries[path]

            cached = cached_files.get(path)
            if cached and cached["mtime"] == stat.st_mtime and cached["size"] == stat.st_size:
                current_blob_hash = cached["blob_hash"]
            else:
                raw_bytes = full_path.read_bytes()
                # Compute hash without writing yet
                import hashlib
                header = f"blob {len(raw_bytes)}\x00".encode("utf-8")
                current_blob_hash = hashlib.sha256(header + raw_bytes).hexdigest()
                self.db.update_file_cache(path, stat.st_mtime, stat.st_size, current_blob_hash)

            if current_blob_hash != head_entry.blob_hash:
                # Modified! Also detect symbols changed
                syms_changed = []
                try:
                    head_content = self.storage.read_blob(head_entry.blob_hash).decode("utf-8", errors="replace")
                    work_content = full_path.read_text(encoding="utf-8", errors="replace")
                    diff_res = SemanticDiffer.diff_content(path, head_content, work_content)
                    syms_changed = [s.name for s in diff_res.symbol_diffs]
                except Exception:
                    pass

                results.append(FileStatus(
                    path=path,
                    status="modified",
                    size=stat.st_size,
                    symbols_changed=syms_changed,
                ))
            else:
                results.append(FileStatus(path=path, status="unmodified", size=stat.st_size))

        return results

    # Checkpoint Creation (Transactional Commit)

    def create_checkpoint(
        self,
        message: str,
        author: str = "Agent",
        agent_metadata: Optional[AgentMetadata] = None,
        branch: Optional[str] = None,
    ) -> Checkpoint:
        """Create a new immutable checkpoint from current working directory."""
        target_branch = branch or self.get_active_branch()
        head_cid = self.get_head_checkpoint_id()
        parent_ids = [head_cid] if head_cid else []

        # 1. Walk working files and write blobs
        working_files = self.list_working_files()
        tree_entries: List[TreeEntry] = []

        for rel_path in working_files:
            full_p = self.root_dir / rel_path
            raw_bytes = full_p.read_bytes()
            is_bin = b"\x00" in raw_bytes[:1024]

            blob_hash = self.storage.write_blob(raw_bytes)
            stat = full_p.stat()

            # Update cache
            self.db.update_file_cache(rel_path, stat.st_mtime, stat.st_size, blob_hash)

            tree_entries.append(TreeEntry(
                path=rel_path,
                blob_hash=blob_hash,
                size=len(raw_bytes),
                mode=0o755 if os.access(full_p, os.X_OK) else 0o644,
                is_binary=is_bin,
            ))

        # 2. Write tree object
        tree_hash = self.storage.write_tree(tree_entries)

        # 3. Create Checkpoint object
        meta = agent_metadata or AgentMetadata()
        checkpoint = Checkpoint(
            id="",
            parent_ids=parent_ids,
            tree_hash=tree_hash,
            timestamp=current_iso_timestamp(),
            author=author,
            message=message,
            branch=target_branch,
            agent_metadata=meta,
        )

        # 4. Write checkpoint object
        cid = self.storage.write_checkpoint(checkpoint)

        # 5. Record checkpoint in SQLite index
        self.db.record_checkpoint(checkpoint)

        # 6. Parse and record symbols in index for fast queryability
        for entry in tree_entries:
            if not entry.is_binary:
                try:
                    content = (self.root_dir / entry.path).read_text(encoding="utf-8", errors="replace")
                    symbols = ASTParser.parse_file(entry.path, content)
                    if symbols:
                        self.db.record_symbols(cid, entry.path, symbols)
                except Exception:
                    pass

        # 7. Update branch ref
        if target_branch != "DETACHED":
            self.set_branch_checkpoint(target_branch, cid)
        else:
            (self.cognit_dir / "HEAD").write_text(cid + "\n", encoding="utf-8")

        return checkpoint

    # Diffing

    def diff(
        self,
        mode: str = "summary",
        target_checkpoint_id: Optional[str] = None,
    ) -> List[FileDiffResult]:
        """Compute diffs between HEAD/target checkpoint and working tree."""
        base_cid = self.resolve_ref(target_checkpoint_id) if target_checkpoint_id else self.get_head_checkpoint_id()
        base_entries: Dict[str, TreeEntry] = {}

        if base_cid:
            base_cp = self.storage.read_checkpoint(base_cid)
            base_entries = {e.path: e for e in self.storage.read_tree(base_cp.tree_hash)}

        working_files = set(self.list_working_files())
        all_paths = sorted(set(base_entries.keys()).union(working_files))
        diff_results: List[FileDiffResult] = []

        for path in all_paths:
            full_p = self.root_dir / path

            if path in base_entries and path not in working_files:
                # Deleted file
                old_bytes = self.storage.read_blob(base_entries[path].blob_hash)
                old_content = old_bytes.decode("utf-8", errors="replace")
                lines_cnt = len(old_content.splitlines())
                diff_results.append(FileDiffResult(
                    file_path=path,
                    is_deleted=True,
                    total_deleted=lines_cnt,
                    raw_unified_diff=f"--- a/{path}\n+++ /dev/null\n@@ -1,{lines_cnt} +0,0 @@\n",
                ))
                continue

            if path not in base_entries and path in working_files:
                # Added file
                new_content = full_p.read_text(encoding="utf-8", errors="replace")
                lines_cnt = len(new_content.splitlines())
                diff_results.append(FileDiffResult(
                    file_path=path,
                    is_new=True,
                    total_added=lines_cnt,
                    raw_unified_diff=f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{lines_cnt} @@\n",
                ))
                continue

            # Modified or identical
            old_bytes = self.storage.read_blob(base_entries[path].blob_hash)
            old_content = old_bytes.decode("utf-8", errors="replace")
            new_content = full_p.read_text(encoding="utf-8", errors="replace")

            if old_content != new_content:
                res = SemanticDiffer.diff_content(path, old_content, new_content)
                diff_results.append(res)

        return diff_results

    def diff_checkpoints(
        self,
        cid_base: str,
        cid_target: str,
        mode: str = "summary",
    ) -> List[FileDiffResult]:
        """Compute diffs directly between two checkpoints without touching working directory."""
        full_base = self.resolve_ref(cid_base)
        full_target = self.resolve_ref(cid_target)

        base_cp = self.storage.read_checkpoint(full_base)
        target_cp = self.storage.read_checkpoint(full_target)

        base_entries = {e.path: e for e in self.storage.read_tree(base_cp.tree_hash)}
        target_entries = {e.path: e for e in self.storage.read_tree(target_cp.tree_hash)}

        all_paths = sorted(set(base_entries.keys()) | set(target_entries.keys()))
        diff_results: List[FileDiffResult] = []

        for path in all_paths:
            if path in base_entries and path not in target_entries:
                old_bytes = self.storage.read_blob(base_entries[path].blob_hash)
                old_content = old_bytes.decode("utf-8", errors="replace")
                lines_cnt = len(old_content.splitlines())
                diff_results.append(FileDiffResult(
                    file_path=path,
                    is_deleted=True,
                    total_deleted=lines_cnt,
                    raw_unified_diff=f"--- a/{path}\n+++ /dev/null\n@@ -1,{lines_cnt} +0,0 @@\n",
                ))
            elif path not in base_entries and path in target_entries:
                new_bytes = self.storage.read_blob(target_entries[path].blob_hash)
                new_content = new_bytes.decode("utf-8", errors="replace")
                lines_cnt = len(new_content.splitlines())
                diff_results.append(FileDiffResult(
                    file_path=path,
                    is_new=True,
                    total_added=lines_cnt,
                    raw_unified_diff=f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{lines_cnt} @@\n",
                ))
            else:
                old_bytes = self.storage.read_blob(base_entries[path].blob_hash)
                new_bytes = self.storage.read_blob(target_entries[path].blob_hash)
                if old_bytes != new_bytes:
                    old_content = old_bytes.decode("utf-8", errors="replace")
                    new_content = new_bytes.decode("utf-8", errors="replace")
                    res = SemanticDiffer.diff_content(path, old_content, new_content)
                    diff_results.append(res)

        return diff_results

    # 3-Way Branch Merging

    def merge_branches(
        self,
        source_branch: str,
        target_branch: Optional[str] = None,
        author: str = "MergeAgent",
        message: str = "",
    ) -> Checkpoint:
        """Perform semantic 3-way merge from source_branch into target_branch."""
        tgt_b = target_branch or self.get_active_branch()
        source_cid = self.get_branch_checkpoint(source_branch)
        target_cid = self.get_branch_checkpoint(tgt_b)

        if not source_cid:
            raise ValueError(f"Source branch '{source_branch}' not found.")
        if not target_cid:
            raise ValueError(f"Target branch '{tgt_b}' not found.")

        # Find common ancestor (merge base)
        base_cid = self._find_merge_base(target_cid, source_cid)
        base_entries = {}
        if base_cid:
            base_cp = self.storage.read_checkpoint(base_cid)
            base_entries = {e.path: e for e in self.storage.read_tree(base_cp.tree_hash)}

        ours_cp = self.storage.read_checkpoint(target_cid)
        theirs_cp = self.storage.read_checkpoint(source_cid)

        ours_entries = {e.path: e for e in self.storage.read_tree(ours_cp.tree_hash)}
        theirs_entries = {e.path: e for e in self.storage.read_tree(theirs_cp.tree_hash)}

        all_paths = sorted(set(base_entries.keys()) | set(ours_entries.keys()) | set(theirs_entries.keys()))

        merged_tree_entries: List[TreeEntry] = []
        any_conflicts = False

        for path in all_paths:
            base_blob = self.storage.read_blob(base_entries[path].blob_hash).decode("utf-8", errors="replace") if path in base_entries else ""
            ours_blob = self.storage.read_blob(ours_entries[path].blob_hash).decode("utf-8", errors="replace") if path in ours_entries else ""
            theirs_blob = self.storage.read_blob(theirs_entries[path].blob_hash).decode("utf-8", errors="replace") if path in theirs_entries else ""

            merge_res = SemanticMerger.merge_files(path, base_blob, ours_blob, theirs_blob)

            if not merge_res.clean:
                any_conflicts = True

            # Write merged content
            merged_bytes = merge_res.merged_content.encode("utf-8")
            blob_hash = self.storage.write_blob(merged_bytes)

            # Write file into working directory safely
            out_file = (self.root_dir / path).resolve()
            if not out_file.is_relative_to(self.root_dir.resolve()):
                raise ValueError(f"Path traversal detected in merge path: '{path}'")
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(merged_bytes)

            merged_tree_entries.append(TreeEntry(
                path=path,
                blob_hash=blob_hash,
                size=len(merged_bytes),
                mode=0o644,
            ))

        tree_hash = self.storage.write_tree(merged_tree_entries)
        default_msg = f"Merge branch '{source_branch}' into '{tgt_b}'" + (" [CONFLICTS]" if any_conflicts else "")

        merge_cp = Checkpoint(
            id="",
            parent_ids=[target_cid, source_cid],
            tree_hash=tree_hash,
            timestamp=current_iso_timestamp(),
            author=author,
            message=message or default_msg,
            branch=tgt_b,
            agent_metadata=AgentMetadata(
                agent_id="merge-agent",
                model="semantic-merger",
                goal=f"Merge {source_branch} into {tgt_b}",
                test_status="conflicted" if any_conflicts else "clean",
            ),
        )

        cid = self.storage.write_checkpoint(merge_cp)
        self.db.record_checkpoint(merge_cp)
        self.set_branch_checkpoint(tgt_b, cid)

        return merge_cp

    def _find_merge_base(self, cid_a: str, cid_b: str) -> Optional[str]:
        """Find the lowest common ancestor between two checkpoints."""
        ancestors_a = self._get_all_ancestors(cid_a)
        queue = [cid_b]
        visited = set()

        while queue:
            curr = queue.pop(0)
            if curr in ancestors_a:
                return curr
            if curr not in visited:
                visited.add(curr)
                cp = self.db.get_checkpoint(curr)
                if cp:
                    queue.extend(cp.parent_ids)
        return None

    def _get_all_ancestors(self, cid: str) -> Set[str]:
        ancestors = set()
        queue = [cid]
        while queue:
            curr = queue.pop(0)
            if curr not in ancestors:
                ancestors.add(curr)
                cp = self.db.get_checkpoint(curr)
                if cp:
                    queue.extend(cp.parent_ids)
        return ancestors

    # Time Travel & Checkout

    def time_travel(self, checkpoint_id: str) -> Checkpoint:
        """Safely restore working directory to an exact checkpoint or reference."""
        resolved_cid = self.resolve_ref(checkpoint_id)
        cp = self.storage.read_checkpoint(resolved_cid)
        self._checkout_tree(cp.id)
        # Update HEAD to detached or point to this checkpoint
        (self.cognit_dir / "HEAD").write_text(resolved_cid + "\n", encoding="utf-8")
        return cp

    def undo(self) -> Optional[Checkpoint]:
        """Undo last checkpoint on current branch safely."""
        head_cp = self.get_head_checkpoint()
        if not head_cp or not head_cp.parent_ids:
            return None
        parent_id = head_cp.parent_ids[0]
        return self.time_travel(parent_id)

    def _checkout_tree(self, checkpoint_id: str) -> None:
        """Restore working directory to match the tree of checkpoint_id."""
        resolved_cid = self.resolve_ref(checkpoint_id)
        cp = self.storage.read_checkpoint(resolved_cid)
        tree_entries = self.storage.read_tree(cp.tree_hash)
        expected_paths = {e.path: e for e in tree_entries}

        # Delete files in working dir that are not in target tree (except ignored ones)
        current_files = self.list_working_files()
        for f in current_files:
            if f not in expected_paths:
                p = self.root_dir / f
                if p.is_file():
                    try:
                        p.unlink()
                    except OSError:
                        pass
                # Prune empty parent directories up to root_dir
                parent = p.parent
                while parent != self.root_dir and parent.exists():
                    try:
                        if not any(parent.iterdir()):
                            parent.rmdir()
                            parent = parent.parent
                        else:
                            break
                    except OSError:
                        break

        # Write files from tree safely
        for path, entry in expected_paths.items():
            full_p = (self.root_dir / path).resolve()
            if not full_p.is_relative_to(self.root_dir.resolve()):
                raise ValueError(f"Path traversal detected in tree entry: '{path}'")
            full_p.parent.mkdir(parents=True, exist_ok=True)
            blob_bytes = self.storage.read_blob(entry.blob_hash)
            full_p.write_bytes(blob_bytes)
            stat = full_p.stat()
            self.db.update_file_cache(path, stat.st_mtime, stat.st_size, entry.blob_hash)

    def log(
        self,
        limit: int = 50,
        branch: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> List[Checkpoint]:
        """Query checkpoint history with rich metadata filtering."""
        all_cps = self.db.get_all_checkpoints(limit=limit, branch=branch)
        if agent_id:
            all_cps = [c for c in all_cps if c.agent_metadata.agent_id == agent_id]
        return all_cps

    # Advanced Agentic Features (100x Upgrade)

    def get_dependency_graph(self):
        """Build and return repository dependency graph."""
        from cognit.semantic.graph import DependencyGraph
        graph = DependencyGraph(self.root_dir, self)
        graph.build_graph()
        return graph

    def analyze_impact(self, target: str):
        """Analyze change blast radius and affected tests for target file or symbol."""
        graph = self.get_dependency_graph()
        return graph.analyze_impact(target)

    def build_context(self, goal: str, max_tokens: int = 1500) -> str:
        """Generate a token-optimized context block for an agent prompt."""
        graph = self.get_dependency_graph()
        return graph.build_compact_context(goal, max_tokens)

    def record_micro_step(self, action: str, agent_id: str = "agent"):
        """Record an ephemeral micro-version in the flight recorder."""
        from cognit.agentic.recorder import FlightRecorder
        recorder = FlightRecorder(self)
        return recorder.record_step(action, agent_id)

    def rollback_micro_step(self, steps: int = 1):
        """Roll back working directory by N micro-steps."""
        from cognit.agentic.recorder import FlightRecorder
        recorder = FlightRecorder(self)
        return recorder.rollback(steps)

    def create_bundle(self, output_path: str, branch_name: Optional[str] = None) -> int:
        """Create a compressed .cgb offline repository bundle."""
        from cognit.core.bundle import BundleManager
        bm = BundleManager(self)
        return bm.create_bundle(output_path, branch_name)

    def apply_bundle(self, bundle_path: str) -> Dict[str, Any]:
        """Unpack a .cgb bundle into current repository."""
        from cognit.core.bundle import BundleManager
        bm = BundleManager(self)
        return bm.apply_bundle(bundle_path)

