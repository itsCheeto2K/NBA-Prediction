import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.config import settings

class CheckpointManager:
    """Manages ingestion run states and backfill checkpoints."""

    def __init__(self, manifest_path: Optional[Path] = None):
        self.manifest_path = manifest_path or (settings.DATA_DIR / "manifests" / "checkpoints.json")
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoints: Dict[str, Dict[str, Any]] = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.checkpoints, f, indent=2, ensure_ascii=False)

    def is_completed(self, task_key: str) -> bool:
        task = self.checkpoints.get(task_key, {})
        return task.get("status") == "COMPLETED"

    def get_status(self, task_key: str) -> Optional[str]:
        return self.checkpoints.get(task_key, {}).get("status")

    def get_rows_count(self, task_key: str) -> int:
        return self.checkpoints.get(task_key, {}).get("rows_count", 0)

    def get_error(self, task_key: str) -> Optional[str]:
        return self.checkpoints.get(task_key, {}).get("error")

    def mark_in_progress(self, task_key: str) -> None:
        self.checkpoints[task_key] = {
            "status": "IN_PROGRESS",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def mark_completed(
        self,
        task_key: str,
        rows_count: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        current = self.checkpoints.get(task_key, {})
        current.update({
            "status": "COMPLETED",
            "rows_count": rows_count,
            "metadata": metadata or {},
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        self.checkpoints[task_key] = current
        self._save()

    def mark_failed(self, task_key: str, error: str) -> None:
        current = self.checkpoints.get(task_key, {})
        current.update({
            "status": "FAILED",
            "error": str(error),
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        self.checkpoints[task_key] = current
        self._save()
