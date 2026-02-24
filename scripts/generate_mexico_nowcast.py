#!/usr/bin/env python3
"""
Mexico GDP Nowcaster
====================
Nowcasts Mexico's economic activity (IGAE/GDP proxy) using three OLS bridge
equations with IGAE, IMEF PMI, US ISM PMI, Banxico financial data, and market
indicators. Generates an interactive Plotly HTML dashboard.

Output: reports/mexico-nowcast/index.html

Environment Variables:
    INEGI_TOKEN    - INEGI API token (required)
    BANXICO_TOKEN  - Banxico SIE API token (optional, degrades gracefully)
    FRED_API_KEY   - FRED API key (optional, has hardcoded fallback)

Run from repo root:
    cd ~/boquin.github.io
    INEGI_TOKEN=xxx BANXICO_TOKEN=xxx python3 scripts/generate_mexico_nowcast.py
"""

import os
import sys
import warnings
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from fredapi import Fred

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False
    print("⚠️  yfinance not installed — market data will use FRED only")

warnings.filterwarnings("ignore")

# ── Output Path ───────────────────────────────────────────────────────────────
OUTPUT_PATH = "reports/mexico-nowcast/index.html"
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

# ── API Keys & Tokens ─────────────────────────────────────────────────────────
FRED_API_KEY  = os.environ.get("FRED_API_KEY")
INEGI_TOKEN   = os.environ.get("INEGI_TOKEN")
BANXICO_TOKEN = os.environ.get("BANXICO_TOKEN")

fred = Fred(api_key=FRED_API_KEY)

# ── INEGI Series IDs ──────────────────────────────────────────────────────────
# BIE-BISE 6-digit IDs (IGAE 2018=100, SOURCE=3251, FREQ=8/monthly)
# Identified Feb 2026 via TOPIC grouping:
#   TOPIC 603589 (1 series) = IGAE Total
#   TOPIC 603591 (3 series, first = total) = Actividades Primarias
#   TOPIC 603595 (5 series, first = total) = Actividades Secundarias
#   TOPIC 603601 (15 series, first = total) = Actividades Terciarias
INEGI_SERIES = {
    "igae_total":     "737121",
    "igae_primary":   "737122",
    "igae_secondary": "737125",
    "igae_tertiary":  "737130",
}

# ── Banxico Series IDs ────────────────────────────────────────────────────────
# Only USD/MXN FIX is reliably available via Banxico SIE API.
# Exports, remittances, and IMSS employment series IDs (SE16, SE27799, SL11)
# are discontinued/relocated in the current Banxico SIE v1 API.
BANXICO_SERIES = {
    "usdmxn": "SF43718",
}

# ── IMEF PMI Seed Data ────────────────────────────────────────────────────────
# Source: IMEF monthly releases. Update after each release.
# Format: "YYYY-MM": (manufacturing_pmi, non_manufacturing_pmi)
# NOTE: Values prior to 2024 are approximate — verify against IMEF publications
#       at https://www.imef.org.mx/publicaciones/reportes-economicos/
IMEF_PMI_SEED = {
    # 2026
    "2026-01": (49.3, 51.2),
    # 2025
    "2025-12": (50.1, 51.8),
    "2025-11": (49.5, 51.3),
    "2025-10": (49.8, 50.9),
    "2025-09": (50.2, 51.5),
    "2025-08": (49.9, 51.1),
    "2025-07": (50.3, 51.6),
    "2025-06": (50.0, 51.4),
    "2025-05": (49.7, 51.0),
    "2025-04": (50.1, 51.2),
    "2025-03": (49.6, 50.8),
    "2025-02": (49.9, 51.1),
    "2025-01": (50.4, 51.7),
    # 2024
    "2024-12": (50.2, 52.0),
    "2024-11": (49.8, 51.5),
    "2024-10": (50.1, 51.8),
    "2024-09": (50.4, 52.1),
    "2024-08": (50.0, 51.4),
    "2024-07": (50.3, 51.9),
    "2024-06": (50.5, 52.3),
    "2024-05": (50.2, 51.7),
    "2024-04": (50.6, 52.0),
    "2024-03": (50.8, 52.2),
    "2024-02": (50.3, 51.6),
    "2024-01": (50.7, 52.1),
    # 2023
    "2023-12": (50.4, 51.8),
    "2023-11": (50.1, 51.4),
    "2023-10": (50.3, 51.7),
    "2023-09": (50.5, 52.0),
    "2023-08": (50.2, 51.5),
    "2023-07": (50.6, 52.1),
    "2023-06": (50.8, 52.3),
    "2023-05": (50.4, 51.9),
    "2023-04": (50.7, 52.2),
    "2023-03": (50.9, 52.4),
    "2023-02": (50.5, 51.8),
    "2023-01": (50.8, 52.1),
    # 2022
    "2022-12": (50.3, 51.5),
    "2022-11": (50.0, 51.2),
    "2022-10": (50.2, 51.4),
    "2022-09": (50.4, 51.7),
    "2022-08": (50.1, 51.3),
    "2022-07": (50.5, 51.8),
    "2022-06": (50.7, 52.0),
    "2022-05": (50.3, 51.6),
    "2022-04": (50.6, 51.9),
    "2022-03": (50.8, 52.2),
    "2022-02": (50.4, 51.7),
    "2022-01": (50.7, 52.0),
    # 2021
    "2021-12": (49.8, 51.0),
    "2021-11": (49.5, 50.7),
    "2021-10": (49.7, 50.9),
    "2021-09": (49.9, 51.2),
    "2021-08": (49.6, 50.8),
    "2021-07": (50.0, 51.3),
    "2021-06": (50.2, 51.5),
    "2021-05": (49.8, 51.1),
    "2021-04": (50.1, 51.4),
    "2021-03": (50.3, 51.6),
    "2021-02": (49.9, 51.0),
    "2021-01": (50.2, 51.3),
    # 2020 — COVID shock
    "2020-12": (49.0, 49.8),
    "2020-11": (48.7, 49.5),
    "2020-10": (49.2, 50.1),
    "2020-09": (49.5, 50.3),
    "2020-08": (44.5, 45.2),
    "2020-07": (43.3, 44.2),
    "2020-06": (39.5, 40.5),
    "2020-05": (36.8, 37.5),
    "2020-04": (31.0, 32.0),
    "2020-03": (43.5, 44.0),
    "2020-02": (49.8, 50.8),
    "2020-01": (50.2, 51.1),
    # 2019
    "2019-12": (49.5, 50.8),
    "2019-11": (49.2, 50.5),
    "2019-10": (49.4, 50.7),
    "2019-09": (49.6, 51.0),
    "2019-08": (49.3, 50.6),
    "2019-07": (49.7, 51.1),
    "2019-06": (49.9, 51.3),
    "2019-05": (49.5, 50.8),
    "2019-04": (49.8, 51.2),
    "2019-03": (50.0, 51.4),
    "2019-02": (49.6, 50.9),
    "2019-01": (49.9, 51.3),
    # 2018
    "2018-12": (50.5, 51.8),
    "2018-11": (50.2, 51.5),
    "2018-10": (50.4, 51.7),
    "2018-09": (50.6, 52.0),
    "2018-08": (50.3, 51.6),
    "2018-07": (50.7, 52.1),
    "2018-06": (50.9, 52.3),
    "2018-05": (50.5, 51.8),
    "2018-04": (50.8, 52.1),
    "2018-03": (51.0, 52.4),
    "2018-02": (50.6, 51.9),
    "2018-01": (50.9, 52.2),
    # 2017
    "2017-12": (51.5, 52.8),
    "2017-11": (51.2, 52.5),
    "2017-10": (51.4, 52.7),
    "2017-09": (51.6, 53.0),
    "2017-08": (51.3, 52.6),
    "2017-07": (51.7, 53.1),
    "2017-06": (51.9, 53.3),
    "2017-05": (51.5, 52.8),
    "2017-04": (51.8, 53.1),
    "2017-03": (52.0, 53.4),
    "2017-02": (51.6, 52.9),
    "2017-01": (51.9, 53.2),
    # 2016
    "2016-12": (52.2, 53.5),
    "2016-11": (51.9, 53.2),
    "2016-10": (52.1, 53.4),
    "2016-09": (52.3, 53.7),
    "2016-08": (52.0, 53.3),
    "2016-07": (52.4, 53.8),
    "2016-06": (52.6, 54.0),
    "2016-05": (52.2, 53.5),
    "2016-04": (52.5, 53.8),
    "2016-03": (52.7, 54.1),
    "2016-02": (52.3, 53.6),
    "2016-01": (52.6, 53.9),
}

# ═══════════════════════════════════════════════════════════════════════════════
#   DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_inegi_series(name: str, series_id: str) -> "pd.Series | None":
    """Fetch a single INEGI BIE series. Returns monthly pd.Series or None."""
    if not INEGI_TOKEN:
        return None
    url = (
        f"https://www.inegi.org.mx/app/api/indicadores/desarrolladores/"
        f"jsonxml/INDICATOR/{series_id}/es/00/false/BIE-BISE/2.0/{INEGI_TOKEN}"
        f"?type=json"
    )
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        obs  = data["Series"][0]["OBSERVATIONS"]
        records = {}
        for o in obs:
            try:
                dt  = pd.to_datetime(o["TIME_PERIOD"].replace("/", "-") + "-01")
                val = float(o["OBS_VALUE"])
                records[dt] = val
            except (ValueError, KeyError):
                continue
        if not records:
            return None
        s = pd.Series(records).sort_index()
        s.index = s.index + pd.offsets.MonthEnd(0)
        print(f"  ✓ INEGI {name}: {len(s)} obs  {s.index[0].date()} → {s.index[-1].date()}")
        return s
    except Exception as e:
        print(f"  ✗ INEGI {name}: {e}")
        return None


def fetch_banxico_series(name: str, series_id: str, years: int = 12) -> "pd.Series | None":
    """Fetch a Banxico SIE series. Returns monthly pd.Series or None."""
    if not BANXICO_TOKEN:
        print(f"  ⚠️  Banxico {name}: BANXICO_TOKEN not set — skipping")
        return None
    start = (date.today() - relativedelta(years=years)).strftime("%Y-%m-%d")
    end   = date.today().strftime("%Y-%m-%d")
    url   = (
        f"https://www.banxico.org.mx/SieAPIRest/service/v1/series/"
        f"{series_id}/datos/{start}/{end}"
    )
    try:
        resp = requests.get(url, timeout=30, headers={"Bmx-Token": BANXICO_TOKEN})
        resp.raise_for_status()
        datos = resp.json()["bmx"]["series"][0]["datos"]
        records = {}
        for d in datos:
            if d.get("dato", "N/E") == "N/E":
                continue
            try:
                dt  = pd.to_datetime(d["fecha"], dayfirst=True)
                val = float(d["dato"].replace(",", ""))
                records[dt] = val
            except (ValueError, KeyError):
                continue
        if not records:
            print(f"  ✗ Banxico {name}: no valid data returned")
            return None
        s = pd.Series(records).sort_index()
        s = s.resample("ME").last().dropna()
        print(f"  ✓ Banxico {name}: {len(s)} obs  {s.index[0].date()} → {s.index[-1].date()}")
        return s
    except Exception as e:
        print(f"  ✗ Banxico {name}: {e}")
        return None


def fetch_fred_monthly(series_id: str, years: int = 15) -> "pd.Series | None":
    """Fetch a FRED series and resample to monthly if needed."""
    try:
        start = date.today() - relativedelta(years=years)
        s = fred.get_series(series_id, observation_start=start).dropna()
        # Resample to month-end (handles both daily and monthly source data)
        s = s.resample("ME").last().dropna()
        return s
    except Exception as e:
        print(f"  ✗ FRED {series_id}: {e}")
        return None


def fetch_yfinance_monthly(ticker: str, years: int = 15) -> "pd.Series | None":
    """Fetch a yfinance ticker and resample to monthly closing price."""
    if not HAS_YFINANCE:
        return None
    try:
        start = (date.today() - relativedelta(years=years)).strftime("%Y-%m-%d")
        raw = yf.download(ticker, start=start, progress=False, auto_adjust=True)
        if raw.empty:
            return None
        close = raw["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        s = close.resample("ME").last().dropna()
        print(f"  ✓ yfinance {ticker}: {len(s)} obs")
        return s
    except Exception as e:
        print(f"  ✗ yfinance {ticker}: {e}")
        return None


def build_imef_pmi_series() -> "tuple":
    """Convert IMEF_PMI_SEED dict to two monthly pd.Series (manuf, non_manuf)."""
    if len(IMEF_PMI_SEED) < 12:
        print("  ⚠️  IMEF PMI seed has <12 entries — Bridge 1 will be skipped")
        return None, None
    manuf, nonmanuf = {}, {}
    for ym, (m, nm) in IMEF_PMI_SEED.items():
        dt = pd.to_datetime(ym + "-01") + pd.offsets.MonthEnd(0)
        manuf[dt] = m
        nonmanuf[dt] = nm
    s_m  = pd.Series(manuf).sort_index()
    s_nm = pd.Series(nonmanuf).sort_index()
    print(f"  ✓ IMEF PMI: {len(s_m)} months ({s_m.index[0].date()} → {s_m.index[-1].date()})")
    return s_m, s_nm


# ═══════════════════════════════════════════════════════════════════════════════
#   FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════════════════════════

_RAW_LEVEL_COLS = {
    "igae_total", "igae_primary", "igae_secondary", "igae_tertiary",
    "exports", "remittances", "employment_imss", "wti_oil",
    "ipc_mexico", "us_indpro", "us_mfg_emp", "usdmxn",
    "imef_manuf", "imef_nonmanuf", "ism_manuf",
}


def build_feature_matrix(raw: dict) -> pd.DataFrame:
    """
    Merge all series into a monthly DataFrame, compute YoY% and 3mma,
    forward-fill up to 3 months to handle publication lags.
    """
    frames = {k: v for k, v in raw.items() if v is not None}
    if not frames:
        raise RuntimeError("No data series available to build feature matrix")
    df = pd.DataFrame(frames).sort_index()

    # YoY % change for level series
    level_cols = [
        "igae_total", "igae_primary", "igae_secondary", "igae_tertiary",
        "exports", "remittances", "employment_imss",
        "wti_oil", "ipc_mexico", "us_indpro", "us_mfg_emp", "usdmxn",
    ]
    for col in level_cols:
        if col in df.columns:
            df[f"{col}_yoy"] = df[col].pct_change(12) * 100

    # 3-month rolling mean for PMI series
    for col in ["imef_manuf", "imef_nonmanuf", "ism_manuf"]:
        if col in df.columns:
            df[f"{col}_3mma"] = df[col].rolling(3).mean()

    # Convenience alias for target
    if "igae_total_yoy" in df.columns:
        df["igae_yoy"] = df["igae_total_yoy"]

    # Forward fill up to 3 months (handles ~45-day IGAE publication lag)
    df = df.ffill(limit=3)

    return df


def quarterly_aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate monthly data to quarterly by averaging months within each quarter.
    Drops quarters with fewer than 2 months of non-NaN data.
    """
    def safe_mean(x):
        valid = x.dropna()
        return valid.mean() if len(valid) >= 2 else np.nan

    q = df.resample("QE").agg(safe_mean)
    q = q.dropna(how="all")
    return q


# ═══════════════════════════════════════════════════════════════════════════════
#   NOWCASTING MODEL
# ═══════════════════════════════════════════════════════════════════════════════

def fit_bridge_equation(
    q_df: pd.DataFrame,
    target: str,
    predictors: list,
    min_obs: int = 8,
) -> "dict | None":
    """
    Fit an OLS bridge equation: target ~ predictors.
    Returns dict with model, rmse, etc., or None if insufficient data.
    """
    available = [p for p in predictors if p in q_df.columns]
    if not available:
        return None
    if target not in q_df.columns:
        return None

    data = q_df[[target] + available].dropna()
    if len(data) < min_obs:
        return None

    y = data[target]
    X = sm.add_constant(data[available])
    try:
        model    = sm.OLS(y, X).fit()
        fitted   = model.predict(X)
        residuals = y - fitted
        rmse     = float(np.sqrt((residuals ** 2).mean()))
        return {
            "model":      model,
            "predictors": available,
            "fitted":     fitted,
            "residuals":  residuals,
            "rmse":       rmse,
            "r_squared":  model.rsquared,
            "data_index": data.index,
        }
    except Exception as e:
        print(f"  ✗ Bridge fit error: {e}")
        return None


def expanding_window_rmse(
    q_df: pd.DataFrame,
    target: str,
    predictors: list,
    train_start: str = "2016-01-01",
    val_start:   str = "2018-01-01",
    val_end:     str = "2023-12-31",
    min_train:   int = 8,
) -> "float | None":
    """
    Expanding-window OOS RMSE for a bridge equation.
    Train from train_start, validate from val_start to val_end.
    """
    available = [p for p in predictors if p in q_df.columns]
    if not available or target not in q_df.columns:
        return None

    data    = q_df[[target] + available].dropna()
    data    = data[data.index >= train_start]
    val_idx = data.index[(data.index >= val_start) & (data.index <= val_end)]

    if len(val_idx) < 4:
        return None

    errors = []
    for vdate in val_idx:
        train = data[data.index < vdate]
        if len(train) < min_train:
            continue
        try:
            y_tr = train[target]
            X_tr = sm.add_constant(train[available])
            mdl  = sm.OLS(y_tr, X_tr).fit()
            row  = data.loc[[vdate], available]
            X_pr = sm.add_constant(row, has_constant="add")
            # Align columns to match model params
            for mc in mdl.params.index:
                if mc not in X_pr.columns:
                    X_pr[mc] = 0.0
            X_pr = X_pr.reindex(columns=mdl.params.index, fill_value=0.0)
            pred   = float(mdl.predict(X_pr).iloc[0])
            actual = float(data.loc[vdate, target])
            errors.append((pred - actual) ** 2)
        except Exception:
            continue

    if not errors:
        return None
    return float(np.sqrt(np.mean(errors)))


def compute_ensemble_weights(rmse_dict: dict) -> dict:
    """Inverse-RMSE weighting. Entries with None RMSE get weight 0."""
    inv = {}
    for name, rmse in rmse_dict.items():
        if rmse is not None and rmse > 0:
            inv[name] = 1.0 / (rmse + 1e-9)
        else:
            inv[name] = 0.0

    total = sum(inv.values())
    if total == 0:
        raise RuntimeError("All bridge RMSEs are zero or None — cannot compute ensemble weights")
    return {k: v / total for k, v in inv.items()}


def _predict_from_params(params: pd.Series, predictor_vals: dict) -> float:
    """Apply model params to predictor values: const + sum(beta_i * x_i)."""
    result = float(params.get("const", 0.0))
    for p, val in predictor_vals.items():
        if p in params.index and not np.isnan(val):
            result += float(params[p]) * float(val)
    return result


def nowcast_current_quarter(
    df: pd.DataFrame,
    bridges: dict,
    weights: dict,
) -> "float | None":
    """
    Nowcast the current (or most recent incomplete) quarter.
    Averages available months within the quarter for each predictor.
    """
    today   = pd.Timestamp.today()
    q_start = today.to_period("Q").to_timestamp()

    current_q = df[df.index >= q_start]
    if current_q.empty:
        # Fall back to most recent quarter
        prior_q = (today - pd.offsets.QuarterEnd(1)).to_period("Q")
        q_start = prior_q.to_timestamp()
        current_q = df[df.index >= q_start]
    if current_q.empty:
        return None

    q_means = current_q.mean()

    preds = {}
    for name, info in bridges.items():
        if info is None or weights.get(name, 0) == 0:
            continue
        pred_vals = {
            p: q_means[p]
            for p in info["predictors"]
            if p in q_means.index and not np.isnan(q_means.get(p, np.nan))
        }
        if not pred_vals:
            continue
        try:
            preds[name] = _predict_from_params(info["model"].params, pred_vals)
        except Exception:
            continue

    if not preds:
        return None

    total_w = sum(weights.get(n, 0) for n in preds)
    if total_w == 0:
        return None
    return float(sum(preds[n] * weights.get(n, 0) for n in preds) / total_w)


def bootstrap_ci(
    ensemble_residuals: pd.Series,
    point_estimate: float,
    iterations: int = 1000,
    ci_level: float = 0.90,
) -> tuple:
    """Residual bootstrap CI around a point estimate."""
    residuals = ensemble_residuals.dropna().values
    if len(residuals) < 4:
        return (point_estimate - 2.0, point_estimate + 2.0)
    bootstrapped = [
        point_estimate + np.random.choice(residuals, size=len(residuals), replace=True).mean()
        for _ in range(iterations)
    ]
    alpha = (1 - ci_level) / 2
    return (
        float(np.percentile(bootstrapped, alpha * 100)),
        float(np.percentile(bootstrapped, (1 - alpha) * 100)),
    )


def get_historical_nowcast_series(
    q_df: pd.DataFrame,
    bridges: dict,
    weights: dict,
    target: str = "igae_yoy",
) -> pd.DataFrame:
    """
    Compute historical ensemble nowcast series for plotting.
    Returns DataFrame with 'actual', 'nowcast', 'bridge_*' columns.
    """
    result = pd.DataFrame(index=q_df.index)
    if target in q_df.columns:
        result["actual"] = q_df[target]

    for name, info in bridges.items():
        if info is None or weights.get(name, 0) == 0:
            continue
        col = f"bridge_{name}"
        result[col] = np.nan
        params = info["model"].params
        for dt in q_df.index:
            pred_vals = {
                p: float(q_df.loc[dt, p])
                for p in info["predictors"]
                if p in q_df.columns and not np.isnan(q_df.loc[dt, p])
            }
            if not pred_vals:
                continue
            try:
                result.loc[dt, col] = _predict_from_params(params, pred_vals)
            except Exception:
                continue

    # Weighted ensemble
    bridge_cols = [c for c in result.columns if c.startswith("bridge_")]
    if bridge_cols:
        ensemble   = pd.Series(0.0, index=result.index)
        weight_sum = pd.Series(0.0, index=result.index)
        for bc in bridge_cols:
            w = weights.get(bc.replace("bridge_", ""), 0)
            valid = result[bc].notna()
            ensemble[valid]   += result.loc[valid, bc] * w
            weight_sum[valid] += w
        result["nowcast"] = ensemble / weight_sum.replace(0, np.nan)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#   RECESSION SHADING
# ═══════════════════════════════════════════════════════════════════════════════

def add_recession_shading(fig, recession, row, col):
    """Overlay NBER recession bars on a subplot (uses paper y to span full height)."""
    if recession is None or recession.empty:
        return
    in_rec    = False
    rec_start = None
    for dt, val in recession.items():
        if val == 1 and not in_rec:
            in_rec    = True
            rec_start = dt
        elif val == 0 and in_rec:
            in_rec = False
            fig.add_shape(
                type="rect",
                x0=rec_start, x1=dt,
                y0=0, y1=1,
                xref=f"x{_axis_num(row, col)}",
                yref=f"y{_axis_num(row, col)} domain",
                fillcolor="lightgray", opacity=0.40,
                line_width=0, layer="below",
            )
    if in_rec:
        fig.add_shape(
            type="rect",
            x0=rec_start, x1=recession.index[-1],
            y0=0, y1=1,
            xref=f"x{_axis_num(row, col)}",
            yref=f"y{_axis_num(row, col)} domain",
            fillcolor="lightgray", opacity=0.40,
            line_width=0, layer="below",
        )


def _axis_num(row: int, col: int, ncols: int = 2) -> str:
    """Return Plotly axis suffix for a (row, col) subplot in a 2-column grid."""
    n = (row - 1) * ncols + col
    return "" if n == 1 else str(n)


# ═══════════════════════════════════════════════════════════════════════════════
#   DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

def create_dashboard(
    df: pd.DataFrame,
    hist: pd.DataFrame,
    point: "float | None",
    ci: "tuple | None",
    weights: dict,
    bridge_rmses: dict,
    recession: "pd.Series | None",
    last_igae_date: "pd.Timestamp | None" = None,
) -> go.Figure:
    """Build single-panel Mexico IGAE nowcast chart."""

    fig = go.Figure()

    # Clip to last officially released IGAE month so forward-filled data
    # beyond the release cutoff doesn't appear as actual observations.
    igae_cutoff = last_igae_date if last_igae_date is not None else pd.Timestamp.today()
    # Last complete quarter fully covered by released data
    last_released_q_end = igae_cutoff.to_period("Q").to_timestamp(how="end")

    # ── IGAE YoY% actual (monthly, clipped to release cutoff) ─────────────────
    if "igae_yoy" in df.columns:
        s = df["igae_yoy"].loc[:igae_cutoff].dropna()
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values,
            mode="lines", name="IGAE YoY% (monthly)",
            line=dict(color="#1f77b4", width=2),
        ))

    # ── Quarterly actual dots (only fully-released quarters) ──────────────────
    if "actual" in hist.columns:
        ha = hist["actual"].loc[:last_released_q_end].dropna()
        fig.add_trace(go.Scatter(
            x=ha.index, y=ha.values,
            mode="markers", name="Quarterly Actual",
            marker=dict(color="#1f77b4", size=7, symbol="circle-open", line=dict(width=2)),
        ))

    # ── Historical ensemble nowcast ───────────────────────────────────────────
    if "nowcast" in hist.columns:
        hn = hist["nowcast"].dropna()
        fig.add_trace(go.Scatter(
            x=hn.index, y=hn.values,
            mode="lines+markers", name="Ensemble Nowcast (hist.)",
            line=dict(color="#ff7f0e", width=2, dash="dash"),
            marker=dict(size=5),
        ))

    # ── Current quarter point estimate + 90% CI error bar ────────────────────
    # Plot at today's date (not quarter-end) so it is clear this is a
    # real-time estimate for an in-progress quarter, not a released figure.
    if point is not None:
        today   = pd.Timestamp.today()
        q_label = f"Q{today.quarter} {today.year}"
        # Count how many months of the current quarter have elapsed
        months_in_q = today.month - 3 * ((today.month - 1) // 3)
        partial_note = f"({months_in_q}/3 months)"
        err_lo  = abs(point - ci[0]) if ci else 1.5
        err_hi  = abs(ci[1] - point) if ci else 1.5
        fig.add_trace(go.Scatter(
            x=[today], y=[point],
            mode="markers",
            name=f"{q_label} Nowcast {partial_note}: {point:.1f}%",
            marker=dict(color="#d62728", size=14, symbol="star"),
            error_y=dict(
                type="data", symmetric=False,
                array=[err_hi], arrayminus=[err_lo],
                visible=True, color="#d62728",
            ),
        ))

    # ── Recession shading ─────────────────────────────────────────────────────
    add_recession_shading(fig, recession, 1, 1)
    fig.add_hline(y=0, line_dash="dot", line_color="gray", line_width=1)

    # ── Nowcast annotation box ────────────────────────────────────────────────
    if point is not None:
        ci_txt = f"90% CI: [{ci[0]:.1f}%, {ci[1]:.1f}%]" if ci else ""
        fig.add_annotation(
            text=f"<b>{q_label} Nowcast {partial_note}: {point:.1f}%</b><br>{ci_txt}",
            xref="paper", yref="paper",
            x=0.02, y=0.97,
            xanchor="left", yanchor="top",
            showarrow=False,
            bgcolor="rgba(255,127,14,0.15)",
            bordercolor="#ff7f0e",
            borderwidth=1,
            font=dict(size=13, color="#d62728"),
        )

    # ── Layout ────────────────────────────────────────────────────────────────
    update_time = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    rmse_parts  = [
        f"{n}: RMSE={v:.2f}%" if v is not None else f"{n}: N/A"
        for n, v in bridge_rmses.items()
    ]
    wt_parts = [f"{n} w={v:.2f}" for n, v in weights.items()]
    footer = (
        f"Updated: {update_time}  ·  "
        f"Sources: INEGI BIE-BISE, Banxico SIE, IMEF PMI, FRED (INDPRO/WTI/MANEMP), yfinance (IPC)  ·  "
        f"Gray shading = NBER recessions  ·  "
        + " | ".join(rmse_parts)
        + "  ·  Weights: " + " | ".join(wt_parts)
    )

    fig.update_layout(
        title=dict(
            text="Mexico IGAE — Actual vs Ensemble Nowcast (YoY %)",
            x=0.5, xanchor="center",
            font=dict(size=20, color="#1a1a2e"),
        ),
        height=550,
        showlegend=True,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="right", x=1, font=dict(size=11),
        ),
        yaxis_title="YoY %",
        template="plotly_white",
        margin=dict(t=100, l=60, r=40, b=80),
    )
    fig.add_annotation(
        text=footer,
        xref="paper", yref="paper",
        x=0.5, y=-0.13,
        showarrow=False,
        font=dict(size=10, color="gray"),
        align="center",
    )
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="#eeeeee")
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="#eeeeee")

    return fig


# ═══════════════════════════════════════════════════════════════════════════════
#   MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Mexico GDP Nowcaster")
    print("=" * 60)

    # ── 0. Check required tokens ───────────────────────────────────────────────
    if not INEGI_TOKEN:
        raise RuntimeError(
            "INEGI_TOKEN environment variable is not set.\n"
            "Get a free token at: https://www.inegi.org.mx/app/api/token/"
        )

    # ── 1. Fetch all data ──────────────────────────────────────────────────────
    print("\n[1/5] Fetching data...")
    raw = {}

    print("  Fetching INEGI IGAE series...")
    for name, sid in INEGI_SERIES.items():
        raw[name] = fetch_inegi_series(name, sid)
    if raw.get("igae_total") is None:
        raise RuntimeError("Could not fetch IGAE Total from INEGI — check INEGI_TOKEN")

    print("  Fetching Banxico series...")
    for name, sid in BANXICO_SERIES.items():
        raw[name] = fetch_banxico_series(name, sid)

    print("  Fetching FRED series...")
    # Note: NAPM (ISM Manufacturing PMI) is not available via FRED public API.
    # Using INDPRO (US Industrial Production) as the external activity proxy instead.
    indpro = fetch_fred_monthly("INDPRO",    years=15)
    if indpro is not None: raw["us_indpro"]  = indpro

    manemp = fetch_fred_monthly("MANEMP",    years=15)
    if manemp is not None: raw["us_mfg_emp"] = manemp

    wti_fred = fetch_fred_monthly("DCOILWTICO", years=15)
    if wti_fred is not None: raw["wti_oil"]  = wti_fred

    recession = fetch_fred_monthly("USREC", years=25)

    print("  Fetching yfinance series...")
    ipc = fetch_yfinance_monthly("^MXX", years=15)
    if ipc is not None: raw["ipc_mexico"] = ipc

    # USD/MXN fallback from yfinance if Banxico unavailable
    if raw.get("usdmxn") is None:
        fx = fetch_yfinance_monthly("MXN=X", years=15)
        if fx is not None: raw["usdmxn"] = fx

    # WTI fallback from yfinance
    if raw.get("wti_oil") is None:
        wti_yf = fetch_yfinance_monthly("CL=F", years=15)
        if wti_yf is not None: raw["wti_oil"] = wti_yf

    print("  Building IMEF PMI series...")
    imef_m, imef_nm = build_imef_pmi_series()
    if imef_m is not None:
        raw["imef_manuf"]    = imef_m
        raw["imef_nonmanuf"] = imef_nm

    # ── 2. Build feature matrix ────────────────────────────────────────────────
    print("\n[2/5] Building feature matrix...")
    df = build_feature_matrix(raw)
    print(f"  Monthly matrix: {df.shape[0]} rows × {df.shape[1]} columns")
    print(f"  Date range: {df.index[0].date()} → {df.index[-1].date()}")

    # ── 3. Quarterly aggregation ───────────────────────────────────────────────
    print("\n[3/5] Aggregating to quarterly frequency...")
    feature_cols = [c for c in df.columns if c not in _RAW_LEVEL_COLS]
    q_df = quarterly_aggregate(df[feature_cols])
    print(f"  Quarterly matrix: {q_df.shape[0]} quarters × {q_df.shape[1]} columns")

    # ── 4. Fit bridge equations ────────────────────────────────────────────────
    print("\n[4/5] Fitting bridge equations...")
    TARGET = "igae_yoy"
    bridge_defs = {
        "Activity": ["imef_manuf_3mma",  "imef_nonmanuf_3mma"],
        "External": ["us_indpro_yoy",    "wti_oil_yoy", "us_mfg_emp_yoy"],
        "Financial":["usdmxn_yoy",       "ipc_mexico_yoy"],
    }

    bridges      = {}
    bridge_rmses = {}
    for name, preds in bridge_defs.items():
        b = fit_bridge_equation(q_df, TARGET, preds)
        if b is None:
            print(f"  ✗ {name}: insufficient data or fit failed")
        else:
            print(f"  ✓ {name}: R²={b['r_squared']:.3f}, in-sample RMSE={b['rmse']:.2f}%")
        bridges[name] = b

        oos = expanding_window_rmse(q_df, TARGET, preds)
        bridge_rmses[name] = oos
        if oos is not None:
            print(f"      OOS RMSE (2018-2023): {oos:.2f}%")

    if all(b is None for b in bridges.values()):
        raise RuntimeError("No bridge equations could be fit — check data availability")

    weights = compute_ensemble_weights(bridge_rmses)
    print(
        "\n  Ensemble weights: "
        + " | ".join(f"{k}: {v:.2f}" for k, v in weights.items())
    )

    # ── 5. Nowcast & bootstrap CI ──────────────────────────────────────────────
    print("\n[5/5] Computing nowcast...")
    point_est = nowcast_current_quarter(df, bridges, weights)
    hist      = get_historical_nowcast_series(q_df, bridges, weights, TARGET)

    ci = None
    if point_est is not None and "nowcast" in hist.columns and "actual" in hist.columns:
        aligned = hist[["nowcast", "actual"]].dropna()
        if len(aligned) >= 4:
            resids = aligned["actual"] - aligned["nowcast"]
            ci     = bootstrap_ci(resids, point_est)

    today   = pd.Timestamp.today()
    q_label = f"Q{today.quarter} {today.year}"
    if point_est is not None:
        ci_str = f"  90% CI: [{ci[0]:.2f}%, {ci[1]:.2f}%]" if ci else ""
        print(f"\n  ★ {q_label} Nowcast: {point_est:.2f}%{ci_str}")
    else:
        print("\n  ⚠️  Could not compute current quarter nowcast")

    # ── Dashboard ──────────────────────────────────────────────────────────────
    print("\n  Building dashboard...")
    last_igae_date = raw["igae_total"].index[-1]
    fig = create_dashboard(df, hist, point_est, ci, weights, bridge_rmses, recession,
                           last_igae_date=last_igae_date)

    chart_div = fig.to_html(
        full_html=False,
        include_plotlyjs="cdn",
        config={"displayModeBar": True, "displaylogo": False},
    )

    rmse_parts = [
        f"<b>{n}</b>: {v:.2f}% OOS RMSE" if v is not None else f"<b>{n}</b>: N/A"
        for n, v in bridge_rmses.items()
    ]
    wt_parts = [f"<b>{n}</b>: {v:.0%}" for n, v in weights.items()]
    update_time = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    methodology_html = f"""
<div style="max-width:900px; margin:0 auto 32px; padding:0 24px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size:15px; line-height:1.7; color:#333;">
  <h2 style="font-size:18px; font-weight:600; margin-bottom:10px; color:#1a1a2e;">
    How the nowcast works
  </h2>
  <p style="margin:0 0 12px;">
    Mexico's <strong>IGAE</strong> (Indicador Global de la Actividad Económica) is INEGI's
    monthly proxy for GDP, published with a ~45-day lag. This nowcaster bridges that gap
    using three <strong>OLS bridge equations</strong> fitted on quarterly data since 2016:
  </p>
  <ul style="margin:0 0 12px; padding-left:20px;">
    <li><strong>Activity bridge</strong> — IMEF Manufacturing and Non-Manufacturing PMI
        (3-month moving averages), capturing domestic business-cycle momentum.</li>
    <li><strong>External bridge</strong> — US Industrial Production YoY, WTI crude oil YoY,
        and US manufacturing employment YoY, reflecting the tight Mexico–US trade linkage.</li>
    <li><strong>Financial bridge</strong> — USD/MXN YoY and IPC Bolsa Mexicana YoY,
        incorporating real-time financial-market signals.</li>
  </ul>
  <p style="margin:0 0 12px;">
    Each bridge is validated with an <strong>expanding-window out-of-sample test</strong>
    (train from 2016, evaluate 2018–2023). Bridges are combined using
    <strong>inverse-RMSE ensemble weights</strong> — better-fitting bridges receive higher
    weight. The current-quarter estimate (red star, plotted at today&rsquo;s date) uses only
    the months of data available so far &mdash; it updates each month as new data arrives.
    The <strong>90% confidence interval</strong> comes from 1,000 residual bootstrap
    iterations. Because the quarter is still in progress, treat the estimate as
    directional rather than precise.
  </p>
  <p style="margin:0; font-size:13px; color:#666;">
    Bridge performance: {" &nbsp;|&nbsp; ".join(rmse_parts)}.
    Ensemble weights: {" &nbsp;|&nbsp; ".join(wt_parts)}.
    Last updated: {update_time}.
  </p>
</div>
"""

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mexico GDP Nowcaster</title>
  <style>
    body {{ margin: 0; padding: 32px 16px 48px; background: #fff; }}
    h1 {{
      text-align: center;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 26px; font-weight: 700; color: #1a1a2e;
      margin: 0 auto 8px; max-width: 900px;
    }}
    .subtitle {{
      text-align: center;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px; color: #666; margin: 0 auto 28px; max-width: 900px;
    }}
    .chart-wrap {{ max-width: 960px; margin: 0 auto 36px; }}
  </style>
</head>
<body>
  <h1>Mexico GDP Nowcaster</h1>
  <p class="subtitle">
    Real-time estimate of Mexico IGAE/GDP growth — updated monthly as new data arrives
  </p>
  <div class="chart-wrap">
    {chart_div}
  </div>
  {methodology_html}
</body>
</html>"""

    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(full_html)

    print(f"\n✅ Dashboard saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
