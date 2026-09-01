"""Ordered literal corrections for each conversion stage."""

Rule = tuple[str, str]
Rules = tuple[Rule, ...]

LABEL_RULES: Rules = (
    ("简体中文", "繁体中文(大陆)"),
    ("中文(简体)", "繁体中文(大陆)"),
    ("Chinese (Simplified)", "Traditional Chinese (Mainland)"),
    ("Chinese(Simplified)", "Traditional Chinese (Mainland)"),
    ("zh_hans", "zh_hant_cn"),
    ("zh-hans", "zh-Hant-CN"),
)

S2T_RULES: Rules = (
    ("天后", "天後"),
    ("撤消", "撤銷"),
    ("撒銷", "撤銷"),
    ("帳號", "賬號"),
    ("才", "纔"),
    ("回覆", "回復"),
    ("迴", "回"),
    ("佣", "傭"),
    ("夥伴", "伙伴"),
    ("錶情", "表情"),
    ("隻能", "衹能"),
    ("只", "衹"),
    ("座標", "坐標"),
    ("云", "雲"),
    # Gesture verbs use 划; underline nouns are restored after t2gov.
    ("左劃", "左划"),
    ("右劃", "右划"),
    ("上劃", "上划"),
    ("下劃", "下划"),
    ("线", "綫"),
)

T2GOV_RULES: Rules = (
    ("下划綫", "下劃綫"),
    ("加布裏埃拉", "加布里埃拉"),
    ("哈裏斯", "哈里斯"),
    ("奧裏亞", "奧里亞"),
    ("弗裏斯蘭", "弗里斯蘭"),
    ("斯瓦希裏", "斯瓦希里"),
    ("克裏奧爾", "克里奧爾"),
    ("索馬裏", "索馬里"),
    ("公裏", "公里"),
    ("英裏", "英里"),
    ("複", "復"),
    ("並", "并"),
    # Mainland convention; Telegram UI does not contain the rare name cases.
    ("於", "于"),
)

POLISH_RULES: Rules = (
    ("（", "("),
    ("）", ")"),
    ("“", "「"),
    ("”", "」"),
    ("‘", "『"),
    ("’", "』"),
)


def apply_rules(text: str, rules: Rules) -> str:
    for old, new in rules:
        text = text.replace(old, new)
    return text
