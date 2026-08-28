"""Chad App / Adlos Home Assistant Integration with End-to-End Encryption (E2EE) & Multi-User Support."""

import os
import re
import base64
import hashlib
import logging
import asyncio
import aiohttp
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

from .const import (
    DOMAIN,
    CONF_URL,
    CONF_TOKEN,
    CONF_ROOM_ID,
    CONF_BOT_ID,
    CONF_TARGET_CONTACTS,
    CONF_ENCRYPTION_KEY,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# E2EE Crypto & Room Helpers (Identical to Dart EncryptionHelper in Adlos App)
# ---------------------------------------------------------------------------

def derive_room_id(id_a: str, id_b: str) -> str:
    """Derives a deterministic 15-character PocketBase-compatible Room ID for two contacts."""
    combined = "_".join(sorted([id_a.strip(), id_b.strip()]))
    h = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    clean = re.sub(r'[^a-zA-Z0-9]', '', h).lower()
    return clean[:15]


def derive_deterministic_room_key(room_id: str) -> bytes:
    """Derives a deterministic 32-byte AES key from room_id (SHA-256 of 'adlos_e2ee_secret_v1_<roomId>')."""
    return hashlib.sha256(f"adlos_e2ee_secret_v1_{room_id}".encode("utf-8")).digest()


def decode_key_bytes(key_str: str) -> bytes:
    """Decodes a base64/base64url key string or hashes an arbitrary passphrase into 32 bytes."""
    normalized = (key_str or "").strip()
    if not normalized:
        return b""
    try:
        return base64.urlsafe_b64decode(normalized)
    except Exception:
        pass
    try:
        # Standard base64 with padding
        b64 = normalized.replace("-", "+").replace("_", "/")
        while len(b64) % 4 != 0:
            b64 += "="
        return base64.b64decode(b64)
    except Exception:
        # Fallback: SHA-256 hash of the passphrase string
        return hashlib.sha256(normalized.encode("utf-8")).digest()


def encrypt_text(plain_text: str, key_bytes: bytes) -> str:
    """Encrypts plain text using AES-256-CBC with PKCS7 padding and a random 16-byte IV.
    
    Output format: iv_base64:ciphertext_base64
    """
    if not plain_text:
        return plain_text
    if not key_bytes or len(key_bytes) != 32:
        _LOGGER.warning("ADLOS_E2EE: Invalid key length (%s bytes), sending unencrypted text", len(key_bytes) if key_bytes else 0)
        return plain_text

    try:
        iv = os.urandom(16)
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(plain_text.encode("utf-8")) + padder.finalize()

        cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()

        iv_b64 = base64.b64encode(iv).decode("ascii")
        ct_b64 = base64.b64encode(ciphertext).decode("ascii")
        return f"{iv_b64}:{ct_b64}"
    except Exception as err:
        _LOGGER.error("ADLOS_E2EE: Text encryption failed: %s", err)
        return plain_text


def encrypt_bytes(data_bytes: bytes, key_bytes: bytes) -> bytes:
    """Encrypts raw file bytes using AES-256-CBC with PKCS7 padding.
    
    Output format: 16 bytes IV prefix + ciphertext bytes
    """
    if not data_bytes:
        return data_bytes
    if not key_bytes or len(key_bytes) != 32:
        _LOGGER.warning("ADLOS_E2EE: Invalid key length (%s bytes), sending unencrypted file", len(key_bytes) if key_bytes else 0)
        return data_bytes

    try:
        iv = os.urandom(16)
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(data_bytes) + padder.finalize()

        cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()

        return iv + ciphertext
    except Exception as err:
        _LOGGER.error("ADLOS_E2EE: File byte encryption failed: %s", err)
        return data_bytes


# ---------------------------------------------------------------------------
# Home Assistant Entry Setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Chad App / Adlos from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    url = entry.options.get(CONF_URL, entry.data.get(CONF_URL, "https://pocket.nextbee.org/api/collections/messages/records"))
    token = entry.options.get(CONF_TOKEN, entry.data.get(CONF_TOKEN))
    bot_id = entry.options.get(CONF_BOT_ID, entry.data.get(CONF_BOT_ID, "homeassistant_bot")).strip() or "homeassistant_bot"
    default_room = entry.options.get(CONF_ROOM_ID, entry.data.get(CONF_ROOM_ID, "homeassistant_bot")).strip() or "homeassistant_bot"
    target_contacts_raw = entry.options.get(CONF_TARGET_CONTACTS, entry.data.get(CONF_TARGET_CONTACTS, ""))
    configured_key = entry.options.get(CONF_ENCRYPTION_KEY, entry.data.get(CONF_ENCRYPTION_KEY))

    stored_users = entry.options.get("registered_users", entry.data.get("registered_users", {}))
    if not isinstance(stored_users, dict):
        stored_users = {}

    hass.data[DOMAIN][entry.entry_id] = {
        CONF_URL: url,
        CONF_TOKEN: token,
        CONF_BOT_ID: bot_id,
        CONF_ROOM_ID: default_room,
        CONF_TARGET_CONTACTS: target_contacts_raw,
        CONF_ENCRYPTION_KEY: configured_key,
        "registered_users": dict(stored_users),
    }

    session = async_get_clientsession(hass)

    def _resolve_room_key(target_room: str, custom_key_str: str | None = None) -> bytes:
        """Determines the 32-byte encryption key for a room."""
        if custom_key_str and custom_key_str.strip():
            return decode_key_bytes(custom_key_str)
        if configured_key and str(configured_key).strip():
            return decode_key_bytes(configured_key)
        return derive_deterministic_room_key(target_room)

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

    async def _async_send_text_to_room(target_room: str, text: str, custom_key: str | None = None, extra_fields: dict | None = None) -> bool:
        target_url = _get_target_url(url)
        candidate_urls = _get_candidate_urls(target_url)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        key_bytes = _resolve_room_key(target_room, custom_key)
        encrypted_text = encrypt_text(text, key_bytes)

        payload = {
            "room": target_room,
            "sender": "Home Assistant",
            "text": encrypted_text,
            "type": "text",
        }
        if extra_fields:
            if "title" in extra_fields and extra_fields["title"]:
                payload["title"] = extra_fields["title"]
            if "targets" in extra_fields and extra_fields["targets"]:
                payload["targets"] = extra_fields["targets"]
            if "target" in extra_fields and extra_fields["target"] is not None:
                payload["target"] = extra_fields["target"]

        _LOGGER.debug("ADLOS_REST: Sending encrypted message to room %s", target_room)

        for post_url in candidate_urls:
            try:
                async with session.post(post_url, json=payload, headers=headers, timeout=10) as response:
                    resp_body = await response.text()
                    if response.status in (200, 201, 204):
                        _LOGGER.info("ADLOS_REST SUCCESS (HTTP %s) via %s for room %s: %s", response.status, post_url, target_room, resp_body)
                        return True
                    _LOGGER.error("ADLOS_REST ERROR (HTTP %s) via %s: %s", response.status, post_url, resp_body)
            except Exception as e:
                _LOGGER.error("ADLOS_REST EXCEPTION posting to %s: %s", post_url, e)

        _LOGGER.error("ADLOS_REST: Failed to send encrypted message to room %s", target_room)
        return False

    async def _async_send_file_to_room(target_room: str, text: str, file_path: str, custom_key: str | None = None, extra_fields: dict | None = None) -> bool:
        target_url = _get_target_url(url)
        candidate_urls = _get_candidate_urls(target_url)
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        key_bytes = _resolve_room_key(target_room, custom_key)

        try:
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
        except Exception as e:
            _LOGGER.error("ADLOS_REST: Could not read image file '%s': %s", file_path, e)
            return False

        encrypted_file_bytes = encrypt_bytes(raw_bytes, key_bytes)
        encrypted_text = encrypt_text(text, key_bytes) if text else ""

        filename = os.path.basename(file_path)
        _LOGGER.debug("ADLOS_REST: Sending encrypted photo (%s bytes) to room %s", len(encrypted_file_bytes), target_room)

        for post_url in candidate_urls:
            try:
                form_data = aiohttp.FormData()
                form_data.add_field("text", encrypted_text)
                form_data.add_field("sender", "Home Assistant")
                form_data.add_field("room", target_room)
                form_data.add_field("type", "image")
                form_data.add_field(
                    "file",
                    encrypted_file_bytes,
                    filename=filename,
                    content_type="application/octet-stream"
                )

                async with session.post(post_url, data=form_data, headers=headers, timeout=20) as response:
                    resp_body = await response.text()
                    if response.status in (200, 201, 204):
                        _LOGGER.info("ADLOS_REST SUCCESS (HTTP %s) via %s for room %s: %s", response.status, post_url, target_room, resp_body)
                        return True
                    _LOGGER.error("ADLOS_REST ERROR (HTTP %s) via %s: %s", response.status, post_url, resp_body)
            except Exception as e:
                _LOGGER.error("ADLOS_REST EXCEPTION posting photo to %s: %s", post_url, e)

        _LOGGER.error("ADLOS_REST: Failed to send encrypted photo to room %s", target_room)
        return False

    def _parse_recipients(raw_input) -> list[str]:
        """Parses various recipient formats into a clean list of strings."""
        if not raw_input:
            return []
        if isinstance(raw_input, list):
            res = []
            for item in raw_input:
                res.extend(_parse_recipients(item))
            return res
        if isinstance(raw_input, str):
            # Split by comma, semicolon or whitespace
            parts = re.split(r'[,;\s]+', raw_input.strip())
            return [p.strip() for p in parts if p.strip()]
        return [str(raw_input).strip()]

    def _resolve_target_rooms(specified_targets: list[str], explicit_room: str | None = None) -> list[str]:
        """Maps user names, contact IDs, or room names to deterministic room IDs."""
        if explicit_room and str(explicit_room).strip() and str(explicit_room).strip() != "homeassistant_bot":
            return [str(explicit_room).strip()]

        targets = specified_targets
        if not targets:
            targets = _parse_recipients(target_contacts_raw)

        if not targets:
            # Fallback to default room (standard: "homeassistant_bot")
            return [explicit_room or default_room or "homeassistant_bot"]

        reg_users = hass.data[DOMAIN].get(entry.entry_id, {}).get("registered_users", {})
        target_rooms = []

        for rec in targets:
            if not rec:
                continue
            rec_str = str(rec).strip()
            if rec_str.startswith("room:"):
                target_rooms.append(rec_str[5:].strip())
            elif rec_str == bot_id or rec_str == "homeassistant_bot":
                target_rooms.append(rec_str)
            else:
                # Check registered users by name (case-insensitive) or contact_id
                matched_cid = None
                for cid, uinfo in reg_users.items():
                    if rec_str.lower() == cid.lower() or rec_str.lower() == str(uinfo.get("name", "")).lower():
                        matched_cid = cid
                        break

                if matched_cid:
                    target_rooms.append(derive_room_id(bot_id, matched_cid))
                elif len(rec_str) == 15 and re.match(r'^[a-zA-Z0-9]{15}$', rec_str):
                    # Valid 15-character PocketBase contact ID
                    target_rooms.append(derive_room_id(bot_id, rec_str))
                else:
                    # User name or target not mapped to a 15-char contact ID -> fallback to standard bot room
                    _LOGGER.info("ADLOS: Target '%s' mapped to standard bot room '%s'", rec_str, default_room or "homeassistant_bot")
                    target_rooms.append(default_room or "homeassistant_bot")

        return list(dict.fromkeys(target_rooms)) if target_rooms else [default_room or "homeassistant_bot"]

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

        explicit_room = data.get("room") or extra_data.get("room")

        raw_targets = (
            data.get("target")
            or data.get("targets")
            or data.get("contact_id")
            or data.get("contact_ids")
            or extra_data.get("target")
            or extra_data.get("targets")
            or extra_data.get("contact_id")
            or extra_data.get("contact_ids")
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

        custom_key = (
            data.get("encryption_key")
            or extra_data.get("encryption_key")
            or data.get("key")
            or extra_data.get("key")
        )
        if custom_key:
            custom_key = str(custom_key).strip()
            if not custom_key:
                custom_key = None

        extra_fields = {
            "title": title or "Home Assistant",
            "targets": parsed_targets,
            "target": raw_targets,
        }

        return target_rooms, text, file_path, custom_key, extra_fields

    async def send_message(call: ServiceCall):
        """Service to send an encrypted text message or photo to one or multiple recipients."""
        target_rooms, text, file_path, custom_key, extra_fields = _extract_params(call)

        tasks = []
        for room in target_rooms:
            if file_path and os.path.exists(file_path):
                tasks.append(_async_send_file_to_room(room, text, file_path, custom_key, extra_fields))
            else:
                if file_path:
                    _LOGGER.warning("ADLOS_REST: Image file '%s' not found. Sending as text message.", file_path)
                tasks.append(_async_send_text_to_room(room, text, custom_key, extra_fields))

        if tasks:
            await asyncio.gather(*tasks)

    async def send_photo(call: ServiceCall):
        """Service to send an encrypted photo to one or multiple recipients."""
        target_rooms, text, file_path, custom_key, extra_fields = _extract_params(call)

        tasks = []
        for room in target_rooms:
            if file_path and os.path.exists(file_path):
                tasks.append(_async_send_file_to_room(room, text, file_path, custom_key, extra_fields))
            else:
                if file_path:
                    _LOGGER.warning("ADLOS_REST: File path '%s' not found for send_photo. Sending as text message instead.", file_path)
                tasks.append(_async_send_text_to_room(room, text, custom_key, extra_fields))

        if tasks:
            await asyncio.gather(*tasks)

    async def async_register_user_entry(contact_id: str, user_name: str | None = None) -> list[str]:
        cid = (contact_id or "").strip()
        if not cid:
            return []
        name = (user_name or "").strip() or cid

        reg_users = hass.data[DOMAIN][entry.entry_id].setdefault("registered_users", {})
        reg_users[cid] = {
            "contact_id": cid,
            "name": name,
        }

        cur_str = entry.options.get(CONF_TARGET_CONTACTS, entry.data.get(CONF_TARGET_CONTACTS, ""))
        cur_list = [c.strip() for c in re.split(r'[,;\s]+', cur_str) if c.strip()]
        if cid not in cur_list:
            cur_list.append(cid)

        new_options = dict(entry.options)
        new_options[CONF_TARGET_CONTACTS] = ", ".join(cur_list)
        new_options["registered_users"] = reg_users
        hass.config_entries.async_update_entry(entry, options=new_options)
        _LOGGER.info("ADLOS_REGISTRATION: Registered user '%s' (%s). Total registered users: %s", name, cid, len(reg_users))
        return cur_list

    async def async_unregister_user_entry(contact_id: str) -> None:
        cid = (contact_id or "").strip()
        if not cid:
            return
        reg_users = hass.data[DOMAIN][entry.entry_id].setdefault("registered_users", {})
        reg_users.pop(cid, None)

        cur_str = entry.options.get(CONF_TARGET_CONTACTS, entry.data.get(CONF_TARGET_CONTACTS, ""))
        cur_list = [c.strip() for c in re.split(r'[,;\s]+', cur_str) if c.strip()]
        if cid in cur_list:
            cur_list.remove(cid)

        new_options = dict(entry.options)
        new_options[CONF_TARGET_CONTACTS] = ", ".join(cur_list)
        new_options["registered_users"] = reg_users
        hass.config_entries.async_update_entry(entry, options=new_options)
        _LOGGER.info("ADLOS_REGISTRATION: Unregistered user contact ID: %s", cid)

    # Register Webhooks for QR code automatic pairing and user registration
    webhook_ids = [f"adlos_pairing_{entry.entry_id}", "adlos_pairing", "adlos_register_user"]

    async def handle_pairing_webhook(hass: HomeAssistant, webhook_id: str, request: aiohttp.web.Request) -> aiohttp.web.Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        msg_type = str(body.get("type") or "").strip()
        contact_id = str(body.get("contact_id") or body.get("contactId") or body.get("user_id") or body.get("id") or "").strip()
        user_name = str(body.get("name") or body.get("user_name") or body.get("username") or "").strip()
        
        if contact_id:
            contacts = await async_register_user_entry(contact_id, user_name)
            reg_users = hass.data[DOMAIN][entry.entry_id].get("registered_users", {})
            return aiohttp.web.json_response({
                "status": "ok",
                "message": f"User {contact_id} ({user_name}) successfully registered in Home Assistant",
                "contact_id": contact_id,
                "name": user_name,
                "total_registered": len(reg_users),
                "bot_id": bot_id,
                "room_id": derive_room_id(bot_id, contact_id),
            })
        return aiohttp.web.json_response({"status": "error", "message": "Missing contact_id"}, status=400)

    for wid in webhook_ids:
        try:
            from homeassistant.components import webhook
            webhook.async_register(hass, DOMAIN, f"Adlos Pairing ({wid})", wid, handle_pairing_webhook)
        except Exception:
            pass

    async def register_user(call: ServiceCall):
        """Service to register a user contact_id into target_contacts and registered_users."""
        contact_id = str(call.data.get("contact_id") or call.data.get("id") or call.data.get("target") or "").strip()
        user_name = str(call.data.get("name") or call.data.get("user_name") or "").strip()
        if contact_id:
            await async_register_user_entry(contact_id, user_name)

    async def unregister_user(call: ServiceCall):
        """Service to remove a user contact_id from target_contacts and registered_users."""
        contact_id = str(call.data.get("contact_id") or call.data.get("id") or call.data.get("target") or "").strip()
        if contact_id:
            await async_unregister_user_entry(contact_id)

    import voluptuous as vol
    from homeassistant.helpers import config_validation as cv

    send_message_schema = vol.Schema({
        vol.Required("message"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("target"): vol.Any(cv.string, list),
        vol.Optional("targets"): vol.Any(cv.string, list),
        vol.Optional("room"): cv.string,
        vol.Optional("image"): cv.string,
        vol.Optional("path"): cv.string,
        vol.Optional("encryption_key"): cv.string,
    }, extra=vol.ALLOW_EXTRA)

    send_photo_schema = vol.Schema({
        vol.Optional("message"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("path"): cv.string,
        vol.Optional("image"): cv.string,
        vol.Optional("target"): vol.Any(cv.string, list),
        vol.Optional("targets"): vol.Any(cv.string, list),
        vol.Optional("room"): cv.string,
        vol.Optional("encryption_key"): cv.string,
    }, extra=vol.ALLOW_EXTRA)

    register_user_schema = vol.Schema({
        vol.Required("contact_id"): cv.string,
        vol.Optional("name"): cv.string,
    }, extra=vol.ALLOW_EXTRA)

    unregister_user_schema = vol.Schema({
        vol.Required("contact_id"): cv.string,
    }, extra=vol.ALLOW_EXTRA)

    # Register services under chad_app domain
    hass.services.async_register(DOMAIN, "send_message", send_message, schema=send_message_schema)
    hass.services.async_register(DOMAIN, "send_photo", send_photo, schema=send_photo_schema)
    hass.services.async_register(DOMAIN, "register_user", register_user, schema=register_user_schema)
    hass.services.async_register(DOMAIN, "unregister_user", unregister_user, schema=unregister_user_schema)

    # Register aliases so adlos.send_message, adlos.register_user, etc. work out of the box in automations
    for alias_domain in ["adlos", "adloshacs"]:
        try:
            hass.services.async_register(alias_domain, "send_message", send_message, schema=send_message_schema)
            hass.services.async_register(alias_domain, "send_photo", send_photo, schema=send_photo_schema)
            hass.services.async_register(alias_domain, "register_user", register_user, schema=register_user_schema)
            hass.services.async_register(alias_domain, "unregister_user", unregister_user, schema=unregister_user_schema)
        except Exception:
            pass

    # Forward platform setups (notify & image QR code entity)
    await hass.config_entries.async_forward_entry_setups(entry, ["notify", "image"])

    # Create Pairing QR Code and Notification
    try:
        from homeassistant.components import persistent_notification
        import qrcode
        import time

        ha_url = str(entry.data.get("ha_url") or "https://homey.org").strip().rstrip("/")
        if not ha_url.startswith("http://") and not ha_url.startswith("https://"):
            ha_url = f"https://{ha_url}"
        ha_token = str(entry.data.get(CONF_TOKEN) or "").strip()

        pairing_payload = json.dumps({
            "type": "adlos_ha",
            "url": ha_url,
            "token": ha_token,
            "webhook_id": "adlos_pairing",
        })

        img = qrcode.make(pairing_payload)
        www_dir = hass.config.path("www")
        os.makedirs(www_dir, exist_ok=True)
        img_path = os.path.join(www_dir, "adlos_qr.png")
        img.save(img_path)

        notification_msg = (
            f"### 📱 Adlos App Kopplung\n\n"
            f"Scanne diesen QR-Code mit der Adlos-App:\n\n"
            f"![QR-Code](/local/adlos_qr.png?t={int(time.time())})\n\n"
            f"**Home Assistant URL:** `{ha_url}`\n\n"
            f"**Token:** `{ha_token}`\n\n"
            f"**Kopplungs-Daten:**\n```json\n{pairing_payload}\n```"
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
    # Unregister webhooks
    webhook_ids = [f"adlos_pairing_{entry.entry_id}", "adlos_pairing", "adlos_register_user"]
    for wid in webhook_ids:
        try:
            from homeassistant.components import webhook
            webhook.async_unregister(hass, wid)
        except Exception:
            pass

    hass.data[DOMAIN].pop(entry.entry_id, None)
    if not hass.data[DOMAIN]:
        for s in ["send_message", "send_photo", "register_user", "unregister_user"]:
            for d in [DOMAIN, "adlos", "adloshacs"]:
                try:
                    hass.services.async_remove(d, s)
                except Exception:
                    pass
        try:
            hass.services.async_remove("notify", "adlos")
        except Exception:
            pass
        try:
            hass.services.async_remove("notify", "chad_app")
        except Exception:
            pass

    return True


