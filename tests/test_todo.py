"""Tests for the FamilyBoard CalDAV todo entity."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.todo import TodoItem, TodoItemStatus
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.familyboard_caldav.caldav_client import VTodoItem
from custom_components.familyboard_caldav.const import EVENT_RECURRING_COMPLETED
from custom_components.familyboard_caldav.todo import FamilyBoardCalDAVTodo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(name: str = "Nextcloud") -> MagicMock:
    """Return a mock CalDAVClientManager."""
    mgr = MagicMock()
    mgr.name = name
    mgr.calendars = {"Tasks": MagicMock()}
    return mgr


def _make_coordinator(
    manager: MagicMock | None = None,
    items: dict[str, list[VTodoItem]] | None = None,
) -> MagicMock:
    """Return a mock CalDAVCoordinator."""
    mgr = manager or _make_manager()
    coord = MagicMock()
    coord.manager = mgr
    coord.config_entry = MagicMock()
    coord.config_entry.entry_id = "test_entry"
    coord._data = items or {}
    coord.async_request_refresh = AsyncMock()
    coord.get_todos = lambda cal_name: coord._data.get(cal_name, [])
    return coord


def _make_vtodo(**overrides: object) -> VTodoItem:
    """Return a VTodoItem with sensible defaults, overridable."""
    defaults: dict = {
        "uid": "test-001",
        "summary": "Test task",
        "status": "NEEDS-ACTION",
        "due": datetime.datetime(2026, 5, 20, 12, 0, tzinfo=datetime.UTC),
        "dtstart": None,
        "completed": None,
        "description": None,
        "rrule": None,
        "calendar_name": "Tasks",
        "calendar_url": "https://dav.local/cal/tasks/1.ics",
        "priority": None,
        "percent_complete": None,
        "location": None,
        "url": None,
        "categories": [],
    }
    defaults.update(overrides)
    return VTodoItem(**defaults)


def _entity(
    coordinator: MagicMock | None = None,
    manager: MagicMock | None = None,
    calendar_name: str = "Tasks",
) -> FamilyBoardCalDAVTodo:
    """Create a FamilyBoardCalDAVTodo for testing."""
    if coordinator is None:
        coordinator = _make_coordinator(manager=manager)
    return FamilyBoardCalDAVTodo(coordinator, calendar_name)


# ---------------------------------------------------------------------------
# Entity identity
# ---------------------------------------------------------------------------


class TestEntitySetup:
    """Tests for entity attributes and identity."""

    def test_unique_id(self) -> None:
        """Unique ID follows the naming convention."""
        ent = _entity(calendar_name="My Tasks")
        assert ent.unique_id == "familyboard_caldav_nextcloud_my_tasks"

    def test_unique_id_spaces(self) -> None:
        """Spaces in names are replaced with underscores."""
        mgr = _make_manager("Home Server")
        ent = _entity(manager=mgr, calendar_name="Work Tasks")
        assert ent.unique_id == "familyboard_caldav_home_server_work_tasks"

    def test_name(self) -> None:
        """Entity name is the calendar name."""
        ent = _entity(calendar_name="Shopping")
        assert ent.name == "Shopping"

    def test_supported_features(self) -> None:
        """Entity supports all expected features."""
        from homeassistant.components.todo import TodoListEntityFeature

        ent = _entity()
        features = ent.supported_features
        assert features & TodoListEntityFeature.CREATE_TODO_ITEM
        assert features & TodoListEntityFeature.UPDATE_TODO_ITEM
        assert features & TodoListEntityFeature.DELETE_TODO_ITEM
        assert features & TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        assert features & TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
        assert features & TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM


# ---------------------------------------------------------------------------
# _to_ha_item conversion
# ---------------------------------------------------------------------------


class TestToHaItem:
    """Tests for the VTodoItem → HA TodoItem conversion."""

    def test_basic_conversion(self) -> None:
        """Simple VTodoItem converts to TodoItem."""
        vtodo = _make_vtodo(summary="Buy milk", description="2%")
        ha_item = FamilyBoardCalDAVTodo._to_ha_item(vtodo)

        assert ha_item.uid == "test-001"
        assert ha_item.summary == "Buy milk"
        assert ha_item.status == TodoItemStatus.NEEDS_ACTION
        assert ha_item.description == "2%"

    def test_completed_status(self) -> None:
        """COMPLETED maps to TodoItemStatus.COMPLETED."""
        vtodo = _make_vtodo(status="COMPLETED")
        ha_item = FamilyBoardCalDAVTodo._to_ha_item(vtodo)
        assert ha_item.status == TodoItemStatus.COMPLETED

    def test_in_process_maps_to_needs_action(self) -> None:
        """IN-PROCESS maps to NEEDS_ACTION (HA only has 2 states)."""
        vtodo = _make_vtodo(status="IN-PROCESS")
        ha_item = FamilyBoardCalDAVTodo._to_ha_item(vtodo)
        assert ha_item.status == TodoItemStatus.NEEDS_ACTION

    def test_cancelled_maps_to_needs_action(self) -> None:
        """CANCELLED maps to NEEDS_ACTION."""
        vtodo = _make_vtodo(status="CANCELLED")
        ha_item = FamilyBoardCalDAVTodo._to_ha_item(vtodo)
        assert ha_item.status == TodoItemStatus.NEEDS_ACTION

    def test_midnight_datetime_converts_to_date(self) -> None:
        """DUE at midnight converts to date for HA TodoItem."""
        vtodo = _make_vtodo(
            due=datetime.datetime(2026, 6, 1, 0, 0, 0, tzinfo=datetime.UTC)
        )
        ha_item = FamilyBoardCalDAVTodo._to_ha_item(vtodo)
        assert ha_item.due == datetime.date(2026, 6, 1)
        assert isinstance(ha_item.due, datetime.date)
        assert not isinstance(ha_item.due, datetime.datetime)

    def test_non_midnight_stays_datetime(self) -> None:
        """DUE at a non-midnight time stays as datetime."""
        vtodo = _make_vtodo(
            due=datetime.datetime(2026, 6, 1, 14, 30, tzinfo=datetime.UTC)
        )
        ha_item = FamilyBoardCalDAVTodo._to_ha_item(vtodo)
        assert isinstance(ha_item.due, datetime.datetime)
        assert ha_item.due.hour == 14

    def test_date_only_due(self) -> None:
        """DUE as date stays as date."""
        vtodo = _make_vtodo(due=datetime.date(2026, 6, 1))
        ha_item = FamilyBoardCalDAVTodo._to_ha_item(vtodo)
        assert ha_item.due == datetime.date(2026, 6, 1)

    def test_no_due(self) -> None:
        """No DUE results in None."""
        vtodo = _make_vtodo(due=None)
        ha_item = FamilyBoardCalDAVTodo._to_ha_item(vtodo)
        assert ha_item.due is None

    def test_no_description(self) -> None:
        """None description maps to None."""
        vtodo = _make_vtodo(description=None)
        ha_item = FamilyBoardCalDAVTodo._to_ha_item(vtodo)
        assert ha_item.description is None


# ---------------------------------------------------------------------------
# extra_state_attributes
# ---------------------------------------------------------------------------


class TestExtraStateAttributes:
    """Tests for the extra_state_attributes property."""

    def test_empty_items(self) -> None:
        """No items → empty list."""
        ent = _entity()
        assert ent.extra_state_attributes == {"vtodo_items": []}

    def test_minimal_item(self) -> None:
        """A minimal item has uid, summary, status."""
        ent = _entity()
        ent.coordinator._data["Tasks"] = [_make_vtodo(due=None)]
        attrs = ent.extra_state_attributes

        items = attrs["vtodo_items"]
        assert len(items) == 1
        data = items[0]
        assert data["uid"] == "test-001"
        assert data["summary"] == "Test task"
        assert data["status"] == "NEEDS-ACTION"
        assert "due" not in data
        assert "dtstart" not in data
        assert "completed" not in data

    def test_full_item(self) -> None:
        """All fields are exposed when set."""
        ent = _entity()
        ent.coordinator._data["Tasks"] = [
            _make_vtodo(
                due=datetime.datetime(2026, 5, 20, 12, 0, tzinfo=datetime.UTC),
                dtstart=datetime.datetime(2026, 5, 14, 9, 0, tzinfo=datetime.UTC),
                completed=datetime.datetime(2026, 5, 21, 10, 0, tzinfo=datetime.UTC),
                description="Notes here",
                rrule="FREQ=DAILY",
                priority=2,
                percent_complete=60,
                location="Office",
                url="https://example.com",
                categories=["work", "urgent"],
            )
        ]
        data = ent.extra_state_attributes["vtodo_items"][0]

        assert data["due"] == "2026-05-20T12:00:00+00:00"
        assert data["dtstart"] == "2026-05-14T09:00:00+00:00"
        assert data["completed"] == "2026-05-21T10:00:00+00:00"
        assert data["description"] == "Notes here"
        assert data["rrule"] == "FREQ=DAILY"
        assert data["priority"] == 2
        assert data["percent_complete"] == 60
        assert data["location"] == "Office"
        assert data["url"] == "https://example.com"
        assert data["categories"] == ["work", "urgent"]

    def test_multiple_items(self) -> None:
        """Multiple items are all included."""
        ent = _entity()
        ent.coordinator._data["Tasks"] = [
            _make_vtodo(uid="a", summary="First", due=None),
            _make_vtodo(uid="b", summary="Second", due=None),
            _make_vtodo(uid="c", summary="Third", due=None),
        ]
        items = ent.extra_state_attributes["vtodo_items"]
        assert len(items) == 3
        assert [i["uid"] for i in items] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# todo_items property
# ---------------------------------------------------------------------------


class TestTodoItems:
    """Tests for the todo_items property."""

    def test_empty(self) -> None:
        """No internal items → empty list."""
        ent = _entity()
        assert ent.todo_items == []

    def test_converts_all_items(self) -> None:
        """All VTodoItems are converted to HA TodoItems."""
        ent = _entity()
        ent.coordinator._data["Tasks"] = [
            _make_vtodo(uid="a", summary="One"),
            _make_vtodo(uid="b", summary="Two", status="COMPLETED"),
        ]
        items = ent.todo_items
        assert len(items) == 2
        assert items[0].summary == "One"
        assert items[0].status == TodoItemStatus.NEEDS_ACTION
        assert items[1].summary == "Two"
        assert items[1].status == TodoItemStatus.COMPLETED


# ---------------------------------------------------------------------------
# async_create_todo_item
# ---------------------------------------------------------------------------


class TestCreateTodoItem:
    """Tests for async_create_todo_item (HA API)."""

    @pytest.mark.asyncio
    async def test_create_basic(self) -> None:
        """Create a basic todo item through HA API."""
        mgr = _make_manager()
        mgr.async_add_todo = AsyncMock(return_value=_make_vtodo())
        coord = _make_coordinator(manager=mgr)

        ent = _entity(coordinator=coord)

        item = TodoItem(
            summary="New task",
            due=datetime.date(2026, 6, 1),
            description="Notes",
        )
        await ent.async_create_todo_item(item)

        mgr.async_add_todo.assert_called_once_with(
            "Tasks", "New task", due=datetime.date(2026, 6, 1), description="Notes"
        )
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_empty_summary(self) -> None:
        """Create with None summary uses empty string."""
        mgr = _make_manager()
        mgr.async_add_todo = AsyncMock(return_value=_make_vtodo())
        coord = _make_coordinator(manager=mgr)

        ent = _entity(coordinator=coord)

        item = TodoItem(summary=None)
        await ent.async_create_todo_item(item)

        mgr.async_add_todo.assert_called_once()
        call_args = mgr.async_add_todo.call_args
        assert call_args[0][1] == ""


# ---------------------------------------------------------------------------
# async_create_vtodo
# ---------------------------------------------------------------------------


class TestCreateVTodo:
    """Tests for async_create_vtodo (full RFC API)."""

    @pytest.mark.asyncio
    async def test_create_with_all_fields(self) -> None:
        """Create a VTODO with all RFC 5545 fields."""
        mgr = _make_manager()
        mgr.async_add_todo = AsyncMock(return_value=_make_vtodo())
        coord = _make_coordinator(manager=mgr)

        ent = _entity(coordinator=coord)

        await ent.async_create_vtodo(
            "Full task",
            due=datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.UTC),
            dtstart=datetime.datetime(2026, 5, 28, 9, 0, tzinfo=datetime.UTC),
            description="Detailed",
            priority=3,
            percent_complete=25,
            location="Home",
            url="https://example.com",
            categories=["work"],
        )

        mgr.async_add_todo.assert_called_once_with(
            "Tasks",
            "Full task",
            due=datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.UTC),
            dtstart=datetime.datetime(2026, 5, 28, 9, 0, tzinfo=datetime.UTC),
            description="Detailed",
            priority=3,
            percent_complete=25,
            location="Home",
            url="https://example.com",
            categories=["work"],
        )
        coord.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# async_update_todo_item
# ---------------------------------------------------------------------------


class TestUpdateTodoItem:
    """Tests for async_update_todo_item (HA API)."""

    @pytest.mark.asyncio
    async def test_update_summary(self) -> None:
        """Update just the summary."""
        mgr = _make_manager()
        mgr.async_update_todo = AsyncMock(return_value=_make_vtodo())
        coord = _make_coordinator(manager=mgr, items={"Tasks": [_make_vtodo()]})

        ent = _entity(coordinator=coord)

        item = TodoItem(uid="test-001", summary="Renamed")
        await ent.async_update_todo_item(item)

        mgr.async_update_todo.assert_called_once()
        kwargs = mgr.async_update_todo.call_args[1]
        assert kwargs["summary"] == "Renamed"

    @pytest.mark.asyncio
    async def test_update_none_uid_noop(self) -> None:
        """Update with None UID does nothing."""
        mgr = _make_manager()
        mgr.async_update_todo = AsyncMock()
        coord = _make_coordinator(manager=mgr)

        ent = _entity(coordinator=coord)

        item = TodoItem(uid=None, summary="Orphan")
        await ent.async_update_todo_item(item)

        mgr.async_update_todo.assert_not_called()
        coord.async_request_refresh.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("recurring", [False, True])
    async def test_completion_event_only_for_advanced_recurrence(
        self, hass: HomeAssistant, recurring: bool
    ) -> None:
        """Only a successfully advanced recurrence emits a completion event."""
        mgr = _make_manager()
        mgr.async_complete_todo = AsyncMock(
            return_value=_make_vtodo(
                status="NEEDS-ACTION" if recurring else "COMPLETED",
                rrule="FREQ=DAILY" if recurring else None,
            )
        )
        coord = _make_coordinator(manager=mgr)
        ent = _entity(coordinator=coord)
        ent.hass = hass
        ent.entity_id = "todo.tasks"
        events = []
        unsubscribe = hass.bus.async_listen(EVENT_RECURRING_COMPLETED, events.append)

        await ent.async_update_todo_item(
            TodoItem(uid="test-001", status=TodoItemStatus.COMPLETED)
        )
        await hass.async_block_till_done()
        unsubscribe()

        assert len(events) == int(recurring)
        if recurring:
            assert events[0].data == {"entity_id": "todo.tasks", "uid": "test-001"}
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_nonrecurring_delegates(self) -> None:
        """Completing a non-recurring task calls async_complete_todo."""
        mgr = _make_manager()
        mgr.async_complete_todo = AsyncMock(
            return_value=_make_vtodo(status="COMPLETED")
        )
        coord = _make_coordinator(
            manager=mgr,
            items={"Tasks": [_make_vtodo(status="NEEDS-ACTION")]},
        )

        ent = _entity(coordinator=coord)

        item = TodoItem(uid="test-001", status=TodoItemStatus.COMPLETED)
        await ent.async_update_todo_item(item)

        mgr.async_complete_todo.assert_called_once_with("Tasks", "test-001")
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_already_completed_checks_server(self) -> None:
        """Cached status must not bypass the server-backed completion path."""
        mgr = _make_manager()
        mgr.async_complete_todo = AsyncMock()
        mgr.async_update_todo = AsyncMock(return_value=_make_vtodo())
        coord = _make_coordinator(
            manager=mgr,
            items={"Tasks": [_make_vtodo(status="COMPLETED")]},
        )

        ent = _entity(coordinator=coord)

        item = TodoItem(uid="test-001", status=TodoItemStatus.COMPLETED)
        await ent.async_update_todo_item(item)

        mgr.async_complete_todo.assert_awaited_once_with("Tasks", "test-001")
        mgr.async_update_todo.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_unknown_uid_checks_server(self) -> None:
        """A cache miss still uses recurrence-aware completion."""
        mgr = _make_manager()
        mgr.async_complete_todo = AsyncMock()
        mgr.async_update_todo = AsyncMock(return_value=_make_vtodo())
        coord = _make_coordinator(manager=mgr, items={"Tasks": []})

        ent = _entity(coordinator=coord)

        item = TodoItem(uid="unknown-uid", status=TodoItemStatus.COMPLETED)
        await ent.async_update_todo_item(item)

        mgr.async_complete_todo.assert_awaited_once_with("Tasks", "unknown-uid")
        mgr.async_update_todo.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("missing", [False, True])
    async def test_completion_failure_is_reported(self, missing: bool) -> None:
        """Missing tasks and invalid recurrence fail without a generic update."""
        mgr = _make_manager()
        mgr.async_complete_todo = AsyncMock(
            return_value=None,
            side_effect=None if missing else ValueError("Invalid recurrence"),
        )
        coord = _make_coordinator(manager=mgr)
        ent = _entity(coordinator=coord)

        with pytest.raises(HomeAssistantError):
            await ent.async_update_todo_item(
                TodoItem(uid="test-001", status=TodoItemStatus.COMPLETED)
            )

        mgr.async_update_todo.assert_not_called()
        coord.async_request_refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reopen_completed(self) -> None:
        """Changing status from COMPLETED to NEEDS-ACTION."""
        mgr = _make_manager()
        mgr.async_update_todo = AsyncMock(return_value=_make_vtodo())
        coord = _make_coordinator(
            manager=mgr,
            items={"Tasks": [_make_vtodo(status="COMPLETED")]},
        )

        ent = _entity(coordinator=coord)

        item = TodoItem(uid="test-001", status=TodoItemStatus.NEEDS_ACTION)
        await ent.async_update_todo_item(item)

        mgr.async_update_todo.assert_called_once()
        kwargs = mgr.async_update_todo.call_args[1]
        assert kwargs["status"] == "NEEDS-ACTION"


# ---------------------------------------------------------------------------
# async_update_vtodo
# ---------------------------------------------------------------------------


class TestUpdateVTodo:
    """Tests for async_update_vtodo (full RFC API)."""

    @pytest.mark.asyncio
    async def test_update_all_fields(self) -> None:
        """Update all RFC 5545 fields at once."""
        mgr = _make_manager()
        mgr.async_update_todo = AsyncMock(return_value=_make_vtodo())
        coord = _make_coordinator(manager=mgr)

        ent = _entity(coordinator=coord)

        await ent.async_update_vtodo(
            "test-001",
            summary="Updated",
            due=datetime.date(2026, 7, 1),
            dtstart=datetime.date(2026, 6, 28),
            description="New notes",
            status="IN-PROCESS",
            priority=1,
            percent_complete=50,
            location="Garden",
            url="https://new.example.com",
            categories=["outdoor"],
        )

        mgr.async_update_todo.assert_called_once()
        kwargs = mgr.async_update_todo.call_args[1]
        assert kwargs["summary"] == "Updated"
        assert kwargs["priority"] == 1
        assert kwargs["percent_complete"] == 50
        assert kwargs["location"] == "Garden"
        assert kwargs["categories"] == ["outdoor"]

    @pytest.mark.asyncio
    async def test_update_single_field(self) -> None:
        """Update only one field, rest stay at sentinel."""
        mgr = _make_manager()
        mgr.async_update_todo = AsyncMock(return_value=_make_vtodo())
        coord = _make_coordinator(manager=mgr)

        ent = _entity(coordinator=coord)

        await ent.async_update_vtodo("test-001", priority=5)

        kwargs = mgr.async_update_todo.call_args[1]
        assert kwargs["priority"] == 5
        assert kwargs["summary"] is None
        # Other fields should be sentinel (...)
        assert kwargs["due"] is ...


# ---------------------------------------------------------------------------
# async_delete_todo_items
# ---------------------------------------------------------------------------


class TestDeleteTodoItems:
    """Tests for async_delete_todo_items."""

    @pytest.mark.asyncio
    async def test_delete_single(self) -> None:
        """Delete a single todo item."""
        mgr = _make_manager()
        mgr.async_delete_todo = AsyncMock(return_value=True)
        coord = _make_coordinator(manager=mgr)

        ent = _entity(coordinator=coord)

        await ent.async_delete_todo_items(["uid-1"])

        mgr.async_delete_todo.assert_called_once_with("Tasks", "uid-1")
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_multiple(self) -> None:
        """Delete multiple todo items."""
        mgr = _make_manager()
        mgr.async_delete_todo = AsyncMock(return_value=True)
        coord = _make_coordinator(manager=mgr)

        ent = _entity(coordinator=coord)

        await ent.async_delete_todo_items(["uid-1", "uid-2", "uid-3"])

        assert mgr.async_delete_todo.call_count == 3
        calls = [c.args for c in mgr.async_delete_todo.call_args_list]
        assert ("Tasks", "uid-1") in calls
        assert ("Tasks", "uid-2") in calls
        assert ("Tasks", "uid-3") in calls

    @pytest.mark.asyncio
    async def test_delete_empty_list(self) -> None:
        """Delete with empty list triggers refresh."""
        mgr = _make_manager()
        mgr.async_delete_todo = AsyncMock()
        coord = _make_coordinator(manager=mgr)

        ent = _entity(coordinator=coord)

        await ent.async_delete_todo_items([])

        mgr.async_delete_todo.assert_not_called()
        coord.async_request_refresh.assert_awaited_once()
