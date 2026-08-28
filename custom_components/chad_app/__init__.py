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

    def _get_target_url(raw_url: str) -> str:
        raw_base_url = (raw_url or "").strip()
        if "beeserver.org" in raw_base_url and "pocket" not in raw_base_url:
            base_url = "https://pocket.nextbee.org"
        else:
            base_url = raw_base_url or "https://pocket.nextbee.org"

        if "records" in base_url:
            return base_url
        if base_url.startswith(("http://", "https://")):
            return f"{base_url.rstrip('/')}/api/collections/messages/records"
        return "https://pocket.nextbee.org/api/collections/messages/records"

    def _get_candidate_urls(target_url: str) -> list[str]:
        candidates = [
            target_url,
            "https://pocket.nextbee.org/api/collections/messages/records",
            "http://192.168.178.74:8090/api/collections/messages/records",
        ]
        return list(dict.fromkeys(candidates))

    async def _async_send_text(target_room: str, text: str) -> bool:
        target_url = _get_target_url(url)
        candidate_urls = _get_candidate_urls(target_url)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = {
            "room": target_room,
            "sender": "Home Assistant",
            "text": text,
            "type": "text",
        }

        _LOGGER.warning("ADLOS_REST: Sending message to candidate URLs (room=%s): %s", target_room, text)

        for post_url in candidate_urls:
            try:
                async with session.post(post_url, json=payload, headers=headers, timeout=10) as response:
                    resp_body = await response.text()
                    if response.status in (200, 201, 204):
                        _LOGGER.warning("ADLOS_REST SUCCESS (HTTP %s) via %s: %s", response.status, post_url, resp_body)
                        return True
                    _LOGGER.error("ADLOS_REST ERROR (HTTP %s) via %s: %s", response.status, post_url, resp_body)
            except Exception as e:
                _LOGGER.error("ADLOS_REST EXCEPTION posting to %s: %s", post_url, e)

        _LOGGER.error("ADLOS_REST: Failed to send message to all candidate URLs: %s", candidate_urls)
        return False

    async def _async_send_file(target_room: str, text: str, file_path: str) -> bool:
        target_url = _get_target_url(url)
        candidate_urls = _get_candidate_urls(target_url)
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        _LOGGER.warning("ADLOS_REST: Sending photo to candidate URLs (room=%s, file=%s): %s", target_room, file_path, text)

        for post_url in candidate_urls:
            try:
                form_data = aiohttp.FormData()
                form_data.add_field("text", text)
                form_data.add_field("sender", "Home Assistant")
                form_data.add_field("room", target_room)
                form_data.add_field("type", "image")

                with open(file_path, "rb") as f:
                    form_data.add_field("file", f, filename=os.path.basename(file_path))

                    async with session.post(post_url, data=form_data, headers=headers, timeout=15) as response:
                        resp_body = await response.text()
                        if response.status in (200, 201, 204):
                            _LOGGER.warning("ADLOS_REST SUCCESS (HTTP %s) via %s: %s", response.status, post_url, resp_body)
                            return True
                        _LOGGER.error("ADLOS_REST ERROR (HTTP %s) via %s: %s", response.status, post_url, resp_body)
            except Exception as e:
                _LOGGER.error("ADLOS_REST EXCEPTION posting photo to %s: %s", post_url, e)

        _LOGGER.error("ADLOS_REST: Failed to send photo to all candidate URLs: %s", candidate_urls)
        return False

    def _extract_params(call: ServiceCall):
        data = call.data
        extra_data = data.get("data") if isinstance(data.get("data"), dict) else {}

        raw_text = (
            data.get("message")
            or data.get("text")
            or data.get("caption")
            or data.get("content")
            or data.get("payload")
            or extra_data.get("message")
            or extra_data.get("text")
            or extra_data.get("caption")
            or ""
        )

        title = data.get("title") or extra_data.get("title")
        if title and raw_text and not str(raw_text).startswith(str(title)):
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

        file_path = (
            data.get("path")
            or data.get("image")
            or data.get("file_path")
            or extra_data.get("path")
            or extra_data.get("image")
            or extra_data.get("file_path")
        )
        if file_path:
            file_path = str(file_path).strip()
            if not file_path:
                file_path = None

        return target_room, text, file_path

    async def send_message(call: ServiceCall):
        """Service to send a text message or photo if path is provided."""
        target_room, text, file_path = _extract_params(call)

        if file_path and os.path.exists(file_path):
            await _async_send_file(target_room, text, file_path)
        else:
            if file_path:
                _LOGGER.warning("ADLOS_REST: Image file '%s' not found. Sending as text message.", file_path)
            await _async_send_text(target_room, text)

    async def send_photo(call: ServiceCall):
        """Service to send a photo (optional image path) to PocketBase REST API."""
        target_room, text, file_path = _extract_params(call)

        if file_path and os.path.exists(file_path):
            await _async_send_file(target_room, text, file_path)
        else:
            if file_path:
                _LOGGER.warning("ADLOS_REST: File path '%s' not found for send_photo. Sending as text message instead.", file_path)
            else:
                _LOGGER.info("ADLOS_REST: No file path provided for send_photo. Sending as text message.")
            await _async_send_text(target_room, text)

    # Register services under chad_app domain
    hass.services.async_register(DOMAIN, "send_message", send_message)
    hass.services.async_register(DOMAIN, "send_photo", send_photo)

    # Register aliases so adlos.send_message, adlos.send_photo, and notify.adlos work out of the box in automations
    try:
        hass.services.async_register("adlos", "send_message", send_message)
        hass.services.async_register("adlos", "send_photo", send_photo)
    except Exception:
        pass

    # Forward notify platform setup so notify.adlos entity is created
    await hass.config_entries.async_forward_entry_setups(entry, ["notify"])

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

