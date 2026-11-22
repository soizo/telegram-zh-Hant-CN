"""Convert Telegram zh-Hans exports to zh-Hant-CN.

Conversion itself is standard OpenCC: ``s2t`` followed by the latest ``t2gov``
configuration. Project-specific corrections live in ``rules.yml``.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from http.client import HTTPException
from io import BytesIO
from pathlib import Path, PurePosixPath
from subprocess import CalledProcessError, run
from time import sleep
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import yaml

T2GOV_REPOSITORY = (
    "TerryTian-tech/"
    "OpenCC-Traditional-Chinese-characters-according-to-Chinese-government-standards"
)
T2GOV_CONFIG = "t2gov.json"
ARCHIVE_PREFIX = "telegram-zh-hant-cn"
CHECKSUMS_NAME = "SHA256SUMS"
TAG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
USER_AGENT = "telegram-cngov/0.1"


PLURAL_QUANTITIES = ("zero", "one", "two", "few", "many", "other", "any")
PREFERRED_PLURAL = ("other", "any", "one", "zero", "two", "few", "many")


@dataclass(frozen=True)
class Platform:
    name: str
    url: str
    filename: str
    plural_delimiter: str = "_"
    plural_quantities: tuple[str, ...] = PLURAL_QUANTITIES
    preferred_plural: tuple[str, ...] = PREFERRED_PLURAL


PLATFORMS = (
    Platform(
        "android",
        "https://translations.telegram.org/zh-hans/android/export",
        "android.xml",
    ),
    Platform(
        "ios",
        "https://translations.telegram.org/zh-hans/ios/export",
        "ios.strings",
        plural_quantities=("any",),
        preferred_plural=("any",),
    ),
    Platform(
        "tdesktop",
        "https://translations.telegram.org/zh-hans/tdesktop/export",
        "tdesktop.strings",
        plural_delimiter="#",
    ),
    Platform(
        "macos",
        "https://translations.telegram.org/zh-hans/macos/export",
        "macos.strings",
        plural_quantities=("other", "any"),
    ),
    Platform(
        "android_x",
        "https://translations.telegram.org/zh-hans/android_x/export",
        "android_x.xml",
        plural_quantities=("other",),
    ),
    Platform(
        "webk",
        "https://translations.telegram.org/zh-hans/webk/export",
        "webk.strings",
        plural_quantities=("other",),
    ),
    Platform(
        "weba",
        "https://translations.telegram.org/zh-hans/weba/export",
        "weba.strings",
        plural_quantities=("other",),
    ),
    Platform(
        "unigram",
        "https://translations.telegram.org/zh-hans/unigram/export",
        "unigram.xml",
        plural_quantities=("other",),
    ),
)
FINAL_FILENAMES = tuple(sorted(platform.filename for platform in PLATFORMS))


def import_filename(name: str) -> str:
    """Return the import-friendly filename for a release file."""
    path = PurePosixPath(name)
    return f"{path.stem}-import{path.suffix}"


IMPORT_FILENAMES = tuple(import_filename(name) for name in FINAL_FILENAMES)
RELEASE_FILENAMES = FINAL_FILENAMES + IMPORT_FILENAMES

Rule = tuple[str, str]


@dataclass(frozen=True)
class Rules:
    labels: tuple[Rule, ...] = ()
    inline: tuple[Rule, ...] = ()
    replacements: tuple[Rule, ...] = ()


@dataclass(frozen=True)
class BuildResult:
    output: Path
    files: tuple[Path, ...]
    import_files: tuple[Path, ...]
    archive: Path
    import_archive: Path
    t2gov_sha: str


class PipelineError(RuntimeError):
    """A conversion step could not complete safely."""


def _pairs(value: Any, name: str, path: Path) -> tuple[Rule, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise PipelineError(f"{path}: {name} must be a mapping")
    pairs: list[Rule] = []
    for old, new in value.items():
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            raise PipelineError(f"{path}: invalid {name} entry: {old!r}: {new!r}")
        pairs.append((old, new))
    return tuple(pairs)


def load_rules(path: Path) -> Rules:
    """Read the user-maintained corrections from a YAML mapping."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise PipelineError(f"could not read rules from {path}") from error
    if not isinstance(data, dict):
        raise PipelineError(f"{path}: rules must be a YAML mapping")
    return Rules(
        labels=_pairs(data.get("labels"), "labels", path),
        inline=_pairs(data.get("inline"), "inline", path),
        replacements=_pairs(data.get("replacements"), "replacements", path),
    )


# Entries that name some other language must keep their own label.
FOREIGN_LABEL_KEY = re.compile(
    r'^\s*(?:<string\s+name="?|")'
    r"(?:Language\.[a-z]{2,3}(?:-[A-Za-z]{2,4})?"
    r"|Translate\.Language|Translation\.Language|TranslateLanguage)"
)


def replace_labels(
    text: str, labels: tuple[Rule, ...], inline: tuple[Rule, ...] = ()
) -> str:
    """Rename the pack, including where it names itself inside a sentence."""
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if FOREIGN_LABEL_KEY.match(line) is None:
            for old, new in labels:
                line = line.replace(f'"{old}"', f'"{new}"')
                line = line.replace(f">{old}<", f">{new}<")
            for old, new in inline:
                line = line.replace(old, new)
        lines.append(line)
    return "".join(lines)


def apply_rules(text: str, rules: tuple[Rule, ...]) -> str:
    for old, new in rules:
        text = text.replace(old, new)
    return text


# A .strings entry may span lines and may carry a trailing // comment.
STRINGS_ENTRY = re.compile(
    r'^"(?P<key>[^"]+)"\s*=\s*"(?P<value>(?:[^"\\]|\\.)*)";[ \t]*(?://[^\n]*)?$',
    re.MULTILINE | re.DOTALL,
)


def _plural_quantities(platform: Platform) -> str:
    return "|".join(re.escape(quantity) for quantity in platform.plural_quantities)


def _choose_plural(
    items: list[tuple[int, str, str]], platform: Platform
) -> tuple[int, str, str]:
    """Pick the value for the target language from all entries of a key."""
    for quantity in platform.preferred_plural:
        matches = [item for item in items if item[1] == quantity]
        if matches:
            return max(matches, key=lambda item: item[0])
    return max(items, key=lambda item: item[0])


def _apply_actions(
    text: str, entries: list[re.Match[str]], actions: dict[int, str | None]
) -> str:
    pieces: list[str] = []
    last = 0
    for index, entry in enumerate(entries):
        if index not in actions:
            continue
        pieces.append(text[last : entry.start()])
        replacement = actions[index]
        last = entry.end()
        if replacement is not None:
            pieces.append(replacement)
        elif text.startswith("\n", last):
            last += 1
    pieces.append(text[last:])
    return "".join(pieces)


def _flatten_xml_plurals(text: str, platform: Platform) -> str:
    pattern = re.compile(
        r'^(?P<indent>\s*)<string name="(?P<base>[^"]+?)'
        + re.escape(platform.plural_delimiter)
        + r"(?P<quantity>"
        + _plural_quantities(platform)
        + r')"[^>]*>(?P<value>.*?)</string>\s*$',
        re.DOTALL,
    )
    lines = text.splitlines(keepends=True)
    groups: dict[str, list[tuple[int, str, str, str]]] = {}
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match is not None:
            groups.setdefault(match.group("base"), []).append(
                (
                    index,
                    match.group("quantity"),
                    match.group("indent"),
                    match.group("value"),
                )
            )

    replacements: dict[int, str] = {}
    removed: set[int] = set()
    for base, items in groups.items():
        index, _, value = _choose_plural(
            [(item[0], item[1], item[3]) for item in items],
            platform,
        )
        indent = next(item[2] for item in items if item[0] == index)
        newline = "\n" if lines[index].endswith("\n") else ""
        replacements[index] = f'{indent}<string name="{base}">{value}</string>{newline}'
        removed.update(item[0] for item in items)
        removed.discard(index)

    if not replacements:
        return text

    output: list[str] = []
    for index, line in enumerate(lines):
        if index in replacements:
            output.append(replacements[index])
        elif index not in removed:
            output.append(line)
    return "".join(output)


def _flatten_strings_plurals(text: str, platform: Platform) -> str:
    key_pattern = re.compile(
        r"^(?P<base>.+)"
        + re.escape(platform.plural_delimiter)
        + r"(?P<quantity>"
        + _plural_quantities(platform)
        + r")$"
    )
    entries = list(STRINGS_ENTRY.finditer(text))
    groups: dict[str, list[tuple[int, str, str]]] = {}
    for index, entry in enumerate(entries):
        key_match = key_pattern.match(entry.group("key"))
        if key_match is not None:
            groups.setdefault(key_match.group("base"), []).append(
                (index, key_match.group("quantity"), entry.group("value"))
            )

    actions: dict[int, str | None] = {}
    for base, items in groups.items():
        chosen, _, value = _choose_plural(items, platform)
        actions[chosen] = f'"{base}" = "{value}";'
        for index, _, _ in items:
            if index != chosen:
                actions[index] = None

    if not actions:
        return text
    return _apply_actions(text, entries, actions)


def _has_cjk(value: str) -> bool:
    return re.search(r"[\u3400-\u9fff]", value) is not None


def _dedupe_xml_import(text: str) -> str:
    pattern = re.compile(
        r'^(?P<indent>\s*)<string name="(?P<key>[^"]+)"[^>]*>'
        r"(?P<value>.*?)</string>\s*$",
        re.DOTALL,
    )
    lines = text.splitlines(keepends=True)
    seen: dict[str, int] = {}
    replacements: dict[int, str] = {}
    removed: set[int] = set()
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match is None:
            continue
        key = match.group("key")
        if key not in seen:
            seen[key] = index
            continue
        previous = pattern.match(lines[seen[key]])
        assert previous is not None
        old_value = previous.group("value")
        new_value = match.group("value")
        if new_value != old_value and _has_cjk(new_value) and not _has_cjk(old_value):
            replacements[seen[key]] = (
                f'{match.group("indent")}<string name="{key}">{new_value}</string>\n'
            )
        removed.add(index)
    output: list[str] = []
    for index, line in enumerate(lines):
        if index in replacements:
            output.append(replacements[index])
        elif index not in removed:
            output.append(line)
    return "".join(output)


def _dedupe_strings_import(text: str) -> str:
    entries = list(STRINGS_ENTRY.finditer(text))
    seen: dict[str, tuple[int, re.Match[str]]] = {}
    actions: dict[int, str | None] = {}
    for index, entry in enumerate(entries):
        key = entry.group("key")
        if key not in seen:
            seen[key] = (index, entry)
            continue
        old_index, old_entry = seen[key]
        new_value = entry.group("value")
        if new_value != old_entry.group("value") and _has_cjk(new_value) and not _has_cjk(
            old_entry.group("value")
        ):
            actions[old_index] = f'"{key}" = "{new_value}";'
        actions[index] = None
    if not actions:
        return text
    return _apply_actions(text, entries, actions)


def _dedupe_import(text: str, platform: Platform) -> str:
    if platform.filename.endswith(".xml"):
        return _dedupe_xml_import(text)
    return _dedupe_strings_import(text)


def flatten_plural_keys(text: str, platform: Platform) -> str:
    """Collapse plural forms into the base keys used by the import tool.

    The translation platform's importer only understands plain keys. Android
    and web exports spell plurals as ``Key_other``; Telegram Desktop uses
    ``Key#other``; Apple exports use ``Key_any``. For Chinese each plural has a
    single form, so one value per base key is enough.
    """
    if platform.filename.endswith(".xml"):
        flattened = _flatten_xml_plurals(text, platform)
    else:
        flattened = _flatten_strings_plurals(text, platform)
    return _dedupe_import(flattened, platform)


OPENING_QUOTES = {"「": "」", "『": "』"}
CLOSING_QUOTES = {close: opening for opening, close in OPENING_QUOTES.items()}
# Upstream .strings values occasionally close a corner quote with an escaped
# ASCII quote, for example: "We delete messages for「%@\" from this chat".
ESCAPED_QUOTE = re.compile(r'([「」])([^「」\n]*?)\\"')
# A straight-closing quote between ASCII letters is an English apostrophe.
APOSTROPHE = re.compile(r"(?<![A-Za-z])’|’(?![A-Za-z])")


def _pair_quotes(line: str) -> str:
    output: list[str] = []
    stack: list[str] = []
    for index, char in enumerate(line):
        if char in OPENING_QUOTES:
            if stack and stack[-1] == char:
                output.append(OPENING_QUOTES[char])
                stack.pop()
            else:
                output.append(char)
                stack.append(char)
        elif char in CLOSING_QUOTES:
            opening = CLOSING_QUOTES[char]
            if stack and stack[-1] == opening:
                output.append(char)
                stack.pop()
            elif any(quote in (opening, char) for quote in line[index + 1 :]):
                output.append(opening)
                stack.append(opening)
            else:
                output.append(char)
        else:
            output.append(char)
    return "".join(output)


def repair_quotes(text: str) -> str:
    """Close corner quotes that upstream opened or reversed incorrectly."""
    text = ESCAPED_QUOTE.sub(r"「\2」", text)
    text = APOSTROPHE.sub("』", text)
    return "".join(_pair_quotes(line) for line in text.splitlines(keepends=True))


def download_bytes(url: str, *, attempts: int = 3, timeout: float = 180) -> bytes:
    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout) as response:
                if urlsplit(response.url).scheme != "https":
                    raise PipelineError(f"only HTTPS downloads are allowed: {url}")
                payload = response.read()
            if not payload:
                raise PipelineError(f"empty response from {url}")
            return payload
        except PipelineError:
            raise
        except (HTTPException, OSError, URLError) as error:
            if attempt == attempts:
                raise PipelineError(
                    f"download failed after {attempts} attempts: {url}"
                ) from error
            sleep(attempt * 3)
    raise AssertionError("unreachable")


def download_text(url: str, *, attempts: int = 3, timeout: float = 180) -> str:
    try:
        return download_bytes(url, attempts=attempts, timeout=timeout).decode("utf-8")
    except UnicodeDecodeError as error:
        raise PipelineError(f"response from {url} is not UTF-8") from error


def validate_export(platform: Platform, text: str) -> None:
    start = text.lstrip("\ufeff \t\r\n").lower()
    if start.startswith(("<!doctype html", "<html")):
        raise PipelineError(
            f"{platform.name} export returned HTML instead of translations"
        )


def _read_text(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as file:
        return file.read()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        file.write(text)


def _require_files(
    directory: Path, names: tuple[str, ...] = FINAL_FILENAMES
) -> None:
    missing = [name for name in names if not (directory / name).is_file()]
    if missing:
        raise PipelineError(f"missing files in {directory}: {', '.join(missing)}")


def download_sources(destination: Path, rules: Rules) -> None:
    destination.mkdir(parents=True, exist_ok=True)

    def fetch(platform: Platform) -> None:
        text = download_text(platform.url)
        validate_export(platform, text)
        _write_text(
            destination / platform.filename,
            replace_labels(text, rules.labels, rules.inline),
        )

    with ThreadPoolExecutor(max_workers=len(PLATFORMS)) as executor:
        tuple(executor.map(fetch, PLATFORMS))
    _require_files(destination)


def safe_extract_zip(data: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(BytesIO(data)) as archive:
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise PipelineError(f"unsafe archive path: {member.filename}")
            target = destination.joinpath(*path.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def download_t2gov(destination: Path) -> tuple[Path, str]:
    """Fetch the newest t2gov commit and return its OpenCC config."""
    feed = download_text(f"https://github.com/{T2GOV_REPOSITORY}/commits/main.atom")
    match = re.search(r"Grit::Commit/([0-9a-f]{40})", feed)
    if match is None:
        raise PipelineError("invalid t2gov commit feed")
    commit_sha = match.group(1)

    safe_extract_zip(
        download_bytes(
            f"https://github.com/{T2GOV_REPOSITORY}/archive/{commit_sha}.zip"
        ),
        destination,
    )
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise PipelineError("unexpected t2gov archive layout")
    config = roots[0] / "t2gov" / T2GOV_CONFIG
    for name in (
        T2GOV_CONFIG,
        "CJK_Compatibility_Ideographs.txt",
        "TGPhrases.txt",
        "TGCharacters.txt",
    ):
        if not (config.parent / name).is_file():
            raise PipelineError(f"t2gov archive is missing {name}")
    return config, commit_sha


def run_opencc(source: Path, destination: Path, config: str | Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        run(
            ["opencc", "-c", str(config), "-i", str(source), "-o", str(destination)],
            check=True,
        )
    except FileNotFoundError as error:
        raise PipelineError(
            "OpenCC is not installed; install the official opencc CLI"
        ) from error
    except CalledProcessError as error:
        raise PipelineError(f"OpenCC failed for {source.name}") from error
    if not destination.is_file():
        raise PipelineError(f"OpenCC produced no output for {source.name}")


def opencc_directory(source: Path, destination: Path, config: str | Path) -> None:
    _require_files(source)
    destination.mkdir(parents=True, exist_ok=True)
    for name in FINAL_FILENAMES:
        run_opencc(source / name, destination / name, config)


def convert_directory(source: Path, destination: Path, rules: Rules) -> None:
    _require_files(source)
    destination.mkdir(parents=True, exist_ok=True)
    for platform in PLATFORMS:
        text = repair_quotes(
            apply_rules(_read_text(source / platform.filename), rules.replacements)
        )
        _write_text(destination / platform.filename, text)
        _write_text(
            destination / import_filename(platform.filename),
            flatten_plural_keys(text, platform),
        )


def _restore_backup(backup: Path | None, output: Path) -> None:
    if backup is None or not backup.exists() or output.exists():
        return
    backup.replace(output)


def publish_outputs(source: Path, output: Path) -> tuple[Path, ...]:
    _require_files(source, RELEASE_FILENAMES)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    prepared = Path(tempfile.mkdtemp(prefix=f".{output.name}-new-", dir=output.parent))
    backup: Path | None = None
    try:
        for name in RELEASE_FILENAMES:
            shutil.copy2(source / name, prepared / name)
        if output.exists():
            backup = Path(
                tempfile.mkdtemp(prefix=f".{output.name}-old-", dir=output.parent)
            )
            backup.rmdir()
            output.replace(backup)
        prepared.replace(output)
    except OSError as error:
        _restore_backup(backup, output)
        raise PipelineError(f"could not install outputs at {output}") from error
    finally:
        if prepared.exists():
            shutil.rmtree(prepared)
        if backup is not None and backup.exists():
            shutil.rmtree(backup)
    return tuple(output / name for name in RELEASE_FILENAMES)


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def final_hashes(directory: Path) -> dict[str, str]:
    _require_files(directory, RELEASE_FILENAMES)
    return {name: sha256_file(directory / name) for name in RELEASE_FILENAMES}


def default_tag() -> str:
    """Return today's release tag, matching the ``vYYYY.MM.DD`` scheme."""
    return f"v{datetime.now(UTC):%Y.%m.%d}"


def archive_name(tag: str) -> str:
    """Return the tagged archive filename for ``tag``."""
    if not TAG_PATTERN.fullmatch(tag):
        raise PipelineError(f"invalid tag: {tag!r}")
    return f"{ARCHIVE_PREFIX}-{tag}.zip"


def import_archive_name(tag: str) -> str:
    """Return the tagged import archive filename for ``tag``."""
    if not TAG_PATTERN.fullmatch(tag):
        raise PipelineError(f"invalid tag: {tag!r}")
    return f"{ARCHIVE_PREFIX}-{tag}-import.zip"


def _write_archive(
    directory: Path, archive: Path, names: tuple[str, ...]
) -> Path:
    with ZipFile(archive, "w") as output:
        for name in names:
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            output.writestr(
                info,
                (directory / name).read_bytes(),
                compress_type=ZIP_DEFLATED,
                compresslevel=9,
            )
    return archive


def create_archive(directory: Path, tag: str | None = None) -> Path:
    _require_files(directory)
    return _write_archive(
        directory,
        directory / archive_name(tag or default_tag()),
        FINAL_FILENAMES,
    )


def create_import_archive(directory: Path, tag: str | None = None) -> Path:
    _require_files(directory, IMPORT_FILENAMES)
    return _write_archive(
        directory,
        directory / import_archive_name(tag or default_tag()),
        IMPORT_FILENAMES,
    )


def write_checksums(directory: Path, *archives: Path) -> Path:
    checksums = final_hashes(directory)
    for archive in archives:
        checksums[archive.name] = sha256_file(archive)
    destination = directory / CHECKSUMS_NAME
    destination.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())),
        encoding="utf-8",
    )
    return destination


def _prepare(directory: Path) -> Path:
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    return directory


def _build(root: Path, output: Path, rules: Rules, tag: str) -> BuildResult:
    source = _prepare(root / "source")
    hant = _prepare(root / "hant")
    gov = _prepare(root / "gov")
    staging = _prepare(root / "staging")

    download_sources(source, rules)
    opencc_directory(source, hant, "s2t")
    config, t2gov_sha = download_t2gov(_prepare(root / "t2gov"))
    opencc_directory(hant, gov, config)
    convert_directory(gov, staging, rules)

    published = publish_outputs(staging, output)
    files = tuple(path for path in published if path.name in FINAL_FILENAMES)
    import_files = tuple(path for path in published if path.name in IMPORT_FILENAMES)
    archive = create_archive(output, tag)
    import_archive = create_import_archive(output, tag)
    write_checksums(output, archive, import_archive)
    return BuildResult(
        output.resolve(),
        files,
        import_files,
        archive,
        import_archive,
        t2gov_sha,
    )


def build(
    output: Path,
    *,
    tag: str | None = None,
    work_dir: Path | None = None,
    rules: Path = Path("rules.yml"),
) -> BuildResult:
    """Run the whole conversion and publish the result to ``output``."""
    loaded = load_rules(rules)
    selected_tag = tag or default_tag()
    if work_dir is not None:
        work_dir.mkdir(parents=True, exist_ok=True)
        return _build(work_dir, output, loaded, selected_tag)
    with tempfile.TemporaryDirectory(prefix="telegram-cngov-") as temporary:
        return _build(Path(temporary), output, loaded, selected_tag)
