import datetime as dt
import unittest

from scripts.release import (  # pyright: ignore[reportMissingImports]
    ReleaseError,
    choose_tag,
    parse_manifest,
)
from telegram_cngov.pipeline import (  # pyright: ignore[reportMissingImports]
    FINAL_FILENAMES,
)


class ManifestTests(unittest.TestCase):
    def test_manifest_requires_every_final_file(self) -> None:
        text = "\n".join(f"{'0' * 64}  {name}" for name in FINAL_FILENAMES[:-1])
        with self.assertRaisesRegex(ReleaseError, "missing"):
            parse_manifest(text)

    def test_manifest_ignores_archive_hash(self) -> None:
        text = "\n".join(
            [
                *(f"{'0' * 64}  {name}" for name in FINAL_FILENAMES),
                f"{'1' * 64}  telegram-zh-Hant-CN-v2026.09.01.zip",
            ]
        )
        self.assertEqual(set(parse_manifest(text)), set(FINAL_FILENAMES))


class TagTests(unittest.TestCase):
    def test_first_tag_uses_date(self) -> None:
        self.assertEqual(
            choose_tag(lambda _tag: False, dt.date(2026, 9, 1)),
            "v2026.09.01",
        )

    def test_existing_tags_get_next_suffix(self) -> None:
        existing = {"v2026.09.01", "v2026.09.01.2"}
        self.assertEqual(
            choose_tag(existing.__contains__, dt.date(2026, 9, 1)),
            "v2026.09.01.3",
        )


if __name__ == "__main__":
    unittest.main()
