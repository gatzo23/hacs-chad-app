"""Adlos notification service & entity platform for Chad App."""

import logging
from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_URL, CONF_TOKEN, CONF_ROOM_ID

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Adlos notify entity from a config entry."""
    async_add_entities([AdlosChadNotifyEntity(hass, entry)], update_before_add=True)


class AdlosChadNotifyEntity(NotifyEntity):
    """Adlos Notify Entity for modern Home Assistant UI."""

    _attr_has_entity_name = False
    _attr_name = "Adlos"
    _attr_icon = "mdi:chat-processing-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the notify entity."""
        self.hass = hass
        self.entry = entry
        self.entity_id = "notify.adlos"
        self._attr_unique_id = f"{DOMAIN}_notify_{entry.entry_id}"

    async def async_send_message(self, message: str, title: str | None = None, data: dict | None = None) -> None:
        """Send a notification message via Adlos Notify Entity."""
        send_func = self.hass.services.has_service(DOMAIN, "send_message")
        if send_func:
            call_data = {"message": message, "title": title}
            if data:
                call_data["data"] = data
            await self.hass.services.async_call(DOMAIN, "send_message", call_data)
