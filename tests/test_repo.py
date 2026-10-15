"""Unit tests for CognitRepo core functionality."""

import shutil
import tempfile
from pathlib import Path
import unittest

from cognit.core.models import AgentMetadata
from cognit.core.repo import CognitRepo


class TestRepo(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.repo = CognitRepo.init(self.temp_dir, default_branch="main")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init(self):
        self.assertTrue((self.temp_dir / ".cognit").is_dir())
        self.assertTrue((self.temp_dir / ".cognit" / "objects").is_dir())
        self.assertEqual(self.repo.get_active_branch(), "main")
        self.assertIsNone(self.repo.get_head_checkpoint())

    def test_checkpoint_and_status(self):
        # Create a sample file
        test_file = self.temp_dir / "app.py"
        test_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

        # Check status before checkpoint: app.py should be added
        st = self.repo.status()
        app_st = next(s for s in st if s.path == "app.py")
        self.assertEqual(app_st.status, "added")

        # Commit checkpoint with agent metadata
        cp = self.repo.create_checkpoint(
            message="Add hello function",
            author="Agent Coder",
            agent_metadata=AgentMetadata(
                agent_id="coder-1",
                model="gemini-3.8-flash",
                goal="Create greeting utility",
                test_status="passed",
                tokens_used=150,
            ),
        )

        self.assertIsNotNone(cp.id)
        self.assertEqual(cp.branch, "main")
        self.assertEqual(self.repo.get_head_checkpoint_id(), cp.id)

        # Status after checkpoint: app.py should be unmodified
        st = self.repo.status()
        app_st = next(s for s in st if s.path == "app.py")
        self.assertEqual(app_st.status, "unmodified")

        # Modify the file
        test_file.write_text("def hello():\n    return 'agent world'\n", encoding="utf-8")
        st = self.repo.status()
        app_st = next(s for s in st if s.path == "app.py")
        self.assertEqual(app_st.status, "modified")
        self.assertIn("hello", app_st.symbols_changed)

    def test_branches_and_time_travel(self):
        file_a = self.temp_dir / "file_a.txt"
        file_a.write_text("Version 1", encoding="utf-8")
        cp1 = self.repo.create_checkpoint("First commit")

        # Create feature branch
        self.repo.create_branch("feature/exp")
        self.repo.switch_branch("feature/exp")
        self.assertEqual(self.repo.get_active_branch(), "feature/exp")

        # Commit change on feature branch
        file_a.write_text("Version 2 on feature", encoding="utf-8")
        cp2 = self.repo.create_checkpoint("Feature commit")

        self.assertEqual(file_a.read_text(), "Version 2 on feature")

        # Switch back to main
        self.repo.switch_branch("main")
        self.assertEqual(self.repo.get_active_branch(), "main")
        self.assertEqual(file_a.read_text(), "Version 1")

        # Time travel to cp2
        self.repo.time_travel(cp2.id)
        self.assertEqual(file_a.read_text(), "Version 2 on feature")

        # Undo back to cp1
        undo_cp = self.repo.undo()
        self.assertIsNotNone(undo_cp)
        self.assertEqual(undo_cp.id, cp1.id)
        self.assertEqual(file_a.read_text(), "Version 1")


if __name__ == "__main__":
    unittest.main()
