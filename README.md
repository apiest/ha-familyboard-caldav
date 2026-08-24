# FamilyBoard CalDAV

RFC 5545-compliant CalDAV VTODO integration for Home Assistant. Connects to any
CalDAV server (Nextcloud, Radicale, Baikal, iCloud, Exchange, …), discovers
calendars, and exposes each as a `todo.*` entity with full recurring-task
support.

> **Standalone integration.** Works independently of FamilyBoard, but the
> `todo.*` entities it creates plug straight into FamilyBoard's `chores:` /
> `shared_chores:` config.

## Features

- **Full VTODO field preservation** — `DTSTART`, `DUE`, `COMPLETED`,
  `PRIORITY`, `PERCENT-COMPLETE`, `LOCATION`, `URL`, `CATEGORIES`, `RRULE`,
  `DESCRIPTION` are all exposed in `extra_state_attributes.vtodo_items`.
- **Recurring task completion** — completing a recurring VTODO advances the
  `DUE` date to the next RRULE occurrence instead of marking the task done.
  Supports `FREQ=DAILY`, `WEEKLY`, `MONTHLY`, `YEARLY`, `BYDAY`, `INTERVAL`,
  `COUNT` and `UNTIL`.
- **Server-handled recurrence** — `server_handles_rrule` toggle for servers
  that manage recurrence themselves (e.g. Exchange).
- **Repeat from completion date** — tag a task (default tag:
  `from-completion`) to make it recur relative to *when you ticked it off*
  instead of relative to its previous `DUE` date. See
  [Repeat from completion date](#repeat-from-completion-date).
- **DataUpdateCoordinator** — all calendars are polled every 5 minutes by a
  single coordinator; entities read cached data.
- **Reconfigure flow** — change URL, credentials, or settings without removing
  the integration.
- **Diagnostics** — downloadable diagnostics with redacted credentials,
  calendar list, and per-calendar todo counts.

## Modules

| File | Purpose |
|---|---|
| `__init__.py` | Entry setup: creates coordinator, forwards todo platform. |
| `coordinator.py` | `CalDAVCoordinator` — `DataUpdateCoordinator` wrapping `CalDAVClientManager`, polls all calendars. Defines `CalDAVConfigEntry`. |
| `caldav_client.py` | `CalDAVClientManager` — CalDAV connection lifecycle, VTODO CRUD, RRULE advancement logic. `VTodoItem` dataclass. |
| `todo.py` | `FamilyBoardCalDAVTodo` — `CoordinatorEntity` + `TodoListEntity`, full HA todo API + extended VTODO methods. |
| `config_flow.py` | User step (connection test) + reconfigure step. |
| `diagnostics.py` | Config entry diagnostics — redacted config, calendars, todo counts, connection status. |
| `const.py` | Domain constant, update interval, repeat-from-completion tag default. |
| `translations/` | EN + NL strings for config flow. |

## Architecture

```
┌─────────────────┐
│  CalDAV server   │    (Nextcloud, Radicale, Baikal, …)
│  RFC 4791        │
└────────┬────────┘
         │  caldav library (executor)
┌────────▼────────┐
│ CalDAVClient-    │    Connection lifecycle, calendar discovery,
│ Manager          │    VTODO parsing, RRULE advancement
└────────┬────────┘
         │
┌────────▼────────┐
│ CalDAV-          │    DataUpdateCoordinator — polls every 5 min,
│ Coordinator      │    caches dict[calendar_name → list[VTodoItem]]
└────────┬────────┘
         │
┌────────▼────────┐
│ FamilyBoard-     │    CoordinatorEntity + TodoListEntity
│ CalDAVTodo       │    One entity per discovered calendar
│ (todo.*)         │
└─────────────────┘
```

- **Polling**: the coordinator polls all calendars every 5 minutes.
  Mutations (create / update / delete / complete) trigger an immediate
  coordinator refresh.
- **Blocking I/O**: all `caldav` library calls run in the executor via
  `hass.async_add_executor_job` — no blocking on the event loop.
- **ConfigEntryNotReady**: if the server is unreachable at setup, HA
  retries automatically.

## VTodoItem model

The `VTodoItem` dataclass holds a parsed RFC 5545 VTODO:

| Field | Type | Notes |
|---|---|---|
| `uid` | `str` | VTODO UID |
| `summary` | `str` | Task title |
| `status` | `str` | `NEEDS-ACTION`, `IN-PROCESS`, `COMPLETED`, `CANCELLED` |
| `due` | `datetime \| date \| None` | Due date/time |
| `dtstart` | `datetime \| date \| None` | Start date/time |
| `completed` | `datetime \| None` | Completion timestamp |
| `description` | `str \| None` | Notes |
| `rrule` | `str \| None` | Recurrence rule (raw string) |
| `calendar_name` | `str` | Parent calendar |
| `calendar_url` | `str` | CalDAV resource URL |
| `priority` | `int \| None` | 0–9 (1 = highest, 9 = lowest) |
| `percent_complete` | `int \| None` | 0–100 |
| `location` | `str \| None` | Location |
| `url` | `str \| None` | Related URL |
| `categories` | `list[str]` | Tags / categories |

### RRULE advancement

When a recurring VTODO is completed:

1. The RRULE set is evaluated for the next occurrence after the current `DUE`.
2. `DUE` is advanced to that occurrence; `STATUS` is reset to `NEEDS-ACTION`;
   `COMPLETED` is removed.
3. `DTSTART` is **not** shifted — it anchors the RRULE. Shifting it would
   reset `COUNT` or make `UNTIL` unreachable. (Exception: tasks that
   [repeat from their completion date](#repeat-from-completion-date) are
   re-anchored anyway, so their `DTSTART` follows `DUE`.)
4. If no future occurrence exists (recurrence exhausted), the task is marked
   `COMPLETED` normally.

When `server_handles_rrule` is enabled, the client skips advancement and simply
marks the task `COMPLETED` — the server creates the next occurrence.

### Repeat from completion date

Some chores are anchored to the calendar ("first Thursday of the month"), but
most household chores are anchored to the *last time you actually did them*
("empty the litter box every 2 days"). RFC 5545 only describes the first kind.

Without this feature, completing a litter-box chore two days late gives you:

| Task completed | Repeat from due date | Repeat from completion date |
|---|---|---|
| on time (due 25 Aug) | 27 Aug ✅ | 27 Aug ✅ |
| late (28 Aug) | **27 Aug — due again immediately** ❌ | 30 Aug ✅ |

#### How to enable it

Add the tag `from-completion` to the task. In **Tasks.org** this is a normal
tag; in **Nextcloud Tasks** it is a category. Either way it lands in the VTODO's
`CATEGORIES` property, which syncs to every client:

```ics
BEGIN:VTODO
SUMMARY:Empty the litter box
DUE;VALUE=DATE:20260825
RRULE:FREQ=DAILY;INTERVAL=2
CATEGORIES:chores,from-completion
END:VTODO
```

On completion the integration re-anchors the RRULE on the completion timestamp
instead of on the old `DUE`, then writes the resulting `DUE` back. Time-of-day
is preserved from the original `DUE`, and `DTSTART` (when present) is shifted by
the same delta so its offset to `DUE` stays intact.

The tag name is configurable per connection in the config flow and the
reconfigure flow (`from_completion_tag`), so you can use e.g. a Dutch tag.
Matching ignores case and surrounding whitespace. Leave it blank to disable the
feature entirely. Untagged tasks keep standard RFC 5545 behaviour, so
calendar-anchored and completion-anchored chores can live in the same list.

Tagged tasks are **always** advanced client-side, even when
`server_handles_rrule` is enabled — no CalDAV server implements this behaviour.

#### Why a tag and not the Tasks.org setting?

Tasks.org has a per-task "repeat from completion date" option, but it stores it
in a local SQLite column (`repeat_from`) that is **never written to the CalDAV
server**. Its own sync code (`iCalendar.applyLocal` / `Task.applyRemote`) leaves
the field out entirely, so a second phone syncing the same calendar silently
falls back to "repeat from due date". The tag convention used here is genuinely
distributed: every client — Tasks.org, Nextcloud Tasks, Home Assistant — sees
the same `CATEGORIES` value.

> **Legacy `FROM=COMPLETION`.** Very old Tasks.org databases stored the flag as
> a non-standard `FROM=COMPLETION` part inside the RRULE. The integration still
> understands that part (and strips it before parsing, since `dateutil` rejects
> it) but it never *writes* one: modern Tasks.org passes such a rule straight to
> its RRULE parser, which throws and causes the recurrence to be dropped. An
> explicit `FROM=` part in the RRULE takes precedence over the tag.

## Entity

Each CalDAV calendar with VTODOs produces one `todo.*` entity:

| Attribute | Value |
|---|---|
| Platform | `todo` |
| Unique ID | `familyboard_caldav_{connection}_{calendar}` |
| Device | Service-type device per CalDAV connection |
| Supported features | `CREATE`, `UPDATE`, `DELETE`, `SET_DUE_DATE`, `SET_DUE_DATETIME`, `SET_DESCRIPTION` |

### Standard HA todo API

These methods map to the HA todo UI and automations:

| Method | Behavior |
|---|---|
| `async_create_todo_item` | Create a VTODO with summary, due, description |
| `async_update_todo_item` | Update fields; completing a recurring task advances RRULE |
| `async_delete_todo_items` | Delete VTODOs by UID |

### Extended VTODO API

For full RFC 5545 control (used by FamilyBoard and advanced automations):

| Method | Behavior |
|---|---|
| `async_create_vtodo` | Create with all fields: due, dtstart, description, priority, percent_complete, location, url, categories |
| `async_update_vtodo` | Update any combination of fields; sentinel (`...`) means "don't touch" |

### `extra_state_attributes`

The entity exposes a `vtodo_items` attribute containing the full parsed VTODO
data for every item in the calendar — fields not representable in HA's
`TodoItem` (rrule, priority, percent_complete, location, url, categories,
dtstart, completed) are preserved here.

## Configuration

### Config flow

1. **Settings → Devices & Services → Add Integration → FamilyBoard CalDAV**
2. Enter:
   - CalDAV server URL
   - Username / Password
   - (optional) Display name
   - Verify SSL (default: on)
   - Server handles RRULE (default: off)
3. The integration tests the connection, discovers calendars, and creates
   one `todo.*` entity per calendar.

### Reconfigure

Settings → Devices & Services → FamilyBoard CalDAV → Configure. Change URL,
credentials, SSL, or RRULE mode. The entry reloads automatically.

## Installation

### HACS (recommended)

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/apiest/ha-familyboard-caldav` as an Integration
3. Install **FamilyBoard CalDAV**
4. Restart Home Assistant

### Manual

Copy `custom_components/familyboard_caldav/` to your HA config's
`custom_components/` directory and restart.

## Testing

```bash
pip install -r requirements_test.txt
pytest
```

Test files:

- `test_caldav_client.py` — VTODO parsing, RRULE advancement (daily, weekly,
  monthly, count, until, date-only, exhaustion), `_advance_rrule` edge cases.
- `test_todo.py` — entity identity, `_to_ha_item` conversion, extra attributes,
  todo_items property, create/update/delete/complete flows, extended VTODO API.

## Design principles

- **Standalone** — no dependency on FamilyBoard; usable with any HA automation.
- **RFC 5545 faithful** — all VTODO fields preserved; RRULE advancement follows
  the spec (DTSTART anchored, DUE advanced, COUNT/UNTIL respected).
- **HA Gold standard** — `DataUpdateCoordinator`, `runtime_data`, typed config
  entry, `CoordinatorEntity`, `DeviceInfo`, `ConfigEntryNotReady`, diagnostics.
- **No blocking I/O** — all CalDAV operations run in the executor.
- **No YAML config** — UI config flow + reconfigure only.
