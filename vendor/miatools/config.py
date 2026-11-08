"""Local, per-PC configuration of the shared tools.

Values are read, in order of priority, from environment variables (``MIA_<KEY>`` in upper case), from
``shared/paths.local.toml`` (ignored by git, see ``paths.local.example.toml``) and finally from the defaults
of each caller.
"""
import os
import tomllib
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parent.parent
HUB_DIR = SHARED_DIR.parent
LOCAL_FILE = SHARED_DIR / "paths.local.toml"


def _load_local():
    """Return the content of the local TOML file, or an empty dict if it does not exist."""
    if not LOCAL_FILE.is_file():
        return {}
    with LOCAL_FILE.open("rb") as f:
        return tomllib.load(f)


_LOCAL = _load_local()


def get(key, default=None):
    """Return the configured value of ``key``.

    Args:
        key: lower-case name, e.g. ``"game_dir"``.
        default: value returned when neither the environment nor the local file sets it.

    Returns:
        The value as a string (or the default).
    """
    env = os.environ.get("MIA_" + key.upper())
    if env:
        return env
    return _LOCAL.get(key, default)


def get_path(key):
    """Return the configured value of ``key`` as an expanded ``Path``, or ``None`` if it is not set."""
    value = get(key)
    return Path(value).expanduser() if value else None
