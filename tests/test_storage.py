"""Unit tests for content-addressable ObjectStorage."""

import shutil
import tempfile
from pathlib import Path
import unittest

from cognit.core.models import Checkpoint, TreeEntry, AgentMetadata
from cognit.core.storage import ObjectStorage


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.storage = ObjectStorage(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_write_and_read_blob(self):
        data = b"Hello, Agent World! Content addressable bytes."
        blob_hash = self.storage.write_blob(data)
        self.assertTrue(self.storage.has_object(blob_hash))

        retrieved = self.storage.read_blob(blob_hash)
        self.assertEqual(retrieved, data)

    def test_write_and_read_tree(self):
        entries = [
            TreeEntry(path="src/main.py", blob_hash="abc12345", size=100),
            TreeEntry(path="README.md", blob_hash="def67890", size=50),
        ]
        tree_hash = self.storage.write_tree(entries)
        self.assertTrue(self.storage.has_object(tree_hash))

        retrieved = self.storage.read_tree(tree_hash)
        self.assertEqual(len(retrieved), 2)
        # Verify sorted deterministically
        self.assertEqual(retrieved[0].path, "README.md")
        self.assertEqual(retrieved[1].path, "src/main.py")

    def test_write_and_read_checkpoint(self):
        cp = Checkpoint(
            id="",
            parent_ids=["parent_1"],
            tree_hash="tree_hash_1",
            author="Agent Coder",
            message="Initial commit",
            agent_metadata=AgentMetadata(
                agent_id="agent-01",
                model="gemini-3.8-flash",
                goal="Set up repo",
                tokens_used=120,
            ),
        )
        cp_hash = self.storage.write_checkpoint(cp)
        self.assertTrue(self.storage.has_object(cp_hash))

        retrieved = self.storage.read_checkpoint(cp_hash)
        self.assertEqual(retrieved.id, cp_hash)
        self.assertEqual(retrieved.message, "Initial commit")
        self.assertEqual(retrieved.agent_metadata.model, "gemini-3.8-flash")
        self.assertEqual(retrieved.agent_metadata.tokens_used, 120)


if __name__ == "__main__":
    unittest.main()
