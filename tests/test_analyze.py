import contextlib
import io
import json
import os.path
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree


ANALYZER = Path(__file__).resolve().parents[1] / "skills" / "session-context-analysis" / "analyze.py"


def snapshot(step, tokens, size, rules=0):
    return {
        "timestamp": f"2026-11-24T11:00:{step:02}Z",
        "current_context_tokens": tokens,
        "current_context_bytes": size,
        "per_source_context_bytes": {"rules": rules},
    }


def analyze(events, **extra):
    with tempfile.TemporaryDirectory() as directory:
        cache = Path(directory)
        (cache / "session-context-test.json").write_text(json.dumps({"events": events, **extra}))
        stdout = io.StringIO()
        with (
            patch.object(os.path, "expanduser", return_value=directory),
            patch.object(sys, "argv", [str(ANALYZER), "test"]),
            contextlib.redirect_stdout(stdout),
        ):
            runpy.run_path(str(ANALYZER), run_name="__main__")
        html = (cache / "session-context-test.html").read_text()
        svg = ElementTree.fromstring("<svg " + html.split("<svg ", 1)[1].split("</svg>", 1)[0] + "</svg>")
        return stdout.getvalue(), svg


class AnalyzerTest(unittest.TestCase):
    def test_rules_and_remainder_are_shown_as_bytes(self):
        report, svg = analyze([snapshot(1, 20000, 90000), snapshot(2, 21000, 95000, 2713)])
        self.assertIn("| 2 | 2,713 | +2,713 |", report)
        self.assertIn("step 2 -2,750.", report)
        self.assertNotIn("AGENTS.md", report)
        chart_text = "".join(svg.itertext())
        self.assertIn("Other context (e.g. conversation and tool activity): 92,287 bytes (97%)", chart_text)
        self.assertIn("rules (all sources): 2,713 bytes (3%)", chart_text)
        self.assertNotIn("-2,750", chart_text)

    def test_positive_token_estimate_difference_stays_out_of_source_shares(self):
        report, svg = analyze([snapshot(1, 40000, 95000, 2713)])
        self.assertIn("step 1 +16,250.", report)
        chart_text = "".join(svg.itertext())
        self.assertIn("Other context (e.g. conversation and tool activity): 92,287 bytes (97%)", chart_text)
        self.assertNotIn("16,250", chart_text)

    def test_flagged_spike_preserves_reading_and_both_deltas(self):
        report, svg = analyze([
            snapshot(1, 20000, 60000),
            snapshot(2, 42000, 61000),
            snapshot(3, 21000, 62000),
        ])
        self.assertIn("| 42,000 | +22,000 |", report)
        self.assertIn("| 21,000 | -21,000 |", report)
        self.assertIn("possible anomalous reading", report)
        self.assertIn("step 2: +22,000 tokens (logged total 42,000)", "".join(svg.itertext()))

    def test_large_net_decline_is_not_classified_as_a_reversion(self):
        report, _ = analyze([
            snapshot(1, 20000, 60000),
            snapshot(2, 42000, 61000),
            snapshot(3, 15000, 61000),
        ])
        self.assertNotIn("anomalous reading", report)
        self.assertIn("tokens fell; bytes stayed flat or grew", report)

    def test_fetched_total_is_separate_from_acu_history(self):
        report, svg = analyze(
            [snapshot(1, 20000, 60000), snapshot(2, 22000, 62000)],
            acu_points=[["2026-11-24T11:00:01Z", 1.0], ["2026-11-24T11:00:02Z", 2.0]],
            acus=1.5,
            fetched_at="2026-11-24T11:00:03Z",
        )
        self.assertIn("| 2.00 | +1.00 |", report)
        self.assertIn("Session ACU total when fetched at 2026-11-24 11:00:03 UTC: 1.50.", report)
        self.assertNotIn("-0.50", report)
        historical_line, = (node for node in svg.findall("{*}polyline") if node.get("stroke") == "#DB2777")
        self.assertEqual(len(historical_line.get("points").split()), 2)
        self.assertIn("1.50 ACUs (session total when fetched)", "".join(svg.find("{*}path").itertext()))

    def test_acu_chart_and_table_without_context_snapshots(self):
        report, svg = analyze(
            [],
            acu_points=[["2026-11-25T06:29:00Z", 1.2], ["2026-11-25T08:35:21Z", 4.78]],
            acus=5.11,
            fetched_at="2026-11-25T08:46:00Z",
        )
        self.assertIn("| 2026-11-25 08:35:21 | 4.78 | +3.58 |", report)
        self.assertNotIn("Logged tokens", report)
        chart_text = "".join(svg.itertext())
        self.assertIn("Context data isn't available for this session", report)
        self.assertIn("Context data isn't available for this session", chart_text)
        self.assertIn("Time (UTC)", chart_text)
        self.assertNotIn("Context bytes by source", chart_text)
        line, = svg.findall("{*}polyline")
        self.assertEqual(line.get("stroke"), "#DB2777")
        self.assertEqual(len(line.get("points").split()), 2)
        self.assertIn("5.11 ACUs (session total when fetched)", "".join(svg.find("{*}path").itertext()))

    def test_acu_total_without_readings_or_fetch_timestamp(self):
        report, svg = analyze([], acus=0)
        self.assertIn("Session ACU total when fetched: 0.00.", report)
        self.assertIn("Fetch time unavailable", "".join(svg.itertext()))
        self.assertIn("0.00 ACUs (session total when fetched)", "".join(svg.find("{*}path").itertext()))
        self.assertIsNone(svg.find("{*}polyline"))

    def test_readings_only_prints_full_table_without_context_snapshots(self):
        report, svg = analyze([], acu_points=[
            [f"2026-11-25T06:29:{second:02}Z", second] for second in range(21)
        ])
        self.assertIn("| 2026-11-25 06:29:20 | 20.00 | +1.00 |", report)
        self.assertEqual(len(svg.findall("{*}circle")), 21)
        self.assertIsNone(svg.find("{*}path"))

    def test_no_chart_without_context_or_acu_data(self):
        with self.assertRaises(SystemExit) as exit_result:
            analyze([], acu_points=[], acus=None)
        self.assertIsNone(exit_result.exception.code)


if __name__ == "__main__":
    unittest.main()
