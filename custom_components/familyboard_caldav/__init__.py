"""FamilyBoard CalDAV integration for Home Assistant.

Provides RFC 5545-compliant CalDAV VTODO entities. Each configured
CalDAV connection discovers calendars and exposes them as ``todo.*``
entities with full RRULE support.

Designed to work alongside the FamilyBoard integration: the ``todo.*``
entity IDs can be used in ``chores:`` / ``shared_chores:`` just like
any other todo entity.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .caldav_client import CalDAVClientManager
from .coordinator import CalDAVConfigEntry, CalDAVCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.TODO]


async def async_setup_entry(hass: HomeAssistant, entry: CalDAVConfigEntry) -> bool:
    """Set up a FamilyBoard CalDAV connection from a config entry."""
    config: dict[str, Any] = dict(entry.data)
    manager = CalDAVClientManager(hass, config)

    coordinator = CalDAVCoordinator(hass, entry, manager)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: CalDAVConfigEntry) -> bool:
    """Unload a CalDAV config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
