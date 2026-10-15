"""Bidirectional bridge between Cognit and Git for seamless GitHub ecosystem interoperability."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from cognit.core.models import AgentMetadata, Checkpoint


class GitBridge:
    """Interoperability bridge allowing import from Git and export to Git."""

    def __init__(self, cognit_repo: Any) -> None:
        self.cognit_repo = cognit_repo

    def import_from_git(self, git_dir: Path | str, max_commits: int = 50) -> int:
        """Import commit history from a Git repository into Cognit."""
        git_path = Path(git_dir)
        if not (git_path / ".git").exists() and not (git_path / "HEAD").exists():
            raise ValueError(f"Path '{git_path}' is not a valid Git repository.")

        # Read git log: format: hash|parent|author|date|subject
        cmd = [
            "git", "log", f"-n{max_commits}", "--reverse",
            "--format=%H|%P|%an|%aI|%s"
        ]
        res = subprocess.run(cmd, cwd=str(git_path), capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Git log failed: {res.stderr}")

        lines = res.stdout.strip().splitlines()
        imported_count = 0

        for line in lines:
            if not line.strip():
                continue
            parts = line.split("|", 4)
            if len(parts) < 5:
                continue
            git_hash, git_parents, author, timestamp, subject = parts
            parent_hashes = git_parents.split()

            # Checkout commit in git to read files or snapshot securely
            subprocess.run(["git", "checkout", "-q", "--detach", git_hash, "--"], cwd=str(git_path), check=True)

            if git_path.resolve() != self.cognit_repo.root_dir.resolve():
                # Sync files from git_path into cognit repo
                git_files = set()
                for root, dirs, files in os.walk(git_path):
                    if ".git" in dirs:
                        dirs.remove(".git")
                    for f in files:
                        full_f = Path(root) / f
                        rel = full_f.relative_to(git_path).as_posix()
                        git_files.add(rel)
                        target_f = (self.cognit_repo.root_dir / rel).resolve()
                        if not target_f.is_relative_to(self.cognit_repo.root_dir.resolve()):
                            continue
                        target_f.parent.mkdir(parents=True, exist_ok=True)
                        target_f.write_bytes(full_f.read_bytes())
                # Remove obsolete files from root_dir
                for f in self.cognit_repo.list_working_files():
                    if f not in git_files:
                        del_p = self.cognit_repo.root_dir / f
                        if del_p.is_file():
                            try:
                                del_p.unlink()
                            except OSError:
                                pass

            # Create checkpoint in Cognit
            cp = self.cognit_repo.create_checkpoint(
                message=f"[git:{git_hash[:7]}] {subject}",
                author=author,
                agent_metadata=AgentMetadata(
                    agent_id="git-import",
                    model="git",
                    goal=f"Imported from git commit {git_hash[:8]}",
                ),
            )
            imported_count += 1

        return imported_count

    def export_to_git(self, target_git_dir: Path | str) -> int:
        """Export Cognit checkpoints to a Git repository."""
        target_path = Path(target_git_dir)
        target_path.mkdir(parents=True, exist_ok=True)

        # Ensure git repo is initialized at target
        if not (target_path / ".git").exists():
            subprocess.run(["git", "init"], cwd=str(target_path), check=True)

        checkpoints = self.cognit_repo.db.get_all_checkpoints(limit=200)
        # Reverse to apply in chronological order
        checkpoints.reverse()

        exported_count = 0
        for cp in checkpoints:
            # Restore files into target dir from tree
            tree_entries = self.cognit_repo.storage.read_tree(cp.tree_hash)
            expected_paths = {e.path for e in tree_entries}

            # Delete files that are not in target tree (excluding .git)
            for root, dirs, files in os.walk(target_path):
                if ".git" in dirs:
                    dirs.remove(".git")
                for f in files:
                    full_f = Path(root) / f
                    rel_f = full_f.relative_to(target_path).as_posix()
                    if rel_f not in expected_paths:
                        try:
                            full_f.unlink()
                        except OSError:
                            pass

            # Write files safely
            for entry in tree_entries:
                out_file = (target_path / entry.path).resolve()
                if not out_file.is_relative_to(target_path.resolve()):
                    continue
                out_file.parent.mkdir(parents=True, exist_ok=True)
                blob_bytes = self.cognit_repo.storage.read_blob(entry.blob_hash)
                out_file.write_bytes(blob_bytes)

            # Run git add & commit
            subprocess.run(["git", "add", "-A"], cwd=str(target_path), check=True)

            # Commit message with agent reasoning metadata
            meta_msg = cp.message
            if cp.agent_metadata.goal:
                meta_msg += f"\n\n[Cognit Agent: {cp.agent_metadata.agent_id} | Model: {cp.agent_metadata.model}]"
                meta_msg += f"\nGoal: {cp.agent_metadata.goal}"
            if cp.agent_metadata.reasoning:
                meta_msg += f"\nReasoning: {cp.agent_metadata.reasoning}"

            env = os.environ.copy()
            env["GIT_COMMITTER_NAME"] = cp.author
            env["GIT_COMMITTER_EMAIL"] = "agent@cognit.local"
            env["GIT_AUTHOR_NAME"] = cp.author
            env["GIT_AUTHOR_EMAIL"] = "agent@cognit.local"
            env["GIT_AUTHOR_DATE"] = cp.timestamp
            env["GIT_COMMITTER_DATE"] = cp.timestamp

            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", meta_msg],
                cwd=str(target_path),
                env=env,
                check=True,
                capture_output=True,
            )
            exported_count += 1

        return exported_count
