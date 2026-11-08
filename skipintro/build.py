"""Building the skip-intro pak from the installed game."""
import shutil
from pathlib import Path

from miatools import pak, paths
from miatools.uasset import Package

from .assets import patch_package
from .movie import black_movie

PAK_NAME = "MadeInAbyss-BSFD-SkipIntro_98_P.pak"
MOD_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR = MOD_DIR / "build"
OUT = BUILD_DIR / PAK_NAME
BLACK_MOVIE = BUILD_DIR / "black.mp4"
MIN_DURATION = 0.01
ANIMATION_SPEED = 5.0

CONTENT = "MadeInAbyss-BSFD/Content/"
TITLE = CONTENT + "MadeInAbyss/Maps/Title/"
CAUTION = TITLE + "Caution/"
LOGO_MOVIE = CONTENT + "Movies/logo_spikechun.mp4"

# Asset path (without extension) -> (class-default floats to shorten, bytecode float constants to shorten,
# widget animations to play at ANIMATION_SPEED, whether constant Delay durations are shortened)
PATCHES = {
    CAUTION + "WBP_PictureCtrl": ({"ShowTime": 6.0}, (0.5,), (), False),
    CAUTION + "WBP_AutoSaveCaution": ({"ForcedShowTime": 1.0}, (), (), False),
    TITLE + "WBP_TitleLayout": ({}, (), ("In", "DeskIn"), True),
}


def _write(stage, internal_path, data):
    """Write ``data`` at ``internal_path`` inside the staging folder."""
    target = stage / internal_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def stage_files(stage, log=print):
    """Write every patched file of the pak into the folder ``stage``."""
    for asset, (properties, constants, animations, delays) in PATCHES.items():
        package = Package.from_game(asset + ".uasset")
        uexp, changes = patch_package(package, properties, constants, MIN_DURATION, animations, ANIMATION_SPEED,
                                      delays)
        _write(stage, asset + ".uasset", package.data)
        _write(stage, asset + ".uexp", uexp)
        for change in changes:
            log(f"  {Path(asset).name}: {change}")
    _write(stage, LOGO_MOVIE, black_movie(BLACK_MOVIE).read_bytes())


def build(log=print):
    """Build the pak into ``build/``; return its ``Path``."""
    stage = paths.tmp_dir("skip-intro-stage")
    try:
        stage_files(stage, log)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        pak.create(OUT, stage)
    finally:
        shutil.rmtree(stage)
    return OUT
