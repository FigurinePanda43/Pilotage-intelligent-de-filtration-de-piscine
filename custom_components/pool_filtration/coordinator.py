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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
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
    CONF_TARGET_FACTOR,
    DEFAULT_TARGET_FACTOR,
    CONF_ECO_OFF_PEAK_SLOTS,
    CONF_ECO_OFF_PEAK_SENSOR,
    CONF_BUSY_BOOST_DURATION,
    DEFAULT_BUSY_BOOST_DURATION,
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
    ECO_DAY_MIN_RATIO,
    ECO_DAY_MIN_HOURS,
    ECO_TEMP_THRESHOLD,
    ECO_UV_THRESHOLD,
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
        self._h_done_day: float = 0.0       # pump time during solar window today
        self._last_reset_date: str | None = None
        self._last_commanded_on: datetime | None = None
        self._last_commanded_off: datetime | None = None
        self._last_state_check: datetime | None = None
        self._pump_was_on: bool = False
        self._winter_mode: bool = False
        self._last_winter_cycle: datetime | None = None
        self._eco_mode: bool = False
        self._busy_mode: bool = False

        self._persistent_loaded: bool = False

    # ------------------------------------------------------------------
    # Public helpers (called from switch entity)
    # ------------------------------------------------------------------

    async def set_winter_mode(self, enabled: bool) -> None:
        """Enable or disable winter mode and persist the change."""
        self._winter_mode = enabled
        _LOGGER.info("Pool filtration: winter mode %s", "ENABLED" if enabled else "DISABLED")
        await self._save_persistent_data()
        await self.async_request_refresh()

    async def set_eco_mode(self, enabled: bool) -> None:
        """Enable or disable eco mode and persist the change."""
        self._eco_mode = enabled
        _LOGGER.info("Pool filtration: eco mode %s", "ENABLED" if enabled else "DISABLED")
        await self._save_persistent_data()
        await self.async_request_refresh()

    async def reset_daily_counters(self) -> None:
        """Manually reset the filtration target so it is recalculated on the next cycle.

        Only h_target is cleared — h_done and h_done_day are preserved so the
        record of filtration already performed today is not lost.
        """
        self._h_target = 0.0
        _LOGGER.info("Pool filtration: manual target reset triggered")
        await self._save_persistent_data()
        await self.async_request_refresh()

    async def set_busy_mode(self, enabled: bool) -> None:
        """Enable or disable busy (high-occupancy) mode and persist the change."""
        self._busy_mode = enabled
        _LOGGER.info("Pool filtration: busy mode %s", "ENABLED" if enabled else "DISABLED")
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
        water_temp, wt_degraded = self._read_state_with_flag(CONF_WATER_TEMP, FALLBACK_WATER_TEMP)
        air_temp, at_degraded = self._read_state_with_flag(CONF_AIR_TEMP, FALLBACK_AIR_TEMP)
        uv, uv_degraded = self._read_state_with_flag(CONF_UV_SENSOR, FALLBACK_UV)
        wind, wind_degraded = self._read_wind_with_flag()
        degraded = wt_degraded or at_degraded or uv_degraded or wind_degraded

        # Prune stale entries every cycle regardless of sensor availability.
        # This ensures the last-known-value fallback is bounded to the history
        # window: unavailable < window → last known value; ≥ window → hardcoded fallback.
        self._prune(self._water_temp_history, now, WATER_TEMP_AVG_HOURS)
        self._prune(self._air_temp_history, now, AIR_TEMP_AVG_HOURS)
        self._prune(self._uv_history, now, UV_AVG_HOURS)
        self._prune(self._wind_history, now, WIND_AVG_HOURS)

        # Append only real (non-fallback) readings
        if not wt_degraded:
            self._water_temp_history.append((now, water_temp))
        if not at_degraded:
            self._air_temp_history.append((now, air_temp))
        if not uv_degraded:
            self._uv_history.append((now, uv))
        if not wind_degraded:
            self._wind_history.append((now, wind))

        # Averages:
        #   capteur indisponible < fenêtre → moyenne des dernières vraies valeurs
        #   capteur indisponible ≥ fenêtre → deque vide → valeur par défaut
        water_temp_avg = self._avg(self._water_temp_history) if self._water_temp_history else FALLBACK_WATER_TEMP
        air_temp_avg = self._avg(self._air_temp_history) if self._air_temp_history else FALLBACK_AIR_TEMP
        uv_avg = self._avg(self._uv_history) if self._uv_history else FALLBACK_UV
        wind_avg = self._avg(self._wind_history) if self._wind_history else FALLBACK_WIND

        # Compute filtration targets
        h_min = self._h_min(water_temp_avg)
        h_dyn = self._h_dyn(water_temp_avg, uv_avg, wind_avg, air_temp_avg)

        # Apply user correction factor (0.5–2.0, default 1.0)
        target_factor = float(
            self.config_entry.options.get(CONF_TARGET_FACTOR, DEFAULT_TARGET_FACTOR)
        )
        h_min_adj = min(h_min * target_factor, MAX_FILTRATION_HOURS)
        h_dyn_adj = min(h_dyn * target_factor, MAX_FILTRATION_HOURS)

        # Only ratchet h_target when we have at least one real temperature reading.
        # If the history is empty AND sensors are degraded (e.g. first cycle after
        # a restart), the averages are fallback values (20 °C) which would inflate
        # h_target to 10 h and lock it there for the rest of the day.
        if self._water_temp_history or not degraded:
            self._h_target = max(self._h_target, h_min_adj, h_dyn_adj)

        # Solar window – computed BEFORE accumulation so in_window is available
        solar_noon = self._solar_noon(now)
        window_start = solar_noon - timedelta(hours=SOLAR_WINDOW_HOURS)
        window_end = solar_noon + timedelta(hours=SOLAR_WINDOW_HOURS)
        in_window = window_start <= now <= window_end
        time_remaining_window = max(
            0.0, (window_end - now).total_seconds() / 3600.0
        )

        # Busy mode – night boost window (centered on solar midnight)
        boost_start, boost_end = self._boost_window(now)
        in_boost_window = boost_start <= now < boost_end

        # Accumulate pump run-time (tracks in-window time separately for eco)
        pump_is_on = self._read_pump_state()
        self._accumulate_run_time(now, pump_is_on, in_window)

        h_remaining = max(0.0, self._h_target - self._h_done)

        # ── Eco mode computations ────────────────────────────────────────
        h_day_min = max(ECO_DAY_MIN_RATIO * self._h_target, ECO_DAY_MIN_HOURS)
        h_shiftable = max(0.0, self._h_target - h_day_min)
        h_done_shiftable = max(0.0, self._h_done - self._h_done_day)
        h_shiftable_remaining = max(0.0, h_shiftable - h_done_shiftable)
        is_off_peak = self._is_off_peak(now)

        # Progressive minimum: fraction of h_day_min expected by current time
        if in_window:
            w_total = (window_end - window_start).total_seconds()
            w_elapsed_frac = (now - window_start).total_seconds() / w_total
            h_day_min_prog = h_day_min * max(0.0, min(1.0, w_elapsed_frac))
        else:
            h_day_min_prog = h_day_min

        eco_allowed = (
            self._eco_mode
            and not self._winter_mode
            # No critical catch-up in progress
            and not (time_remaining_window > 0 and h_remaining > time_remaining_window)
            # Environmental conditions are moderate
            and water_temp <= ECO_TEMP_THRESHOLD
            and uv_avg <= ECO_UV_THRESHOLD
            # Solar window minimum is on track
            and not (in_window and self._h_done_day < h_day_min_prog)
        )

        # ── Delay status ─────────────────────────────────────────────────
        if h_remaining > 0 and in_window and time_remaining_window > 0:
            delay_status = (
                "late" if h_remaining > time_remaining_window else "on_time"
            )
        elif h_remaining > 0 and now > window_end:
            delay_status = "late"
        else:
            delay_status = "on_time"

        # ── Frost / winter condition ──────────────────────────────────────
        frost_condition = (
            air_temp <= WINTER_AIR_TEMP_THRESHOLD
            and water_temp <= WINTER_WATER_TEMP_THRESHOLD
        )

        # ── Pump decision ────────────────────────────────────────────────
        pump_should_be_on, decision_reason = self._decide(
            now=now,
            h_remaining=h_remaining,
            in_window=in_window,
            time_remaining_window=time_remaining_window,
            window_end=window_end,
            frost_condition=frost_condition,
            eco_allowed=eco_allowed,
            h_day_min=h_day_min,
            h_shiftable_remaining=h_shiftable_remaining,
            is_off_peak=is_off_peak,
            in_boost_window=in_boost_window,
            degraded=degraded,
        )

        system_state = self._compute_system_state(pump_should_be_on, decision_reason, degraded)

        await self._apply_decision(now, pump_is_on, pump_should_be_on)
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
            "target_factor": target_factor,
            "h_min_adj": h_min_adj,
            "h_dyn_adj": h_dyn_adj,
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
            "decision_reason": decision_reason,
            "system_state": system_state,
            # Winter
            "winter_mode": self._winter_mode,
            "frost_condition": frost_condition,
            # Eco
            "eco_mode": self._eco_mode,
            "eco_allowed": eco_allowed,
            "is_off_peak": is_off_peak,
            "current_tariff": "HC" if is_off_peak else "HP",
            "h_day_min": h_day_min,
            "h_shiftable": h_shiftable,
            "h_shiftable_remaining": h_shiftable_remaining,
            "h_done_day": self._h_done_day,
            # Busy mode
            "busy_mode": self._busy_mode,
            "in_boost_window": in_boost_window,
            "boost_start": boost_start,
            "boost_end": boost_end,
            "boost_remaining": (
                max(0.0, (boost_end - now).total_seconds() / 3600.0)
                if in_boost_window else 0.0
            ),
            "busy_boost_duration": float(
                self.config_entry.options.get(CONF_BUSY_BOOST_DURATION, DEFAULT_BUSY_BOOST_DURATION)
            ),
            # Diagnostics
            "degraded": degraded,
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
        h_remaining: float,
        in_window: bool,
        time_remaining_window: float,
        window_end: datetime,
        frost_condition: bool,
        eco_allowed: bool,
        h_day_min: float,
        h_shiftable_remaining: float,
        is_off_peak: bool,
        in_boost_window: bool,
        degraded: bool,
    ) -> tuple[bool, str]:
        """Return (should_run, reason) for pump decision."""

        # 1. Winter mode overrides everything
        if self._winter_mode:
            return self._decide_winter(now, frost_condition)

        # 2. Busy mode – night boost (suspended when degraded)
        if self._busy_mode and in_boost_window and not degraded:
            return True, "busy_boost"

        # 3. Eco mode (only when eco_allowed; otherwise fall through to normal logic)
        if eco_allowed:
            return self._decide_eco(
                now, h_remaining, window_end, h_shiftable_remaining, is_off_peak,
            )

        # ── Normal mode ──────────────────────────────────────────────────
        if self._h_done >= MAX_FILTRATION_HOURS:
            return False, "daily_limit_reached"

        if h_remaining <= 0:
            return False, "target_reached"

        allowed_start, allowed_end = self._allowed_hours()
        current_hour = now.hour

        cond1 = in_window and h_remaining > 0
        cond2 = time_remaining_window > 0 and h_remaining > time_remaining_window
        cond3 = now >= window_end and self._h_done < self._h_target

        if not (cond1 or cond2 or cond3):
            return False, "idle"

        inside_allowed = allowed_start <= current_hour < allowed_end
        if not inside_allowed and not cond3:
            return False, "outside_hours"

        if cond3:
            return True, "end_of_day_catchup"
        if cond2:
            return True, "catching_up_delay"
        return True, "solar_window"

    def _decide_winter(self, now: datetime, frost_condition: bool) -> tuple[bool, str]:
        """Winter mode: run anti-freeze cycles when frost is detected, OFF otherwise."""
        if not frost_condition:
            # No frost risk → pump stays completely OFF in winter mode
            return False, "winter_standby"

        opts = self.config_entry.options
        cycle_hours = int(opts.get(CONF_WINTER_CYCLE_HOURS, DEFAULT_WINTER_CYCLE_HOURS))
        run_minutes = int(opts.get(CONF_WINTER_RUN_MINUTES, DEFAULT_WINTER_RUN_MINUTES))

        if self._last_winter_cycle is None:
            return True, "winter_frost_cycle"

        elapsed_min = (now - self._last_winter_cycle).total_seconds() / 60.0

        # Still within the current run window
        if elapsed_min <= run_minutes:
            return True, "winter_frost_cycle"

        # Time for a new cycle
        if elapsed_min >= cycle_hours * 60.0:
            return True, "winter_frost_cycle"

        # Between cycles
        return False, "winter_frost_cycle"

    def _decide_eco(
        self,
        now: datetime,
        h_remaining: float,
        window_end: datetime,
        h_shiftable_remaining: float,
        is_off_peak: bool,
    ) -> tuple[bool, str]:
        """Eco mode decision: shift shiftable hours to off-peak, guard day minimum."""
        if self._h_done >= MAX_FILTRATION_HOURS:
            return False, "daily_limit_reached"

        if h_remaining <= 0:
            return False, "target_reached"

        allowed_start, allowed_end = self._allowed_hours()
        current_hour = now.hour

        # Safety: end-of-day catch-up always overrides eco preference
        if now >= window_end and self._h_done < self._h_target:
            if allowed_start <= current_hour < allowed_end:
                return True, "end_of_day_catchup"

        if not (allowed_start <= current_hour < allowed_end):
            return False, "outside_hours"

        # Off-peak hours with shiftable time remaining
        if is_off_peak and h_shiftable_remaining > 0:
            return True, "eco_off_peak"

        # Peak hours in eco mode → wait for off-peak (day min already met because
        # eco_allowed=True guarantees h_done_day >= h_day_min_prog)
        return False, "eco_peak_hours"

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
        entity_id = self._get_entity(CONF_PUMP_SWITCH)
        if not entity_id:
            _LOGGER.error("Pool pump switch entity not configured — cannot control pump")
            return
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
        entity_id = self._get_entity(CONF_PUMP_SWITCH)
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        return state.state == "on"

    def _accumulate_run_time(
        self, now: datetime, pump_is_on: bool, in_window: bool
    ) -> None:
        """Add elapsed on-time to h_done (and h_done_day when in solar window)."""
        if self._last_state_check is not None and self._pump_was_on:
            elapsed_h = (now - self._last_state_check).total_seconds() / 3600.0
            # Cap to 2× scan interval to avoid huge jumps after restarts
            max_elapsed = DEFAULT_SCAN_INTERVAL * 2 / 60.0
            elapsed_h = min(elapsed_h, max_elapsed)
            self._h_done = min(self._h_done + elapsed_h, MAX_FILTRATION_HOURS)
            if in_window:
                self._h_done_day = min(self._h_done_day + elapsed_h, MAX_FILTRATION_HOURS)

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
                "Pool filtration: daily reset (h_done=%.2f → 0, h_done_day=%.2f → 0, h_target=%.2f → 0)",
                self._h_done,
                self._h_done_day,
                self._h_target,
            )
            self._h_done = 0.0
            self._h_done_day = 0.0
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

    def _sunrise_for_date(self, d) -> datetime:
        """Return sunrise datetime for a given date."""
        try:
            location, _ = get_astral_location(self.hass)
            from astral.sun import sunrise as astral_sunrise  # bundled with HA
            tz = dt_util.get_time_zone(self.hass.config.time_zone)
            return astral_sunrise(location.observer, d, tzinfo=tz)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Sunrise calculation failed (%s), using 06:00", exc)
            from datetime import timezone
            tz = dt_util.get_time_zone(self.hass.config.time_zone)
            from datetime import datetime as _dt
            return _dt(d.year, d.month, d.day, 6, 0, 0, tzinfo=tz)

    def _sunset_for_date(self, d) -> datetime:
        """Return sunset datetime for a given date."""
        try:
            location, _ = get_astral_location(self.hass)
            from astral.sun import sunset as astral_sunset  # bundled with HA
            tz = dt_util.get_time_zone(self.hass.config.time_zone)
            return astral_sunset(location.observer, d, tzinfo=tz)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Sunset calculation failed (%s), using 21:00", exc)
            tz = dt_util.get_time_zone(self.hass.config.time_zone)
            from datetime import datetime as _dt
            return _dt(d.year, d.month, d.day, 21, 0, 0, tzinfo=tz)

    def _boost_window(self, now: datetime) -> tuple[datetime, datetime]:
        """Return (boost_start, boost_end) centered on solar midnight for the current night.

        Before noon: uses previous evening's sunset → today's sunrise.
        After noon:  uses today's sunset → tomorrow's sunrise.
        """
        if now.hour < 12:
            date_eve = (now - timedelta(days=1)).date()
            date_morn = now.date()
        else:
            date_eve = now.date()
            date_morn = (now + timedelta(days=1)).date()

        sunset = self._sunset_for_date(date_eve)
        sunrise = self._sunrise_for_date(date_morn)

        night_mid = sunset + (sunrise - sunset) / 2

        boost_h = float(
            self.config_entry.options.get(CONF_BUSY_BOOST_DURATION, DEFAULT_BUSY_BOOST_DURATION)
        )
        half = timedelta(hours=boost_h / 2)

        # Clamp to the night window so boost never spills into daylight
        boost_start = max(night_mid - half, sunset)
        boost_end = min(night_mid + half, sunrise)

        return boost_start, boost_end

    # ------------------------------------------------------------------
    # System state
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_system_state(
        pump_should_be_on: bool, reason: str, degraded: bool
    ) -> str:
        """High-level system state for dashboard display."""
        if degraded:
            return "degraded"
        if reason.startswith("winter"):
            return "winter"
        if reason == "busy_boost":
            return "busy"
        if reason in ("catching_up_delay", "end_of_day_catchup"):
            return "catching_up"
        if reason.startswith("eco"):
            return "eco"
        if pump_should_be_on:
            return "normal"
        return "idle"

    def _is_off_peak(self, now: datetime) -> bool:
        """Return True when the current time is in an off-peak (heures creuses) slot.

        Priority order:
          1. binary_sensor (Option B) – real-time signal from the grid provider
          2. Multi-slot text string (Option A) – "HH:MM-HH:MM,HH:MM-HH:MM,..."
        If neither is configured, returns False (eco mode has no effect).
        """
        opts = self.config_entry.options

        # ── Option B: binary sensor ─────────────────────────────────────
        sensor_id = opts.get(CONF_ECO_OFF_PEAK_SENSOR)
        if sensor_id:
            state = self.hass.states.get(sensor_id)
            if state is not None and state.state not in ("unavailable", "unknown"):
                return state.state == "on"

        # ── Option A: multi-slot string ─────────────────────────────────
        slots_str: str = opts.get(CONF_ECO_OFF_PEAK_SLOTS, "")
        if not slots_str:
            return False

        current_min = now.hour * 60 + now.minute

        for raw_slot in slots_str.split(","):
            slot = raw_slot.strip()
            if not slot:
                continue
            try:
                start_part, end_part = slot.split("-", 1)
                sh, sm = (int(x) for x in start_part.strip().split(":"))
                eh, em = (int(x) for x in end_part.strip().split(":"))
                start_min = sh * 60 + sm
                end_min = eh * 60 + em
            except (ValueError, AttributeError):
                _LOGGER.debug("Invalid off-peak slot %r — skipping", slot)
                continue

            if start_min <= end_min:
                # Same-day window (e.g. 12:00-14:00)
                if start_min <= current_min < end_min:
                    return True
            else:
                # Overnight window (e.g. 22:00-06:00)
                if current_min >= start_min or current_min < end_min:
                    return True

        return False

    # ------------------------------------------------------------------
    # Entity resolution (options override > original config data)
    # ------------------------------------------------------------------

    def _get_entity(self, conf_key: str) -> str | None:
        """Return the entity ID for a conf key.

        Options take priority so users can change sensors without
        re-running the initial config flow.  Empty strings in options
        are treated as «not set» and fall back to the original data.
        """
        override = self.config_entry.options.get(conf_key)
        if override:
            return override
        return self.config_entry.data.get(conf_key)

    # ------------------------------------------------------------------
    # Sensor helpers
    # ------------------------------------------------------------------

    def _read_state_with_flag(self, conf_key: str, fallback: float) -> tuple[float, bool]:
        """Return (value, is_degraded). is_degraded=True when fallback was used."""
        entity_id = self._get_entity(conf_key)
        if not entity_id:
            return fallback, False  # sensor not configured, not degraded
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            _LOGGER.debug("Entity %s unavailable, using fallback %.1f", entity_id, fallback)
            return fallback, True
        try:
            return float(state.state), False
        except ValueError:
            _LOGGER.debug(
                "Entity %s has non-numeric state %r, using fallback %.1f",
                entity_id, state.state, fallback,
            )
            return fallback, True

    def _read_wind_with_flag(self) -> tuple[float, bool]:
        """Read wind speed, optionally taking max with gust sensor."""
        wind, degraded = self._read_state_with_flag(CONF_WIND_SENSOR, FALLBACK_WIND)
        gust_entity = self._get_entity(CONF_WIND_GUST_SENSOR)
        if gust_entity:
            gust, gust_degraded = self._float_state_with_flag(gust_entity, FALLBACK_WIND)
            wind = max(wind, gust)
            degraded = degraded or gust_degraded
        return wind, degraded

    def _float_state_with_flag(self, entity_id: str, fallback: float) -> tuple[float, bool]:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            _LOGGER.debug("Entity %s unavailable, using fallback %.1f", entity_id, fallback)
            return fallback, True
        try:
            return float(state.state), False
        except ValueError:
            _LOGGER.debug(
                "Entity %s has non-numeric state %r, using fallback %.1f",
                entity_id, state.state, fallback,
            )
            return fallback, True

    # ------------------------------------------------------------------
    # Rolling average helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prune(
        history: deque[tuple[datetime, float]],
        now: datetime,
        window_hours: float,
    ) -> None:
        """Remove entries older than window_hours from the left of the deque."""
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
        self._h_done_day = float(data.get("h_done_day", 0.0))
        self._last_reset_date = data.get("last_reset_date")
        self._pump_was_on = bool(data.get("pump_was_on", False))
        self._winter_mode = bool(data.get("winter_mode", False))
        self._eco_mode = bool(data.get("eco_mode", False))
        self._busy_mode = bool(data.get("busy_mode", False))

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
                "h_done_day": self._h_done_day,
                "last_reset_date": self._last_reset_date,
                "pump_was_on": self._pump_was_on,
                "winter_mode": self._winter_mode,
                "eco_mode": self._eco_mode,
                "busy_mode": self._busy_mode,
                "last_commanded_on": _iso(self._last_commanded_on),
                "last_commanded_off": _iso(self._last_commanded_off),
                "last_state_check": _iso(self._last_state_check),
                "last_winter_cycle": _iso(self._last_winter_cycle),
            }
        )
