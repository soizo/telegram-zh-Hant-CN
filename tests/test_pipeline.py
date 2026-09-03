import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from subprocess import CalledProcessError
from unittest.mock import patch
from urllib.error import URLError
from zipfile import ZipFile

from telegram_cngov.pipeline import (  # pyright: ignore[reportMissingImports]
    FINAL_FILENAMES,
    PLATFORMS,
    PipelineError,
    create_deterministic_zip,
    download_t2gov,
    download_text,
    final_hashes,
    polish_outputs,
    publish_outputs,
    run_opencc,
    safe_extract_zip,
    validate_export,
)


class DownloadTests(unittest.TestCase):
    @patch("telegram_cngov.pipeline.sleep")
    @patch("telegram_cngov.pipeline._https_get")
    def test_transient_failure_is_retried(self, https_get, _sleep) -> None:
        https_get.side_effect = [URLError("temporary"), "成功".encode()]
        self.assertEqual(download_text("https://example.invalid/file"), "成功")
        self.assertEqual(https_get.call_count, 2)

    @patch("telegram_cngov.pipeline.sleep")
    @patch("telegram_cngov.pipeline._https_get", side_effect=URLError("down"))
    def test_exhausted_download_fails(self, https_get, _sleep) -> None:
        with self.assertRaisesRegex(PipelineError, "download failed"):
            download_text("https://example.invalid/file")
        self.assertEqual(https_get.call_count, 3)

    @patch("telegram_cngov.pipeline._https_get", return_value=b"")
    def test_empty_download_fails(self, _https_get) -> None:
        with self.assertRaisesRegex(PipelineError, "empty response"):
            download_text("https://example.invalid/file", attempts=1)

    def test_unsupported_emoji_export_is_excluded(self) -> None:
        self.assertEqual(len(PLATFORMS), 8)
        self.assertNotIn("emoji.strings", FINAL_FILENAMES)

    def test_html_export_is_rejected(self) -> None:
        with self.assertRaisesRegex(PipelineError, "returned HTML"):
            validate_export(PLATFORMS[0], "<!DOCTYPE html><html></html>")


class PolishTests(unittest.TestCase):
    def test_same_direction_corner_quotes_are_paired(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for malformed in ("「文字「", "」文字」"):
                for name in FINAL_FILENAMES:
                    (root / name).write_text(malformed, encoding="utf-8")

                polish_outputs(root)

                for name in FINAL_FILENAMES:
                    self.assertEqual(
                        (root / name).read_text(encoding="utf-8"), "「文字」"
                    )


class ArchiveTests(unittest.TestCase):
    def test_parent_traversal_is_rejected(self) -> None:
        payload = BytesIO()
        with ZipFile(payload, "w") as archive:
            archive.writestr("../escape.txt", "bad")
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(PipelineError, "unsafe archive path"),
        ):
            safe_extract_zip(payload.getvalue(), Path(directory))

    @patch("telegram_cngov.pipeline.download_bytes")
    @patch("telegram_cngov.pipeline.download_text")
    def test_t2gov_commit_comes_from_atom_feed(
        self, download_text, download_bytes
    ) -> None:
        commit_sha = "a" * 40
        download_text.return_value = (
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            f"<id>tag:github.com,2008:Grit::Commit/{commit_sha}</id>"
            "</entry></feed>"
        )
        payload = BytesIO()
        with ZipFile(payload, "w") as archive:
            for name in (
                "t2gov.json",
                "CJK_Compatibility_Ideographs.txt",
                "TGPhrases.txt",
                "TGCharacters.txt",
            ):
                archive.writestr(f"repository/t2gov/{name}", "data")
        download_bytes.return_value = payload.getvalue()

        with tempfile.TemporaryDirectory() as directory:
            config, actual_sha = download_t2gov(Path(directory))

        self.assertEqual(actual_sha, commit_sha)
        self.assertEqual(config.name, "t2gov.json")
        self.assertIn("commits/main.atom", download_text.call_args.args[0])


class OpenCCTests(unittest.TestCase):
    @patch("telegram_cngov.pipeline.run")
    def test_opencc_uses_argument_array(self, run) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "in.txt"
            output = root / "out.txt"
            run.side_effect = lambda *_args, **_kwargs: output.write_text(
                "converted", encoding="utf-8"
            )
            run_opencc(source, output, "s2t")
            run.assert_called_once_with(
                ["opencc", "-c", "s2t", "-i", str(source), "-o", str(output)],
                check=True,
            )

    @patch("telegram_cngov.pipeline.run")
    def test_opencc_must_create_output(self, _run) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(PipelineError, "produced no output"):
                run_opencc(root / "in", root / "out", "s2t")

    @patch("telegram_cngov.pipeline.run", side_effect=CalledProcessError(1, ["opencc"]))
    def test_opencc_failure_is_reported(self, _run) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(PipelineError, "OpenCC failed"):
                run_opencc(root / "in", root / "out", "s2t")


class OutputTests(unittest.TestCase):
    def populate(self, directory: Path) -> None:
        directory.mkdir()
        for name in FINAL_FILENAMES:
            (directory / name).write_text(f"content:{name}\n", encoding="utf-8")

    def test_incomplete_source_does_not_replace_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            output = root / "dist"
            output.mkdir()
            (output / "sentinel").write_text("old", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "missing output"):
                publish_outputs(source, output)
            self.assertTrue((output / "sentinel").exists())

    def test_zip_is_reproducible_and_hashes_cover_final_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "outputs"
            self.populate(outputs)
            first = root / "first.zip"
            second = root / "second.zip"
            create_deterministic_zip(outputs, first)
            create_deterministic_zip(outputs, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(set(final_hashes(outputs)), set(FINAL_FILENAMES))


if __name__ == "__main__":
    unittest.main()
