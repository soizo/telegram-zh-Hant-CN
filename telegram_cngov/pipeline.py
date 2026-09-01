from __future__ import annotations

import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from http.client import HTTPException, HTTPSConnection
from io import BytesIO
from pathlib import Path, PurePosixPath
from subprocess import CalledProcessError, run
from time import sleep
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .rules import LABEL_RULES, POLISH_RULES, S2T_RULES, T2GOV_RULES, Rules, apply_rules

T2GOV_REPOSITORY = (
    "TerryTian-tech/"
    "OpenCC-Traditional-Chinese-characters-according-to-Chinese-government-standards"
)


@dataclass(frozen=True)
class Platform:
    name: str
    url: str
    filename: str


PLATFORMS = (
    Platform(
        "android",
        "https://translations.telegram.org/zh-hans/android/export",
        "android.xml",
    ),
    Platform(
        "ios", "https://translations.telegram.org/zh-hans/ios/export", "ios.strings"
    ),
    Platform(
        "tdesktop",
        "https://translations.telegram.org/zh-hans/tdesktop/export",
        "tdesktop.strings",
    ),
    Platform(
        "macos",
        "https://translations.telegram.org/zh-hans/macos/export",
        "macos.strings",
    ),
    Platform(
        "android_x",
        "https://translations.telegram.org/zh-hans/android_x/export",
        "android_x.xml",
    ),
    Platform(
        "webk", "https://translations.telegram.org/zh-hans/webk/export", "webk.strings"
    ),
    Platform(
        "weba", "https://translations.telegram.org/zh-hans/weba/export", "weba.strings"
    ),
    Platform(
        "unigram",
        "https://translations.telegram.org/zh-hans/unigram/export",
        "unigram.xml",
    ),
    Platform(
        "emoji",
        "https://translations.telegram.org/zh-hans/emoji/export",
        "emoji.strings",
    ),
)
FINAL_FILENAMES = tuple(sorted(platform.filename for platform in PLATFORMS))


@dataclass(frozen=True)
class StagePaths:
    source: Path
    labelled: Path
    s2t: Path
    output: Path


@dataclass(frozen=True)
class BuildResult:
    files: tuple[Path, ...]
    t2gov_sha: str | None


class PipelineError(RuntimeError):
    """A conversion stage could not complete safely."""


def _https_get(url: str, timeout: float, redirects: int = 5) -> bytes:
    current = url
    for _ in range(redirects + 1):
        parsed = urlsplit(current)
        if parsed.scheme != "https" or not parsed.hostname:
            raise PipelineError(f"only HTTPS downloads are allowed: {current}")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        connection = HTTPSConnection(parsed.hostname, parsed.port, timeout=timeout)
        try:
            connection.request(
                "GET", path, headers={"User-Agent": "telegram-cngov/0.1"}
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise URLError(f"redirect without Location from {current}")
                current = urljoin(current, location)
                continue
            if response.status >= 400:
                raise URLError(f"HTTP {response.status} from {current}")
            return response.read()
        finally:
            connection.close()
    raise URLError(f"too many redirects from {url}")


def download_bytes(url: str, *, attempts: int = 3, timeout: float = 180) -> bytes:
    for attempt in range(1, attempts + 1):
        try:
            payload = _https_get(url, timeout)
            if not payload:
                raise PipelineError(f"empty response from {url}")
            return payload
        except PipelineError:
            raise
        except (HTTPException, OSError, URLError, TimeoutError) as error:
            if attempt == attempts:
                raise PipelineError(
                    f"download failed after {attempts} attempts: {url}"
                ) from error
            sleep(attempt * 3)
    raise AssertionError("unreachable")


def download_text(url: str, *, attempts: int = 3, timeout: float = 180) -> str:
    payload = download_bytes(url, attempts=attempts, timeout=timeout)
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PipelineError(f"response from {url} is not UTF-8") from error


def _read_text(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as file:
        return file.read()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        file.write(text)


def download_sources(destination: Path) -> tuple[Path, ...]:
    destination.mkdir(parents=True, exist_ok=True)

    def download(platform: Platform) -> Path:
        path = destination / platform.filename
        _write_text(path, download_text(platform.url))
        return path

    with ThreadPoolExecutor(max_workers=len(PLATFORMS)) as executor:
        files = tuple(executor.map(download, PLATFORMS))
    _require_files(destination)
    return files


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
    feed_url = f"https://github.com/{T2GOV_REPOSITORY}/commits/main.atom"
    match = re.search(
        r"<id>tag:github\.com,2008:Grit::Commit/([0-9a-f]{40})</id>",
        download_text(feed_url),
    )
    if match is None:
        raise PipelineError("invalid t2gov commit feed")
    commit_sha = match.group(1)
    try:
        int(commit_sha, 16)
    except ValueError as error:
        raise PipelineError("invalid t2gov commit SHA") from error

    archive_url = f"https://github.com/{T2GOV_REPOSITORY}/archive/{commit_sha}.zip"
    safe_extract_zip(download_bytes(archive_url), destination)
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise PipelineError("unexpected t2gov archive layout")
    config = roots[0] / "t2gov" / "t2gov.json"
    for name in (
        "t2gov.json",
        "CJK_Compatibility_Ideographs.txt",
        "TGPhrases.txt",
        "TGCharacters.txt",
    ):
        if not (config.parent / name).is_file():
            raise PipelineError(f"t2gov archive is missing {name}")
    return config, commit_sha


def stage_paths(root: Path) -> StagePaths:
    return StagePaths(
        root / "01-source-zh-Hans",
        root / "02-labels-replaced",
        root / "03-s2t-standard-Hant",
        root / "04-output-zh-Hant-CN",
    )


def _require_files(directory: Path) -> None:
    missing = [name for name in FINAL_FILENAMES if not (directory / name).is_file()]
    if missing:
        raise PipelineError(
            f"missing output files in {directory}: {', '.join(missing)}"
        )


def transform_directory(source: Path, destination: Path, rules: Rules) -> None:
    _require_files(source)
    destination.mkdir(parents=True, exist_ok=True)
    for platform in PLATFORMS:
        _write_text(
            destination / platform.filename,
            apply_rules(_read_text(source / platform.filename), rules),
        )


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


def opencc_directory(
    source: Path, destination: Path, config: str | Path, rules: Rules
) -> None:
    _require_files(source)
    destination.mkdir(parents=True, exist_ok=True)
    for platform in PLATFORMS:
        output = destination / platform.filename
        run_opencc(source / platform.filename, output, config)
        _write_text(output, apply_rules(_read_text(output), rules))


def polish_outputs(directory: Path) -> None:
    _require_files(directory)
    for name in FINAL_FILENAMES:
        path = directory / name
        _write_text(path, apply_rules(_read_text(path), POLISH_RULES))


def _restore_backup(backup: Path | None, output: Path) -> None:
    if backup is None or not backup.exists() or output.exists():
        return
    backup.replace(output)


def publish_outputs(source: Path, output: Path) -> tuple[Path, ...]:
    _require_files(source)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    prepared = Path(tempfile.mkdtemp(prefix=f".{output.name}-new-", dir=output.parent))
    backup: Path | None = None
    try:
        for name in FINAL_FILENAMES:
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
    return tuple(output / name for name in FINAL_FILENAMES)


def _run_in_workspace(root: Path, output: Path, from_step: int) -> BuildResult:
    paths = stage_paths(root)
    t2gov_sha: str | None = None

    if from_step <= 1:
        download_sources(paths.source)
    if from_step <= 2:
        transform_directory(paths.source, paths.labelled, LABEL_RULES)
    if from_step <= 3:
        opencc_directory(paths.labelled, paths.s2t, "s2t", S2T_RULES)
    if from_step <= 4:
        config, t2gov_sha = download_t2gov(root / ".t2gov")
        opencc_directory(paths.s2t, paths.output, config, T2GOV_RULES)
    if from_step <= 5:
        polish_outputs(paths.output)

    return BuildResult(publish_outputs(paths.output, output), t2gov_sha)


def run_pipeline(
    output: Path,
    *,
    work_dir: Path | None = None,
    from_step: int = 1,
) -> BuildResult:
    if from_step not in range(1, 6):
        raise PipelineError("--from must be between 1 and 5")
    if from_step > 1 and work_dir is None:
        raise PipelineError("--from greater than 1 requires --work-dir")
    if work_dir is not None:
        work_dir.mkdir(parents=True, exist_ok=True)
        return _run_in_workspace(work_dir, output, from_step)
    with tempfile.TemporaryDirectory(prefix="telegram-cngov-") as temporary:
        return _run_in_workspace(Path(temporary), output, from_step)


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def final_hashes(directory: Path) -> dict[str, str]:
    _require_files(directory)
    return {name: sha256_file(directory / name) for name in FINAL_FILENAMES}


def create_deterministic_zip(directory: Path, destination: Path) -> None:
    _require_files(directory)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w") as archive:
        for name in FINAL_FILENAMES:
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(
                info,
                (directory / name).read_bytes(),
                compress_type=ZIP_DEFLATED,
                compresslevel=9,
            )


def write_checksums(directory: Path, archive: Path, destination: Path) -> None:
    checksums = final_hashes(directory)
    checksums[archive.name] = sha256_file(archive)
    destination.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())),
        encoding="utf-8",
    )
