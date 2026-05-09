# Step 2 — Replace zh-Hans language labels with zh-Hant-CN equivalents.
# Applied to simplified-Chinese source BEFORE OpenCC s2t, so the replacement
# text gets traditionalised in the same pass.

# --- display names: 简体中文 -> 繁体中文(大陆) ---
# (s2t will yield 繁體中文(大陸) downstream)
s/简体中文/繁体中文(大陆)/g
s/中文(简体)/繁体中文(大陆)/g
s/Chinese (Simplified)/Traditional Chinese (Mainland)/g
s/Chinese(Simplified)/Traditional Chinese (Mainland)/g

# --- language tags ---
# zh_hans  -> zh_hant_cn   (Telegram underscore-lowercase convention)
# zh-hans  -> zh-Hant-CN   (BCP 47 canonical form, IANA registered 2005-04-26)
s/zh_hans/zh_hant_cn/g
s/zh-hans/zh-Hant-CN/g
