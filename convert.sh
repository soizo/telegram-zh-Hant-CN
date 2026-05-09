#!/bin/bash
set -euo pipefail

# Telegram zh-Hans -> zh-Hant-CN conversion pipeline
# ---------------------------------------------------
# 1) Download zh-Hans translation exports from translations.telegram.org
# 2) Replace language labels (simplified text) with zh-Hant-CN equivalents
# 3) OpenCC s2t: Simplified -> Standard Traditional
# 4) OpenCC t2gov: Standard Traditional -> PRC-standard glyphs
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
FROM_STEP=1

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
    for cmd in opencc curl git sed; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        echo "FATAL: missing dependencies: ${missing[*]}" >&2
        echo "  brew install opencc curl git" >&2
        exit 1
    fi
}

# -- step 0: prepare t2gov config ---------------------------------------------
setup_t2gov() {
    echo "[setup] t2gov dictionary"
    if [ -d "$T2GOV_DIR" ]; then
        git -C "$T2GOV_DIR" pull --quiet
    else
        git clone --quiet --depth 1 "$T2GOV_REPO" "$T2GOV_DIR"
    fi
    [ -f "$T2GOV_DIR/t2gov/t2gov.json" ] || { echo "FATAL: t2gov/t2gov.json not found" >&2; exit 1; }
}

# -- label-replacement (on simplified source) ---------------------------------
# Done BEFORE s2t so that OpenCC converts our replacement text to traditional.
label_one() {
    local src="$1" dst="$2"
    sed \
        -e 's/简体中文/繁体中文(大陆)/g' \
        -e 's/中文(简体)/繁体中文(大陆)/g' \
        -e 's/Chinese (Simplified)/Traditional Chinese (Mainland)/g' \
        -e 's/Chinese(Simplified)/Traditional Chinese (Mainland)/g' \
        -e 's/zh_hans/zh_hant_cn/g' \
        -e 's/zh-hans/zh-Hant-CN/g' \
        "$src" > "$dst"
}

# -- steps 1+2: download + label-replace, pipelined per platform ---------------
# All platforms run in parallel; each one moves to label-replace as soon as
# its download finishes, so slow downloads don't block fast ones.
download_and_label_one() {
    local name="$1" url="$2" filename="$3"
    local src="$DOWNLOAD_DIR/$filename"
    local dst="$LABELLED_DIR/$filename"
    # curl retries transient errors (timeout, DNS, 5xx, connection refused)
    # with exponential backoff. --retry-all-errors also covers HTTP 4xx, which
    # translations.telegram.org occasionally throws under load.
    local attempt
    for attempt in 1 2 3; do
        if curl -fsSL \
                --retry 5 --retry-delay 2 --retry-connrefused --retry-all-errors \
                --connect-timeout 15 --max-time 180 \
                -o "$src" "$url"; then
            local size; size=$(wc -c < "$src" | tr -d ' ')
            label_one "$src" "$dst"
            printf "  %-12s ok (%sB)%s\n" "$name" "$size" \
                "$([ "$attempt" -gt 1 ] && echo " [after ${attempt} tries]")"
            return 0
        fi
        printf "  %-12s download attempt %d failed, retrying...\n" "$name" "$attempt"
        sleep $((attempt * 3))
    done
    printf "  %-12s FAILED after 3 outer retries\n" "$name"
    return 0
}

download_and_label_parallel() {
    mkdir -p "$DOWNLOAD_DIR" "$LABELLED_DIR"
    echo "[step 1+2] downloading + replacing labels (parallel)"
    for entry in "${PLATFORMS[@]}"; do
        IFS='|' read -r name url filename <<< "$entry"
        download_and_label_one "$name" "$url" "$filename" &
    done
    wait
}

# Used in --local mode only (no downloads to overlap with).
replace_labels() {
    mkdir -p "$LABELLED_DIR"
    echo "[step 2] replacing language labels"
    for entry in "${PLATFORMS[@]}"; do
        IFS='|' read -r name url filename <<< "$entry"
        local src="$DOWNLOAD_DIR/$filename"
        local dst="$LABELLED_DIR/$filename"
        [ -f "$src" ] || { printf "  %-12s skipped (no source)\n" "$name"; continue; }
        label_one "$src" "$dst"
        printf "  %-12s done\n" "$name"
    done
}

# -- step 3: opencc s2t (Simplified -> Standard Traditional) ------------------
# OpenCC's mmseg segmenter is tuned for its own dictionary; pre-segmenting with
# jieba+\x1e was found to disrupt phrase matches (e.g. 「不至於」 → 「不至于」 was
# being split apart, leaving 「於」 unconverted).
# After s2t, sed/03.sed patches misparses (天后→天後, 隻能→衹能, 线→綫…) before
# t2gov sees the file.
convert_s2t() {
    mkdir -p "$S2T_DIR"
    echo "[step 3] OpenCC s2t"
    for entry in "${PLATFORMS[@]}"; do
        IFS='|' read -r name url filename <<< "$entry"
        local src="$LABELLED_DIR/$filename"
        local dst="$S2T_DIR/$filename"
        [ -f "$src" ] || { printf "  %-12s skipped\n" "$name"; continue; }
        opencc -c s2t -i "$src" -o "$dst"
        printf "  %-12s done\n" "$name"
    done
}

# -- step 4: opencc t2gov (Standard Traditional -> PRC-standard glyphs) -------
# After t2gov, sed/04.sed patches glyph errors (裏→里 in names, 複→復, residual
# 於→于 fallback for cases OpenCC's phrase rules can't reach).
convert_t2gov() {
    mkdir -p "$OUTPUT_DIR"
    echo "[step 4] OpenCC t2gov"
    local cfg="$T2GOV_DIR/t2gov/t2gov.json"
    for entry in "${PLATFORMS[@]}"; do
        IFS='|' read -r name url filename <<< "$entry"
        local src="$S2T_DIR/$filename"
        local dst="$OUTPUT_DIR/$filename"
        [ -f "$src" ] || { printf "  %-12s skipped\n" "$name"; continue; }
        opencc -c "$cfg" -i "$src" -o "$dst"
        printf "  %-12s done\n" "$name"
    done
}

# -- usage / args --------------------------------------------------------------
usage() {
    cat >&2 <<EOF
usage: $0 [--from N] [--local]

  --from N    start from step N (1-5), reusing prior outputs on disk:
                1 = download zh-Hans sources + label-replace (default)
                2 = label-replace only (sources must exist in 01-source-zh-Hans/)
                3 = OpenCC s2t (input: 02-labels-replaced/)
                4 = OpenCC t2gov (input: 03-s2t-standard-Hant/)
                5 = general polish (in-place on 04-output-zh-Hant-CN/)
  --local     alias for --from 2 (skip download)
  -h, --help  show this help
EOF
    exit 1
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --from)
                shift
                [[ "${1:-}" =~ ^[1-5]$ ]] || { echo "--from requires a step number 1-5 (got: ${1:-<empty>})" >&2; usage; }
                FROM_STEP="$1"; shift
                ;;
            --local) FROM_STEP=2; shift ;;
            -h|--help) usage ;;
            *) echo "unknown option: $1" >&2; usage ;;
        esac
    done
}

# Pre-flight: when starting mid-pipeline, the previous step's output dir must
# already exist (otherwise the step has nothing to read).
require_dir() {
    local dir="$1" hint="$2"
    [ -d "$dir" ] || { echo "FATAL: $dir does not exist — $hint" >&2; exit 1; }
}

# -- step 5: general polish ----------------------------------------------------
# Rules live in sed/05.sed (typographic / cross-step conventions, e.g. full-width
# punctuation -> half-width).
# Convention: sed/NN.sed, where NN matches the step number that applies it.
# Each step reads its own NN.sed; to add new rule files, drop them into sed/.
batch_fixes() {
    echo "[step 5] general polish"
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
            "$f"
        printf "  %-12s done\n" "$name"
    done
}

# -- main ----------------------------------------------------------------------
main() {
    parse_args "$@"
    echo "telegram zh-Hans -> zh-Hant-CN conversion"
    echo "==========================================="
    [ "$FROM_STEP" -gt 1 ] && echo "(starting from step $FROM_STEP)"
    check_deps
    # t2gov repo only needed for step 4; skip its clone/pull if starting later.
    [ "$FROM_STEP" -le 4 ] && setup_t2gov

    if [ "$FROM_STEP" -le 1 ]; then
        download_and_label_parallel
    elif [ "$FROM_STEP" -eq 2 ]; then
        require_dir "$DOWNLOAD_DIR" "run with --from 1 first to download sources"
        replace_labels
    fi
    if [ "$FROM_STEP" -le 3 ]; then
        require_dir "$LABELLED_DIR" "run with --from 2 (or earlier) first"
        convert_s2t
    fi
    if [ "$FROM_STEP" -le 4 ]; then
        require_dir "$S2T_DIR" "run with --from 3 (or earlier) first"
        convert_t2gov
    fi
    if [ "$FROM_STEP" -le 5 ]; then
        require_dir "$OUTPUT_DIR" "run with --from 4 (or earlier) first"
        batch_fixes
    fi

    echo "==========================================="
    echo "done. output in $OUTPUT_DIR/"
    ls -lh "$OUTPUT_DIR/" 2>/dev/null || echo "  (empty)"
}

main "$@"
