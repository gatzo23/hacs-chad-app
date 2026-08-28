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

from .const import DOMAIN, CONF_HA_URL, CONF_TOKEN

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
            ha_url = str(self._entry.data.get(CONF_HA_URL) or "https://homey.org").strip().rstrip("/")
            if not ha_url.startswith("http://") and not ha_url.startswith("https://"):
                ha_url = f"https://{ha_url}"
            ha_token = str(self._entry.data.get(CONF_TOKEN) or "").strip()

            payload = json.dumps({
                "type": "adlos_ha",
                "url": ha_url,
                "token": ha_token,
                "webhook_id": "adlos_pairing",
            })

            img = qrcode.make(payload)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as err:
            _LOGGER.error("Failed to generate Adlos QR image: %s", err)
            return None
