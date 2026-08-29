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

        # 3. Eindeutige Message-ID
        msg_id = data.get("id") or f"ha_{int(time.time() * 1000)}_{secrets.token_hex(4)}"

        # 4. Bild- und Kameraübertragung
        camera_entity = data.get("camera") or data.get("camera_entity")
        if not camera_entity and data.get("entity_id") and str(data.get("entity_id")).startswith("camera."):
            camera_entity = data.get("entity_id")

        image_url = None
        raw_image = data.get("image") or data.get("url") or data.get("path") or data.get("file_path")

        if camera_entity:
            proxy_url = f"/api/camera_proxy/{camera_entity}"
            image_url = proxy_url
        elif raw_image:
            image_url = str(raw_image).strip()

        # 5. Weiterleitung an send_message Service (übernimmt E2EE-Verschlüsselung, SSE-Stream, Backlog & REST-Dispatch)
        call_data = {
            "id": msg_id,
            "message": str(message or ""),
            "room": room_id,
            "data": data,
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

        camera_entity = data.get("camera") or data.get("camera_entity")
        if not camera_entity and data.get("entity_id") and str(data.get("entity_id")).startswith("camera."):
            camera_entity = data.get("entity_id")

        image_url = None
        raw_image = data.get("image") or data.get("url") or data.get("path") or data.get("file_path")

        if camera_entity:
            proxy_url = f"/api/camera_proxy/{camera_entity}"
            image_url = proxy_url
        elif raw_image:
            image_url = str(raw_image).strip()

        call_data = {
            "id": msg_id,
            "message": str(message or ""),
            "target": self.contact_id,
            "targets": [self.contact_id],
            "data": data,
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


