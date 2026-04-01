# telegram-zh-Hant-CN

Bash pipeline for converting Telegram's Simplified Chinese (zh-Hans) translation files into **Traditional Chinese with PRC-standard glyphs** (zh-Hant-CN).

## What it does

1. **Download** — fetches zh-Hans translation exports for all Telegram platforms (Android, iOS, tdesktop, macOS, Android X, Web-K, Web-A, Unigram, Emoji) from `translations.telegram.org`.
2. **Label replacement** — rewrites language identifiers (`简体中文` -> `繁体中文(大陆)`, `zh_hans` -> `zh_hant_cn`, etc.) while still in simplified text so that OpenCC converts them correctly.
3. **OpenCC s2t** — Simplified to Standard Traditional, phrase-preserving.
4. **t2gov** — Standard Traditional to PRC-standard Traditional glyphs, using [OpenCC-Traditional-Chinese-characters-according-to-Chinese-government-standards](https://github.com/TerryTian-tech/OpenCC-Traditional-Chinese-characters-according-to-Chinese-government-standards).
5. **Batch fixes** — corrects known OpenCC misparses and t2gov errata (see comments in `convert.sh` for the full list).

## Language tag

`zh-Hant-CN` is an [IANA-registered](https://www.iana.org/assignments/lang-tag-apps/zh-Hant-CN) BCP 47 tag (registered 2005-04-26) meaning *PRC Mainland Chinese written in Traditional script*. `Hans`/`Hant` are **script** subtags, not region codes; `CN` is the region subtag.

## Dependencies

- [OpenCC](https://github.com/BYVoid/OpenCC) (`brew install opencc`)
- `curl`, `git`, `sed`

## Usage

```sh
# full run: download + convert
./convert.sh

# skip download, use existing files in 01-source-zh-Hans/
./convert.sh --local
```

Output lands in `04-output-zh-Hant-CN/`.

## Licence

[Apache-2.0](LICENCE)
