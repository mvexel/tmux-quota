from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unittest

from tmux_quota.model import Window
from tmux_quota.render import PALETTES, render
from tmux_quota.source import SourceError, parse, parse_input

NOW = 1_800_000_000.0
FIXTURES = Path(__file__).parent / "fixtures"


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def window(pct=50, elapsed=0.5, duration=604800):
    return Window("W", pct, duration, NOW + duration * (1 - elapsed), NOW)


class PaceTests(unittest.TestCase):
    def test_bands_and_boundaries_for_each_period(self):
        for duration in (18000, 604800):
            for pct, expected in [(0, "green"), (40, "green"), (40.01, "blue"),
                                  (55, "blue"), (55.01, "amber"), (70, "amber"),
                                  (70.01, "red"), (100, "red")]:
                with self.subTest(duration=duration, pct=pct):
                    self.assertEqual(window(pct, duration=duration).pace(NOW), expected)

    def test_grace_floor_and_full_budget(self):
        self.assertEqual(window(1, elapsed=0).pace(NOW), "green")
        self.assertEqual(window(2, elapsed=0).pace(NOW), "blue")
        self.assertEqual(window(100, elapsed=0.999).pace(NOW), "red")

    def test_neutral_for_unreliable_pace(self):
        for w in [replace(window(), observed_at=NOW - 601),
                  replace(window(), observed_at=None),
                  replace(window(), observed_at=NOW + 61),
                  replace(window(), resets_at=None),
                  replace(window(), resets_at=NOW),
                  replace(window(), resets_at=NOW + 700000),
                  replace(window(), last_known=True)]:
            with self.subTest(window=w):
                self.assertEqual(w.pace(NOW), "unknown")

    def test_pace_changes_as_time_passes_without_new_fetch(self):
        w = window(60, elapsed=0.25)
        self.assertEqual(w.pace(NOW), "red")
        self.assertEqual(w.pace(NOW + 604800 / 2, max_age=604800), "green")


class AdapterTests(unittest.TestCase):
    def test_claude_alias_active_age_and_no_invented_5h(self):
        data = {"schemaVersion": 1, "activeAccountNumber": 2, "accounts": [
            {"number": 2, "alias": "personal", "usageStatus": "ok", "usageAgeSeconds": 100,
             "usageFetchedAt": iso(NOW - 20),
             "usage": {"sevenDay": {"pct": 47, "resetsAt": iso(NOW + 300000)}}}
        ]}
        a = parse(data, "claude", NOW)[0]
        self.assertTrue(a.active)
        self.assertEqual(a.label, "personal")
        self.assertEqual([w.label for w in a.windows], ["W"])
        self.assertEqual(a.windows[0].observed_at, NOW - 100)

    def test_claude_last_good_stays_neutral(self):
        data = {"accounts": [{"number": 1, "usage": None,
                "lastGoodAgeSeconds": 30, "lastGoodUsage": {
                    "sevenDay": {"pct": 54, "resetsAt": iso(NOW + 302400)}}}]}
        a = parse(data, "claude", NOW)[0]
        self.assertEqual(a.windows[0].pace(NOW), "unknown")
        self.assertTrue(a.windows[0].available(NOW, 600))
        self.assertIn("~1", render([a], now=NOW, format="plain"))

    def test_codex_raw_usage_schema_and_error(self):
        data = {"provider": "codex", "accounts": [{"number": 1, "active": True,
                "usage": {"weekly": {"pct": 17, "resets_at": iso(NOW + 302400)}}}]}
        a = parse(data, "codex", NOW)[0]
        self.assertEqual(a.windows[0].consumed, 17)
        self.assertEqual(a.windows[0].pace(NOW), "green")
        data["accounts"][0]["error"] = "timeout"
        a = parse(data, "codex", NOW)[0]
        self.assertEqual(a.windows[0].pace(NOW), "unknown")
        self.assertFalse(a.windows[0].available(NOW, 600))

    def test_codex_metadata_list_is_not_mistaken_for_quota(self):
        a = parse({"accounts": [{"number": 1, "label": "Codex Pro"}]}, "codex", NOW)[0]
        self.assertEqual(a.windows, ())
        self.assertIn("Codex ~1 ?", render([a], now=NOW, format="plain"))

    def test_empty_missing_and_unknown_fields(self):
        self.assertEqual(parse({"accounts": [], "future": True}, "claude", NOW), [])
        for data in [[], {}, {"accounts": [None]}, {"schemaVersion": 2, "accounts": []},
                     {"accounts": [], "error": "oops"}]:
            with self.subTest(data=data), self.assertRaises(SourceError):
                parse(data, "claude", NOW)

    def test_bad_percentages_and_missing_freshness(self):
        for pct, expected in [(True, None), (float("nan"), None), ("42", None),
                              (float("inf"), None), (-5, 0), (105, 100)]:
            a = parse({"accounts": [{"number": 1, "usage": {
                "sevenDay": {"pct": pct}}}]}, "claude", NOW)[0]
            self.assertEqual(a.windows[0].consumed, expected)
            self.assertEqual(a.windows[0].pace(NOW), "unknown")

    def test_fixtures_and_provider_selection(self):
        data = json.loads((FIXTURES / "combined.json").read_text())
        rows = parse_input(data, ("claude", "codex"), NOW)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(parse_input(data, ("codex",), NOW)), 1)
        self.assertEqual(len(parse_input(data["codex"], ("codex",), NOW)), 1)


class RendererTests(unittest.TestCase):
    def accounts(self, pct=50):
        return parse({"accounts": [{"number": 1, "active": True, "alias": "work",
                     "usageAgeSeconds": 0, "usage": {"sevenDay": {
                         "pct": pct, "resetsAt": iso(NOW + 302400)}}}]}, "claude", NOW)

    def test_theme_colors_and_equal_plain_content(self):
        for theme in PALETTES:
            for pct, band in [(35, "green"), (50, "blue"), (65, "amber"), (80, "red")]:
                a = self.accounts(pct)
                styled = render(a, now=NOW, theme=theme)
                plain = render(a, now=NOW, format="plain")
                self.assertIn(f"#[fg={PALETTES[theme][band]}] {pct}%", styled)
                self.assertEqual(re.sub(r"#\[[^]]*\]", "", styled), plain)

    def test_zero_full_ascii_and_width(self):
        self.assertIn("------ 0%", render(self.accounts(0), now=NOW, format="plain", ascii_only=True))
        self.assertIn("==== 100%", render(self.accounts(100), now=NOW, format="plain", ascii_only=True, width=4))

    def test_untrusted_labels_cannot_inject_tmux_formats(self):
        text = render(self.accounts(), now=NOW, labels={"claude:1": "#[fg=red]#(touch /tmp/no)\n\x1b"})
        self.assertNotIn("#[fg=red]", text)
        self.assertNotIn("#(", text)
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\n", text)

    def test_unknown_ages_active_filter_and_failed_provider(self):
        a = self.accounts()
        text = render(a, now=NOW + 601, format="plain", scoped_providers=("claude", "codex"))
        self.assertEqual(text, "Claude *~work W ░░░░░░ ? │ Codex ?")
        self.assertEqual(render([replace(a[0], active=False)], now=NOW, active_only=True), "")


if __name__ == "__main__":
    unittest.main()
