"""Portable offline archive bundle manager for Cognit repositories."""

from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from cognit.core.models import Checkpoint, TreeEntry


class BundleManager:
    """Creates and applies portable .cgb archive bundles."""

    def __init__(self, repo: Any) -> None:
        self.repo = repo

    def create_bundle(
        self,
        output_bundle_path: Path | str,
        branch_name: Optional[str] = None,
        max_checkpoints: int = 100,
    ) -> int:
        """Package a branch and its object history into a portable compressed bundle."""
        target_branch = branch_name or self.repo.get_active_branch()
        head_cid = self.repo.get_branch_checkpoint(target_branch)
        if not head_cid:
            raise ValueError(f"Branch '{target_branch}' has no checkpoints.")

        out_path = Path(output_bundle_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Collect checkpoints along ancestry
        checkpoints: List[Checkpoint] = []
        objects_to_pack: Dict[str, bytes] = {}

        queue = [head_cid]
        visited_cids = set()

        while queue and len(checkpoints) < max_checkpoints:
            curr = queue.pop(0)
            if curr in visited_cids:
                continue
            visited_cids.add(curr)

            cp = self.repo.storage.read_checkpoint(curr)
            checkpoints.append(cp)

            # Read raw checkpoint object
            obj_type, cp_raw = self.repo.storage.read_raw(curr)
            objects_to_pack[f"checkpoint_{curr}"] = cp_raw

            # Read tree
            tree_hash = cp.tree_hash
            obj_type, tree_raw = self.repo.storage.read_raw(tree_hash)
            objects_to_pack[f"tree_{tree_hash}"] = tree_raw

            # Read blobs in tree
            tree_entries = self.repo.storage.read_tree(tree_hash)
            for entry in tree_entries:
                key = f"blob_{entry.blob_hash}"
                if key not in objects_to_pack:
                    obj_type, blob_raw = self.repo.storage.read_raw(entry.blob_hash)
                    objects_to_pack[key] = blob_raw

            queue.extend(cp.parent_ids)

        # Create tar.gz bundle
        manifest = {
            "version": "1.0",
            "branch": target_branch,
            "head_checkpoint": head_cid,
            "checkpoints_count": len(checkpoints),
            "objects_count": len(objects_to_pack),
            "checkpoint_ids": [c.id for c in checkpoints],
        }

        with tarfile.open(str(out_path), "w:gz") as tar:
            # Add manifest
            manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
            ti = tarfile.TarInfo(name="manifest.json")
            ti.size = len(manifest_bytes)
            tar.addfile(ti, BytesIO(manifest_bytes))

            # Add objects
            for obj_key, raw_data in objects_to_pack.items():
                ti = tarfile.TarInfo(name=f"objects/{obj_key}")
                ti.size = len(raw_data)
                tar.addfile(ti, BytesIO(raw_data))

        return len(checkpoints)

    def apply_bundle(self, bundle_path: Path | str) -> Dict[str, Any]:
        """Import all checkpoints and objects from a bundle into current repo."""
        b_path = Path(bundle_path)
        if not b_path.is_file():
            raise FileNotFoundError(f"Bundle file '{b_path}' not found.")

        with tarfile.open(str(b_path), "r:gz") as tar:
            # Read manifest
            manifest_file = tar.extractfile("manifest.json")
            if not manifest_file:
                raise ValueError("Corrupt bundle: missing manifest.json")
            manifest = json.loads(manifest_file.read().decode("utf-8"))

            branch = manifest["branch"]
            head_cid = manifest["head_checkpoint"]
            cp_ids = manifest.get("checkpoint_ids", [head_cid])

            # Unpack objects directly into storage
            imported_objs = 0
            for member in tar.getmembers():
                if member.isfile() and member.name.startswith("objects/"):
                    parts = member.name.split("/", 1)
                    if len(parts) > 1 and "_" in parts[1]:
                        filename = parts[1]
                        obj_type, _ = filename.split("_", 1)
                        f = tar.extractfile(member)
                        if f:
                            raw_data = f.read()
                            self.repo.storage.write_raw(obj_type, raw_data)
                            imported_objs += 1

            # Register checkpoints in SQLite
            for cid in cp_ids:
                if self.repo.storage.has_object(cid):
                    cp = self.repo.storage.read_checkpoint(cid)
                    self.repo.db.record_checkpoint(cp)

            self.repo.set_branch_checkpoint(branch, head_cid)

        return {
            "branch": branch,
            "head_checkpoint": head_cid,
            "objects_imported": imported_objs,
        }
