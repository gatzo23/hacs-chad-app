import logging
import aiohttp
import os
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_URL, CONF_TOKEN, CONF_ROOM_ID

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Chad App from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    url = entry.data[CONF_URL]
    token = entry.data.get(CONF_TOKEN)
    room_id = entry.data[CONF_ROOM_ID]

    # Store configuration
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_URL: url,
        CONF_TOKEN: token,
        CONF_ROOM_ID: room_id
    }

    session = async_get_clientsession(hass)

    async def send_message(call: ServiceCall):
        """Service to send a text message."""
        text = call.data.get("text")
        
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = {
            "room": room_id,
            "sender": "Home Assistant",
            "text": text,
            "type": "text"
        }

        try:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status not in (200, 201, 204):
                    _LOGGER.error("Failed to send message: %s", await response.text())
        except Exception as e:
            _LOGGER.error("Error sending message: %s", e)

    async def send_photo(call: ServiceCall):
        """Service to send a photo."""
        text = call.data.get("text", "")
        file_path = call.data.get("path")

        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        if not os.path.exists(file_path):
            _LOGGER.error("File not found: %s", file_path)
            return

        try:
            data = aiohttp.FormData()
            data.add_field("text", text)
            data.add_field("sender", "Home Assistant")
            data.add_field("room", room_id)
            data.add_field("type", "image")
            
            with open(file_path, "rb") as f:
                data.add_field("file", f, filename=os.path.basename(file_path))
                
                async with session.post(url, data=data, headers=headers) as response:
                    if response.status not in (200, 201, 204):
                        _LOGGER.error("Failed to send photo: %s", await response.text())
        except Exception as e:
            _LOGGER.error("Error sending photo: %s", e)

    # Register services
    hass.services.async_register(DOMAIN, "send_message", send_message)
    hass.services.async_register(DOMAIN, "send_photo", send_photo)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN].pop(entry.entry_id)
    # Removing services if this is the last entry
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, "send_message")
        hass.services.async_remove(DOMAIN, "send_photo")

    return True
