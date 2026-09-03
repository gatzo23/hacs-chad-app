"""Chad App / Adlos Home Assistant Integration with native Adlos protocol, E2EE, and bidirectional chat."""

import os
import re
import json
import time
import logging
import asyncio
import secrets
import aiohttp
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.components import persistent_notification
import voluptuous as vol
from homeassistant.helpers import config_validation as cv

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
    CONF_ENCRYPTION_KEY,
    CONF_TOKEN,
    CONF_URL,
)
from .crypto import (
    derive_room_id,
    encrypt_text,
    encrypt_bytes,
    decode_key_bytes,
)
from .pocketbase_listener import PocketBaseListener, get_clean_base_url

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Chad App / Adlos from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    server_url = get_clean_base_url(
        entry.options.get(CONF_SERVER_URL)
        or entry.data.get(CONF_SERVER_URL)
        or entry.options.get(CONF_URL)
        or entry.data.get(CONF_URL)
        or DEFAULT_SERVER_URL
    )
    bot_id = (
        entry.options.get(CONF_BOT_ID)
        or entry.data.get(CONF_BOT_ID)
        or "homeassistant_bot"
    ).strip()
    bot_name = (
        entry.options.get(CONF_BOT_NAME)
        or entry.data.get(CONF_BOT_NAME)
        or DEFAULT_BOT_NAME
    ).strip()
    token = entry.options.get(CONF_TOKEN, entry.data.get(CONF_TOKEN))

    paired_users = entry.options.get(
        CONF_PAIRED_USERS,
        entry.data.get(CONF_PAIRED_USERS, {})
    )
    if not isinstance(paired_users, dict):
        paired_users = {}

    session = async_get_clientsession(hass)

    entry_data = {
        CONF_SERVER_URL: server_url,
        CONF_BOT_ID: bot_id,
        CONF_BOT_NAME: bot_name,
        CONF_TOKEN: token,
        CONF_PAIRED_USERS: dict(paired_users),
    }
    hass.data[DOMAIN][entry.entry_id] = entry_data

    def _resolve_user_key_for_room(room_id: str, custom_key: str | None = None) -> bytes:
        """Determines the AES key for a room."""
        if custom_key and str(custom_key).strip():
            return decode_key_bytes(custom_key)

        # Check in paired users
        cur_users = hass.data[DOMAIN][entry.entry_id].get(CONF_PAIRED_USERS, {})
        for uid, uinfo in cur_users.items():
            u_room = derive_room_id(uid, bot_id)
            if room_id == u_room or room_id == uinfo.get("room_id"):
                r_key = uinfo.get("room_key")
                if r_key:
                    return decode_key_bytes(r_key)

        return b""

    async def _async_send_text_to_room(
        target_room: str,
        text: str,
        custom_key: str | None = None,
        extra_fields: dict | None = None,
    ) -> bool:
        """Sends an encrypted (or plaintext fallback) text message to PocketBase."""
        records_url = f"{server_url}/api/collections/messages/records"
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        key_bytes = _resolve_user_key_for_room(target_room, custom_key)
        encrypted_text = encrypt_text(text, key_bytes) if key_bytes else text

        payload = {
            "room": target_room,
            "sender": bot_name,
            "text": encrypted_text,
            "type": "text",
        }

        try:
            async with session.post(records_url, json=payload, headers=headers, timeout=10) as resp:
                resp_text = await resp.text()
                if resp.status in (200, 201, 204):
                    _LOGGER.info("ADLOS: Message sent successfully (HTTP %s) to room %s", resp.status, target_room)
                    return True
                _LOGGER.error("ADLOS: Failed to send message to room %s (HTTP %s): %s", target_room, resp.status, resp_text)
        except Exception as err:
            _LOGGER.error("ADLOS: Exception sending message to room %s: %s", target_room, err)
        return False

    async def _async_send_file_to_room(
        target_room: str,
        text: str,
        file_path: str,
        custom_key: str | None = None,
        extra_fields: dict | None = None,
    ) -> bool:
        """Sends an encrypted image/file to PocketBase via multipart form data."""
        records_url = f"{server_url}/api/collections/messages/records"
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        key_bytes = _resolve_user_key_for_room(target_room, custom_key)

        try:
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
        except Exception as err:
            _LOGGER.error("ADLOS: Could not read file '%s': %s", file_path, err)
            return False

        encrypted_file_bytes = encrypt_bytes(raw_bytes, key_bytes) if key_bytes else raw_bytes
        encrypted_text = encrypt_text(text, key_bytes) if (text and key_bytes) else (text or "")
        filename = os.path.basename(file_path)

        form_data = aiohttp.FormData()
        form_data.add_field("text", encrypted_text)
        form_data.add_field("sender", bot_name)
        form_data.add_field("room", target_room)
        form_data.add_field("type", "image")
        form_data.add_field(
            "file",
            encrypted_file_bytes,
            filename=filename,
            content_type="application/octet-stream" if key_bytes else "image/jpeg",
        )

        try:
            async with session.post(records_url, data=form_data, headers=headers, timeout=20) as resp:
                resp_text = await resp.text()
                if resp.status in (200, 201, 204):
                    _LOGGER.info("ADLOS: File sent successfully (HTTP %s) to room %s", resp.status, target_room)
                    return True
                _LOGGER.error("ADLOS: Failed to send file to room %s (HTTP %s): %s", target_room, resp.status, resp_text)
        except Exception as err:
            _LOGGER.error("ADLOS: Exception sending file to room %s: %s", target_room, err)
        return False

    def _parse_recipients(raw_input: Any) -> list[str]:
        """Parses various recipient formats into a list of strings."""
        if not raw_input:
            return []
        if isinstance(raw_input, list):
            res = []
            for item in raw_input:
                res.extend(_parse_recipients(item))
            return res
        if isinstance(raw_input, str):
            parts = re.split(r'[,;\s]+', raw_input.strip())
            return [p.strip() for p in parts if p.strip()]
        return [str(raw_input).strip()]

    def _resolve_target_rooms(specified_targets: list[str], explicit_room: str | None = None) -> list[str]:
        """Resolves target names, IDs, or explicit rooms to derived room IDs."""
        if explicit_room and str(explicit_room).strip():
            return [str(explicit_room).strip()]

        cur_paired = hass.data[DOMAIN][entry.entry_id].get(CONF_PAIRED_USERS, {})

        if not specified_targets:
            # If no target specified, send to all paired users
            if cur_paired:
                return [derive_room_id(uid, bot_id) for uid in cur_paired]
            # Fallback room
            return [derive_room_id("homeassistant_user", bot_id)]

        target_rooms = []
        for rec in specified_targets:
            if not rec:
                continue
            rec_str = str(rec).strip()
            if rec_str.startswith("room:"):
                target_rooms.append(rec_str[5:].strip())
            else:
                matched = False
                for uid, uinfo in cur_paired.items():
                    uname = str(uinfo.get("name", "")).lower()
                    if rec_str.lower() == uid.lower() or (uname and rec_str.lower() in uname):
                        target_rooms.append(derive_room_id(uid, bot_id))
                        matched = True
                        break

                if not matched:
                    # Treat rec_str directly as contact ID
                    target_rooms.append(derive_room_id(rec_str, bot_id))

        return list(dict.fromkeys(target_rooms))

    def _extract_params(call: ServiceCall):
        data = call.data
        extra_data = data.get("data") if isinstance(data.get("data"), dict) else {}

        raw_text = (
            data.get("message")
            or data.get("text")
            or data.get("caption")
            or data.get("content")
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

        explicit_room = data.get("room") or extra_data.get("room")
        raw_targets = (
            data.get("target")
            or data.get("targets")
            or data.get("contact_id")
            or extra_data.get("target")
            or extra_data.get("targets")
        )
        parsed_targets = _parse_recipients(raw_targets)
        target_rooms = _resolve_target_rooms(parsed_targets, explicit_room)

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

        custom_key = data.get("encryption_key") or extra_data.get("encryption_key")
        return target_rooms, text, file_path, custom_key

    async def send_message(call: ServiceCall):
        """Service to send message or photo to one or multiple recipients."""
        target_rooms, text, file_path, custom_key = _extract_params(call)

        call_data = call.data
        extra_data = call_data.get("data") if isinstance(call_data.get("data"), dict) else {}

        # Handle camera snapshot
        camera_entity = (
            call_data.get("camera")
            or extra_data.get("camera")
            or call_data.get("camera_entity")
            or extra_data.get("camera_entity")
        )
        if not camera_entity and call_data.get("entity_id") and str(call_data.get("entity_id")).startswith("camera."):
            camera_entity = call_data.get("entity_id")

        if camera_entity and not file_path:
            try:
                from homeassistant.components.camera import async_get_image
                image_data = await async_get_image(hass, camera_entity)
                if image_data and image_data.content:
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
                        tf.write(image_data.content)
                        file_path = tf.name
            except Exception as err:
                _LOGGER.error("ADLOS: Failed to take camera snapshot for '%s': %s", camera_entity, err)

        tasks = []
        for room in target_rooms:
            if file_path and os.path.exists(file_path):
                tasks.append(_async_send_file_to_room(room, text, file_path, custom_key))
            else:
                tasks.append(_async_send_text_to_room(room, text, custom_key))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def send_photo(call: ServiceCall):
        """Service alias to send photo."""
        await send_message(call)

    async def register_user(call: ServiceCall):
        """Registers a user contact manually."""
        contact_id = str(call.data.get("contact_id") or call.data.get("id") or "").strip()
        user_name = str(call.data.get("name") or call.data.get("user_name") or "").strip() or contact_id
        if contact_id:
            room_key = str(call.data.get("room_key") or call.data.get("key") or "").strip()
            cur_paired = dict(hass.data[DOMAIN][entry.entry_id].get(CONF_PAIRED_USERS, {}))
            cur_paired[contact_id] = {
                "contact_id": contact_id,
                "name": user_name,
                "room_key": room_key,
                "room_id": derive_room_id(contact_id, bot_id),
            }
            new_options = dict(entry.options)
            new_options[CONF_PAIRED_USERS] = cur_paired
            hass.config_entries.async_update_entry(entry, options=new_options)
            hass.data[DOMAIN][entry.entry_id][CONF_PAIRED_USERS] = cur_paired
            _LOGGER.info("ADLOS: Manually registered user '%s' (%s)", user_name, contact_id)

    async def unregister_user(call: ServiceCall):
        """Unregisters a user contact."""
        contact_id = str(call.data.get("contact_id") or call.data.get("id") or "").strip()
        if contact_id:
            cur_paired = dict(hass.data[DOMAIN][entry.entry_id].get(CONF_PAIRED_USERS, {}))
            cur_paired.pop(contact_id, None)
            new_options = dict(entry.options)
            new_options[CONF_PAIRED_USERS] = cur_paired
            hass.config_entries.async_update_entry(entry, options=new_options)
            hass.data[DOMAIN][entry.entry_id][CONF_PAIRED_USERS] = cur_paired
            _LOGGER.info("ADLOS: Unregistered user contact ID: %s", contact_id)

    send_message_schema = vol.Schema({
        vol.Optional("message"): vol.Any(cv.string, None),
        vol.Optional("text"): vol.Any(cv.string, None),
        vol.Optional("title"): vol.Any(cv.string, None),
        vol.Optional("target"): vol.Any(cv.string, list, None),
        vol.Optional("targets"): vol.Any(cv.string, list, None),
        vol.Optional("room"): vol.Any(cv.string, None),
        vol.Optional("camera"): vol.Any(cv.string, None),
        vol.Optional("camera_entity"): vol.Any(cv.string, None),
        vol.Optional("image"): vol.Any(cv.string, None),
        vol.Optional("path"): vol.Any(cv.string, None),
        vol.Optional("encryption_key"): vol.Any(cv.string, None),
        vol.Optional("id"): vol.Any(cv.string, None),
    }, extra=vol.ALLOW_EXTRA)

    register_user_schema = vol.Schema({
        vol.Required("contact_id"): cv.string,
        vol.Optional("name"): vol.Any(cv.string, None),
        vol.Optional("room_key"): vol.Any(cv.string, None),
    }, extra=vol.ALLOW_EXTRA)

    unregister_user_schema = vol.Schema({
        vol.Required("contact_id"): cv.string,
    }, extra=vol.ALLOW_EXTRA)

    # Register services under chad_app and adlos aliases
    for domain_name in [DOMAIN, "adlos", "adloshacs"]:
        try:
            hass.services.async_register(domain_name, "send_message", send_message, schema=send_message_schema)
            hass.services.async_register(domain_name, "send_photo", send_photo, schema=send_message_schema)
            hass.services.async_register(domain_name, "register_user", register_user, schema=register_user_schema)
            hass.services.async_register(domain_name, "unregister_user", unregister_user, schema=unregister_user_schema)
        except Exception:
            pass

    # Start PocketBase background listener
    listener = PocketBaseListener(
        hass=hass,
        entry=entry,
        session=session,
        send_callback=_async_send_text_to_room,
    )
    hass.data[DOMAIN][entry.entry_id]["listener"] = listener
    await listener.start()

    # Forward platform setups (notify & image QR code entity)
    await hass.config_entries.async_forward_entry_setups(entry, ["notify", "image"])

    # Create Pairing QR Code Notification in Home Assistant
    try:
        import qrcode
        pairing_payload = json.dumps({
            "action": "adlos_contact",
            "id": bot_id,
            "name": bot_name,
            "home_server": server_url,
        })
        img = qrcode.make(pairing_payload)
        www_dir = hass.config.path("www")
        os.makedirs(www_dir, exist_ok=True)
        img_path = os.path.join(www_dir, "adlos_qr.png")
        img.save(img_path)

        notification_msg = (
            f"### 📱 Adlos App Kopplung\n\n"
            f"Scanne diesen QR-Code mit der Adlos-App (**'Kontakt hinzufügen'**):\n\n"
            f"![QR-Code](/local/adlos_qr.png?t={int(time.time())})\n\n"
            f"- **Bot-ID:** `{bot_id}`\n"
            f"- **Name:** `{bot_name}`\n"
            f"- **Server:** `{server_url}`\n\n"
            f"```json\n{pairing_payload}\n```"
        )
        persistent_notification.async_create(
            hass,
            notification_msg,
            title="Adlos QR-Code",
            notification_id="adlos_pairing_qr",
        )
    except Exception as err:
        _LOGGER.warning("Could not generate pairing QR notification: %s", err)

    # Reload entry when options are updated
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    listener: PocketBaseListener | None = entry_store.get("listener")
    if listener:
        await listener.stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["notify", "image"])

    hass.data[DOMAIN].pop(entry.entry_id, None)
    if not hass.data[DOMAIN]:
        for s in ["send_message", "send_photo", "register_user", "unregister_user"]:
            for d in [DOMAIN, "adlos", "adloshacs"]:
                try:
                    hass.services.async_remove(d, s)
                except Exception:
                    pass

    return unload_ok
