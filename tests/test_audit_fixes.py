"""Comprehensive regression and edge-case unit tests for bug audit fixes."""

import tempfile
import unittest
from pathlib import Path

from cognit.core.models import Checkpoint, Symbol, SpeculativeTrial, AgentMetadata
from cognit.core.storage import ObjectStorage
from cognit.core.database import Database
from cognit.core.repo import CognitRepo
from cognit.semantic.parser import ASTParser
from cognit.semantic.semantic_merge import SemanticMerger
from cognit.agentic.workspace import AgentWorkspace
from cognit.agentic.recorder import MicroSnapshot


class TestAuditFixes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp_dir.name)
        self.repo = CognitRepo.init(self.root_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_short_hash_and_ref_resolution(self):
        """Test resolving HEAD, HEAD~1, branch names, and short hashes."""
        # Checkpoint 1
        (self.root_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        cp1 = self.repo.create_checkpoint("Commit 1")

        # Checkpoint 2
        (self.root_path / "app.py").write_text("x = 2\n", encoding="utf-8")
        cp2 = self.repo.create_checkpoint("Commit 2")

        # 1. Resolve HEAD
        self.assertEqual(self.repo.resolve_ref("HEAD"), cp2.id)

        # 2. Resolve HEAD~1
        self.assertEqual(self.repo.resolve_ref("HEAD~1"), cp1.id)

        # 3. Resolve branch name
        self.assertEqual(self.repo.resolve_ref("main"), cp2.id)

        # 4. Resolve short-hash (e.g. 7 characters)
        short_cp1 = cp1.id[:7]
        self.assertEqual(self.repo.resolve_ref(short_cp1), cp1.id)

        short_cp2 = cp2.id[:8]
        self.assertEqual(self.repo.resolve_ref(short_cp2), cp2.id)

        # 5. Storage read with short-hash
        read_cp = self.repo.storage.read_checkpoint(short_cp1)
        self.assertEqual(read_cp.id, cp1.id)
        self.assertEqual(read_cp.message, "Commit 1")

        # 6. Database get_checkpoint with short-hash
        db_cp = self.repo.db.get_checkpoint(short_cp2)
        self.assertIsNotNone(db_cp)
        self.assertEqual(db_cp.id, cp2.id)

    def test_time_travel_with_short_hash(self):
        """Test time_travel using short hash and HEAD~1."""
        (self.root_path / "data.txt").write_text("v1\n", encoding="utf-8")
        cp1 = self.repo.create_checkpoint("First version")

        (self.root_path / "data.txt").write_text("v2\n", encoding="utf-8")
        cp2 = self.repo.create_checkpoint("Second version")

        # Restore using short hash
        short_id = cp1.id[:8]
        restored_cp = self.repo.time_travel(short_id)
        self.assertEqual(restored_cp.id, cp1.id)
        self.assertEqual((self.root_path / "data.txt").read_text(encoding="utf-8"), "v1\n")

    def test_diff_checkpoints_direct(self):
        """Test direct 2-checkpoint diffing without working directory dependency."""
        (self.root_path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        cp1 = self.repo.create_checkpoint("Add add function")

        (self.root_path / "calc.py").write_text("def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n", encoding="utf-8")
        cp2 = self.repo.create_checkpoint("Add sub function")

        # Diff directly between cp1 and cp2 using short hashes
        diffs = self.repo.diff_checkpoints(cp1.id[:8], cp2.id[:8])
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].file_path, "calc.py")
        self.assertGreater(diffs[0].total_added, 0)

    def test_multi_symbol_reverse_splicing(self):
        """Test semantic merge splicing with multiple non-colliding symbols at different line offsets."""
        base = (
            "def alpha():\n    return 1\n\n"
            "def beta():\n    return 2\n\n"
            "def gamma():\n    return 3\n"
        )
        # Ours modifies alpha (line 1)
        ours = (
            "def alpha():\n    return 'changed_by_ours'\n\n"
            "def beta():\n    return 2\n\n"
            "def gamma():\n    return 3\n"
        )
        # Theirs modifies gamma (line 7) and beta (line 4)
        theirs = (
            "def alpha():\n    return 1\n\n"
            "def beta():\n    # new docstring\n    return 200\n\n"
            "def gamma():\n    return 'changed_by_theirs_with_multiple_lines'\n    # extra line\n"
        )

        res = SemanticMerger.merge_files("service.py", base, ours, theirs)
        self.assertTrue(res.clean)
        self.assertIn("'changed_by_ours'", res.merged_content)
        self.assertIn("200", res.merged_content)
        self.assertIn("'changed_by_theirs_with_multiple_lines'", res.merged_content)

    def test_javascript_ast_brace_matching_and_body_hash(self):
        """Verify that changes inside JS function bodies change body_hash and end_line is accurate."""
        code1 = "function calculateTotal(items) {\n    const sum = items.reduce((a, b) => a + b, 0);\n    return sum;\n}"
        code2 = "function calculateTotal(items) {\n    const sum = items.reduce((a, b) => a + b, 0);\n    console.log('debug');\n    return sum * 1.1;\n}"

        syms1 = ASTParser.parse_javascript(code1)
        syms2 = ASTParser.parse_javascript(code2)

        self.assertEqual(len(syms1), 1)
        self.assertEqual(len(syms2), 1)

        s1 = syms1[0]
        s2 = syms2[0]

        # Verify end line computed
        self.assertEqual(s1.start_line, 1)
        self.assertEqual(s1.end_line, 4)
        self.assertEqual(s2.start_line, 1)
        self.assertEqual(s2.end_line, 5)

        # Body hash must differ because function body changed!
        self.assertNotEqual(s1.body_hash, s2.body_hash)

    def test_go_ast_brace_matching(self):
        """Verify that Go function block bounds and body hash are correctly extracted."""
        code = (
            "package main\n\n"
            "func Add(a int, b int) int {\n"
            "    res := a + b\n"
            "    return res\n"
            "}\n"
        )
        syms = ASTParser.parse_go(code)
        self.assertEqual(len(syms), 1)
        s = syms[0]
        self.assertEqual(s.name, "Add")
        self.assertEqual(s.start_line, 3)
        self.assertEqual(s.end_line, 6)

    def test_defensive_from_dict_with_unexpected_keys(self):
        """Verify dataclasses don't crash when JSON contains extra unrecognized fields."""
        sym = Symbol.from_dict({"name": "foo", "kind": "function", "unexpected_field_123": True})
        self.assertEqual(sym.name, "foo")

        trial = SpeculativeTrial.from_dict({
            "name": "trial_1",
            "base_checkpoint_id": "abc",
            "current_checkpoint_id": "def",
            "future_schema_field": 42,
        })
        self.assertEqual(trial.name, "trial_1")

        snap = MicroSnapshot.from_dict({
            "step_index": 5,
            "extra_analytics": {"cpu": 90},
        })
        self.assertEqual(snap.step_index, 5)

        ws = AgentWorkspace.from_dict({
            "agent_id": "agent-007",
            "branch_name": "agents/007",
            "workspace_dir": "/tmp/ws",
            "extra_meta": "test",
        })
        self.assertEqual(ws.agent_id, "agent-007")

    def test_path_traversal_prevention_in_branches_and_tags(self):
        """Verify that branch and tag operations reject path traversal strings."""
        (self.root_path / "file.txt").write_text("content\n", encoding="utf-8")
        self.repo.create_checkpoint("Initial commit")

        # Test branch name traversal
        with self.assertRaises(ValueError):
            self.repo.create_branch("../../evil_branch")

        with self.assertRaises(ValueError):
            self.repo.set_branch_checkpoint("../../../outside", "some_cid")

        with self.assertRaises(ValueError):
            self.repo.switch_branch("../escape")

        # Test invalid negative relative reference
        with self.assertRaises(ValueError):
            self.repo.resolve_ref("HEAD~-1")

    def test_storage_hash_security_validation(self):
        """Verify object storage rejects non-hex and path-traversing hashes."""
        with self.assertRaises(ValueError):
            self.repo.storage._object_path("../../etc/passwd")

        with self.assertRaises(ValueError):
            self.repo.storage._object_path("invalid!hash!123")

        self.assertFalse(self.repo.storage.has_object("../../etc/passwd"))
        self.assertIsNone(self.repo.storage.find_object_by_prefix("../escape"))

    def test_workspace_manager_path_traversal_prevention(self):
        """Verify WorkspaceManager rejects agent_id containing traversal characters."""
        from cognit.agentic.workspace import WorkspaceManager
        (self.root_path / "app.py").write_text("x = 10\n", encoding="utf-8")
        self.repo.create_checkpoint("Base commit")

        wm = WorkspaceManager(self.repo)
        with self.assertRaises(ValueError):
            wm.create_workspace("../../attacker_agent")

        with self.assertRaises(ValueError):
            wm.create_workspace("/absolute/agent")

    def test_disjoint_class_methods_semantic_merge(self):
        """Verify that two agents modifying different methods of the same class merge cleanly without false conflict."""
        base_code = (
            "class BankAccount:\n"
            "    def __init__(self):\n"
            "        self.balance = 0\n"
            "\n"
            "    def deposit(self, amount):\n"
            "        self.balance += amount\n"
            "\n"
            "    def withdraw(self, amount):\n"
            "        self.balance -= amount\n"
        )
        # Agent A improves deposit validation
        ours_code = (
            "class BankAccount:\n"
            "    def __init__(self):\n"
            "        self.balance = 0\n"
            "\n"
            "    def deposit(self, amount):\n"
            "        if amount <= 0:\n"
            "            raise ValueError('Must be positive')\n"
            "        self.balance += amount\n"
            "\n"
            "    def withdraw(self, amount):\n"
            "        self.balance -= amount\n"
        )
        # Agent B improves withdraw overdraft check
        theirs_code = (
            "class BankAccount:\n"
            "    def __init__(self):\n"
            "        self.balance = 0\n"
            "\n"
            "    def deposit(self, amount):\n"
            "        self.balance += amount\n"
            "\n"
            "    def withdraw(self, amount):\n"
            "        if amount > self.balance:\n"
            "            raise ValueError('Insufficient funds')\n"
            "        self.balance -= amount\n"
        )

        res = SemanticMerger.merge_files("account.py", base_code, ours_code, theirs_code)
        self.assertTrue(res.clean, f"Expected clean disjoint method merge, got conflicts: {res.conflicts}")
        self.assertIn("Must be positive", res.merged_content)
        self.assertIn("Insufficient funds", res.merged_content)


if __name__ == "__main__":
    unittest.main()
