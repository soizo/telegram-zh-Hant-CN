import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from scripts.install_opencc import (  # pyright: ignore[reportMissingImports]
    ARCHIVE_SHA256,
    PACKAGES,
    InstallerError,
    extract_packages,
    verify_archive,
)


class InstallerTests(unittest.TestCase):
    def test_archive_checksum_is_required(self) -> None:
        with self.assertRaisesRegex(InstallerError, "checksum"):
            verify_archive(b"not the official archive")

    def test_only_runtime_packages_are_extracted(self) -> None:
        archive = BytesIO()
        with ZipFile(archive, "w") as bundle:
            for name in PACKAGES:
                bundle.writestr(name, name)
            bundle.writestr("libopencc-dev_1.4.2-1_amd64.deb", "skip")
        with tempfile.TemporaryDirectory() as directory:
            paths = extract_packages(archive.getvalue(), Path(directory))
            self.assertEqual(tuple(path.name for path in paths), PACKAGES)
            self.assertFalse((Path(directory) / "libopencc-dev_1.4.2-1_amd64.deb").exists())

    def test_release_workflow_uses_pinned_installer(self) -> None:
        workflow = (
            Path(__file__).parents[1] / ".github/workflows/release.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("python scripts/install_opencc.py", workflow)
        self.assertNotIn("apt-get install --yes opencc", workflow)

    def test_expected_checksum_is_sha256(self) -> None:
        self.assertEqual(len(ARCHIVE_SHA256), 64)
        int(ARCHIVE_SHA256, 16)


if __name__ == "__main__":
    unittest.main()
