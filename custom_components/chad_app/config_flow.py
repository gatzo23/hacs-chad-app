import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import (
    DOMAIN,
    CONF_URL,
    CONF_TOKEN,
    CONF_ROOM_ID,
    CONF_BOT_ID,
    CONF_TARGET_CONTACTS,
    CONF_ENCRYPTION_KEY,
)

class ChadAppConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chad App / Adlos."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            return self.async_create_entry(title="Adlos / Chad App", data=user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_URL, default="https://pocket.nextbee.org/api/collections/messages/records"): str,
            vol.Optional(CONF_BOT_ID, default="homeassistant_bot"): str,
            vol.Optional(CONF_TARGET_CONTACTS, default=""): str,
            vol.Optional(CONF_ROOM_ID, default="homeassistant_bot"): str,
            vol.Optional(CONF_TOKEN): str,
            vol.Optional(CONF_ENCRYPTION_KEY): str,
        })

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return ChadAppOptionsFlowHandler(config_entry)


class ChadAppOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Chad App / Adlos options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_contacts = self.config_entry.options.get(
            CONF_TARGET_CONTACTS,
            self.config_entry.data.get(CONF_TARGET_CONTACTS, "")
        )
        current_bot_id = self.config_entry.options.get(
            CONF_BOT_ID,
            self.config_entry.data.get(CONF_BOT_ID, "homeassistant_bot")
        )
        current_key = self.config_entry.options.get(
            CONF_ENCRYPTION_KEY,
            self.config_entry.data.get(CONF_ENCRYPTION_KEY, "")
        )

        options_schema = vol.Schema({
            vol.Optional(CONF_TARGET_CONTACTS, default=current_contacts): str,
            vol.Optional(CONF_BOT_ID, default=current_bot_id): str,
            vol.Optional(CONF_ENCRYPTION_KEY, default=current_key): str,
        })

        return self.async_show_form(
            step_id="init", data_schema=options_schema
        )

