# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-09-21

### Added
- **Repeat from completion date.** Tagging a task with `from-completion` (the
  tag name is configurable per connection) makes it recur relative to when it
  was ticked off instead of relative to its previous `DUE` date. The tag
  travels in the VTODO's `CATEGORIES` property, so it is visible to every
  client — unlike Tasks.org's own "repeat from completion" setting, which
  lives in a device-local database column and is never synced. Tagged tasks
  are always advanced client-side, even when `server_handles_rrule` is
  enabled, since no CalDAV server implements this behaviour.
- Support for Tasks.org's legacy non-standard `FROM=COMPLETION` RRULE part,
  which is recognised as a fallback for older items. An explicit `FROM=` part
  takes precedence over the tag. The integration never writes one back.

### Fixed
- Completing a task whose RRULE contained `FROM=COMPLETION` or `FROM=DUE`
  raised `ValueError: unknown parameter 'FROM'` from `dateutil` and left the
  task unchanged. The part is now split off before parsing and preserved on
  save so Tasks.org keeps working.
- Invalid recurrence rules or missing recurrence anchors now reject completion
  without saving, instead of marking the task completed without advancing.
- Completion always uses the server-backed recurrence path, including cache
  misses. Already-completed server tasks are left unchanged.
- Successful client-side recurring completions emit an HA event so FamilyBoard
  0.4.1 can credit an occurrence whose task UID remains unchanged.

## [0.1.0] - 2026-05-17

### Added
- Standalone CalDAV integration for Home Assistant, split from FamilyBoard.
- CalDAV connection config flow with URL, username, password, and
  calendar selection.
- RFC 5545-compliant VTODO handling: `DTSTART`, `DUE`, `COMPLETED`,
  `PRIORITY`, `PERCENT-COMPLETE`, `LOCATION`, `URL`, `CATEGORIES`,
  `RRULE`, `DESCRIPTION` preserved in `extra_state_attributes.vtodo_items`.
- Recurring task completion that advances `DUE` to the next RRULE
  occurrence instead of marking done. Supports `FREQ=DAILY`, `WEEKLY`,
  `MONTHLY`, `YEARLY`, `BYDAY`, `INTERVAL`, `COUNT`, `UNTIL`.
- `server_handles_rrule` toggle for servers that manage recurrence
  themselves (e.g. Exchange).
- `todo.*` entities compatible with FamilyBoard's `chores:` /
  `shared_chores:` configuration.
