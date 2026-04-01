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
    CONF_ECO_OFF_PEAK_START,
    CONF_ECO_OFF_PEAK_END,
    CONF_ECO_OFF_PEAK_SENSOR,
    DEFAULT_RESET_TIME,
    DEFAULT_ALLOWED_START,
    DEFAULT_ALLOWED_END,
    DEFAULT_WINTER_CYCLE_HOURS,
    DEFAULT_WINTER_RUN_MINUTES,
)

_SLIDER = "slider"


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
        # Do NOT pass config_entry here – HA 2024.x+ sets it automatically as
        # a read-only property on the OptionsFlow base class.  Passing it to
        # __init__ and then assigning self.config_entry would raise
        # AttributeError ("can't set attribute") on those versions.
        return PoolFiltrationOptionsFlow()


class PoolFiltrationOptionsFlow(config_entries.OptionsFlow):
    """Handle operational option updates."""

    # No __init__ override – self.config_entry is provided by the HA framework.

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Show the options form (general + winter + eco)."""
        opts = self.config_entry.options

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        def _num(min_: int, max_: int, step: int = 1) -> selector.NumberSelector:
            return selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=min_, max=max_, step=step, mode=_SLIDER
                )
            )

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
                # ── Eco mode – Option A (fixed hours) ──────────────────────
                vol.Optional(
                    CONF_ECO_OFF_PEAK_START,
                    description={"suggested_value": opts.get(CONF_ECO_OFF_PEAK_START)},
                ): _num(0, 23),
                vol.Optional(
                    CONF_ECO_OFF_PEAK_END,
                    description={"suggested_value": opts.get(CONF_ECO_OFF_PEAK_END)},
                ): _num(0, 23),
                # ── Eco mode – Option B (binary sensor) ────────────────────
                vol.Optional(
                    CONF_ECO_OFF_PEAK_SENSOR,
                    description={
                        "suggested_value": opts.get(CONF_ECO_OFF_PEAK_SENSOR)
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
