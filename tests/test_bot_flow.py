"""The bot's handlers with fake Telegram objects: a big PDF sent as a split ZIP, in the wrong order."""

import asyncio
import itertools
import random
import shutil
import zipfile
from types import SimpleNamespace

import pytest

pytest.importorskip("telegram")
from telegram.error import BadRequest

from sheetmusic.bot import app as bot


class Msg:
    ids = itertools.count(100)

    def __init__(self, document=None, reply_to=None):
        self.message_id = next(Msg.ids)
        self.document, self.reply_to_message = document, reply_to
        self.texts, self.replies, self.sent, self.deleted, self.markup = [], [], [], False, None
        self.chat = SimpleNamespace(send_action=self._noop)

    async def _noop(self, *a, **k):
        pass

    async def reply_text(self, text, reply_markup=None, **k):
        m = Msg()
        m.texts, m.markup = [text], reply_markup
        self.replies.append(m)
        return m

    async def edit_text(self, text, **k):
        self.texts.append(text)

    async def delete(self):
        self.deleted = True

    async def reply_document(self, fh, filename=None, caption=None):
        self.sent.append((filename, fh.read(), caption))


def document(path, size=None, refuse=None):
    """`refuse`: the message of the BadRequest Telegram answers to getFile (None = it hands the file over)."""
    async def get_file():
        if refuse:
            raise BadRequest(refuse)
        return SimpleNamespace(download_to_drive=lambda dst: _copy(path, dst))

    async def _copy(src, dst):
        shutil.copyfile(src, dst)
    return SimpleNamespace(file_name=path.name, file_size=size or path.stat().st_size,
                           mime_type="application/octet-stream", get_file=get_file)


def context():
    return SimpleNamespace(chat_data={}, application=SimpleNamespace(bot_data={"allowed": set()}))


def update_with(doc):
    msg = Msg(document=doc)
    return SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=1)), msg


@pytest.fixture
def pieces(numbered_pdf, tmp_path):
    zip_path = tmp_path / "set.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        z.write(numbered_pdf, "set.pdf")
    data = zip_path.read_bytes()
    step = len(data) // 3 + 1
    out = []
    for i in range(3):
        p = tmp_path / f"set.zip.{i + 1:03d}"
        p.write_bytes(data[i * step:(i + 1) * step])
        out.append(p)
    return out


def test_split_zip_is_collected_assembled_and_processed(pieces, numbered_pdf):
    ctx = context()
    order = list(pieces)
    random.Random(1).shuffle(order)
    first, last = None, None

    async def scenario():
        nonlocal first, last
        for n, path in enumerate(order, 1):
            upd, msg = update_with(document(path))
            await bot.on_document(upd, ctx)
            if n < 3:
                first = first or msg.replies[0]
                assert "Waiting for the rest" in (msg.replies[0] if n == 1 else first).texts[-1]
            else:
                last = msg.replies[0]
        assert first.deleted                                           # the "waiting" note is gone
        assert "What should I do" in last.texts[0] and last.markup is not None
        sess = ctx.chat_data["assembled"][last.message_id]
        assert (sess.dir / "assembled.pdf").exists() and not ctx.chat_data["pieces"]

        answered = []
        async def answer(*a, **k):
            answered.append(a)
        query = SimpleNamespace(data="a4", message=last, answer=answer)
        await bot.on_choice(SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1)), ctx)
        return sess

    sess = asyncio.run(scenario())
    assert len(last.sent) == 1 and last.sent[0][0].endswith("_A4.pdf")
    assert last.sent[0][1][:4] == b"%PDF" and last.deleted            # the PDF came back, the keyboard message is gone
    assert not sess.dir.exists() and not ctx.chat_data["assembled"]    # nothing left on disk


def test_bad_pieces_are_reported_and_cancel_forgets_the_rest(tmp_path):
    ctx = context()
    junk = tmp_path / "x.001"
    junk.write_bytes(b"not a pdf and not a zip")
    waiting = tmp_path / "y.zip.002"
    waiting.write_bytes(b"PK\x03\x04 only the middle of something")

    async def scenario():
        upd, msg = update_with(document(junk))
        await bot.on_document(upd, ctx)
        assert "neither a ZIP nor a PDF" in msg.replies[0].texts[0] and not ctx.chat_data["pieces"]
        upd, msg = update_with(document(waiting))
        await bot.on_document(upd, ctx)
        assert "Waiting for the rest" in msg.replies[0].texts[0] and ctx.chat_data["pieces"]
        dirs = [s.dir for s in ctx.chat_data["pieces"].values()]
        upd, msg = update_with(document(waiting))
        await bot.cancel(upd, ctx)
        assert "Dropped" in msg.replies[0].texts[0] and not ctx.chat_data.get("pieces")
        return dirs

    assert not any(d.exists() for d in asyncio.run(scenario()))


def test_a_file_over_20_mb_is_refused_only_when_telegram_says_so(tmp_path):
    ctx = context()
    big = tmp_path / "scan.pdf"
    big.write_bytes(b"%PDF-1.4 stand-in")

    async def scenario():
        upd, msg = update_with(document(big, size=30 * bot.MB, refuse="File is too big"))     # Telegram says no
        await bot.on_document(upd, ctx)
        assert "cannot get a file this big" in msg.replies[0].texts[0] and "split" in msg.replies[0].texts[0].lower()
        assert msg.replies[0].markup is None
        upd, msg = update_with(document(big, size=30 * bot.MB))                               # Telegram says yes
        await bot.on_document(upd, ctx)
        assert msg.replies[0].texts[0] == "What should I do with it?" and msg.replies[0].markup is not None

    asyncio.run(scenario())


def test_other_telegram_errors_are_not_mistaken_for_too_big(tmp_path):
    big = tmp_path / "scan.pdf"
    big.write_bytes(b"x")

    async def scenario():
        upd, msg = update_with(document(big, size=30 * bot.MB, refuse="Bad Request: something else"))
        with pytest.raises(BadRequest):
            await bot.on_document(upd, context())

    asyncio.run(scenario())


def test_unknown_files_get_the_instructions(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_bytes(b"x")

    async def scenario():
        upd, msg = update_with(document(txt))
        await bot.on_document(upd, context())
        assert "Please send a PDF" in msg.replies[0].texts[0]

    asyncio.run(scenario())


class FakeBig:
    """Stands in for the MTProto downloader: 'downloads' by copying a local file."""
    def __init__(self, source):
        self.source, self.calls = source, []

    async def download(self, message_id, dst):
        self.calls.append(message_id)
        shutil.copyfile(self.source, dst)


def test_big_pdf_goes_over_mtproto_when_it_is_set_up(numbered_pdf, tmp_path):
    big = FakeBig(numbered_pdf)
    ctx = context()
    ctx.application.bot_data["big"] = big
    asked_http = []

    async def scenario():
        doc = document(numbered_pdf, size=30 * bot.MB, refuse="File is too big")      # the HTTP Bot API would refuse
        real_get_file = doc.get_file

        async def spy():
            asked_http.append(1)
            return await real_get_file()
        doc.get_file = spy
        upd, original = update_with(doc)
        await bot.on_document(upd, ctx)
        keyboard = original.replies[0]
        assert keyboard.texts[0] == "What should I do with it?" and keyboard.markup is not None
        keyboard.reply_to_message = original
        async def answer(*a, **k):
            pass
        query = SimpleNamespace(data="a4", message=keyboard, answer=answer)
        await bot.on_choice(SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1)), ctx)
        return original, keyboard

    original, keyboard = asyncio.run(scenario())
    assert big.calls == [original.message_id] and not asked_http           # MTProto fetched it, HTTP was never asked
    assert len(original.sent) == 1 and original.sent[0][1][:4] == b"%PDF"  # and the job ran on the downloaded file
    assert any("Downloading 30 MB" in t for t in keyboard.texts)


def test_a_file_over_the_mtproto_limit_is_still_refused(tmp_path):
    f = tmp_path / "huge.pdf"
    f.write_bytes(b"x")
    ctx = context()
    ctx.application.bot_data["big"] = FakeBig(f)

    async def scenario():
        upd, msg = update_with(document(f, size=2100 * bot.MB))
        await bot.on_document(upd, ctx)
        assert "cannot get a file this big" in msg.replies[0].texts[0] and msg.replies[0].markup is None

    asyncio.run(scenario())


def test_mtproto_downloader_fetches_the_message_by_id(tmp_path):
    from sheetmusic.bot.mtproto import BigDownloader

    class Client:
        def __init__(self, message):
            self.message, self.log = message, []

        async def get_messages(self, entity, ids):
            self.log.append(("get_messages", entity, ids))
            return self.message

        async def download_media(self, message, file):
            self.log.append(("download_media", file))

    async def scenario():
        ok = Client(SimpleNamespace(media=object()))
        await BigDownloader(1, "h", "t", client=ok).download(77, tmp_path / "x.pdf")
        assert ok.log == [("get_messages", None, 77), ("download_media", str(tmp_path / "x.pdf"))]
        for gone in (None, SimpleNamespace(media=None)):
            with pytest.raises(RuntimeError, match="no file"):
                await BigDownloader(1, "h", "t", client=Client(gone)).download(77, tmp_path / "y.pdf")

    asyncio.run(scenario())
