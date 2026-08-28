import json
import base64
import io
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.network import get_url
from .const import (
    DOMAIN,
    CONF_URL,
    CONF_TOKEN,
    CONF_ROOM_ID,
    CONF_BOT_ID,
    CONF_TARGET_CONTACTS,
    CONF_ENCRYPTION_KEY,
)


def make_qr_svg_data_uri(text: str) -> str:
    """Generates an SVG QR-Code data URI."""
    try:
        import qrcode
        import qrcode.image.svg
        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(text, image_factory=factory)
        buf = io.BytesIO()
        img.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{b64}"
    except Exception:
        return ""


class ChadAppConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chad App / Adlos (exakt wie in v17 mit QR-Code)."""
    VERSION = 1

    def __init__(self):
        """Initialize config flow."""
        self._user_input = {}

    async def async_step_user(self, user_input=None):
        """Handle the initial step: HA URL, Token, PocketBase URL und room_id."""
        errors = {}

        if user_input is not None:
            self._user_input = user_input
            return await self.async_step_pair()

        try:
            default_ha_url = get_url(self.hass, allow_internal=True, allow_external=True)
        except Exception:
            default_ha_url = "https://homey.org"

        data_schema = vol.Schema({
            vol.Required(CONF_HA_URL, default=default_ha_url): str,
            vol.Optional(CONF_TOKEN, default=""): str,
            vol.Required(CONF_URL, default="https://pocket.nextbee.org/api/collections/messages/records"): str,
            vol.Required(CONF_ROOM_ID, default="homeassistant_bot"): str,
        })

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_pair(self, user_input=None):
        """Step 2: Show QR Code pairing screen with user-specified HA URL and Token."""
        if user_input is not None:
            return self.async_create_entry(title="Adlos / Chad App", data=self._user_input)

        raw_ha_url = (self._user_input.get(CONF_HA_URL) or "").strip()
        if raw_ha_url:
            if not raw_ha_url.startswith("http://") and not raw_ha_url.startswith("https://"):
                ha_url = f"https://{raw_ha_url}"
            else:
                ha_url = raw_ha_url
            ha_url = ha_url.rstrip("/")
        else:
            try:
                ha_url = get_url(self.hass, allow_internal=True, allow_external=True)
            except Exception:
                ha_url = "https://homey.org"

        token = (self._user_input.get(CONF_TOKEN) or "").strip()
        if not token:
            token = "adlos_ha_access"

        pairing_payload = json.dumps({
            "type": "adlos_ha",
            "url": ha_url,
            "token": token,
            "webhook_id": "adlos_pairing",
        })

        qr_data_uri = make_qr_svg_data_uri(pairing_payload)
        description = (
            "### 📱 Scanne diesen QR-Code mit der Adlos App:\n\n"
            f"![QR-Code]({qr_data_uri})\n\n"
            f"**Home Assistant URL:** `{ha_url}`\n\n"
            f"**Token:** `{token}`\n\n"
            "Klicke auf **Abschließen**, wenn du den Code gescannt hast."
        )

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({}),
            description_placeholders={"qr_description": description},
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

        current_bot_id = self.config_entry.options.get(
            CONF_BOT_ID,
            self.config_entry.data.get(CONF_BOT_ID, "homeassistant_bot")
        )

        options_schema = vol.Schema({
            vol.Optional(CONF_BOT_ID, default=current_bot_id): str,
        })

        return self.async_show_form(
            step_id="init", data_schema=options_schema
        )


