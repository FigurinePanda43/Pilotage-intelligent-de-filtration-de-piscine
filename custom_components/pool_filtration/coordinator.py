"""DataUpdateCoordinator for Pool Filtration – core logic."""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.sun import get_astral_location
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    STORAGE_VERSION,
    DEFAULT_SCAN_INTERVAL,
    CONF_PUMP_SWITCH,
    CONF_WATER_TEMP,
    CONF_AIR_TEMP,
    CONF_UV_SENSOR,
    CONF_WIND_SENSOR,
    CONF_WIND_GUST_SENSOR,
    CONF_RESET_TIME,
    CONF_ALLOWED_START,
    CONF_ALLOWED_END,
    CONF_WINTER_CYCLE_HOURS,
    CONF_WINTER_RUN_MINUTES,
    DEFAULT_RESET_TIME,
    DEFAULT_ALLOWED_START,
    DEFAULT_ALLOWED_END,
    DEFAULT_WINTER_CYCLE_HOURS,
    DEFAULT_WINTER_RUN_MINUTES,
    MIN_FILTRATION_HOURS,
    MAX_FILTRATION_HOURS,
    MIN_ON_MINUTES,
    MIN_OFF_MINUTES,
    WATER_TEMP_AVG_HOURS,
    AIR_TEMP_AVG_HOURS,
    UV_AVG_HOURS,
    WIND_AVG_HOURS,
    SOLAR_WINDOW_HOURS,
    UV_THRESHOLD,
    WIND_THRESHOLD,
    AIR_TEMP_THRESHOLD,
    UV_COEFF,
    WIND_COEFF,
    AIR_TEMP_COEFF,
    WINTER_AIR_TEMP_THRESHOLD,
    WINTER_WATER_TEMP_THRESHOLD,
    WINTER_NO_FROST_DAILY_HOURS,
    FALLBACK_WATER_TEMP,
    FALLBACK_AIR_TEMP,
    FALLBACK_UV,
    FALLBACK_WIND,
)

_LOGGER = logging.getLogger(__name__)


class PoolFiltrationCoordinator(DataUpdateCoordinator):
    """Manage all data, calculations and pump control for pool filtration."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL),
        )
        self.config_entry = config_entry
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{config_entry.entry_id}",
        )

        # Rolling average buffers: deque of (timestamp, float)
        self._water_temp_history: deque[tuple[datetime, float]] = deque()
        self._air_temp_history: deque[tuple[datetime, float]] = deque()
        self._uv_history: deque[tuple[datetime, float]] = deque()
        self._wind_history: deque[tuple[datetime, float]] = deque()

        # Persistent state (loaded from storage)
        self._h_target: float = 0.0
        self._h_done: float = 0.0
        self._last_reset_date: str | None = None
        self._last_commanded_on: datetime | None = None
        self._last_commanded_off: datetime | None = None
        self._last_state_check: datetime | None = None
        self._pump_was_on: bool = False
        self._winter_mode: bool = False
        self._last_winter_cycle: datetime | None = None

        self._persistent_loaded: bool = False

    # ------------------------------------------------------------------
    # Public helpers (called from switch entity)
    # ------------------------------------------------------------------

    async def set_winter_mode(self, enabled: bool) -> None:
        """Enable or disable winter mode and persist the change."""
        self._winter_mode = enabled
        if enabled:
            _LOGGER.info("Pool filtration: winter mode ENABLED")
        else:
            _LOGGER.info("Pool filtration: winter mode DISABLED")
        await self._save_persistent_data()
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Persist state on integration unload."""
        await self._save_persistent_data()

    # ------------------------------------------------------------------
    # Core coordinator update
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch sensor data, run calculations, control pump."""
        if not self._persistent_loaded:
            await self._load_persistent_data()
            self._persistent_loaded = True

        now = dt_util.now()

        # Daily reset check
        self._check_daily_reset(now)

        # Read raw sensor values (with fallbacks for unavailable sensors)
        water_temp = self._read_state(CONF_WATER_TEMP, FALLBACK_WATER_TEMP)
        air_temp = self._read_state(CONF_AIR_TEMP, FALLBACK_AIR_TEMP)
        uv = self._read_state(CONF_UV_SENSOR, FALLBACK_UV)
        wind = self._read_wind(air_temp)

        # Update rolling averages
        self._push(self._water_temp_history, now, water_temp, WATER_TEMP_AVG_HOURS)
        self._push(self._air_temp_history, now, air_temp, AIR_TEMP_AVG_HOURS)
        self._push(self._uv_history, now, uv, UV_AVG_HOURS)
        self._push(self._wind_history, now, wind, WIND_AVG_HOURS)

        water_temp_avg = self._avg(self._water_temp_history)
        air_temp_avg = self._avg(self._air_temp_history)
        uv_avg = self._avg(self._uv_history)
        wind_avg = self._avg(self._wind_history)

        # Compute filtration targets
        h_min = self._h_min(water_temp_avg)
        h_dyn = self._h_dyn(water_temp_avg, uv_avg, wind_avg, air_temp_avg)
        self._h_target = max(self._h_target, h_min, h_dyn)

        # Accumulate pump run-time before reading new state
        pump_is_on = self._read_pump_state()
        self._accumulate_run_time(now, pump_is_on)

        h_remaining = max(0.0, self._h_target - self._h_done)

        # Solar window
        solar_noon = self._solar_noon(now)
        window_start = solar_noon - timedelta(hours=SOLAR_WINDOW_HOURS)
        window_end = solar_noon + timedelta(hours=SOLAR_WINDOW_HOURS)
        in_window = window_start <= now <= window_end
        time_remaining_window = max(
            0.0, (window_end - now).total_seconds() / 3600.0
        )

        # Delay status
        if h_remaining > 0 and in_window and time_remaining_window > 0:
            delay_status = (
                "late" if h_remaining > time_remaining_window else "on_time"
            )
        elif h_remaining > 0 and now > window_end:
            delay_status = "late"
        else:
            delay_status = "on_time"

        # Decide pump state
        frost_condition = (
            air_temp <= WINTER_AIR_TEMP_THRESHOLD
            or water_temp <= WINTER_WATER_TEMP_THRESHOLD
        )
        pump_should_be_on = self._decide(
            now=now,
            pump_is_on=pump_is_on,
            h_remaining=h_remaining,
            in_window=in_window,
            time_remaining_window=time_remaining_window,
            window_end=window_end,
            water_temp=water_temp,
            air_temp=air_temp,
            frost_condition=frost_condition,
        )

        # Apply decision to physical switch
        await self._apply_decision(now, pump_is_on, pump_should_be_on)

        # Persist after every update
        await self._save_persistent_data()

        return {
            # Raw readings
            "water_temp": water_temp,
            "air_temp": air_temp,
            "uv": uv,
            "wind": wind,
            # Rolling averages
            "water_temp_avg_3h": water_temp_avg,
            "air_temp_avg_3h": air_temp_avg,
            "uv_avg_1h": uv_avg,
            "wind_avg_1h": wind_avg,
            # Targets
            "h_min": h_min,
            "h_dyn": h_dyn,
            "h_target": self._h_target,
            "h_done": self._h_done,
            "h_remaining": h_remaining,
            # Solar window
            "solar_noon": solar_noon,
            "window_start": window_start,
            "window_end": window_end,
            "in_window": in_window,
            "time_remaining_window": time_remaining_window,
            # Decision
            "pump_is_on": pump_is_on,
            "pump_should_be_on": pump_should_be_on,
            "delay_status": delay_status,
            # Winter
            "winter_mode": self._winter_mode,
            "frost_condition": frost_condition,
        }

    # ------------------------------------------------------------------
    # Filtration formulas
    # ------------------------------------------------------------------

    @staticmethod
    def _h_min(water_temp_avg: float) -> float:
        """H_min = clamp(T_eau / 2 ; 2 ; 16)."""
        return max(MIN_FILTRATION_HOURS, min(16.0, water_temp_avg / 2.0))

    @staticmethod
    def _h_dyn(
        water_temp_avg: float,
        uv_avg: float,
        wind_avg: float,
        air_temp_avg: float,
    ) -> float:
        """H_dyn = clamp(T/2 + UV_adj + Wind_adj + Air_adj ; 2 ; 18)."""
        base = water_temp_avg / 2.0
        uv_adj = UV_COEFF * max(uv_avg - UV_THRESHOLD, 0.0)
        wind_adj = WIND_COEFF * max(wind_avg - WIND_THRESHOLD, 0.0)
        air_adj = AIR_TEMP_COEFF * max(air_temp_avg - AIR_TEMP_THRESHOLD, 0.0)
        return max(
            MIN_FILTRATION_HOURS, min(MAX_FILTRATION_HOURS, base + uv_adj + wind_adj + air_adj)
        )

    # ------------------------------------------------------------------
    # Decision logic
    # ------------------------------------------------------------------

    def _decide(
        self,
        now: datetime,
        pump_is_on: bool,
        h_remaining: float,
        in_window: bool,
        time_remaining_window: float,
        window_end: datetime,
        water_temp: float,
        air_temp: float,
        frost_condition: bool,
    ) -> bool:
        """Return True if the pump should be running."""

        # --- Winter mode overrides normal logic ---
        if self._winter_mode:
            return self._decide_winter(now, pump_is_on, frost_condition)

        # --- Normal mode ---
        # Hard limit
        if self._h_done >= MAX_FILTRATION_HOURS:
            return False

        allowed_start, allowed_end = self._allowed_hours()
        current_hour = now.hour

        # Condition 1 – inside priority window and still remaining time
        cond1 = in_window and h_remaining > 0

        # Condition 2 – critical catch-up: more remaining than time left in window
        cond2 = time_remaining_window > 0 and h_remaining > time_remaining_window

        # Condition 3 – end-of-day catch-up (after window, still below minimum)
        cond3 = now >= window_end and self._h_done < self._h_target

        if not (cond1 or cond2 or cond3):
            return False

        # Enforce allowed time window (can be overridden by catch-up need)
        inside_allowed = allowed_start <= current_hour < allowed_end
        if not inside_allowed and not cond3:
            return False

        return True

    def _decide_winter(
        self, now: datetime, pump_is_on: bool, frost_condition: bool
    ) -> bool:
        """Winter mode decision."""
        opts = self.config_entry.options
        cycle_hours = int(opts.get(CONF_WINTER_CYCLE_HOURS, DEFAULT_WINTER_CYCLE_HOURS))
        run_minutes = int(opts.get(CONF_WINTER_RUN_MINUTES, DEFAULT_WINTER_RUN_MINUTES))

        if frost_condition:
            # Cycle-based: run `run_minutes` every `cycle_hours` hours
            if self._last_winter_cycle is None:
                return True  # First ever cycle

            elapsed_since_cycle_start = (
                now - self._last_winter_cycle
            ).total_seconds() / 60.0

            if elapsed_since_cycle_start <= run_minutes:
                return True  # Still within run window

            if elapsed_since_cycle_start >= cycle_hours * 60.0:
                return True  # Time for a new cycle

            return False
        else:
            # No frost: just limit to WINTER_NO_FROST_DAILY_HOURS per day
            return self._h_done < WINTER_NO_FROST_DAILY_HOURS

    # ------------------------------------------------------------------
    # Pump control
    # ------------------------------------------------------------------

    async def _apply_decision(
        self, now: datetime, pump_is_on: bool, pump_should_be_on: bool
    ) -> None:
        """Turn pump on or off respecting anti-cycling guards."""
        if pump_should_be_on and not pump_is_on:
            if not self._can_turn_on(now):
                _LOGGER.debug(
                    "Anti-cycling: skip turn-on (last OFF < %d min ago)",
                    MIN_OFF_MINUTES,
                )
                return
            await self._set_pump(True)
            self._last_commanded_on = now
            if self._winter_mode:
                self._last_winter_cycle = now

        elif not pump_should_be_on and pump_is_on:
            if not self._can_turn_off(now):
                _LOGGER.debug(
                    "Anti-cycling: skip turn-off (last ON < %d min ago)",
                    MIN_ON_MINUTES,
                )
                return
            await self._set_pump(False)
            self._last_commanded_off = now

    def _can_turn_on(self, now: datetime) -> bool:
        if self._last_commanded_off is None:
            return True
        elapsed = (now - self._last_commanded_off).total_seconds() / 60.0
        return elapsed >= MIN_OFF_MINUTES

    def _can_turn_off(self, now: datetime) -> bool:
        if self._last_commanded_on is None:
            return True
        elapsed = (now - self._last_commanded_on).total_seconds() / 60.0
        return elapsed >= MIN_ON_MINUTES

    async def _set_pump(self, turn_on: bool) -> None:
        """Call HA service to change pump switch state."""
        entity_id = self.config_entry.data[CONF_PUMP_SWITCH]
        service = "turn_on" if turn_on else "turn_off"
        try:
            await self.hass.services.async_call(
                "homeassistant",
                service,
                {"entity_id": entity_id},
                blocking=True,
            )
            _LOGGER.info("Pool pump: %s", "ON" if turn_on else "OFF")
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to %s pool pump: %s", service, exc)

    # ------------------------------------------------------------------
    # Pump run-time tracking
    # ------------------------------------------------------------------

    def _read_pump_state(self) -> bool:
        entity_id = self.config_entry.data[CONF_PUMP_SWITCH]
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        return state.state == "on"

    def _accumulate_run_time(self, now: datetime, pump_is_on: bool) -> None:
        """Add elapsed on-time to h_done since last check."""
        if self._last_state_check is not None and self._pump_was_on:
            elapsed_h = (now - self._last_state_check).total_seconds() / 3600.0
            # Clamp to a sane maximum per cycle (e.g. 2× the scan interval) to
            # avoid huge accumulations after long downtimes / restarts.
            max_elapsed = DEFAULT_SCAN_INTERVAL * 2 / 60.0
            elapsed_h = min(elapsed_h, max_elapsed)
            self._h_done = min(self._h_done + elapsed_h, MAX_FILTRATION_HOURS)

        self._last_state_check = now
        self._pump_was_on = pump_is_on

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    def _check_daily_reset(self, now: datetime) -> None:
        """Reset counters at the configured daily reset time."""
        opts = self.config_entry.options
        reset_str = opts.get(CONF_RESET_TIME, DEFAULT_RESET_TIME)
        try:
            rh, rm = (int(x) for x in reset_str.split(":"))
        except (ValueError, AttributeError):
            rh, rm = 0, 0

        today_str = now.date().isoformat()
        today_reset = now.replace(hour=rh, minute=rm, second=0, microsecond=0)

        # Reset once per day, after the reset time has passed
        if now >= today_reset and self._last_reset_date != today_str:
            _LOGGER.info(
                "Pool filtration: daily reset (h_done=%.2f → 0, h_target=%.2f → 0)",
                self._h_done,
                self._h_target,
            )
            self._h_done = 0.0
            self._h_target = 0.0
            self._last_reset_date = today_str

    # ------------------------------------------------------------------
    # Solar noon
    # ------------------------------------------------------------------

    def _solar_noon(self, now: datetime) -> datetime:
        """Return solar noon for today in local time."""
        try:
            location, _ = get_astral_location(self.hass)
            from astral.sun import noon as astral_noon  # bundled with HA

            tz = dt_util.get_time_zone(self.hass.config.time_zone)
            solar_noon = astral_noon(location.observer, now.date(), tzinfo=tz)
            return solar_noon
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Solar noon calculation failed (%s), using 13:00", exc)
            return now.replace(hour=13, minute=0, second=0, microsecond=0)

    # ------------------------------------------------------------------
    # Sensor helpers
    # ------------------------------------------------------------------

    def _read_state(self, conf_key: str, fallback: float) -> float:
        entity_id = self.config_entry.data.get(conf_key)
        if not entity_id:
            return fallback
        return self._float_state(entity_id, fallback)

    def _read_wind(self, air_temp: float) -> float:
        """Read wind speed, optionally taking max with gust sensor."""
        wind = self._read_state(CONF_WIND_SENSOR, FALLBACK_WIND)
        gust_entity = self.config_entry.data.get(CONF_WIND_GUST_SENSOR)
        if gust_entity:
            gust = self._float_state(gust_entity, FALLBACK_WIND)
            wind = max(wind, gust)
        return wind

    def _float_state(self, entity_id: str, fallback: float) -> float:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            _LOGGER.debug("Entity %s unavailable, using fallback %.1f", entity_id, fallback)
            return fallback
        try:
            return float(state.state)
        except ValueError:
            _LOGGER.debug(
                "Entity %s has non-numeric state %r, using fallback %.1f",
                entity_id,
                state.state,
                fallback,
            )
            return fallback

    # ------------------------------------------------------------------
    # Rolling average helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _push(
        history: deque[tuple[datetime, float]],
        now: datetime,
        value: float,
        window_hours: float,
    ) -> None:
        """Append value and prune entries older than window_hours."""
        history.append((now, value))
        cutoff = now - timedelta(hours=window_hours)
        while history and history[0][0] < cutoff:
            history.popleft()

    @staticmethod
    def _avg(history: deque[tuple[datetime, float]]) -> float:
        """Weighted average – simple mean for equal-interval updates."""
        if not history:
            return 0.0
        return sum(v for _, v in history) / len(history)

    # ------------------------------------------------------------------
    # Options helpers
    # ------------------------------------------------------------------

    def _allowed_hours(self) -> tuple[int, int]:
        opts = self.config_entry.options
        start = int(opts.get(CONF_ALLOWED_START, DEFAULT_ALLOWED_START))
        end = int(opts.get(CONF_ALLOWED_END, DEFAULT_ALLOWED_END))
        return start, end

    # ------------------------------------------------------------------
    # Persistent storage
    # ------------------------------------------------------------------

    async def _load_persistent_data(self) -> None:
        data: dict | None = await self._store.async_load()
        if not data:
            return

        self._h_target = float(data.get("h_target", 0.0))
        self._h_done = float(data.get("h_done", 0.0))
        self._last_reset_date = data.get("last_reset_date")
        self._pump_was_on = bool(data.get("pump_was_on", False))
        self._winter_mode = bool(data.get("winter_mode", False))

        def _parse_dt(key: str) -> datetime | None:
            raw = data.get(key)
            if raw is None:
                return None
            try:
                return datetime.fromisoformat(raw)
            except (ValueError, TypeError):
                return None

        self._last_commanded_on = _parse_dt("last_commanded_on")
        self._last_commanded_off = _parse_dt("last_commanded_off")
        self._last_state_check = _parse_dt("last_state_check")
        self._last_winter_cycle = _parse_dt("last_winter_cycle")

        _LOGGER.debug(
            "Loaded persistent data: h_target=%.2f h_done=%.2f winter=%s",
            self._h_target,
            self._h_done,
            self._winter_mode,
        )

    async def _save_persistent_data(self) -> None:
        def _iso(dt: datetime | None) -> str | None:
            return dt.isoformat() if dt else None

        await self._store.async_save(
            {
                "h_target": self._h_target,
                "h_done": self._h_done,
                "last_reset_date": self._last_reset_date,
                "pump_was_on": self._pump_was_on,
                "winter_mode": self._winter_mode,
                "last_commanded_on": _iso(self._last_commanded_on),
                "last_commanded_off": _iso(self._last_commanded_off),
                "last_state_check": _iso(self._last_state_check),
                "last_winter_cycle": _iso(self._last_winter_cycle),
            }
        )
