import logging
import aiohttp
import os
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_URL, CONF_TOKEN, CONF_ROOM_ID

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Chad App / Adlos from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    url = entry.data.get(CONF_URL, "http://192.168.178.74:8090/api/collections/messages/records")
    token = entry.data.get(CONF_TOKEN)
    room_id = entry.data.get(CONF_ROOM_ID, "homeassistant_bot")

    # Store configuration
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_URL: url,
        CONF_TOKEN: token,
        CONF_ROOM_ID: room_id
    }

    session = async_get_clientsession(hass)

    async def send_message(call: ServiceCall):
        """Service to send a text message to PocketBase REST API."""
        text = call.data.get("text") or call.data.get("message") or call.data.get("content") or call.data.get("payload") or ""
        target_room = call.data.get("room") or call.data.get("target") or room_id

        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = {
            "room": target_room,
            "sender": "Home Assistant",
            "text": text,
            "type": "text"
        }

        try:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status not in (200, 201, 204):
                    _LOGGER.error("Failed to send message: %s", await response.text())
                else:
                    _LOGGER.info("Message successfully posted to PocketBase REST API: %s", text)
        except Exception as e:
            _LOGGER.error("Error sending message: %s", e)

    async def send_photo(call: ServiceCall):
        """Service to send a photo to PocketBase REST API."""
        text = call.data.get("text") or call.data.get("message") or call.data.get("caption") or ""
        file_path = call.data.get("path") or call.data.get("file_path") or call.data.get("image")
        target_room = call.data.get("room") or call.data.get("target") or room_id

        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        if not file_path or not os.path.exists(file_path):
            _LOGGER.error("File not found for send_photo: %s", file_path)
            return

        try:
            data = aiohttp.FormData()
            data.add_field("text", text)
            data.add_field("sender", "Home Assistant")
            data.add_field("room", target_room)
            data.add_field("type", "image")
            
            with open(file_path, "rb") as f:
                data.add_field("file", f, filename=os.path.basename(file_path))
                
                async with session.post(url, data=data, headers=headers) as response:
                    if response.status not in (200, 201, 204):
                        _LOGGER.error("Failed to send photo: %s", await response.text())
        except Exception as e:
            _LOGGER.error("Error sending photo: %s", e)

    # Register services under chad_app domain
    hass.services.async_register(DOMAIN, "send_message", send_message)
    hass.services.async_register(DOMAIN, "send_photo", send_photo)

    # Register aliases so adlos.send_message, adlos.send_photo, and notify.adlos work out of the box in automations
    hass.services.async_register("adlos", "send_message", send_message)
    hass.services.async_register("adlos", "send_photo", send_photo)
    hass.services.async_register("notify", "adlos", send_message)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN].pop(entry.entry_id, None)
    if not hass.data[DOMAIN]:
        for s in ["send_message", "send_photo"]:
            try:
                hass.services.async_remove(DOMAIN, s)
            except Exception:
                pass
            try:
                hass.services.async_remove("adlos", s)
            except Exception:
                pass
        try:
            hass.services.async_remove("notify", "adlos")
        except Exception:
            pass

    return True

