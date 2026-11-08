#!/usr/bin/env python3
"""Build, install or uninstall the skip-intro pak.

  python3 run.py              build build/MadeInAbyss-BSFD-SkipIntro_98_P.pak
  python3 run.py install      build and copy it into the game's Paks folder
  python3 run.py uninstall    remove it from the game
  python3 run.py release      build build/MadeInAbyss-BSFD-SkipIntro-v<version>.zip for players
"""
import sys
from pathlib import Path

MOD_DIR = Path(__file__).resolve().parent
HUB_SHARED = MOD_DIR.parents[1] / "shared"
# Inside the hub the shared tools are used; in the mod's own repository, their copy in vendor/.
sys.path.insert(0, str(HUB_SHARED if (HUB_SHARED / "miatools").is_dir() else MOD_DIR / "vendor"))

from miatools import game, pak, paths, release  # noqa: E402

from skipintro.assets import UnexpectedValue  # noqa: E402
from skipintro.build import OUT, PAK_NAME, build  # noqa: E402
from skipintro.movie import GStreamerMissing  # noqa: E402

COMMANDS = ("build", "install", "uninstall", "release")
ARCHIVE_NAME = "MadeInAbyss-BSFD-SkipIntro"


def main(argv):
    """Run the command given in ``argv`` (default ``build``); return the exit code."""
    command = argv[0] if argv else "build"
    if command not in COMMANDS:
        print(__doc__)
        return 2
    try:
        if command == "uninstall":
            if (paths.get().paks / PAK_NAME).exists():
                pak.remove_pak(PAK_NAME)
                print("removed", PAK_NAME)
            else:
                print(PAK_NAME, "is not installed")
            return 0
        out = build()
        print("built", out)
        if command == "install":
            print("installed in", pak.install_pak(out))
        if command == "release":
            files = {release.in_game_folder("pak", PAK_NAME): OUT}
            zip_path = release.make_zip(MOD_DIR, ARCHIVE_NAME, files, readme_name=f"{ARCHIVE_NAME}-README.txt")
            print("release zip", zip_path)
    except (UnexpectedValue, GStreamerMissing, game.GameRunning, paths.PathNotFound, ValueError,
            FileNotFoundError) as error:
        print("error:", error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
