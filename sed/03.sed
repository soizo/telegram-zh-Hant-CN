# Step 3 — Fixups for OpenCC s2t misparses.
# Applied in-place after `opencc -c s2t`, before t2gov sees the file.
# One sed rule per line. Blank lines and lines starting with `#` are ignored.
# Used via: sed -i '' -f sed/03.sed <file>

# --- s2t misparses ---
s/天后/天後/g
s/撤消/撤銷/g
s/撒銷/撤銷/g
s/帳號/賬號/g
s/才/纔/g
s/回覆/回復/g
s/迴/回/g
s/佣/傭/g
s/夥伴/伙伴/g
s/錶情/表情/g
s/隻能/衹能/g
s/只/衹/g
s/座標/坐標/g
s/云/雲/g

# --- gesture verbs: 劃 -> 划 ---
# Noun form 下劃綫 is restored later in 04.sed (the 綫 form only exists after
# t2gov has converted 線->綫; 03.sed runs before t2gov so it sees 下划線 here).
s/左劃/左划/g
s/右劃/右划/g
s/上劃/上划/g
s/下劃/下划/g

# --- simplified 线 leaked through s2t -> 綫 ---
s/线/綫/g
