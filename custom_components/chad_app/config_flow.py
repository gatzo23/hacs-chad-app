"""Config and Options Flow for Adlos / Chad App integration."""

import os
import io
import time
import json
import base64
import secrets
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.components import persistent_notification

from .const import (
    DOMAIN,
    DEFAULT_SERVER_URL,
    DEFAULT_BOT_NAME,
    CONF_SERVER_URL,
    CONF_BOT_NAME,
    CONF_BOT_ID,
    CONF_PAIRED_USERS,
    CONF_ROOM_ID,
    CONF_TARGET_CONTACTS,
    CONF_URL,
)
from .pocketbase_listener import get_clean_base_url


def generate_bot_id() -> str:
    """Generates a persistent 15-character bot ID (ha_ + 12 hex characters)."""
    return f"ha_{secrets.token_hex(6)}"


def generate_qr_code(hass, text: str) -> tuple[str, str]:
    """Generates QR code PNG and returns local HA URL and base64 data URI."""
    try:
        import qrcode
        img = qrcode.make(text)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        data_uri = f"data:image/png;base64,{b64}"

        www_dir = hass.config.path("www")
        os.makedirs(www_dir, exist_ok=True)
        img_path = os.path.join(www_dir, "adlos_qr.png")
        img.save(img_path)
        local_url = f"/local/adlos_qr.png?t={int(time.time())}"
        return local_url, data_uri
    except Exception:
        return "", ""


class ChadAppConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Adlos."""
    VERSION = 1

    def __init__(self):
        """Initialize config flow."""
        self._user_input: dict = {}
        self._bot_id: str = ""

    async def async_step_user(self, user_input=None):
        """Step 1: Configuration of server and bot name."""
        errors = {}

        if user_input is not None:
            server_url = get_clean_base_url(user_input.get(CONF_SERVER_URL, DEFAULT_SERVER_URL))
            bot_name = (user_input.get(CONF_BOT_NAME) or DEFAULT_BOT_NAME).strip()
            bot_id = generate_bot_id()

            self._user_input = {
                CONF_SERVER_URL: server_url,
                CONF_URL: server_url,
                CONF_BOT_NAME: bot_name,
                CONF_BOT_ID: bot_id,
                CONF_ROOM_ID: bot_id,
                CONF_PAIRED_USERS: {},
                CONF_TARGET_CONTACTS: "",
            }
            self._bot_id = bot_id
            return await self.async_step_pair()

        data_schema = vol.Schema({
            vol.Required(CONF_SERVER_URL, default=DEFAULT_SERVER_URL): str,
            vol.Required(CONF_BOT_NAME, default=DEFAULT_BOT_NAME): str,
        })

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_pair(self, user_input=None):
        """Step 2: Display QR Code for instant pairing with Adlos App."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"Adlos ({self._user_input.get(CONF_BOT_NAME, DEFAULT_BOT_NAME)})",
                data=self._user_input,
            )

        bot_id = self._user_input.get(CONF_BOT_ID, self._bot_id)
        bot_name = self._user_input.get(CONF_BOT_NAME, DEFAULT_BOT_NAME)
        server_url = self._user_input.get(CONF_SERVER_URL, DEFAULT_SERVER_URL)

        # Native Adlos contact QR code format
        qr_payload = json.dumps({
            "action": "adlos_contact",
            "id": bot_id,
            "name": bot_name,
            "home_server": server_url,
        })

        local_url, data_uri = generate_qr_code(self.hass, qr_payload)

        # Create persistent notification in HA
        try:
            notification_msg = (
                f"### 📱 Adlos App Kopplung\n\n"
                f"Scanne diesen QR-Code in deiner Adlos-App unter **'Kontakt hinzufügen'**:\n\n"
                f"![QR-Code]({local_url})\n\n"
                f"- **Bot-ID:** `{bot_id}`\n"
                f"- **Name:** `{bot_name}`\n"
                f"- **Server:** `{server_url}`\n\n"
                f"```json\n{qr_payload}\n```"
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
                "bot_id": bot_id,
                "bot_name": bot_name,
                "server_url": server_url,
                "qr_image": f"![QR-Code]({local_url})" if local_url else "",
                "qr_payload": qr_payload,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return ChadAppOptionsFlowHandler(config_entry)


class ChadAppOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Adlos options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage Adlos options and show QR Code."""
        if user_input is not None:
            server_url = get_clean_base_url(user_input.get(CONF_SERVER_URL, DEFAULT_SERVER_URL))
            bot_name = (user_input.get(CONF_BOT_NAME) or DEFAULT_BOT_NAME).strip()

            new_options = dict(self.config_entry.options)
            new_options[CONF_SERVER_URL] = server_url
            new_options[CONF_BOT_NAME] = bot_name

            # Keep existing bot_id
            bot_id = self.config_entry.data.get(CONF_BOT_ID) or self.config_entry.options.get(CONF_BOT_ID)
            if bot_id:
                new_options[CONF_BOT_ID] = bot_id

            return self.async_create_entry(title="", data=new_options)

        bot_id = (
            self.config_entry.options.get(CONF_BOT_ID)
            or self.config_entry.data.get(CONF_BOT_ID)
            or "homeassistant_bot"
        )
        bot_name = (
            self.config_entry.options.get(CONF_BOT_NAME)
            or self.config_entry.data.get(CONF_BOT_NAME)
            or DEFAULT_BOT_NAME
        )
        server_url = (
            self.config_entry.options.get(CONF_SERVER_URL)
            or self.config_entry.data.get(CONF_SERVER_URL)
            or DEFAULT_SERVER_URL
        )

        qr_payload = json.dumps({
            "action": "adlos_contact",
            "id": bot_id,
            "name": bot_name,
            "home_server": server_url,
        })
        local_url, _ = generate_qr_code(self.hass, qr_payload)

        paired_users = self.config_entry.options.get(
            CONF_PAIRED_USERS,
            self.config_entry.data.get(CONF_PAIRED_USERS, {})
        )
        users_count = len(paired_users) if isinstance(paired_users, dict) else 0

        options_schema = vol.Schema({
            vol.Required(CONF_SERVER_URL, default=server_url): str,
            vol.Required(CONF_BOT_NAME, default=bot_name): str,
        })

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            description_placeholders={
                "bot_id": bot_id,
                "server_url": server_url,
                "users_count": str(users_count),
                "qr_image": f"![QR-Code]({local_url})" if local_url else "",
            },
        )
