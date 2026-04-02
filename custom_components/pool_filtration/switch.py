"""Switch platform for Pool Filtration – winter mode toggle."""
from __future__ import annotations

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
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
    """Set up Pool Filtration switches from config entry."""
    coordinator: PoolFiltrationCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PoolWinterModeSwitch(coordinator, entry),
        PoolEcoModeSwitch(coordinator, entry),
        PoolBusyModeSwitch(coordinator, entry),
    ])


class PoolWinterModeSwitch(CoordinatorEntity[PoolFiltrationCoordinator], SwitchEntity):
    """Switch to enable/disable winter (anti-freeze) mode."""

    _attr_has_entity_name = True
    _attr_translation_key = "winter_mode"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:snowflake"

    def __init__(
        self,
        coordinator: PoolFiltrationCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_winter_mode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Pool Filtration",
            "manufacturer": "Pool Filtration",
            "model": "Smart Controller",
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator._winter_mode

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        await self.coordinator.set_winter_mode(True)

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        await self.coordinator.set_winter_mode(False)


class PoolEcoModeSwitch(CoordinatorEntity[PoolFiltrationCoordinator], SwitchEntity):
    """Switch to enable/disable eco (off-peak optimisation) mode."""

    _attr_has_entity_name = True
    _attr_translation_key = "eco_mode"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:leaf"

    def __init__(
        self,
        coordinator: PoolFiltrationCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_eco_mode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Pool Filtration",
            "manufacturer": "Pool Filtration",
            "model": "Smart Controller",
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator._eco_mode

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        await self.coordinator.set_eco_mode(True)

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        await self.coordinator.set_eco_mode(False)


class PoolBusyModeSwitch(CoordinatorEntity[PoolFiltrationCoordinator], SwitchEntity):
    """Switch to enable/disable busy (high-occupancy) mode."""

    _attr_has_entity_name = True
    _attr_translation_key = "busy_mode"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:pool"

    def __init__(
        self,
        coordinator: PoolFiltrationCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_busy_mode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Pool Filtration",
            "manufacturer": "Pool Filtration",
            "model": "Smart Controller",
        }

    @property
    def is_on(self) -> bool:
        return self.coordinator._busy_mode

    async def async_turn_on(self, **kwargs) -> None:  # noqa: ANN003
        await self.coordinator.set_busy_mode(True)

    async def async_turn_off(self, **kwargs) -> None:  # noqa: ANN003
        await self.coordinator.set_busy_mode(False)
