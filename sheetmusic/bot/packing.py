"""Results too big for one Telegram message (bots can send 50 MB per file): several ZIPs, each small enough.

The parts are grouped in order into as few ZIPs as possible ("Title (1 of 3).zip" ...). A single file that is
bigger than the limit on its own is zipped and cut into volumes (name.zip.001, name.zip.002, ...), which any
unzip tool joins again (the same shape the bot accepts as input)."""

import zipfile
from pathlib import Path

MB = 1024 * 1024
SEND_LIMIT = 48 * MB                    # Telegram allows 50 MB per file: leave some room for ZIP overhead
_ENTRY_OVERHEAD = 512                   # generous size of an entry's headers inside a ZIP


def pack(files: list[Path], base: str, out_dir: Path, limit: int = SEND_LIMIT, as_zip: bool = True) -> list[Path]:
    """The files to send for `files`. One file that fits is sent as it is (unless `as_zip`); everything else
    is zipped in groups of at most `limit` bytes. `base` names the ZIPs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if len(files) == 1 and not as_zip and files[0].stat().st_size <= limit:
        return files
    groups: list[list[Path]] = []
    size = 0
    for f in files:
        need = f.stat().st_size + _ENTRY_OVERHEAD
        if not groups or size + need > limit:
            groups.append([])
            size = 0
        groups[-1].append(f)
        size += need
    zips = []
    for i, group in enumerate(groups, 1):
        name = f"{base}.zip" if len(groups) == 1 else f"{base} ({i} of {len(groups)}).zip"
        path = out_dir / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:       # PDFs are already compressed
            for f in group:
                z.write(f, f.name)
        zips.extend(_volumes(path, limit) if path.stat().st_size > limit else [path])
    return zips


def _volumes(path: Path, limit: int) -> list[Path]:
    """name.zip -> name.zip.001, name.zip.002, ... of at most `limit` bytes each (the ZIP itself is removed)."""
    volumes = []
    with path.open("rb") as src:
        n = 0
        while chunk := src.read(limit):
            n += 1
            vol = path.with_name(f"{path.name}.{n:03d}")
            vol.write_bytes(chunk)
            volumes.append(vol)
    path.unlink()
    return volumes
