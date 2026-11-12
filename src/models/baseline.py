"""
Module: Baselines & Deviance Metrics (§10.1, §10.2, §5 of Stats-Only Model Selection Spec)
Provides:
- Mean Poisson deviance calculation with exact y*log(y/mu) limit at y=0
- WeightedAverageBaseline for K in {5, 10, 20} with exponential decay fallback
- MinutesRateBaseline predicting historical/shrunk minutes * rate shrinkage
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, Any


def calculate_poisson_deviance(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Compute mean Poisson deviance:
    d(y, mu) = 2 * (y * log(y / mu) - (y - mu))
    When y = 0, y * log(y / mu) -> 0, so d(0, mu) = 2 * mu (§10.2).
    """
    y = np.maximum(np.asarray(y_true, dtype=np.float64), 0.0)
    mu = np.maximum(np.asarray(y_pred, dtype=np.float64), 1e-6)

    pos_mask = y > 0
    dev = np.zeros_like(y, dtype=np.float64)

    dev[pos_mask] = 2.0 * (y[pos_mask] * np.log(y[pos_mask] / mu[pos_mask]) - (y[pos_mask] - mu[pos_mask]))
    dev[~pos_mask] = 2.0 * mu[~pos_mask]

    return float(np.mean(dev))


class WeightedAverageBaseline:
    """
    Baseline predicting recent weighted rolling average (§5.1).
    Supports K in {5, 10, 20} played appearances.
    Fallbacks: larger windows if available, followed by group prior rate * minutes.
    """

    def __init__(self, stat: str = "pts", k: int = 5):
        self.stat = stat.lower()
        self.k = k
        self.default_prior = 10.0 if self.stat == "pts" else (4.0 if self.stat == "reb" else 2.5)

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        primary_col = f"{self.stat}_roll_mean_{self.k}"

        if primary_col in df.columns:
            preds = df[primary_col].copy()
            # Hierarchical fallback if NaN or missing
            candidate_fallbacks = [f"{self.stat}_roll_mean_{w}" for w in [5, 10, 20] if w != self.k]
            candidate_fallbacks.append(f"{self.stat}_decay_mean")
            for fb in candidate_fallbacks:
                if fb in df.columns:
                    preds = preds.fillna(df[fb])
            
            # Prior fallback
            prior_min = df.get("min_roll_mean_5", pd.Series([25.0] * len(df))).fillna(25.0)
            prior_rate = df.get(f"{self.stat}_rate_shrinkage", pd.Series([self.default_prior / 25.0] * len(df)))
            prior_baseline = (prior_min * prior_rate).fillna(self.default_prior)
            preds = preds.fillna(prior_baseline)
            return np.maximum(preds.to_numpy(dtype=np.float64), 0.1)

        # Fallback if primary col does not exist in df
        return np.full(len(df), self.default_prior, dtype=np.float64)


class MinutesRateBaseline:
    """
    Baseline predicting pregame minutes estimate * Gamma-Poisson rate shrinkage (§5.2):
    mu_MR = m_hat(C) * rho_shrunk(C)
    """

    def __init__(self, stat: str = "pts"):
        self.stat = stat.lower()
        self.default_rate = 0.5 if self.stat == "pts" else (0.15 if self.stat == "reb" else 0.12)
        self.default_minutes = 25.0

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        min_col = "min_roll_mean_5"
        rate_col = f"{self.stat}_rate_shrinkage"

        minutes = df.get(min_col, pd.Series([self.default_minutes] * len(df))).fillna(self.default_minutes)
        rates = df.get(rate_col, pd.Series([self.default_rate] * len(df))).fillna(self.default_rate)

        preds = (minutes * rates).to_numpy(dtype=np.float64)
        return np.maximum(preds, 0.1)
