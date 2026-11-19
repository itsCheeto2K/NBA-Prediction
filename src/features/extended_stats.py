"""Pregame box-score profiles. Every aggregate excludes the current game.

Percentages are ratios of historical totals, never averages of percentages.
Unavailable advanced metrics are deliberately not estimated from box scores.
"""
import numpy as np
import pandas as pd

RAW_STATS = ("pts", "reb", "ast", "min", "fgm", "fga", "fg3m", "fg3a",
             "ftm", "fta", "oreb", "dreb", "stl", "blk", "tov", "pf", "plus_minus")
COUNTS = RAW_STATS + ("fg2m", "fg2a", "double_double", "triple_double")
RATIOS = ("fg_pct", "fg2_pct", "fg3_pct", "ft_pct", "ts_pct", "efg_pct", "ast_to")
WINDOWS = (5, 10, 20, "season")
EXTENDED_FEATURE_COLS = [f"ext_{name}_{window}" for window in WINDOWS for name in COUNTS + RATIOS]
RECIPE_VERSION = "extended_boxscore_v1"
UNAVAILABLE_ADVANCED = ("usage_pct", "offensive_rating", "defensive_rating", "per")


def compute_extended_stats(frame: pd.DataFrame) -> pd.DataFrame:
    """Return new features with NaN for unknown/zero-exposure observations.

    Rolling profiles span seasons, as do the existing rolling features; the
    season profile resets at each season boundary. Input must be one row per
    player/game. Counts below are per-game means, including DD/TD frequencies.
    """
    df = frame.sort_values(["player_id", "game_date", "game_id"]).reset_index(drop=True).copy()
    raw = pd.DataFrame({c: pd.to_numeric(df[c], errors="coerce") if c in df
                        else pd.Series(np.nan, index=df.index) for c in RAW_STATS})
    # DNP rows must not count as a zero-point played game.
    raw.loc[raw["min"].isna() | raw["min"].le(0), :] = np.nan
    raw["fg2m"] = (raw.fgm - raw.fg3m).clip(lower=0)
    raw["fg2a"] = (raw.fga - raw.fg3a).clip(lower=0)
    categories = raw[["pts", "reb", "ast", "stl", "blk"]]
    known = categories.notna().all(axis=1)
    tens = categories.ge(10).sum(axis=1)
    raw["double_double"] = tens.ge(2).astype(float).where(known)
    raw["triple_double"] = tens.ge(3).astype(float).where(known)
    ratio_pairs = {
        "fg_pct": (raw.fgm, raw.fga), "fg2_pct": (raw.fg2m, raw.fg2a),
        "fg3_pct": (raw.fg3m, raw.fg3a), "ft_pct": (raw.ftm, raw.fta),
        "ts_pct": (raw.pts, 2 * (raw.fga + .44 * raw.fta)),
        "efg_pct": (raw.fgm + .5 * raw.fg3m, raw.fga), "ast_to": (raw.ast, raw.tov),
    }
    for name, (numerator, denominator) in ratio_pairs.items():
        valid = numerator.notna() & denominator.notna()
        raw[f"{name}_num"] = numerator.where(valid)
        raw[f"{name}_den"] = denominator.where(valid)
    outputs = {}
    for window in WINDOWS:
        keys = [df["player_id"], df["season"]] if window == "season" and "season" in df else df["player_id"]
        # Shift within the same grouping used for the subsequent accumulation.
        lagged = raw.groupby(keys, sort=False).shift(1)
        grouped = lagged.groupby(keys, sort=False)
        if window == "season":
            sums = grouped.cumsum()
            counts = lagged.notna().astype(float).groupby(keys, sort=False).cumsum()
        else:
            sums = grouped.rolling(window, min_periods=1).sum().droplevel(0).reindex(df.index)
            counts = grouped.rolling(window, min_periods=1).count().droplevel(0).reindex(df.index)
        means = sums / counts.replace(0, np.nan)
        for name in COUNTS:
            outputs[f"ext_{name}_{window}"] = means[name]
        for name in RATIOS:
            numerator, denominator = sums[f"{name}_num"], sums[f"{name}_den"]
            outputs[f"ext_{name}_{window}"] = numerator / denominator.where(denominator > 0)
    return pd.concat([df.drop(columns=list(outputs), errors="ignore"), pd.DataFrame(outputs, index=df.index)], axis=1)
