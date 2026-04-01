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
    DEFAULT_RESET_TIME,
    DEFAULT_ALLOWED_START,
    DEFAULT_ALLOWED_END,
    DEFAULT_WINTER_CYCLE_HOURS,
    DEFAULT_WINTER_RUN_MINUTES,
)


class PoolFiltrationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 1 – entity selection."""
        if user_input is not None:
            return self.async_create_entry(
                title="Pool Filtration",
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_PUMP_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Required(CONF_WATER_TEMP): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="temperature",
                    )
                ),
                vol.Required(CONF_AIR_TEMP): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="temperature",
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
        return PoolFiltrationOptionsFlow(config_entry)


class PoolFiltrationOptionsFlow(config_entries.OptionsFlow):
    """Handle operational option updates."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Show options form."""
        opts = self.config_entry.options

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_RESET_TIME,
                    default=opts.get(CONF_RESET_TIME, DEFAULT_RESET_TIME),
                ): selector.TimeSelector(selector.TimeSelectorConfig()),
                vol.Optional(
                    CONF_ALLOWED_START,
                    default=opts.get(CONF_ALLOWED_START, DEFAULT_ALLOWED_START),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=23,
                        step=1,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    CONF_ALLOWED_END,
                    default=opts.get(CONF_ALLOWED_END, DEFAULT_ALLOWED_END),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=24,
                        step=1,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    CONF_WINTER_CYCLE_HOURS,
                    default=opts.get(
                        CONF_WINTER_CYCLE_HOURS, DEFAULT_WINTER_CYCLE_HOURS
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=12,
                        step=1,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    CONF_WINTER_RUN_MINUTES,
                    default=opts.get(
                        CONF_WINTER_RUN_MINUTES, DEFAULT_WINTER_RUN_MINUTES
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=120,
                        step=5,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
