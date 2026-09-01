import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telegram_cngov.__main__ import main  # pyright: ignore[reportMissingImports]
from telegram_cngov.pipeline import BuildResult  # pyright: ignore[reportMissingImports]


class CliTests(unittest.TestCase):
    def test_resume_requires_persistent_work_directory(self) -> None:
        with self.assertRaises(SystemExit) as error:
            main(["--from", "2"])
        self.assertEqual(error.exception.code, 2)

    @patch("telegram_cngov.__main__.run_pipeline")
    def test_metadata_is_written_when_requested(self, run_pipeline) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "dist"
            metadata = root / "meta" / "build.json"
            run_pipeline.return_value = BuildResult((), "a" * 40)
            self.assertEqual(
                main(["--output", str(output), "--metadata", str(metadata)]),
                0,
            )
            self.assertEqual(
                json.loads(metadata.read_text(encoding="utf-8")),
                {"t2gov_sha": "a" * 40},
            )


if __name__ == "__main__":
    unittest.main()
