"""Preparing a mod for publication: release checks, a self-contained copy of ``miatools``, the release zip.

A mod folder (``projects/<slug>``) is ready for players when ``check`` reports no errors: stage ``serious``
or ``published``, committed and pushed, no game files or private data, documented code, the ``miatools``
modules it imports copied in ``vendor/miatools``, a player ``CHANGELOG.md`` with a version, a ``LICENSE``
and the player texts in ``release/``, made from ``release/store.toml`` (see ``storetexts``). The release zip
mirrors the game folder (``in_game_folder``), so players extract it where Steam's "Browse local files" opens.
"""
import ast
import filecmp
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import config

MIATOOLS_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = config.HUB_DIR / "templates" / "release"

VENDOR_DIR = "vendor"
RELEASE_DIR = "release"
BUILD_DIR = "build"
PLAYER_README = "README.txt"
NEXUS_DESCRIPTION = "nexus-description.bbcode"
NEXUS_SUMMARY = "nexus-summary.txt"
VERSION_PLACEHOLDER = "{VERSION}"
# Where each kind of mod goes, from the folder Steam's "Browse local files" opens. The release zip mirrors
# it, so players extract the zip there.
INSTALL_FOLDERS = {
    "pak": ("MadeInAbyss-BSFD", "Content", "Paks"),
    "ue4ss": ("MadeInAbyss-BSFD", "Binaries", "Win64", "Mods"),
}

READY_STAGES = ("serious", "published")
STAGE_LINE = re.compile(r"^- \*\*Stage:\*\*\s*(\S+)", re.MULTILINE)
PROJECTS_FILE = config.HUB_DIR / "PROJECTS.md"
VERSION_HEADING = re.compile(r"^## \[?v?(\d+\.\d+\.\d+(?:-[\w.]+)?)", re.MULTILINE)
SESSION_ENTRY = re.compile(r"^- \*\*Session:\*\*", re.MULTILINE)

GAME_FILE_SUFFIXES = {
    ".pak", ".utoc", ".ucas", ".locres", ".ufont", ".uasset", ".uexp", ".ubulk", ".umap", ".sav", ".log",
}
SECRET_FILE_NAMES = {".env", "id_rsa", "id_ed25519", "credentials.json"}
LOCAL_PATH_PATTERNS = (
    re.compile(r"/(?:home|Users)/\w[\w.-]*/"),
    re.compile(r"\b[A-Za-z]:\\Users\\\w", re.IGNORECASE),
    re.compile(r"\bpfx/drive_c/users/\w"),
)
SECRET_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile("-----BEGIN [A-Z ]*" + "PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password)\b\s*[=:]\s*['\"][^'\"\s]{8,}['\"]"),
)
OTHER_DRIVE_PATTERN = re.compile(r"\b[D-Z]:\\\w")
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
ALLOWED_EMAIL = re.compile(r"(?i)^git@|noreply|no-reply|example\.(?:com|org)")
TEMPLATE_PLACEHOLDER = re.compile(r"<[a-z][^<>]*>")
LUA_FUNCTION = re.compile(r"^\s*function\s+([\w.:]+)")
LUA_COMMENT = re.compile(r"^\s*--")


@dataclass(frozen=True)
class Finding:
    """One problem found by ``check``.

    Attributes:
        level: ``"error"`` (blocks the release) or ``"warning"`` (to look at).
        message: what is wrong and, when useful, how to fix it.
        path: the file concerned, relative to the mod folder, or ``""``.
    """
    level: str
    message: str
    path: str = ""

    def __str__(self):
        where = f"{self.path}: " if self.path else ""
        return f"{self.level:7} {where}{self.message}"


def check(project):
    """Run every release check on a mod folder.

    Args:
        project: the mod folder (``projects/<slug>``).

    Returns:
        A list of ``Finding``, errors first.
    """
    project = Path(project).resolve()
    if not (project / "README.md").is_file():
        raise FileNotFoundError(f"{project} is not a mod folder (no README.md)")
    files = tracked_files(project)
    findings = [
        *_check_stage(project),
        *_check_git(project),
        *_check_files(project, files),
        *_check_docstrings(project, files),
        *_check_vendor(project, files),
        *_check_player_files(project),
        *_check_store(project),
    ]
    return sorted(findings, key=lambda f: f.level != "error")


def tracked_files(project):
    """Return the files of ``project`` known to git (tracked or new and not ignored), relative to it."""
    out = _git(project, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", ".")
    return sorted({Path(name) for name in out.split("\0") if name and (project / name).is_file()})


def version(project):
    """Return the newest version in the mod's player ``CHANGELOG.md`` (e.g. ``"1.0.0"``), or ``None``."""
    changelog = Path(project) / "CHANGELOG.md"
    if not changelog.is_file():
        return None
    match = VERSION_HEADING.search(changelog.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def version_notes(project):
    """Return the lines under the newest version heading of the player ``CHANGELOG.md`` (empty if none)."""
    changelog = Path(project) / "CHANGELOG.md"
    if not changelog.is_file():
        return []
    text = changelog.read_text(encoding="utf-8")
    match = VERSION_HEADING.search(text)
    if not match:
        return []
    body = text[match.end():].split("\n", 1)[1] if "\n" in text[match.end():] else ""
    lines = []
    for line in body.splitlines():
        if line.startswith("## "):
            break
        lines.append(line)
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def miatools_imports(project):
    """Return the ``miatools`` modules imported by the mod's Python files, with their own dependencies.

    Args:
        project: the mod folder.

    Returns:
        A sorted list of module names, e.g. ``["config", "game", "pak", "paths"]``.
    """
    project = Path(project)
    wanted = set()
    for rel in tracked_files(project):
        if rel.suffix == ".py" and rel.parts[0] != VENDOR_DIR:
            wanted |= _imported_miatools(ast.parse((project / rel).read_text(encoding="utf-8")))
    return sorted(_with_dependencies(wanted))


def vendor(project):
    """Copy the ``miatools`` modules the mod imports into ``<project>/vendor/miatools``.

    Modules no longer imported are removed from the copy; the whole copy is removed if the mod no longer
    imports ``miatools``.

    Args:
        project: the mod folder.

    Returns:
        The list of copied module names (empty if the mod does not use ``miatools``).
    """
    project = Path(project)
    modules = miatools_imports(project)
    target = project / VENDOR_DIR / "miatools"
    if not modules:
        if target.is_dir():
            shutil.rmtree(target)
        return []
    target.mkdir(parents=True, exist_ok=True)
    for old in target.glob("*.py"):
        if old.stem not in modules and old.name != "__init__.py":
            old.unlink()
    for name in ["__init__", *modules]:
        shutil.copyfile(MIATOOLS_DIR / f"{name}.py", target / f"{name}.py")
    return modules


def init_release_files(project):
    """Copy the release templates (``store.toml``) into ``<project>/release/`` without overwriting files.

    Returns:
        The list of created files.
    """
    target = Path(project) / RELEASE_DIR
    target.mkdir(exist_ok=True)
    created = []
    for template in sorted(TEMPLATES_DIR.iterdir()):
        dest = target / template.name
        if not dest.exists():
            shutil.copyfile(template, dest)
            created.append(dest)
    return created


def in_game_folder(kind, name):
    """Return the path inside the release zip for ``name`` of a mod of ``kind`` (``"pak"`` or ``"ue4ss"``).

    Example: ``in_game_folder("pak", "X_98_P.pak")`` is ``"MadeInAbyss-BSFD/Content/Paks/X_98_P.pak"``.
    """
    return "/".join((*INSTALL_FOLDERS[kind], name))


def make_zip(project, archive_name, contents, readme_name=PLAYER_README):
    """Build ``<project>/build/<archive_name>-v<version>.zip`` for players.

    The version comes from ``CHANGELOG.md``; ``release/README.txt`` is added with ``{VERSION}`` filled
    in and Windows line endings.

    Args:
        project: the mod folder.
        archive_name: base name of the zip, e.g. ``"MadeInAbyss-BSFD-SkipIntro"``.
        contents: mapping of path inside the zip to a local file or folder (a folder is added recursively),
            e.g. ``{in_game_folder("pak", pak_name): build_dir / pak_name}``.
        readme_name: name of the README in the zip. With a zip extracted into the game folder, give it the
            mod's name (e.g. ``"MadeInAbyss-BSFD-SkipIntro-README.txt"``) so mods do not overwrite each other's.

    Returns:
        The path of the zip.

    Raises:
        ValueError: if ``CHANGELOG.md`` has no version heading.
        FileNotFoundError: if ``release/README.txt`` or one of ``contents`` is missing.
    """
    project = Path(project)
    release_version = version(project)
    if not release_version:
        raise ValueError("CHANGELOG.md has no version heading such as '## v1.0.0: 2026-11-03'")
    readme = (project / RELEASE_DIR / PLAYER_README).read_text(encoding="utf-8")
    out = project / BUILD_DIR / f"{archive_name}-v{release_version}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname, source in contents.items():
            _add_to_zip(archive, arcname, Path(source))
        text = readme.replace(VERSION_PLACEHOLDER, release_version)
        archive.writestr(readme_name, text.replace("\r\n", "\n").replace("\n", "\r\n"))
    return out


def run_outside(project, command, keep=False):
    """Run ``command`` in a copy of the mod made outside the hub, as a fresh clone of its own repository.

    Only the files ``tracked_files`` returns are copied, so the run fails if the mod still needs ``shared/``
    or an ignored file. The copy goes to the system temporary folder, outside any git repository, so the
    mod's tools cannot find the hub from it.

    Args:
        project: the mod folder.
        command: the command and its arguments, run from the copy's root.
        keep: leave the copy in place for inspection instead of deleting it.

    Returns:
        ``(exit code, copy folder)``; the folder no longer exists unless ``keep`` is true.
    """
    project = Path(project)
    root = Path(tempfile.mkdtemp(prefix=f"try-outside-{project.name}-"))
    copy = root / project.name
    try:
        for rel in tracked_files(project):
            (copy / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project / rel, copy / rel)
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        return subprocess.run(command, cwd=copy, env=env).returncode, copy
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)


def stage(project):
    """Return the stage of a mod from its README, or from ``PROJECTS.md`` if the README has none.

    Returns:
        ``"idea"``, ``"draft"``, ``"serious"``, ``"published"`` or ``None`` if neither file says it.
    """
    project = Path(project)
    match = STAGE_LINE.search((project / "README.md").read_text(encoding="utf-8"))
    if match:
        return match.group(1)
    if PROJECTS_FILE.is_file():
        for line in PROJECTS_FILE.read_text(encoding="utf-8").splitlines():
            cells = [cell.strip() for cell in line.split("|")]
            if len(cells) > 3 and cells[1] == project.name:
                return cells[3]
    return None


def _check_stage(project):
    """Return a finding unless the stage is ``serious`` or ``published``."""
    current = stage(project) or "missing"
    if current in READY_STAGES:
        return []
    return [Finding("error", f"stage is '{current}': the user must move it to 'serious' first", "README.md")]


def _check_git(project):
    """Return findings for uncommitted changes and commits not pushed."""
    findings = []
    if _git(project, "status", "--porcelain", "--", ".").strip():
        findings.append(Finding("error", "uncommitted changes in the mod folder"))
    try:
        ahead = _git(project, "rev-list", "--count", "@{upstream}..HEAD").strip()
    except subprocess.CalledProcessError:
        findings.append(Finding("error", "the branch has no upstream: push it"))
    else:
        if ahead != "0":
            findings.append(Finding("error", f"{ahead} commit(s) not pushed"))
    return findings


def _check_files(project, files):
    """Return findings for game files, secret files, local paths, e-mail addresses and secrets."""
    findings = []
    for rel in files:
        if rel.suffix.lower() in GAME_FILE_SUFFIXES:
            findings.append(Finding("error", "game or generated file: remove it and ignore it", str(rel)))
            continue
        if rel.name in SECRET_FILE_NAMES:
            findings.append(Finding("error", "secret file", str(rel)))
            continue
        text = _read_text(project / rel)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            findings += _check_line(f"{rel}:{number}", line)
    return findings


def history_findings(top, commit, prefix=""):
    """Return findings for every file ever committed in the history of ``commit``, not only the last one.

    Used before a repository becomes public: a game file or a secret removed later is still in its history.

    Args:
        top: the git working tree to run in.
        commit: the newest commit of the history to scan.
        prefix: shown before each path, e.g. ``"history: "``.
    """
    objects = _git(top, "rev-list", "--objects", commit)
    blobs = {}
    for line in objects.splitlines():
        sha, _, name = line.partition(" ")
        if name:
            blobs.setdefault(sha, name)
    findings = []
    for sha, name in blobs.items():
        if _git(top, "cat-file", "-t", sha).strip() != "blob":
            continue
        rel = Path(name)
        if rel.suffix.lower() in GAME_FILE_SUFFIXES:
            findings.append(Finding("error", "game or generated file in the history", prefix + name))
            continue
        if rel.name in SECRET_FILE_NAMES:
            findings.append(Finding("error", "secret file in the history", prefix + name))
            continue
        data = subprocess.run(["git", "cat-file", "blob", sha], cwd=top, check=True, capture_output=True).stdout
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            findings += _check_line(f"{prefix}{name}:{number}", line)
    return findings


def check_line(where, line):
    """Return the findings (local paths, secrets, e-mail addresses) for one line of text at ``where``."""
    return _check_line(where, line)


def _check_line(where, line):
    """Return the findings for one line of text."""
    findings = []
    if any(p.search(line) for p in LOCAL_PATH_PATTERNS):
        findings.append(Finding("error", "local path of this PC", where))
    elif OTHER_DRIVE_PATTERN.search(line):
        findings.append(Finding("warning", "path on a drive other than C: is it a path of this PC?", where))
    if any(p.search(line) for p in SECRET_PATTERNS):
        findings.append(Finding("error", "looks like a secret (token, key, password)", where))
    for email in EMAIL_PATTERN.findall(line):
        if not ALLOWED_EMAIL.search(email):
            findings.append(Finding("warning", f"e-mail address {email}: personal data?", where))
    return findings


def _check_docstrings(project, files):
    """Return warnings for public Python definitions without a docstring and Lua functions without a comment."""
    findings = []
    for rel in files:
        if rel.parts[0] == VENDOR_DIR:
            continue
        if rel.suffix == ".py":
            missing = _python_missing_docstrings(ast.parse((project / rel).read_text(encoding="utf-8")))
        elif rel.suffix == ".lua":
            missing = _lua_missing_comments((project / rel).read_text(encoding="utf-8"))
        else:
            continue
        findings += [Finding("warning", f"no docstring: {name}", str(rel)) for name in missing]
    return findings


def _check_vendor(project, files):
    """Return errors if the copy of ``miatools`` is missing, incomplete or older than ``shared/``."""
    modules = miatools_imports(project)
    target = project / VENDOR_DIR / "miatools"
    if not modules:
        if target.is_dir():
            return [Finding("error", "the mod no longer imports miatools: run 'mia.py vendor'",
                            str(target.relative_to(project)))]
        return []
    findings = []
    for name in ["__init__", *modules]:
        copy = target / f"{name}.py"
        rel = str(copy.relative_to(project))
        if not copy.is_file():
            findings.append(Finding("error", "missing: run 'mia.py vendor'", rel))
        elif not filecmp.cmp(copy, MIATOOLS_DIR / f"{name}.py", shallow=False):
            findings.append(Finding("error", "differs from shared/miatools: run 'mia.py vendor'", rel))
        elif Path(rel) not in files:
            findings.append(Finding("error", "not tracked by git", rel))
    return findings


def _check_player_files(project):
    """Return findings for the player changelog, licence and release texts."""
    findings = []
    changelog = project / "CHANGELOG.md"
    if not changelog.is_file():
        findings.append(Finding("error", "missing player changelog", "CHANGELOG.md"))
    elif SESSION_ENTRY.search(changelog.read_text(encoding="utf-8")):
        findings.append(Finding(
            "error", "this is the session log: rename it DEVLOG.md and start a player CHANGELOG.md",
            "CHANGELOG.md"))
    elif not version(project):
        findings.append(Finding("error", "no version heading such as '## v1.0.0: 2026-11-03'", "CHANGELOG.md"))
    if not (project / "LICENSE").is_file():
        findings.append(Finding("error", "missing licence: the user chooses it", "LICENSE"))
    release = Path(RELEASE_DIR)
    for name, level in ((PLAYER_README, "error"), (NEXUS_DESCRIPTION, "warning"), (NEXUS_SUMMARY, "warning")):
        path = project / release / name
        if not path.is_file():
            findings.append(Finding(level, "missing: run 'mia.py init-release', then 'mia.py store-texts'",
                                    str(release / name)))
        elif TEMPLATE_PLACEHOLDER.search(path.read_text(encoding="utf-8")):
            findings.append(Finding(level, "template placeholders '<...>' still to fill", str(release / name)))
    return findings


def _check_store(project):
    """Return findings for ``release/store.toml`` and the player texts made from it."""
    from . import storetexts

    path = Path(RELEASE_DIR) / storetexts.STORE_FILE
    if not (project / path).is_file():
        return [Finding("warning", "no store file: 'mia.py init-release', fill it, then 'mia.py store-texts'",
                        str(path))]
    try:
        store = storetexts.load(project)
        stale = storetexts.stale(project)
    except storetexts.StoreError as error:
        return [Finding("error", str(error), str(path))]
    findings = [Finding("error", problem, str(path)) for problem in storetexts.problems(store)]
    findings += [Finding("error", "out of date with store.toml or CHANGELOG.md: run 'mia.py store-texts'",
                         str(Path(RELEASE_DIR) / name)) for name in stale]
    findings += [Finding("warning", f"media file missing: {item['file']}", str(path))
                 for item in store.media if not (project / item["file"]).is_file()]
    if not store.links.get("repository"):
        findings.append(Finding("warning", "no GitHub repository yet: 'mia.py publish-repo --create'", str(path)))
    return findings


def _python_missing_docstrings(tree):
    """Return the names of the module, public functions, classes and methods in ``tree`` without a docstring."""
    missing = [] if ast.get_docstring(tree) else ["module"]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and _is_public(node.name):
            if not ast.get_docstring(node):
                missing.append(node.name)
            if isinstance(node, ast.ClassDef):
                missing += [f"{node.name}.{m.name}" for m in node.body
                            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and _is_public(m.name) and not ast.get_docstring(m)]
    return missing


def _lua_missing_comments(text):
    """Return the names of global (non-``local``) Lua functions not preceded by a comment line."""
    lines = text.splitlines()
    missing = []
    for i, line in enumerate(lines):
        match = LUA_FUNCTION.match(line)
        if match and (i == 0 or not LUA_COMMENT.match(lines[i - 1])):
            missing.append(match.group(1))
    return missing


def _imported_miatools(tree):
    """Return the ``miatools`` module names a parsed Python file imports."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == "miatools":
                names |= {alias.name for alias in node.names}
            elif node.module.startswith("miatools."):
                names.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            names |= {a.name.split(".")[1] for a in node.names if a.name.startswith("miatools.")}
    return {n for n in names if (MIATOOLS_DIR / f"{n}.py").is_file()}


def _with_dependencies(modules):
    """Return ``modules`` plus every ``miatools`` module they import, recursively."""
    result, todo = set(), list(modules)
    while todo:
        name = todo.pop()
        if name in result:
            continue
        result.add(name)
        tree = ast.parse((MIATOOLS_DIR / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                todo += [node.module] if node.module else [a.name for a in node.names]
    return result


def _add_to_zip(archive, arcname, source):
    """Add a file, or a folder recursively, to ``archive`` under ``arcname``."""
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_file():
        archive.write(source, arcname)
        return
    for path in sorted(source.rglob("*")):
        if path.is_file():
            archive.write(path, f"{arcname}/{path.relative_to(source).as_posix()}")


def _is_public(name):
    """Return whether a Python name is public (no leading underscore)."""
    return not name.startswith("_")


def _read_text(path):
    """Return the content of a text file, or ``None`` for a binary file."""
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _git(project, *args):
    """Run git in ``project`` and return its output."""
    return subprocess.run(["git", *args], cwd=project, check=True, capture_output=True, text=True).stdout
