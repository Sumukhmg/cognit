"""Unit tests for ExplainEngine lineage tracing."""

import shutil
import tempfile
from pathlib import Path
import unittest

from cognit.agentic.explain import ExplainEngine
from cognit.core.models import AgentMetadata
from cognit.core.repo import CognitRepo


class TestExplain(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.repo = CognitRepo.init(self.temp_dir, default_branch="main")
        self.explain = ExplainEngine(self.repo.db, self.repo)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_explain_symbol_lineage(self):
        app_file = self.temp_dir / "calc.py"
        app_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        self.repo.create_checkpoint(
            "Initial add func",
            agent_metadata=AgentMetadata(
                agent_id="coder-alpha",
                model="gemini-3.8-flash",
                goal="Implement basic arithmetic",
                reasoning="Standard addition",
                test_status="passed",
            )
        )

        # Second revision
        app_file.write_text("def add(a, b):\n    # Support numeric conversion\n    return float(a) + float(b)\n", encoding="utf-8")
        self.repo.create_checkpoint(
            "Enhance add with float coercion",
            agent_metadata=AgentMetadata(
                agent_id="coder-beta",
                model="gpt-4o",
                goal="Handle string numbers cleanly",
                reasoning="Cast to float to prevent TypeError",
                test_status="passed",
                tokens_used=220,
            )
        )

        lineage = self.explain.explain_symbol("calc.py", "add")
        self.assertEqual(len(lineage), 2)
        # Most recent first
        self.assertEqual(lineage[0].agent_id, "coder-beta")
        self.assertEqual(lineage[0].model, "gpt-4o")
        self.assertEqual(lineage[0].goal, "Handle string numbers cleanly")

        self.assertEqual(lineage[1].agent_id, "coder-alpha")
        self.assertEqual(lineage[1].model, "gemini-3.8-flash")


if __name__ == "__main__":
    unittest.main()
