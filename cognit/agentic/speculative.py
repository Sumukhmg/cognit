"""Speculative Execution and Trial Management for AI agents."""

from __future__ import annotations

import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from cognit.core.database import Database
from cognit.core.models import SpeculativeTrial, Checkpoint, current_iso_timestamp


class SpeculativeManager:
    """Manages speculative exploration branches, evaluations, and auto-promotions."""

    def __init__(self, db: Database, repo: Any) -> None:
        self.db = db
        self.repo = repo

    def start_trial(self, name: str, base_checkpoint_id: Optional[str] = None) -> SpeculativeTrial:
        """Create a new speculative trial branch."""
        if not base_checkpoint_id:
            head_cp = self.repo.get_head_checkpoint()
            if not head_cp:
                raise ValueError("Cannot start speculative trial on empty repository without base checkpoint.")
            base_checkpoint_id = head_cp.id

        existing = self.db.get_trial(name)
        if existing and existing.status == "active":
            raise ValueError(f"Active trial '{name}' already exists.")

        trial = SpeculativeTrial(
            name=name,
            base_checkpoint_id=base_checkpoint_id,
            current_checkpoint_id=base_checkpoint_id,
            status="active",
            created_at=current_iso_timestamp(),
        )
        self.db.record_trial(trial)

        # Create branch ref for the trial
        self.repo.create_branch(f"speculative/{name}", start_checkpoint_id=base_checkpoint_id)
        return trial

    def evaluate_trial(
        self,
        name: str,
        test_command: Optional[str] = None,
        score: Optional[float] = None,
        notes: str = "",
    ) -> SpeculativeTrial:
        """Run tests or record evaluation score for a speculative trial."""
        trial = self.db.get_trial(name)
        if not trial:
            raise ValueError(f"Trial '{name}' not found.")

        passed = None
        eval_notes = notes

        if test_command:
            start_t = time.time()
            try:
                proc = subprocess.run(
                    test_command,
                    shell=True,
                    cwd=str(self.repo.root_dir),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                )
                dur = round(time.time() - start_t, 2)
                passed = (proc.returncode == 0)
                eval_notes += f"\nCommand: {test_command}\nExit: {proc.returncode} ({dur}s)\nOutput:\n{proc.stdout[-500:]}\n{proc.stderr[-500:]}"
            except Exception as e:
                passed = False
                eval_notes += f"\nCommand failed with exception: {str(e)}"

        trial.test_passed = passed
        trial.score = score if score is not None else (1.0 if passed else 0.0 if passed is False else None)
        trial.evaluation_notes = eval_notes.strip()

        # Update latest checkpoint of trial branch
        branch_ref = self.repo.get_branch_checkpoint(f"speculative/{name}")
        if branch_ref:
            trial.current_checkpoint_id = branch_ref

        self.db.record_trial(trial)
        return trial

    def accept_trial(self, name: str) -> Checkpoint:
        """Promote a winning trial branch onto the main/current branch."""
        trial = self.db.get_trial(name)
        if not trial:
            raise ValueError(f"Trial '{name}' not found.")

        target_branch = self.repo.get_active_branch()
        trial_cp_id = self.repo.get_branch_checkpoint(f"speculative/{name}")
        if not trial_cp_id:
            raise ValueError(f"No commits found on trial branch 'speculative/{name}'.")

        # Merge or fast-forward
        merged_cp = self.repo.merge_branches(
            source_branch=f"speculative/{name}",
            target_branch=target_branch,
            author="SpeculativeAgent",
            message=f"Accept speculative trial '{name}' (Score: {trial.score})",
        )

        trial.status = "accepted"
        self.db.record_trial(trial)
        return merged_cp

    def discard_trial(self, name: str, reason: str = "") -> SpeculativeTrial:
        """Mark a trial as discarded while preserving the record for post-mortem analysis."""
        trial = self.db.get_trial(name)
        if not trial:
            raise ValueError(f"Trial '{name}' not found.")

        trial.status = "discarded"
        trial.evaluation_notes += f"\nDiscarded: {reason}"
        self.db.record_trial(trial)
        return trial

    def list_trials(self) -> List[SpeculativeTrial]:
        return self.db.list_trials()
