# Telegram Chinese Traditional (Mainland)

**Apply the language pack in Telegram:** [t.me/setlanguage/chinese-traditional-mainland](https://t.me/setlanguage/chinese-traditional-mainland)

Converts Telegram's Simplified Chinese (`zh-Hans`) translation exports into
**Traditional Chinese with PRC-standard glyphs** (`zh-Hant-CN`).

## How it works

1. Download the Android, iOS, Telegram Desktop, macOS, Android X, Web K, Web A,
   and Unigram exports.
2. Rename the language-pack labels listed in [`rules.yml`](rules.yml).
3. Run OpenCC `s2t`.
4. Run the latest [`t2gov`](https://github.com/TerryTian-tech/OpenCC-Traditional-Chinese-characters-according-to-Chinese-government-standards)
   OpenCC configuration.
5. Apply the project corrections in `rules.yml` and repair malformed corner
   quotes.

The output directory contains the eight platform files, a deterministic ZIP
archive, and `SHA256SUMS`.

## Standard

The target is the PRC government standard for Traditional Chinese characters,
as encoded by the community-maintained
[`t2gov`](https://github.com/TerryTian-tech/OpenCC-Traditional-Chinese-characters-according-to-Chinese-government-standards)
OpenCC configuration. Every run downloads the newest `t2gov` commit and prints
its SHA, so any build can be traced back to the exact character rules it used.

`rules.yml` holds only this project's own corrections on top of that standard;
it is not a replacement for it.

## Requirements

- Python 3.11 or newer
- The official [OpenCC](https://github.com/BYVoid/OpenCC) `opencc` CLI
- Network access to GitHub, to fetch the latest `t2gov` rules and the Telegram
  translation exports

```console
# macOS
brew install opencc

# Ubuntu
sudo apt-get install opencc
```

## Usage

```console
python -m pip install --editable .
telegram-cngov
```

Options:

```console
telegram-cngov --output dist          # output directory (default: dist)
telegram-cngov --rules rules.yml      # corrections file (default: rules.yml)
telegram-cngov --work-dir .work       # keep intermediate conversions
```

## Rules

`rules.yml` contains only project-specific corrections. Everything OpenCC can
do is left to OpenCC.

- `labels` — whole translation values that name the language pack. Only a value
  that is exactly the label is rewritten, so sentences that mention
  "简体中文" are converted normally.
- `replacements` — ordered literal corrections applied after conversion.
  These cover mainland usage and upstream typos that the government standard
  does not handle.

`rules.yml` is read from the current directory by default; pass `--rules` to
use another file.

## Automation

CI runs the tests. The build workflow runs weekly and can be started manually.
It converts the latest exports and compares the generated `SHA256SUMS` with the
latest release, publishing a `vYYYY.MM.DD` release only when something changed.

## Language tag

`zh-Hant-CN` is an [IANA-registered](https://www.iana.org/assignments/language-subtag-registry)
BCP 47 tag: Chinese in Traditional script, PRC mainland region.

## Licence

[MIT](LICENSE)
