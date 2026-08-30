# Step 4 — Fixups for OpenCC t2gov glyph errors.
# Applied in-place after `opencc -c t2gov.json`.
# One sed rule per line. Blank lines and lines starting with `#` are ignored.
# Used via: sed -i '' -f sed/04.sed <file>

# --- restore noun 下劃綫 (gesture verbs were collapsed in 03.sed) ---
# 03.sed turned 下劃 -> 下划 to fix gesture-verb usage; this re-traditionalises
# the underline noun, which only takes the 綫 form after t2gov ran.
s/下划綫/下劃綫/g

# --- t2gov glyph errors: 裏 -> 里 in transliterated names and units ---
s/加布裏埃拉/加布里埃拉/g
s/哈裏斯/哈里斯/g
s/奧裏亞/奧里亞/g
s/弗裏斯蘭/弗里斯蘭/g
s/斯瓦希裏/斯瓦希里/g
s/克裏奧爾/克里奧爾/g
s/索馬裏/索馬里/g
s/公裏/公里/g
s/英裏/英里/g

# --- PRC convention cases t2gov misses ---
s/複/復/g
s/並/并/g

# --- fallback: 於 -> 于 for cases OpenCC's phrase rules can't reach ---
# The mainland standard collapses 於 to 于 universally, but t2gov leaves single
# 於 unconverted when context (placeholders, segmentation) prevents matching a
# TGPhrases entry — e.g. 「計劃於 %1$s 開始」. Apply as a last-resort sweep.
# Trade-off: very rare names like 「於菟」 / surname 「於」 will also be flattened,
# which is fine for Telegram UI strings.
s/於/于/g
