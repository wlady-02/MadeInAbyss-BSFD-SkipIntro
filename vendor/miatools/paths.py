"""Every path the mods need: game install, UE4SS, Proton prefix, saves, crash reports, local data.

Game paths are found automatically from the Steam libraries; any of them can be forced in
``shared/paths.local.toml`` or with a ``MIA_<KEY>`` environment variable (see ``config``).

Local data never goes to the home folder or ``/tmp``. It lives in the main checkout of the hub, ignored by
git, so every worktree of the same PC shares it:

- ``data/save-backups/``, ``data/tmp/``: shared by every mod (``data_dir``, ``tmp_dir``);
- ``mods/<slug>/``: a worktree of each mod's branch, so every mod is a visible folder (``mod_folder``);
- ``original|work|build|publish/`` inside the mod's folder there: its game files, test output, builds and store
  material (``mod_data``); in the mod's own repository, outside the hub, the same folders at its root.
"""
import re
import subprocess
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from . import config

STEAM_APP_ID = "1324340"
GAME_FOLDER = "MadeInAbyss-BSFD"
EXECUTABLE = "MadeInAbyss-Win64-Shipping.exe"
OFFICIAL_PAK_PREFIX = "MadeInAbyss-BSFD-WindowsNoEditor"
USER_DATA = Path("drive_c/users/steamuser/Documents/My Games") / GAME_FOLDER / "Saved"
DATA_FOLDER = "data"
BACKUP_FOLDER = "save-backups"
TMP_FOLDER = "tmp"
MOD_DATA_KINDS = ("original", "work", "build", "publish")
MODS_FOLDER = "mods"
SDK_URL = "https://github.com/RealGamertime/made-in-abyss-modding-docs"

_STEAM_ROOTS = (
    "~/.steam/steam",
    "~/.steam/debian-installation",
    "~/.local/share/Steam",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",
)


class PathNotFound(RuntimeError):
    """Raised when a required path cannot be found; the message says how to set it."""


@dataclass(frozen=True)
class GamePaths:
    """Resolved paths of one installation of the game."""

    library: Path
    game_dir: Path
    prefix: Path
    backup_dir: Path

    @property
    def content(self):
        """``MadeInAbyss-BSFD/Content`` inside the install."""
        return self.game_dir / GAME_FOLDER / "Content"

    @property
    def paks(self):
        """Folder of the game paks; extra mod paks go here too."""
        return self.content / "Paks"

    @property
    def win64(self):
        """Folder of the executable, UE4SS and its ``Mods`` folder."""
        return self.game_dir / GAME_FOLDER / "Binaries" / "Win64"

    @property
    def ue4ss_mods(self):
        """UE4SS ``Mods`` folder."""
        return self.win64 / "Mods"

    @property
    def ue4ss_log(self):
        """UE4SS log, rewritten at every game start; timestamps are UTC."""
        return self.win64 / "UE4SS.log"

    @property
    def ue4ss_settings(self):
        """UE4SS settings file."""
        return self.win64 / "UE4SS-settings.ini"

    @property
    def user_data(self):
        """``Saved`` folder of the game inside the Proton prefix."""
        return self.prefix / USER_DATA

    @property
    def saves(self):
        """Folder with the ``SlotNN.sav`` files."""
        return self.user_data / "SaveGames"

    @property
    def crashes(self):
        """Folder with one sub-folder per crash report."""
        return self.user_data / "Crashes"

    @property
    def game_logs(self):
        """Unreal Engine logs of the game."""
        return self.user_data / "Logs"

    def as_dict(self):
        """Return every path by name, for printing."""
        names = ("library", "game_dir", "content", "paks", "win64", "ue4ss_mods", "ue4ss_log",
                 "ue4ss_settings", "prefix", "user_data", "saves", "crashes", "game_logs", "backup_dir")
        return {name: getattr(self, name) for name in names}


@cache
def hub_root():
    """Return the main checkout of the hub (or of the mod's own repository once it is outside the hub).

    In a ``git worktree`` (such as ``mods/<slug>``) this is still the main checkout.
    Without git, the folder above ``shared/`` (or ``vendor/``) is used.
    """
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                cwd=config.HUB_DIR, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return config.HUB_DIR
    return Path(common).parent


def data_dir():
    """Return the hub's local data folder (``<hub>/data``, or ``data_dir`` from the config), created if missing."""
    folder = config.get_path("data_dir") or hub_root() / DATA_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def tmp_dir(prefix):
    """Return a new empty folder under ``data/tmp/`` for throwaway copies; the caller removes it."""
    root = data_dir() / TMP_FOLDER
    root.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{prefix}-", dir=root))


def mod_folder(slug):
    """Return ``<hub>/mods/<slug>``, the worktree of the mod's branch (made by ``mia.py checkout-mods``)."""
    return hub_root() / MODS_FOLDER / slug


def mod_data(slug, kind):
    """Return a local data folder of one mod, created if missing.

    The folder is inside the mod's code folder in ``mods/<slug>/projects/<slug>/`` when that worktree exists, else
    in ``projects/<slug>/`` of the main checkout (move it into ``mods/<slug>`` after ``mia.py checkout-mods``);
    outside the hub it is at the root of the mod's repository. Removing the ``mods/<slug>`` worktree deletes it.

    Args:
        slug: the mod's slug, e.g. ``"hud"``.
        kind: ``"original"`` (files from the game), ``"work"`` (test screenshots, logs, caches), ``"build"``
            or ``"publish"`` (store screenshots and images).

    Raises:
        ValueError: if ``kind`` is not one of ``MOD_DATA_KINDS``.
    """
    if kind not in MOD_DATA_KINDS:
        raise ValueError(f"kind must be one of {', '.join(MOD_DATA_KINDS)}")
    root = hub_root()
    in_mods = mod_folder(slug) / "projects" / slug
    if in_mods.is_dir():
        mod_root = in_mods
    elif (root / "projects").is_dir() or (root / "shared").is_dir():
        mod_root = root / "projects" / slug
    else:
        mod_root = root
    folder = mod_root / kind
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _steam_libraries():
    """Yield every Steam library folder found on this PC."""
    seen = set()
    for root in _STEAM_ROOTS:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        candidates = [root]
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            text = vdf.read_text(encoding="utf-8", errors="replace")
            candidates += [Path(p) for p in re.findall(r'"path"\s+"([^"]+)"', text)]
        for lib in candidates:
            key = lib.resolve()
            if key not in seen:
                seen.add(key)
                yield lib


def _find_library():
    """Return the Steam library that contains the game."""
    for lib in _steam_libraries():
        if (lib / "steamapps" / "common" / GAME_FOLDER / GAME_FOLDER / "Content" / "Paks").is_dir():
            return lib
    raise PathNotFound("Game not found in the Steam libraries: set game_dir in shared/paths.local.toml "
                       "or MIA_GAME_DIR=/path/to/MadeInAbyss-BSFD")


@cache
def get():
    """Return the ``GamePaths`` of this PC (computed once per process).

    Raises:
        PathNotFound: if the game cannot be found and is not configured.
    """
    game_dir = config.get_path("game_dir")
    prefix = config.get_path("prefix")
    library = config.get_path("library")
    if not (game_dir and prefix):
        library = library or _find_library()
    game_dir = game_dir or library / "steamapps" / "common" / GAME_FOLDER
    prefix = prefix or library / "steamapps" / "compatdata" / STEAM_APP_ID / "pfx"
    backup_dir = config.get_path("backup_dir") or data_dir() / BACKUP_FOLDER
    return GamePaths(library=library or game_dir.parent.parent.parent, game_dir=game_dir,
                     prefix=prefix, backup_dir=backup_dir)
