"""Button platform for Pool Filtration."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PoolFiltrationCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pool Filtration buttons from config entry."""
    coordinator: PoolFiltrationCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PoolResetButton(coordinator, entry)])


class PoolResetButton(CoordinatorEntity[PoolFiltrationCoordinator], ButtonEntity):
    """Button to manually reset the daily filtration counters."""

    _attr_has_entity_name = True
    _attr_translation_key = "reset_counters"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_icon = "mdi:restart"

    def __init__(
        self,
        coordinator: PoolFiltrationCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_reset_counters"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Pool Filtration",
            "manufacturer": "Pool Filtration",
            "model": "Smart Controller",
        }

    async def async_press(self) -> None:
        """Reset h_done, h_done_day and h_target to zero."""
        await self.coordinator.reset_daily_counters()
