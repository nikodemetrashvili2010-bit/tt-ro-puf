# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for the measurement CSV analyzer (new run-based format)."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import analyze_counts as analyzer


def make_csv(path, run_id, chip, cond, vectors, rounds=4, clk=25_000_000, window=1000):
    """vectors: {arm: [16 counts]}. Emits `rounds` identical rounds plus header."""
    meta = ('# META {"run_id": "%s", "chip_id": "%s", "condition": "%s", '
            '"clk_hz_requested": %d, "window": %d}' % (run_id, chip, cond, clk, window))
    lines = [meta, "run_id,chip_id,condition,round,order,arm,idx,count,t_ms"]
    t = 0
    for r in range(rounds):
        order = 0
        for arm, vals in vectors.items():
            for idx, c in enumerate(vals):
                lines.append("%s,%s,%s,%d,%d,%d,%d,%d,%d"
                             % (run_id, chip, cond, r, order, arm, idx, c, t))
                order += 1
                t += 1
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class AnalyzeCountsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_missing_columns_rejected(self):
        p = self.root / "bad.csv"
        p.write_text("arm,idx,count\n0,0,100\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing CSV column"):
            analyzer.load_files([str(p)])

    def test_arm_idx_range_rejected(self):
        p = make_csv(self.root / "r.csv", "r1", "c1", "room", {2: [100] * 16})
        with self.assertRaisesRegex(ValueError, "arm/idx out of range"):
            analyzer.load_files([p])

    def test_grouping_and_timeouts(self):
        vals = list(range(1000, 1016))
        p = make_csv(self.root / "g.csv", "r1", "c1", "room", {0: vals, 1: vals}, rounds=2)
        # inject one timeout row
        text = Path(p).read_text().rstrip().split("\n")
        text.append("r1,c1,room,9,0,0,0,-1,999")
        Path(p).write_text("\n".join(text) + "\n")
        groups = analyzer.load_files([p])
        g = groups[("c1", "room")]
        self.assertEqual(g["timeouts"], 1)
        self.assertEqual(analyzer.osc_means(g, 0)[0], 1000.0)
        self.assertEqual(len(analyzer.complete_vector(g, 0)), 16)

    def test_duplicate_file_rejected(self):
        p = make_csv(self.root / "d.csv", "r1", "c1", "room", {0: [1] * 16, 1: [1] * 16})
        with self.assertRaisesRegex(ValueError, "identical file passed more than once"):
            analyzer.load_files([p, p])

    def test_duplicate_run_id_rejected(self):
        a = make_csv(self.root / "a.csv", "same", "c1", "room", {0: [1] * 16, 1: [1] * 16})
        b = make_csv(self.root / "b.csv", "same", "c2", "room", {0: [2] * 16, 1: [2] * 16})
        with self.assertRaisesRegex(ValueError, "duplicate run_id"):
            analyzer.load_files([a, b])

    def test_across_chips_correlation_and_bootstrap(self):
        asc = list(range(1000, 1016))
        b = [v + 100 for v in asc]
        groups = analyzer.load_files([
            make_csv(self.root / "c1.csv", "r1", "c1", "room", {0: asc, 1: b}),
            make_csv(self.root / "c2.csv", "r2", "c2", "room", {0: list(reversed(asc)), 1: b}),
        ])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            analyzer.print_across_chips(groups, [("logical-pair", analyzer.LOGICAL_PAIRS)])
        text = out.getvalue()
        self.assertIn("Condition: room", text)
        self.assertIn("bootstrap 95% by chip", text)
        # Opposite Arm A patterns -> strongly negative correlation.
        self.assertIn("r=-1.000", text)

    def test_incompatible_settings_block_comparison(self):
        asc = list(range(1000, 1016))
        groups = analyzer.load_files([
            make_csv(self.root / "w1.csv", "r1", "c1", "room", {0: asc}, window=1000),
            make_csv(self.root / "w2.csv", "r2", "c2", "room", {0: asc}, window=500),
        ])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            analyzer.print_across_chips(groups, [("logical-pair", analyzer.LOGICAL_PAIRS)])
        self.assertIn("incompatible acquisition settings", out.getvalue())

    def test_main_status_codes(self):
        good = make_csv(self.root / "ok.csv", "r1", "c7", "room", {0: [5] * 16, 1: [5] * 16})
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            status = analyzer.main([good])
        self.assertEqual(status, 0)
        self.assertIn("== c7 / room", so.getvalue())
        self.assertIn("Descriptive metrics only", so.getvalue())

        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
            status = analyzer.main([str(self.root / "missing.csv")])
        self.assertEqual(status, 2)
        self.assertIn("error:", se.getvalue())


class NewStatisticsTests(unittest.TestCase):
    def test_centered_removes_offset(self):
        v = [100.0, 110.0, 90.0]
        c = analyzer.centered(v)
        self.assertAlmostEqual(sum(c), 0.0)
        # a chip 2x faster gives the same centered pattern
        c2 = analyzer.centered([200.0, 220.0, 180.0])
        for a, b in zip(c, c2):
            self.assertAlmostEqual(a, b)

    def test_loco_scores_shared_pattern(self):
        pat = list(range(16))
        vectors = {"c1": [500 + 3 * x for x in pat],
                   "c2": [520 + 3 * x + 0.1 for x in pat],
                   "c3": [480 + 3 * x - 0.1 for x in pat]}
        scores = analyzer.loco_scores(vectors)
        self.assertEqual(set(scores), {"c1", "c2", "c3"})
        for s in scores.values():
            self.assertGreater(s, 0.99)

    def test_paired_delta_ci_positive_when_a_repeats(self):
        a = {"c1": 0.9, "c2": 0.95, "c3": 0.92, "c4": 0.88}
        b = {"c1": 0.1, "c2": -0.05, "c3": 0.02, "c4": 0.15}
        d, lo, hi, n = analyzer.paired_delta_ci(a, b)
        self.assertEqual(n, 4)
        self.assertGreater(d, 0.7)
        self.assertGreater(lo, 0.0)

    def test_holdout_ber_needs_enough_rounds(self):
        g = {"by_round": {("r", 0): {}, ("r", 1): {}}, "raw": {}}
        ber, fragile, nb = analyzer.bit_reliability(g, 0, analyzer.LOGICAL_PAIRS)
        self.assertIsNone(ber)


# --------------------------------------------------------------------------
# The four faults below were all found by reading rather than by failing, and
# every one of them loses a volunteer's data without saying anything. They are
# survivable in my own runs, where I know what I did, and not in someone
# else's. Fixed 2026-08-11.
# --------------------------------------------------------------------------

class VolunteerDataFaultTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _rows(self, run_id="r1", chip="c1", cond="room"):
        head = "run_id,chip_id,condition,round,order,arm,idx,count,t_ms"
        body = ["%s,%s,%s,0,%d,%d,%d,%d,%d"
                % (run_id, chip, cond, i, a, i % 16, 20000 + i, i)
                for a in (0, 1) for i in range(16)]
        return [head] + body

    def test_broken_meta_is_an_error_not_a_shrug(self):
        # An unescaped quote in NOTES used to produce exactly this line, and
        # parse_meta answered it with None, identical to a file with no header.
        p = self.root / "broken.csv"
        bad = '# META {"run_id": "r1", "notes": "ran it at 22"C"}'
        p.write_text("\n".join([bad] + self._rows()) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            analyzer.load_files([str(p)])

    def test_absent_meta_is_still_allowed(self):
        p = self.root / "nometa.csv"
        p.write_text("\n".join(self._rows()) + "\n", encoding="utf-8")
        groups = analyzer.load_files([str(p)])          # must not raise
        self.assertEqual(len(groups), 1)

    def test_two_concatenated_runs_are_rejected(self):
        # What a helpful volunteer does when asked for "your data".
        p = self.root / "cat.csv"
        m1 = '# META {"run_id": "r1", "clk_hz_requested": 25000000, "window": 1000}'
        m2 = '# META {"run_id": "r2", "clk_hz_requested": 10000000, "window": 1000}'
        p.write_text("\n".join([m1] + self._rows("r1") + [m2] + self._rows("r2")) + "\n",
                     encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "2 META lines"):
            analyzer.load_files([str(p)])

    def test_disagreeing_measured_values_are_kept_not_overwritten(self):
        # Two runs, one die, one nominal label, 9 degrees apart. dict.update
        # kept whichever was read last and the disagreement left no trace.
        def one(name, run_id, temp):
            p = self.root / name
            meta = ('# META {"run_id": "%s", "clk_hz_requested": 25000000, '
                    '"window": 1000, "temp_c_measured": %s}' % (run_id, temp))
            p.write_text("\n".join([meta] + self._rows(run_id)) + "\n", encoding="utf-8")
            return str(p)
        groups = analyzer.load_files([one("a.csv", "r1", 22.0), one("b.csv", "r2", 31.0)])
        g = next(iter(groups.values()))
        self.assertEqual(g["measured"]["temp_c_measured"], {22.0, 31.0})
        # and the spread has to fail the compatibility check, not pass it
        self.assertFalse(analyzer.settings_ok([("x", g), ("y", g)]))

    def test_wrap_levels_match_the_documented_floor(self):
        # 13.55 MHz is the floor quoted in measure_puf.py's own header, derived
        # there independently. The 1.0x boundary has to land on it.
        self.assertEqual(analyzer.wrap_risk(25_000_000, 1000)[0], "ok")
        self.assertEqual(analyzer.wrap_risk(20_000_000, 1000)[0], "thin")
        self.assertEqual(analyzer.wrap_risk(13_000_000, 1000)[0], "wrap")
        self.assertEqual(analyzer.wrap_risk(10_000_000, 1000)[0], "wrap")
        self.assertEqual(analyzer.wrap_risk(None, 1000)[0], "unknown")
        floor_mhz = analyzer.FASTEST_SIM_MHZ * 1000 / 65536
        self.assertAlmostEqual(floor_mhz, 13.55, places=2)

    def test_a_long_window_wraps_just_as_well_as_a_slow_clock(self):
        # count = f * window / clk, so the window is the other way in.
        self.assertEqual(analyzer.wrap_risk(25_000_000, 1000)[0], "ok")
        self.assertEqual(analyzer.wrap_risk(25_000_000, 2000)[0], "wrap")


if __name__ == "__main__":
    unittest.main()
