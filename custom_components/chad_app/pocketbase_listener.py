"""PocketBase Realtime SSE listener, handshake exchange, and ephemeral relay for Adlos."""

import asyncio
import json
import logging
import aiohttp
from typing import Callable, Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components import persistent_notification

from .const import (
    DOMAIN,
    DEFAULT_SERVER_URL,
    DEFAULT_BOT_NAME,
    CONF_SERVER_URL,
    CONF_BOT_NAME,
    CONF_BOT_ID,
    CONF_PAIRED_USERS,
    CONF_TARGET_CONTACTS,
    CONF_TOKEN,
    CONF_URL,
    EVENT_ADLOS_MESSAGE_RECEIVED,
    EVENT_ADLOS_HANDSHAKE_RECEIVED,
)
from .crypto import (
    derive_room_id,
    decrypt_text,
    encrypt_text,
)

_LOGGER = logging.getLogger(__name__)


def get_clean_base_url(raw_url: str | None) -> str:
    """Normalizes any PocketBase URL to base domain URL e.g. https://pocket.nextbee.org."""
    url = (raw_url or "").strip()
    if not url:
        return DEFAULT_SERVER_URL
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"
    url = url.rstrip("/")

    # Strip subpaths if user passed full collection URL
    for suffix in [
        "/api/collections/messages/records",
        "/api/collections/messages",
        "/api/realtime",
        "/api",
    ]:
        if url.endswith(suffix):
            url = url[:-len(suffix)].rstrip("/")
            break
    return url or DEFAULT_SERVER_URL


class PocketBaseListener:
    """Manages SSE Realtime stream and polling fallback to PocketBase messages collection."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session: aiohttp.ClientSession,
        send_callback: Callable[[str, str, str | None], Any] | None = None,
    ):
        self.hass = hass
        self.entry = entry
        self.session = session
        self.send_callback = send_callback

        self._running = False
        self._sse_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._processed_record_ids: set[str] = set()

    @property
    def server_url(self) -> str:
        raw = (
            self.entry.options.get(CONF_SERVER_URL)
            or self.entry.data.get(CONF_SERVER_URL)
            or self.entry.options.get(CONF_URL)
            or self.entry.data.get(CONF_URL)
            or DEFAULT_SERVER_URL
        )
        return get_clean_base_url(raw)

    @property
    def bot_id(self) -> str:
        return (
            self.entry.options.get(CONF_BOT_ID)
            or self.entry.data.get(CONF_BOT_ID)
            or "homeassistant_bot"
        ).strip()

    @property
    def bot_name(self) -> str:
        return (
            self.entry.options.get(CONF_BOT_NAME)
            or self.entry.data.get(CONF_BOT_NAME)
            or DEFAULT_BOT_NAME
        ).strip()

    @property
    def token(self) -> str | None:
        t = self.entry.options.get(CONF_TOKEN) or self.entry.data.get(CONF_TOKEN)
        return str(t).strip() if t else None

    @property
    def paired_users(self) -> dict[str, dict]:
        users = self.entry.options.get(
            CONF_PAIRED_USERS,
            self.entry.data.get(CONF_PAIRED_USERS, {})
        )
        if isinstance(users, dict):
            return dict(users)
        return {}

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def start(self) -> None:
        """Starts the background listener tasks."""
        if self._running:
            return
        self._running = True
        self._sse_task = asyncio.create_task(self._sse_loop(), name="adlos_pb_sse_loop")
        self._poll_task = asyncio.create_task(self._poll_loop(), name="adlos_pb_poll_loop")
        _LOGGER.info("ADLOS_PB: Started listener for bot '%s' on %s", self.bot_id, self.server_url)

    async def stop(self) -> None:
        """Stops the background listener tasks."""
        self._running = False
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        _LOGGER.info("ADLOS_PB: Stopped listener for bot '%s'", self.bot_id)

    async def _sse_loop(self) -> None:
        """Main SSE event stream consumer with automatic reconnect."""
        backoff = 2
        while self._running:
            realtime_url = f"{self.server_url}/api/realtime"
            _LOGGER.debug("ADLOS_PB: Connecting to SSE realtime at %s", realtime_url)
            try:
                headers = {}
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"

                async with self.session.get(
                    realtime_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=None, sock_read=60)
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("ADLOS_PB: SSE connection failed with HTTP %s", resp.status)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 30)
                        continue

                    backoff = 2
                    client_id = None
                    event_type = "message"

                    # Read SSE stream line by line
                    while self._running:
                        line_bytes = await resp.content.readline()
                        if not line_bytes:
                            break
                        line = line_bytes.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue

                        if line.startswith("event:"):
                            event_type = line[6:].strip()
                        elif line.startswith("data:"):
                            data_str = line[5:].strip()
                            try:
                                data = json.loads(data_str)
                            except Exception:
                                continue

                            # 1. PocketBase PB_CONNECT handshake
                            if event_type == "PB_CONNECT":
                                client_id = data.get("clientId")
                                _LOGGER.debug("ADLOS_PB: Received PB_CONNECT with clientId: %s", client_id)
                                if client_id:
                                    await self._subscribe_to_messages(client_id)
                            else:
                                # Regular record event
                                await self._handle_incoming_event(data)

            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.debug("ADLOS_PB: SSE stream error: %s (reconnecting in %ss)", err, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _subscribe_to_messages(self, client_id: str) -> bool:
        """Subscribes to messages collection in PocketBase using client_id."""
        url = f"{self.server_url}/api/realtime"
        payload = {
            "clientId": client_id,
            "subscriptions": ["messages"],
        }
        try:
            async with self.session.post(url, json=payload, headers=self._get_headers(), timeout=10) as resp:
                if resp.status in (200, 204):
                    _LOGGER.info("ADLOS_PB: Successfully subscribed clientId %s to 'messages'", client_id)
                    return True
                resp_text = await resp.text()
                _LOGGER.warning("ADLOS_PB: Failed to subscribe clientId %s: HTTP %s - %s", client_id, resp.status, resp_text)
        except Exception as err:
            _LOGGER.error("ADLOS_PB: Exception subscribing to realtime messages: %s", err)
        return False

    async def _poll_loop(self) -> None:
        """Periodic polling fallback (every 15s) to guarantee no messages are missed."""
        # Initial delay before starting poll
        await asyncio.sleep(5)
        while self._running:
            try:
                await self._poll_records()
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.debug("ADLOS_PB: Polling fallback exception: %s", err)

            try:
                await asyncio.sleep(15)
            except asyncio.CancelledError:
                break

    async def _poll_records(self) -> None:
        """Queries recent messages from PocketBase to handle any uncollected messages."""
        records_url = f"{self.server_url}/api/collections/messages/records?perPage=30&sort=-created"
        try:
            async with self.session.get(records_url, headers=self._get_headers(), timeout=10) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
                items = data.get("items", [])
                for record in items:
                    await self._process_record(record)
        except Exception as err:
            _LOGGER.debug("ADLOS_PB: Poll request failed: %s", err)

    async def _handle_incoming_event(self, data: dict) -> None:
        """Handles an SSE payload with action and record."""
        action = data.get("action")
        record = data.get("record")
        if action in ("create", "update") and isinstance(record, dict):
            await self._process_record(record)

    async def _process_record(self, record: dict) -> None:
        """Core message and handshake processor."""
        record_id = str(record.get("id") or "").strip()
        if not record_id or record_id in self._processed_record_ids:
            return

        sender = str(record.get("sender") or "").strip()
        msg_type = str(record.get("type") or "").strip()
        room = str(record.get("room") or "").strip()
        raw_text = str(record.get("text") or "").strip()

        # Ignore our own messages
        if sender == self.bot_name or sender == "Home Assistant":
            return

        # Case A: Handshake message
        if msg_type == "handshake":
            handled = await self._handle_handshake(record_id, room, raw_text)
            if handled:
                self._processed_record_ids.add(record_id)
                if len(self._processed_record_ids) > 1000:
                    self._processed_record_ids.clear()
            return

        # Case B: Chat message from a paired user
        paired_users = self.paired_users
        matched_user = None

        for uid, uinfo in paired_users.items():
            expected_room = derive_room_id(uid, self.bot_id)
            if room == expected_room or room == uinfo.get("room_id"):
                matched_user = (uid, uinfo)
                break

        if matched_user:
            self._processed_record_ids.add(record_id)
            if len(self._processed_record_ids) > 1000:
                self._processed_record_ids.clear()
            await self._handle_user_message(record_id, matched_user, room, sender, raw_text, record)

    async def _handle_handshake(self, record_id: str, room: str, raw_text: str) -> bool:
        """Processes incoming handshake from Adlos App."""
        try:
            payload = json.loads(raw_text) if raw_text.startswith("{") else {}
        except Exception:
            payload = {}

        if not isinstance(payload, dict):
            return False

        sender_id = str(payload.get("sender_id") or "").strip()
        sender_name = str(payload.get("sender_name") or "").strip() or sender_id
        room_key = str(payload.get("room_key") or "").strip()

        if not sender_id:
            return False

        # Verify whether this handshake room matches our bot_id
        expected_room = derive_room_id(sender_id, self.bot_id)
        if room != expected_room:
            # Handshake not for this bot
            return False

        _LOGGER.info(
            "ADLOS_PB: Received valid handshake from '%s' (%s) with room_key for room %s",
            sender_name, sender_id, room
        )

        # 1. Ephemeral relay: delete record from PocketBase immediately
        await self._delete_record(record_id)

        # 2. Persist user in Home Assistant config entry
        await self._save_paired_user(sender_id, sender_name, room_key, room)

        # 3. Fire Home Assistant event
        self.hass.bus.async_fire(
            EVENT_ADLOS_HANDSHAKE_RECEIVED,
            {
                "user_id": sender_id,
                "user_name": sender_name,
                "room_id": room,
                "has_key": bool(room_key),
            },
        )

        # 4. Create persistent notification in HA
        try:
            notification_msg = (
                f"### 🎉 Adlos-Kontakt gekoppelt!\n\n"
                f"**Name:** {sender_name}\n"
                f"**Kontakt-ID:** `{sender_id}`\n"
                f"**Raum-ID:** `{room}`\n\n"
                f"Home Assistant kann ab sofort Benachrichtigungen an **{sender_name}** senden "
                f"und auf Chat-Befehle antworten."
            )
            persistent_notification.async_create(
                self.hass,
                notification_msg,
                title="Adlos Kopplung erfolgreich",
                notification_id=f"adlos_paired_{sender_id}",
            )
        except Exception:
            pass

        # 5. Send welcome message to user in Adlos Chat
        if self.send_callback:
            welcome_text = f"Hallo {sender_name}! Home Assistant ist jetzt erfolgreich mit deiner Adlos-App gekoppelt. 🚀"
            asyncio.create_task(self.send_callback(room, welcome_text, room_key))

        return True

    async def _handle_user_message(
        self,
        record_id: str,
        matched_user: tuple[str, dict],
        room: str,
        sender: str,
        raw_text: str,
        raw_record: dict,
    ) -> None:
        """Processes an incoming chat message from a paired user."""
        user_id, uinfo = matched_user
        user_name = uinfo.get("name") or sender or user_id
        room_key = uinfo.get("room_key")

        # 1. Decrypt text if encrypted
        decrypted_text = decrypt_text(raw_text, room_key) if room_key else raw_text
        _LOGGER.info("ADLOS_PB: Incoming message from %s in %s: %s", user_name, room, decrypted_text)

        # 2. Ephemeral relay: delete record from PocketBase immediately
        await self._delete_record(record_id)

        # 3. Fire HA event
        self.hass.bus.async_fire(
            EVENT_ADLOS_MESSAGE_RECEIVED,
            {
                "user_id": user_id,
                "user_name": user_name,
                "room": room,
                "text": decrypted_text,
                "record": raw_record,
            },
        )

        # 4. Conversation API integration (Home Assistant Assist)
        await self._process_conversation(room, user_id, user_name, decrypted_text, room_key)

    async def _process_conversation(
        self,
        room: str,
        user_id: str,
        user_name: str,
        text: str,
        room_key: str | None,
    ) -> None:
        """Sends user message to HA Conversation agent and returns answer back to Adlos."""
        if not text:
            return

        try:
            from homeassistant.components import conversation
            if hasattr(conversation, "async_converse"):
                _LOGGER.debug("ADLOS_PB: Forwarding message to conversation.async_converse: %s", text)
                result = await conversation.async_converse(
                    self.hass,
                    text=text,
                    conversation_id=room,
                    context=None,
                )

                response_text = None
                if hasattr(result, "response") and result.response:
                    speech = getattr(result.response, "speech", {})
                    if isinstance(speech, dict):
                        response_text = speech.get("plain", {}).get("speech")
                elif isinstance(result, dict):
                    speech = result.get("response", {}).get("speech", {})
                    if isinstance(speech, dict):
                        response_text = speech.get("plain", {}).get("speech")

                if response_text and self.send_callback:
                    _LOGGER.info("ADLOS_PB: Assist response: %s", response_text)
                    await self.send_callback(room, response_text, room_key)
        except Exception as err:
            _LOGGER.debug("ADLOS_PB: Conversation processing error (Assist may not be configured): %s", err)

    async def _delete_record(self, record_id: str) -> bool:
        """Ephemeral relay: Deletes message/handshake record from PocketBase."""
        url = f"{self.server_url}/api/collections/messages/records/{record_id}"
        try:
            async with self.session.delete(url, headers=self._get_headers(), timeout=10) as resp:
                if resp.status in (200, 204):
                    _LOGGER.debug("ADLOS_PB: Ephemeral deleted record %s from PocketBase", record_id)
                    return True
                _LOGGER.warning("ADLOS_PB: Failed to delete record %s (HTTP %s)", record_id, resp.status)
        except Exception as err:
            _LOGGER.debug("ADLOS_PB: Exception deleting record %s: %s", record_id, err)
        return False

    async def _save_paired_user(
        self,
        user_id: str,
        user_name: str,
        room_key: str,
        room_id: str,
    ) -> None:
        """Updates integration config entry with new paired user."""
        current_users = dict(self.paired_users)
        current_users[user_id] = {
            "contact_id": user_id,
            "name": user_name,
            "room_key": room_key,
            "room_id": room_id,
        }

        # Also update target_contacts string for backwards compatibility
        cur_targets_raw = self.entry.options.get(CONF_TARGET_CONTACTS, self.entry.data.get(CONF_TARGET_CONTACTS, ""))
        targets_list = [t.strip() for t in cur_targets_raw.split(",") if t.strip()]
        if user_id not in targets_list:
            targets_list.append(user_id)

        new_options = dict(self.entry.options)
        new_options[CONF_PAIRED_USERS] = current_users
        new_options[CONF_TARGET_CONTACTS] = ", ".join(targets_list)

        self.hass.config_entries.async_update_entry(self.entry, options=new_options)
        _LOGGER.info("ADLOS_PB: Saved paired user %s. Total paired users: %s", user_name, len(current_users))
