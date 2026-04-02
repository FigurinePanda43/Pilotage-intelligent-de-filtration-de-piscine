"""Constants for the Pool Filtration integration."""

DOMAIN = "pool_filtration"
PLATFORMS = ["sensor", "switch"]

# ---------------------------------------------------------------------------
# Config / options keys
# ---------------------------------------------------------------------------
CONF_PUMP_SWITCH = "pump_switch"
CONF_WATER_TEMP = "water_temp_sensor"
CONF_AIR_TEMP = "air_temp_sensor"
CONF_UV_SENSOR = "uv_sensor"
CONF_WIND_SENSOR = "wind_sensor"
CONF_WIND_GUST_SENSOR = "wind_gust_sensor"  # optional

CONF_RESET_TIME = "reset_time"
CONF_ALLOWED_START = "allowed_start"
CONF_ALLOWED_END = "allowed_end"
CONF_WINTER_CYCLE_HOURS = "winter_cycle_hours"
CONF_WINTER_RUN_MINUTES = "winter_run_minutes"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_RESET_TIME = "00:00"
DEFAULT_ALLOWED_START = 6
DEFAULT_ALLOWED_END = 23
DEFAULT_WINTER_CYCLE_HOURS = 4
DEFAULT_WINTER_RUN_MINUTES = 60
DEFAULT_SCAN_INTERVAL = 10  # minutes

# ---------------------------------------------------------------------------
# Filtration limits
# ---------------------------------------------------------------------------
MIN_FILTRATION_HOURS = 2.0
MAX_FILTRATION_HOURS = 18.0

# ---------------------------------------------------------------------------
# Anti-cycling
# ---------------------------------------------------------------------------
MIN_ON_MINUTES = 30
MIN_OFF_MINUTES = 15

# ---------------------------------------------------------------------------
# Rolling average windows (hours)
# ---------------------------------------------------------------------------
WATER_TEMP_AVG_HOURS = 3
AIR_TEMP_AVG_HOURS = 3
UV_AVG_HOURS = 1
WIND_AVG_HOURS = 1

# ---------------------------------------------------------------------------
# Solar window
# ---------------------------------------------------------------------------
SOLAR_WINDOW_HOURS = 4  # +/- around solar noon

# ---------------------------------------------------------------------------
# Dynamic target formula thresholds / coefficients
# ---------------------------------------------------------------------------
UV_THRESHOLD = 3.0
WIND_THRESHOLD = 15.0       # km/h
AIR_TEMP_THRESHOLD = 26.0   # °C

UV_COEFF = 0.20
WIND_COEFF = 0.04
AIR_TEMP_COEFF = 0.12

# ---------------------------------------------------------------------------
# Winter mode
# ---------------------------------------------------------------------------
WINTER_AIR_TEMP_THRESHOLD = 0.0    # °C
WINTER_WATER_TEMP_THRESHOLD = 5.0  # °C
WINTER_NO_FROST_DAILY_HOURS = 0.0  # no frost in winter mode → pump stays OFF

# ---------------------------------------------------------------------------
# Eco mode
# ---------------------------------------------------------------------------
CONF_ECO_OFF_PEAK_SLOTS = "eco_off_peak_slots"   # option A: "HH:MM-HH:MM,HH:MM-HH:MM,..."
CONF_ECO_OFF_PEAK_SENSOR = "eco_off_peak_sensor" # option B: binary_sensor (takes priority)

ECO_DAY_MIN_RATIO = 0.6    # 60 % of H_target must be done during solar window
ECO_DAY_MIN_HOURS = 3.0    # absolute floor for daytime minimum
ECO_TEMP_THRESHOLD = 28.0  # °C – above this, eco is suspended
ECO_UV_THRESHOLD = 6.0     # index – above this, eco is suspended

# ---------------------------------------------------------------------------
# Fallback sensor values when unavailable
# ---------------------------------------------------------------------------
FALLBACK_WATER_TEMP = 20.0
FALLBACK_AIR_TEMP = 20.0
FALLBACK_UV = 0.0
FALLBACK_WIND = 0.0

# ---------------------------------------------------------------------------
# Busy mode (forte fréquentation)
# ---------------------------------------------------------------------------
CONF_BUSY_BOOST_DURATION = "busy_boost_duration"
DEFAULT_BUSY_BOOST_DURATION = 2.0   # hours
BUSY_BOOST_MIN_HOURS = 0.5
BUSY_BOOST_MAX_HOURS = 6.0

# ---------------------------------------------------------------------------
# Persistent storage
# ---------------------------------------------------------------------------
STORAGE_VERSION = 1
