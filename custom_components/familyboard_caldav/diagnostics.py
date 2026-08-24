"""Diagnostics support for the FamilyBoard CalDAV integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import CalDAVConfigEntry

TO_REDACT = {"password", "username"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CalDAVConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a CalDAV config entry."""
    coordinator = entry.runtime_data
    manager = coordinator.manager

    calendars = list(manager.calendars.keys())

    todo_counts: dict[str, int] = {}
    for cal_name in calendars:
        todo_counts[cal_name] = len(coordinator.get_todos(cal_name))

    return {
        "config": {
            k: "**REDACTED**" if k in TO_REDACT else v for k, v in entry.data.items()
        },
        "calendars": calendars,
        "todo_counts": todo_counts,
        "connected": manager._started,
    }
