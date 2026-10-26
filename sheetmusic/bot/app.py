"""Telegram handlers.

Env (read from the environment or a .env file, see .env.example):
     TELEGRAM_BOT_TOKEN   required, from @BotFather
     ALLOWED_USERS        optional, comma separated Telegram user ids; empty = anyone
     TELEGRAM_API_ID / TELEGRAM_API_HASH
                          optional, from https://my.telegram.org: lets the bot receive PDFs above 20 MB

Through the HTTP Bot API a bot can download files up to 20 MB and upload up to 50 MB. Bigger PDFs are fetched
over MTProto when TELEGRAM_API_ID / TELEGRAM_API_HASH are set (mtproto.py, up to 2 GB); without them the user
is asked for a split ZIP (several files of at most 20 MB each), which is put back together here (archives.py)."""

import asyncio
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from ..ocr import OcrUnavailable
from . import archives
from .jobs import MODES, RUNNERS, safe_name
from .mtproto import MAX_BIG, BigDownloader

MB = 1024 * 1024
MAX_DOWNLOAD = 20 * MB                  # Telegram documents this as the most a bot can fetch; from here we ask
SESSION_TTL = 3600                      # seconds before pieces of an unfinished archive are thrown away

HOW_TO_SPLIT = (
    "Over 20 MB? Send it as a split ZIP: pieces of at most 20 MB each, all in one go, in any order.\n"
    "• 7-Zip / Keka: Add to archive → format zip → “Split to volumes” 15M  (name.zip.001, .002 …)\n"
    "• Terminal: zip -s 15m name.zip big.pdf  (name.z01, name.z02, name.zip)")

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
        f"• {MODES['parts']}\n• {MODES['a4']}\n• {MODES['contrast']}\n\n" + HOW_TO_SPLIT)


async def cannot_fetch(context: ContextTypes.DEFAULT_TYPE, doc) -> bool:
    """True if there is no way to get this file. Above MAX_DOWNLOAD the HTTP Bot API is asked (its answer is
    Telegram's, not a guess of ours); when the MTProto downloader is set up it takes over instead."""
    if not doc.file_size or doc.file_size <= MAX_DOWNLOAD:
        return False
    if context.application.bot_data.get("big") is not None:
        return doc.file_size > MAX_BIG
    try:
        await doc.get_file()
    except BadRequest as exc:
        log.info("getFile for %.1f MB refused: %s", doc.file_size / MB, exc)
        if "too big" in str(exc).lower():
            return True
        raise
    log.info("getFile for %.1f MB accepted", doc.file_size / MB)
    return False


async def fetch(context: ContextTypes.DEFAULT_TYPE, message, dst: Path) -> None:
    """Save the document of `message` as `dst`: over the HTTP Bot API, or over MTProto when it is too big for that."""
    doc, big = message.document, context.application.bot_data.get("big")
    if big is not None and doc.file_size and doc.file_size > MAX_DOWNLOAD:
        log.info("downloading %.1f MB over MTProto", doc.file_size / MB)
        await big.download(message.message_id, dst)
    else:
        await (await doc.get_file()).download_to_drive(dst)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        return
    doc = update.message.document
    name = doc.file_name or ""
    is_pdf = doc.mime_type == "application/pdf" or name.lower().endswith(".pdf")
    if not is_pdf and not archives.is_piece(name):
        await update.message.reply_text("Please send a PDF file.\n\n" + HOW_TO_SPLIT)
        return
    if await cannot_fetch(context, doc):
        await update.message.reply_text(f"I cannot get a file this big ({doc.file_size / MB:.1f} MB).\n\n" + HOW_TO_SPLIT)
        return
    if is_pdf:
        await update.message.reply_text("What should I do with it?", reply_markup=KEYBOARD,
                                        reply_to_message_id=update.message.message_id)
    else:
        await on_piece(update, context)


class Pieces:
    """The files received so far for one split archive."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="sheetbot-"))
        self.files: dict[str, Path] = {}
        self.status = None                          # the message that says what is still missing
        self.created = time.monotonic()

    def discard(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def _purge(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forget (and delete) unfinished archives and unused assembled PDFs that are older than SESSION_TTL."""
    chat = context.chat_data
    for store in (chat.get("pieces", {}), chat.get("assembled", {})):
        for k, item in list(store.items()):
            if time.monotonic() - item.created > SESSION_TTL:
                item.discard()
                del store[k]


async def on_piece(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """One file of a split archive: keep it, and when the archive is complete offer the actions."""
    _purge(context)
    doc = update.message.document
    pieces = context.chat_data.setdefault("pieces", {})
    k = archives.key(doc.file_name)
    sess = pieces.setdefault(k, Pieces())
    path = sess.dir / safe_name(doc.file_name)
    await fetch(context, update.message, path)
    sess.files[doc.file_name] = path
    try:
        found = await asyncio.to_thread(archives.assemble, sess.files, sess.dir / "assembled.pdf")
    except ValueError as exc:
        del pieces[k]
        sess.discard()
        await update.message.reply_text(f"{exc}\n\nSend /start for the instructions.")
        return
    except Exception:
        log.exception("could not read the pieces")
        del pieces[k]
        sess.discard()
        await update.message.reply_text("Could not read those files.")
        return
    count = len(sess.files)
    if found is None:
        text = f"Got {count} file{'s' if count != 1 else ''} of “{k}”. Waiting for the rest (/cancel to start over)."
        if sess.status is None:
            sess.status = await update.message.reply_text(text)
        else:
            await _edit(sess.status, text)
        return
    del pieces[k]
    if sess.status is not None:
        await sess.status.delete()
    msg = await update.message.reply_text(f"Put {count} file{'s' if count != 1 else ''} together: {found}.\n"
                                          "What should I do with it?", reply_markup=KEYBOARD)
    context.chat_data.setdefault("assembled", {})[msg.message_id] = sess


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        return
    sessions = list(context.chat_data.pop("pieces", {}).values())
    for sess in sessions:
        sess.discard()
    await update.message.reply_text("Dropped the files I was waiting on." if sessions else "Nothing to cancel.")


async def on_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _allowed(update, context):
        await query.answer()
        return
    mode = query.data
    original = query.message.reply_to_message
    assembled = context.chat_data.get("assembled", {}).get(query.message.message_id)
    if mode not in RUNNERS or (assembled is None and (original is None or original.document is None)):
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
                if assembled is not None:
                    src = assembled.dir / "assembled.pdf"
                else:
                    src = tmp / (safe_name(Path(original.document.file_name or "input.pdf").stem) + ".pdf")
                    if original.document.file_size and original.document.file_size > MAX_DOWNLOAD:
                        await _edit(status, f"Downloading {original.document.file_size / MB:.0f} MB …")
                    await fetch(context, original, src)
                    await _edit(status, f"Working: {MODES[mode]} …")
                out_dir = tmp / "out"
                out_dir.mkdir()
                reply_to = status if assembled is not None else original
                await status.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
                files, summary = await asyncio.to_thread(RUNNERS[mode], src, out_dir, progress)
                for n, dst in enumerate(files, 1):
                    note = summary if n == 1 else f"{summary.splitlines()[0]} — file {n} of {len(files)}"
                    if len(files) > 1 and n == 1:
                        note = f"{summary}\n\nToo big for one message: {len(files)} files."
                    with dst.open("rb") as fh:
                        await reply_to.reply_document(fh, filename=safe_name(dst.name), caption=note[:1000])
            await status.delete()
        except OcrUnavailable:
            log.exception("tesseract missing")
            await _edit(status, "OCR is not available on the server (Tesseract missing).")
        except Exception:
            log.exception("processing failed")
            await _edit(status, "Could not process this PDF.")
        finally:
            if assembled is not None:
                assembled.discard()
                context.chat_data["assembled"].pop(status.message_id, None)


async def on_start(app: Application) -> None:
    await set_commands(app)
    big = app.bot_data.get("big")
    if big is not None:
        try:
            await big.start()
            log.info("MTProto connection ready: PDFs up to %d MB are accepted", MAX_BIG // MB)
        except Exception:
            log.exception("MTProto login failed (check TELEGRAM_API_ID / TELEGRAM_API_HASH): files above 20 MB stay off")
            app.bot_data["big"] = None


async def on_stop(app: Application) -> None:
    if app.bot_data.get("big") is not None:
        await app.bot_data["big"].stop()


async def set_commands(app: Application) -> None:
    """Fill the '/' command menu shown in the Telegram client."""
    await app.bot.set_my_commands([
        BotCommand("start", "What this bot can do"),
        BotCommand("help", "How to use it, and how to send a PDF over 20 MB"),
        BotCommand("cancel", "Forget the files of a split ZIP I am waiting on"),
    ])


def build_application(token: str, allowed: set[int] | None = None, big=None) -> Application:
    app = Application.builder().token(token).post_init(on_start).post_shutdown(on_stop).build()
    app.bot_data["allowed"] = allowed or set()
    app.bot_data["big"] = big                     # a BigDownloader, or None: files above 20 MB need the split-ZIP route
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(CallbackQueryHandler(on_choice))
    return app


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))        # real environment variables win over .env
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)   # its INFO lines print every URL, token included
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("error: set TELEGRAM_BOT_TOKEN (create a bot with @BotFather)")
    allowed = {int(u) for u in re.split(r"[,\s]+", os.environ.get("ALLOWED_USERS", "")) if u}
    big = None
    api_id, api_hash = os.environ.get("TELEGRAM_API_ID"), os.environ.get("TELEGRAM_API_HASH")
    if api_id and api_hash:
        try:
            big = BigDownloader(int(api_id), api_hash, token)
        except Exception:
            log.exception("could not set up the MTProto downloader: files above 20 MB stay off")
    else:
        log.info("TELEGRAM_API_ID / TELEGRAM_API_HASH not set: PDFs above 20 MB must come as a split ZIP")
    build_application(token, allowed, big).run_polling()
