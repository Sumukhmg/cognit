"""Speculative Multi-Model Tournament and Leaderboard Engine."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from cognit.agentic.speculative import SpeculativeManager
from cognit.core.models import Checkpoint


@dataclass
class CandidateScorecard:
    """Evaluation scorecard for a candidate speculative trial."""

    trial_name: str
    branch_name: str
    model: str
    test_passed: bool
    score: float
    duration_seconds: float = 0.0
    lines_added: int = 0
    lines_deleted: int = 0
    tokens_used: int = 0
    rank: int = 0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SpeculativeTournament:
    """Ranks and selects the optimal candidate among parallel speculative trials."""

    def __init__(self, repo: Any) -> None:
        self.repo = repo
        self.spec = SpeculativeManager(self.repo.db, self.repo)

    def evaluate_candidates(
        self,
        trial_names: List[str],
        test_command: Optional[str] = None,
    ) -> List[CandidateScorecard]:
        """Run evaluations across multiple trial branches and produce a ranked scorecard."""
        scorecards: List[CandidateScorecard] = []

        for name in trial_names:
            trial = self.repo.db.get_trial(name)
            if not trial:
                continue

            # Evaluate with command if provided
            if test_command:
                trial = self.spec.evaluate_trial(name, test_command=test_command)

            # Get latest checkpoint on trial branch
            branch_name = f"speculative/{name}"
            cid = self.repo.get_branch_checkpoint(branch_name)
            model = "unknown"
            tokens = 0
            if cid:
                cp = self.repo.storage.read_checkpoint(cid)
                model = cp.agent_metadata.model or "unknown"
                tokens = cp.agent_metadata.tokens_used or 0
                diffs = self.repo.diff_checkpoints(trial.base_checkpoint_id, cid)
            else:
                diffs = []

            added = sum(d.total_added for d in diffs)
            deleted = sum(d.total_deleted for d in diffs)

            # Composite ranking score:
            # High weight on passing tests (1000 pts), small penalty on excessive token bloat
            pass_pts = 1000 if trial.test_passed else 0
            composite = pass_pts + (trial.score or 0) * 100 - (tokens * 0.01)

            scorecards.append(CandidateScorecard(
                trial_name=name,
                branch_name=branch_name,
                model=model,
                test_passed=bool(trial.test_passed),
                score=round(composite, 2),
                lines_added=added,
                lines_deleted=deleted,
                tokens_used=tokens,
                notes=trial.evaluation_notes or "",
            ))

        # Rank by composite score descending
        scorecards.sort(key=lambda s: s.score, reverse=True)
        for idx, sc in enumerate(scorecards, start=1):
            sc.rank = idx

        return scorecards

    def promote_winner(self, scorecards: List[CandidateScorecard]) -> Optional[Checkpoint]:
        """Automatically promote and merge the top-ranked candidate into active branch."""
        if not scorecards:
            return None

        winner = scorecards[0]
        if not winner.test_passed:
            raise RuntimeError(f"Winner '{winner.trial_name}' failed verification tests. Cannot promote.")

        return self.spec.accept_trial(winner.trial_name)
