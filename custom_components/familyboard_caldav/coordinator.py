"""DataUpdateCoordinator for the FamilyBoard CalDAV integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .caldav_client import CalDAVClientManager, VTodoItem
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type CalDAVConfigEntry = ConfigEntry[CalDAVCoordinator]


class CalDAVCoordinator(DataUpdateCoordinator[dict[str, list[VTodoItem]]]):
    """Coordinate CalDAV VTODO data updates across entities.

    The coordinator owns the :class:`CalDAVClientManager` and periodically
    fetches all VTODOs from every discovered calendar.  Entities read from
    ``coordinator.data[calendar_name]`` instead of polling individually.
    """

    config_entry: CalDAVConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: CalDAVConfigEntry,
        manager: CalDAVClientManager,
    ) -> None:
        """Initialize the CalDAV coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=UPDATE_INTERVAL,
        )
        self.manager = manager

    async def async_setup(self) -> None:
        """Connect to the CalDAV server (called once during entry setup)."""
        try:
            await self.manager.async_start()
        except Exception as err:
            raise ConfigEntryNotReady(
                f"Failed to connect to CalDAV server: {err}"
            ) from err

    async def _async_update_data(self) -> dict[str, list[VTodoItem]]:
        """Fetch VTODOs from all discovered calendars."""
        result: dict[str, list[VTodoItem]] = {}
        for cal_name in self.manager.calendars:
            try:
                result[cal_name] = await self.manager.async_get_todos(cal_name)
            except Exception as err:
                raise UpdateFailed(
                    f"Error fetching todos from {cal_name}: {err}"
                ) from err
        return result

    async def async_shutdown(self) -> None:
        """Disconnect the CalDAV client."""
        await self.manager.async_stop()

    def get_todos(self, calendar_name: str) -> list[VTodoItem]:
        """Return cached VTODOs for a calendar (empty list if unavailable)."""
        if self.data is None:
            return []
        return self.data.get(calendar_name, [])
