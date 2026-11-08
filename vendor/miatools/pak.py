"""Reading and writing UE4.25 .pak files (version 9, no compression, no encryption) and reading files from the
official game paks.

The original paks are read-only: mods are extra paks named ``<name>_<N>_P.pak`` placed next to them, where a
higher ``N`` wins over a lower one.
"""
import hashlib
import re
import shutil
import struct
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import game, paths

MAGIC = 0x5A6F12E1
PAK_VERSION = 9
DEFAULT_MOUNT = "../../../"
ENTRY_HEADER_SIZE = 53
MOD_PAK_NAME = re.compile(r"_\d+_P\.pak$")  # size of the copy of the entry record written before every file's data


@dataclass
class Entry:
    """One file inside a pak."""

    name: str
    offset: int
    size: int
    uncompressed_size: int
    compression: int
    sha1: bytes
    flags: int

    @property
    def readable(self):
        """True if the entry is neither compressed nor encrypted."""
        return not self.compression and not self.flags & 1


def read_fstring(data, pos):
    """Read an Unreal ``FString`` at ``pos``; return ``(text, next position)``."""
    length = struct.unpack_from("<i", data, pos)[0]
    pos += 4
    if length == 0:
        return "", pos
    if length > 0:
        return data[pos:pos + length - 1].decode("latin-1"), pos + length
    length = -length
    return data[pos:pos + 2 * length - 2].decode("utf-16-le"), pos + 2 * length


def write_fstring(text):
    """Encode ``text`` as an Unreal ``FString`` (ASCII when possible, else UTF-16)."""
    try:
        raw = text.encode("ascii") + b"\0"
        return struct.pack("<i", len(raw)) + raw
    except UnicodeEncodeError:
        raw = text.encode("utf-16-le") + b"\0\0"
        return struct.pack("<i", -(len(raw) // 2)) + raw


def _read_footer(f):
    """Return ``(version, index offset, index size, index encrypted)`` from the end of an open pak."""
    f.seek(0, 2)
    size = f.tell()
    f.seek(max(0, size - 512))
    tail = f.read()
    i = tail.rfind(struct.pack("<I", MAGIC))
    _, version, offset, index_size = struct.unpack_from("<IiQQ", tail, i)
    return version, offset, index_size, bool(tail[i - 1])


def _read_entry(data, pos, name):
    """Read one index record at ``pos``; return ``(Entry, next position)``."""
    offset, size, usize, compression = struct.unpack_from("<qqqI", data, pos)
    pos += 28
    sha1 = data[pos:pos + 20]
    pos += 20
    if compression:
        blocks = struct.unpack_from("<i", data, pos)[0]
        pos += 4 + 16 * blocks
    flags, _ = struct.unpack_from("<BI", data, pos)
    pos += 5
    return Entry(name, offset, size, usize, compression, sha1, flags), pos


def _entry_record(offset, data):
    """Return the index record of an uncompressed file stored at ``offset``."""
    return (struct.pack("<qqqI", offset, len(data), len(data), 0)
            + hashlib.sha1(data).digest() + struct.pack("<BI", 0, 0))


def read_index(pak):
    """Read the index of a pak.

    Returns:
        ``(version, mount point, list of Entry)``.
    """
    with open(pak, "rb") as f:
        version, offset, index_size, encrypted = _read_footer(f)
        if encrypted:
            raise ValueError(f"{pak}: the index is encrypted, an AES key is needed")
        f.seek(offset)
        data = f.read(index_size)
    mount, pos = read_fstring(data, 0)
    count = struct.unpack_from("<i", data, pos)[0]
    pos += 4
    entries = []
    for _ in range(count):
        name, pos = read_fstring(data, pos)
        entry, pos = _read_entry(data, pos, name)
        entries.append(entry)
    return version, mount, entries


def read_entry(pak, entry):
    """Return the bytes of ``entry`` from ``pak``, checking its SHA-1."""
    if not entry.readable:
        raise ValueError(f"{entry.name} is compressed or encrypted")
    with open(pak, "rb") as f:
        f.seek(entry.offset + ENTRY_HEADER_SIZE)
        data = f.read(entry.size)
    if hashlib.sha1(data).digest() != entry.sha1:
        raise ValueError(f"{entry.name}: SHA-1 mismatch")
    return data


def create(out, source_dir, mount=DEFAULT_MOUNT):
    """Write a new uncompressed pak with every file under ``source_dir``.

    Args:
        out: path of the pak to write.
        source_dir: folder whose relative paths become the paths inside the pak
            (e.g. ``MadeInAbyss-BSFD/Content/...``).
        mount: mount point stored in the pak.

    Returns:
        The number of files written.
    """
    source_dir = Path(source_dir)
    files = sorted(p.relative_to(source_dir).as_posix() for p in source_dir.rglob("*") if p.is_file())
    index = b""
    with open(out, "wb") as f:
        for name in files:
            data = (source_dir / name).read_bytes()
            offset = f.tell()
            f.write(_entry_record(0, data))
            f.write(data)
            index += write_fstring(name) + _entry_record(offset, data)
        index = write_fstring(mount) + struct.pack("<i", len(files)) + index
        index_offset = f.tell()
        f.write(index)
        f.write(b"\0" * 16 + b"\0")  # encryption key GUID, index not encrypted
        f.write(struct.pack("<IiQQ", MAGIC, PAK_VERSION, index_offset, len(index)))
        f.write(hashlib.sha1(index).digest())
        f.write(b"\0")  # frozen index flag
        f.write(b"\0" * 32 * 5)  # no compression methods
    return len(files)


def _pak_priority(name):
    """Return the load priority of a pak as UE4.25 does: plain paks first, then ``_P`` by number."""
    if not name.endswith("_P.pak"):
        return 0
    match = re.search(r"_(\d+)_P\.pak$", name)
    version = int(match.group(1)) + 1 if match and int(match.group(1)) >= 1 else 1
    return 100 * version


def official_paks():
    """Return the game's own paks (never the mod paks), in load order."""
    folder = paths.get().paks
    names = [p.name for p in folder.glob(paths.OFFICIAL_PAK_PREFIX + "*.pak")]
    return [folder / n for n in sorted(names, key=lambda n: (_pak_priority(n), n))]


def game_files():
    """Return ``{internal path: (pak, Entry)}`` with the winning version of every file of the official paks."""
    files = {}
    for pak in official_paks():
        for entry in read_index(pak)[2]:
            files[entry.name] = (pak, entry)
    return files


def find_game_files(filters):
    """Return the internal paths of the official paks containing any of ``filters`` (case-insensitive)."""
    filters = [f.lower() for f in filters]
    return sorted(name for name in game_files() if not filters or any(f in name.lower() for f in filters))


def read_game_file(internal_path):
    """Return the bytes of the winning version of ``internal_path`` in the official paks."""
    found = game_files().get(internal_path)
    if not found:
        raise FileNotFoundError(f"{internal_path} is not in the game paks")
    return read_entry(*found)


def extract_game_files(filters, out_dir):
    """Extract every official file matching ``filters`` into ``out_dir`` (keeping internal paths).

    Never extract into the repository: game assets must not be committed.

    Returns:
        The list of written ``Path``s.
    """
    out_dir = Path(out_dir)
    written = []
    files = game_files()
    for name in find_game_files(filters):
        target = out_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(read_entry(*files[name]))
        written.append(target)
    return written


def mod_paks():
    """Return the paks in the game folder that are not official, i.e. installed by mods."""
    official = set(official_paks())
    return sorted(p for p in paths.get().paks.glob("*.pak") if p not in official)


def install_pak(pak):
    """Copy a mod pak (named ``<name>_<N>_P.pak``) into the game's ``Paks`` folder; return the installed ``Path``."""
    pak = Path(pak)
    if pak.name.startswith(paths.OFFICIAL_PAK_PREFIX):
        raise ValueError("Refusing to overwrite an official game pak")
    if not MOD_PAK_NAME.search(pak.name):
        raise ValueError(f"{pak.name}: a mod pak must be named <name>_<N>_P.pak to load after the game paks")
    game.require_closed(f"installing {pak.name}")
    target = paths.get().paks / pak.name
    shutil.copy2(pak, target)
    return target


def remove_pak(name):
    """Remove a mod pak from the game's ``Paks`` folder."""
    if name.startswith(paths.OFFICIAL_PAK_PREFIX):
        raise ValueError("Refusing to remove an official game pak")
    game.require_closed(f"removing {name}")
    (paths.get().paks / name).unlink()


@contextmanager
def temporarily(install=None, remove=None):
    """Install the pak ``install`` and/or take out the installed pak named ``remove`` inside a ``with`` block.

    When the block ends, the ``Paks`` folder is put back as it was: a pak that was replaced or taken out is
    restored from a copy in ``data/tmp``, a pak that was not there before is removed. The game must be closed.

    Args:
        install: path of a mod pak to install (e.g. the mod's build).
        remove: file name of an installed mod pak to take out (e.g. to show the game without the mod).
    """
    folder = paths.get().paks
    keep = paths.tmp_dir("pak-swap")
    touched = [name for name in (Path(install).name if install else None, remove) if name]
    saved = {}
    for name in touched:
        if (folder / name).is_file():
            saved[name] = shutil.copy2(folder / name, keep / name)
    try:
        if remove and (folder / remove).is_file():
            remove_pak(remove)
        if install:
            install_pak(install)
        yield
    finally:
        if game.is_running():
            raise game.GameRunning(f"close the game, then put the paks back by hand from {keep} "
                                   f"({', '.join(saved) or 'nothing saved'}; remove the others: "
                                   f"{', '.join(n for n in touched if n not in saved) or 'none'})")
        for name in touched:
            if name in saved:
                shutil.copy2(saved[name], folder / name)
            elif (folder / name).is_file():
                (folder / name).unlink()
        shutil.rmtree(keep, ignore_errors=True)
