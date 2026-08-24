"""Config flow for FamilyBoard CalDAV integration."""

from __future__ import annotations

import logging
from typing import Any

import caldav
from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import voluptuous as vol

from .const import CONF_FROM_COMPLETION_TAG, DEFAULT_FROM_COMPLETION_TAG, DOMAIN

_LOGGER = logging.getLogger(__name__)


class FamilyBoardCalDAVConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FamilyBoard CalDAV."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input["url"]
            username = user_input["username"]
            password = user_input["password"]
            verify_ssl = user_input.get("verify_ssl", True)

            # Test the connection
            try:
                await self.hass.async_add_executor_job(
                    self._test_connection, url, username, password, verify_ssl
                )
            except Exception:
                _LOGGER.exception("Failed to connect to CalDAV server %s", url)
                errors["base"] = "cannot_connect"
            else:
                title = user_input.get("name") or f"{username}@{url}"
                await self.async_set_unique_id(f"{url}#{username}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema(
            {
                vol.Required("url"): selector.TextSelector(
                    selector.TextSelectorConfig(type="url")
                ),
                vol.Required("username"): selector.TextSelector(),
                vol.Required("password"): selector.TextSelector(
                    selector.TextSelectorConfig(type="password")
                ),
                vol.Optional("name"): selector.TextSelector(),
                vol.Optional("verify_ssl", default=True): selector.BooleanSelector(),
                vol.Optional(
                    "server_handles_rrule", default=False
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_FROM_COMPLETION_TAG, default=DEFAULT_FROM_COMPLETION_TAG
                ): selector.TextSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def _test_connection(
        url: str, username: str, password: str, verify_ssl: bool
    ) -> None:
        """Test the CalDAV connection (sync, runs in executor)."""
        client = caldav.DAVClient(
            url=url,
            username=username,
            password=password,
            ssl_verify_cert=verify_ssl,
        )
        principal = client.principal()
        principal.calendars()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        existing = dict(entry.data)

        if user_input is not None:
            url = user_input["url"]
            username = user_input["username"]
            password = user_input["password"]
            verify_ssl = user_input.get("verify_ssl", True)

            try:
                await self.hass.async_add_executor_job(
                    self._test_connection, url, username, password, verify_ssl
                )
            except Exception:
                _LOGGER.exception("Failed to connect to CalDAV server %s", url)
                errors["base"] = "cannot_connect"
            else:
                title = user_input.get("name") or url
                return self.async_update_reload_and_abort(
                    entry, title=title, data=user_input
                )

        d = existing
        schema = vol.Schema(
            {
                vol.Required("url", default=d.get("url", "")): selector.TextSelector(
                    selector.TextSelectorConfig(type="url")
                ),
                vol.Required(
                    "username", default=d.get("username", "")
                ): selector.TextSelector(),
                vol.Required(
                    "password", default=d.get("password", "")
                ): selector.TextSelector(selector.TextSelectorConfig(type="password")),
                vol.Optional(
                    "name",
                    description={"suggested_value": d.get("name", "")},
                ): selector.TextSelector(),
                vol.Optional(
                    "verify_ssl", default=d.get("verify_ssl", True)
                ): selector.BooleanSelector(),
                vol.Optional(
                    "server_handles_rrule",
                    default=d.get("server_handles_rrule", False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_FROM_COMPLETION_TAG,
                    default=d.get(
                        CONF_FROM_COMPLETION_TAG, DEFAULT_FROM_COMPLETION_TAG
                    ),
                ): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )
