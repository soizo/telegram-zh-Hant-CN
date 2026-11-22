# Changelog

## Unreleased

### Changed

- The build workflow runs weekly and only publishes a release when the
  generated checksums differ from the latest release.
- The release archive is named `telegram-zh-hant-cn-<tag>.zip`, where `<tag>`
  is the release tag such as `v2026.11.22` (previously
  `telegram-zh-Hant-CN.zip`). Local builds without `--tag` use today's
  `vYYYY.MM.DD` tag.

### Fixed

- The pack now calls itself `繁體中文(大陸)` in sentences such as
  `使用繁體中文(大陸)繼續`. Only translation options that list other languages
  say `簡體中文`.

## 1.0.0 — 2026-11-22

Full rewrite around standard OpenCC conversion and a single user-maintained
rules file.

### Changed

- Conversion is now standard OpenCC: `s2t` followed by the latest `t2gov`
  configuration. Jieba segmentation and the generated keyword-protection
  markers are gone.
- Every project-specific correction lives in `rules.yml`; the
  `telegram_cngov/rules` package and its five YAML files are removed.
- CLI: `--from` and `--metadata` are gone, `--rules` is new. `--work-dir`
  still keeps intermediate conversions.
- The release automation is a single workflow that builds daily and publishes
  a `vYYYY.MM.DD` release. The release-comparison script is removed.
- Output now always includes a deterministic `telegram-zh-Hant-CN.zip` and
  `SHA256SUMS` alongside the eight platform files.

### Fixed

- Reversed and unbalanced corner quotes are repaired without breaking nested
  quotes or English apostrophes.
- Upstream `.strings` values that closed a corner quote with `\"` are fixed.
- `SendTodayAt` closes its quote with an ASCII apostrophe instead of a curly
  quote.
- Corrections kept for mainland usage and upstream typos: `帳號`→`賬號`,
  `座標`→`坐標`, `撤消`/`撒銷`→`撤銷`, `錶情`, `隻能`, `並`→`并`, `迴`,
  `天后`, `加布裏埃拉`.
