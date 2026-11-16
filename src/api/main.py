import json
import logging
import math
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import lightgbm as lgb
from catboost import CatBoostRegressor

from src.api.schemas import (
    PredictRequest,
    PredictResponse,
    PredictionInterval,
    LineProbabilities,
    PricingEvaluation,
    PMFItem,
    ScheduleContext,
    OpponentContext,
    DvpStatDetail,
    DvpContext,
    InjuryRecord,
    LiveHealthResponse,
    ReadyHealthResponse,
    SyncRunRequest,
    SyncJobResponse,
    OcrOddsRequest,
    PlayerHistoryResponse,
)
from src.config import settings
from src.collectors.static import get_all_players_df, get_all_teams_df
from src.collectors.injuries import fetch_espn_injuries, get_player_injury, get_team_injuries
from src.collectors.sync import get_job_manager, get_last_sync_info, _SYNC_LOCK
from src.features.participation import ParticipationModel, normalize_injury_status
from src.distribution.settlement import compute_unconditional_settlement, evaluate_injury_readiness
from src.distribution.engine import DiscreteDistributionEngine
from src.distribution.pricing import (
    american_to_decimal,
    remove_vig_multiplicative,
    calculate_ev,
    calculate_kelly_fraction,
)
from src.distribution.special_groups import assess_player_condition, adjust_dispersion_for_uncertainty
from src.features.player_history import get_player_history


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("api")

app = FastAPI(
    title="NBA Player Props Prediction API",
    description="Full probability distribution and calibrated expected value prediction engine for NBA Player Props.",
    version="1.9.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global in-memory cache for models and reference tables
MODELS: Dict[str, Any] = {}
BUNDLES: Dict[str, Any] = {}
FEATURES_META: List[str] = []
PLAYERS_DF: Optional[pd.DataFrame] = None
TEAMS_DF: Optional[pd.DataFrame] = None
LATEST_FEATURES_DF: Optional[pd.DataFrame] = None
SCHEDULE_DF: Optional[pd.DataFrame] = None
TEAM_LOGS_DF: Optional[pd.DataFrame] = None
PLAYER_LOGS_DF: Optional[pd.DataFrame] = None
PLAYER_NAME_TO_MINUTES: Dict[str, float] = {}
DIST_ENGINE = DiscreteDistributionEngine(dist_type="nbinom", k_max=60)


def get_player_baseline_minutes(name: str, default_min: float = 18.0) -> float:
    """Lookup a player's actual historical baseline minutes from previous game averages."""
    from src.collectors.injuries import normalize_text
    norm = normalize_text(name)
    return PLAYER_NAME_TO_MINUTES.get(norm, default_min)


def load_resources():
    global MODELS, BUNDLES, FEATURES_META, PLAYERS_DF, TEAMS_DF, LATEST_FEATURES_DF, SCHEDULE_DF, TEAM_LOGS_DF, PLAYER_LOGS_DF, PLAYER_NAME_TO_MINUTES
    models_dir = settings.BASE_DIR / "models"
    meta_path = models_dir / "features_meta.json"

    # 1. Feature columns
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            FEATURES_META = json.load(f).get("features", [])

    # 2. Production ModelBundles (§11)
    from src.models.selector import ModelBundle
    for stat in ["pts", "reb", "ast"]:
        bundle_dir = models_dir / f"bundle_{stat}"
        if bundle_dir.exists():
            try:
                BUNDLES[stat] = ModelBundle.load(bundle_dir)
                logger.info(f"Loaded atomic ModelBundle for {stat.upper()}: {BUNDLES[stat].bundle_id}")
            except Exception as e:
                logger.warning(f"Could not load ModelBundle for {stat}: {e}")

    # 3. Legacy Models fallback (LightGBM & CatBoost)
    for stat in ["pts", "reb", "ast"]:
        lgbm_path = models_dir / f"lgbm_{stat}.txt"
        cat_path = models_dir / f"catboost_{stat}.cbm"

        if lgbm_path.exists():
            booster = lgb.Booster(model_file=str(lgbm_path))
            MODELS[f"lgbm_{stat}"] = booster
            logger.info(f"Loaded LightGBM model for {stat}")
        elif cat_path.exists():
            cat = CatBoostRegressor()
            cat.load_model(str(cat_path))
            MODELS[f"catboost_{stat}"] = cat
            logger.info(f"Loaded CatBoost model for {stat}")

    # 4. Reference Data
    PLAYERS_DF = get_all_players_df()
    TEAMS_DF = get_all_teams_df()

    # 5. Schedule & Team Logs
    sched_path = settings.PARQUET_DIR / "schedule_2026-27.parquet"
    if sched_path.exists():
        SCHEDULE_DF = pd.read_parquet(sched_path)
        logger.info(f"Loaded schedule with {len(SCHEDULE_DF)} games")

    tlogs_path = settings.PARQUET_DIR / "team_gamelogs_2026-27.parquet"
    if tlogs_path.exists():
        TEAM_LOGS_DF = pd.read_parquet(tlogs_path)
        logger.info(f"Loaded team gamelogs with {len(TEAM_LOGS_DF)} records")

    plogs_path = settings.PARQUET_DIR / "player_gamelogs_2026-27.parquet"
    if plogs_path.exists():
        PLAYER_LOGS_DF = pd.read_parquet(plogs_path)
        logger.info(f"Loaded player gamelogs with {len(PLAYER_LOGS_DF)} records")

    # 6. Features Parquet
    feat_path = settings.PARQUET_DIR / "features_all_seasons.parquet"
    if feat_path.exists():
        df_feat = pd.read_parquet(feat_path)
        df_feat["game_date_dt"] = pd.to_datetime(df_feat["game_date"])
        df_sorted = df_feat.sort_values(by=["player_id", "game_date_dt", "game_id"])
        LATEST_FEATURES_DF = df_sorted.groupby("player_id").last().reset_index()
        logger.info(f"Loaded latest feature states for {len(LATEST_FEATURES_DF)} players")

        from src.collectors.injuries import normalize_text
        PLAYER_NAME_TO_MINUTES.clear()
        if LATEST_FEATURES_DF is not None:
            for r in LATEST_FEATURES_DF.to_dict(orient="records"):
                p_name = r.get("player_name")
                if not p_name:
                    continue
                m = r.get("min_decay_mean")
                if pd.isna(m) or m <= 0:
                    m = r.get("min_roll_mean_5")
                if pd.isna(m) or m <= 0:
                    m = r.get("min_roll_mean_10")
                if pd.isna(m) or m <= 0:
                    m = r.get("min", 18.0)
                PLAYER_NAME_TO_MINUTES[normalize_text(p_name)] = round(float(m), 1)


# Initialize resources once on module load (guarantees TestClient readiness)
if not MODELS or PLAYERS_DF is None:
    load_resources()

# Mount static files for dashboard frontend
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _trigger_auto_sync_if_stale(max_age_hours: float = 2.0) -> None:
    """Checks last sync time and enqueues a background sync if data is stale (> max_age_hours)."""
    try:
        from src.collectors.sync import get_last_sync_info, get_job_manager
        info = get_last_sync_info()
        last_sync_str = info.get("last_sync_time")
        should_sync = False

        if not last_sync_str:
            should_sync = True
        else:
            try:
                last_dt = datetime.fromisoformat(last_sync_str.replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600.0
                if age_hours >= max_age_hours:
                    should_sync = True
            except Exception:
                should_sync = True

        if should_sync:
            logger.info("Auto-sync: Data is stale (>2 hours or new day). Launching background sync for 2026-27...")
            manager = get_job_manager()
            manager.enqueue_job(season="2026-27", force_refresh=True)
        else:
            logger.info(f"Auto-sync: Data is fresh (synced within last {max_age_hours}h).")

        # Non-blocking pre-warm / refresh ESPN injury cache in background
        import threading
        threading.Thread(
            target=lambda: fetch_espn_injuries(force_refresh=False),
            name="bg-injury-refresh",
            daemon=True,
        ).start()
    except Exception as e:
        logger.warning(f"Auto-sync check notice: {e}")


@app.get("/")
def serve_index():
    _trigger_auto_sync_if_stale()
    from fastapi.responses import FileResponse
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "NBA Player Props API is running. Access /docs for OpenAPI specifications."}


@app.get("/fastcheck")
def serve_fastcheck():
    _trigger_auto_sync_if_stale()
    from fastapi.responses import FileResponse
    fc_path = static_dir / "fastcheck.html"
    if fc_path.exists():
        return FileResponse(fc_path)
    return {"message": "FastCheck interface under construction."}


@app.on_event("startup")
def on_app_startup():
    """Startup lifecycle hook: non-blocking resource load (§5)."""
    logger.info("Application starting: verifying latest valid bundles and snapshots...")
    if not MODELS or PLAYERS_DF is None:
        load_resources()
    logger.info("Application startup completed successfully without blocking network backfill.")
    _trigger_auto_sync_if_stale()


@app.get("/api/health/live", response_model=LiveHealthResponse)
def health_live():
    """Lightweight process/event-loop liveness check (§6, §13). Zero network calls."""
    return LiveHealthResponse(
        status="alive",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/api/health/ready", response_model=ReadyHealthResponse)
def health_ready():
    """
    Readiness probe (§6, §13):
    Verifies ModelBundles or legacy models across all stat markets (pts, reb, ast),
    reference data present, and features available.
    """
    market_models = {
        m: (m in BUNDLES) or (f"lgbm_{m}" in MODELS)
        for m in ["pts", "reb", "ast"]
    }
    all_markets_ready = all(market_models.values())

    checks = {
        "model_bundles_loaded": len(BUNDLES),
        "legacy_models_loaded": len(MODELS),
        "market_models": market_models,
        "all_markets_ready": all_markets_ready,
        "players_reference_loaded": PLAYERS_DF is not None and not PLAYERS_DF.empty,
        "teams_reference_loaded": TEAMS_DF is not None and not TEAMS_DF.empty,
        "latest_features_loaded": LATEST_FEATURES_DF is not None and not LATEST_FEATURES_DF.empty,
        "sync_lock_active": _SYNC_LOCK.is_locked(),
    }
    is_ready = bool(
        all_markets_ready
        and checks["players_reference_loaded"]
        and checks["latest_features_loaded"]
    )
    status_str = "READY" if is_ready else ("DEGRADED" if any(market_models.values()) and checks["players_reference_loaded"] else "NOT_READY")

    response_payload = ReadyHealthResponse(
        status=status_str,
        ready=is_ready,
        checks=checks,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    if not is_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response_payload.model_dump(),
        )

    return response_payload


@app.get("/api/health")
def legacy_health_check():
    """Legacy health check for backward compatibility."""
    return {
        "status": "ok",
        "models_loaded": list(MODELS.keys()) + [f"bundle_{k}" for k in BUNDLES.keys()],
        "players_count": len(PLAYERS_DF) if PLAYERS_DF is not None else 0,
        "features_available": len(FEATURES_META),
    }


@app.post("/api/sync/run", status_code=status.HTTP_202_ACCEPTED, response_model=SyncJobResponse)
def trigger_sync_job(req: SyncRunRequest):
    """
    Asynchronous manual sync job launcher (§5.2, §13):
    Returns HTTP 202 Accepted with job_id immediately.
    """
    manager = get_job_manager()
    job = manager.enqueue_job(season=req.season, force_refresh=req.force_refresh)
    return SyncJobResponse(
        job_id=job["job_id"],
        season=job["season"],
        status=job["status"],
        created_at=job["created_at"],
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
        message="Sync job enqueued successfully.",
        error=job.get("error"),
        result=job.get("result"),
    )


@app.get("/api/sync/status/{job_id}", response_model=SyncJobResponse)
def get_sync_job_status(job_id: str):
    """Query progress and result of a specific sync job (§5.2, §6)."""
    manager = get_job_manager()
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Sync job {job_id} not found.")

    return SyncJobResponse(
        job_id=job["job_id"],
        season=job["season"],
        status=job["status"],
        created_at=job["created_at"],
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
        message=f"Sync job is {job['status']}.",
        error=job.get("error"),
        result=job.get("result"),
    )


@app.get("/api/sync/status")
def get_sync_status():
    """Query overall committed sync status and latest watermarks."""
    return get_last_sync_info()


@app.post("/api/sync")
def trigger_sync_legacy():
    """Legacy synchronous sync endpoint (redirects to async worker or runs guarded)."""
    manager = get_job_manager()
    job = manager.enqueue_job(season="2026-27", force_refresh=True)
    import threading
    threading.Thread(
        target=lambda: fetch_espn_injuries(force_refresh=True),
        name="manual-sync-injury-refresh",
        daemon=True,
    ).start()
    return {
        "message": "Sync job initiated asynchronously.",
        "job_id": job["job_id"],
        "status": job["status"],
    }


@app.get("/api/injuries")
def get_league_injuries(team: Optional[str] = None):
    """Retrieve live ESPN NBA injury reports."""
    data = fetch_espn_injuries()
    if team:
        t_upper = team.upper().strip()
        return {"team": t_upper, "injuries": get_team_injuries(t_upper, data)}
    return data


def check_server_staking_policy_validated() -> bool:
    """
    Server-side verification of staking policy (§9.3, §14).
    Staking recommendations are strictly withheld unless a valid certified
    simulation gate report / policy artifact exists and is verified on the server.
    """
    gate_cert_path = settings.REPORTS_DIR / "simulation_gate_certified.json"
    if gate_cert_path.exists():
        try:
            with open(gate_cert_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("gate_decision") == "PASS" and data.get("certified", False):
                    return True
        except Exception:
            return False
    return False


def evaluate_market_pricing(
    req: PredictRequest,
    line_probs: Dict[str, float],
) -> Optional[PricingEvaluation]:
    """
    Evaluate sportsbook odds, de-vig, model-implied EV, and refund-adjusted Kelly fraction (§8, §9).
    Hides staking recommendations by default unless allow_staking_recommendation=True AND server policy validated.
    """
    # 1. Normalize American odds if supplied
    d_over = req.odds_over
    d_under = req.odds_under

    if req.american_odds_over is not None:
        try:
            d_over = american_to_decimal(req.american_odds_over)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid american_odds_over: {e}")

    if req.american_odds_under is not None:
        try:
            d_under = american_to_decimal(req.american_odds_under)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid american_odds_under: {e}")

    if d_over is None or d_under is None:
        return None

    if d_over <= 1.0 or d_under <= 1.0 or not math.isfinite(d_over) or not math.isfinite(d_under):
        raise HTTPException(status_code=422, detail="Decimal odds must be finite and strictly greater than 1.0")

    # 2. Multiplicative de-vig
    devig = remove_vig_multiplicative(odds_over=d_over, odds_under=d_under)

    # 3. Model EV with push refund (§9.2)
    ev_o = calculate_ev(prob_win=line_probs["q_over"], prob_loss=line_probs["q_under"], decimal_odds=d_over)
    ev_u = calculate_ev(prob_win=line_probs["q_under"], prob_loss=line_probs["q_over"], decimal_odds=d_under)

    # 4. Refund-adjusted Kelly fraction & server-side policy validation (§9.3)
    server_policy_validated = check_server_staking_policy_validated()
    effective_allow_staking = bool(server_policy_validated and req.allow_staking_recommendation)

    kelly_o = calculate_kelly_fraction(
        prob_win=line_probs["q_over"],
        prob_loss=line_probs["q_under"],
        decimal_odds=d_over,
        allow_recommendation=effective_allow_staking,
    )
    kelly_u = calculate_kelly_fraction(
        prob_win=line_probs["q_under"],
        prob_loss=line_probs["q_over"],
        decimal_odds=d_under,
        allow_recommendation=effective_allow_staking,
    )

    return PricingEvaluation(
        fair_over=devig["fair_over"],
        fair_under=devig["fair_under"],
        overround=devig["overround"],
        is_underround=devig.get("is_underround", False),
        ev_over=ev_o,
        ev_under=ev_u,
        ev_type="MODEL_IMPLIED",
        kelly_over=kelly_o["kelly_recommendation"],
        kelly_under=kelly_u["kelly_recommendation"],
        math_optimal_f_over=kelly_o["math_optimal_f"],
        math_optimal_f_under=kelly_u["math_optimal_f"],
        staking_policy_validated=server_policy_validated,
        staking_reason=kelly_o["reason"] if server_policy_validated else "STAKING_POLICY_UNVALIDATED",
    )


@app.get("/api/players")
def search_players(
    q: Optional[str] = Query(None, description="Search term for player name"),
    query: Optional[str] = Query(None, description="Search term alias"),
):
    """Search for players by name prefix or substring."""
    search_term = (q or query or "").strip()
    if len(search_term) < 2:
        return []
    if PLAYERS_DF is None or PLAYERS_DF.empty:
        return []
    
    match = PLAYERS_DF[PLAYERS_DF["full_name"].str.contains(search_term, case=False, na=False, regex=False)]
    id_col = "player_id" if "player_id" in match.columns else "id"
    records = []
    for _, r in match.head(20).iterrows():
        records.append({
            "id": int(r[id_col]),
            "player_id": int(r[id_col]),
            "full_name": r["full_name"],
            "is_active": r.get("is_active", True),
        })
    return records


@app.get(
    "/api/players/{player_id}/history",
    response_model=PlayerHistoryResponse,
    tags=["Reference History"],
    summary="Player Recent and H2H Reference History",
    description="Pure read-only player reference history (10 recent games and 10 vs opponent). Zero impact on prediction/inference.",
)
def get_player_reference_history(
    player_id: int,
    opponent_team_id: Optional[int] = Query(None, description="Opponent team ID to filter H2H history"),
    opponent_abbr: Optional[str] = Query(None, description="Opponent abbreviation (e.g. GSW, BOS)"),
    target_game_id: Optional[str] = Query(None, description="Target game ID for cutoff"),
    season_type: str = Query("Regular Season", description="Season type (default: Regular Season)"),
    limit: int = Query(10, ge=1, le=50, description="Max games to return for each table (default: 10)"),
) -> PlayerHistoryResponse:
    """Retrieve player's recent 10 games and 10 games vs opponent for reference display (§6)."""
    # Verify player exists in reference tables or gamelogs
    player_exists = False
    if PLAYERS_DF is not None and not PLAYERS_DF.empty:
        id_col = "player_id" if "player_id" in PLAYERS_DF.columns else "id"
        player_exists = (PLAYERS_DF[id_col] == player_id).any()

    # Call pure read service
    res = get_player_history(
        player_id=player_id,
        opponent_team_id=opponent_team_id,
        opponent_abbr=opponent_abbr,
        target_game_id=target_game_id,
        season_type=season_type,
        limit=limit,
    )

    if not player_exists and res["recent"]["returned_count"] == 0 and res["vs_opponent"]["returned_count"] == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player with ID {player_id} not found",
        )

    return PlayerHistoryResponse(**res)



@app.get("/api/teams/{team_abbr}/matchup")
def get_team_matchup(team_abbr: str):
    """Retrieve upcoming matchup context and scheduled opponent for a specific team."""
    team_abbr = team_abbr.strip().upper()
    if SCHEDULE_DF is None or SCHEDULE_DF.empty:
        return {"team_abbr": team_abbr, "opponent_abbr": None, "has_game": False}

    from src.features.matchup_resolver import get_team_upcoming_game, get_team_current_defensive_profile
    game = get_team_upcoming_game(team_abbr, SCHEDULE_DF)
    if not game:
        return {"team_abbr": team_abbr, "opponent_abbr": None, "has_game": False}

    opp_abbr = game["opponent_abbr"]
    opp_def = get_team_current_defensive_profile(opp_abbr, TEAM_LOGS_DF if TEAM_LOGS_DF is not None else pd.DataFrame())
    own_def = get_team_current_defensive_profile(team_abbr, TEAM_LOGS_DF if TEAM_LOGS_DF is not None else pd.DataFrame())

    return {
        "team_abbr": team_abbr,
        "opponent_abbr": opp_abbr,
        "is_home": bool(game["is_home"] == 1),
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "game_date": game["game_date"],
        "slate_label": game.get("slate_label", "Upcoming"),
        "tipoff_vn": game.get("tipoff_vn", ""),
        "game_status_text": game.get("game_status_text", "Scheduled"),
        "has_game": True,
        "opponent_defense": opp_def,
        "team_defense": own_def,
    }


@app.get("/api/teams/{team_abbr}/defense-profile")
def get_team_defense_profile(team_abbr: str):
    """Retrieve defensive profile, empirical Bayes shrunk rates, and percentile ranks for a team."""
    team_abbr = team_abbr.strip().upper()
    from src.features.matchup_resolver import get_team_current_defensive_profile
    from src.features.dvp_context import get_team_all_dvp_profiles
    profile = get_team_current_defensive_profile(team_abbr, TEAM_LOGS_DF if TEAM_LOGS_DF is not None else pd.DataFrame())
    dvp = get_team_all_dvp_profiles(
        team_abbr,
        PLAYER_LOGS_DF if PLAYER_LOGS_DF is not None else pd.DataFrame(),
        TEAM_LOGS_DF if TEAM_LOGS_DF is not None else pd.DataFrame(),
    )
    return {
        "team_abbr": team_abbr,
        "profile": profile,
        "dvp": dvp,
    }


@app.get("/api/teams/{team_abbr}/roster")
def get_team_roster(team_abbr: str):
    """Retrieve complete player rotation and bench for a team."""
    team_abbr = team_abbr.strip().upper()
    if LATEST_FEATURES_DF is None or LATEST_FEATURES_DF.empty:
        return []

    sub = LATEST_FEATURES_DF[LATEST_FEATURES_DF["team_abbreviation"] == team_abbr].copy()
    if sub.empty:
        return []

    # Sort by active season first (2026-27 > 2025-26 > older), then min_roll_mean_5 descending
    if "season" in sub.columns:
        sub["_sort_season"] = sub["season"].apply(
            lambda s: 3 if s == "2026-27" else (2 if s == "2025-26" else 1)
        )
        sub = sub.sort_values(by=["_sort_season", "min_roll_mean_5"], ascending=[False, False])
    else:
        sub = sub.sort_values(by="min_roll_mean_5", ascending=False)

    from src.features.dvp_position import resolve_player_position
    roster = []
    for _, r in sub.iterrows():
        p_id = int(r["player_id"])
        p_name = str(r.get("player_name", "Unknown"))
        raw_min = r.get("min_roll_mean_5")
        raw_pts = r.get("pts_roll_mean_5")
        min_avg = round(float(raw_min), 1) if pd.notna(raw_min) else 0.0
        pts_avg = round(float(raw_pts), 1) if pd.notna(raw_pts) else 0.0
        suggested_line = round(pts_avg - 0.5, 1) if pts_avg >= 5.0 else 4.5
        season_val = str(r.get("season", "2026-27"))
        is_current = season_val == "2026-27"
        raw_pos, pos_grp = resolve_player_position(p_id)

        roster.append({
            "player_id": p_id,
            "player_name": p_name,
            "team_abbreviation": team_abbr,
            "position_raw": raw_pos,
            "position_group": pos_grp,
            "min_avg": min_avg,
            "pts_avg": pts_avg,
            "suggested_line": suggested_line,
            "season": season_val,
            "is_current": is_current,
        })
    return roster


@app.post("/api/fastcheck/predict-batch")
def predict_batch_fastcheck(items: List[PredictRequest]):
    """Run lightweight fast predictions for a batch of players on the fastcheck screen."""
    if len(items) > 50:
        raise HTTPException(status_code=422, detail="Batch size limit exceeded. Maximum 50 items allowed.")
    results = []
    for req in items:
        try:
            resp = predict_props(req)
            lp = resp.line_probabilities
            dvp_pts_rank = resp.dvp_context.pts.rank_asc if resp.dvp_context else None
            pricing = resp.pricing
            results.append({
                "player_id": req.player_id,
                "expected_value": resp.expected_value,
                "median": resp.median,
                "q_over": round(lp.q_over * 100, 1) if lp else None,
                "q_under": round(lp.q_under * 100, 1) if lp else None,
                "ev_over": pricing.ev_over if pricing else None,
                "ev_under": pricing.ev_under if pricing else None,
                "dvp_pts_rank": dvp_pts_rank,
                "line": req.line,
                "error": None,
            })
        except Exception as e:
            results.append({
                "player_id": req.player_id,
                "expected_value": None,
                "median": None,
                "q_over": None,
                "q_under": None,
                "ev_over": None,
                "ev_under": None,
                "dvp_pts_rank": None,
                "line": req.line,
                "error": str(e),
            })
    return results


@app.post("/api/fastcheck/ocr-odds")
def ocr_odds_fastcheck(req: OcrOddsRequest):
    """Extract player prop lines and odds from an uploaded or pasted screenshot."""
    try:
        raw_b64 = req.image_base64.strip()
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]

        img_bytes = base64.b64decode(raw_b64)
        if len(img_bytes) == 0:
            raise ValueError("Empty image data")

        from src.services.odds_ocr_parser import parse_odds_image
        all_players = PLAYERS_DF.to_dict(orient="records") if PLAYERS_DF is not None else []
        results = parse_odds_image(img_bytes, all_players, LATEST_FEATURES_DF)

        team_counts = {}
        for r in results:
            t = r.get("team_abbreviation")
            if t:
                team_counts[t] = team_counts.get(t, 0) + 1

        return {
            "status": "success",
            "detected_count": len(results),
            "team_counts": team_counts,
            "items": results,
        }
    except Exception as e:
        logger.error(f"Error processing OCR odds image: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Không thể nhận diện ảnh: {str(e)}")


@app.post("/api/predict", response_model=PredictResponse)
def predict_props(req: PredictRequest):
    """
    Produce calibrated probability distribution, expected value, and market evaluation
    for an individual player prop (§10, §11).
    """
    stat = req.stat.lower().strip()
    if stat not in ["pts", "reb", "ast"]:
        raise HTTPException(status_code=400, detail="Stat must be one of: pts, reb, ast")

    player_id = req.player_id

    # 1. Player Info & Existence Check (§10, Issue 08)
    player_found = False
    player_name = "Unknown Player"
    if PLAYERS_DF is not None and not PLAYERS_DF.empty:
        id_col = "player_id" if "player_id" in PLAYERS_DF.columns else "id"
        p_row = PLAYERS_DF[PLAYERS_DF[id_col] == player_id]
        if not p_row.empty:
            player_name = str(p_row.iloc[0]["full_name"])
            player_found = True

    if not player_found and LATEST_FEATURES_DF is not None and not LATEST_FEATURES_DF.empty:
        feat_match = LATEST_FEATURES_DF[LATEST_FEATURES_DF["player_id"] == player_id]
        if not feat_match.empty:
            player_found = True
            player_name = str(feat_match.iloc[0].get("player_name", "Unknown Player"))

    if not player_found:
        raise HTTPException(
            status_code=404,
            detail=f"Player with ID {player_id} not found in database.",
        )

    # 2. Features Lookup
    row_features = None
    team_abbr = None
    if LATEST_FEATURES_DF is not None:
        feat_match = LATEST_FEATURES_DF[LATEST_FEATURES_DF["player_id"] == player_id]
        if not feat_match.empty:
            row_features = feat_match.iloc[0].to_dict()
            team_abbr = row_features.get("team_abbreviation")

    # 3. Dynamic Matchup Context Resolution (§5, §6 of Supplement Plan)
    upcoming_info = None
    if row_features is not None and team_abbr:
        from src.features.matchup_resolver import resolve_live_matchup_context
        s_row = pd.Series(row_features)
        resolved_s, live_game_info = resolve_live_matchup_context(
            player_history_row=s_row,
            team_abbr=team_abbr,
            sched_df=SCHEDULE_DF if SCHEDULE_DF is not None else pd.DataFrame(),
            team_logs_df=TEAM_LOGS_DF if TEAM_LOGS_DF is not None else pd.DataFrame(),
            opp_override=req.opponent_override,
        )
        row_features = resolved_s.to_dict()
        upcoming_info = live_game_info

        # Ensure compatibility fields
        if "opponent" not in upcoming_info:
            upcoming_info["opponent"] = upcoming_info.get("scheduled_opponent") or upcoming_info.get("active_opponent")
        if "tipoff_time_et" not in upcoming_info:
            upcoming_info["tipoff_time_et"] = upcoming_info.get("game_date")
        if "is_override" not in upcoming_info:
            upcoming_info["is_override"] = bool(req.opponent_override and req.opponent_override.strip().upper() != upcoming_info.get("scheduled_opponent", "").upper())
    elif req.opponent_override:
        opp = req.opponent_override.strip().upper()
        upcoming_info = {
            "game_id": None,
            "game_date": "Upcoming",
            "opponent": opp,
            "scheduled_opponent": opp,
            "active_opponent": opp,
            "is_home": True,
            "home_team": team_abbr or "GSW",
            "away_team": opp,
            "game_status_text": "Scenario",
            "tipoff_time_et": None,
            "is_override": True,
        }

    # 4. Injury and Participation evaluation
    all_injuries = fetch_espn_injuries()
    is_stale_inj = bool(all_injuries.get("is_stale_report", False))
    if not is_stale_inj and "fetched_at" in all_injuries:
        try:
            fat = datetime.fromisoformat(all_injuries["fetched_at"])
            if (datetime.now(timezone.utc) - fat).total_seconds() > 21600.0:
                is_stale_inj = True
        except Exception:
            pass

    player_inj_raw = get_player_injury(player_name, all_injuries)

    player_inj = None
    p_status = "available"
    if player_inj_raw:
        p_status = normalize_injury_status(player_inj_raw.get("status", "Healthy"))
        player_inj = InjuryRecord(
            player_name=player_name,
            status=player_inj_raw.get("status", "Healthy"),
            short_comment=player_inj_raw.get("short_comment", ""),
            long_comment=player_inj_raw.get("long_comment"),
            date=player_inj_raw.get("date"),
            position=player_inj_raw.get("position"),
            baseline_minutes=get_player_baseline_minutes(player_name),
        )

    # Teammate & Opponent injuries
    teammate_injs: List[InjuryRecord] = []
    opponent_injs: List[InjuryRecord] = []
    tm_missing_mins = 0.0
    tm_lost_minutes_list: List[float] = []
    opp_missing_mins = 0.0

    def compute_absence_weight(status_str: str) -> float:
        """Calculate expected missing fraction from normalized injury status."""
        st = str(status_str).lower().strip()
        if st in ("out", "suspended"):
            return 1.0
        if st == "doubtful":
            return 0.85
        if st == "questionable":
            return 0.50
        if st in ("day-to-day", "gtd", "d2d"):
            return 0.40
        if st == "probable":
            return 0.10
        return 0.0

    if team_abbr:
        raw_tm = get_team_injuries(team_abbr, all_injuries)
        for inj in raw_tm:
            inj_name = inj.get("player_name", "")
            if inj_name.lower() != player_name.lower():
                b_min = get_player_baseline_minutes(inj_name)
                norm_st = normalize_injury_status(inj.get("status", ""))
                weight = compute_absence_weight(norm_st)
                miss_min = round(b_min * weight, 1)

                rec = InjuryRecord(
                    player_name=inj_name,
                    status=norm_st,
                    short_comment=inj.get("short_comment", ""),
                    long_comment=inj.get("long_comment"),
                    date=inj.get("date"),
                    position=inj.get("position"),
                    baseline_minutes=b_min,
                    missing_minutes=miss_min,
                )
                if miss_min > 0:
                    tm_missing_mins += miss_min
                    tm_lost_minutes_list.append(miss_min)
                teammate_injs.append(rec)

    opp_abbr = req.opponent_override or (upcoming_info["opponent"] if upcoming_info else None)
    if opp_abbr:
        raw_opp = get_team_injuries(opp_abbr, all_injuries)
        for inj in raw_opp:
            inj_name = inj.get("player_name", "")
            b_min = get_player_baseline_minutes(inj_name)
            norm_st = normalize_injury_status(inj.get("status", ""))
            weight = compute_absence_weight(norm_st)
            miss_min = round(b_min * weight, 1)

            rec = InjuryRecord(
                player_name=inj_name,
                status=norm_st,
                short_comment=inj.get("short_comment", ""),
                long_comment=inj.get("long_comment"),
                date=inj.get("date"),
                position=inj.get("position"),
                baseline_minutes=b_min,
                missing_minutes=miss_min,
            )
            if miss_min > 0:
                opp_missing_mins += miss_min
            opponent_injs.append(rec)

    tm_lost_minutes_list.sort(reverse=True)
    tm_top2_lost = sum(tm_lost_minutes_list[:2])

    days_since_last = float(row_features.get("days_since_last_appearance", 2.0)) if row_features is not None else 2.0
    is_long_ret = (days_since_last >= 14.0)

    part_model = ParticipationModel()
    pi_part = part_model.predict_p_active(p_status)

    cond_input = dict(row_features) if row_features else {}
    cond_input["player_id"] = player_id
    cond_input["injury_status"] = p_status
    cond_input["days_since_last_appearance"] = days_since_last
    cond_input["return_candidate"] = is_long_ret
    cond_input["pi_participate"] = pi_part

    has_valid_model = (stat in BUNDLES) or (f"lgbm_{stat}" in MODELS)
    has_valid_prior = (row_features is not None and (f"{stat}_roll_mean_5" in row_features or f"{stat}_shrinkage_mean" in row_features))

    condition = assess_player_condition(
        row=cond_input,
        has_valid_model=has_valid_model,
        has_valid_prior=has_valid_prior,
    )

    own_status_code_map = {
        "available": 0.0,
        "healthy": 0.0,
        "not_listed": 0.0,
        "probable": 0.0,
        "day-to-day": 1.0,
        "questionable": 1.0,
        "doubtful": 2.0,
        "out": 3.0,
        "unknown": 0.0,
    }
    own_status_code = own_status_code_map.get(str(p_status).lower().strip(), 0.0)

    # Inject features for model
    if row_features is not None:
        if isinstance(row_features, pd.Series):
            row_features = row_features.to_dict()
        row_features["days_since_last_appearance"] = float(days_since_last)
        row_features["is_long_absence_return"] = float(is_long_ret)
        row_features["games_since_return"] = 0.0 if is_long_ret else 5.0
        row_features["own_status_code"] = float(own_status_code)
        row_features["own_is_questionable"] = 1.0 if own_status_code >= 1.0 else 0.0
        row_features["pi_participate"] = float(pi_part)
        row_features["teammate_missing_minutes"] = float(tm_missing_mins)
        row_features["teammate_missing_fga"] = float(tm_missing_mins * 0.40)
        row_features["teammate_missing_ast"] = float(tm_missing_mins * 0.10)
        row_features["teammate_missing_pts"] = float(tm_missing_mins * 0.55)
        row_features["teammate_top2_lost_minutes"] = float(tm_top2_lost)
        row_features["opp_missing_minutes"] = float(opp_missing_mins)
        row_features["opp_missing_fga"] = float(opp_missing_mins * 0.40)
        row_features["opp_missing_ast"] = float(opp_missing_mins * 0.10)
        row_features["opp_missing_pts"] = float(opp_missing_mins * 0.55)

    from src.features.injury_roles import evaluate_injury_context_support
    ctx_support = evaluate_injury_context_support(tm_missing_mins)
    if not ctx_support["is_supported"]:
        if ctx_support["reason_code"] not in condition.get("reason_codes", []):
            condition.setdefault("reason_codes", []).append(ctx_support["reason_code"])
        # Maintain strict condition hierarchy: do NOT override if player is OUT or forecast_status is already not_issued
        if condition.get("forecast_status") != "not_issued" and condition.get("operational_state") not in ("OUT", "NOT_ISSUED"):
            condition["operational_state"] = "SCENARIO_ONLY"
            condition["status"] = "SCENARIO_ONLY"
            condition["forecast_status"] = "conditional_scenario"
            condition["action"] = f"Extreme teammate missing minutes ({tm_missing_mins:.1f}m > 45% team capacity). Outputting conditional scenario diagnostics."

    readiness_eval = evaluate_injury_readiness(
        player_status=p_status,
        n_games_history=int(row_features.get("n_games_history", 10)) if row_features is not None else 10,
        days_since_last=days_since_last,
        is_stale_report=is_stale_inj,
    )

    # 4b. Defense vs Position (DvP) Context Resolution & Injection (§11, §12)
    active_opp = req.opponent_override or (upcoming_info["opponent"] if upcoming_info else None) or (row_features.get("opponent_abbr") if row_features else "MIA")
    target_dvp = None
    try:
        from src.features.dvp_context import resolve_player_target_dvp
        target_dvp = resolve_player_target_dvp(
            player_id=player_id,
            opponent_abbr=active_opp,
            player_logs_df=PLAYER_LOGS_DF if PLAYER_LOGS_DF is not None else pd.DataFrame(),
            team_logs_df=TEAM_LOGS_DF if TEAM_LOGS_DF is not None else pd.DataFrame(),
        )
        if target_dvp and row_features is not None:
            for k, v in target_dvp.items():
                if k.startswith("dvp_"):
                    row_features[k] = float(v) if not isinstance(v, bool) else (1.0 if v else 0.0)
    except Exception as e:
        logger.warning(f"Error resolving target DvP context: {e}")

    # 5. Predict expected value mu and distribution
    active_bundle = BUNDLES.get(stat)
    line_probs = None
    pricing_info = None
    mu = 10.0 if stat == "pts" else 3.0
    median_val = mu
    interval_info = {"lower": max(0.0, mu - 3.0), "upper": mu + 3.0}
    pmf_list = []

    if active_bundle is not None and row_features is not None:
        df_single = pd.DataFrame([row_features if isinstance(row_features, dict) else row_features.to_dict()])
        dist = active_bundle.predict_distribution(df_single)
        mu = dist.mean()
        median_val = dist.median()
        interval_info = dist.prediction_interval(0.90)
        prefix = dist.prefix_pmf(max(60, int(mu + 10)))
        pmf_list = [PMFItem(value=int(k), prob=round(float(p), 4)) for k, p in enumerate(prefix) if p > 0.001 or k <= int(mu) + 5]

        if req.line is not None and condition.get("forecast_status") != "not_issued":
            raw_probs = dist.calculate_line_probabilities(req.line)
            line_probs = LineProbabilities(**raw_probs)
            pricing_info = evaluate_market_pricing(req, raw_probs)
    else:
        # Legacy fallback
        model_key = f"lgbm_{stat}"
        mu = 10.0 if stat == "pts" else 3.0

        if model_key in MODELS and row_features is not None and FEATURES_META:
            feature_vals = [float(row_features.get(c, 0.0) if not pd.isna(row_features.get(c)) else 0.0) for c in FEATURES_META]
            X = np.array([feature_vals])
            booster = MODELS[model_key]
            raw_pred = booster.predict(X)[0]
            mu = max(float(raw_pred), 0.5)
        elif row_features is not None:
            mu = float(row_features.get(f"{stat}_roll_mean_5", mu))

        base_phi = 0.04 if stat == "pts" else (0.08 if stat == "reb" else 0.09)
        n_eff = float(row_features.get(f"{stat}_n_eff", 0.0)) if row_features is not None else 0.0
        is_ret = condition["flags"].get("returning_from_rest", False)
        adjusted_phi = adjust_dispersion_for_uncertainty(base_phi, n_eff, is_returning=is_ret, mode="pooled")

        dist = DIST_ENGINE.get_distribution(mu=mu, phi=adjusted_phi)
        mu = dist.mean()
        median_val = dist.median()
        interval_info = dist.prediction_interval(0.90)

        if req.line is not None and condition.get("forecast_status") != "not_issued":
            raw_probs = dist.calculate_line_probabilities(req.line)
            line_probs = LineProbabilities(**raw_probs)
            pricing_info = evaluate_market_pricing(req, raw_probs)

        prefix = dist.prefix_pmf(max(60, int(mu + 10)))
        pmf_list = [PMFItem(value=int(k), prob=round(float(p), 4)) for k, p in enumerate(prefix) if p > 0.001 or k <= int(mu) + 5]

    # Unconditional settlement
    unconditional_settle = None
    if line_probs is not None:
        unconditional_settle = compute_unconditional_settlement(
            conditional_probs=line_probs.model_dump(),
            pi_participate=pi_part,
        )

    injury_impact_info = {
        "pi_participate": pi_part,
        "participation_probability_semantics": "entered_game",
        "teammate_missing_minutes": round(tm_missing_mins, 1),
        "teammate_top2_lost_minutes": round(tm_top2_lost, 1),
        "opp_missing_minutes": round(opp_missing_mins, 1),
        "own_return_days": days_since_last,
        "allocator_mode": "research_eligibility_only",
        "scenario_weights_validated": False,
    }

    # Contexts
    schedule_context = None
    opponent_context = None
    if row_features is not None:
        schedule_context = ScheduleContext(
            team_b2b=bool(row_features.get("team_b2b", 0) == 1),
            opp_b2b=bool(row_features.get("opp_b2b", 0) == 1),
            team_rest_days=int(row_features.get("team_rest_days", 2)),
            opp_rest_days=int(row_features.get("opp_rest_days", 2)),
            rest_advantage_days=int(row_features.get("rest_advantage_days", 0)),
            team_3in4=bool(row_features.get("team_3in4", 0) == 1),
            team_4in6=bool(row_features.get("team_4in6", 0) == 1),
            player_played_previous_team_game=bool(row_features.get("player_played_previous_team_game", 1) == 1),
            team_b2b_but_player_rested=bool(row_features.get("team_b2b_but_player_rested", 0) == 1),
            player_minutes_last7days=round(float(row_features.get("player_minutes_last7days", 0.0)), 1),
        )

        opponent_context = OpponentContext(
            opponent_abbr=req.opponent_override or str(row_features.get("opponent_abbr", "OPP")),
            opp_pace_prev10=round(float(row_features.get("opp_pace_prev10", 100.0)), 2),
            opp_def_rating_prev10=round(float(row_features.get("opp_def_rating_prev10", 115.0)), 2),
            opp_ast_allowed_per100_prev10=round(float(row_features.get("opp_ast_allowed_per100_prev10", 25.0)), 2),
            opp_dreb_share_prev10=round(float(row_features.get("opp_dreb_share_prev10", 0.75)), 3),
            opp_fg3a_share_prev10=round(float(row_features.get("opp_fg3a_share_prev10", 0.40)), 3),
            opp_pts_allowed_per100=round(float(row_features.get("opp_pts_allowed_per100_shrunk_prev10", 114.0)), 1) if "opp_pts_allowed_per100_shrunk_prev10" in row_features else None,
            opp_pts_rank_asc=float(row_features.get("opp_pts_allowed_rank_asc_prev10", 15.5)) if "opp_pts_allowed_rank_asc_prev10" in row_features else None,
            opp_pts_pct_asc=round(float(row_features.get("opp_pts_allowed_pct_asc_prev10", 0.5)), 2) if "opp_pts_allowed_pct_asc_prev10" in row_features else None,
            opp_fg3m_allowed_per100=round(float(row_features.get("opp_fg3m_allowed_per100_shrunk_prev10", 13.0)), 1) if "opp_fg3m_allowed_per100_shrunk_prev10" in row_features else None,
            opp_fg3m_rank_asc=float(row_features.get("opp_fg3m_allowed_rank_asc_prev10", 15.5)) if "opp_fg3m_allowed_rank_asc_prev10" in row_features else None,
            opp_blocks_made_per100=round(float(row_features.get("opp_blocks_made_per100_shrunk_prev10", 5.0)), 1) if "opp_blocks_made_per100_shrunk_prev10" in row_features else None,
            opp_blocks_rank_asc=float(row_features.get("opp_blocks_made_rank_asc_prev10", 15.5)) if "opp_blocks_made_rank_asc_prev10" in row_features else None,
        )

    # 7. Defense vs Position (DvP) Context (§11, §12)
    dvp_ctx = None
    try:
        if target_dvp is None:
            from src.features.dvp_context import resolve_player_target_dvp
            active_opp = opponent_context.opponent_abbr if opponent_context else "OPP"
            target_dvp = resolve_player_target_dvp(
                player_id=player_id,
                opponent_abbr=active_opp,
                player_logs_df=PLAYER_LOGS_DF if PLAYER_LOGS_DF is not None else pd.DataFrame(),
                team_logs_df=TEAM_LOGS_DF if TEAM_LOGS_DF is not None else pd.DataFrame(),
            )
        if target_dvp is not None:
            dvp_ctx = DvpContext(
            player_id=player_id,
            position_raw=target_dvp["position_raw"],
            position_group=target_dvp["position_group"],
            opponent_abbr=target_dvp["opponent_abbr"],
            dvp_supported=target_dvp["dvp_supported"],
            pts=DvpStatDetail(
                volume_per100=target_dvp["dvp_pts_volume_per100"],
                rank_asc=target_dvp["dvp_pts_volume_rank_asc"],
                minrate=target_dvp["dvp_pts_minrate"],
                minrate_rank_asc=target_dvp["dvp_pts_minrate_rank_asc"],
            ),
            reb=DvpStatDetail(
                volume_per100=target_dvp["dvp_reb_volume_per100"],
                rank_asc=target_dvp["dvp_reb_volume_rank_asc"],
                minrate=target_dvp["dvp_reb_minrate"],
                minrate_rank_asc=target_dvp["dvp_reb_minrate_rank_asc"],
            ),
            ast=DvpStatDetail(
                volume_per100=target_dvp["dvp_ast_volume_per100"],
                rank_asc=target_dvp["dvp_ast_volume_rank_asc"],
                minrate=target_dvp["dvp_ast_minrate"],
                minrate_rank_asc=target_dvp["dvp_ast_minrate_rank_asc"],
            ),
        )
    except Exception as e:
        logger.warning(f"Error resolving target DvP context: {e}")

    return PredictResponse(
        player_id=player_id,
        player_name=player_name,
        team_abbreviation=team_abbr,
        stat=stat.upper(),
        expected_value=round(float(mu), 2),
        median=median_val,
        prediction_interval=PredictionInterval(**interval_info),
        line_probabilities=line_probs,
        pricing=pricing_info,
        pmf=pmf_list,
        condition=condition,
        schedule_context=schedule_context,
        opponent_context=opponent_context,
        dvp_context=dvp_ctx,
        upcoming_game_info=upcoming_info,
        player_injury=player_inj,
        teammate_injuries=teammate_injs,
        opponent_injuries=opponent_injs,
        readiness=readiness_eval,
        unconditional_settlement=unconditional_settle,
        injury_impact=injury_impact_info,
    )
