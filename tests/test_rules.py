import unittest

from telegram_cngov.rules import (  # pyright: ignore[reportMissingImports]
    LABEL_RULES,
    POLISH_RULES,
    S2T_RULES,
    T2GOV_RULES,
    apply_rules,
)


class RuleTests(unittest.TestCase):
    def test_each_literal_rule_replaces_its_source(self) -> None:
        for rules in (LABEL_RULES, S2T_RULES, T2GOV_RULES, POLISH_RULES):
            for old, new in rules:
                with self.subTest(old=old, new=new):
                    self.assertEqual(apply_rules(old, ((old, new),)), new)

    def test_cross_stage_underline_and_gesture_rules(self) -> None:
        gesture = apply_rules("向下劃", S2T_RULES)
        underline = apply_rules("下划綫", T2GOV_RULES)
        self.assertEqual(gesture, "向下划")
        self.assertEqual(underline, "下劃綫")

    def test_language_labels_are_rewritten_before_conversion(self) -> None:
        self.assertEqual(
            apply_rules("简体中文 zh_hans zh-hans", LABEL_RULES),
            "繁体中文(大陆) zh_hant_cn zh-Hant-CN",
        )


if __name__ == "__main__":
    unittest.main()
