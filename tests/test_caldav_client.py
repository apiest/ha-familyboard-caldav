"""Tests for the CalDAV client manager."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest
from vobject import readOne

from custom_components.familyboard_caldav.caldav_client import (
    CalDAVClientManager,
    VTodoItem,
    _advance_rrule,
    _parse_vtodo,
    _split_repeat_from,
)

# ---------------------------------------------------------------------------
# VTODO ICS fixtures
# ---------------------------------------------------------------------------

VTODO_SIMPLE = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//CalDAV//EN
BEGIN:VTODO
UID:simple-001
SUMMARY:Buy groceries
STATUS:NEEDS-ACTION
DUE:20260515T180000Z
DESCRIPTION:Milk\\, eggs\\, bread
PRIORITY:1
END:VTODO
END:VCALENDAR
"""

VTODO_DAILY_RRULE = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//CalDAV//EN
BEGIN:VTODO
UID:daily-001
SUMMARY:Water plants
STATUS:NEEDS-ACTION
DTSTART:20260510T080000Z
DUE:20260510T080000Z
RRULE:FREQ=DAILY
END:VTODO
END:VCALENDAR
"""

VTODO_WEEKLY_RRULE_UNTIL = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//CalDAV//EN
BEGIN:VTODO
UID:weekly-001
SUMMARY:Weekly report
STATUS:NEEDS-ACTION
DTSTART:20260512T090000Z
DUE:20260512T090000Z
RRULE:FREQ=WEEKLY;UNTIL=20260602T090000Z
END:VTODO
END:VCALENDAR
"""

VTODO_MONTHLY_COUNT = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//CalDAV//EN
BEGIN:VTODO
UID:monthly-001
SUMMARY:Pay rent
STATUS:NEEDS-ACTION
DTSTART:20260101T120000Z
DUE:20260101T120000Z
RRULE:FREQ=MONTHLY;COUNT=3
END:VTODO
END:VCALENDAR
"""

VTODO_EXHAUSTED = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//CalDAV//EN
BEGIN:VTODO
UID:exhausted-001
SUMMARY:One-time recurring
STATUS:NEEDS-ACTION
DTSTART:20260510T080000Z
DUE:20260510T080000Z
RRULE:FREQ=DAILY;COUNT=1
END:VTODO
END:VCALENDAR
"""

VTODO_DATE_ONLY = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//CalDAV//EN
BEGIN:VTODO
UID:dateonly-001
SUMMARY:All day task
STATUS:NEEDS-ACTION
DUE;VALUE=DATE:20260515
RRULE:FREQ=WEEKLY
END:VTODO
END:VCALENDAR
"""

VTODO_NO_DUE = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//CalDAV//EN
BEGIN:VTODO
UID:nodue-001
SUMMARY:Someday task
STATUS:NEEDS-ACTION
END:VTODO
END:VCALENDAR
"""

VTODO_COMPLETED = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//CalDAV//EN
BEGIN:VTODO
UID:done-001
SUMMARY:Already done
STATUS:COMPLETED
COMPLETED:20260510T100000Z
DUE:20260510T080000Z
END:VTODO
END:VCALENDAR
"""

VTODO_FULL_RFC = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//CalDAV//EN
BEGIN:VTODO
UID:full-001
SUMMARY:Full RFC task
STATUS:IN-PROCESS
DTSTART:20260514T090000Z
DUE:20260520T170000Z
COMPLETED:20260521T120000Z
DESCRIPTION:Detailed notes for this task
PRIORITY:3
PERCENT-COMPLETE:40
LOCATION:Home office
URL:https://example.com/task/123
CATEGORIES:work,urgent
RRULE:FREQ=WEEKLY
END:VTODO
END:VCALENDAR
"""

# --- Edge-case fixtures ---

VTODO_MINIMAL = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:minimal-001
SUMMARY:Bare minimum
END:VTODO
END:VCALENDAR
"""

VTODO_PRIORITY_ZERO = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:prio0-001
SUMMARY:Undefined priority
STATUS:NEEDS-ACTION
PRIORITY:0
END:VTODO
END:VCALENDAR
"""

VTODO_PRIORITY_NINE = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:prio9-001
SUMMARY:Lowest priority
STATUS:NEEDS-ACTION
PRIORITY:9
END:VTODO
END:VCALENDAR
"""

VTODO_PERCENT_ZERO = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:pct0-001
SUMMARY:Not started
STATUS:NEEDS-ACTION
PERCENT-COMPLETE:0
END:VTODO
END:VCALENDAR
"""

VTODO_PERCENT_HUNDRED = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:pct100-001
SUMMARY:Fully done
STATUS:COMPLETED
PERCENT-COMPLETE:100
END:VTODO
END:VCALENDAR
"""

VTODO_SINGLE_CATEGORY = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:singlecat-001
SUMMARY:One category
STATUS:NEEDS-ACTION
CATEGORIES:personal
END:VTODO
END:VCALENDAR
"""

VTODO_MULTI_CATEGORIES = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:multicat-001
SUMMARY:Many categories
STATUS:NEEDS-ACTION
CATEGORIES:home,work,urgent,low-energy
END:VTODO
END:VCALENDAR
"""

VTODO_IN_PROCESS = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:inprocess-001
SUMMARY:Work in progress
STATUS:IN-PROCESS
PERCENT-COMPLETE:50
DUE:20260520T120000Z
END:VTODO
END:VCALENDAR
"""

VTODO_CANCELLED = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:cancelled-001
SUMMARY:Cancelled task
STATUS:CANCELLED
END:VTODO
END:VCALENDAR
"""

VTODO_RECURRING_NO_DUE = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:recnodue-001
SUMMARY:Recurring without DUE
STATUS:NEEDS-ACTION
DTSTART:20260510T080000Z
RRULE:FREQ=DAILY
END:VTODO
END:VCALENDAR
"""

VTODO_RECURRING_COMPLETED_TS = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:reccomp-001
SUMMARY:Completed recurring
STATUS:COMPLETED
DTSTART:20260510T080000Z
DUE:20260510T080000Z
COMPLETED:20260510T090000Z
RRULE:FREQ=DAILY
END:VTODO
END:VCALENDAR
"""

VTODO_YEARLY = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:yearly-001
SUMMARY:Annual review
STATUS:NEEDS-ACTION
DTSTART:20260101T000000Z
DUE:20260101T000000Z
RRULE:FREQ=YEARLY;COUNT=3
END:VTODO
END:VCALENDAR
"""

VTODO_BYDAY = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:byday-001
SUMMARY:Every Mon and Wed
STATUS:NEEDS-ACTION
DTSTART:20260511T100000Z
DUE:20260511T100000Z
RRULE:FREQ=WEEKLY;BYDAY=MO,WE
END:VTODO
END:VCALENDAR
"""

VTODO_INTERVAL = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:interval-001
SUMMARY:Every other week
STATUS:NEEDS-ACTION
DTSTART:20260511T100000Z
DUE:20260511T100000Z
RRULE:FREQ=WEEKLY;INTERVAL=2
END:VTODO
END:VCALENDAR
"""

VTODO_DATE_ONLY_DTSTART = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:datestart-001
SUMMARY:Date-only start
STATUS:NEEDS-ACTION
DTSTART;VALUE=DATE:20260510
DUE;VALUE=DATE:20260515
RRULE:FREQ=MONTHLY
END:VTODO
END:VCALENDAR
"""

VTODO_LONG_DESCRIPTION = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:longdesc-001
SUMMARY:Task with long description
STATUS:NEEDS-ACTION
DESCRIPTION:Line one\\nLine two\\nLine three\\, with comma
END:VTODO
END:VCALENDAR
"""

VTODO_URL_COMPLEX = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:urlcomplex-001
SUMMARY:Complex URL
STATUS:NEEDS-ACTION
URL:https://example.com/path?q=1&b=2#section
END:VTODO
END:VCALENDAR
"""

VTODO_LOCATION_UNICODE = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:unicode-001
SUMMARY:Unicode location
STATUS:NEEDS-ACTION
LOCATION:Café résumé
END:VTODO
END:VCALENDAR
"""

VTODO_EMPTY_DESCRIPTION = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VTODO
UID:emptydesc-001
SUMMARY:Empty description
STATUS:NEEDS-ACTION
DESCRIPTION:
END:VTODO
END:VCALENDAR
"""


# ---------------------------------------------------------------------------
# _parse_vtodo tests
# ---------------------------------------------------------------------------


def _make_mock_todo(ics: str) -> MagicMock:
    """Create a mock caldav.Todo from an ICS string."""
    mock = MagicMock()
    mock.vobject_instance = readOne(ics)
    mock.url = "https://nextcloud.local/dav/calendars/user/tasks/item.ics"
    return mock


class TestParseVTodo:
    """Tests for _parse_vtodo."""

    def test_simple_vtodo(self) -> None:
        """Parse a simple VTODO without RRULE."""
        todo = _make_mock_todo(VTODO_SIMPLE)
        item = _parse_vtodo(todo, "Tasks")

        assert item.uid == "simple-001"
        assert item.summary == "Buy groceries"
        assert item.status == "NEEDS-ACTION"
        assert item.due == datetime.datetime(2026, 5, 15, 18, 0, tzinfo=datetime.UTC)
        assert item.description == "Milk, eggs, bread"
        assert item.rrule is None
        assert item.is_recurring is False
        assert item.calendar_name == "Tasks"
        assert item.priority == 1
        assert item.dtstart is None
        assert item.completed is None
        assert item.percent_complete is None
        assert item.location is None
        assert item.url is None
        assert item.categories == []

    def test_recurring_vtodo(self) -> None:
        """Parse a VTODO with RRULE."""
        todo = _make_mock_todo(VTODO_DAILY_RRULE)
        item = _parse_vtodo(todo, "Tasks")

        assert item.uid == "daily-001"
        assert item.rrule is not None
        assert "FREQ=DAILY" in item.rrule
        assert item.is_recurring is True
        assert item.dtstart == datetime.datetime(2026, 5, 10, 8, 0, tzinfo=datetime.UTC)

    def test_completed_vtodo(self) -> None:
        """Parse a completed VTODO with COMPLETED timestamp."""
        todo = _make_mock_todo(VTODO_COMPLETED)
        item = _parse_vtodo(todo, "Tasks")

        assert item.uid == "done-001"
        assert item.status == "COMPLETED"
        assert item.completed == datetime.datetime(
            2026, 5, 10, 10, 0, tzinfo=datetime.UTC
        )

    def test_no_due_vtodo(self) -> None:
        """Parse a VTODO without DUE date."""
        todo = _make_mock_todo(VTODO_NO_DUE)
        item = _parse_vtodo(todo, "Tasks")

        assert item.uid == "nodue-001"
        assert item.due is None
        assert item.dtstart is None

    def test_full_rfc_vtodo(self) -> None:
        """Parse a VTODO with all RFC 5545 fields."""
        todo = _make_mock_todo(VTODO_FULL_RFC)
        item = _parse_vtodo(todo, "Tasks")

        assert item.uid == "full-001"
        assert item.summary == "Full RFC task"
        assert item.status == "IN-PROCESS"
        assert item.dtstart == datetime.datetime(2026, 5, 14, 9, 0, tzinfo=datetime.UTC)
        assert item.due == datetime.datetime(2026, 5, 20, 17, 0, tzinfo=datetime.UTC)
        assert item.completed == datetime.datetime(
            2026, 5, 21, 12, 0, tzinfo=datetime.UTC
        )
        assert item.description == "Detailed notes for this task"
        assert item.priority == 3
        assert item.percent_complete == 40
        assert item.location == "Home office"
        assert item.url == "https://example.com/task/123"
        assert "work" in item.categories
        assert "urgent" in item.categories
        assert item.rrule is not None
        assert "FREQ=WEEKLY" in item.rrule
        assert item.is_recurring is True

    def test_minimal_vtodo(self) -> None:
        """Parse a VTODO with only UID and SUMMARY."""
        todo = _make_mock_todo(VTODO_MINIMAL)
        item = _parse_vtodo(todo, "Inbox")

        assert item.uid == "minimal-001"
        assert item.summary == "Bare minimum"
        assert item.status == "NEEDS-ACTION"  # default
        assert item.due is None
        assert item.dtstart is None
        assert item.description is None
        assert item.rrule is None
        assert item.priority is None
        assert item.percent_complete is None
        assert item.location is None
        assert item.url is None
        assert item.categories == []
        assert item.calendar_name == "Inbox"

    def test_priority_zero(self) -> None:
        """RFC 5545: PRIORITY 0 = undefined."""
        todo = _make_mock_todo(VTODO_PRIORITY_ZERO)
        item = _parse_vtodo(todo)
        assert item.priority == 0

    def test_priority_nine(self) -> None:
        """RFC 5545: PRIORITY 9 = lowest."""
        todo = _make_mock_todo(VTODO_PRIORITY_NINE)
        item = _parse_vtodo(todo)
        assert item.priority == 9

    def test_percent_complete_zero(self) -> None:
        """PERCENT-COMPLETE 0 is a valid value (not started)."""
        todo = _make_mock_todo(VTODO_PERCENT_ZERO)
        item = _parse_vtodo(todo)
        assert item.percent_complete == 0

    def test_percent_complete_hundred(self) -> None:
        """PERCENT-COMPLETE 100 means fully done."""
        todo = _make_mock_todo(VTODO_PERCENT_HUNDRED)
        item = _parse_vtodo(todo)
        assert item.percent_complete == 100
        assert item.status == "COMPLETED"

    def test_single_category(self) -> None:
        """A VTODO with one CATEGORIES value."""
        todo = _make_mock_todo(VTODO_SINGLE_CATEGORY)
        item = _parse_vtodo(todo)
        assert item.categories == ["personal"]

    def test_multiple_categories(self) -> None:
        """A VTODO with comma-separated CATEGORIES."""
        todo = _make_mock_todo(VTODO_MULTI_CATEGORIES)
        item = _parse_vtodo(todo)
        assert len(item.categories) == 4
        assert "home" in item.categories
        assert "work" in item.categories
        assert "urgent" in item.categories
        assert "low-energy" in item.categories

    def test_in_process_status(self) -> None:
        """RFC 5545: STATUS IN-PROCESS."""
        todo = _make_mock_todo(VTODO_IN_PROCESS)
        item = _parse_vtodo(todo)
        assert item.status == "IN-PROCESS"
        assert item.percent_complete == 50

    def test_cancelled_status(self) -> None:
        """RFC 5545: STATUS CANCELLED."""
        todo = _make_mock_todo(VTODO_CANCELLED)
        item = _parse_vtodo(todo)
        assert item.status == "CANCELLED"

    def test_url_with_query_params(self) -> None:
        """Parse a URL with query parameters and fragment."""
        todo = _make_mock_todo(VTODO_URL_COMPLEX)
        item = _parse_vtodo(todo)
        assert item.url == "https://example.com/path?q=1&b=2#section"

    def test_unicode_location(self) -> None:
        """Parse a location with non-ASCII characters."""
        todo = _make_mock_todo(VTODO_LOCATION_UNICODE)
        item = _parse_vtodo(todo)
        assert item.location == "Café résumé"

    def test_description_with_newlines(self) -> None:
        """Escaped newlines in DESCRIPTION are preserved."""
        todo = _make_mock_todo(VTODO_LONG_DESCRIPTION)
        item = _parse_vtodo(todo)
        assert "Line one" in item.description
        assert "Line two" in item.description
        assert "with comma" in item.description

    def test_calendar_url_from_mock(self) -> None:
        """calendar_url is populated from the caldav.Todo.url."""
        todo = _make_mock_todo(VTODO_SIMPLE)
        item = _parse_vtodo(todo, "Tasks")
        assert item.calendar_url == (
            "https://nextcloud.local/dav/calendars/user/tasks/item.ics"
        )

    def test_calendar_url_none(self) -> None:
        """calendar_url is empty when the mock has no url."""
        mock = MagicMock()
        mock.vobject_instance = readOne(VTODO_SIMPLE)
        mock.url = None
        item = _parse_vtodo(mock, "Tasks")
        assert item.calendar_url == ""

    def test_date_only_due(self) -> None:
        """DUE with VALUE=DATE is parsed as datetime.date."""
        todo = _make_mock_todo(VTODO_DATE_ONLY)
        item = _parse_vtodo(todo)
        assert isinstance(item.due, datetime.date)
        assert not isinstance(item.due, datetime.datetime)
        assert item.due == datetime.date(2026, 5, 15)

    def test_date_only_dtstart(self) -> None:
        """DTSTART with VALUE=DATE is parsed as datetime.date."""
        todo = _make_mock_todo(VTODO_DATE_ONLY_DTSTART)
        item = _parse_vtodo(todo)
        assert isinstance(item.dtstart, datetime.date)
        assert not isinstance(item.dtstart, datetime.datetime)

    def test_is_recurring_property(self) -> None:
        """VTodoItem.is_recurring reflects rrule presence."""
        item_recurring = VTodoItem(
            uid="r1", summary="R", status="NEEDS-ACTION", rrule="FREQ=DAILY"
        )
        item_once = VTodoItem(uid="r2", summary="O", status="NEEDS-ACTION")

        assert item_recurring.is_recurring is True
        assert item_once.is_recurring is False


# ---------------------------------------------------------------------------
# _advance_rrule tests
# ---------------------------------------------------------------------------


class TestAdvanceRRule:
    """Tests for the RRULE advancement logic."""

    def test_advance_daily(self) -> None:
        """Daily RRULE advances DUE by one day."""
        vobj = readOne(VTODO_DAILY_RRULE)
        result = _advance_rrule(vobj)

        assert result is True
        new_due = vobj.vtodo.due.value
        assert new_due == datetime.datetime(2026, 5, 11, 8, 0, tzinfo=datetime.UTC)
        assert vobj.vtodo.status.value == "NEEDS-ACTION"

    def test_advance_weekly_until(self) -> None:
        """Weekly RRULE with UNTIL advances correctly."""
        vobj = readOne(VTODO_WEEKLY_RRULE_UNTIL)
        result = _advance_rrule(vobj)

        assert result is True
        new_due = vobj.vtodo.due.value
        assert new_due == datetime.datetime(2026, 5, 19, 9, 0, tzinfo=datetime.UTC)

    def test_advance_weekly_until_exhausted(self) -> None:
        """Weekly RRULE with UNTIL becomes exhausted at the boundary."""
        vobj = readOne(VTODO_WEEKLY_RRULE_UNTIL)

        count = 0
        while _advance_rrule(vobj):
            count += 1
            if count > 10:
                break

        # UNTIL is Jun 2 — should get: May 19, May 26, Jun 2 = 3 advancements
        assert count == 3

    def test_advance_monthly_count(self) -> None:
        """Monthly RRULE with COUNT=3 produces exactly 2 advancements."""
        vobj = readOne(VTODO_MONTHLY_COUNT)

        assert _advance_rrule(vobj) is True
        assert vobj.vtodo.due.value == datetime.datetime(
            2026, 2, 1, 12, 0, tzinfo=datetime.UTC
        )

        assert _advance_rrule(vobj) is True
        assert vobj.vtodo.due.value == datetime.datetime(
            2026, 3, 1, 12, 0, tzinfo=datetime.UTC
        )

        assert _advance_rrule(vobj) is False  # exhausted

    def test_advance_exhausted_count_1(self) -> None:
        """RRULE with COUNT=1 is immediately exhausted."""
        vobj = readOne(VTODO_EXHAUSTED)
        result = _advance_rrule(vobj)

        assert result is False

    def test_advance_no_rrule(self) -> None:
        """Non-recurring VTODO returns False."""
        vobj = readOne(VTODO_SIMPLE)
        result = _advance_rrule(vobj)

        assert result is False

    def test_advance_resets_status(self) -> None:
        """Advancing resets STATUS to NEEDS-ACTION."""
        vobj = readOne(VTODO_DAILY_RRULE)
        vobj.vtodo.status.value = "COMPLETED"

        result = _advance_rrule(vobj)

        assert result is True
        assert vobj.vtodo.status.value == "NEEDS-ACTION"

    def test_advance_date_only(self) -> None:
        """Date-only DUE is preserved as date after advancement."""
        vobj = readOne(VTODO_DATE_ONLY)
        result = _advance_rrule(vobj)

        assert result is True
        new_due = vobj.vtodo.due.value
        assert isinstance(new_due, datetime.date)
        # Should be May 22 (one week later)
        assert new_due == datetime.date(2026, 5, 22)

    def test_advance_preserves_dtstart(self) -> None:
        """DTSTART is NOT updated — it stays as the RRULE anchor."""
        vobj = readOne(VTODO_DAILY_RRULE)
        original_dtstart = vobj.vtodo.dtstart.value
        result = _advance_rrule(vobj)

        assert result is True
        assert vobj.vtodo.dtstart.value == original_dtstart

    def test_advance_removes_completed_timestamp(self) -> None:
        """Advancing a recurring task removes the COMPLETED timestamp."""
        vobj = readOne(VTODO_RECURRING_COMPLETED_TS)
        assert hasattr(vobj.vtodo, "completed")

        result = _advance_rrule(vobj)

        assert result is True
        assert not hasattr(vobj.vtodo, "completed")

    def test_advance_yearly(self) -> None:
        """YEARLY RRULE with COUNT=3 advances correctly."""
        vobj = readOne(VTODO_YEARLY)

        assert _advance_rrule(vobj) is True
        assert vobj.vtodo.due.value == datetime.datetime(
            2027, 1, 1, 0, 0, tzinfo=datetime.UTC
        )

        assert _advance_rrule(vobj) is True
        assert vobj.vtodo.due.value == datetime.datetime(
            2028, 1, 1, 0, 0, tzinfo=datetime.UTC
        )

        assert _advance_rrule(vobj) is False

    def test_advance_byday(self) -> None:
        """WEEKLY RRULE with BYDAY=MO,WE advances to next matching day."""
        vobj = readOne(VTODO_BYDAY)
        # DTSTART is 2026-05-11 (Monday), DUE is May 11
        assert _advance_rrule(vobj) is True
        new_due = vobj.vtodo.due.value
        # Next occurrence after Mon May 11 should be Wed May 13
        assert new_due == datetime.datetime(2026, 5, 13, 10, 0, tzinfo=datetime.UTC)

        assert _advance_rrule(vobj) is True
        new_due = vobj.vtodo.due.value
        # After Wed May 13 → Mon May 18
        assert new_due == datetime.datetime(2026, 5, 18, 10, 0, tzinfo=datetime.UTC)

    def test_advance_interval(self) -> None:
        """WEEKLY RRULE with INTERVAL=2 skips one week."""
        vobj = readOne(VTODO_INTERVAL)
        assert _advance_rrule(vobj) is True
        new_due = vobj.vtodo.due.value
        # May 11 + 2 weeks = May 25
        assert new_due == datetime.datetime(2026, 5, 25, 10, 0, tzinfo=datetime.UTC)

    def test_advance_recurring_no_due_uses_dtstart(self) -> None:
        """Recurring VTODO without DUE falls back to DTSTART for advancement."""
        vobj = readOne(VTODO_RECURRING_NO_DUE)
        result = _advance_rrule(vobj)

        assert result is True
        # DUE should now be added with the next occurrence
        new_due = vobj.vtodo.due.value
        assert new_due == datetime.datetime(2026, 5, 11, 8, 0, tzinfo=datetime.UTC)

    def test_advance_date_only_dtstart_and_due(self) -> None:
        """Both DTSTART and DUE as DATE values — DUE advances as date."""
        vobj = readOne(VTODO_DATE_ONLY_DTSTART)
        result = _advance_rrule(vobj)

        assert result is True
        new_due = vobj.vtodo.due.value
        assert isinstance(new_due, datetime.date)
        # DTSTART anchors the RRULE at May 10, DUE is May 15.
        # Monthly recurrence from DTSTART → next after May 15 is Jun 10.
        assert new_due == datetime.date(2026, 6, 10)

    def test_advance_multiple_rapid_completions(self) -> None:
        """Simulates completing a daily task multiple times in sequence."""
        vobj = readOne(VTODO_DAILY_RRULE)

        for _i in range(1, 31):  # 30 days
            assert _advance_rrule(vobj) is True

        # Started at May 10, advanced 30 times → Jun 9
        expected = datetime.datetime(2026, 6, 9, 8, 0, tzinfo=datetime.UTC)
        assert vobj.vtodo.due.value == expected


# ---------------------------------------------------------------------------
# Tasks.org FROM=COMPLETION recurrence
# ---------------------------------------------------------------------------


def _from_completion_vtodo(
    rrule: str,
    due: str = "DUE;VALUE=DATE:20260810",
    dtstart: str = "DTSTART;VALUE=DATE:20260808",
    categories: str | None = None,
) -> str:
    """Build a Tasks.org-style VTODO with the given RRULE."""
    cats = f"CATEGORIES:{categories}\r\n" if categories else ""
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//tasks.org//android-140102//EN\r\n"
        "BEGIN:VTODO\r\n"
        "UID:from-completion-1\r\n"
        "SUMMARY:Water the plants\r\n"
        f"{dtstart}\r\n"
        f"{due}\r\n"
        f"RRULE:{rrule}\r\n"
        f"{cats}"
        "STATUS:NEEDS-ACTION\r\n"
        "END:VTODO\r\n"
        "END:VCALENDAR\r\n"
    )


# A Thursday, well after the original DUE date of 2026-08-10.
COMPLETED_AT = datetime.datetime(2026, 8, 20, 19, 30, tzinfo=datetime.UTC)


class TestSplitRepeatFrom:
    """Tests for splitting the non-standard FROM= part out of an RRULE."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("FREQ=DAILY;INTERVAL=2;FROM=COMPLETION", ("FREQ=DAILY;INTERVAL=2", True)),
            ("FROM=COMPLETION;FREQ=DAILY", ("FREQ=DAILY", True)),
            ("FREQ=DAILY;FROM=DUE", ("FREQ=DAILY", False)),
            ("FREQ=WEEKLY;BYDAY=MO", ("FREQ=WEEKLY;BYDAY=MO", False)),
            ("FREQ=DAILY;from=completion", ("FREQ=DAILY", True)),
        ],
    )
    def test_split(self, raw: str, expected: tuple[str, bool]) -> None:
        """The FROM= part is stripped and reported."""
        assert _split_repeat_from(raw) == expected

    def test_vtodo_item_property(self) -> None:
        """VTodoItem surfaces the repeat-from-completion flag."""
        from_completion = VTodoItem(
            uid="a",
            summary="A",
            status="NEEDS-ACTION",
            rrule="FREQ=DAILY;FROM=COMPLETION",
        )
        tagged = VTodoItem(
            uid="d",
            summary="D",
            status="NEEDS-ACTION",
            rrule="FREQ=DAILY",
            categories=["chores", "From-Completion"],
        )
        from_due = VTodoItem(
            uid="b", summary="B", status="NEEDS-ACTION", rrule="FREQ=DAILY"
        )
        once = VTodoItem(uid="c", summary="C", status="NEEDS-ACTION")

        assert from_completion.repeats_from_completion() is True
        assert tagged.repeats_from_completion() is True
        assert from_due.repeats_from_completion() is False
        assert once.repeats_from_completion() is False

    def test_explicit_from_due_beats_tag(self) -> None:
        """An explicit FROM= part in the RRULE wins over the category tag."""
        item = VTodoItem(
            uid="e",
            summary="E",
            status="NEEDS-ACTION",
            rrule="FREQ=DAILY;FROM=DUE",
            categories=["from-completion"],
        )

        assert item.repeats_from_completion() is False

    def test_custom_tag_name(self) -> None:
        """The tag name is configurable."""
        item = VTodoItem(
            uid="f",
            summary="F",
            status="NEEDS-ACTION",
            rrule="FREQ=DAILY",
            categories=["na-afvinken"],
        )

        assert item.repeats_from_completion("na-afvinken") is True
        assert item.repeats_from_completion() is False


class TestAdvanceFromCompletion:
    """Tasks.org FROM=COMPLETION recurrence is advanced client-side."""

    def test_two_days_after_completion(self) -> None:
        """A task repeating 2 days after completion lands 2 days after the tick."""
        vobj = readOne(_from_completion_vtodo("FREQ=DAILY;INTERVAL=2;FROM=COMPLETION"))

        assert _advance_rrule(vobj, COMPLETED_AT) is True
        # Completed Aug 20 → next due Aug 22, *not* Aug 12 (due + 2 days).
        assert vobj.vtodo.due.value == datetime.date(2026, 8, 22)
        assert vobj.vtodo.status.value == "NEEDS-ACTION"

    def test_from_due_ignores_completion_date(self) -> None:
        """Without FROM=COMPLETION the previous DUE stays the anchor."""
        vobj = readOne(_from_completion_vtodo("FREQ=DAILY;INTERVAL=2"))

        assert _advance_rrule(vobj, COMPLETED_AT) is True
        assert vobj.vtodo.due.value == datetime.date(2026, 8, 12)

    def test_explicit_from_due_does_not_raise(self) -> None:
        """FROM=DUE is stripped too — dateutil cannot parse it."""
        vobj = readOne(_from_completion_vtodo("FREQ=DAILY;INTERVAL=2;FROM=DUE"))

        assert _advance_rrule(vobj, COMPLETED_AT) is True
        assert vobj.vtodo.due.value == datetime.date(2026, 8, 12)

    def test_preserves_due_time_of_day(self) -> None:
        """The original DUE time-of-day survives, as in Tasks.org."""
        vobj = readOne(
            _from_completion_vtodo(
                "FREQ=DAILY;INTERVAL=2;FROM=COMPLETION",
                due="DUE:20260810T090000Z",
                dtstart="DTSTART:20260810T080000Z",
            )
        )

        assert _advance_rrule(vobj, COMPLETED_AT) is True
        new_due = vobj.vtodo.due.value
        assert new_due.date() == datetime.date(2026, 8, 22)
        # 09:00 from the old DUE, not 19:30 from the completion moment.
        assert (new_due.hour, new_due.minute) == (9, 0)

    def test_dtstart_keeps_offset(self) -> None:
        """DTSTART follows DUE and keeps its original offset."""
        vobj = readOne(_from_completion_vtodo("FREQ=DAILY;INTERVAL=2;FROM=COMPLETION"))

        assert _advance_rrule(vobj, COMPLETED_AT) is True
        # DTSTART was 2 days before DUE (Aug 8 → Aug 10); DUE is now Aug 22.
        assert vobj.vtodo.dtstart.value == datetime.date(2026, 8, 20)

    def test_weekly_byday_from_completion(self) -> None:
        """Weekly BYDAY re-anchors on the completion date."""
        vobj = readOne(_from_completion_vtodo("FREQ=WEEKLY;BYDAY=MO;FROM=COMPLETION"))

        assert _advance_rrule(vobj, COMPLETED_AT) is True
        # Completed Thursday Aug 20 → next Monday is Aug 24.
        assert vobj.vtodo.due.value == datetime.date(2026, 8, 24)

    def test_repeated_completions_never_fall_behind(self) -> None:
        """Each completion re-anchors, so DUE never lags behind reality."""
        vobj = readOne(_from_completion_vtodo("FREQ=DAILY;INTERVAL=2;FROM=COMPLETION"))
        completed = COMPLETED_AT

        for _ in range(5):
            assert _advance_rrule(vobj, completed) is True
            assert (
                vobj.vtodo.due.value == (completed + datetime.timedelta(days=2)).date()
            )
            # Next completion happens a week later than planned.
            completed += datetime.timedelta(days=7)

    def test_unparseable_rrule_raises(self) -> None:
        """A malformed RRULE must not be treated as exhausted."""
        vobj = readOne(_from_completion_vtodo("FREQ=NONSENSE"))

        with pytest.raises(ValueError):
            _advance_rrule(vobj, COMPLETED_AT)

    @pytest.mark.parametrize(
        "failure", [ValueError("invalid rule"), TypeError("mixed dates")]
    )
    def test_recurrence_failure_does_not_save(self, failure: Exception) -> None:
        """Failed recurrence evaluation leaves the server task untouched."""
        todo = _make_mock_todo(VTODO_DAILY_RRULE)
        original = todo.vobject_instance.serialize()

        with (
            patch(
                "vobject.icalendar.RecurringComponent.getrruleset", side_effect=failure
            ),
            pytest.raises(ValueError),
        ):
            CalDAVClientManager._complete_or_advance(todo, "Tasks")

        todo.save.assert_not_called()
        assert todo.vobject_instance.serialize() == original

    def test_recurring_without_dates_does_not_save(self) -> None:
        """A recurring task without an anchor cannot safely be completed."""
        todo = _make_mock_todo(VTODO_DAILY_RRULE)
        todo.vobject_instance.vtodo.contents.pop("due")
        todo.vobject_instance.vtodo.contents.pop("dtstart")

        with pytest.raises(ValueError):
            CalDAVClientManager._complete_or_advance(todo, "Tasks")

        todo.save.assert_not_called()
        assert todo.vobject_instance.vtodo.status.value == "NEEDS-ACTION"


class TestAdvanceFromCompletionTag:
    """A CATEGORIES tag marks a task as repeating from its completion date."""

    def test_tag_re_anchors_on_completion(self) -> None:
        """Kattenbak case: tagged FREQ=DAILY;INTERVAL=2 follows the tick, not DUE."""
        vobj = readOne(
            _from_completion_vtodo(
                "FREQ=DAILY;INTERVAL=2", categories="chores,from-completion"
            )
        )

        assert _advance_rrule(vobj, COMPLETED_AT, "from-completion") is True
        assert vobj.vtodo.due.value == datetime.date(2026, 8, 22)

    def test_untagged_task_keeps_due_anchor(self) -> None:
        """Calendar-anchored chores are unaffected by the feature."""
        vobj = readOne(
            _from_completion_vtodo("FREQ=DAILY;INTERVAL=2", categories="chores")
        )

        assert _advance_rrule(vobj, COMPLETED_AT, "from-completion") is True
        assert vobj.vtodo.due.value == datetime.date(2026, 8, 12)

    def test_tag_matching_is_case_insensitive(self) -> None:
        """Tag comparison ignores case and surrounding whitespace."""
        vobj = readOne(
            _from_completion_vtodo(
                "FREQ=DAILY;INTERVAL=2", categories="From-Completion"
            )
        )

        assert _advance_rrule(vobj, COMPLETED_AT, "from-completion") is True
        assert vobj.vtodo.due.value == datetime.date(2026, 8, 22)

    def test_no_tag_configured_ignores_categories(self) -> None:
        """Without a configured tag the categories are irrelevant."""
        vobj = readOne(
            _from_completion_vtodo(
                "FREQ=DAILY;INTERVAL=2", categories="from-completion"
            )
        )

        assert _advance_rrule(vobj, COMPLETED_AT, None) is True
        assert vobj.vtodo.due.value == datetime.date(2026, 8, 12)

    def test_weekly_byday_tagged(self) -> None:
        """BYDAY rules re-anchor on the completion week when tagged."""
        vobj = readOne(
            _from_completion_vtodo("FREQ=WEEKLY;BYDAY=MO", categories="from-completion")
        )

        assert _advance_rrule(vobj, COMPLETED_AT, "from-completion") is True
        assert vobj.vtodo.due.value == datetime.date(2026, 8, 24)


# ---------------------------------------------------------------------------
# CalDAVClientManager tests (mocked caldav)
# ---------------------------------------------------------------------------


class TestCalDAVClientManager:
    """Tests for CalDAVClientManager with mocked CalDAV client."""

    def test_already_completed_server_task_is_unchanged(self) -> None:
        """Retrying a completed recurring task must not reopen it."""
        todo = _make_mock_todo(VTODO_DAILY_RRULE)
        todo.vobject_instance.vtodo.status.value = "COMPLETED"
        original = todo.vobject_instance.serialize()

        result = CalDAVClientManager._complete_or_advance(todo, "Tasks")

        assert result.status == "COMPLETED"
        assert todo.vobject_instance.serialize() == original
        todo.save.assert_not_called()

    @pytest.fixture
    def config(self) -> dict:
        """Return a sample CalDAV connection config."""
        return {
            "url": "https://nextcloud.local/remote.php/dav",
            "username": "testuser",
            "password": "testpass",
            "verify_ssl": True,
            "name": "Nextcloud",
        }

    @pytest.fixture
    def hass(self) -> MagicMock:
        """Return a mock HomeAssistant instance."""
        mock_hass = MagicMock()

        async def _add_executor_job(func, *args):
            return func(*args)

        mock_hass.async_add_executor_job = _add_executor_job
        return mock_hass

    @pytest.fixture
    def manager(self, hass: MagicMock, config: dict) -> CalDAVClientManager:
        """Return a CalDAVClientManager instance."""
        return CalDAVClientManager(hass, config)

    @pytest.mark.asyncio
    async def test_complete_nonrecurring(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Completing a non-recurring task marks it COMPLETED."""
        mock_todo = _make_mock_todo(VTODO_SIMPLE)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_complete_todo("Tasks", "simple-001")

        assert result is not None
        assert result.status == "COMPLETED"
        mock_todo.save.assert_called_once_with(no_create=True)

    @pytest.mark.asyncio
    async def test_complete_recurring_advances(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Completing a recurring task advances DUE instead of marking done."""
        mock_todo = _make_mock_todo(VTODO_DAILY_RRULE)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_complete_todo("Tasks", "daily-001")

        assert result is not None
        assert result.status == "NEEDS-ACTION"
        # DUE should have advanced from May 10 to May 11
        assert result.due == datetime.datetime(2026, 5, 11, 8, 0, tzinfo=datetime.UTC)
        mock_todo.save.assert_called_once_with(no_create=True)

    @pytest.mark.asyncio
    async def test_complete_exhausted_recurring(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Exhausted recurring task is marked COMPLETED."""
        mock_todo = _make_mock_todo(VTODO_EXHAUSTED)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_complete_todo("Tasks", "exhausted-001")

        assert result is not None
        assert result.status == "COMPLETED"

    @pytest.mark.asyncio
    async def test_complete_recurring_server_handles_rrule(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """When server_handles_rrule=True, recurring task is marked COMPLETED."""
        manager._server_handles_rrule = True
        mock_todo = _make_mock_todo(VTODO_DAILY_RRULE)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_complete_todo("Tasks", "daily-001")

        assert result is not None
        # Server handles RRULE — client just marks COMPLETED
        assert result.status == "COMPLETED"
        assert result.completed is not None
        mock_todo.save.assert_called_once_with(no_create=True)

    @pytest.mark.asyncio
    async def test_complete_from_completion_ignores_server_handles_rrule(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """FROM=COMPLETION is a Tasks.org extension no server implements."""
        manager._server_handles_rrule = True
        mock_todo = _make_mock_todo(
            _from_completion_vtodo("FREQ=DAILY;INTERVAL=2;FROM=COMPLETION")
        )
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_complete_todo("Tasks", "from-completion-1")

        assert result is not None
        # Advanced client-side despite server_handles_rrule=True
        assert result.status == "NEEDS-ACTION"
        assert result.completed is None
        assert (
            result.due
            == (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2)).date()
        )

    @pytest.mark.asyncio
    async def test_complete_tagged_ignores_server_handles_rrule(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """A tagged task is advanced client-side even for RRULE-aware servers."""
        manager._server_handles_rrule = True
        manager._from_completion_tag = "from-completion"
        mock_todo = _make_mock_todo(
            _from_completion_vtodo(
                "FREQ=DAILY;INTERVAL=2", categories="chores,from-completion"
            )
        )
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_complete_todo("Tasks", "from-completion-1")

        assert result is not None
        assert result.status == "NEEDS-ACTION"
        assert result.completed is None
        assert (
            result.due
            == (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=2)).date()
        )

    @pytest.mark.asyncio
    async def test_complete_nonrecurring_server_handles_rrule(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """server_handles_rrule doesn't affect non-recurring tasks."""
        manager._server_handles_rrule = True
        mock_todo = _make_mock_todo(VTODO_SIMPLE)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_complete_todo("Tasks", "simple-001")

        assert result is not None
        assert result.status == "COMPLETED"

    @pytest.mark.asyncio
    async def test_complete_not_found(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Completing a non-existent task returns None."""
        from caldav.lib.error import NotFoundError

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.side_effect = NotFoundError("not found")
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_complete_todo("Tasks", "missing-001")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_todos(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_get_todos returns parsed VTodoItems."""
        mock_todo1 = _make_mock_todo(VTODO_SIMPLE)
        mock_todo2 = _make_mock_todo(VTODO_DAILY_RRULE)

        mock_cal = MagicMock()
        mock_cal.search.return_value = [mock_todo1, mock_todo2]
        manager._calendars = {"Tasks": mock_cal}

        items = await manager.async_get_todos("Tasks")

        assert len(items) == 2
        assert items[0].uid == "simple-001"
        assert items[1].uid == "daily-001"
        assert items[1].is_recurring is True

    @pytest.mark.asyncio
    async def test_delete_todo(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_delete_todo calls delete on the caldav.Todo."""
        mock_todo = _make_mock_todo(VTODO_SIMPLE)
        mock_todo.delete = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_delete_todo("Tasks", "simple-001")

        assert result is True
        mock_todo.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_todos_missing_calendar(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_get_todos with unknown calendar returns empty list."""
        manager._calendars = {}
        items = await manager.async_get_todos("NonExistent")
        assert items == []

    @pytest.mark.asyncio
    async def test_update_vtodo_all_fields(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_update_todo can set all RFC 5545 fields."""
        mock_todo = _make_mock_todo(VTODO_SIMPLE)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo(
            "Tasks",
            "simple-001",
            summary="Updated summary",
            due=datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.UTC),
            dtstart=datetime.datetime(2026, 5, 28, 9, 0, tzinfo=datetime.UTC),
            description="New description",
            priority=5,
            percent_complete=75,
            location="Kitchen",
            url="https://example.com/updated",
            categories=["home", "chore"],
        )

        assert result is not None
        assert result.summary == "Updated summary"
        assert result.due == datetime.datetime(2026, 6, 1, 12, 0, tzinfo=datetime.UTC)
        assert result.dtstart == datetime.datetime(
            2026, 5, 28, 9, 0, tzinfo=datetime.UTC
        )
        assert result.description == "New description"
        assert result.priority == 5
        assert result.percent_complete == 75
        assert result.location == "Kitchen"
        assert result.url == "https://example.com/updated"
        assert result.categories == ["home", "chore"]
        assert mock_todo.vobject_instance.vtodo.due.value.tzinfo != datetime.UTC
        assert (
            mock_todo.vobject_instance.vtodo.due.value.utcoffset()
            == datetime.timedelta(0)
        )
        assert mock_todo.vobject_instance.vtodo.dtstart.value.tzinfo != datetime.UTC
        assert (
            mock_todo.vobject_instance.vtodo.dtstart.value.utcoffset()
            == datetime.timedelta(0)
        )
        mock_todo.save.assert_called_once_with(no_create=True)

    @pytest.mark.asyncio
    async def test_update_vtodo_remove_optional_fields(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_update_todo can remove optional fields by passing None."""
        mock_todo = _make_mock_todo(VTODO_FULL_RFC)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo(
            "Tasks",
            "full-001",
            location=None,
            url=None,
            categories=None,
        )

        assert result is not None
        assert result.location is None
        assert result.url is None
        assert result.categories == []

    @pytest.mark.asyncio
    async def test_update_missing_calendar(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_update_todo with unknown calendar returns None."""
        manager._calendars = {}
        result = await manager.async_update_todo("Ghost", "uid-1", summary="x")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_missing_uid(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_update_todo with not-found UID returns None."""
        from caldav.lib.error import NotFoundError

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.side_effect = NotFoundError("nope")
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo("Tasks", "bad-uid", summary="x")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_sentinel_fields_not_touched(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Fields left at sentinel (...) should not be modified."""
        mock_todo = _make_mock_todo(VTODO_FULL_RFC)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        # Only update summary — all other fields should be untouched
        result = await manager.async_update_todo(
            "Tasks", "full-001", summary="New title"
        )

        assert result is not None
        assert result.summary == "New title"
        # All other fields stay from the original
        assert result.priority == 3
        assert result.percent_complete == 40
        assert result.location == "Home office"
        assert result.url == "https://example.com/task/123"

    @pytest.mark.asyncio
    async def test_update_status_only(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Update only the status field."""
        mock_todo = _make_mock_todo(VTODO_IN_PROCESS)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo(
            "Tasks", "inprocess-001", status="COMPLETED"
        )

        assert result is not None
        assert result.status == "COMPLETED"
        mock_todo.save.assert_called_once_with(no_create=True)

    @pytest.mark.asyncio
    async def test_update_priority_from_none(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Add priority to a VTODO that didn't have one."""
        mock_todo = _make_mock_todo(VTODO_MINIMAL)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo("Tasks", "minimal-001", priority=5)

        assert result is not None
        assert result.priority == 5

    @pytest.mark.asyncio
    async def test_update_remove_priority(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Remove priority from a VTODO."""
        mock_todo = _make_mock_todo(VTODO_SIMPLE)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo("Tasks", "simple-001", priority=None)

        assert result is not None
        assert result.priority is None

    @pytest.mark.asyncio
    async def test_update_percent_complete_add_and_change(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Set percent-complete, then change it."""
        mock_todo = _make_mock_todo(VTODO_MINIMAL)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo(
            "Tasks", "minimal-001", percent_complete=25
        )
        assert result is not None
        assert result.percent_complete == 25

        # Now update to 75 — reuse the same mock_todo which was mutated
        mock_todo.save.reset_mock()
        result2 = await manager.async_update_todo(
            "Tasks", "minimal-001", percent_complete=75
        )
        assert result2 is not None
        assert result2.percent_complete == 75

    @pytest.mark.asyncio
    async def test_update_categories_replace(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Replace existing categories with new ones."""
        mock_todo = _make_mock_todo(VTODO_MULTI_CATEGORIES)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo(
            "Tasks", "multicat-001", categories=["only-this"]
        )
        assert result is not None
        assert result.categories == ["only-this"]

    @pytest.mark.asyncio
    async def test_update_due_to_date_only(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Update DUE from datetime to date-only."""
        mock_todo = _make_mock_todo(VTODO_SIMPLE)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo(
            "Tasks", "simple-001", due=datetime.date(2026, 7, 1)
        )
        assert result is not None
        assert result.due == datetime.date(2026, 7, 1)

    @pytest.mark.asyncio
    async def test_update_remove_due(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Remove DUE from a VTODO."""
        mock_todo = _make_mock_todo(VTODO_SIMPLE)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo("Tasks", "simple-001", due=None)
        assert result is not None
        assert result.due is None

    @pytest.mark.asyncio
    async def test_update_add_description(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Add description to a VTODO that has none."""
        mock_todo = _make_mock_todo(VTODO_MINIMAL)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo(
            "Tasks", "minimal-001", description="Added notes"
        )
        assert result is not None
        assert result.description == "Added notes"

    @pytest.mark.asyncio
    async def test_update_remove_description(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Remove description from a VTODO."""
        mock_todo = _make_mock_todo(VTODO_SIMPLE)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_update_todo(
            "Tasks", "simple-001", description=None
        )
        assert result is not None
        assert result.description is None

    @pytest.mark.asyncio
    async def test_complete_missing_calendar(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_complete_todo with unknown calendar returns None."""
        manager._calendars = {}
        result = await manager.async_complete_todo("Ghost", "uid-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_complete_sets_completed_timestamp(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Completing a non-recurring task sets COMPLETED timestamp."""
        mock_todo = _make_mock_todo(VTODO_SIMPLE)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_complete_todo("Tasks", "simple-001")

        assert result is not None
        assert result.status == "COMPLETED"
        assert result.completed is not None
        assert isinstance(result.completed, datetime.datetime)
        assert mock_todo.vobject_instance.vtodo.completed.value.tzinfo != datetime.UTC
        assert (
            mock_todo.vobject_instance.vtodo.completed.value.utcoffset()
            == datetime.timedelta(0)
        )

    @pytest.mark.asyncio
    async def test_complete_recurring_preserves_rrule(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Completing a recurring task preserves the RRULE."""
        mock_todo = _make_mock_todo(VTODO_DAILY_RRULE)
        mock_todo.save = MagicMock()

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_complete_todo("Tasks", "daily-001")

        assert result is not None
        assert result.rrule is not None
        assert "FREQ=DAILY" in result.rrule

    @pytest.mark.asyncio
    async def test_delete_missing_calendar(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_delete_todo with unknown calendar returns False."""
        manager._calendars = {}
        result = await manager.async_delete_todo("Ghost", "uid-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_missing_uid(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_delete_todo with not-found UID returns False."""
        from caldav.lib.error import NotFoundError

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.side_effect = NotFoundError("nope")
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_delete_todo("Tasks", "bad-uid")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_exception(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_delete_todo handles delete() exception gracefully."""
        mock_todo = _make_mock_todo(VTODO_SIMPLE)
        mock_todo.delete = MagicMock(side_effect=ConnectionError("offline"))

        mock_cal = MagicMock()
        mock_cal.todo_by_uid.return_value = mock_todo
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_delete_todo("Tasks", "simple-001")
        assert result is False

    @pytest.mark.asyncio
    async def test_add_todo_missing_calendar(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_add_todo with unknown calendar returns None."""
        manager._calendars = {}
        result = await manager.async_add_todo("Ghost", "new task")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_todo_generic_exception(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """_find_todo_by_uid handles generic exceptions."""
        mock_cal = MagicMock()
        mock_cal.todo_by_uid.side_effect = ConnectionError("network")
        manager._calendars = {"Tasks": mock_cal}

        result = await manager.async_complete_todo("Tasks", "uid-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_start_connects_and_discovers(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_start connects and discovers calendars."""
        mock_cal1 = MagicMock()
        mock_cal1.name = "Tasks"
        mock_cal2 = MagicMock()
        mock_cal2.name = "Personal"

        with (
            patch.object(manager, "_connect") as mock_connect,
            patch.object(
                manager, "_discover_calendars", return_value=[mock_cal1, mock_cal2]
            ),
        ):
            mock_connect.return_value = MagicMock()
            await manager.async_start()

        assert "Tasks" in manager.calendars
        assert "Personal" in manager.calendars
        assert manager._started is True

    @pytest.mark.asyncio
    async def test_start_idempotent(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """Calling async_start twice doesn't reconnect."""
        manager._started = True
        with patch.object(manager, "_connect") as mock_connect:
            await manager.async_start()
        mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_failure_raises(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_start re-raises on connection failure."""
        with (
            patch.object(manager, "_connect", side_effect=ConnectionError("refused")),
            pytest.raises(ConnectionError),
        ):
            await manager.async_start()

        assert manager._started is False

    @pytest.mark.asyncio
    async def test_stop_cleans_up(
        self, manager: CalDAVClientManager, hass: MagicMock
    ) -> None:
        """async_stop resets internal state."""
        manager._started = True
        manager._client = MagicMock()
        manager._calendars = {"Tasks": MagicMock()}

        await manager.async_stop()

        assert manager._client is None
        assert manager._calendars == {}
        assert manager._started is False

    def test_name_property(self, manager: CalDAVClientManager) -> None:
        """Name property returns the configured name."""
        assert manager.name == "Nextcloud"

    def test_name_defaults_to_url(self, hass: MagicMock) -> None:
        """Name falls back to URL when not configured."""
        config = {
            "url": "https://dav.example.com",
            "username": "u",
            "password": "p",
        }
        mgr = CalDAVClientManager(hass, config)
        assert mgr.name == "https://dav.example.com"

    def test_server_handles_rrule_default_false(self, hass: MagicMock) -> None:
        """server_handles_rrule defaults to False."""
        config = {"url": "https://dav.local", "username": "u", "password": "p"}
        mgr = CalDAVClientManager(hass, config)
        assert mgr._server_handles_rrule is False

    def test_server_handles_rrule_from_config(self, hass: MagicMock) -> None:
        """server_handles_rrule is read from config."""
        config = {
            "url": "https://dav.local",
            "username": "u",
            "password": "p",
            "server_handles_rrule": True,
        }
        mgr = CalDAVClientManager(hass, config)
        assert mgr._server_handles_rrule is True
