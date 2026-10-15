"""Unit tests for AST-aware SemanticMerger and SemanticDiffer."""

import unittest

from cognit.semantic.parser import ASTParser
from cognit.semantic.semantic_diff import SemanticDiffer
from cognit.semantic.semantic_merge import SemanticMerger


class TestSemanticMerge(unittest.TestCase):
    def test_ast_parser_python(self):
        code = """
import os

def calculate_tax(amount, rate):
    \"\"\"Calculate tax on amount.\"\"\"
    return amount * rate

class Account:
    def deposit(self, val):
        self.balance += val
"""
        symbols = ASTParser.parse_python(code)
        sym_names = [s.name for s in symbols]
        self.assertIn("calculate_tax", sym_names)
        self.assertIn("Account", sym_names)
        self.assertIn("Account.deposit", sym_names)

        tax_sym = next(s for s in symbols if s.name == "calculate_tax")
        self.assertEqual(tax_sym.kind, "function")
        self.assertEqual(tax_sym.docstring, "Calculate tax on amount.")

    def test_semantic_diff(self):
        old_code = """
def process(data):
    return data.strip()
"""
        new_code = """
def process(data):
    # Added lowercase normalization
    return data.strip().lower()

def validate(data):
    return len(data) > 0
"""
        res = SemanticDiffer.diff_content("utils.py", old_code, new_code)
        self.assertEqual(len(res.symbol_diffs), 2)

        proc_diff = next(s for s in res.symbol_diffs if s.name == "process")
        self.assertEqual(proc_diff.change_type, "modified")

        val_diff = next(s for s in res.symbol_diffs if s.name == "validate")
        self.assertEqual(val_diff.change_type, "added")

    def test_clean_disjoint_semantic_merge(self):
        """Simulate two agents working on separate functions in the same file.
        In Git this often causes conflict markers. In Cognit this merges cleanly!
        """
        base_code = """
def service_status():
    return "ok"
"""
        # Agent A adds function auth_user
        ours_code = """
def service_status():
    return "ok"

def auth_user(token):
    return token == "secret"
"""
        # Agent B adds function log_audit
        theirs_code = """
def service_status():
    return "ok"

def log_audit(event):
    print("AUDIT:", event)
"""
        res = SemanticMerger.merge_files("service.py", base_code, ours_code, theirs_code)
        self.assertTrue(res.clean, f"Expected clean merge, got conflicts: {res.conflicts}")
        self.assertIn("def auth_user", res.merged_content)
        self.assertIn("def log_audit", res.merged_content)
        self.assertIn("def service_status", res.merged_content)

    def test_conflicting_symbol_merge(self):
        """Simulate two agents modifying the SAME function with differing logic."""
        base_code = """
def calculate_discount(price):
    return price * 0.05
"""
        # Agent A changes discount to 10%
        ours_code = """
def calculate_discount(price):
    return price * 0.10
"""
        # Agent B changes discount to 20%
        theirs_code = """
def calculate_discount(price):
    return price * 0.20
"""
        res = SemanticMerger.merge_files("pricing.py", base_code, ours_code, theirs_code)
        self.assertFalse(res.clean)
        self.assertEqual(len(res.conflicts), 1)
        self.assertEqual(res.conflicts[0].symbol_name, "calculate_discount")
        self.assertIn("CONFLICT: calculate_discount", res.merged_content)


if __name__ == "__main__":
    unittest.main()
