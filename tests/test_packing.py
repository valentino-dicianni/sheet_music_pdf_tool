"""Results over Telegram's per-file limit come back as several ZIPs, or as volumes of one big ZIP."""

import os
import zipfile

from sheetmusic.bot import archives
from sheetmusic.bot.packing import pack

LIMIT = 10 * 1024


def blobs(tmp_path, sizes):
    files = []
    for i, size in enumerate(sizes):
        f = tmp_path / f"part{i}.pdf"
        f.write_bytes(os.urandom(size))
        files.append(f)
    return files


def names_in(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        return z.namelist()


def test_everything_fits_in_one_zip(tmp_path):
    out = pack(blobs(tmp_path, [2000, 3000]), "Set", tmp_path / "send", LIMIT)
    assert [p.name for p in out] == ["Set.zip"] and names_in(out[0]) == ["part0.pdf", "part1.pdf"]


def test_one_small_file_can_go_as_itself(tmp_path):
    files = blobs(tmp_path, [2000])
    assert pack(files, "Set", tmp_path / "send", LIMIT, as_zip=False) == files


def test_parts_are_grouped_in_order_into_zips_under_the_limit(tmp_path):
    out = pack(blobs(tmp_path, [4000, 4000, 4000, 4000, 4000]), "Set", tmp_path / "send", LIMIT)
    assert [p.name for p in out] == ["Set (1 of 3).zip", "Set (2 of 3).zip", "Set (3 of 3).zip"]
    assert all(p.stat().st_size <= LIMIT for p in out)
    assert [names_in(p) for p in out] == [["part0.pdf", "part1.pdf"], ["part2.pdf", "part3.pdf"], ["part4.pdf"]]


def test_a_file_bigger_than_the_limit_becomes_volumes_that_join_again(tmp_path):
    (big,) = blobs(tmp_path, [35000])
    out = pack([big], "Big", tmp_path / "send", LIMIT, as_zip=False)
    assert [p.name for p in out] == [f"Big.zip.{i:03d}" for i in range(1, 5)]
    assert all(p.stat().st_size <= LIMIT for p in out)
    # ... and they are exactly what the bot itself accepts as input
    result = tmp_path / "joined.pdf"
    assert archives.assemble({p.name: p for p in out}, result) is not None
    assert result.read_bytes() == big.read_bytes()
