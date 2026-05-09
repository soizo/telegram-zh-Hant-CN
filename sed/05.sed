# Step 5 — General / cross-step polish.
# Applied in-place after all conversion steps and their per-step fixups.
# Rules here are not tied to any specific OpenCC step — they're typographic
# / convention choices that apply uniformly to the final output.
# One sed rule per line. Blank lines and lines starting with `#` are ignored.
# Used via: sed -i '' -f sed/05.sed <file>

# --- punctuation: full-width -> half-width, curly -> corner brackets ---
s/（/(/g
s/）/)/g
s/“/「/g
s/”/」/g
s/‘/『/g
s/’/』/g
