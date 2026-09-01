from __future__ import annotations

import subprocess
import tempfile
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from telegram_cngov.pipeline import (  # pyright: ignore[reportMissingImports]
    download_bytes,
)

ARCHIVE_URL = (
    "https://github.com/BYVoid/OpenCC/releases/download/ver.1.4.2/"
    "opencc-1.4.2-1-deb-amd64.zip"
)
ARCHIVE_SHA256 = "5ec8bc9cd4aed58586af969a66e623b6fe22c24ac66af46aa6c81e8b75fea9e1"
PACKAGES = (
    "libopencc-data_1.4.2-1_all.deb",
    "libopencc1.4_1.4.2-1_amd64.deb",
    "opencc_1.4.2-1_amd64.deb",
)


class InstallerError(RuntimeError):
    """The pinned OpenCC release could not be verified or installed."""


def verify_archive(data: bytes) -> None:
    actual = sha256(data).hexdigest()
    if actual != ARCHIVE_SHA256:
        raise InstallerError(f"OpenCC archive checksum mismatch: {actual}")


def extract_packages(data: bytes, destination: Path) -> tuple[Path, ...]:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with ZipFile(BytesIO(data)) as archive:
            paths = []
            for name in PACKAGES:
                try:
                    payload = archive.read(name)
                except KeyError as error:
                    raise InstallerError(f"OpenCC archive is missing {name}") from error
                path = destination / name
                path.write_bytes(payload)
                paths.append(path)
    except BadZipFile as error:
        raise InstallerError("OpenCC archive is not a valid ZIP") from error
    return tuple(paths)


def main() -> int:
    archive = download_bytes(ARCHIVE_URL)
    verify_archive(archive)
    with tempfile.TemporaryDirectory(prefix="opencc-") as temporary:
        packages = extract_packages(archive, Path(temporary))
        subprocess.run(
            ["sudo", "apt-get", "install", "--yes", *(str(path) for path in packages)],
            check=True,
        )
    subprocess.run(["opencc", "--version"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
