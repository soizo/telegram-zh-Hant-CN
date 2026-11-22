from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from subprocess import CalledProcessError
from typing import Self
from unittest.mock import patch
from urllib.error import URLError
from zipfile import ZipFile

from telegram_cngov.pipeline import (  # pyright: ignore[reportMissingImports]
    FINAL_FILENAMES,
    IMPORT_FILENAMES,
    PLATFORMS,
    PLURAL_QUANTITIES,
    PipelineError,
    Platform,
    apply_rules,
    archive_name,
    create_archive,
    create_import_archive,
    download_t2gov,
    download_text,
    final_hashes,
    flatten_plural_keys,
    import_archive_name,
    import_filename,
    load_rules,
    publish_outputs,
    repair_quotes,
    replace_labels,
    run_opencc,
    safe_extract_zip,
    validate_export,
    write_checksums,
)

ROOT = Path(__file__).parents[1]
RULES = load_rules(ROOT / "rules.yml")


class FakeResponse:
    def __init__(self, payload: bytes, url: str = "https://example.invalid/file"):
        self.payload = payload
        self.url = url

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.payload


class DownloadTests(unittest.TestCase):
    @patch("telegram_cngov.pipeline.sleep")
    @patch("telegram_cngov.pipeline.urlopen")
    def test_transient_failure_is_retried(self, urlopen, _sleep) -> None:
        urlopen.side_effect = [URLError("temporary"), FakeResponse("成功".encode())]
        self.assertEqual(download_text("https://example.invalid/file"), "成功")
        self.assertEqual(urlopen.call_count, 2)

    @patch("telegram_cngov.pipeline.sleep")
    @patch("telegram_cngov.pipeline.urlopen", side_effect=URLError("down"))
    def test_exhausted_download_fails(self, urlopen, _sleep) -> None:
        with self.assertRaisesRegex(PipelineError, "download failed"):
            download_text("https://example.invalid/file")
        self.assertEqual(urlopen.call_count, 3)

    @patch("telegram_cngov.pipeline.urlopen", return_value=FakeResponse(b""))
    def test_empty_download_fails(self, _urlopen) -> None:
        with self.assertRaisesRegex(PipelineError, "empty response"):
            download_text("https://example.invalid/file", attempts=1)

    @patch(
        "telegram_cngov.pipeline.urlopen",
        return_value=FakeResponse(b"ok", "http://example.invalid/file"),
    )
    def test_downgrade_to_http_is_rejected(self, _urlopen) -> None:
        with self.assertRaisesRegex(PipelineError, "only HTTPS"):
            download_text("https://example.invalid/file", attempts=1)

    def test_all_platforms_are_expected(self) -> None:
        self.assertEqual(len(PLATFORMS), 8)
        self.assertEqual(len(FINAL_FILENAMES), 8)

    def test_html_export_is_rejected(self) -> None:
        with self.assertRaisesRegex(PipelineError, "returned HTML"):
            validate_export(PLATFORMS[0], "<!DOCTYPE html><html></html>")


class RuleTests(unittest.TestCase):
    def test_labels_and_inline_names_rewrite_the_pack(self) -> None:
        text = (
            '"LanguageName" = "简体中文";\n'
            '"Continue" = "使用简体中文继续";\n'
            '<string name="language_code">zh_hans</string>\n'
        )
        self.assertEqual(
            replace_labels(text, RULES.labels, RULES.inline),
            '"LanguageName" = "繁体中文(大陆)";\n'
            '"Continue" = "使用繁体中文(大陆)继续";\n'
            '<string name="language_code">zh_hant_cn</string>\n',
        )

    def test_pack_name_inside_sentences_is_rewritten(self) -> None:
        text = (
            '<string name="language_continueInLanguagePopupText">'
            "**Telegram X** 现已可更改语言为 **简体中文**。</string>\n"
            '<string name="language_appliedLanguage">'
            "Telegram 应用的语言已设置为简体中文。</string>\n"
        )
        self.assertEqual(
            replace_labels(text, RULES.labels, RULES.inline),
            '<string name="language_continueInLanguagePopupText">'
            "**Telegram X** 现已可更改语言为 **繁体中文(大陆)**。</string>\n"
            '<string name="language_appliedLanguage">'
            "Telegram 应用的语言已设置为繁体中文(大陆)。</string>\n",
        )

    def test_labels_of_other_languages_are_kept(self) -> None:
        text = (
            '"Translate.Language.Chinese_Simplified" = "简体中文";\n'
            '<string name="Language.zh-CN">简体中文</string>\n'
        )
        self.assertEqual(replace_labels(text, RULES.labels, RULES.inline), text)

    def test_corrections_are_applied_in_order(self) -> None:
        self.assertEqual(
            apply_rules("並迴帳號", RULES.replacements),
            "并回賬號",
        )

    def test_invalid_rules_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.yml"
            path.write_text("labels: [foo]\n", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "labels must be a mapping"):
                load_rules(path)
            path.write_text("- item\n", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "must be a YAML mapping"):
                load_rules(path)


class PluralTests(unittest.TestCase):
    ANDROID = Platform(
        "android",
        "https://example.invalid/android",
        "android.xml",
    )

    def test_android_plurals_collapse_to_the_base_key(self) -> None:
        text = (
            '<resources>\n'
            '    <string name="PeopleJoined_one">一人</string>\n'
            '    <string name="PeopleJoined_other">多人</string>\n'
            '    <string name="Missing">未翻译</string>\n'
            '  <string name="PeopleJoined_zero">零人</string>\n'
            '  <string name="PeopleJoined_two">两人</string>\n'
            '  <string name="PeopleJoined_few">几人</string>\n'
            '  <string name="PeopleJoined_many">多人</string>\n'
            '</resources>\n'
        )
        self.assertEqual(
            flatten_plural_keys(text, self.ANDROID),
            '<resources>\n'
            '    <string name="PeopleJoined">多人</string>\n'
            '    <string name="Missing">未翻译</string>\n'
            '</resources>\n',
        )

    def test_tdesktop_hash_plurals_collapse_to_the_base_key(self) -> None:
        platform = Platform(
            "tdesktop",
            "https://example.invalid/tdesktop",
            "tdesktop.strings",
            plural_delimiter="#",
        )
        text = (
            '"lng_proxy_selected#other" = "已選擇 {count} 個代理";\n'
            '"lng_story_privacy_except_one" = "除 {user} 外";\n'
        )
        self.assertEqual(
            flatten_plural_keys(text, platform),
            '"lng_proxy_selected" = "已選擇 {count} 個代理";\n'
            '"lng_story_privacy_except_one" = "除 {user} 外";\n',
        )

    def test_apple_any_plural_collapses_to_the_base_key(self) -> None:
        platform = Platform(
            "ios",
            "https://example.invalid/ios",
            "ios.strings",
            plural_quantities=("any",),
            preferred_plural=("any",),
        )
        text = '"PUSH_MESSAGE_FWDS_TEXT_any" = "%@ forwarded messages";\n'
        self.assertEqual(
            flatten_plural_keys(text, platform),
            '"PUSH_MESSAGE_FWDS_TEXT" = "%@ forwarded messages";\n',
        )

    def test_duplicate_plural_forms_keep_the_chinese_value(self) -> None:
        platform = Platform(
            "ios",
            "https://example.invalid/ios",
            "ios.strings",
            plural_quantities=("any",),
            preferred_plural=("any",),
        )
        text = (
            '"ProfileLevelInfo.Points_any" = "English value";\n'
            '"Other" = "其他";\n'
            '"ProfileLevelInfo.Points_any" = "中文值";\n'
        )
        result = flatten_plural_keys(text, platform)
        self.assertIn('"ProfileLevelInfo.Points" = "中文值";', result)
        self.assertIn('"Other" = "其他";', result)
        self.assertNotIn("_any", result)
        self.assertNotIn("English value", result)

    def test_duplicate_plain_keys_keep_the_chinese_value(self) -> None:
        platform = Platform(
            "ios",
            "https://example.invalid/ios",
            "ios.strings",
            plural_quantities=("any",),
            preferred_plural=("any",),
        )
        text = (
            '"ProfileLevelInfo.MyDescriptionPreview" = "English";\n'
            '"ProfileLevelInfo.MyDescriptionPreview" = "中文";\n'
        )
        self.assertEqual(
            flatten_plural_keys(text, platform),
            '"ProfileLevelInfo.MyDescriptionPreview" = "中文";\n',
        )

    def test_import_filenames_keep_the_extension(self) -> None:
        self.assertEqual(import_filename("android.xml"), "android-import.xml")
        self.assertEqual(import_filename("ios.strings"), "ios-import.strings")
        self.assertEqual(len(IMPORT_FILENAMES), len(FINAL_FILENAMES))
        self.assertEqual(
            set(PLURAL_QUANTITIES),
            {"zero", "one", "two", "few", "many", "other", "any"},
        )


class QuoteTests(unittest.TestCase):
    def polish(self, text: str) -> str:
        return repair_quotes(apply_rules(text, RULES.replacements))

    def test_same_direction_corner_quotes_are_paired(self) -> None:
        for malformed, expected in (
            ("「文字「", "「文字」"),
            ("」文字」", "「文字」"),
            ("『文字『", "『文字』"),
            ("』文字』", "『文字』"),
        ):
            with self.subTest(malformed=malformed):
                self.assertEqual(self.polish(malformed), expected)

    def test_reversed_corner_quotes_are_turned_around(self) -> None:
        self.assertEqual(
            self.polish("點擊 』AI『> 『%s』。"),
            "點擊 『AI』> 『%s』。",
        )

    def test_curly_quotes_become_corner_quotes(self) -> None:
        self.assertEqual(self.polish("提示詞“示例”"), "提示詞「示例」")

    def test_balanced_nested_quotes_are_unchanged(self) -> None:
        text = "提示詞「使用『喲呵』、『老夥計』等詞語」"
        self.assertEqual(self.polish(text), text)

    def test_english_apostrophes_are_not_quotes(self) -> None:
        text = "Monday’s test doesn’t work; Seller’s share."
        self.assertEqual(self.polish(text), text)

    def test_escaped_ascii_quote_is_closed_with_a_corner_quote(self) -> None:
        self.assertEqual(
            self.polish('爲我和「%@\\"删除'),
            "爲我和「%@」删除",
        )
        self.assertEqual(
            self.polish('話題重命名爲 」%1$@\\"'),
            "話題重命名爲 「%1$@」",
        )

    def test_upstream_apostrophe_typo_is_repaired(self) -> None:
        self.assertEqual(
            self.polish("\\'今天\\' HH:mm ‘發送\\'"),
            "\\'今天\\' HH:mm \\'發送\\'",
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
            self.assertTrue(config.is_file())

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
        for name in FINAL_FILENAMES + IMPORT_FILENAMES:
            (directory / name).write_text(f"content:{name}\n", encoding="utf-8")

    def test_incomplete_source_does_not_replace_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            output = root / "dist"
            output.mkdir()
            (output / "sentinel").write_text("old", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "missing files"):
                publish_outputs(source, output)
            self.assertTrue((output / "sentinel").exists())

    def test_archive_is_reproducible_and_checksums_cover_everything(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "outputs"
            self.populate(outputs)
            first = create_archive(outputs, "v2026.11.22")
            self.assertEqual(first.name, "telegram-zh-hant-cn-v2026.11.22.zip")
            original = first.read_bytes()
            first.unlink()
            second = create_archive(outputs, "v2026.11.22")
            self.assertEqual(original, second.read_bytes())

            import_archive = create_import_archive(outputs, "v2026.11.22")
            self.assertEqual(
                import_archive.name, "telegram-zh-hant-cn-v2026.11.22-import.zip"
            )
            with ZipFile(import_archive) as archive:
                self.assertEqual(set(archive.namelist()), set(IMPORT_FILENAMES))

            checksums = write_checksums(outputs, second, import_archive)
            names = {
                line.split("  ", 1)[1] for line in checksums.read_text().splitlines()
            }
            self.assertEqual(
                names,
                set(FINAL_FILENAMES)
                | set(IMPORT_FILENAMES)
                | {
                    "telegram-zh-hant-cn-v2026.11.22.zip",
                    "telegram-zh-hant-cn-v2026.11.22-import.zip",
                },
            )
            self.assertEqual(
                set(final_hashes(outputs)), set(FINAL_FILENAMES) | set(IMPORT_FILENAMES)
            )

    def test_archive_name_embeds_tag_and_rejects_unsafe_tags(self) -> None:
        self.assertEqual(
            archive_name("v2026.11.22"), "telegram-zh-hant-cn-v2026.11.22.zip"
        )
        self.assertEqual(
            import_archive_name("v2026.11.22"),
            "telegram-zh-hant-cn-v2026.11.22-import.zip",
        )
        with self.assertRaisesRegex(PipelineError, "invalid tag"):
            archive_name("../escape")
        with self.assertRaisesRegex(PipelineError, "invalid tag"):
            import_archive_name("../escape")


if __name__ == "__main__":
    unittest.main()
