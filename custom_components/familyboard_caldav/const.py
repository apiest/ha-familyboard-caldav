"""Constants for the FamilyBoard CalDAV integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "familyboard_caldav"

UPDATE_INTERVAL = timedelta(minutes=5)

# CATEGORIES tag marking a task that recurs from its completion date rather
# than from its previous DUE date. Tasks.org keeps this flag in a local DB
# column that is never synced, so a category is the only portable carrier.
CONF_FROM_COMPLETION_TAG = "from_completion_tag"
DEFAULT_FROM_COMPLETION_TAG = "from-completion"
