from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from telegram_cngov.pipeline import (  # pyright: ignore[reportMissingImports]
    FINAL_FILENAMES,
    PLATFORMS,
    create_deterministic_zip,
    final_hashes,
    write_checksums,
)

MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ([^/]+)")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class ReleaseError(RuntimeError):
    """Release state is incomplete or unsafe to publish."""


@dataclass(frozen=True)
class ReleaseDecision:
    changed: bool
    tag: str | None = None
    archive_name: str | None = None


def parse_manifest(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in text.splitlines():
        match = MANIFEST_LINE.fullmatch(line)
        if match is None:
            raise ReleaseError(f"malformed SHA256SUMS line: {line!r}")
        digest, name = match.groups()
        if name in entries:
            raise ReleaseError(f"duplicate SHA256SUMS entry: {name}")
        entries[name] = digest
    missing = set(FINAL_FILENAMES) - entries.keys()
    if missing:
        raise ReleaseError(f"SHA256SUMS is missing: {', '.join(sorted(missing))}")
    return {name: entries[name] for name in FINAL_FILENAMES}


def choose_tag(existing: Callable[[str], bool], today: dt.date) -> str:
    base = f"v{today:%Y.%m.%d}"
    if not existing(base):
        return base
    suffix = 2
    while existing(f"{base}.{suffix}"):
        suffix += 1
    return f"{base}.{suffix}"


def _gh(*args: str, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args],
        check=False,
        capture_output=True,
        text=not binary,
    )


def _gh_error(process: subprocess.CompletedProcess) -> str:
    error = process.stderr
    if isinstance(error, bytes):
        return error.decode("utf-8", errors="replace")
    return error or "unknown gh error"


def _latest_hashes(repository: str) -> dict[str, str] | None:
    result = _gh("api", f"repos/{repository}/releases/latest")
    if result.returncode:
        error = _gh_error(result)
        if "HTTP 404" in error:
            return None
        raise ReleaseError(f"could not read latest release: {error.strip()}")
    try:
        release = json.loads(result.stdout)
        matches = [
            asset for asset in release["assets"] if asset["name"] == "SHA256SUMS"
        ]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ReleaseError("latest release response is malformed") from error
    if len(matches) != 1:
        raise ReleaseError("latest release must contain exactly one SHA256SUMS asset")
    result = _gh(
        "api",
        matches[0]["url"],
        "-H",
        "Accept: application/octet-stream",
        binary=True,
    )
    if result.returncode:
        raise ReleaseError(
            f"could not download SHA256SUMS: {_gh_error(result).strip()}"
        )
    try:
        return parse_manifest(result.stdout.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ReleaseError("latest SHA256SUMS is not UTF-8") from error


def _tag_exists(repository: str, tag: str) -> bool:
    result = _gh("api", f"repos/{repository}/git/ref/tags/{quote(tag, safe='')}")
    if not result.returncode:
        return True
    error = _gh_error(result)
    if "HTTP 404" in error:
        return False
    raise ReleaseError(f"could not check tag {tag}: {error.strip()}")


def _write_workflow_output(path: Path, **values: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")


def prepare_release(
    dist: Path,
    metadata: Path,
    repository: str,
    workflow_output: Path,
    summary: Path,
    notes: Path,
) -> ReleaseDecision:
    if REPOSITORY.fullmatch(repository) is None:
        raise ReleaseError(f"invalid GitHub repository: {repository}")
    current = final_hashes(dist)
    previous = _latest_hashes(repository)
    if previous == current:
        _write_workflow_output(workflow_output, changed="false")
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(
            "## Translation update\n\nNo translation changes; no Release created.\n",
            encoding="utf-8",
        )
        return ReleaseDecision(False)

    try:
        t2gov_sha = json.loads(metadata.read_text(encoding="utf-8"))["t2gov_sha"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ReleaseError("build metadata is missing or malformed") from error
    if (
        not isinstance(t2gov_sha, str)
        or re.fullmatch(r"[0-9a-f]{40}", t2gov_sha) is None
    ):
        raise ReleaseError("build metadata contains an invalid t2gov SHA")

    now = dt.datetime.now(dt.UTC)
    tag = choose_tag(lambda candidate: _tag_exists(repository, candidate), now.date())
    archive_name = f"telegram-zh-Hant-CN-{tag}.zip"
    archive = dist / archive_name
    create_deterministic_zip(dist, archive)
    write_checksums(dist, archive, dist / "SHA256SUMS")

    notes.parent.mkdir(parents=True, exist_ok=True)
    sources = "\n".join(f"- {platform.name}: {platform.url}" for platform in PLATFORMS)
    notes.write_text(
        f"Generated: {now:%Y-%m-%d %H:%M:%S} UTC\n\n"
        f"t2gov commit: `{t2gov_sha}`\n\n"
        f"Telegram sources:\n{sources}\n",
        encoding="utf-8",
    )
    _write_workflow_output(
        workflow_output,
        changed="true",
        tag=tag,
        archive=archive_name,
    )
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        f"## Translation update\n\nPublishing `{tag}`.\n", encoding="utf-8"
    )
    return ReleaseDecision(True, tag, archive_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare",))
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    args = parser.parse_args(argv)

    repository = os.environ.get("GITHUB_REPOSITORY")
    workflow_output = os.environ.get("GITHUB_OUTPUT")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    missing = [
        name
        for name, value in (
            ("GITHUB_REPOSITORY", repository),
            ("GITHUB_OUTPUT", workflow_output),
            ("GITHUB_STEP_SUMMARY", summary),
        )
        if not value
    ]
    if missing:
        parser.error(f"missing environment: {', '.join(missing)}")
    assert (
        repository is not None and workflow_output is not None and summary is not None
    )
    try:
        prepare_release(
            args.dist,
            args.metadata,
            repository,
            Path(workflow_output),
            Path(summary),
            args.notes,
        )
    except ReleaseError as error:
        parser.exit(1, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
