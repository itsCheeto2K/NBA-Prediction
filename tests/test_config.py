from pathlib import Path
from src.config import Settings, SeasonType

def test_settings_default_values():
    settings = Settings()
    assert "2023-24" in settings.SEASONS
    assert "2024-25" in settings.SEASONS
    assert "2025-26" in settings.SEASONS
    assert settings.REQUEST_TIMEOUT == 60
    assert settings.REQUEST_DELAY >= 1.0
    assert isinstance(settings.DATA_DIR, Path)
    assert isinstance(settings.RAW_DIR, Path)
    assert isinstance(settings.PARQUET_DIR, Path)

def test_season_types():
    assert SeasonType.REGULAR == "Regular Season"
    assert SeasonType.PLAYOFFS == "Playoffs"
    assert SeasonType.PLAYIN == "PlayIn"
