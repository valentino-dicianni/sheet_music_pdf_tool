"""A PDF too big for a bot to download in one go (Telegram: 20 MB per file), sent in pieces.

Accepted ways to send it:
  * a split ZIP from Info-ZIP / Windows / macOS:        name.z01, name.z02, ..., name.zip
  * a split ZIP from 7-Zip / Keka / WinRAR "volumes":    name.zip.001, name.zip.002, ...
  * a PDF cut into raw pieces (e.g. with `split`):      name.pdf.001, name.pdf.002, ...
  * a normal ZIP that fits in one file:                  name.zip

The pieces may arrive in any order; `assemble` says "not yet" (None) until everything is there.
Pure Python, no Telegram: easy to test."""

import re
import shutil
import struct
import zipfile
from pathlib import Path

MB = 1024 * 1024
MAX_PDF = 500 * MB                      # refuse to unpack more than this (zip bombs)

_Z = re.compile(r"^(?P<stem>.+)\.z(?P<n>\d{2,})$", re.I)                              # name.z01
_NUM = re.compile(r"^(?P<stem>.+?)(?P<ext>\.(?:zip|pdf))?\.(?P<n>\d{3,})$", re.I)    # name.zip.001, name.001
_ZIP = re.compile(r"^(?P<stem>.+)\.zip$", re.I)                                       # name.zip
_EOCD = struct.Struct("<HHHHII")        # fields of the end-of-central-directory record after its signature


def _mb(n: int) -> str:
    return f"{n / MB:.1f} MB"


def is_piece(name: str) -> bool:
    return any(p.match(name) for p in (_Z, _NUM, _ZIP))


def key(name: str) -> str:
    """Files with the same key belong to one archive ('set.z01', 'set.zip', 'set.zip.001' -> 'set')."""
    for pattern in (_Z, _NUM, _ZIP):
        m = pattern.match(name)
        if m:
            return m["stem"].lower()
    return name.lower()


def assemble(files: dict[str, Path], out: Path) -> str | None:
    """Try to build the PDF `out` from the pieces received so far (name -> path).

    Returns a short description when done, None while pieces are still missing, and raises
    ValueError (with a message for the user) when the pieces cannot be a valid archive."""
    zparts: dict[int, Path] = {}
    numbered: dict[int, Path] = {}
    zips: list[Path] = []
    for name, path in files.items():
        if m := _Z.match(name):
            zparts[int(m["n"])] = path
        elif m := _NUM.match(name):
            numbered[int(m["n"])] = path
        elif _ZIP.match(name):
            zips.append(path)
        else:
            raise ValueError(f"I don't know what to do with {name!r}.")
    if numbered:
        return _assemble_numbered(numbered, out)
    if not zips:
        return None                                      # only .z01 ... so far: the .zip comes last
    last = zips[-1]
    eocd = _read_eocd(last)
    if eocd["this_disk"] == 0 and not zparts:
        return _extract_pdf(last, out)                   # an ordinary, unsplit ZIP
    need = range(1, eocd["this_disk"] + 1)               # .z01 ... .zNN come before the .zip
    if any(n not in zparts for n in need):
        return None
    joined = out.with_suffix(".joined")
    try:
        _join_split_zip([zparts[n] for n in need] + [last], joined)
        return _extract_pdf(joined, out)
    finally:
        joined.unlink(missing_ok=True)


def _assemble_numbered(numbered: dict[int, Path], out: Path) -> str | None:
    last_n = max(numbered)
    if any(n not in numbered for n in range(1, last_n + 1)):
        return None                                      # a piece is missing (or the first one is still to come)
    tail = _tail(numbered[last_n], 70 * 1024)
    head = numbered[1].open("rb").read(4)
    if head[:2] == b"PK":
        if b"PK\x05\x06" not in tail:
            return None                                  # the last piece (with the directory) has not arrived
    elif head == b"%PDF":
        if b"%%EOF" not in tail[-2048:]:
            return None
    else:
        raise ValueError("Those pieces are neither a ZIP nor a PDF.")
    joined = out.with_suffix(".joined")
    try:
        _concat([numbered[n] for n in range(1, last_n + 1)], joined)
        if head[:2] == b"PK":
            e = _read_eocd(joined)
            if e["eocd_pos"] + 22 + e["comment_len"] != joined.stat().st_size or e["cd_off"] + e["cd_size"] != e["eocd_pos"]:
                return None                              # the size does not add up: pieces are missing
            return _extract_pdf(joined, out)
        shutil.move(joined, out)
        return f"PDF ({_mb(out.stat().st_size)})"
    finally:
        joined.unlink(missing_ok=True)


def _tail(path: Path, n: int) -> bytes:
    with path.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(f.tell() - n, 0))
        return f.read()


def _concat(parts: list[Path], dst: Path) -> None:
    with dst.open("wb") as w:
        for p in parts:
            with p.open("rb") as r:
                shutil.copyfileobj(r, w, 1024 * 1024)


def _read_eocd(path: Path) -> dict:
    """The end-of-central-directory record of a ZIP (in its last bytes)."""
    data = _tail(path, 65535 + 22 + 64)
    i = data.rfind(b"PK\x05\x06")
    if i < 0 or len(data) < i + 22:
        raise ValueError(f"{path.name} is not a ZIP archive.")
    this_disk, cd_disk, here, total, cd_size, cd_off = _EOCD.unpack_from(data, i + 4)
    (comment_len,) = struct.unpack_from("<H", data, i + 20)
    size = path.stat().st_size
    return dict(this_disk=this_disk, cd_disk=cd_disk, total=total, cd_size=cd_size, cd_off=cd_off,
                comment_len=comment_len, eocd_pos=size - len(data) + i)


def _join_split_zip(segments: list[Path], out: Path) -> None:
    """name.z01 + name.z02 + ... + name.zip -> one ordinary ZIP: the directory refers to (disk, offset)
    pairs, which become plain offsets into the joined file."""
    starts, pos = [], 0                                  # where each disk begins in the joined file
    for s in segments:
        starts.append(pos)
        pos += s.stat().st_size
    _concat(segments, out)
    e = _read_eocd(out)
    if e["cd_disk"] >= len(segments):
        raise ValueError("The ZIP pieces do not belong together.")
    cd_abs = starts[e["cd_disk"]] + e["cd_off"]
    with out.open("r+b") as f:
        f.seek(cd_abs)
        cd = bytearray(f.read(e["cd_size"]))
        p = 0
        while p < len(cd):
            if cd[p:p + 4] != b"PK\x01\x02":
                raise ValueError("The ZIP archive is damaged.")
            name_len, extra_len, comment_len = struct.unpack_from("<HHH", cd, p + 28)
            (disk,) = struct.unpack_from("<H", cd, p + 34)
            (offset,) = struct.unpack_from("<I", cd, p + 42)
            if offset == 0xFFFFFFFF or disk >= len(segments):
                raise ValueError("That ZIP is too big or not supported (ZIP64).")
            struct.pack_into("<H", cd, p + 34, 0)
            struct.pack_into("<I", cd, p + 42, starts[disk] + offset)
            p += 46 + name_len + extra_len + comment_len
        f.seek(cd_abs)
        f.write(cd)
        f.seek(e["eocd_pos"] + 4)
        f.write(_EOCD.pack(0, 0, e["total"], e["total"], e["cd_size"], cd_abs))


def _extract_pdf(zip_path: Path, out: Path) -> str:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            pdfs = [i for i in zf.infolist()
                    if not i.is_dir() and i.filename.lower().endswith(".pdf")
                    and not i.filename.startswith("__MACOSX/") and not Path(i.filename).name.startswith("._")]
            if not pdfs:
                raise ValueError("There is no PDF in that archive.")
            if len(pdfs) > 1:
                raise ValueError(f"That archive holds {len(pdfs)} PDFs: send one PDF per archive.")
            info = pdfs[0]
            if info.file_size > MAX_PDF:
                raise ValueError(f"That PDF is too big ({_mb(info.file_size)}, the limit is {_mb(MAX_PDF)}).")
            with zf.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            return f"{Path(info.filename).name} ({_mb(info.file_size)})"
    except zipfile.BadZipFile as exc:
        raise ValueError("The ZIP archive is damaged (or pieces are missing).") from exc
