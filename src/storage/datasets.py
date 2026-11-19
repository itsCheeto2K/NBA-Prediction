"""Immutable dataset views. Readers resolve one manifest once per operation."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Mapping

from src.config import settings


@dataclass(frozen=True)
class DatasetView:
    version: str
    files: Mapping[str, Path]
    metadata: Mapping = field(default_factory=dict)

    def path(self, name: str) -> Path:
        return self.files.get(name, Path("__missing_snapshot_file__") / name)

    def glob(self, pattern: str):
        from fnmatch import fnmatch
        return sorted(path for name, path in self.files.items() if fnmatch(name, pattern))


def dataset_view(parquet_dir=None, data_dir=None) -> DatasetView:
    parquet_dir = Path(parquet_dir or settings.PARQUET_DIR)
    data_dir = Path(data_dir or settings.DATA_DIR)
    manifest = data_dir / "snapshots" / "manifest.json"
    if manifest.exists() and parquet_dir.resolve() == (data_dir / "parquet").resolve():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        active_snapshot = payload.get("active_snapshot", "")
        files = {}
        for name, raw_path in payload["files"].items():
            original = Path(raw_path)
            relocated = data_dir / "snapshots" / active_snapshot / name
            files[name] = original if original.is_file() else relocated
        missing = [str(p) for p in files.values() if not p.is_file()]
        if missing:
            raise RuntimeError(f"Incomplete dataset snapshot: {missing}")

        # Snapshot manifests historically recorded absolute machine-local
        # paths. Resolve those pointers after moving the data root between
        # Windows development and Linux deployment environments.
        metadata = dict(payload)
        metadata["files"] = {name: str(path) for name, path in files.items()}

        def relocated_artifact(raw_path, anchor, fallback):
            if not raw_path:
                return fallback
            original = Path(raw_path)
            if original.exists():
                return original
            parts = PureWindowsPath(str(raw_path)).parts
            if anchor in parts:
                suffix = parts[parts.index(anchor):]
                candidate = data_dir.joinpath(*suffix)
                if candidate.exists():
                    return candidate
            posix_parts = Path(str(raw_path).replace("\\", "/")).parts
            if anchor in posix_parts:
                suffix = posix_parts[posix_parts.index(anchor):]
                candidate = data_dir.joinpath(*suffix)
                if candidate.exists():
                    return candidate
            return fallback

        metadata["models_dir"] = str(relocated_artifact(
            payload.get("models_dir"), "releases", settings.BASE_DIR / "models"
        ))
        metadata["reports_dir"] = str(relocated_artifact(
            payload.get("reports_dir"), "releases", settings.REPORTS_DIR
        ))
        return DatasetView(payload["active_snapshot"], files, metadata)
    return DatasetView("legacy", {p.name: p.resolve() for p in parquet_dir.glob("*.parquet")})


def atomic_json(path: Path, payload) -> None:
    """Publish metadata with one filesystem rename on the same volume."""
    import uuid
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def prepare_snapshot(staging: Path, run_id: str, view: DatasetView, data_dir: Path):
    """Copy every member before publishing; legacy files are never modified."""
    import shutil
    target = data_dir / "snapshots" / run_id
    target.mkdir(parents=True, exist_ok=False)
    files = dict(view.files)
    files.update({p.name: p for p in staging.glob("*.parquet")})
    result = {}
    for name, source in files.items():
        dest = target / name
        shutil.copy2(source, dest)
        result[name] = str(dest.resolve())
    payload = {k: v for k, v in view.metadata.items() if k not in ("files", "active_snapshot")}
    payload.update(active_snapshot=run_id, files=result)
    return payload
