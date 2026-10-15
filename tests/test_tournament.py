"""Unit tests for SpeculativeTournament multi-model selection."""

import shutil
import tempfile
from pathlib import Path
import unittest

from cognit.agentic.speculative import SpeculativeManager
from cognit.agentic.tournament import SpeculativeTournament
from cognit.core.models import AgentMetadata
from cognit.core.repo import CognitRepo


class TestTournament(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.repo = CognitRepo.init(self.temp_dir, default_branch="main")
        (self.temp_dir / "math_ops.py").write_text("def solve(): return 0\n", encoding="utf-8")
        self.repo.create_checkpoint("Initial base commit")
        self.spec = SpeculativeManager(self.repo.db, self.repo)
        self.tourn = SpeculativeTournament(self.repo)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tournament_ranking_and_auto_promotion(self):
        # Candidate 1: Model Gemini
        self.spec.start_trial("candidate-gemini")
        self.repo.switch_branch("speculative/candidate-gemini")
        (self.temp_dir / "math_ops.py").write_text("def solve(): return 42  # Fast solution\n", encoding="utf-8")
        self.repo.create_checkpoint(
            "Gemini solution",
            agent_metadata=AgentMetadata(
                agent_id="agent-gemini",
                model="gemini-3.8-flash",
                tokens_used=120,
            ),
        )
        self.spec.evaluate_trial("candidate-gemini", score=0.99)
        # Mark test passed
        trial1 = self.repo.db.get_trial("candidate-gemini")
        trial1.test_passed = True
        self.repo.db.record_trial(trial1)

        # Candidate 2: Model Slow
        self.repo.switch_branch("main")
        self.spec.start_trial("candidate-slow")
        self.repo.switch_branch("speculative/candidate-slow")
        (self.temp_dir / "math_ops.py").write_text("def solve(): return 42  # Bloated solution\n" * 10, encoding="utf-8")
        self.repo.create_checkpoint(
            "Slow solution",
            agent_metadata=AgentMetadata(
                agent_id="agent-slow",
                model="slow-model",
                tokens_used=950,
            ),
        )
        self.spec.evaluate_trial("candidate-slow", score=0.75)
        trial2 = self.repo.db.get_trial("candidate-slow")
        trial2.test_passed = True
        self.repo.db.record_trial(trial2)

        # Switch back to main
        self.repo.switch_branch("main")

        # Evaluate in Tournament
        scorecards = self.tourn.evaluate_candidates(["candidate-gemini", "candidate-slow"])
        self.assertEqual(len(scorecards), 2)
        # Winner must be candidate-gemini (rank #1) due to higher score and lower token cost
        self.assertEqual(scorecards[0].trial_name, "candidate-gemini")
        self.assertEqual(scorecards[0].rank, 1)

        # Auto-promote winner
        merged_cp = self.tourn.promote_winner(scorecards)
        self.assertIsNotNone(merged_cp)
        self.assertEqual(self.repo.get_active_branch(), "main")

        # Verify main branch contains the winner's code
        content = (self.temp_dir / "math_ops.py").read_text(encoding="utf-8")
        self.assertIn("Fast solution", content)


if __name__ == "__main__":
    unittest.main()
