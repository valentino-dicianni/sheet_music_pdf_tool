"""A PDF sent in pieces (split ZIP) is put back together byte for byte, whatever order the pieces arrive in."""

import itertools
import os
import shutil
import subprocess
import zipfile

import pytest
from PIL import Image

from sheetmusic.bot import archives

PIECE = 64 * 1024                      # the smallest split Info-ZIP allows


@pytest.fixture(scope="module")
def pdf_bytes(tmp_path_factory):
    """A PDF of incompressible noise (like a scan): ~240 KB, so a 64 KB split gives 4 pieces."""
    path = tmp_path_factory.mktemp("noise") / "big.pdf"
    pages = [Image.frombytes("L", (200, 300), os.urandom(200 * 300)) for _ in range(4)]
    pages[0].save(path, "PDF", save_all=True, append_images=pages[1:], resolution=72.0)
    return path.read_bytes()


def split_raw(data, dst, name):
    """name.001, name.002, ... (what 7-Zip / Keka / `split` write)"""
    out = []
    for i in range(0, len(data), PIECE):
        p = dst / f"{name}.{i // PIECE + 1:03d}"
        p.write_bytes(data[i:i + PIECE])
        out.append(p)
    return out


def make_zip(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def feed(pieces, out):
    """Hand the pieces over one by one; nothing may come out before the last one."""
    got, result = {}, None
    for n, p in enumerate(pieces, 1):
        got[p.name] = p
        result = archives.assemble(got, out)
        if n < len(pieces):
            assert result is None and not out.exists(), f"finished too early after {n} of {len(pieces)} pieces"
    return result


def every_order(pieces):
    return itertools.permutations(pieces)


def test_names():
    assert [archives.is_piece(n) for n in ("a.z01", "a.zip", "a.zip.001", "a.pdf.002", "a.001", "a.pdf", "a.txt")] == \
        [True, True, True, True, True, False, False]
    assert {archives.key(n) for n in ("Set.z01", "set.zip", "SET.zip.003", "set.pdf.001")} == {"set"}


@pytest.mark.parametrize("name", ["set.zip", "set.pdf"])
def test_raw_pieces_in_any_order(pdf_bytes, tmp_path, name):
    data = pdf_bytes if name.endswith(".pdf") else make_zip(tmp_path / "x.zip", {"big.pdf": pdf_bytes}).read_bytes()
    pieces = split_raw(data, tmp_path, name)
    assert len(pieces) >= 3
    for order in every_order(pieces):
        out = tmp_path / "out.pdf"
        out.unlink(missing_ok=True)
        assert feed(list(order), out)
        assert out.read_bytes() == pdf_bytes


def test_an_ordinary_zip(pdf_bytes, tmp_path):
    z = make_zip(tmp_path / "set.zip", {"scores/big.pdf": pdf_bytes, "__MACOSX/._big.pdf": b"junk", "readme.txt": b"hi"})
    out = tmp_path / "out.pdf"
    assert archives.assemble({z.name: z}, out).startswith("big.pdf")
    assert out.read_bytes() == pdf_bytes


@pytest.mark.skipif(not shutil.which("zip"), reason="needs Info-ZIP")
def test_info_zip_split_archive_in_any_order(pdf_bytes, tmp_path):
    (tmp_path / "big.pdf").write_bytes(pdf_bytes)
    (tmp_path / "junk.bin").write_bytes(os.urandom(100 * 1024))        # first, so the PDF starts on the 2nd disk
    subprocess.run(["zip", "-q", "-s", f"{PIECE // 1024}k", "set.zip", "junk.bin", "big.pdf"], cwd=tmp_path, check=True)
    pieces = sorted(tmp_path.glob("set.z*"))
    assert len(pieces) >= 4
    for order in every_order(pieces):
        out = tmp_path / "out.pdf"
        out.unlink(missing_ok=True)
        assert feed(list(order), out)
        assert out.read_bytes() == pdf_bytes


@pytest.mark.skipif(not shutil.which("7z"), reason="needs 7-Zip")
def test_7zip_volumes_in_any_order(pdf_bytes, tmp_path):
    (tmp_path / "big.pdf").write_bytes(pdf_bytes)
    (tmp_path / "junk.bin").write_bytes(os.urandom(100 * 1024))
    subprocess.run(["7z", "a", "-tzip", f"-v{PIECE // 1024}k", "-bd", "-y", "set.zip", "junk.bin", "big.pdf"],
                   cwd=tmp_path, check=True, capture_output=True)
    pieces = sorted(tmp_path.glob("set.zip.*"))
    assert len(pieces) >= 3
    for order in every_order(pieces):
        out = tmp_path / "out.pdf"
        out.unlink(missing_ok=True)
        assert feed(list(order), out)
        assert out.read_bytes() == pdf_bytes


def test_a_missing_middle_piece_is_waited_for_not_guessed(pdf_bytes, tmp_path):
    pieces = split_raw(make_zip(tmp_path / "x.zip", {"big.pdf": pdf_bytes}).read_bytes(), tmp_path, "set.zip")
    got = {p.name: p for p in (pieces[0], pieces[-1])}                 # first and last, nothing between
    assert archives.assemble(got, tmp_path / "out.pdf") is None and not (tmp_path / "out.pdf").exists()


def test_bad_input_gets_a_clear_message(pdf_bytes, tmp_path):
    out = tmp_path / "out.pdf"
    two = make_zip(tmp_path / "two.zip", {"a.pdf": pdf_bytes, "b.pdf": pdf_bytes})
    with pytest.raises(ValueError, match="2 PDFs"):
        archives.assemble({two.name: two}, out)
    none = make_zip(tmp_path / "none.zip", {"notes.txt": b"x"})
    with pytest.raises(ValueError, match="no PDF"):
        archives.assemble({none.name: none}, out)
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"this is not a zip" * 100)
    with pytest.raises(ValueError, match="not a ZIP"):
        archives.assemble({junk.name: junk}, out)
    raw = tmp_path / "set.001"
    raw.write_bytes(b"neither a PDF nor a ZIP")
    with pytest.raises(ValueError, match="neither"):
        archives.assemble({raw.name: raw}, out)
    damaged = bytearray(make_zip(tmp_path / "ok.zip", {"big.pdf": pdf_bytes}).read_bytes())
    damaged[1000] ^= 0xFF                                              # flip a byte inside the stored PDF
    bad = tmp_path / "bad.zip"
    bad.write_bytes(damaged)
    with pytest.raises(ValueError, match="damaged"):
        archives.assemble({bad.name: bad}, out)


def test_too_big_to_unpack_is_refused(pdf_bytes, tmp_path, monkeypatch):
    z = make_zip(tmp_path / "set.zip", {"big.pdf": pdf_bytes})
    monkeypatch.setattr(archives, "MAX_PDF", 1000)
    with pytest.raises(ValueError, match="too big"):
        archives.assemble({z.name: z}, tmp_path / "out.pdf")
