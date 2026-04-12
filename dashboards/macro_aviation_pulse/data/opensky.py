# data/opensky.py — OpenSky Network API client
#
# Required env vars (registered account gives ~4,000 req/day):
#   OPENSKY_USERNAME
#   OPENSKY_PASSWORD
#
# Anonymous access (~100 req/day) is used automatically when env vars are absent,
# but will hit rate limits quickly at 4-region × 5-min polling cadence.

import logging
import os
import threading
from typing import Optional

import requests

from config import (
    CALLSIGN_IDX,
    ICAO24_IDX,
    LAT_IDX,
    LON_IDX,
    OPENSKY_BASE_URL,
    REGIONS,
    REQUEST_TIMEOUT_S,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process cache: last known count per region (populated on every successful
# API call; returned as fallback on timeout / rate-limit).
# ---------------------------------------------------------------------------
_last_known: dict[str, int] = {r: 0 for r in REGIONS}
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_credentials() -> Optional[tuple[str, str]]:
    """Return (username, password) from env vars, or None for anonymous."""
    user = os.environ.get("OPENSKY_USERNAME")
    pw   = os.environ.get("OPENSKY_PASSWORD")
    if user and pw:
        return (user, pw)
    logger.warning("OPENSKY_USERNAME/PASSWORD not set — using anonymous access")
    return None


def _call_opensky(params: dict) -> Optional[dict]:
    """
    Execute one GET request against the OpenSky REST API.

    Handles authentication (if credentials are present), timeouts, and HTTP
    errors.  Returns parsed JSON on success, None on any failure.

    Args:
        params: Query parameters dict (lamin, lomin, lamax, lomax, etc.)

    Returns:
        Parsed JSON dict or None.
    """
    auth = _get_credentials()
    try:
        response = requests.get(
            OPENSKY_BASE_URL,
            params=params,
            auth=auth,
            timeout=REQUEST_TIMEOUT_S,
        )
        if response.status_code == 429:
            logger.warning("OpenSky rate limit hit (HTTP 429) — using cached value")
            return None
        if response.status_code == 401:
            logger.error("OpenSky auth failed (HTTP 401) — check credentials")
            return None
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        logger.warning("OpenSky request timed out after %ds", REQUEST_TIMEOUT_S)
        return None
    except requests.ConnectionError as exc:
        logger.warning("OpenSky connection error: %s", exc)
        return None
    except requests.HTTPError as exc:
        logger.warning("OpenSky HTTP error: %s", exc)
        return None
    except ValueError as exc:
        logger.error("OpenSky JSON decode error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_region_count(region_name: str) -> int:
    """
    Fetch the live aircraft count for one EM region bounding box.

    On HTTP 429 (rate limit) or timeout, returns the last known cached count
    for this region so the dashboard degrades gracefully instead of crashing.

    Args:
        region_name: A key from config.REGIONS (e.g. "Brazil").

    Returns:
        Integer count of unique icao24 transponders currently airborne within
        the region's bounding box.
    """
    bbox = REGIONS[region_name]
    params = {
        "lamin": bbox["lamin"],
        "lomin": bbox["lomin"],
        "lamax": bbox["lamax"],
        "lomax": bbox["lomax"],
    }

    data = _call_opensky(params)
    if data is None or data.get("states") is None:
        # Return cached fallback
        with _cache_lock:
            fallback = _last_known[region_name]
        logger.debug("Using cached count %d for %s", fallback, region_name)
        return fallback

    states = data["states"]
    unique_icao24 = {s[ICAO24_IDX] for s in states if s[ICAO24_IDX]}
    count = len(unique_icao24)

    with _cache_lock:
        _last_known[region_name] = count

    logger.info("%s: %d aircraft", region_name, count)
    return count


def fetch_aircraft_positions(region_name: str) -> list[dict]:
    """
    Return a list of aircraft position dicts for the Mapbox scatter plot.

    Filters out state vectors with null latitude or longitude (aircraft that
    have not transmitted a valid position fix).

    On any API failure, returns an empty list — the map renders without this
    region's dots rather than raising an exception.

    Args:
        region_name: A key from config.REGIONS.

    Returns:
        List of dicts: [{lat, lon, icao24, callsign}, ...]
    """
    bbox = REGIONS[region_name]
    params = {
        "lamin": bbox["lamin"],
        "lomin": bbox["lomin"],
        "lamax": bbox["lamax"],
        "lomax": bbox["lomax"],
    }

    data = _call_opensky(params)
    if data is None or data.get("states") is None:
        return []

    positions: list[dict] = []
    for state in data["states"]:
        try:
            lat = state[LAT_IDX]
            lon = state[LON_IDX]
            if lat is None or lon is None:
                continue
            positions.append({
                "lat":      float(lat),
                "lon":      float(lon),
                "icao24":   state[ICAO24_IDX] or "",
                "callsign": (state[CALLSIGN_IDX] or "").strip(),
            })
        except (IndexError, TypeError, ValueError):
            continue

    return positions
