"""Intent locks for coordinating multi-agent swarms without collision."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from cognit.core.database import Database
from cognit.core.models import current_iso_timestamp


class IntentLockManager:
    """Manages file and symbol level intention locks for multi-agent systems."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def acquire(
        self,
        target: str,
        agent_id: str,
        goal: str = "",
        ttl_seconds: int = 300,
    ) -> bool:
        """Acquire a lease lock on a target (file path or symbol like 'auth.py:verify')."""
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
        return self.db.acquire_lock(target=target, agent_id=agent_id, goal=goal, expires_at=expires_at)

    def release(self, target: str, agent_id: str) -> bool:
        """Release a lease lock."""
        return self.db.release_lock(target=target, agent_id=agent_id)

    def check_target(self, target: str) -> Optional[Dict[str, Any]]:
        """Check if a file or symbol is locked by another agent."""
        locks = self.db.list_locks()
        now = current_iso_timestamp()
        for lock in locks:
            if lock["target"] == target and lock["expires_at"] > now:
                return lock
        return None

    def list_active(self) -> List[Dict[str, Any]]:
        """List all currently valid locks."""
        locks = self.db.list_locks()
        now = current_iso_timestamp()
        return [l for l in locks if l["expires_at"] > now]
