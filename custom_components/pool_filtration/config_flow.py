"""Config flow for Pool Filtration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
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
    TARGET_FACTOR_MIN,
    TARGET_FACTOR_MAX,
    CONF_MAX_FILTRATION_HOURS,
    MAX_FILTRATION_HOURS,
    MAX_FILTRATION_HOURS_UPPER,
    CONF_ECO_OFF_PEAK_SLOTS,
    CONF_ECO_OFF_PEAK_SENSOR,
    CONF_BUSY_BOOST_DURATION,
    DEFAULT_BUSY_BOOST_DURATION,
    BUSY_BOOST_MIN_HOURS,
    BUSY_BOOST_MAX_HOURS,
    DEFAULT_RESET_TIME,
    DEFAULT_ALLOWED_START,
    DEFAULT_ALLOWED_END,
    DEFAULT_WINTER_CYCLE_HOURS,
    DEFAULT_WINTER_RUN_MINUTES,
)

_SLIDER = "slider"

# Entity conf keys exposed in the options override section
_ENTITY_KEYS = (
    CONF_PUMP_SWITCH,
    CONF_WATER_TEMP,
    CONF_AIR_TEMP,
    CONF_UV_SENSOR,
    CONF_WIND_SENSOR,
    CONF_WIND_GUST_SENSOR,
)


class PoolFiltrationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 1 – entity selection."""
        if user_input is not None:
            return self.async_create_entry(title="Pool Filtration", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_PUMP_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Required(CONF_WATER_TEMP): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="temperature"
                    )
                ),
                vol.Required(CONF_AIR_TEMP): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="temperature"
                    )
                ),
                vol.Required(CONF_UV_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_WIND_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_WIND_GUST_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> PoolFiltrationOptionsFlow:
        """Return the options flow."""
        # Do NOT pass config_entry — HA 2024.x+ exposes it as a read-only property.
        return PoolFiltrationOptionsFlow()


class PoolFiltrationOptionsFlow(config_entries.OptionsFlow):
    """Handle operational option updates and sensor overrides."""

    # No __init__ override – self.config_entry is injected by the HA framework.

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Show the options form."""
        opts = self.config_entry.options
        data = self.config_entry.data

        if user_input is not None:
            # Strip empty strings so _get_entity() falls back to original data
            cleaned = {k: v for k, v in user_input.items() if v not in (None, "")}
            return self.async_create_entry(title="", data=cleaned)

        def _num(min_: int, max_: int, step: int = 1) -> selector.NumberSelector:
            return selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=min_, max=max_, step=step, mode=_SLIDER
                )
            )

        def _cur_entity(key: str) -> str | None:
            """Current entity: options override first, then original data."""
            return opts.get(key) or data.get(key)

        schema = vol.Schema(
            {
                # ── General ────────────────────────────────────────────────
                vol.Optional(
                    CONF_RESET_TIME,
                    default=opts.get(CONF_RESET_TIME, DEFAULT_RESET_TIME),
                ): selector.TimeSelector(selector.TimeSelectorConfig()),
                vol.Optional(
                    CONF_ALLOWED_START,
                    default=int(opts.get(CONF_ALLOWED_START, DEFAULT_ALLOWED_START)),
                ): _num(0, 23),
                vol.Optional(
                    CONF_ALLOWED_END,
                    default=int(opts.get(CONF_ALLOWED_END, DEFAULT_ALLOWED_END)),
                ): _num(1, 24),
                # ── Plafond journalier ──────────────────────────────────────
                vol.Optional(
                    CONF_MAX_FILTRATION_HOURS,
                    default=float(
                        opts.get(CONF_MAX_FILTRATION_HOURS, MAX_FILTRATION_HOURS)
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=6.0,
                        max=MAX_FILTRATION_HOURS_UPPER,
                        step=0.5,
                        mode=_SLIDER,
                    )
                ),
                # ── Facteur de correction de l'objectif ────────────────────
                vol.Optional(
                    CONF_TARGET_FACTOR,
                    default=float(opts.get(CONF_TARGET_FACTOR, DEFAULT_TARGET_FACTOR)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=TARGET_FACTOR_MIN,
                        max=TARGET_FACTOR_MAX,
                        step=0.1,
                        mode=_SLIDER,
                    )
                ),
                # ── Winter ─────────────────────────────────────────────────
                vol.Optional(
                    CONF_WINTER_CYCLE_HOURS,
                    default=int(
                        opts.get(CONF_WINTER_CYCLE_HOURS, DEFAULT_WINTER_CYCLE_HOURS)
                    ),
                ): _num(1, 12),
                vol.Optional(
                    CONF_WINTER_RUN_MINUTES,
                    default=int(
                        opts.get(CONF_WINTER_RUN_MINUTES, DEFAULT_WINTER_RUN_MINUTES)
                    ),
                ): _num(10, 120, step=5),
                # ── Busy mode – boost nocturne ──────────────────────────────
                vol.Optional(
                    CONF_BUSY_BOOST_DURATION,
                    default=float(
                        opts.get(CONF_BUSY_BOOST_DURATION, DEFAULT_BUSY_BOOST_DURATION)
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=BUSY_BOOST_MIN_HOURS,
                        max=BUSY_BOOST_MAX_HOURS,
                        step=0.5,
                        mode=_SLIDER,
                    )
                ),
                # ── Eco – heures creuses ────────────────────────────────────
                vol.Optional(
                    CONF_ECO_OFF_PEAK_SLOTS,
                    description={
                        "suggested_value": opts.get(CONF_ECO_OFF_PEAK_SLOTS, "")
                    },
                ): selector.TextSelector(selector.TextSelectorConfig()),
                vol.Optional(
                    CONF_ECO_OFF_PEAK_SENSOR,
                    description={
                        "suggested_value": opts.get(CONF_ECO_OFF_PEAK_SENSOR)
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
                # ── Capteurs – modifications ────────────────────────────────
                vol.Optional(
                    CONF_PUMP_SWITCH,
                    description={"suggested_value": _cur_entity(CONF_PUMP_SWITCH)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(
                    CONF_WATER_TEMP,
                    description={"suggested_value": _cur_entity(CONF_WATER_TEMP)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="temperature"
                    )
                ),
                vol.Optional(
                    CONF_AIR_TEMP,
                    description={"suggested_value": _cur_entity(CONF_AIR_TEMP)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="temperature"
                    )
                ),
                vol.Optional(
                    CONF_UV_SENSOR,
                    description={"suggested_value": _cur_entity(CONF_UV_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_WIND_SENSOR,
                    description={"suggested_value": _cur_entity(CONF_WIND_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_WIND_GUST_SENSOR,
                    description={"suggested_value": _cur_entity(CONF_WIND_GUST_SENSOR)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
