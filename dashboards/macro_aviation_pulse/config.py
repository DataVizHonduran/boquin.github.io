# config.py — Region definitions and global constants
# Add a new EM region by appending one entry to REGIONS. No other file needs to change.

REGIONS: dict[str, dict] = {
    "Brazil": {
        "lamin": -34.0,
        "lomin": -74.0,
        "lamax":   5.0,
        "lomax": -34.0,
        "color": "#00b4d8",
    },
    "Mexico": {
        "lamin":  14.0,
        "lomin": -118.0,
        "lamax":  33.0,
        "lomax": -86.0,
        "color": "#f4a261",
    },
    "South Korea": {
        "lamin":  33.0,
        "lomin": 124.0,
        "lamax":  38.5,
        "lomax": 130.0,
        "color": "#e76f51",
    },
    "China": {
        "lamin":  18.0,
        "lomin":  73.0,
        "lamax":  53.0,
        "lomax": 135.0,
        "color": "#2a9d8f",
    },
}

# Dash interval: how often the UI callback fires to redraw from DB
POLL_INTERVAL_MS: int = 5 * 60 * 1000  # 5 minutes in milliseconds

# Background thread: seconds to sleep between consecutive region API calls
# 4 regions × 60s = 240s stagger, leaving ~60s margin before next 5-min cycle
POLL_STAGGER_SECONDS: int = 60

# Congestion Index alert threshold (CI < this value triggers an alert)
ALERT_CI_THRESHOLD: float = 0.80

# Rolling window for the CI baseline denominator
ROLLING_WINDOW_DAYS: int = 7

# Minimum samples before CI is considered reliable (1 full day at 5-min cadence)
BASELINE_MIN_SAMPLES: int = 288

# Seconds of history returned for the 24h time-series chart
HISTORY_24H_SECONDS: int = 24 * 3600

# SQLite database path (relative to project root; auto-created at startup)
DB_PATH: str = "aviation_data.db"

# OpenSky REST API
OPENSKY_BASE_URL: str = "https://opensky-network.org/api/states/all"
REQUEST_TIMEOUT_S: int = 15

# OpenSky state-vector field indices (from API docs)
ICAO24_IDX: int    = 0
CALLSIGN_IDX: int  = 1
LON_IDX: int       = 5
LAT_IDX: int       = 6
