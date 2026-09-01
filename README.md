# Telegram-zh-Hant-CN

**Apply the language pack in Telegram:** [t.me/setlanguage/chinese-traditional-mainland](https://t.me/setlanguage/chinese-traditional-mainland)

Python pipeline for converting Telegram's Simplified Chinese (`zh-Hans`) translation exports into **Traditional Chinese with PRC-standard glyphs** (`zh-Hant-CN`).

## Pipeline

1. Download exports for Android, iOS, Telegram Desktop, macOS, Android X, Web K, Web A, and Unigram.
2. Replace language labels and tags before conversion.
3. Convert Simplified Chinese to standard Traditional Chinese with OpenCC `s2t`.
4. Apply the latest [`t2gov`](https://github.com/TerryTian-tech/OpenCC-Traditional-Chinese-characters-according-to-Chinese-government-standards) rules.
5. Apply project corrections and typography rules.

## Requirements

- Python 3.11 or newer
- Official [OpenCC](https://github.com/BYVoid/OpenCC) CLI

```console
# macOS
brew install opencc

# Ubuntu
sudo apt-get install opencc
```

## Installation

```console
python -m pip install --editable .
```

## Usage

```console
# Full conversion; intermediate stages are deleted automatically
telegram-cngov

# Select the final output directory
telegram-cngov --output dist

# Keep intermediate stages for inspection
telegram-cngov --work-dir .work

# Resume from a retained stage
telegram-cngov --work-dir .work --from 3
```

The final directory contains eight platform files. `--from` accepts stages 1–5 and requires `--work-dir`.

## Development

```console
python -m unittest discover -s tests -v
python -m compileall -q telegram_cngov scripts tests
```

## Automation

CI validates pushes and pull requests. The update workflow runs at 03:00 UTC on calendar days **1, 6, 11, 16, 21, 26, and 31**, and can also be started manually. Month boundaries are therefore not always exactly 120 hours apart.

When the eight generated files differ from the latest published checksums, the workflow creates a date-tagged Release (`vYYYY.MM.DD`) containing:

- all eight translation files;
- a deterministic ZIP archive;
- `SHA256SUMS`.

If the files are unchanged, no tag or Release is created. Generated translations are never committed to `main`.

## Language tag

`zh-Hant-CN` is an [IANA-registered](https://www.iana.org/assignments/lang-tag-apps/zh-Hant-CN) BCP 47 tag (registered 2005-04-26) meaning Chinese written in Traditional script for the PRC mainland region. `Hans` and `Hant` are script subtags; `CN` is the region subtag.

## Licence

[MIT](LICENSE)
