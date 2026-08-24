# Copilot instructions — FamilyBoard CalDAV

Home Assistant custom integration (`custom_components/familyboard_caldav/`) that
connects to a CalDAV server and exposes each calendar as a `TodoListEntity`.
HA Gold quality standard. Target HA: 2026.4+.

## Ecosystem

This repo is part of a multi-repo family:

| Repo | Domain | Purpose |
|---|---|---|
| ha-familyboard | `familyboard` | Main family dashboard — consumes `todo.*` entities from this integration |
| **ha-familyboard-caldav** (this) | `familyboard_caldav` | CalDAV todo-list sync |
| ha-parcel | `parcel` | Standalone parcel tracking |
| ha-postnl | `postnl` | PostNL parcel provider |

Cross-repo contracts:
- This integration is **standalone** — no direct imports from any sibling.
- FamilyBoard reads the `todo.*` entities this integration creates via the HA
  todo platform. Renaming entities here breaks FamilyBoard's chore lists.
- The domain name `familyboard_caldav` is baked into entity IDs on production
  installations. Do not rename.

## Architecture (Gold standard)

- **`CalDAVCoordinator`** (`coordinator.py`) wraps `CalDAVClientManager` and
  polls every 5 minutes via `DataUpdateCoordinator`. Type alias:
  `CalDAVConfigEntry = ConfigEntry[CalDAVCoordinator]`.
- **`entry.runtime_data`** stores the coordinator — no `hass.data[DOMAIN]`.
- **`ConfigEntryNotReady`** raised when the coordinator fails initial setup.
- **`CoordinatorEntity[CalDAVCoordinator]`** base for `FamilyBoardCalDAVTodo`.
- **`DeviceInfo`** with `DeviceEntryType.SERVICE` groups all entities under one
  device per config entry.
- **`diagnostics.py`** exposes redacted config, calendar list, todo counts, and
  connection status.

## Key modules

| Module | Responsibility |
|---|---|
| `__init__.py` | Entry setup/unload, coordinator init, `ConfigEntryNotReady` |
| `coordinator.py` | `CalDAVCoordinator(DataUpdateCoordinator)`, `CalDAVConfigEntry` type alias |
| `caldav_client.py` | `CalDAVClientManager` — low-level CalDAV operations, RRULE advancement, `VTodoItem` model |
| `config_flow.py` | Config flow (URL + credentials → calendar discovery) |
| `todo.py` | `FamilyBoardCalDAVTodo(CoordinatorEntity, TodoListEntity)` — full CRUD |
| `diagnostics.py` | `async_get_config_entry_diagnostics` |
| `const.py` | Domain, update interval, default values |

## CalDAV client details

- `VTodoItem` dataclass models a VTODO. Fields use sentinel `...` (Ellipsis) to
  distinguish "not set" from `None`. This causes `type: ignore[assignment]`
  annotations throughout — they are intentional.
- RRULE advancement: when completing a recurring todo, `caldav_client.py`
  calculates the next occurrence and updates `DUE`/`DTSTART` accordingly.
- Known technical debt: bare `except Exception:` in `caldav_client.py` and
  `config_flow.py` should be narrowed to `caldav.lib.error.DAVError` and
  `requests.RequestException`.

## Testing

- `pytest` with fixtures in `tests/conftest.py`.
- `tests/test_caldav_client.py` — unit tests for CalDAV client operations.
- `tests/test_todo.py` — entity-level tests using `_make_coordinator()` helper.
- Run: `pytest` from repo root.

## Code style

Follow Home Assistant core conventions. Enforced by `ruff check` and
`ruff format --check` (config in `pyproject.toml`).

- PEP 257 docstrings on every module, class, and public function.
- Type hints on all function signatures. Use `from __future__ import annotations`.
- `snake_case`, async-first, no blocking I/O on the event loop.
- Before committing: `ruff check --fix . && ruff format .`

## Deploy

```bash
scp custom_components/familyboard_caldav/*.py \
    <user>@<ip>:./hass-config/custom_components/familyboard_caldav/
```

## Don'ts

- Don't rename the `familyboard_caldav` domain — entity IDs are baked in.
- Don't add direct dependencies on sibling repos (familyboard, parcel).
- Don't import from `homeassistant.components.*` for CalDAV — use the `caldav`
  library directly.
