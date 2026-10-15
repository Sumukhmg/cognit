"""Unit tests for Cognit CLI commands and JSON output."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.cli_path = Path(__file__).parent.parent / "cognit" / "cli.py"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def run_cmd(self, *args):
        import os
        project_root = Path(__file__).parent.parent
        cmd = ["python", str(self.cli_path)] + list(args)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(project_root)
        return subprocess.run(cmd, cwd=str(self.temp_dir), capture_output=True, text=True, env=env)

    def test_cli_init_and_status_json(self):
        # Init
        res = self.run_cmd("init", "--json")
        self.assertEqual(res.returncode, 0, f"Error: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["data"]["branch"], "main")

        # Create a file
        (self.temp_dir / "index.js").write_text("function main() { return 1; }", encoding="utf-8")

        # Status JSON
        res = self.run_cmd("status", "--json")
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data["status"], "ok")
        files = data["data"]["files"]
        idx_file = next(f for f in files if f["path"] == "index.js")
        self.assertEqual(idx_file["status"], "added")

        # Checkpoint JSON
        res = self.run_cmd(
            "checkpoint", "-m", "Add index.js",
            "--model", "gemini-3.8-flash",
            "--goal", "Initialize frontend entry",
            "--tokens", "100",
            "--json"
        )
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["data"]["message"], "Add index.js")
        self.assertEqual(data["data"]["agent_metadata"]["model"], "gemini-3.8-flash")

        # Log JSON
        res = self.run_cmd("log", "--json")
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["message"], "Add index.js")


if __name__ == "__main__":
    unittest.main()
