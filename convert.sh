#!/bin/bash
set -euo pipefail

# Telegram zh-Hans -> zh-Hant-CN conversion pipeline
# ---------------------------------------------------
# 1) Download zh-Hans translation exports from translations.telegram.org
# 2) Replace language labels (simplified text) with zh-Hant-CN equivalents
# 3) jieba segmentation + OpenCC s2t: Simplified -> Standard Traditional
# 4) jieba segmentation + t2gov: Standard Traditional -> PRC-standard glyphs
#
# Language tag reference (BCP 47 / IANA):
#   zh-Hans    = Chinese, Simplified script (script subtag, NOT region)
#   zh-Hant    = Chinese, Traditional script
#   zh-Hant-CN = Chinese, Traditional script, PRC region
#                (IANA registered 2005-04-26 by Mark Davis)
#   Telegram internally uses underscore-lowercase: zh_hans, zh_hant_cn

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOWNLOAD_DIR="$SCRIPT_DIR/01-source-zh-Hans"
LABELLED_DIR="$SCRIPT_DIR/02-labels-replaced"
S2T_DIR="$SCRIPT_DIR/03-s2t-standard-Hant"
OUTPUT_DIR="$SCRIPT_DIR/04-output-zh-Hant-CN"
T2GOV_REPO="https://github.com/TerryTian-tech/OpenCC-Traditional-Chinese-characters-according-to-Chinese-government-standards.git"
T2GOV_DIR="$SCRIPT_DIR/.opencc-t2gov"
JIEBA_SCRIPT="$SCRIPT_DIR/jieba_segment.py"
JIEBA_DIR="$T2GOV_DIR/jieba"
SKIP_DOWNLOAD=false

# platform|url|filename
PLATFORMS=(
    "android|https://translations.telegram.org/zh-hans/android/export|android.xml"
    "ios|https://translations.telegram.org/zh-hans/ios/export|ios.strings"
    "tdesktop|https://translations.telegram.org/zh-hans/tdesktop/export|tdesktop.strings"
    "macos|https://translations.telegram.org/zh-hans/macos/export|macos.strings"
    "android_x|https://translations.telegram.org/zh-hans/android_x/export|android_x.xml"
    "webk|https://translations.telegram.org/zh-hans/webk/export|webk.strings"
    "weba|https://translations.telegram.org/zh-hans/weba/export|weba.strings"
    "unigram|https://translations.telegram.org/zh-hans/unigram/export|unigram.xml"
    "emoji|https://translations.telegram.org/zh-hans/emoji/export|emoji.strings"
)

# -- dependency check ----------------------------------------------------------
check_deps() {
    local missing=()
    for cmd in opencc curl git sed python3; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        echo "FATAL: missing dependencies: ${missing[*]}" >&2
        echo "  brew install opencc curl git python3" >&2
        exit 1
    fi
    if ! python3 -c "import jieba" 2>/dev/null; then
        echo "FATAL: jieba Python package not installed" >&2
        echo "  pip3 install jieba" >&2
        exit 1
    fi
}

# -- step 0: prepare t2gov config ---------------------------------------------
setup_t2gov() {
    echo "[setup] t2gov dictionary + jieba"
    if [ -d "$T2GOV_DIR" ]; then
        git -C "$T2GOV_DIR" pull --quiet
    else
        git clone --quiet --depth 1 "$T2GOV_REPO" "$T2GOV_DIR"
    fi
    [ -f "$T2GOV_DIR/t2gov/t2gov.json" ] || { echo "FATAL: t2gov/t2gov.json not found" >&2; exit 1; }
    [ -d "$JIEBA_DIR" ] || { echo "FATAL: jieba dictionary directory not found" >&2; exit 1; }
}

# -- step 1: download ---------------------------------------------------------
download_files() {
    mkdir -p "$DOWNLOAD_DIR"
    echo "[step 1] downloading zh-Hans exports"
    for entry in "${PLATFORMS[@]}"; do
        IFS='|' read -r name url filename <<< "$entry"
        echo "  $name -> $filename"
        if curl -fL --progress-bar -o "$DOWNLOAD_DIR/$filename" "$url"; then
            printf "  %-12s ok (%sB)\n" "$name" "$(wc -c < "$DOWNLOAD_DIR/$filename" | tr -d ' ')"
        else
            printf "  %-12s FAILED (skipped)\n" "$name"
        fi
    done
}

# -- step 2: replace language labels (on simplified source) --------------------
# Done BEFORE s2t so that OpenCC converts our replacement text to traditional.
#   简体中文             -> 繁体中文(大陆)     (s2t will yield 繁體中文(大陸))
#   Chinese (Simplified) -> Traditional Chinese (Mainland)
#   zh_hans              -> zh_hant_cn       (Telegram underscore convention)
#   zh-hans              -> zh-Hant-CN       (BCP 47 canonical form)
replace_labels() {
    mkdir -p "$LABELLED_DIR"
    echo "[step 2] replacing language labels"
    for entry in "${PLATFORMS[@]}"; do
        IFS='|' read -r name url filename <<< "$entry"
        local src="$DOWNLOAD_DIR/$filename"
        local dst="$LABELLED_DIR/$filename"
        [ -f "$src" ] || { printf "  %-12s skipped (no source)\n" "$name"; continue; }
        sed \
            -e 's/简体中文/繁体中文(大陆)/g' \
            -e 's/中文(简体)/繁体中文(大陆)/g' \
            -e 's/Chinese (Simplified)/Traditional Chinese (Mainland)/g' \
            -e 's/Chinese(Simplified)/Traditional Chinese (Mainland)/g' \
            -e 's/zh_hans/zh_hant_cn/g' \
            -e 's/zh-hans/zh-Hant-CN/g' \
            "$src" > "$dst"
        printf "  %-12s done\n" "$name"
    done
}

# -- step 3: jieba + opencc s2t -----------------------------------------------
convert_s2t() {
    mkdir -p "$S2T_DIR"
    echo "[step 3] jieba segmentation + OpenCC s2t"
    local seg_dir
    seg_dir=$(mktemp -d)
    python3 "$JIEBA_SCRIPT" "$LABELLED_DIR" "$seg_dir" \
        --dict "$JIEBA_DIR/dict_ancient_chinese.txt" \
        --userdict "$JIEBA_DIR/userdict.txt"
    for entry in "${PLATFORMS[@]}"; do
        IFS='|' read -r name url filename <<< "$entry"
        local src="$seg_dir/$filename"
        local dst="$S2T_DIR/$filename"
        [ -f "$src" ] || { printf "  %-12s skipped\n" "$name"; continue; }
        opencc -c s2t -i "$src" -o "$dst"
        # Remove jieba segment markers (\036 = \x1e = RS)
        LC_ALL=C tr -d '\036' < "$dst" > "$dst.tmp" && mv "$dst.tmp" "$dst"
        printf "  %-12s done\n" "$name"
    done
    rm -rf "$seg_dir"
}

# -- step 4: jieba + t2gov ----------------------------------------------------
convert_t2gov() {
    mkdir -p "$OUTPUT_DIR"
    echo "[step 4] jieba segmentation + t2gov"
    local cfg="$T2GOV_DIR/t2gov/t2gov.json"
    local seg_dir
    seg_dir=$(mktemp -d)
    python3 "$JIEBA_SCRIPT" "$S2T_DIR" "$seg_dir" \
        --dict "$JIEBA_DIR/dict_ancient_chinese_traditional.txt" \
        --userdict "$JIEBA_DIR/userdict_traditional.txt"
    for entry in "${PLATFORMS[@]}"; do
        IFS='|' read -r name url filename <<< "$entry"
        local src="$seg_dir/$filename"
        local dst="$OUTPUT_DIR/$filename"
        [ -f "$src" ] || { printf "  %-12s skipped\n" "$name"; continue; }
        opencc -c "$cfg" -i "$src" -o "$dst"
        # Remove jieba segment markers (\036 = \x1e = RS)
        LC_ALL=C tr -d '\036' < "$dst" > "$dst.tmp" && mv "$dst.tmp" "$dst"
        printf "  %-12s done\n" "$name"
    done
    rm -rf "$seg_dir"
}

# -- step 5: batch fixes -------------------------------------------------------
# a) full-width brackets -> half-width; curly quotes -> straight quotes
# b) OpenCC s2t misparses
# c) t2gov glyph errors
batch_fixes() {
    echo "[step 5] batch fixes"
    for entry in "${PLATFORMS[@]}"; do
        IFS='|' read -r name url filename <<< "$entry"
        local f="$OUTPUT_DIR/$filename"
        [ -f "$f" ] || continue
        sed -i '' \
            -e 's/（/(/g' \
            -e 's/）/)/g' \
            -e $'s/\xe2\x80\x9c/\xe3\x80\x8c/g' \
            -e $'s/\xe2\x80\x9d/\xe3\x80\x8d/g' \
            -e $'s/\xe2\x80\x98/\xe3\x80\x8e/g' \
            -e $'s/\xe2\x80\x99/\xe3\x80\x8f/g' \
            -e 's/天后/天後/g' \
            -e 's/撤消/撤銷/g' \
            -e 's/撒銷/撤銷/g' \
            -e 's/帳號/賬號/g' \
            -e 's/才/纔/g' \
            -e 's/回覆/回復/g' \
            -e 's/迴/回/g' \
            -e 's/佣/傭/g' \
            -e 's/夥伴/伙伴/g' \
            -e 's/錶情/表情/g' \
            -e 's/隻能/衹能/g' \
            -e 's/只/衹/g' \
            -e 's/左劃/左划/g' \
            -e 's/右劃/右划/g' \
            -e 's/上劃/上划/g' \
            -e 's/下劃/下划/g' \
            -e 's/下划綫/下劃綫/g' \
            -e 's/座標/坐標/g' \
            -e 's/云/雲/g' \
            -e 's/加布裏埃拉/加布里埃拉/g' \
            -e 's/哈裏斯/哈里斯/g' \
            -e 's/奧裏亞/奧里亞/g' \
            -e 's/弗裏斯蘭/弗里斯蘭/g' \
            -e 's/斯瓦希裏/斯瓦希里/g' \
            -e 's/克裏奧爾/克里奧爾/g' \
            -e 's/索馬裏/索馬里/g' \
            -e 's/公裏/公里/g' \
            -e 's/英裏/英里/g' \
            -e 's/线/綫/g' \
            "$f"
        printf "  %-12s done\n" "$name"
    done
}

# -- usage / args --------------------------------------------------------------
usage() {
    echo "usage: $0 [--local]" >&2
    echo "  --local  skip download, read source files from $DOWNLOAD_DIR" >&2
    exit 1
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --local) SKIP_DOWNLOAD=true; shift ;;
            -h|--help) usage ;;
            *) echo "unknown option: $1" >&2; usage ;;
        esac
    done
}

# -- main ----------------------------------------------------------------------
main() {
    parse_args "$@"
    echo "telegram zh-Hans -> zh-Hant-CN conversion"
    echo "==========================================="
    check_deps
    setup_t2gov
    if [ "$SKIP_DOWNLOAD" = true ]; then
        echo "[step 1] skipped (--local), reading from $DOWNLOAD_DIR"
        [ -d "$DOWNLOAD_DIR" ] || { echo "FATAL: $DOWNLOAD_DIR does not exist" >&2; exit 1; }
    else
        download_files
    fi
    replace_labels
    convert_s2t
    convert_t2gov
    batch_fixes
    echo "==========================================="
    echo "done. output in $OUTPUT_DIR/"
    ls -lh "$OUTPUT_DIR/" 2>/dev/null || echo "  (empty)"
}

main "$@"
