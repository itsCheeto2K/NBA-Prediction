from enum import Enum
from pathlib import Path
from typing import List
from pydantic import BaseModel, Field

class SeasonType(str, Enum):
    REGULAR = "Regular Season"
    PLAYOFFS = "Playoffs"
    PLAYIN = "PlayIn"
    PRESEASON = "Pre Season"

class Settings(BaseModel):
    # Seasons defined in NBA_PLAYER_PROPS_PLAN.md §1 & §11.1
    SEASONS: List[str] = Field(
        default_factory=lambda: ["2023-24", "2024-25", "2025-26", "2026-27"]
    )
    
    # Request options (§5.4 & ai_agents.md)
    REQUEST_TIMEOUT: int = 60
    REQUEST_DELAY: float = 1.0  # seconds between requests to avoid rate limits
    MAX_RETRIES: int = 3
    BACKOFF_FACTOR: float = 2.0
    
    # Storage directories (§4 & §6)
    BASE_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    DATA_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data")
    RAW_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "raw")
    PARQUET_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "parquet")
    REPORTS_DIR: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "reports")

    def create_dirs(self) -> None:
        """Create storage directories if they do not exist."""
        for d in [self.DATA_DIR, self.RAW_DIR, self.PARQUET_DIR, self.REPORTS_DIR]:
            d.mkdir(parents=True, exist_ok=True)

settings = Settings()
