"""Telegram handlers.

Env (read from the environment or a .env file, see .env.example):
     TELEGRAM_BOT_TOKEN   required, from @BotFather
     ALLOWED_USERS        optional, comma separated Telegram user ids; empty = anyone

Telegram bots can download files up to 20 MB and upload up to 50 MB."""

import asyncio
import logging
import os
import re
import tempfile
import time
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from ..ocr import OcrUnavailable
from .jobs import MODES, RUNNERS, safe_name

MAX_DOWNLOAD = 20 * 1024 * 1024
MAX_UPLOAD = 50 * 1024 * 1024

KEYBOARD = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=mode)] for mode, label in MODES.items()])

log = logging.getLogger("sheetmusic.bot")
busy = asyncio.Semaphore(1)   # OCR / rendering is CPU heavy: one job at a time


def _allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    allowed = context.application.bot_data.get("allowed", set())
    user = update.effective_user
    return not allowed or (user is not None and user.id in allowed)


async def _edit(message, text: str) -> None:
    """edit_text that tolerates Telegram's 'message is not modified' error."""
    try:
        await message.edit_text(text)
    except BadRequest as exc:
        if "not modified" not in str(exc):
            raise


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        return
    await update.message.reply_text(
        "Send me a PDF of sheet music (as a file) and choose what to do:\n"
        f"• {MODES['parts']}\n• {MODES['a4']}\n• {MODES['contrast']}\n\n"
        "Limit: 20 MB per PDF.")


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        return
    doc = update.message.document
    if doc.mime_type != "application/pdf" and not (doc.file_name or "").lower().endswith(".pdf"):
        await update.message.reply_text("Please send a PDF file.")
        return
    if doc.file_size and doc.file_size > MAX_DOWNLOAD:
        await update.message.reply_text("Telegram only lets bots download files up to 20 MB. "
                                        "Compress the PDF or send it in smaller pieces.")
        return
    await update.message.reply_text("What should I do with it?", reply_markup=KEYBOARD,
                                    reply_to_message_id=update.message.message_id)


async def on_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _allowed(update, context):
        await query.answer()
        return
    mode = query.data
    original = query.message.reply_to_message
    if mode not in RUNNERS or original is None or original.document is None:
        await query.answer("Please send the PDF again.", show_alert=True)
        return
    await query.answer()
    status = query.message
    await _edit(status, f"Queued: {MODES[mode]}" if busy.locked() else f"Working: {MODES[mode]} …")

    loop = asyncio.get_running_loop()
    last = [0.0]

    def progress(done: int, total: int) -> None:   # called from the worker thread
        if time.monotonic() - last[0] < 5:
            return
        last[0] = time.monotonic()
        asyncio.run_coroutine_threadsafe(
            _edit(status, f"Working: {MODES[mode]} … page {done}/{total}"), loop)

    async with busy:
        await _edit(status, f"Working: {MODES[mode]} …")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                src = tmp / (safe_name(Path(original.document.file_name or "input.pdf").stem) + ".pdf")
                await (await original.document.get_file()).download_to_drive(src)
                out_dir = tmp / "out"
                out_dir.mkdir()
                await original.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
                dst, summary = await asyncio.to_thread(RUNNERS[mode], src, out_dir, progress)
                if dst.stat().st_size > MAX_UPLOAD:
                    await _edit(status, "The result is larger than 50 MB, which Telegram does not "
                                        "allow bots to send.")
                    return
                with dst.open("rb") as fh:
                    await original.reply_document(fh, filename=safe_name(dst.name), caption=summary[:1000])
            await status.delete()
        except OcrUnavailable:
            log.exception("tesseract missing")
            await _edit(status, "OCR is not available on the server (Tesseract missing).")
        except Exception:
            log.exception("processing failed")
            await _edit(status, "Could not process this PDF.")


async def set_commands(app: Application) -> None:
    """Fill the '/' command menu shown in the Telegram client."""
    await app.bot.set_my_commands([
        BotCommand("start", "What this bot can do"),
        BotCommand("help", "How to use it and file size limits"),
    ])


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))        # real environment variables win over .env
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)   # its INFO lines print every URL, token included
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("error: set TELEGRAM_BOT_TOKEN (create a bot with @BotFather)")
    app = Application.builder().token(token).post_init(set_commands).build()
    app.bot_data["allowed"] = {int(u) for u in re.split(r"[,\s]+", os.environ.get("ALLOWED_USERS", "")) if u}
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(CallbackQueryHandler(on_choice))
    app.run_polling()
