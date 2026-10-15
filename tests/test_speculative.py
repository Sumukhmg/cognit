"""Unit tests for agent speculative trial management."""

import shutil
import tempfile
from pathlib import Path
import unittest

from cognit.agentic.speculative import SpeculativeManager
from cognit.core.models import AgentMetadata
from cognit.core.repo import CognitRepo


class TestSpeculative(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.repo = CognitRepo.init(self.temp_dir, default_branch="main")
        # Initial commit
        (self.temp_dir / "app.py").write_text("def base(): pass\n", encoding="utf-8")
        self.base_cp = self.repo.create_checkpoint("Initial commit")
        self.spec = SpeculativeManager(self.repo.db, self.repo)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_trial_lifecycle(self):
        # 1. Start trial
        trial = self.spec.start_trial("trial-optimization")
        self.assertEqual(trial.name, "trial-optimization")
        self.assertEqual(trial.status, "active")

        # Switch to trial branch and make experimental change
        self.repo.switch_branch("speculative/trial-optimization")
        (self.temp_dir / "app.py").write_text("def base(): pass\ndef optimized(): return 42\n", encoding="utf-8")
        self.repo.create_checkpoint(
            "Experiment: add optimized func",
            agent_metadata=AgentMetadata(
                agent_id="optimizer-agent",
                model="gemini-3.8-flash",
                goal="Improve performance",
            )
        )

        # 2. Evaluate trial with synthetic score
        eval_trial = self.spec.evaluate_trial("trial-optimization", score=0.95, notes="Passed benchmark with 3x speedup")
        self.assertEqual(eval_trial.score, 0.95)

        # Switch back to main
        self.repo.switch_branch("main")

        # 3. Accept trial
        merged_cp = self.spec.accept_trial("trial-optimization")
        self.assertIsNotNone(merged_cp)
        self.assertEqual(self.spec.db.get_trial("trial-optimization").status, "accepted")

        # Verify main has the optimized function now!
        content = (self.temp_dir / "app.py").read_text(encoding="utf-8")
        self.assertIn("def optimized", content)

    def test_discard_trial(self):
        self.spec.start_trial("trial-deadend")
        disc = self.spec.discard_trial("trial-deadend", reason="Did not pass unit tests")
        self.assertEqual(disc.status, "discarded")
        self.assertIn("Did not pass unit tests", disc.evaluation_notes)


if __name__ == "__main__":
    unittest.main()
