"""Player texts of a mod for every place it is published, made from one file: ``release/store.toml``.

``render`` turns the store file and the player ``CHANGELOG.md`` into the zip's ``README.txt``, the Nexus Mods
description, summary and page fields, the Steam discussion post, the Discord post and the GitHub release
notes. ``write`` saves them in ``release/``; ``stale`` tells which saved files no longer match.
"""
import re
import textwrap
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import release

STORE_FILE = "store.toml"
README_TXT = release.PLAYER_README
NEXUS_DESCRIPTION = release.NEXUS_DESCRIPTION
NEXUS_SUMMARY = release.NEXUS_SUMMARY
NEXUS_FIELDS = "nexus-fields.md"
STEAM_POST = "steam-post.txt"
DISCORD_POST = "discord-post.md"
GITHUB_NOTES = "github-release.md"
PUBLIC_README = "public-README.md"
GENERATED = (README_TXT, NEXUS_DESCRIPTION, NEXUS_SUMMARY, NEXUS_FIELDS, STEAM_POST, DISCORD_POST, GITHUB_NOTES,
             PUBLIC_README)
MEDIA_FOLDER = "media"

SUMMARY_LIMIT = 350
DISCORD_LIMIT = 2000
WRAP = 78
AUTHOR = "wlady-02"
GAME_TITLE = "Made in Abyss: Binary Star Falling into Darkness"
REQUIREMENTS = {"pak": (), "ue4ss": ("UE4SS 3.0.1",)}
UE4SS_URL = "https://github.com/UE4SS-RE/RE-UE4SS/releases/tag/v3.0.1"
PLATFORMS = "Works on Windows, Linux (Proton) and Steam Deck (desktop mode)."
NOTICE = "Unofficial, free fan mod, not affiliated with the developers or publishers."
AI_NOTICE = "Made with the help of an AI (Claude by Anthropic), tested in game by wlady-02."
PERMISSIONS = ("Free to share and modify with credit; no commercial use; do not re-upload elsewhere "
               "without permission.")
PLACEHOLDER = re.compile(r"<[^<>\s][^<>]*>")
TEXT_FIELDS = ("name", "tagline", "summary", "description", "kind", "game_build", "nexus_category", "permissions")
LIST_FIELDS = ("features", "files", "compatibility")
OPTIONAL_FIELDS = ("permissions", "links", "shots", "build", "media", "public_exclude")
DEFAULT_BUILD = {"requirements": ["Python 3.11 or newer", "the game installed from Steam"],
                 "steps": ["python3 run.py build", "python3 run.py release"]}
BROWSE_STEP = "In Steam: right click on the game -> Manage -> Browse local files."


class StoreError(ValueError):
    """``release/store.toml`` is missing a field or has a wrong value."""


@dataclass
class Store:
    """The content of ``release/store.toml``, with the version and notes from the player changelog.

    Attributes:
        name: the mod's name on the store pages, e.g. ``"Skip Intro"``.
        tagline: a few words for post titles, e.g. ``"the menu in 2 seconds"``.
        summary: one sentence of at most 350 characters (Nexus Mods summary, GitHub description).
        description: two or three lines: what changes in game, what stays the same.
        features: one line per feature.
        kind: ``"pak"`` or ``"ue4ss"``; it decides the installation folder and the requirements.
        files: what the player copies, as named in the game folder (a pak, or a UE4SS mod folder).
        compatibility: one line each: other mods, saves, game updates.
        game_build: the Steam build the mod was tested on.
        nexus_category: the category to pick on Nexus Mods.
        permissions: what others may do with the mod (Nexus Mods permissions); it must match ``LICENSE``.
        links: ``repository`` (``owner/name`` on GitHub), ``nexus`` and ``steam`` page addresses.
        shots: the screenshots ``mia.py store-shots`` takes, see ``storeshots``.
        build: ``requirements`` and ``steps`` (commands) to build the mod from its public repository.
        media: pictures for the public README, ``{"file": "publish/...", "caption": "..."}``; copied into the
            repository's ``media/`` by ``mia.py publish-repo``.
        public_exclude: more files of the mod folder to keep out of the public repository.
        version: the newest version in ``CHANGELOG.md``.
        notes: the lines of that version in ``CHANGELOG.md``.
    """
    name: str
    tagline: str
    summary: str
    description: str
    features: list
    kind: str
    files: list
    compatibility: list
    game_build: str
    nexus_category: str
    permissions: str = PERMISSIONS
    links: dict = field(default_factory=dict)
    shots: list = field(default_factory=list)
    build: dict = field(default_factory=lambda: dict(DEFAULT_BUILD))
    media: list = field(default_factory=list)
    public_exclude: list = field(default_factory=list)
    version: str = ""
    notes: list = field(default_factory=list)

    @property
    def folder(self):
        """The game folder the files go to, Windows style, e.g. ``MadeInAbyss-BSFD\\Content\\Paks``."""
        return "\\".join(release.INSTALL_FOLDERS[self.kind])

    @property
    def requirements(self):
        """What must be installed before the mod, e.g. ``("UE4SS 3.0.1",)``."""
        return REQUIREMENTS[self.kind]

    def link(self, name):
        """Return the address of ``name`` (``repository``, ``nexus``, ``steam``), or ``""``."""
        value = self.links.get(name, "")
        if name == "repository" and value:
            return f"https://github.com/{value}"
        return value


def load(project):
    """Read ``<project>/release/store.toml`` and the player changelog into a ``Store``.

    Raises:
        FileNotFoundError: no store file.
        StoreError: a field is missing or wrong, or the changelog has no version.
    """
    project = Path(project)
    path = project / release.RELEASE_DIR / STORE_FILE
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise StoreError(f"{STORE_FILE}: {error}") from error
    _validate(data)
    store = Store(**data)
    store.version = release.version(project) or ""
    if not store.version:
        raise StoreError("CHANGELOG.md has no version heading such as '## v1.0.0: 2026-11-03'")
    store.notes = release.version_notes(project)
    return store


def _validate(data):
    """Raise ``StoreError`` for a missing, unknown or wrongly typed field of ``store.toml``."""
    known = (*TEXT_FIELDS, *LIST_FIELDS, *OPTIONAL_FIELDS)
    unknown = [key for key in data if key not in known]
    if unknown:
        raise StoreError(f"{STORE_FILE}: unknown field {', '.join(unknown)}")
    missing = [name for name in known if name not in OPTIONAL_FIELDS and not data.get(name)]
    if missing:
        raise StoreError(f"{STORE_FILE}: missing {', '.join(missing)}")
    wrong = [n for n in TEXT_FIELDS if n in data and not isinstance(data[n], str)]
    wrong += [n for n in LIST_FIELDS if not (isinstance(data[n], list) and all(isinstance(v, str) for v in data[n]))]
    if not isinstance(data.get("links", {}), dict):
        wrong.append("links")
    shots = data.get("shots", [])
    if not (isinstance(shots, list) and all(isinstance(t, dict) and t.get("name") for t in shots)):
        wrong.append("shots (each [[shots]] needs a name)")
    if not isinstance(data.get("build", {}), dict):
        wrong.append("build")
    media = data.get("media", [])
    if not (isinstance(media, list) and all(isinstance(m, dict) and m.get("file") for m in media)):
        wrong.append("media (each [[media]] needs a file)")
    if not isinstance(data.get("public_exclude", []), list):
        wrong.append("public_exclude")
    if wrong:
        raise StoreError(f"{STORE_FILE}: wrong type for {', '.join(wrong)} (text or list of texts)")
    if data["kind"] not in REQUIREMENTS:
        raise StoreError(f"{STORE_FILE}: kind must be one of {', '.join(REQUIREMENTS)}")


def render(store):
    """Return ``{file name in release/: text}`` for every generated player text."""
    return {
        README_TXT: readme_txt(store),
        NEXUS_DESCRIPTION: nexus_description(store),
        NEXUS_SUMMARY: store.summary.strip() + "\n",
        NEXUS_FIELDS: nexus_fields(store),
        STEAM_POST: steam_post(store),
        DISCORD_POST: discord_post(store),
        GITHUB_NOTES: github_notes(store),
        PUBLIC_README: public_readme(store),
    }


def problems(store):
    """Return what is not ready: template placeholders left, a summary or a Discord post that is too long."""
    values = [getattr(store, n) for n in TEXT_FIELDS] + [v for n in LIST_FIELDS for v in getattr(store, n)]
    values += [str(v) for v in store.links.values()]
    left = sorted({m for value in values for m in PLACEHOLDER.findall(value)})
    found = [f"template placeholders still to fill: {', '.join(left)}"] if left else []
    if len(store.summary.strip()) > SUMMARY_LIMIT:
        found.append(f"summary is {len(store.summary.strip())} characters, Nexus Mods allows {SUMMARY_LIMIT}")
    discord = discord_post(store)
    if len(discord) > DISCORD_LIMIT:
        found.append(f"Discord post is {len(discord)} characters, Discord allows {DISCORD_LIMIT}")
    return found


def write(project):
    """Render the texts of ``project`` and save them in its ``release/`` folder; return the written paths."""
    folder = Path(project) / release.RELEASE_DIR
    written = []
    for name, text in render(load(project)).items():
        (folder / name).write_text(text, encoding="utf-8")
        written.append(folder / name)
    return written


def stale(project):
    """Return the generated files in ``release/`` that are missing or differ from a new render."""
    folder = Path(project) / release.RELEASE_DIR
    return [name for name, text in render(load(project)).items()
            if not (folder / name).is_file() or (folder / name).read_text(encoding="utf-8") != text]


def install_steps(store):
    """Return the installation steps, one string each, the same for every store."""
    steps = []
    if store.requirements:
        steps.append(f"Install {' and '.join(store.requirements)} first ({UE4SS_URL}).")
    steps += [BROWSE_STEP,
              f"Extract the zip into that folder; it puts {_join(store.files)} in {store.folder}.",
              f"Or copy {_join(store.files)} into {store.folder} by hand."]
    return steps


def uninstall_text(store):
    """Return the uninstall sentence."""
    return f"Delete {_join(store.files)} from {store.folder}. Saves are not touched."


def readme_txt(store):
    """Return the ``README.txt`` that goes in the zip (``{VERSION}`` is filled in by the zip)."""
    lines = [f"{GAME_TITLE.upper()} - {store.name.upper()}",
             f"Version {release.VERSION_PLACEHOLDER} - for the Steam (PC) version, game build {store.game_build}"]
    lines += [link for link in (store.link("nexus"), store.link("repository")) if link]
    lines += ["", "WHAT IT DOES", *_wrap(store.description), "",
              "NOTICE", *_wrap(f"- {NOTICE}", indent="  "), *_wrap(f"- {AI_NOTICE}", indent="  "), "",
              "INSTALLATION"]
    for number, step in enumerate(install_steps(store), 1):
        lines += _wrap(f"{number}. {step}", indent="   ")
    lines += ["", PLATFORMS, "", "COMPATIBILITY"]
    for item in store.compatibility:
        lines += _wrap(f"- {item}", indent="  ")
    lines += ["", "UNINSTALL", *_wrap(uninstall_text(store))]
    return "\n".join(lines) + "\n"


def nexus_description(store):
    """Return the Nexus Mods description (Nexus BBCode)."""
    parts = [f"[size=5][b]{store.name}[/b][/size]", "", _one_line(store.description), "",
             "[size=4][b]Features[/b][/size]", _bb_list(store.features), "",
             "[size=4][b]Installation[/b][/size]", _bb_list(install_steps(store), numbered=True), PLATFORMS, "",
             "[size=4][b]Uninstall[/b][/size]", uninstall_text(store), "",
             "[size=4][b]Compatibility[/b][/size]",
             _bb_list([f"Made for the Steam version, game build {store.game_build}.", *store.compatibility]), "",
             "[size=4][b]Credits[/b][/size]", f"Made by {AUTHOR}. {AI_NOTICE} {NOTICE}"]
    if store.link("repository"):
        parts.append(f"Source code: [url={store.link('repository')}]{store.link('repository')}[/url]")
    return "\n".join(parts) + "\n"


def nexus_fields(store):
    """Return the checklist of the Nexus Mods page fields, to fill in by hand when uploading."""
    requirements = ", ".join(store.requirements) or "none"
    lines = [f"# Nexus Mods page: {store.name}", "",
             f"- Mod name: {store.name}",
             f"- Version: {store.version}",
             f"- Author: {AUTHOR}",
             f"- Category: {store.nexus_category}",
             "- Language: English",
             "- AI generated content: yes, declared (made with the help of Claude by Anthropic)",
             f"- Summary: the text of `{NEXUS_SUMMARY}`",
             f"- Description: the text of `{NEXUS_DESCRIPTION}`",
             f"- Requirements: {requirements}",
             f"- Permissions: {store.permissions}",
             f"- External link: {store.link('repository') or '(none yet)'}",
             "",
             "## Main file",
             f"- File: the release zip of v{store.version} (`build/`), category Main",
             f"- File description: {_join(store.files)} for {store.folder}, game build {store.game_build}. "
             "Extract the zip into the game folder.",
             "- Mod manager download: off (manual install: the zip is extracted into the game folder)",
             "",
             "## Images",
             "- Upload `publish/screenshots/*.jpg` (made by `mia.py store-shots`); the first one is the main image."]
    return "\n".join(lines) + "\n"


def steam_post(store):
    """Return the Steam discussion post: a title line, then the text in Steam BBCode."""
    links = [f"[url={url}]{label}[/url]" for label, url in
             (("Nexus Mods", store.link("nexus")), ("GitHub (source and releases)", store.link("repository")))
             if url]
    parts = ["TITLE:", f"[MOD] {store.name}: {store.tagline}", "", "TEXT:",
             f"[h1]{store.name} v{store.version}[/h1]", _one_line(store.description), "",
             "[b]Features[/b]", _steam_list(store.features), "",
             "[b]Install[/b]", _steam_list(install_steps(store), numbered=True), PLATFORMS, "",
             f"[b]Uninstall:[/b] {uninstall_text(store)}", ""]
    if links:
        parts += ["[b]Download[/b]", _steam_list(links), ""]
    parts.append(f"{NOTICE} {AI_NOTICE}")
    return "\n".join(parts) + "\n"


def discord_post(store):
    """Return the Discord announcement (Discord Markdown, at most 2000 characters)."""
    parts = [f"**{store.name} v{store.version}**: {store.tagline}", f"A mod for *{GAME_TITLE}* (PC/Steam)", "",
             _one_line(store.description), "",
             "**Features**", *[f"- {item}" for item in store.features], "",
             "**Install**", *[f"{n}. {step}" for n, step in enumerate(install_steps(store), 1)], PLATFORMS]
    links = [f"- {label}: <{url}>" for label, url in
             (("Nexus Mods", store.link("nexus")), ("GitHub", store.link("repository"))) if url]
    if links:
        parts += ["", "**Download**", *links]
    parts += ["", f"-# {NOTICE} {AI_NOTICE}"]
    return "\n".join(parts) + "\n"


def github_notes(store):
    """Return the GitHub release notes: the version's changelog lines, then how to install."""
    parts = [*store.notes, "", "### Install", *[f"{n}. {step}" for n, step in enumerate(install_steps(store), 1)],
             PLATFORMS, "", f"Uninstall: {uninstall_text(store)}", "", f"Tested on game build {store.game_build}."]
    return "\n".join(parts) + "\n"


def public_readme(store):
    """Return the README of the public repository: what the mod does, media, download, install, build."""
    build = {**DEFAULT_BUILD, **store.build}
    repo = store.link("repository")
    parts = [f"# {store.name}", "", f"A mod for *{GAME_TITLE}* (PC, Steam). {store.summary.strip()}", ""]
    for item in store.media:
        name = Path(item["file"]).name
        caption = item.get("caption", "")
        if Path(name).suffix.lower() in (".mp4", ".webm"):
            parts += [f"[▶ {caption or name}]({MEDIA_FOLDER}/{name})", ""]
        else:
            parts += [f"![{caption}]({MEDIA_FOLDER}/{name})", *([f"*{caption}*"] if caption else []), ""]
    parts += ["## What it does", "", _one_line(store.description), "", *[f"- {f}" for f in store.features], ""]
    download = [f"[latest release]({repo}/releases/latest)" if repo else "the latest release",
                *([f"[Nexus Mods]({store.link('nexus')})"] if store.link("nexus") else [])]
    parts += ["## Download and install", "", f"Download the zip from {' or '.join(download)}, then:", "",
              *[f"{n}. {step}" for n, step in enumerate(install_steps(store), 1)], "", PLATFORMS, "",
              f"**Uninstall:** {uninstall_text(store)}", "",
              "## Compatibility", "", f"- Made for the Steam version, game build {store.game_build}.",
              *[f"- {item}" for item in store.compatibility], "",
              "## Build it yourself", "", "Requirements:", "", *[f"- {r}" for r in build["requirements"]], "",
              "From the repository folder:", "", "```sh", *build["steps"], "```", "",
              "## Changes", "", "See [CHANGELOG.md](CHANGELOG.md).", "",
              "## License", "", "See [LICENSE](LICENSE).", "",
              f"{NOTICE} {AI_NOTICE}"]
    return "\n".join(parts) + "\n"


def _bb_list(items, numbered=False):
    """Return a Nexus Mods BBCode list of ``items``."""
    body = "\n".join(f"[*]{item}" for item in items)
    return f"[list{'=1' if numbered else ''}]\n{body}\n[/list]"


def _steam_list(items, numbered=False):
    """Return a Steam BBCode list of ``items`` (Steam numbers lists with ``[olist]``, not ``[list=1]``)."""
    tag = "olist" if numbered else "list"
    body = "\n".join(f"[*]{item}" for item in items)
    return f"[{tag}]\n{body}\n[/{tag}]"


def _wrap(text, indent=""):
    """Return ``text`` wrapped at ``WRAP`` columns, continuation lines indented by ``indent``."""
    return textwrap.wrap(_one_line(text), WRAP, subsequent_indent=indent, break_on_hyphens=False) or [""]


def _one_line(text):
    """Return ``text`` with its line breaks and repeated spaces turned into single spaces."""
    return " ".join(text.split())


def _join(names):
    """Return ``names`` as ``a``, ``a and b`` or ``a, b and c``."""
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
