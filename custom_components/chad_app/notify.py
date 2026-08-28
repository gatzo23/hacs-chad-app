"""Adlos notification service & entity platform for Chad App / Adlos."""

import asyncio
import logging
import re
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

        # 1. Standard-Raum (room) beibehalten:
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

        # Bestimme Nachrichtentyp (text, image, video)
        msg_type = data.get("type")
        if not msg_type:
            if data.get("image") or data.get("path") or data.get("file_path"):
                msg_type = "image"
            elif data.get("video") or data.get("video_path"):
                msg_type = "video"
            else:
                msg_type = "text"

        payload = {
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
            "timestamp": asyncio.get_event_loop().time(),
        }

        # Kombinierte Aufrufdaten vorbereiten
        combined_data = {**data, **payload}
        call_data = {
            "message": message,
            "title": title,
            "room": room_id,
            "target": targets,
            "targets": target_list,
            "data": combined_data,
        }

        if data.get("image") or data.get("path") or data.get("file_path"):
            call_data["image"] = data.get("image") or data.get("path") or data.get("file_path")
            call_data["path"] = call_data["image"]

        # Service-Aufruf weiterleiten
        if self.hass.services.has_service(DOMAIN, "send_message"):
            await self.hass.services.async_call(DOMAIN, "send_message", call_data)
        elif self.hass.services.has_service("adlos", "send_message"):
            await self.hass.services.async_call("adlos", "send_message", call_data)
        elif self.hass.services.has_service("adloshacs", "send_message"):
            await self.hass.services.async_call("adloshacs", "send_message", call_data)


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

        call_data = {
            "message": message,
            "title": title,
            "target": self.contact_id,
            "targets": [self.contact_id],
            "data": data,
        }

        if data.get("image") or data.get("path") or data.get("file_path"):
            call_data["image"] = data.get("image") or data.get("path") or data.get("file_path")
            call_data["path"] = call_data["image"]

        if self.hass.services.has_service(DOMAIN, "send_message"):
            await self.hass.services.async_call(DOMAIN, "send_message", call_data)
        elif self.hass.services.has_service("adlos", "send_message"):
            await self.hass.services.async_call("adlos", "send_message", call_data)
        elif self.hass.services.has_service("adloshacs", "send_message"):
            await self.hass.services.async_call("adloshacs", "send_message", call_data)

