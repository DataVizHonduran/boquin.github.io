# utils/metrics.py — SQLite persistence, Congestion Index, and alert detection

import logging
import sqlite3
import time
from contextlib import contextmanager
from typing import Generator

from config import (
    ALERT_CI_THRESHOLD,
    BASELINE_MIN_SAMPLES,
    DB_PATH,
    HISTORY_24H_SECONDS,
    REGIONS,
    ROLLING_WINDOW_DAYS,
)

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS traffic_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    region    TEXT    NOT NULL,
    timestamp INTEGER NOT NULL,
    count     INTEGER NOT NULL,
    ci        REAL    NOT NULL
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_rt ON traffic_history (region, timestamp);
"""


# ---------------------------------------------------------------------------
# DB connection context manager
# ---------------------------------------------------------------------------

@contextmanager
def _db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection and commit/close automatically."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Create the traffic_history table and index if they do not already exist.
    Safe to call multiple times — uses CREATE IF NOT EXISTS.
    Called once at application startup before the background thread starts.
    """
    with _db() as conn:
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_INDEX)
    logger.info("SQLite DB initialised at %s", DB_PATH)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_sample(region: str, count: int, ci: float) -> None:
    """
    Insert one traffic sample and prune rows older than the rolling window.

    Args:
        region: Region name string (key in config.REGIONS).
        count:  Aircraft count for this poll cycle.
        ci:     Congestion Index computed for this sample.
    """
    now = int(time.time())
    cutoff = now - ROLLING_WINDOW_DAYS * 24 * 3600

    with _db() as conn:
        conn.execute(
            "INSERT INTO traffic_history (region, timestamp, count, ci) VALUES (?, ?, ?, ?)",
            (region, now, count, ci),
        )
        conn.execute(
            "DELETE FROM traffic_history WHERE timestamp < ?",
            (cutoff,),
        )

    logger.debug("Wrote sample: %s count=%d ci=%.3f", region, count, ci)


# ---------------------------------------------------------------------------
# Congestion Index
# ---------------------------------------------------------------------------

def compute_ci(region: str, current_count: int) -> float:
    """
    Compute the Congestion Index for a region.

    CI = current_count / rolling_7day_mean

    Behaviour:
    - If fewer than BASELINE_MIN_SAMPLES rows exist, uses the mean of whatever
      samples are available (so CI is meaningful even on day 1).
    - If no historical rows exist at all (very first sample), returns 1.0.
    - Protects against division-by-zero: if rolling mean is 0, returns 1.0.

    Args:
        region:        Region name string.
        current_count: Fresh aircraft count from the latest API poll.

    Returns:
        CI as a float (1.0 = at baseline, <0.80 triggers an alert).
    """
    cutoff = int(time.time()) - ROLLING_WINDOW_DAYS * 24 * 3600

    with _db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, AVG(count) AS mean FROM traffic_history "
            "WHERE region = ? AND timestamp >= ?",
            (region, cutoff),
        ).fetchone()

    n    = row["n"]    if row["n"]    is not None else 0
    mean = row["mean"] if row["mean"] is not None else 0.0

    if n == 0 or mean == 0.0:
        return 1.0

    ci = current_count / mean
    logger.debug("CI for %s: %.3f (n=%d, mean=%.1f)", region, ci, n, mean)
    return round(ci, 4)


# ---------------------------------------------------------------------------
# Reads for dashboard
# ---------------------------------------------------------------------------

def get_history_24h(region: str) -> list[dict]:
    """
    Return all traffic samples for a region from the past 24 hours.

    Args:
        region: Region name string.

    Returns:
        List of dicts [{timestamp, count, ci}] ordered by timestamp ASC.
    """
    cutoff = int(time.time()) - HISTORY_24H_SECONDS

    with _db() as conn:
        rows = conn.execute(
            "SELECT timestamp, count, ci FROM traffic_history "
            "WHERE region = ? AND timestamp >= ? ORDER BY timestamp ASC",
            (region, cutoff),
        ).fetchall()

    return [{"timestamp": r["timestamp"], "count": r["count"], "ci": r["ci"]} for r in rows]


def get_all_alerts() -> list[dict]:
    """
    Return the most recent sample for each region where CI is below threshold.

    Returns:
        List of dicts [{region, ci, count, timestamp}] for regions in alert state.
        Empty list when all regions are within normal range.
    """
    alerts: list[dict] = []
    with _db() as conn:
        for region in REGIONS:
            row = conn.execute(
                "SELECT ci, count, timestamp FROM traffic_history "
                "WHERE region = ? ORDER BY timestamp DESC LIMIT 1",
                (region,),
            ).fetchone()
            if row and row["ci"] < ALERT_CI_THRESHOLD:
                alerts.append({
                    "region":    region,
                    "ci":        row["ci"],
                    "count":     row["count"],
                    "timestamp": row["timestamp"],
                })
    return alerts


def get_latest_counts() -> dict[str, dict]:
    """
    Return the most recent {count, ci, timestamp} for every region.
    Regions with no data yet return count=0, ci=1.0, timestamp=None.

    Returns:
        Dict keyed by region name.
    """
    result: dict[str, dict] = {}
    with _db() as conn:
        for region in REGIONS:
            row = conn.execute(
                "SELECT count, ci, timestamp FROM traffic_history "
                "WHERE region = ? ORDER BY timestamp DESC LIMIT 1",
                (region,),
            ).fetchone()
            if row:
                result[region] = {
                    "count":     row["count"],
                    "ci":        row["ci"],
                    "timestamp": row["timestamp"],
                }
            else:
                result[region] = {"count": 0, "ci": 1.0, "timestamp": None}
    return result
