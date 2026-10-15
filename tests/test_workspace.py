"""Unit tests for WorkspaceManager."""

import shutil
import tempfile
from pathlib import Path
import unittest

from cognit.agentic.workspace import WorkspaceManager
from cognit.core.models import AgentMetadata
from cognit.core.repo import CognitRepo


class TestWorkspace(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.repo = CognitRepo.init(self.temp_dir, default_branch="main")
        (self.temp_dir / "app.py").write_text("print('base')\n", encoding="utf-8")
        self.repo.create_checkpoint("Initial commit")
        self.wm = WorkspaceManager(self.repo)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_workspace_isolation_and_commit(self):
        # Create workspace for agent-alpha
        ws = self.wm.create_workspace("agent-alpha")
        self.assertEqual(ws.agent_id, "agent-alpha")
        ws_path = Path(ws.workspace_dir)
        self.assertTrue((ws_path / "app.py").is_file())

        # Modify app.py in isolated workspace
        (ws_path / "app.py").write_text("print('agent-alpha modification')\n", encoding="utf-8")

        # Main working tree is still 'base' (isolated!)
        self.assertEqual((self.temp_dir / "app.py").read_text(), "print('base')\n")

        # Commit from workspace
        cp = self.wm.commit_workspace(
            "agent-alpha",
            message="Feature from agent alpha",
            metadata=AgentMetadata(
                agent_id="agent-alpha",
                model="gemini-3.8-flash",
                goal="Isolate work",
            )
        )

        self.assertIsNotNone(cp.id)
        self.assertEqual(cp.branch, ws.branch_name)

        # Destroy workspace
        destroyed = self.wm.destroy_workspace("agent-alpha")
        self.assertTrue(destroyed)
        self.assertFalse(ws_path.exists())


if __name__ == "__main__":
    unittest.main()
