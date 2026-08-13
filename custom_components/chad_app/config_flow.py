import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, CONF_URL, CONF_TOKEN, CONF_ROOM_ID

class ChadAppConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chad App."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            return self.async_create_entry(title="Chad App", data=user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_URL, default="https://pocket.nextbee.org/api/collections/messages/records"): str,
            vol.Required(CONF_ROOM_ID, default="homeassistant_bot"): str,
            vol.Optional(CONF_TOKEN): str,
        })

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )
