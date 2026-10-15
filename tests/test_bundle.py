"""Unit tests for BundleManager."""

import shutil
import tempfile
from pathlib import Path
import unittest

from cognit.core.bundle import BundleManager
from cognit.core.models import AgentMetadata
from cognit.core.repo import CognitRepo


class TestBundle(unittest.TestCase):
    def setUp(self):
        self.temp_dir_a = Path(tempfile.mkdtemp())
        self.temp_dir_b = Path(tempfile.mkdtemp())
        self.repo_a = CognitRepo.init(self.temp_dir_a, default_branch="main")
        self.repo_b = CognitRepo.init(self.temp_dir_b, default_branch="main")

    def tearDown(self):
        shutil.rmtree(self.temp_dir_a, ignore_errors=True)
        shutil.rmtree(self.temp_dir_b, ignore_errors=True)

    def test_bundle_pack_and_unpack(self):
        # 1. Create file and checkpoint in Repo A
        (self.temp_dir_a / "package.json").write_text('{"name": "agent-app"}', encoding="utf-8")
        cp = self.repo_a.create_checkpoint(
            "Initial app setup",
            author="DevAgent",
            agent_metadata=AgentMetadata(
                agent_id="agent-bundler",
                model="gemini-3.8-flash",
                goal="Package creation",
            )
        )

        bundle_file = self.temp_dir_a / "export.cgb"
        bm_a = BundleManager(self.repo_a)
        packed_count = bm_a.create_bundle(bundle_file, branch_name="main")
        self.assertEqual(packed_count, 1)
        self.assertTrue(bundle_file.is_file())

        # 2. Apply bundle into Repo B
        bm_b = BundleManager(self.repo_b)
        res = bm_b.apply_bundle(bundle_file)
        self.assertEqual(res["branch"], "main")
        self.assertEqual(res["head_checkpoint"], cp.id)

        # 3. Check Repo B now has the checkpoint object
        retrieved_cp = self.repo_b.storage.read_checkpoint(cp.id)
        self.assertEqual(retrieved_cp.message, "Initial app setup")
        self.assertEqual(retrieved_cp.agent_metadata.agent_id, "agent-bundler")


if __name__ == "__main__":
    unittest.main()
