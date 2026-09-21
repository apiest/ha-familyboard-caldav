"""CalDAV client manager for FamilyBoard.

Owns the CalDAV connection lifecycle and exposes RFC 5545-compliant VTODO
operations. Recurring tasks are advanced (DUE updated to the next occurrence)
instead of being marked completed, preserving the recurrence chain.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import datetime
import logging
import re
from typing import Any

import caldav
from caldav.lib.error import NotFoundError
from dateutil.rrule import rrulestr
from dateutil.tz import tzutc
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from vobject.base import Component as VObject

from .const import CONF_FROM_COMPLETION_TAG, DEFAULT_FROM_COMPLETION_TAG

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "familyboard_caldav_sync"
STORAGE_VERSION = 1

# Tasks.org encodes "repeat from completion date" as a non-standard FROM=
# part inside the RRULE. Nextcloud stores it verbatim and dateutil rejects it,
# so it must be split off before parsing and preserved when saving.
_REPEAT_FROM_RE = re.compile(r";?\bFROM=(COMPLETION|DUE)\b", re.IGNORECASE)


def _split_repeat_from(rrule_value: str) -> tuple[str, bool]:
    """Split a raw RRULE into (standard rule, repeats-from-completion)."""
    match = _REPEAT_FROM_RE.search(rrule_value)
    if match is None:
        return rrule_value, False
    cleaned = _REPEAT_FROM_RE.sub("", rrule_value).strip(";")
    return cleaned, match.group(1).upper() == "COMPLETION"


def _matches_tag(categories: list[str], tag: str | None) -> bool:
    """Return True if *tag* appears in *categories*, ignoring case and spacing."""
    if not tag:
        return False
    folded = tag.strip().casefold()
    return any(str(c).strip().casefold() == folded for c in categories)


def _vtodo_categories(vtodo: Any) -> list[str]:
    """Return the CATEGORIES values of a vobject VTODO."""
    if not hasattr(vtodo, "categories"):
        return []
    cats = vtodo.categories.value
    return [str(c) for c in cats] if isinstance(cats, list) else [str(cats)]


def _recurrence_mode(vtodo: Any, tag: str | None) -> tuple[str, bool]:
    """Return (standard RRULE text, repeats-from-completion) for a VTODO.

    An explicit ``FROM=`` part in the RRULE wins; otherwise the CATEGORIES tag
    decides.
    """
    raw = str(vtodo.rrule.value)
    rule_text, from_completion = _split_repeat_from(raw)
    if rule_text != raw:
        return rule_text, from_completion
    return rule_text, _matches_tag(_vtodo_categories(vtodo), tag)


@dataclass
class VTodoItem:
    """Parsed VTODO — all RFC 5545 fields preserved."""

    uid: str
    summary: str
    status: str
    due: datetime.datetime | datetime.date | None = None
    dtstart: datetime.datetime | datetime.date | None = None
    completed: datetime.datetime | None = None
    description: str | None = None
    rrule: str | None = None
    calendar_name: str = ""
    calendar_url: str = ""
    priority: int | None = None
    percent_complete: int | None = None
    location: str | None = None
    url: str | None = None
    categories: list[str] = field(default_factory=list)

    @property
    def is_recurring(self) -> bool:
        """Return True if this VTODO has a recurrence rule."""
        return self.rrule is not None

    def repeats_from_completion(self, tag: str = DEFAULT_FROM_COMPLETION_TAG) -> bool:
        """Return True when this task recurs from its completion date."""
        if self.rrule is not None:
            rule_text, from_completion = _split_repeat_from(self.rrule)
            if rule_text != self.rrule:
                return from_completion
        return _matches_tag(self.categories, tag)


def _parse_vtodo(todo: caldav.Todo, calendar_name: str = "") -> VTodoItem:
    """Parse a caldav.Todo into a VTodoItem."""
    vobj: VObject = todo.vobject_instance
    vtodo = vobj.vtodo

    uid = str(vtodo.uid.value) if hasattr(vtodo, "uid") else ""
    summary = str(vtodo.summary.value) if hasattr(vtodo, "summary") else ""
    status_raw = str(vtodo.status.value) if hasattr(vtodo, "status") else "NEEDS-ACTION"
    description = (
        str(vtodo.description.value) if hasattr(vtodo, "description") else None
    )

    due: datetime.datetime | datetime.date | None = None
    if hasattr(vtodo, "due"):
        due = vtodo.due.value

    rrule: str | None = None
    if hasattr(vtodo, "rrule"):
        rrule = str(vtodo.rrule.value)

    priority: int | None = None
    if hasattr(vtodo, "priority"):
        with contextlib.suppress(ValueError, TypeError):
            priority = int(vtodo.priority.value)

    categories: list[str] = []
    if hasattr(vtodo, "categories"):
        cats = vtodo.categories.value
        categories = [str(c) for c in cats] if isinstance(cats, list) else [str(cats)]

    dtstart: datetime.datetime | datetime.date | None = None
    if hasattr(vtodo, "dtstart"):
        dtstart = vtodo.dtstart.value

    completed_dt: datetime.datetime | None = None
    if hasattr(vtodo, "completed"):
        val = vtodo.completed.value
        if isinstance(val, datetime.datetime):
            completed_dt = val

    percent_complete: int | None = None
    if hasattr(vtodo, "percent_complete"):
        with contextlib.suppress(ValueError, TypeError):
            percent_complete = int(vtodo.percent_complete.value)

    location: str | None = None
    if hasattr(vtodo, "location"):
        location = str(vtodo.location.value) or None

    vtodo_url: str | None = None
    if hasattr(vtodo, "url"):
        vtodo_url = str(vtodo.url.value) or None

    return VTodoItem(
        uid=uid,
        summary=summary,
        status=status_raw.upper(),
        due=due,
        dtstart=dtstart,
        completed=completed_dt,
        description=description,
        rrule=rrule,
        calendar_name=calendar_name,
        calendar_url=str(todo.url) if todo.url else "",
        priority=priority,
        percent_complete=percent_complete,
        location=location,
        url=vtodo_url,
        categories=categories,
    )


def _normalize_vobject_value(value: Any) -> Any:
    """Convert stdlib UTC datetimes into a vobject-compatible tzinfo."""
    if isinstance(value, datetime.datetime) and value.tzinfo == datetime.UTC:
        return value.astimezone(tzutc())
    return value


def _completion_anchor(
    current_due_dt: datetime.datetime,
    completed_at: datetime.datetime,
    *,
    date_only: bool,
) -> datetime.datetime:
    """Return the anchor for a FROM=COMPLETION recurrence.

    Mirrors Tasks.org: anchor on the moment the task was ticked off, but keep
    the original DUE time-of-day when the VTODO carries one.
    """
    if date_only:
        return datetime.datetime.combine(completed_at.date(), datetime.time.min)

    anchor = completed_at.astimezone(current_due_dt.tzinfo)
    return anchor.replace(
        hour=current_due_dt.hour,
        minute=current_due_dt.minute,
        second=current_due_dt.second,
        microsecond=0,
    )


def _advance_rrule(
    vtodo_vobj: VObject,
    completed_at: datetime.datetime | None = None,
    from_completion_tag: str | None = None,
) -> bool:
    """Advance the DUE date of a recurring VTODO to the next occurrence.

    Tasks marked as repeating from their completion date -- either via the
    ``from_completion_tag`` CATEGORIES tag or the legacy Tasks.org
    ``FROM=COMPLETION`` RRULE part -- are re-anchored on the moment they were
    ticked off instead of on their previous DUE date.

    Returns True if the task was advanced (still has future occurrences),
    False if the recurrence is exhausted.
    """
    vtodo = vtodo_vobj.vtodo

    if not hasattr(vtodo, "rrule"):
        return False

    raw_rrule = str(vtodo.rrule.value)
    rule_text, from_completion = _recurrence_mode(vtodo, from_completion_tag)

    current_due: datetime.datetime | datetime.date | None = None
    if hasattr(vtodo, "due"):
        current_due = vtodo.due.value

    if current_due is None:
        # No DUE date — use DTSTART as anchor
        if hasattr(vtodo, "dtstart"):
            current_due = vtodo.dtstart.value
        else:
            raise ValueError(
                "Recurring VTODO has no DUE or DTSTART; task left unchanged"
            )

    # Ensure we have a datetime for rruleset.after().
    # Keep timezone awareness consistent with what the rruleset produces:
    # date-only VTODOs → naive datetimes; tz-aware VTODOs → aware datetimes.
    date_only = isinstance(current_due, datetime.date) and not isinstance(
        current_due, datetime.datetime
    )
    if date_only:
        current_due_dt = datetime.datetime.combine(current_due, datetime.time.min)
    else:
        current_due_dt = current_due
        if current_due_dt.tzinfo is None:
            current_due_dt = current_due_dt.replace(tzinfo=datetime.UTC)

    anchor = current_due_dt
    next_due = None
    try:
        if from_completion:
            # Nextcloud stores the RRULE but never advances it, so we do what
            # Tasks.org does client-side: re-anchor the rule on the completion.
            anchor = _completion_anchor(
                current_due_dt,
                completed_at or datetime.datetime.now(datetime.UTC),
                date_only=date_only,
            )
            rruleset = rrulestr(rule_text, dtstart=anchor)
        elif rule_text != raw_rrule:
            # FROM=DUE — standard semantics, but dateutil chokes on the part,
            # so parse the sanitized rule anchored the way vobject would.
            dtstart = current_due_dt
            if hasattr(vtodo, "dtstart"):
                start_val = vtodo.dtstart.value
                dtstart = (
                    datetime.datetime.combine(start_val, datetime.time.min)
                    if date_only
                    else start_val
                )
            rruleset = rrulestr(rule_text, dtstart=dtstart)
        else:
            rruleset = vtodo.getrruleset()
        if rruleset is not None:
            next_due = rruleset.after(anchor)
    except (ValueError, TypeError) as err:
        raise ValueError(
            f"Cannot advance RRULE {raw_rrule!r}; task left unchanged"
        ) from err

    if rruleset is None:
        raise ValueError("No recurrence set could be evaluated; task left unchanged")

    if next_due is None:
        # Recurrence exhausted
        return False

    previous_due = current_due_dt

    # Advance DUE to next occurrence
    if hasattr(vtodo, "due"):
        if isinstance(vtodo.due.value, datetime.date) and not isinstance(
            vtodo.due.value, datetime.datetime
        ):
            # Preserve date-only DUE
            vtodo.due.value = (
                next_due.date() if isinstance(next_due, datetime.datetime) else next_due
            )
        else:
            vtodo.due.value = next_due
    else:
        vtodo.add("due").value = next_due

    # Reset STATUS to NEEDS-ACTION
    if hasattr(vtodo, "status"):
        vtodo.status.value = "NEEDS-ACTION"
    else:
        vtodo.add("status").value = "NEEDS-ACTION"

    # Remove COMPLETED timestamp if present
    if hasattr(vtodo, "completed"):
        vtodo.contents.pop("completed", None)

    # For FROM=DUE recurrences DTSTART anchors the RRULE — shifting it would
    # reset COUNT / make UNTIL unreachable, so only DUE advances. FROM=COMPLETION
    # rules are anchored on the completion instead, so DTSTART is free to follow
    # DUE and keep its original offset (this is what Tasks.org does).
    if from_completion and hasattr(vtodo, "dtstart"):
        delta = next_due - previous_due
        start_val = vtodo.dtstart.value
        if isinstance(start_val, datetime.datetime):
            vtodo.dtstart.value = start_val + delta
        elif isinstance(start_val, datetime.date):
            vtodo.dtstart.value = start_val + datetime.timedelta(days=delta.days)

    return True


class CalDAVClientManager:
    """Manage a CalDAV connection and provide VTODO operations."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
    ) -> None:
        """Initialize the CalDAV client manager."""
        self._hass = hass
        self._url: str = config["url"]
        self._username: str = config["username"]
        self._password: str = config["password"]
        self._verify_ssl: bool = config.get("verify_ssl", True)
        self._name: str = config.get("name") or self._url
        self._server_handles_rrule: bool = config.get("server_handles_rrule", False)
        self._from_completion_tag: str = (
            config.get(CONF_FROM_COMPLETION_TAG) or DEFAULT_FROM_COMPLETION_TAG
        )
        self._client: caldav.DAVClient | None = None
        self._calendars: dict[str, caldav.Calendar] = {}
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY)
        self._started = False

    @property
    def name(self) -> str:
        """Return the connection name."""
        return self._name

    @property
    def calendars(self) -> dict[str, caldav.Calendar]:
        """Return discovered calendars keyed by name."""
        return self._calendars

    async def async_start(self) -> None:
        """Connect to the CalDAV server and discover calendars."""
        if self._started:
            return

        try:
            self._client = await self._hass.async_add_executor_job(self._connect)
            cals = await self._hass.async_add_executor_job(self._discover_calendars)
            self._calendars = {cal.name: cal for cal in cals if cal.name}
            self._started = True
            _LOGGER.info(
                "CalDAV connected to %s, found %d calendar(s): %s",
                self._url,
                len(self._calendars),
                ", ".join(self._calendars.keys()),
            )
        except Exception:
            _LOGGER.exception("Failed to connect to CalDAV server %s", self._url)
            raise

    def _connect(self) -> caldav.DAVClient:
        """Create and return a DAVClient (sync, runs in executor)."""
        return caldav.DAVClient(
            url=self._url,
            username=self._username,
            password=self._password,
            ssl_verify_cert=self._verify_ssl,
        )

    def _discover_calendars(self) -> list[caldav.Calendar]:
        """Discover calendars from the principal (sync, runs in executor)."""
        if self._client is None:
            return []
        principal = self._client.principal()
        return principal.calendars()

    async def async_stop(self) -> None:
        """Clean up the client connection."""
        self._client = None
        self._calendars = {}
        self._started = False

    async def async_get_todos(
        self,
        calendar_name: str,
        *,
        include_completed: bool = False,
    ) -> list[VTodoItem]:
        """Return VTODOs from a specific calendar."""
        cal = self._calendars.get(calendar_name)
        if cal is None:
            _LOGGER.warning(
                "Calendar '%s' not found in CalDAV connection", calendar_name
            )
            return []

        raw_todos: list[caldav.Todo] = await self._hass.async_add_executor_job(
            self._search_todos, cal, include_completed
        )
        return [_parse_vtodo(t, calendar_name) for t in raw_todos]

    @staticmethod
    def _search_todos(
        cal: caldav.Calendar, include_completed: bool
    ) -> list[caldav.Todo]:
        """Search for todos in a calendar (sync, runs in executor)."""
        return cal.search(todo=True, include_completed=include_completed)

    async def async_complete_todo(
        self, calendar_name: str, uid: str
    ) -> VTodoItem | None:
        """Complete a VTODO. Recurring tasks are advanced, not completed.

        Returns the updated VTodoItem, or None if the task was not found.
        """
        cal = self._calendars.get(calendar_name)
        if cal is None:
            return None

        todo = await self._hass.async_add_executor_job(self._find_todo_by_uid, cal, uid)
        if todo is None:
            _LOGGER.warning("VTODO %s not found in calendar %s", uid, calendar_name)
            return None

        updated = await self._hass.async_add_executor_job(
            self._complete_or_advance,
            todo,
            calendar_name,
            self._server_handles_rrule,
            self._from_completion_tag,
        )
        return updated

    @staticmethod
    def _find_todo_by_uid(cal: caldav.Calendar, uid: str) -> caldav.Todo | None:
        """Find a VTODO by UID (sync, runs in executor)."""
        try:
            return cal.todo_by_uid(uid)
        except NotFoundError:
            return None
        except Exception:
            _LOGGER.exception("Error finding VTODO %s", uid)
            return None

    @staticmethod
    def _complete_or_advance(
        todo: caldav.Todo,
        calendar_name: str,
        server_handles_rrule: bool = False,
        from_completion_tag: str | None = None,
    ) -> VTodoItem:
        """Complete or advance a VTODO (sync, runs in executor).

        When *server_handles_rrule* is True, recurring tasks are simply
        marked COMPLETED and the server is expected to create the next
        occurrence. When False (the default), the client advances DUE
        to the next RRULE occurrence itself.

        Repeat-from-completion tasks are always advanced client-side: no
        CalDAV server implements that behaviour.
        """
        vobj = todo.vobject_instance

        if getattr(getattr(vobj.vtodo, "status", None), "value", None) == "COMPLETED":
            return _parse_vtodo(todo, calendar_name)

        client_side = not server_handles_rrule
        if not client_side and hasattr(vobj.vtodo, "rrule"):
            _, client_side = _recurrence_mode(vobj.vtodo, from_completion_tag)

        if client_side and _advance_rrule(
            vobj, from_completion_tag=from_completion_tag
        ):
            # Client-side recurrence: save the advanced VTODO
            todo.save(no_create=True)
            _LOGGER.debug(
                "Advanced recurring VTODO %s to next occurrence",
                vobj.vtodo.uid.value,
            )
        else:
            # Non-recurring, exhausted, or server handles RRULE: mark completed
            if hasattr(vobj.vtodo, "status"):
                vobj.vtodo.status.value = "COMPLETED"
            else:
                vobj.vtodo.add("status").value = "COMPLETED"
            if not hasattr(vobj.vtodo, "completed"):
                vobj.vtodo.add("completed")
            vobj.vtodo.completed.value = _normalize_vobject_value(
                datetime.datetime.now(datetime.UTC)
            )
            todo.save(no_create=True)
            _LOGGER.debug("Completed VTODO %s", vobj.vtodo.uid.value)

        return _parse_vtodo(todo, calendar_name)

    async def async_add_todo(
        self,
        calendar_name: str,
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
    ) -> VTodoItem | None:
        """Create a new VTODO in the specified calendar."""
        cal = self._calendars.get(calendar_name)
        if cal is None:
            return None

        todo = await self._hass.async_add_executor_job(
            self._create_todo,
            cal,
            summary,
            due,
            dtstart,
            description,
            priority,
            percent_complete,
            location,
            url,
            categories,
        )
        return _parse_vtodo(todo, calendar_name) if todo else None

    @staticmethod
    def _create_todo(
        cal: caldav.Calendar,
        summary: str,
        due: datetime.datetime | datetime.date | None,
        dtstart: datetime.datetime | datetime.date | None,
        description: str | None,
        priority: int | None,
        percent_complete: int | None,
        location: str | None,
        url: str | None,
        categories: list[str] | None,
    ) -> caldav.Todo | None:
        """Create a VTODO (sync, runs in executor)."""
        kwargs: dict[str, Any] = {"summary": summary}
        if due is not None:
            kwargs["due"] = _normalize_vobject_value(due)
        if dtstart is not None:
            kwargs["dtstart"] = _normalize_vobject_value(dtstart)
        if description:
            kwargs["description"] = description
        if priority is not None:
            kwargs["priority"] = priority
        # Fields not supported by caldav.add_todo() — set via vobject after creation
        extra_fields: dict[str, Any] = {}
        if percent_complete is not None:
            extra_fields["percent-complete"] = str(percent_complete)
        if location:
            extra_fields["location"] = location
        if url:
            extra_fields["url"] = url
        if categories:
            extra_fields["categories"] = categories
        try:
            todo = cal.add_todo(**kwargs)
            if extra_fields and todo is not None:
                vtodo = todo.vobject_instance.vtodo
                for prop, val in extra_fields.items():
                    vtodo.add(prop).value = val
                todo.save(no_create=True)
        except Exception:
            _LOGGER.exception("Failed to create VTODO '%s'", summary)
            return None
        else:
            return todo

    async def async_update_todo(
        self,
        calendar_name: str,
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
    ) -> VTodoItem | None:
        """Update fields on an existing VTODO."""
        cal = self._calendars.get(calendar_name)
        if cal is None:
            return None

        todo = await self._hass.async_add_executor_job(self._find_todo_by_uid, cal, uid)
        if todo is None:
            return None

        fields: dict[str, Any] = {
            "summary": summary,
            "due": due,
            "dtstart": dtstart,
            "description": description,
            "status": status,
            "priority": priority,
            "percent_complete": percent_complete,
            "location": location,
            "url": url,
            "categories": categories,
        }
        updated = await self._hass.async_add_executor_job(
            self._update_fields, todo, calendar_name, fields
        )
        return updated

    @staticmethod
    def _set_or_remove(vtodo: Any, prop: str, value: Any, sentinel: Any = ...) -> None:
        """Set, remove, or skip a vobject property."""
        if value is sentinel:
            return  # not provided
        value = _normalize_vobject_value(value)
        if value is None:
            if hasattr(vtodo, prop):
                vtodo.contents.pop(prop, None)
        elif hasattr(vtodo, prop):
            getattr(vtodo, prop).value = value
        else:
            vtodo.add(prop).value = value

    @staticmethod
    def _update_fields(
        todo: caldav.Todo,
        calendar_name: str,
        fields: dict[str, Any],
    ) -> VTodoItem:
        """Mutate VTODO fields and save (sync, runs in executor)."""
        vtodo = todo.vobject_instance.vtodo
        _set = CalDAVClientManager._set_or_remove

        if fields["summary"] is not None:
            vtodo.summary.value = fields["summary"]

        _set(vtodo, "due", fields["due"])
        _set(vtodo, "dtstart", fields["dtstart"])
        _set(vtodo, "description", fields["description"])
        _set(vtodo, "location", fields["location"])
        _set(vtodo, "url", fields["url"])

        if fields["status"] is not None:
            if hasattr(vtodo, "status"):
                vtodo.status.value = fields["status"]
            else:
                vtodo.add("status").value = fields["status"]

        # Integer fields: convert to string for vobject
        priority = fields["priority"]
        if priority is not ...:
            if priority is None:
                if hasattr(vtodo, "priority"):
                    vtodo.contents.pop("priority", None)
            else:
                if hasattr(vtodo, "priority"):
                    vtodo.priority.value = str(priority)
                else:
                    vtodo.add("priority").value = str(priority)

        pct = fields["percent_complete"]
        if pct is not ...:
            prop = "percent-complete"
            if pct is None:
                if hasattr(vtodo, "percent_complete"):
                    vtodo.contents.pop(prop, None)
            else:
                if prop in vtodo.contents:
                    vtodo.contents[prop][0].value = str(pct)
                else:
                    vtodo.add(prop).value = str(pct)

        cats = fields["categories"]
        if cats is not ...:
            if cats is None:
                vtodo.contents.pop("categories", None)
            else:
                vtodo.contents.pop("categories", None)
                vtodo.add("categories").value = cats

        todo.save(no_create=True)
        return _parse_vtodo(todo, calendar_name)

    async def async_delete_todo(self, calendar_name: str, uid: str) -> bool:
        """Delete a VTODO by UID. Returns True on success."""
        cal = self._calendars.get(calendar_name)
        if cal is None:
            return False

        todo = await self._hass.async_add_executor_job(self._find_todo_by_uid, cal, uid)
        if todo is None:
            return False

        try:
            await self._hass.async_add_executor_job(todo.delete)
        except Exception:
            _LOGGER.exception("Failed to delete VTODO %s", uid)
            return False
        else:
            return True
