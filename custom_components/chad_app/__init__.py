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
        data = call.data
        extra_data = data.get("data") if isinstance(data.get("data"), dict) else {}

        raw_text = (
            data.get("message")
            or data.get("text")
            or data.get("content")
            or data.get("payload")
            or extra_data.get("message")
            or extra_data.get("text")
            or ""
        )

        title = data.get("title") or extra_data.get("title")
        if title and raw_text and not raw_text.startswith(title):
            text = f"{title}\n{raw_text}"
        elif title and not raw_text:
            text = str(title)
        else:
            text = str(raw_text)

        target = data.get("room") or data.get("target") or extra_data.get("room") or extra_data.get("target")
        if isinstance(target, list) and len(target) > 0:
            target_room = str(target[0])
        elif target:
            target_room = str(target)
        else:
            target_room = room_id

        raw_base_url = (url or "").strip()
        if "beeserver.org" in raw_base_url and "pocket" not in raw_base_url:
            base_url = "https://pocket.nextbee.org"
        else:
            base_url = raw_base_url or "https://pocket.nextbee.org"

        if "records" in base_url:
            target_url = base_url
        elif base_url.startswith(("http://", "https://")):
            target_url = f"{base_url.rstrip('/')}/api/collections/messages/records"
        else:
            target_url = "https://pocket.nextbee.org/api/collections/messages/records"

        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = {
            "room": target_room,
            "sender": "Home Assistant",
            "text": text,
            "type": "text"
        }

        _LOGGER.warning("ADLOS_REST: Sending message to %s (room=%s): %s", target_url, target_room, text)

        candidate_urls = [
            target_url,
            "https://pocket.nextbee.org/api/collections/messages/records",
            "http://192.168.178.74:8090/api/collections/messages/records",
        ]
        candidate_urls = list(dict.fromkeys(candidate_urls))

        success = False
        for post_url in candidate_urls:
            try:
                async with session.post(post_url, json=payload, headers=headers, timeout=10) as response:
                    resp_body = await response.text()
                    if response.status not in (200, 201, 204):
                        _LOGGER.error("ADLOS_REST ERROR (HTTP %s) via %s: %s", response.status, post_url, resp_body)
                    else:
                        _LOGGER.warning("ADLOS_REST SUCCESS (HTTP %s) via %s: %s", response.status, post_url, resp_body)
                        success = True
                        break
            except Exception as e:
                _LOGGER.error("ADLOS_REST EXCEPTION posting to %s: %s", post_url, e)

        if not success:
            _LOGGER.error("ADLOS_REST: Failed to send message to all candidate URLs: %s", candidate_urls)

    async def send_photo(call: ServiceCall):
        """Service to send a photo to PocketBase REST API."""
        data = call.data
        extra_data = data.get("data") if isinstance(data.get("data"), dict) else {}

        raw_text = (
            data.get("text")
            or data.get("message")
            or data.get("caption")
            or extra_data.get("caption")
            or extra_data.get("message")
            or ""
        )
        title = data.get("title") or extra_data.get("title")
        if title and raw_text and not raw_text.startswith(title):
            text = f"{title}\n{raw_text}"
        elif title and not raw_text:
            text = str(title)
        else:
            text = str(raw_text)

        file_path = (
            data.get("path")
            or data.get("file_path")
            or data.get("image")
            or extra_data.get("path")
            or extra_data.get("file_path")
            or extra_data.get("image")
        )
        target = data.get("room") or data.get("target") or extra_data.get("room") or extra_data.get("target")
        if isinstance(target, list) and len(target) > 0:
            target_room = str(target[0])
        elif target:
            target_room = str(target)
        else:
            target_room = room_id

        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        if not file_path or not os.path.exists(file_path):
            _LOGGER.error("ADLOS_REST ERROR: File not found for send_photo: %s", file_path)
            return

        _LOGGER.warning("ADLOS_REST: Sending photo to %s (room=%s, file=%s): %s", url, target_room, file_path, text)

        try:
            form_data = aiohttp.FormData()
            form_data.add_field("text", text)
            form_data.add_field("sender", "Home Assistant")
            form_data.add_field("room", target_room)
            form_data.add_field("type", "image")
            
            with open(file_path, "rb") as f:
                form_data.add_field("file", f, filename=os.path.basename(file_path))
                
                async with session.post(url, data=form_data, headers=headers) as response:
                    resp_body = await response.text()
                    if response.status not in (200, 201, 204):
                        _LOGGER.error("ADLOS_REST ERROR (HTTP %s): %s", response.status, resp_body)
                    else:
                        _LOGGER.warning("ADLOS_REST SUCCESS (HTTP %s): %s", response.status, resp_body)
        except Exception as e:
            _LOGGER.error("ADLOS_REST EXCEPTION: %s", e)

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

