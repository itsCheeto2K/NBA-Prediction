import logging
import sys
from pathlib import Path
import pandas as pd

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.features.builder import build_feature_dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_features")

def main():
    settings.create_dirs()
    seasons = ["2023-24", "2024-25", "2025-26"]
    
    logger.info("Loading backfilled Parquet datasets...")
    player_dfs = []
    team_dfs = []
    
    for s in seasons:
        p_path = settings.PARQUET_DIR / f"player_gamelogs_{s}.parquet"
        t_path = settings.PARQUET_DIR / f"team_gamelogs_{s}.parquet"
        
        if p_path.exists():
            pdf = pd.read_parquet(p_path)
            player_dfs.append(pdf)
            logger.info(f"Loaded {len(pdf)} player logs from {p_path.name}")
        else:
            logger.warning(f"File not found: {p_path}")
            
        if t_path.exists():
            tdf = pd.read_parquet(t_path)
            team_dfs.append(tdf)
            logger.info(f"Loaded {len(tdf)} team logs from {t_path.name}")
            
    if not player_dfs:
        logger.error("No player gamelogs found to process!")
        return
        
    combined_players = pd.concat(player_dfs, ignore_index=True)
    combined_teams = pd.concat(team_dfs, ignore_index=True) if team_dfs else None
    
    logger.info(f"Total player-game records across seasons: {len(combined_players)}")
    
    # Run Feature Pipeline
    features_df = build_feature_dataset(
        player_logs_df=combined_players,
        team_logs_df=combined_teams,
    )
    
    out_all_path = settings.PARQUET_DIR / "features_all_seasons.parquet"
    features_df.to_parquet(out_all_path, index=False)
    logger.info(f"Saved full feature dataset ({len(features_df)} rows, {len(features_df.columns)} columns) to {out_all_path}")
    
    # Also save per season
    for s in seasons:
        s_df = features_df[features_df["season"] == s]
        if not s_df.empty:
            s_out = settings.PARQUET_DIR / f"features_{s}.parquet"
            s_df.to_parquet(s_out, index=False)
            logger.info(f"Saved {len(s_df)} feature rows for {s} to {s_out.name}")

if __name__ == "__main__":
    main()
