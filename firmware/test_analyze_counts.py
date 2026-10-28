# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for the measurement CSV analyzer (new run-based format)."""

import contextlib
import io
import random
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

    def test_sdk_log_lines_above_the_header_are_skipped(self):
        # A file straight off a board: the SDK's own lines come first.
        vals = list(range(1000, 1016))
        plain = make_csv(self.root / "plain.csv", "r1", "c1", "room",
                         {0: vals, 1: vals})
        board = self.root / "board.csv"
        board.write_text(
            "BOOT: Tiny Tapeout SDK\n"
            "ttboard.project_mux: Enable design tt_um_x\n"
            + Path(plain).read_text(encoding="utf-8"), encoding="utf-8")
        g = analyzer.load_files([str(board)])[("c1", "room")]
        self.assertEqual(analyzer.osc_means(g, 0)[15], 1015.0)
        self.assertEqual(len(analyzer.complete_vector(g, 1)), 16)

    def test_a_run_that_stopped_is_refused(self):
        p = make_csv(self.root / "s.csv", "r1", "c1", "room", {0: [1] * 16})
        text = Path(p).read_text(encoding="utf-8")
        Path(p).write_text(text + "# ERROR: version bytes read 0 and 0x00,"
                           " expected 2 and 0x1a\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "the run stopped: version"):
            analyzer.load_files([p])

    def test_arm_idx_range_rejected(self):
        # Arm 2 is Arm C since the three-arm design; 3 selects no oscillator.
        p = make_csv(self.root / "r.csv", "r1", "c1", "room", {3: [100] * 16})
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
        # docs/info.md quotes a 28.5 MHz clock floor at the 2048 window, from
        # the fastest ring on the chip, Arm C ring 10 at 911.1 MHz in the ff
        # corner; sim/verify_datasheet.py re-derives it. The 1.0x boundary has
        # to land on it. (This was 13.55 MHz at a 1000-cycle window, from the
        # two-arm baseline's 888.3, until 23 September.)
        self.assertEqual(analyzer.wrap_risk(50_000_000, 2048)[0], "ok")
        self.assertEqual(analyzer.wrap_risk(40_000_000, 2048)[0], "thin")
        self.assertEqual(analyzer.wrap_risk(29_000_000, 2048)[0], "thin")
        self.assertEqual(analyzer.wrap_risk(28_000_000, 2048)[0], "wrap")
        self.assertEqual(analyzer.wrap_risk(None, 2048)[0], "unknown")
        floor_mhz = analyzer.FASTEST_SIM_MHZ * 2048 / 65536
        self.assertAlmostEqual(floor_mhz, 28.5, places=1)

    def test_a_long_window_wraps_just_as_well_as_a_slow_clock(self):
        # count = f * window / clk, so the window is the other way in.
        self.assertEqual(analyzer.wrap_risk(25_000_000, 1000)[0], "ok")
        self.assertEqual(analyzer.wrap_risk(25_000_000, 2000)[0], "wrap")

    def test_third_arm_is_read(self):
        vals = list(range(2000, 2016))
        p = make_csv(self.root / "c.csv", "r1", "c1", "room",
                     {0: vals, 1: vals, 2: vals}, rounds=2)
        g = analyzer.load_files([p])[("c1", "room")]
        self.assertEqual(analyzer.osc_means(g, 2)[15], 2015.0)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            analyzer.print_summaries({("c1", "room"): g})
        self.assertIn("Arm C (hand-placed): 16/16 osc", out.getvalue())

    def test_first_start_split_by_prediction(self):
        # Slot 0 to slot 1 is the one transition the census says counts,
        # and it comes up twice; the other three changes do not count.
        lines = ["run_id,chip_id,condition,round,order,arm,idx,count,"
                 "overflow,count_first,t_ms"]
        seq = [0, 1, 2, 1, 0, 1]
        predicted = {(0, 1)}
        prev = None
        for k, slot in enumerate(seq):
            count = 1000 + slot
            first = count + (1 if (prev, slot) in predicted else 0)
            lines.append("r1,c1,room,0,%d,0,%d,%d,0,%d,%d"
                         % (k, slot, count, first, k))
            prev = slot
        p = self.root / "f.csv"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        groups = analyzer.load_files([str(p)])
        fs = groups[("c1", "room")]["first_start"]
        self.assertEqual(len(fs), 5)  # the first row has nothing before it
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            analyzer.print_first_start(groups, predicted)
        text = out.getvalue()
        self.assertIn("mean +0.400 over 5", text)
        self.assertIn("predicted to count +1.000 over 2", text)
        self.assertIn("the rest +0.000 over 3", text)


# --------------------------------------------------------------------------
# A selection pin that never reaches the chip. The Tang Nano's first run on
# 19 October lost index bit 0, and the report said nothing about it: bit
# error rates of 0.29 to 0.45 and no reason (docs/phaseG_fpga_bench.md).
# Each fault below names one pin and no other. Added 2026-10-22.
# --------------------------------------------------------------------------

def bench_run(path, read, run_id="r1", rounds=20, tie=None):
    """A three-arm run where read(arm, idx) is the ring a selection really
    measures. Every ring has its own count, 20 apart in a scrambled order,
    plus a count of jitter drawn afresh for every reading, so two selections
    of one ring come out close but not equal. tie makes one ring read like
    another."""
    ring = {(k // 16, k % 16): 20000 + 20 * ((29 * k) % 48)
            for k in range(48)}
    if tie:
        ring[tie[1]] = ring[tie[0]]
    lines = ['# META {"run_id": "%s", "clk_hz_requested": 50000000, '
             '"window": 2048}' % run_id,
             "run_id,chip_id,condition,round,order,arm,idx,count,t_ms"]
    rng = random.Random(20261022)
    t = 0
    for r in range(rounds):
        for k in range(48):
            arm, idx = k // 16, k % 16
            count = ring[read(arm, idx)] + rng.randint(0, 1)
            lines.append("%s,c1,room,%d,%d,%d,%d,%d,%d"
                         % (run_id, r, k, arm, idx, count, t))
            t += 1
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class SelectionPinTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def sel(self, read, **kw):
        p = bench_run(self.root / "run.csv", read, **kw)
        g = analyzer.load_files([p])[("c1", "room")]
        return analyzer.run_selections(g)["r1"]

    def named(self, lost):
        return [(pin, n) for pin, _, _, n in lost]

    def test_a_clean_run_names_no_pin(self):
        pairs = analyzer.pin_pairs(self.sel(lambda a, i: (a, i)))
        self.assertEqual([(p, alike, n) for p, _, alike, n in pairs],
                         [("ui[1]", 0, 16), ("ui[7]", 0, 16),
                          ("ui[2]", 0, 24), ("ui[3]", 0, 24),
                          ("ui[4]", 0, 24), ("ui[5]", 0, 24)])
        self.assertEqual(analyzer.lost_pins(self.sel(lambda a, i: (a, i))), [])

    def test_a_lost_index_bit_is_named(self):
        # ui[2] never arrives and the chip reads it as 0
        lost = analyzer.lost_pins(self.sel(lambda a, i: (a, i & ~1)))
        self.assertEqual(self.named(lost), [("ui[2]", 24)])

    def test_a_pin_held_high_is_named_too(self):
        lost = analyzer.lost_pins(self.sel(lambda a, i: (a, i | 8)))
        self.assertEqual(self.named(lost), [("ui[5]", 24)])

    def test_a_lost_arm_bit_is_named(self):
        # ui[7] never arrives, so Arm C's selections measure Arm A's rings
        lost = analyzer.lost_pins(self.sel(lambda a, i: (a & ~2, i)))
        self.assertEqual(self.named(lost), [("ui[7]", 16)])

    def test_two_rings_alike_by_chance_name_nothing(self):
        sel = self.sel(lambda a, i: (a, i), tie=((0, 0), (0, 1)))
        pairs = {p: (alike, n) for p, _, alike, n in analyzer.pin_pairs(sel)}
        self.assertEqual(pairs["ui[2]"], (1, 24))
        self.assertEqual(analyzer.lost_pins(sel), [])

    def test_too_few_repeats_to_tell(self):
        # three rounds of a run that did lose a pin: not enough to say so
        p = bench_run(self.root / "short.csv", lambda a, i: (a, i & ~1),
                      rounds=3)
        groups = analyzer.load_files([p])
        sel = analyzer.run_selections(groups[("c1", "room")])["r1"]
        self.assertEqual(analyzer.lost_pins(sel), [])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            analyzer.print_selection_pins(groups)
        self.assertIn("too few pairs to tell", out.getvalue())

    def test_each_run_is_judged_on_its_own(self):
        good = bench_run(self.root / "good.csv", lambda a, i: (a, i), "r1")
        bad = bench_run(self.root / "bad.csv", lambda a, i: (a, i & ~4), "r2")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = analyzer.main([good, bad])
        self.assertEqual(status, 0)
        text = out.getvalue()
        self.assertIn("c1/room run r1: no pin missing", text)
        self.assertIn("c1/room run r2: PIN ui[4] (index bit 2) DID NOT REACH"
                      " THE CHIP.", text)
        self.assertEqual(text.count("DID NOT REACH THE CHIP"), 1)


# --------------------------------------------------------------------------
# Drift inside a run, the clock sweep and a ring pulled onto the clock, all
# exploratory. Added 2026-10-27 with measure_puf/7, after the physical
# review (docs/phaseG_physical_review.md).
# --------------------------------------------------------------------------

def ramp_run(path, ppm_a_round, rounds=20, run_id="r1"):
    """Three arms in a fresh random order each round, every ring moved up
    together by ppm_a_round each round, steadily, and a fresh fraction of a
    count on every reading, the way jitter dithers the last one. Rings sit
    19 or 29 counts apart in each logical pair, 950 to 1450 ppm."""
    ring = {k: 20000.37 + (29 * k) % 48 for k in range(48)}
    lines = ['# META {"run_id": "%s", "clk_hz_requested": 50000000, '
             '"window": 2048}' % run_id,
             "run_id,chip_id,condition,round,order,arm,idx,count,t_ms"]
    rng = random.Random(20261027)
    j = 0
    for r in range(rounds):
        order = list(range(48))
        rng.shuffle(order)
        for pos, k in enumerate(order):
            scale = 1 + ppm_a_round * 1e-6 * j / 48.0
            count = int(ring[k] * scale + rng.random())
            lines.append("%s,c1,room,%d,%d,%d,%d,%d,%d"
                         % (run_id, r, pos, k // 16, k % 16, count, 10 * j))
            j += 1
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class DriftTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def run_of(self, ppm_a_round):
        p = ramp_run(self.root / ("d%d.csv" % ppm_a_round), ppm_a_round)
        series = analyzer.load_files([p])[("c1", "room")]["series"]["r1"]
        d = analyzer.common_mode([(a, i, c) for _, a, i, c, _ in series])
        span = 1e6 * (analyzer.percentile(d, 0.95)
                      - analyzer.percentile(d, 0.05))
        return series, d, span

    def test_a_planted_drift_is_measured(self):
        # 1500 ppm a round over 960 readings is 29969 ppm from first to
        # last. Against each ring's median, taken mid run, the 5th to 95th
        # percentile is 0.9 of that over 1.015, about 26570.
        _, _, span = self.run_of(1500)
        self.assertGreater(span, 26000)
        self.assertLess(span, 27100)

    def test_no_drift_measures_none(self):
        series, d, span = self.run_of(0)
        self.assertLess(span, 60)
        before = analyzer.repeat_ppm(analyzer.run_view(series)["raw"])
        after = analyzer.repeat_ppm(analyzer.run_view(series, d)["raw"])
        self.assertLess(abs(before - after), 5)

    def test_dividing_it_out_takes_back_the_noise_and_the_bit_errors(self):
        # At 1500 ppm a round two rings read 30 or more places apart in a
        # round can swap when they sit 19 counts apart, so some bits flip
        # as read. With the common mode divided out, none should.
        series, d, _ = self.run_of(1500)
        before, after = analyzer.run_view(series), analyzer.run_view(series, d)
        self.assertGreater(analyzer.repeat_ppm(before["raw"]), 8000)
        self.assertLess(analyzer.repeat_ppm(after["raw"]), 60)

        def errors(view):
            return sum(analyzer.bit_reliability(view, arm,
                                                analyzer.LOGICAL_PAIRS)[0]
                       for arm in (0, 1, 2))
        self.assertGreater(errors(before), 0)
        self.assertEqual(errors(after), 0)

    def test_the_report_says_what_it_is(self):
        p = ramp_run(self.root / "r.csv", 1500)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(analyzer.main([p]), 0)
        text = out.getvalue()
        self.assertIn("== Drift inside a run (exploratory, not preregistered;"
                      " the sections above use the counts as read)", text)
        self.assertRegex(text, r"c1/room run r1: common mode spans 26\d\d\d"
                               r" ppm \(5th to 95th percentile\) over 20"
                               r" rounds, 9\.6 s\n")
        self.assertIn("no clock sweep in this run", text)

    def test_too_few_rounds_say_so(self):
        p = ramp_run(self.root / "s.csv", 1500, rounds=3)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            analyzer.print_drift(analyzer.load_files([p]),
                                 [("logical-pair", analyzer.LOGICAL_PAIRS)])
        self.assertIn("3 round(s), too few to tell drift from noise",
                      out.getvalue())


class ClockTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_on_a_multiple_of_the_window(self):
        # n windows, or one short, which is how a locked ring that started
        # mid period reads; a half or a quarter window for the window
        # timer's low bits, the coarsest that fits. A count of 1 is not one
        # of anything.
        self.assertEqual(analyzer.on_multiple([22528] * 5, 2048), (11, 2048))
        self.assertEqual(analyzer.on_multiple([22527] * 5, 2048), (11, 2048))
        self.assertEqual(analyzer.on_multiple([23552] * 5, 2048), (23, 1024))
        self.assertEqual(analyzer.on_multiple([23041] * 5, 2048), (45, 512))
        self.assertIsNone(analyzer.on_multiple([22530] * 5, 2048))
        self.assertIsNone(analyzer.on_multiple([1] * 5, 2048))
        self.assertIsNone(analyzer.on_multiple([22528] * 5, None))

    def test_a_ring_that_locks_now_and_then_piles_up_on_the_multiple(self):
        # 60 readings spread with an SD of about 10 counts around 23030,
        # 45 x 512 = 23040 inside the spread, and then 12 of them pinned
        # there, the way a ring the supply carries in and out of lock would
        # read. The median does not move onto the multiple; the pile does.
        rng = random.Random(3)
        free = [int(round(rng.gauss(23030, 10))) for _ in range(60)]
        self.assertIsNone(analyzer.pile_up(free, 2048))
        pinned = free[:48] + [23040] * 12
        self.assertIsNone(analyzer.on_multiple(pinned, 2048))
        n, step, k, expected = analyzer.pile_up(pinned, 2048)
        self.assertEqual((n, step), (45, 512))
        self.assertGreaterEqual(k, 12)
        self.assertLess(expected, 7)
        # A ring that hardly moves is left to the median.
        self.assertIsNone(analyzer.pile_up([23040] * 30 + [23041] * 30,
                                           2048))

    def test_the_sweep_names_a_pulled_ring_whatever_shift_they_share(self):
        # Every ring has run 300 ppm faster by the time of the sweep, the
        # supply moved, and B05 sat locked at 11 x 50 MHz in the main
        # rounds, 120 ppm under where it runs free.
        rng = random.Random(1)
        hz = {(k // 16, k % 16): 470e6 + 1.6e6 * ((29 * k) % 48)
              for k in range(48)}
        hz[(1, 5)] = 550e6 * (1 + 120e-6)

        def counts(f, clk, n):
            return [int(f * 2048 / clk + rng.random()) for _ in range(n)]
        main = {k: [11 * 2048] * 60 if k == (1, 5) else counts(f, 50e6, 60)
                for k, f in hz.items()}
        later = {k: counts(f * (1 + 300e-6), 48e6, 10) for k, f in hz.items()}
        off, shared, spread = analyzer.sweep_offsets(main, later,
                                                     50_000_000, 48_000_000)
        self.assertAlmostEqual(shared, 300, delta=15)
        limit = max(analyzer.PULL_FLOOR_PPM, analyzer.PULL_SIGMA * spread)
        self.assertEqual([k for k, v in off.items() if abs(v) > limit],
                         [(1, 5)])
        self.assertAlmostEqual(off[(1, 5)], 120, delta=25)
        # Too few rings with two readings or more: nothing to say.
        self.assertIsNone(analyzer.sweep_offsets(
            {k: main[k] for k in list(main)[:7]}, later, 50e6, 48e6))

    def test_sweep_rows_stay_out_of_everything_else(self):
        # Rounds 4 and 5 at 48 MHz and 6 and 7 at the main clock again,
        # both after the four main rounds: all four are the sweep's.
        meta = ('# META {"run_id": "r1", "clk_hz_requested": 50000000,'
                ' "clk_hz_sdk": 50000000, "window": 2048, "rounds": 4,'
                ' "sweep_rounds": 2, "clk_sweep_hz": [48000000, 50000000]}')
        lines = [meta, "run_id,chip_id,condition,round,order,arm,idx,count,"
                       "overflow,count_first,t_ms,clk_hz,t_rp_c"]
        for r in range(8):
            clk = 48000000 if r in (4, 5) else 50000000
            for k in range(48):
                c = 20000 + k if r < 4 else 30000 + k
                lines.append("r1,c1,room,%d,%d,%d,%d,%d,0,%d,%d,%d,%s"
                             % (r, k, k // 16, k % 16, c, c, 48 * r + k, clk,
                                "31.5" if r < 4 else "33.0"))
        p = self.root / "s.csv"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        g = analyzer.load_files([str(p)])[("c1", "room")]
        self.assertEqual(len(g["by_round"]), 4)
        self.assertEqual(analyzer.osc_means(g, 2)[15], 20047.0)
        self.assertEqual(len(g["first_start"]), 4 * 48 - 1)
        self.assertEqual(sorted(g["sweep"]["r1"]), [48000000, 50000000])
        self.assertEqual(g["sweep"]["r1"][50000000][(0, 0)],
                         [(30000, 0), (30000, 0)])
        self.assertEqual(set(g["t_rp"]["r1"]), {31.5})

    def test_a_file_from_before_version_7_has_no_sweep(self):
        p = make_csv(self.root / "old.csv", "r1", "c1", "room",
                     {0: [20000 + i for i in range(16)]})
        g = analyzer.load_files([p])[("c1", "room")]
        self.assertEqual(g["sweep"], {})
        self.assertEqual(len(g["by_round"]), 4)
        self.assertEqual(g["t_rp"], {})


if __name__ == "__main__":
    unittest.main()
