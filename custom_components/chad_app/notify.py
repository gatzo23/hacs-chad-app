"""Adlos notification service & entity platform for Chad App / Adlos."""

import asyncio
import json
import logging
import re
import secrets
import time
from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_TOKEN, CONF_ROOM_ID

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Adlos notify entities from a config entry."""
    entities: list[NotifyEntity] = [AdlosChadNotifyEntity(hass, entry)]

    # Erstelle automatisch für jeden registrierten Nutzer eine eigene Notify-Entität
    registered_users = entry.options.get("registered_users", entry.data.get("registered_users", {}))
    if isinstance(registered_users, dict):
        for cid, uinfo in registered_users.items():
            name = uinfo.get("name") if isinstance(uinfo, dict) else str(uinfo)
            entities.append(AdlosUserNotifyEntity(hass, entry, cid, name or cid))

    async_add_entities(entities, update_before_add=True)


class AdlosChadNotifyEntity(NotifyEntity):
    """Adlos Notify Entity for modern Home Assistant UI (Broadcast / All Contacts)."""

    _attr_has_entity_name = False
    _attr_name = "adlos"
    _attr_icon = "mdi:chat-processing-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the notify entity."""
        self.hass = hass
        self.entry = entry
        self.entity_id = "notify.adlos"
        self._attr_unique_id = f"{DOMAIN}_notify_{entry.entry_id}"
        self.secret_token = entry.options.get(CONF_TOKEN, entry.data.get(CONF_TOKEN, ""))
        self.webhook_id = f"adlos_pairing_{entry.entry_id}"

    async def async_send_message(self, message: str, title: str | None = None, data: dict | None = None) -> None:
        """Send a notification message via Adlos Notify Entity."""
        data = dict(data) if data else {}

        # 1. Standard-Raum (room) beibehalten: immer "homeassistant_bot" als Default
        room_id = data.get("room") or data.get("room_id") or "homeassistant_bot"

        # 2. Empfänger (targets) als formatierte Liste & Originalwert ermitteln
        targets = data.get("target") or data.get("targets")
        target_list: list[str] = []
        if targets is not None:
            if isinstance(targets, list):
                target_list = [str(t).strip() for t in targets if str(t).strip()]
            elif isinstance(targets, str):
                parts = re.split(r'[,;\s]+', targets.strip())
                target_list = [p.strip() for p in parts if p.strip()]
            else:
                target_list = [str(targets).strip()]

        # 3. Eindeutige Message-ID & Timestamp (Millisekunden)
        msg_id = data.get("id") or f"ha_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        now_ts = int(time.time() * 1000)

        # 4. Leichtgewichtige Bild- und Kameraübertragung (keine riesigen Base64-Strings im SSE-Stream)
        camera_entity = data.get("camera") or data.get("camera_entity")
        if not camera_entity and data.get("entity_id") and str(data.get("entity_id")).startswith("camera."):
            camera_entity = data.get("entity_id")

        image_url = None
        attachment = None
        raw_image = data.get("image") or data.get("url") or data.get("path") or data.get("file_path")

        if camera_entity:
            proxy_url = f"/api/camera_proxy/{camera_entity}"
            image_url = proxy_url
            attachment = {
                "type": "image",
                "url": proxy_url,
                "camera": camera_entity,
            }
            msg_type = "image"
        elif raw_image:
            image_url = str(raw_image).strip()
            attachment = {
                "type": "image",
                "url": image_url,
            }
            msg_type = "image"
        elif data.get("video") or data.get("video_path"):
            msg_type = "video"
        else:
            msg_type = data.get("type") or "text"

        payload = {
            "id": msg_id,
            "room": room_id,
            "sender": "Home Assistant",
            "type": msg_type,
            "title": title or "Home Assistant",
            "message": message,
            "text": message,
            "targets": target_list,
            "target": targets,
            "token": self.secret_token,
            "webhook_id": self.webhook_id,
            "timestamp": now_ts,
        }

        if image_url:
            payload["image"] = image_url
        if attachment:
            payload["attachment"] = attachment
        if camera_entity:
            payload["camera"] = camera_entity

        # 5. Sichere SSE-Zustellung & Backlog-Speicherung (letzte 50 Nachrichten)
        store = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        if store:
            messages_list = store.setdefault("messages", [])
            messages_list.append(payload)
            if len(messages_list) > 50:
                del messages_list[:-50]

            subscribers = list(store.get("subscribers", set()))
            if subscribers:
                sse_data = f"data: {json.dumps(payload)}\n\n".encode("utf-8")
                for resp in subscribers:
                    try:
                        asyncio.create_task(resp.write(sse_data))
                    except Exception as err:
                        _LOGGER.debug("Error writing to SSE subscriber: %s", err)

        # 6. Kombinierte Daten an Service weiterleiten (ohne None-Werte)
        combined_data = {**data, **payload}
        call_data = {
            "id": msg_id,
            "message": str(message or ""),
            "room": room_id,
            "data": combined_data,
        }
        if title is not None:
            call_data["title"] = str(title)
        if targets is not None:
            call_data["target"] = targets
        if target_list:
            call_data["targets"] = target_list
        if image_url:
            call_data["image"] = image_url
            call_data["path"] = image_url
        if camera_entity:
            call_data["camera"] = camera_entity

        try:
            if self.hass.services.has_service(DOMAIN, "send_message"):
                await self.hass.services.async_call(DOMAIN, "send_message", call_data)
            elif self.hass.services.has_service("adlos", "send_message"):
                await self.hass.services.async_call("adlos", "send_message", call_data)
            elif self.hass.services.has_service("adloshacs", "send_message"):
                await self.hass.services.async_call("adloshacs", "send_message", call_data)
        except Exception as err:
            _LOGGER.error("ADLOS_NOTIFY: Error forwarding to send_message: %s", err)


class AdlosUserNotifyEntity(NotifyEntity):
    """Adlos Notify Entity for a specific registered user contact."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:account-arrow-right-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, contact_id: str, user_name: str):
        """Initialize user notify entity."""
        self.hass = hass
        self.entry = entry
        self.contact_id = contact_id
        self.user_name = user_name
        slug_name = re.sub(r'[^a-zA-Z0-9_]', '_', user_name.lower().strip()).strip('_')
        self.entity_id = f"notify.adlos_{slug_name or contact_id}"
        self._attr_name = f"Adlos ({user_name})"
        self._attr_unique_id = f"{DOMAIN}_notify_user_{entry.entry_id}_{contact_id}"
        self.secret_token = entry.options.get(CONF_TOKEN, entry.data.get(CONF_TOKEN, ""))
        self.webhook_id = f"adlos_pairing_{entry.entry_id}"

    async def async_send_message(self, message: str, title: str | None = None, data: dict | None = None) -> None:
        """Send a notification message directly to this registered user."""
        data = dict(data) if data else {}
        data["target"] = self.contact_id
        data.setdefault("room", "homeassistant_bot")

        msg_id = data.get("id") or f"ha_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        now_ts = int(time.time() * 1000)

        camera_entity = data.get("camera") or data.get("camera_entity")
        if not camera_entity and data.get("entity_id") and str(data.get("entity_id")).startswith("camera."):
            camera_entity = data.get("entity_id")

        image_url = None
        attachment = None
        raw_image = data.get("image") or data.get("url") or data.get("path") or data.get("file_path")

        if camera_entity:
            proxy_url = f"/api/camera_proxy/{camera_entity}"
            image_url = proxy_url
            attachment = {
                "type": "image",
                "url": proxy_url,
                "camera": camera_entity,
            }
            msg_type = "image"
        elif raw_image:
            image_url = str(raw_image).strip()
            attachment = {
                "type": "image",
                "url": image_url,
            }
            msg_type = "image"
        else:
            msg_type = data.get("type") or "text"

        payload = {
            "id": msg_id,
            "room": "homeassistant_bot",
            "sender": "Home Assistant",
            "type": msg_type,
            "title": title or "Home Assistant",
            "message": message,
            "text": message,
            "targets": [self.contact_id],
            "target": self.contact_id,
            "token": self.secret_token,
            "webhook_id": self.webhook_id,
            "timestamp": now_ts,
        }

        if image_url:
            payload["image"] = image_url
        if attachment:
            payload["attachment"] = attachment
        if camera_entity:
            payload["camera"] = camera_entity

        store = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        if store:
            messages_list = store.setdefault("messages", [])
            messages_list.append(payload)
            if len(messages_list) > 50:
                del messages_list[:-50]

            subscribers = list(store.get("subscribers", set()))
            if subscribers:
                sse_data = f"data: {json.dumps(payload)}\n\n".encode("utf-8")
                for resp in subscribers:
                    try:
                        asyncio.create_task(resp.write(sse_data))
                    except Exception as err:
                        _LOGGER.debug("Error writing to SSE subscriber: %s", err)

        call_data = {
            "id": msg_id,
            "message": str(message or ""),
            "target": self.contact_id,
            "targets": [self.contact_id],
            "data": {**data, **payload},
        }
        if title is not None:
            call_data["title"] = str(title)
        if image_url:
            call_data["image"] = image_url
            call_data["path"] = image_url
        if camera_entity:
            call_data["camera"] = camera_entity

        try:
            if self.hass.services.has_service(DOMAIN, "send_message"):
                await self.hass.services.async_call(DOMAIN, "send_message", call_data)
            elif self.hass.services.has_service("adlos", "send_message"):
                await self.hass.services.async_call("adlos", "send_message", call_data)
            elif self.hass.services.has_service("adloshacs", "send_message"):
                await self.hass.services.async_call("adloshacs", "send_message", call_data)
        except Exception as err:
            _LOGGER.error("ADLOS_NOTIFY: Error forwarding to send_message: %s", err)


