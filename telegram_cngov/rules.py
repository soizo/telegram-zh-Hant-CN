"""Ordered literal corrections for each conversion stage."""

import re

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
)

# A single closing quote between ASCII letters is an English apostrophe, not a
# Chinese quotation mark (e.g. "don't", "Monday's").
CLOSING_SINGLE_QUOTE = re.compile(r"(?<![A-Za-z])’|’(?![A-Za-z])")

OPENING_QUOTES = {"「": "」", "『": "』"}
CLOSING_QUOTES = {close: open_ for open_, close in OPENING_QUOTES.items()}


# Entries that name other languages, not this language pack.
FOREIGN_LANGUAGE_KEY = re.compile(
    r'^\s*(?:<string\s+name="?|")('
    r"Language\.[a-z]{2,3}(?:-[A-Za-z]{2,4})?"
    r'|Translate\.Language[."]'
    r'|Translation\.Language[."]'
    r"|TranslateLanguage"
    r")"
)


def apply_rules(text: str, rules: Rules) -> str:
    for old, new in rules:
        text = text.replace(old, new)
    return text


def apply_label_rules(text: str) -> str:
    """Rename this pack without relabelling the languages it points at."""
    return "".join(
        line if FOREIGN_LANGUAGE_KEY.match(line) else apply_rules(line, LABEL_RULES)
        for line in text.splitlines(keepends=True)
    )


def _normalize_line(line: str) -> str:
    output: list[str] = []
    stack: list[str] = []
    for index, char in enumerate(line):
        if char in OPENING_QUOTES:
            if stack and stack[-1] == char:
                output.append(OPENING_QUOTES[char])
                stack.pop()
            else:
                output.append(char)
                stack.append(char)
        elif char in CLOSING_QUOTES:
            opening = CLOSING_QUOTES[char]
            if stack and stack[-1] == opening:
                output.append(char)
                stack.pop()
            elif any(quote in (opening, char) for quote in line[index + 1 :]):
                output.append(opening)
                stack.append(opening)
            else:
                output.append(char)
        else:
            output.append(char)
    return "".join(output)


def normalize_corner_quotes(text: str) -> str:
    """Pair corner quotes whose opening and closing marks are reversed."""
    return "".join(_normalize_line(line) for line in text.splitlines(keepends=True))


def apply_polish_rules(text: str) -> str:
    text = apply_rules(text, POLISH_RULES)
    text = CLOSING_SINGLE_QUOTE.sub("』", text)
    return normalize_corner_quotes(text)
