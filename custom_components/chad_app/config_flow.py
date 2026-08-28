import os
import time
import json
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.components import persistent_notification
from .const import (
    DOMAIN,
    CONF_URL,
    CONF_TOKEN,
    CONF_ROOM_ID,
    CONF_BOT_ID,
    CONF_TARGET_CONTACTS,
    CONF_ENCRYPTION_KEY,
    CONF_HA_URL,
)


def normalize_pocketbase_url(raw_url: str) -> str:
    """Normalizes PocketBase URL by automatically appending /api/collections/messages/records."""
    url = (raw_url or "").strip()
    if not url:
        return "https://pocket.nextbee.org/api/collections/messages/records"
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"
    url = url.rstrip("/")
    if url.endswith("/api/collections/messages/records") or url.endswith("/records"):
        return url
    if url.endswith("/api/collections/messages"):
        return f"{url}/records"
    if url.endswith("/api"):
        return f"{url}/collections/messages/records"
    return f"{url}/api/collections/messages/records"


def save_qr_code_image(hass, text: str) -> str:
    """Saves QR code image to HA www directory so it can be rendered reliably via /local/adlos_qr.png."""
    try:
        import qrcode
        img = qrcode.make(text)
        www_dir = hass.config.path("www")
        os.makedirs(www_dir, exist_ok=True)
        img_path = os.path.join(www_dir, "adlos_qr.png")
        img.save(img_path)
        return f"/local/adlos_qr.png?t={int(time.time())}"
    except Exception:
        return ""


class ChadAppConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Chad App / Adlos."""
    VERSION = 1

    def __init__(self):
        """Initialize config flow."""
        self._user_input = {}

    async def async_step_user(self, user_input=None):
        """Handle the initial step: all fields empty by default."""
        errors = {}

        if user_input is not None:
            # Normalize PocketBase URL
            raw_pb_url = user_input.get(CONF_URL, "")
            user_input[CONF_URL] = normalize_pocketbase_url(raw_pb_url)
            
            # Default room_id fallback if left blank
            if not user_input.get(CONF_ROOM_ID, "").strip():
                user_input[CONF_ROOM_ID] = "homeassistant_bot"

            self._user_input = user_input
            return await self.async_step_pair()

        data_schema = vol.Schema({
            vol.Required(CONF_HA_URL, default=""): str,
            vol.Optional(CONF_TOKEN, default=""): str,
            vol.Required(CONF_URL, default=""): str,
            vol.Optional(CONF_ROOM_ID, default=""): str,
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
            ha_url = "https://homey.org"

        token = (self._user_input.get(CONF_TOKEN) or "").strip()

        pairing_payload = json.dumps({
            "type": "adlos_ha",
            "url": ha_url,
            "token": token,
            "webhook_id": "adlos_pairing",
        })

        qr_img_url = save_qr_code_image(self.hass, pairing_payload)

        # Also create a persistent notification in HA
        try:
            notification_msg = (
                f"### 📱 Adlos App Kopplung\n\n"
                f"![QR-Code]({qr_img_url})\n\n"
                f"**Home Assistant URL:** `{ha_url}`\n\n"
                f"**Token:** `{token}`\n\n"
                f"**JSON-Payload:**\n```json\n{pairing_payload}\n```"
            )
            persistent_notification.async_create(
                self.hass,
                notification_msg,
                title="Adlos QR-Code",
                notification_id="adlos_pairing_qr",
            )
        except Exception:
            pass

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({}),
            description_placeholders={
                "ha_url": ha_url,
                "token": token if token else "Kein Token angegeben",
                "qr_image": f"![QR-Code]({qr_img_url})" if qr_img_url else "",
                "pairing_payload": pairing_payload,
            },
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


