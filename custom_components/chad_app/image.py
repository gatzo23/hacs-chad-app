"""Image platform for Adlos pairing QR code."""
from __future__ import annotations

import io
import json
import logging
import qrcode

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    DEFAULT_SERVER_URL,
    DEFAULT_BOT_NAME,
    CONF_SERVER_URL,
    CONF_BOT_NAME,
    CONF_BOT_ID,
    CONF_URL,
)
from .pocketbase_listener import get_clean_base_url

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Adlos QR code image entity."""
    async_add_entities([AdlosQRImageEntity(hass, entry)], update_before_add=True)


class AdlosQRImageEntity(ImageEntity):
    """Representation of the Adlos Pairing QR Code."""

    _attr_has_entity_name = True
    _attr_name = "Kopplungs-QR-Code"
    _attr_icon = "mdi:qrcode-scan"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the image entity."""
        super().__init__(hass)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pairing_qr"

    def image(self) -> bytes | None:
        """Return bytes of image."""
        try:
            bot_id = (
                self._entry.options.get(CONF_BOT_ID)
                or self._entry.data.get(CONF_BOT_ID)
                or "homeassistant_bot"
            )
            bot_name = (
                self._entry.options.get(CONF_BOT_NAME)
                or self._entry.data.get(CONF_BOT_NAME)
                or DEFAULT_BOT_NAME
            )
            raw_url = (
                self._entry.options.get(CONF_SERVER_URL)
                or self._entry.data.get(CONF_SERVER_URL)
                or self._entry.options.get(CONF_URL)
                or self._entry.data.get(CONF_URL)
                or DEFAULT_SERVER_URL
            )
            server_url = get_clean_base_url(raw_url)

            payload = json.dumps({
                "action": "adlos_contact",
                "id": bot_id,
                "name": bot_name,
                "home_server": server_url,
            })

            img = qrcode.make(payload)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as err:
            _LOGGER.error("Failed to generate Adlos QR image: %s", err)
            return None
