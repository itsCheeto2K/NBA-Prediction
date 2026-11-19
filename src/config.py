from enum import Enum
import os
from pathlib import Path
from typing import List
from pydantic import BaseModel, Field


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    return Path(os.environ.get("NBA_DATA_DIR", _project_root() / "data")).expanduser()


def _season_list() -> List[str]:
    configured = os.environ.get("NBA_SEASONS")
    if configured:
        seasons = [season.strip() for season in configured.split(",") if season.strip()]
        if not seasons:
            raise ValueError("NBA_SEASONS must contain at least one season")
        return seasons
    return ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26", "2026-27"]

class SeasonType(str, Enum):
    REGULAR = "Regular Season"
    PLAYOFFS = "Playoffs"
    PLAYIN = "PlayIn"
    PRESEASON = "Pre Season"

class Settings(BaseModel):
    # Keep seasons chronological; NBA_SEASONS can extend/override this list at deploy time.
    SEASONS: List[str] = Field(default_factory=_season_list)
    
    # Request options (§5.4 & ai_agents.md)
    REQUEST_TIMEOUT: int = 60
    REQUEST_DELAY: float = 1.0  # seconds between requests to avoid rate limits
    MAX_RETRIES: int = 3
    BACKOFF_FACTOR: float = 2.0
    
    # Storage directories (§4 & §6)
    BASE_DIR: Path = Field(default_factory=_project_root)
    DATA_DIR: Path = Field(default_factory=_data_root)
    RAW_DIR: Path = Field(default_factory=lambda: Path(os.environ.get("NBA_RAW_DIR", _data_root() / "raw")).expanduser())
    PARQUET_DIR: Path = Field(default_factory=lambda: Path(os.environ.get("NBA_PARQUET_DIR", _data_root() / "parquet")).expanduser())
    REPORTS_DIR: Path = Field(default_factory=lambda: Path(os.environ.get("NBA_REPORTS_DIR", _project_root() / "reports")).expanduser())

    @property
    def ACTIVE_SEASON(self) -> str:
        """Most recent season used for live roster, schedule, and sync operations."""
        configured = os.environ.get("NBA_ACTIVE_SEASON")
        return configured.strip() if configured and configured.strip() else self.SEASONS[-1]

    @property
    def SEASONS_WITH_ACTIVE(self) -> List[str]:
        """Configured history plus an explicitly selected active season, if new."""
        return list(dict.fromkeys([*self.SEASONS, self.ACTIVE_SEASON]))

    def create_dirs(self) -> None:
        """Create storage directories if they do not exist."""
        for d in [self.DATA_DIR, self.RAW_DIR, self.PARQUET_DIR, self.REPORTS_DIR]:
            d.mkdir(parents=True, exist_ok=True)

settings = Settings()
