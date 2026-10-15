"""Unit tests for ConflictResolver."""

import shutil
import tempfile
from pathlib import Path
import unittest

from cognit.agentic.resolver import ConflictResolver
from cognit.core.repo import CognitRepo
from cognit.semantic.semantic_merge import ConflictDetail


class TestResolver(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.repo = CognitRepo.init(self.temp_dir, default_branch="main")
        self.resolver = ConflictResolver(self.repo)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generate_synthesis_prompt(self):
        conflict = ConflictDetail(
            file_path="service.py",
            symbol_name="authenticate",
            kind="function",
            base_snippet="def authenticate(user): pass",
            ours_snippet="def authenticate(user):\n    # Added JWT\n    return verify_jwt(user)",
            theirs_snippet="def authenticate(user):\n    # Added OAuth\n    return verify_oauth(user)",
            reason="Concurrent modifications by two agents",
        )

        prompt = self.resolver.generate_synthesis_prompt(
            conflict,
            goal_a="Add JWT validation",
            goal_b="Add OAuth2 SSO",
        )

        self.assertIn("COGNIT AUTONOMOUS CONFLICT RESOLUTION", prompt)
        self.assertIn("authenticate", prompt)
        self.assertIn("Add JWT validation", prompt)
        self.assertIn("Add OAuth2 SSO", prompt)

    def test_auto_resolve_imports(self):
        conflict = ConflictDetail(
            file_path="app.py",
            symbol_name="import_1",
            kind="import",
            base_snippet="import os",
            ours_snippet="import os\nimport sys",
            theirs_snippet="import os\nimport math",
            reason="Both branches added imports",
        )

        resolved = self.resolver.try_auto_resolve(conflict)
        self.assertIsNotNone(resolved)
        self.assertIn("import math", resolved)
        self.assertIn("import sys", resolved)
        self.assertIn("import os", resolved)


if __name__ == "__main__":
    unittest.main()
