"""Sensor platform for Pool Filtration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PoolFiltrationCoordinator


@dataclass(frozen=True, kw_only=True)
class PoolSensorDescription(SensorEntityDescription):
    """Extended description with value extractor."""

    value_fn: Callable[[dict[str, Any]], Any]


# ---------------------------------------------------------------------------
# Sensor catalogue
# ---------------------------------------------------------------------------
SENSORS: tuple[PoolSensorDescription, ...] = (
    # --- Primary filtration sensors ---
    PoolSensorDescription(
        key="filtration_target_hours",
        translation_key="filtration_target_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: round(d["h_target"], 2),
    ),
    PoolSensorDescription(
        key="filtration_done_hours",
        translation_key="filtration_done_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: round(d["h_done"], 2),
    ),
    PoolSensorDescription(
        key="filtration_remaining_hours",
        translation_key="filtration_remaining_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: round(d["h_remaining"], 2),
    ),
    PoolSensorDescription(
        key="filtration_status",
        translation_key="filtration_status",
        value_fn=lambda d: "ON" if d["pump_is_on"] else "OFF",
    ),
    # --- Rolling averages ---
    PoolSensorDescription(
        key="water_temp_avg_3h",
        translation_key="water_temp_avg_3h",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: round(d["water_temp_avg_3h"], 1),
    ),
    PoolSensorDescription(
        key="air_temp_avg_3h",
        translation_key="air_temp_avg_3h",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: round(d["air_temp_avg_3h"], 1),
    ),
    PoolSensorDescription(
        key="uv_avg_1h",
        translation_key="uv_avg_1h",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: round(d["uv_avg_1h"], 1),
    ),
    PoolSensorDescription(
        key="wind_avg_1h",
        translation_key="wind_avg_1h",
        native_unit_of_measurement="km/h",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: round(d["wind_avg_1h"], 1),
    ),
    # --- Advanced computed sensors ---
    PoolSensorDescription(
        key="dynamic_target",
        translation_key="dynamic_target",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: round(d["h_dyn"], 2),
    ),
    PoolSensorDescription(
        key="minimum_target",
        translation_key="minimum_target",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: round(d["h_min"], 2),
    ),
    PoolSensorDescription(
        key="time_remaining_window",
        translation_key="time_remaining_window",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda d: round(d["time_remaining_window"], 2),
    ),
    PoolSensorDescription(
        key="delay_status",
        translation_key="delay_status",
        value_fn=lambda d: d["delay_status"],
    ),
    PoolSensorDescription(
        key="decision_reason",
        translation_key="decision_reason",
        value_fn=lambda d: d["decision_reason"],
    ),
    PoolSensorDescription(
        key="system_state",
        translation_key="system_state",
        value_fn=lambda d: d["system_state"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pool Filtration sensors from config entry."""
    coordinator: PoolFiltrationCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PoolFiltrationSensor(coordinator, entry, description)
        for description in SENSORS
    )


class PoolFiltrationSensor(CoordinatorEntity[PoolFiltrationCoordinator], SensorEntity):
    """A sensor that reads its value from the coordinator's latest data."""

    entity_description: PoolSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolFiltrationCoordinator,
        entry: ConfigEntry,
        description: PoolSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Pool Filtration",
            "manufacturer": "Pool Filtration",
            "model": "Smart Controller",
        }

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        try:
            return self.entity_description.value_fn(self.coordinator.data)
        except (KeyError, TypeError):
            return None
