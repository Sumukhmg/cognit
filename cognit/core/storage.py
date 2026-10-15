"""Content-addressable object storage for Cognit using SHA-256 and zlib."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zlib
from pathlib import Path
from typing import List, Optional, Tuple

from cognit.core.models import Checkpoint, TreeEntry


class ObjectStorage:
    """Manages immutable, content-addressed objects under .cognit/objects/"""

    def __init__(self, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir)
        self.objects_dir = self.root_dir / ".cognit" / "objects"
        self.objects_dir.mkdir(parents=True, exist_ok=True)

    def _object_path(self, sha256_hash: str) -> Path:
        """Return the directory and file path for a given SHA-256 hash."""
        clean = sha256_hash.strip().lower()
        if not clean or not all(c in "0123456789abcdef" for c in clean):
            raise ValueError(f"Invalid object hash '{sha256_hash}': must be valid hexadecimal.")
        prefix = clean[:2]
        suffix = clean[2:]
        return self.objects_dir / prefix / suffix

    def has_object(self, sha256_hash: str) -> bool:
        """Check if an object exists in storage."""
        if not sha256_hash:
            return False
        clean = sha256_hash.strip().lower()
        if not all(c in "0123456789abcdef" for c in clean):
            return False
        if len(clean) == 64:
            return self._object_path(clean).is_file()
        return self.find_object_by_prefix(clean) is not None

    def find_object_by_prefix(self, prefix: str) -> Optional[str]:
        """Find full 64-char object hash by prefix (minimum 4 chars)."""
        if not prefix:
            return None
        clean_p = prefix.strip().lower()
        if not all(c in "0123456789abcdef" for c in clean_p):
            return None
        if len(clean_p) == 64:
            return clean_p if self._object_path(clean_p).is_file() else None
        if len(clean_p) < 4:
            return None

        dir_path = self.objects_dir / clean_p[:2]
        if not dir_path.is_dir():
            return None

        suffix_prefix = clean_p[2:]
        matches = [
            p.name for p in dir_path.iterdir()
            if p.is_file() and p.name.startswith(suffix_prefix)
        ]
        if len(matches) == 1:
            return clean_p[:2] + matches[0]
        elif len(matches) > 1:
            raise ValueError(f"Ambiguous object prefix '{clean_p}': matches {len(matches)} objects.")
        return None

    def write_raw(self, obj_type: str, payload: bytes) -> str:
        """Write a typed object with header, compute SHA-256, compress, and store atomically."""
        header = f"{obj_type} {len(payload)}\x00".encode("utf-8")
        full_content = header + payload
        sha256_hash = hashlib.sha256(full_content).hexdigest()

        target_path = self._object_path(sha256_hash)
        if target_path.exists():
            return sha256_hash  # Already stored, deduplicated!

        target_path.parent.mkdir(parents=True, exist_ok=True)
        compressed = zlib.compress(full_content, level=6)

        # Atomic write via temporary file
        temp_dir = self.root_dir / ".cognit" / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=temp_dir, delete=False) as tf:
            tf.write(compressed)
            temp_name = tf.name

        try:
            os.replace(temp_name, target_path)
        except OSError:
            # On Windows, if target_path was written simultaneously by another thread/process,
            # os.replace may raise PermissionError. If target exists, deduplication succeeded.
            if target_path.exists():
                if os.path.exists(temp_name):
                    try:
                        os.remove(temp_name)
                    except OSError:
                        pass
                return sha256_hash
            if os.path.exists(temp_name):
                try:
                    os.remove(temp_name)
                except OSError:
                    pass
            raise

        return sha256_hash

    def read_raw(self, sha256_hash: str) -> Tuple[str, bytes]:
        """Read and decompress an object by hash, returning (obj_type, payload)."""
        target_path = self._object_path(sha256_hash)
        if not target_path.is_file():
            if 4 <= len(sha256_hash) < 64:
                resolved = self.find_object_by_prefix(sha256_hash)
                if resolved:
                    target_path = self._object_path(resolved)
                    sha256_hash = resolved
            if not target_path.is_file():
                raise FileNotFoundError(f"Object {sha256_hash} not found in Cognit store.")

        compressed = target_path.read_bytes()
        decompressed = zlib.decompress(compressed)

        null_idx = decompressed.find(b"\x00")
        if null_idx == -1:
            raise ValueError(f"Corrupt object {sha256_hash}: missing null header delimiter.")

        header = decompressed[:null_idx].decode("utf-8")
        obj_type, _ = header.split(" ", 1)
        payload = decompressed[null_idx + 1 :]
        return obj_type, payload

    # High-level typed operations:

    def write_blob(self, data: bytes) -> str:
        """Store raw file content as a blob."""
        return self.write_raw("blob", data)

    def read_blob(self, sha256_hash: str) -> bytes:
        """Retrieve raw file content."""
        full_hash = self.find_object_by_prefix(sha256_hash) or sha256_hash
        obj_type, payload = self.read_raw(full_hash)
        if obj_type != "blob":
            raise ValueError(f"Object {full_hash} is not a blob (got {obj_type})")
        return payload

    def write_tree(self, entries: List[TreeEntry]) -> str:
        """Serialize and store a file tree snapshot."""
        # Sort deterministically by path
        sorted_entries = sorted(entries, key=lambda e: e.path)
        raw_json = json.dumps([e.to_dict() for e in sorted_entries], sort_keys=True).encode("utf-8")
        return self.write_raw("tree", raw_json)

    def read_tree(self, sha256_hash: str) -> List[TreeEntry]:
        """Retrieve and parse a file tree snapshot."""
        full_hash = self.find_object_by_prefix(sha256_hash) or sha256_hash
        obj_type, payload = self.read_raw(full_hash)
        if obj_type != "tree":
            raise ValueError(f"Object {full_hash} is not a tree (got {obj_type})")
        data = json.loads(payload.decode("utf-8"))
        return [TreeEntry.from_dict(d) for d in data]

    def write_checkpoint(self, checkpoint: Checkpoint) -> str:
        """Store a checkpoint object."""
        # For hash stability, serialize without the id field first
        data = checkpoint.to_dict()
        data["id"] = ""
        raw_json = json.dumps(data, sort_keys=True).encode("utf-8")
        actual_hash = self.write_raw("checkpoint", raw_json)
        checkpoint.id = actual_hash
        return actual_hash

    def read_checkpoint(self, sha256_hash: str) -> Checkpoint:
        """Retrieve and parse a checkpoint."""
        full_hash = self.find_object_by_prefix(sha256_hash) or sha256_hash
        obj_type, payload = self.read_raw(full_hash)
        if obj_type != "checkpoint":
            raise ValueError(f"Object {full_hash} is not a checkpoint (got {obj_type})")
        data = json.loads(payload.decode("utf-8"))
        data["id"] = full_hash
        return Checkpoint.from_dict(data)
