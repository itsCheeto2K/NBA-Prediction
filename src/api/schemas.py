import math
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator

VALID_NBA_TEAMS = {
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}

class PredictRequest(BaseModel):
    player_id: int = Field(..., gt=0, description="Valid positive NBA player ID")
    stat: str = Field(default="pts", description="Stat market: pts, reb, or ast")
    line: Optional[float] = Field(default=None, description="Prop line to evaluate (e.g. 24.5)")
    odds_over: Optional[float] = Field(default=None, gt=1.0, description="Decimal odds for Over (must be > 1.0 and finite)")
    odds_under: Optional[float] = Field(default=None, gt=1.0, description="Decimal odds for Under (must be > 1.0 and finite)")
    over_odds: Optional[float] = Field(default=None, gt=1.0, description="Alias for odds_over")
    under_odds: Optional[float] = Field(default=None, gt=1.0, description="Alias for odds_under")
    american_odds_over: Optional[Union[int, float]] = Field(default=None, description="American odds for Over (e.g. -110 or +120)")
    american_odds_under: Optional[Union[int, float]] = Field(default=None, description="American odds for Under (e.g. -110 or +105)")
    game_id: Optional[str] = Field(default=None, description="Specific game ID")
    opponent_override: Optional[str] = Field(default=None, description="Manually override opponent (e.g. 'ATL', 'IND')")
    opponent: Optional[str] = Field(default=None, description="Alias for opponent_override")
    allow_staking_recommendation: bool = Field(default=False, description="Client display preference for staking recommendation; strictly validated server-side (§9.3)")

    @model_validator(mode="before")
    @classmethod
    def populate_odds_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "over_odds" in data and data.get("odds_over") is None:
                data["odds_over"] = data.get("over_odds")
            elif "odds_over" in data and data.get("over_odds") is None:
                data["over_odds"] = data.get("odds_over")
            if "under_odds" in data and data.get("odds_under") is None:
                data["odds_under"] = data.get("under_odds")
            elif "odds_under" in data and data.get("under_odds") is None:
                data["under_odds"] = data.get("odds_under")
            if "opponent" in data and data.get("opponent_override") is None:
                data["opponent_override"] = data.get("opponent")
            elif "opponent_override" in data and data.get("opponent") is None:
                data["opponent"] = data.get("opponent_override")
        return data

    @field_validator("line")
    @classmethod
    def validate_line(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if not math.isfinite(v) or v < 0:
                raise ValueError("Line must be a finite non-negative number")
        return v

    @field_validator("opponent_override", "opponent")
    @classmethod
    def validate_opponent(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = str(v).strip().upper()
            if clean not in VALID_NBA_TEAMS:
                raise ValueError(f"Invalid NBA team abbreviation: '{v}'. Must be one of 30 standard NBA team tricodes.")
            return clean
        return v

    @field_validator("odds_over", "odds_under", "over_odds", "under_odds")
    @classmethod
    def validate_decimal_odds(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if not math.isfinite(v) or v <= 1.0:
                raise ValueError("Decimal odds must be finite and strictly greater than 1.0")
        return v

    @field_validator("american_odds_over", "american_odds_under")
    @classmethod
    def validate_american_odds(cls, v: Optional[Union[int, float]]) -> Optional[Union[int, float]]:
        if v is not None:
            try:
                fv = float(v)
            except (ValueError, TypeError):
                raise ValueError("American odds must be numeric")
            if not math.isfinite(fv) or abs(fv) < 100:
                raise ValueError("American odds must be finite and satisfy |odds| >= 100")
        return v

class PredictionInterval(BaseModel):
    lower: int
    upper: int
    coverage: float

class LineProbabilities(BaseModel):
    line: float
    q_over: float
    q_under: float
    q_push: float

class PricingEvaluation(BaseModel):
    fair_over: float
    fair_under: float
    overround: float
    is_underround: bool = False
    ev_over: Optional[float] = None
    ev_under: Optional[float] = None
    ev_type: str = "MODEL_IMPLIED"
    kelly_over: Optional[float] = None
    kelly_under: Optional[float] = None
    math_optimal_f_over: Optional[float] = None
    math_optimal_f_under: Optional[float] = None
    staking_policy_validated: bool = False
    staking_reason: str = "STAKING_POLICY_UNVALIDATED"

class PMFItem(BaseModel):
    value: int
    prob: float

class ScheduleContext(BaseModel):
    team_b2b: bool
    opp_b2b: bool
    team_rest_days: int
    opp_rest_days: int
    rest_advantage_days: int
    team_3in4: bool
    team_4in6: bool
    player_played_previous_team_game: bool
    team_b2b_but_player_rested: bool
    player_minutes_last7days: float

class OpponentContext(BaseModel):
    opponent_abbr: str
    opp_pace_prev10: float
    opp_def_rating_prev10: float
    opp_ast_allowed_per100_prev10: float
    opp_dreb_share_prev10: float
    opp_fg3a_share_prev10: float
    # Enhanced Opponent Rank & Relative Context (§5, §6, §8)
    opp_pts_allowed_per100: Optional[float] = None
    opp_pts_rank_asc: Optional[float] = None
    opp_pts_pct_asc: Optional[float] = None
    opp_fg3m_allowed_per100: Optional[float] = None
    opp_fg3m_rank_asc: Optional[float] = None
    opp_blocks_made_per100: Optional[float] = None
    opp_blocks_rank_asc: Optional[float] = None

class DvpStatDetail(BaseModel):
    volume_per100: float
    rank_asc: float
    minrate: float
    minrate_rank_asc: float

class DvpContext(BaseModel):
    player_id: int
    position_raw: str
    position_group: str  # 'guard', 'wing', 'big'
    opponent_abbr: str
    dvp_supported: bool
    pts: DvpStatDetail
    reb: DvpStatDetail
    ast: DvpStatDetail

class InjuryRecord(BaseModel):
    player_name: str
    status: str
    short_comment: str
    long_comment: Optional[str] = None
    date: Optional[str] = None
    position: Optional[str] = None
    missing_minutes: Optional[float] = None
    baseline_minutes: Optional[float] = None

class PredictResponse(BaseModel):
    player_id: int
    player_name: str
    team_abbreviation: Optional[str] = None
    stat: str
    expected_value: float
    median: int
    prediction_interval: PredictionInterval
    line_probabilities: Optional[LineProbabilities] = None
    pricing: Optional[PricingEvaluation] = None
    pmf: List[PMFItem]
    condition: Dict[str, Any]
    schedule_context: Optional[ScheduleContext] = None
    opponent_context: Optional[OpponentContext] = None
    dvp_context: Optional[DvpContext] = None
    upcoming_game_info: Optional[Dict[str, Any]] = None
    player_injury: Optional[InjuryRecord] = None
    teammate_injuries: List[InjuryRecord] = []
    opponent_injuries: List[InjuryRecord] = []
    readiness: Optional[Dict[str, Any]] = None
    unconditional_settlement: Optional[Dict[str, Any]] = None
    injury_impact: Optional[Dict[str, Any]] = None

class LiveHealthResponse(BaseModel):
    status: str = "alive"
    timestamp: str

class ReadyHealthResponse(BaseModel):
    status: str
    ready: bool
    checks: Dict[str, Any]
    timestamp: str

class SyncRunRequest(BaseModel):
    season: str = Field(default="2026-27", description="NBA season to sync")
    force_refresh: bool = Field(default=True, description="Force network fetch or allow cache")

class SyncJobResponse(BaseModel):
    job_id: str
    season: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None

class OcrOddsRequest(BaseModel):
    image_base64: str = Field(description="Base64 encoded screenshot image (with or without data:image/png prefix)")


# Player Reference History Schemas (§6 of NBA_HOME_PLAYER_HISTORY_REFERENCE_SPEC.md)

class PlayerHistoryRow(BaseModel):
    game_id: str
    game_date: str
    season: str
    season_type: str = "Regular Season"
    player_team_id: int
    player_team_name: Optional[str] = None
    player_team_abbr: Optional[str] = None
    opponent_team_id: int
    opponent_team_name: Optional[str] = None
    opponent_team_abbr: Optional[str] = None
    home_away: str
    matchup: Optional[str] = None
    minutes: Optional[float] = None
    participation_status: Optional[str] = "PLAYED"
    pts: Optional[int] = None
    reb: Optional[int] = None
    ast: Optional[int] = None
    stl: Optional[int] = None
    blk: Optional[int] = None
    tov: Optional[int] = None
    fg3m: Optional[int] = None
    fgm: Optional[int] = None
    fga: Optional[int] = None
    fg3a: Optional[int] = None
    ftm: Optional[int] = None
    fta: Optional[int] = None
    plus_minus: Optional[int] = None


class PlayerHistoryTable(BaseModel):
    rows: List[PlayerHistoryRow] = []
    returned_count: int = 0


class PlayerHistoryCoverage(BaseModel):
    seasons_available: List[str] = []
    history_complete_for_requested_scope: bool = False
    backfill_pending: bool = False


class PlayerHistoryResponse(BaseModel):
    player_id: int | str
    opponent_team_id: Optional[int | str] = None
    as_of: str
    season_type: str = "Regular Season"
    reference_only: bool = True
    affects_prediction: bool = False
    recent: PlayerHistoryTable
    vs_opponent: PlayerHistoryTable
    coverage: PlayerHistoryCoverage
    data_updated_at: Optional[str] = None
    warnings: List[str] = []

