"""Downloads of files above the 20 MB that the HTTP Bot API hands out.

Telegram's apps (and bots speaking the normal MTProto protocol) can fetch files up to 2 GB; only the HTTP Bot API
refuses them. So for big files the same bot also logs in over MTProto (Telethon) and fetches the message by id.
Needs an api_id / api_hash from https://my.telegram.org (the bot token is the one the bot already has)."""

import logging
from pathlib import Path

log = logging.getLogger("sheetmusic.bot")

MAX_BIG = 2000 * 1024 * 1024            # what Telegram allows for a (non-premium) file


class BigDownloader:
    def __init__(self, api_id: int, api_hash: str, bot_token: str, client=None):
        if client is None:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            client = TelegramClient(StringSession(), api_id, api_hash)
        self._client, self._token = client, bot_token

    async def start(self) -> None:
        await self._client.start(bot_token=self._token)

    async def stop(self) -> None:
        await self._client.disconnect()

    async def download(self, message_id: int, dst: Path) -> None:
        """Save the file attached to message `message_id` of the bot's chats (ids are the same ones the
        Bot API reports) as `dst`."""
        message = await self._client.get_messages(None, ids=message_id)       # private chats: ids are global
        if message is None or not getattr(message, "media", None):
            raise RuntimeError(f"message {message_id} has no file for MTProto to download")
        await self._client.download_media(message, file=str(dst))
