"""Unit tests for DependencyGraph and change impact analysis."""

import shutil
import tempfile
from pathlib import Path
import unittest

from cognit.core.repo import CognitRepo
from cognit.semantic.graph import DependencyGraph


class TestGraph(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.repo = CognitRepo.init(self.temp_dir, default_branch="main")

        # Create module A (utils)
        (self.temp_dir / "utils.py").write_text("""
def hash_string(text: str) -> str:
    \"\"\"Compute hash of text.\"\"\"
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()
""", encoding="utf-8")

        # Create module B (auth imports utils)
        (self.temp_dir / "auth.py").write_text("""
import utils

def login(user, password):
    pwd_hash = utils.hash_string(password)
    return True
""", encoding="utf-8")

        # Create test file
        (self.temp_dir / "test_auth.py").write_text("""
import auth

def test_login():
    assert auth.login('admin', '123')
""", encoding="utf-8")

        self.repo.create_checkpoint("Setup graph test repo")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_impact_analysis(self):
        graph = DependencyGraph(self.temp_dir, self.repo)
        graph.build_graph()

        report = graph.analyze_impact("utils.py")
        self.assertIn("auth.py", report.direct_dependents)
        self.assertIn("test_auth.py", report.transitive_dependents)
        self.assertIn("test_auth.py", report.affected_tests)

    def test_compact_context(self):
        graph = DependencyGraph(self.temp_dir, self.repo)
        graph.build_graph()

        ctx = graph.build_compact_context("hash_string login", max_tokens=1000)
        self.assertIn("hash_string", ctx)
        self.assertIn("login", ctx)


if __name__ == "__main__":
    unittest.main()
