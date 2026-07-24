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


if __name__ == "__main__":
    unittest.main()
