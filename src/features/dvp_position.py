"""Player position normalization and canonical role mapping for Defense vs Position (DvP)."""
from pathlib import Path
from typing import Dict, Optional, Tuple
import pandas as pd
import logging

from src.config import settings

logger = logging.getLogger(__name__)

RAW_POSITION_MAP: Dict[str, str] = {
    # Guards
    "PG": "guard",
    "SG": "guard",
    "G": "guard",
    "POINT GUARD": "guard",
    "SHOOTING GUARD": "guard",
    # Wings / Small Forwards
    "SF": "wing",
    "F": "wing",
    "G-F": "wing",
    "F-G": "wing",
    "SMALL FORWARD": "wing",
    # Bigs / Frontcourt
    "PF": "big",
    "C": "big",
    "F-C": "big",
    "C-F": "big",
    "POWER FORWARD": "big",
    "CENTER": "big",
}

_CACHED_POSITIONS_DF: Optional[pd.DataFrame] = None
_PLAYER_GROUP_LOOKUP: Optional[Dict[int, str]] = None
_PLAYER_RAW_LOOKUP: Optional[Dict[int, str]] = None


def normalize_position_group(raw_pos: Optional[str]) -> str:
    """Deterministic normalized position group mapping (§4 of Spec)."""
    if not raw_pos or pd.isna(raw_pos):
        return "unknown"
    p = str(raw_pos).upper().strip()
    return RAW_POSITION_MAP.get(p, "unknown")


def get_player_positions_df() -> pd.DataFrame:
    """Load canonical player positions dataframe."""
    global _CACHED_POSITIONS_DF, _PLAYER_GROUP_LOOKUP, _PLAYER_RAW_LOOKUP
    if _CACHED_POSITIONS_DF is not None:
        return _CACHED_POSITIONS_DF

    pos_path = settings.PARQUET_DIR / "player_positions.parquet"
    if pos_path.exists():
        _CACHED_POSITIONS_DF = pd.read_parquet(pos_path)
    else:
        logger.warning(f"Player positions file not found at {pos_path}, returning empty DataFrame.")
        _CACHED_POSITIONS_DF = pd.DataFrame(columns=["player_id", "position_raw", "position_group"])

    _PLAYER_GROUP_LOOKUP = dict(zip(_CACHED_POSITIONS_DF["player_id"], _CACHED_POSITIONS_DF["position_group"]))
    _PLAYER_RAW_LOOKUP = dict(zip(_CACHED_POSITIONS_DF["player_id"], _CACHED_POSITIONS_DF["position_raw"]))
    return _CACHED_POSITIONS_DF


def resolve_player_position(player_id: int) -> Tuple[str, str]:
    """
    Look up player's raw position and position group.
    Returns: (position_raw, position_group).
    """
    global _PLAYER_GROUP_LOOKUP, _PLAYER_RAW_LOOKUP
    if _PLAYER_GROUP_LOOKUP is None:
        get_player_positions_df()

    raw = _PLAYER_RAW_LOOKUP.get(player_id, "Unknown") if _PLAYER_RAW_LOOKUP else "Unknown"
    grp = _PLAYER_GROUP_LOOKUP.get(player_id, "unknown") if _PLAYER_GROUP_LOOKUP else "unknown"
    return str(raw), str(grp)
