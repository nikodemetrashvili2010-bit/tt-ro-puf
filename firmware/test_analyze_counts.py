"""Focused regression tests for the measurement CSV analyzer."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import analyze_counts as analyzer


class AnalyzeCountsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write_csv(self, name, rows, metadata=(25_000_000, 1000)):
        path = self.root / name
        lines = []
        if metadata is not None:
            clk, window = metadata
            lines.append(
                "# tt_ro_puf measurement, label=fixture "
                f"clk={clk} window={window} repeats=1"
            )
        lines.append("label,arm,idx,sample,count")
        lines.extend(
            f"{label},{arm},{idx},{sample},{count}"
            for sample, (label, arm, idx, count) in enumerate(rows)
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    @staticmethod
    def vector_rows(label, arm, values):
        return [(label, arm, idx, count) for idx, count in enumerate(values)]

    def test_split_label_and_reject_malformed_labels(self):
        self.assertEqual(
            analyzer.split_label(" chip03_room_1v8 "),
            ("chip03", "room_1v8"),
        )
        for label in ("chip03", "_room", "chip03_"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                analyzer.split_label(label)

    def test_load_files_reports_schema_and_range_errors(self):
        bad_schema = self.root / "bad_schema.csv"
        bad_schema.write_text("label,arm,idx\nchip01_room,0,0\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing CSV column.*count"):
            analyzer.load_files([str(bad_schema)])

        bad_range = self.write_csv(
            "bad_range.csv", [("chip01_room", 2, 0, 100)]
        )
        with self.assertRaisesRegex(ValueError, "arm/index out of range"):
            analyzer.load_files([bad_range])

    def test_load_files_groups_samples_and_skips_timeouts(self):
        first = self.write_csv(
            "first.csv",
            [
                ("chip01_room_1v8", 0, 0, 100),
                ("chip01_room_1v8", 0, 0, -1),
            ],
        )
        second = self.write_csv(
            "second.csv",
            [
                ("chip01_room_1v8", 0, 0, 120),
                ("chip01_room_1v8", 1, 1, 200),
                ("chip01_hot_1v8", 0, 0, 90),
            ],
        )

        groups = analyzer.load_files([first, second])
        self.assertEqual(set(groups), {("chip01", "room_1v8"), ("chip01", "hot_1v8")})
        room = groups[("chip01", "room_1v8")]
        self.assertEqual(room["timeouts"], 1)
        self.assertEqual(room["raw"][(0, 0)], [100, 120])
        self.assertEqual(room["raw"][(1, 1)], [200])
        self.assertEqual(room["sources"], {first, second})
        self.assertEqual(room["settings"], {(25_000_000, 1000)})
        self.assertEqual(analyzer.oscillator_means(room, 0), {0: 110.0})

    def test_complete_same_condition_chips_emit_metrics(self):
        ascending = [1000 + idx for idx in range(analyzer.NRO)]
        descending = list(reversed(ascending))
        first_rows = self.vector_rows("chip01_room_1v8", 0, ascending)
        first_rows += self.vector_rows("chip01_room_1v8", 1, [v + 100 for v in ascending])
        second_rows = self.vector_rows("chip02_room_1v8", 0, descending)
        second_rows += self.vector_rows("chip02_room_1v8", 1, [v + 100 for v in descending])
        groups = analyzer.load_files(
            [
                self.write_csv("chip01.csv", first_rows),
                self.write_csv("chip02.csv", second_rows),
            ]
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            analyzer.print_across_chip_metrics(groups)
        text = output.getvalue()
        self.assertIn("Condition: room_1v8", text)
        self.assertEqual(text.count("mean r=-1.000"), 2)
        self.assertEqual(text.count("mean Hamming distance=100.0%"), 2)

    def test_incomplete_vectors_do_not_produce_cross_chip_metrics(self):
        complete = [1000 + idx for idx in range(analyzer.NRO)]
        groups = analyzer.load_files(
            [
                self.write_csv(
                    "complete.csv",
                    self.vector_rows("chip01_room", 0, complete),
                ),
                self.write_csv(
                    "incomplete.csv",
                    self.vector_rows("chip02_room", 0, complete[:-1]),
                ),
            ]
        )

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            analyzer.print_across_chip_metrics(groups)
        text = output.getvalue()
        self.assertIn("need complete measurements from at least two distinct chips", text)
        self.assertNotIn("centred frequency-pattern correlation", text)

    def test_missing_or_mismatched_metadata_blocks_comparison(self):
        vector = [1000 + idx for idx in range(analyzer.NRO)]
        cases = (
            ("missing", None, (25_000_000, 1000)),
            ("mismatched", (25_000_000, 1000), (50_000_000, 1000)),
        )
        for case, first_metadata, second_metadata in cases:
            with self.subTest(case=case):
                groups = analyzer.load_files(
                    [
                        self.write_csv(
                            f"{case}_first.csv",
                            self.vector_rows("chip01_room", 0, vector),
                            first_metadata,
                        ),
                        self.write_csv(
                            f"{case}_second.csv",
                            self.vector_rows("chip02_room", 0, list(reversed(vector))),
                            second_metadata,
                        ),
                    ]
                )
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    analyzer.print_across_chip_metrics(groups)
                self.assertIn(
                    "clock/window metadata missing or inconsistent",
                    output.getvalue(),
                )

    def test_main_returns_status_and_routes_output(self):
        valid = self.write_csv(
            "valid.csv",
            [
                ("chip07_room_1v8", 0, 0, 1234),
                ("chip07_room_1v8", 0, 0, -1),
            ],
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = analyzer.main([valid])
        self.assertEqual(status, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("== chip07 / room_1v8", stdout.getvalue())
        self.assertIn("skipped timeout samples: 1", stdout.getvalue())
        self.assertIn("descriptive metrics", stdout.getvalue())

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = analyzer.main([str(self.root / "missing.csv")])
        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
