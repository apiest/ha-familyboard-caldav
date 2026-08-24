"""Todo platform for FamilyBoard CalDAV-backed task lists.

Each CalDAV calendar that contains VTODOs is exposed as a
``TodoListEntity`` with RFC 5545-compliant completion: recurring tasks
advance their DUE date instead of being marked completed.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .caldav_client import VTodoItem
from .const import DOMAIN
from .coordinator import CalDAVConfigEntry, CalDAVCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CalDAVConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up CalDAV todo entities from a config entry."""
    coordinator = entry.runtime_data

    entities = [
        FamilyBoardCalDAVTodo(coordinator, cal_name)
        for cal_name in coordinator.manager.calendars
    ]

    if entities:
        async_add_entities(entities)
        _LOGGER.debug("Added %d CalDAV todo entities", len(entities))


class FamilyBoardCalDAVTodo(CoordinatorEntity[CalDAVCoordinator], TodoListEntity):
    """A todo list entity backed by a CalDAV calendar."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(
        self,
        coordinator: CalDAVCoordinator,
        calendar_name: str,
    ) -> None:
        """Initialize the CalDAV todo entity."""
        super().__init__(coordinator)
        self._calendar_name = calendar_name

        safe_name = calendar_name.lower().replace(" ", "_")
        safe_conn = coordinator.manager.name.lower().replace(" ", "_")
        self._attr_unique_id = f"familyboard_caldav_{safe_conn}_{safe_name}"
        self._attr_name = calendar_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=f"CalDAV ({coordinator.manager.name})",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _items(self) -> list[VTodoItem]:
        """Return cached VTODOs from the coordinator."""
        return self.coordinator.get_todos(self._calendar_name)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the list of todo items."""
        return [self._to_ha_item(item) for item in self._items]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose full RFC 5545 VTODO fields not covered by TodoItem."""
        items_data: list[dict[str, Any]] = []
        for item in self._items:
            data: dict[str, Any] = {
                "uid": item.uid,
                "summary": item.summary,
                "status": item.status,
            }
            if item.due is not None:
                data["due"] = item.due.isoformat()
            if item.dtstart is not None:
                data["dtstart"] = item.dtstart.isoformat()
            if item.completed is not None:
                data["completed"] = item.completed.isoformat()
            if item.description:
                data["description"] = item.description
            if item.rrule:
                data["rrule"] = item.rrule
            if item.priority is not None:
                data["priority"] = item.priority
            if item.percent_complete is not None:
                data["percent_complete"] = item.percent_complete
            if item.location:
                data["location"] = item.location
            if item.url:
                data["url"] = item.url
            if item.categories:
                data["categories"] = item.categories
            items_data.append(data)
        return {"vtodo_items": items_data}

    @staticmethod
    def _to_ha_item(item: VTodoItem) -> TodoItem:
        """Convert a VTodoItem to an HA TodoItem."""
        status = (
            TodoItemStatus.COMPLETED
            if item.status == "COMPLETED"
            else TodoItemStatus.NEEDS_ACTION
        )

        due: datetime.date | datetime.datetime | None = item.due
        # HA TodoItem expects date or datetime, not mixed
        if (
            isinstance(due, datetime.datetime)
            and due.hour == 0
            and due.minute == 0
            and due.second == 0
        ):
            due = due.date()

        return TodoItem(
            uid=item.uid,
            summary=item.summary,
            status=status,
            due=due,
            description=item.description,
        )

    async def _refresh(self) -> None:
        """Request a coordinator refresh and write state."""
        await self.coordinator.async_request_refresh()

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a new todo item."""
        await self.coordinator.manager.async_add_todo(
            self._calendar_name,
            item.summary or "",
            due=item.due,
            description=item.description,
        )
        await self._refresh()

    async def async_create_vtodo(
        self,
        summary: str,
        *,
        due: datetime.datetime | datetime.date | None = None,
        dtstart: datetime.datetime | datetime.date | None = None,
        description: str | None = None,
        priority: int | None = None,
        percent_complete: int | None = None,
        location: str | None = None,
        url: str | None = None,
        categories: list[str] | None = None,
    ) -> None:
        """Create a VTODO with all RFC 5545 fields."""
        await self.coordinator.manager.async_add_todo(
            self._calendar_name,
            summary,
            due=due,
            dtstart=dtstart,
            description=description,
            priority=priority,
            percent_complete=percent_complete,
            location=location,
            url=url,
            categories=categories,
        )
        await self._refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update an existing todo item.

        When the status changes to COMPLETED, we delegate to the manager's
        ``async_complete_todo`` which handles RRULE advancement for
        recurring tasks.
        """
        if item.uid is None:
            return

        manager = self.coordinator.manager

        # Check if this is a completion
        if item.status == TodoItemStatus.COMPLETED:
            # Find the current item to check if it's actually changing
            current = next((i for i in self._items if i.uid == item.uid), None)
            if current and current.status != "COMPLETED":
                await manager.async_complete_todo(self._calendar_name, item.uid)
                await self._refresh()
                return

        # Regular field update
        kwargs: dict[str, Any] = {}
        if item.summary is not None:
            kwargs["summary"] = item.summary
        if item.due is not ...:  # type: ignore[comparison-overlap]
            kwargs["due"] = item.due
        if item.description is not ...:  # type: ignore[comparison-overlap]
            kwargs["description"] = item.description
        if item.status is not None:
            kwargs["status"] = (
                "COMPLETED"
                if item.status == TodoItemStatus.COMPLETED
                else "NEEDS-ACTION"
            )

        if kwargs:
            await manager.async_update_todo(self._calendar_name, item.uid, **kwargs)
        await self._refresh()

    async def async_update_vtodo(
        self,
        uid: str,
        *,
        summary: str | None = None,
        due: datetime.datetime | datetime.date | None = ...,  # type: ignore[assignment]
        dtstart: datetime.datetime | datetime.date | None = ...,  # type: ignore[assignment]
        description: str | None = ...,  # type: ignore[assignment]
        status: str | None = None,
        priority: int | None = ...,  # type: ignore[assignment]
        percent_complete: int | None = ...,  # type: ignore[assignment]
        location: str | None = ...,  # type: ignore[assignment]
        url: str | None = ...,  # type: ignore[assignment]
        categories: list[str] | None = ...,  # type: ignore[assignment]
    ) -> None:
        """Update a VTODO with all RFC 5545 fields."""
        await self.coordinator.manager.async_update_todo(
            self._calendar_name,
            uid,
            summary=summary,
            due=due,
            dtstart=dtstart,
            description=description,
            status=status,
            priority=priority,
            percent_complete=percent_complete,
            location=location,
            url=url,
            categories=categories,
        )
        await self._refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete todo items by UID."""
        for uid in uids:
            await self.coordinator.manager.async_delete_todo(self._calendar_name, uid)
        await self._refresh()
