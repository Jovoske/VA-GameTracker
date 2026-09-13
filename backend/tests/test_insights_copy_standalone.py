"""Insights payload regression without database or ML dependencies.

Execute the actual summary and time-window functions against known query
results. These tests check the summary contract, not SQL integration.
"""
import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock


FORECASTING = Path(__file__).parents[1] / "app" / "forecasting"


def load_function(filename, name, namespace):
    source = FORECASTING / filename
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    )
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, str(source), "exec"), namespace)


class InsightsCopyTests(unittest.TestCase):
    def setUp(self):
        self.namespace = {
            "Session": object,
            "select": MagicMock(),
            "func": MagicMock(),
            "Detection": MagicMock(),
            "Image": MagicMock(),
            "Species": MagicMock(),
            "Camera": MagicMock(),
            "_local_hour": MagicMock(),
            "SITTABLE_HOURS": tuple(range(16, 24)) + (0, 1),
        }
        load_function("model.py", "_best_window", self.namespace)
        load_function("insights.py", "_correlations", self.namespace)

    def test_summaries_describe_recordings_and_include_morning_peak(self):
        db = MagicMock()
        db.scalar.return_value = 100
        boar_hours = [(5, 10), (6, 20), (7, 30)]
        deer_hours = [(19, 15), (20, 15), (21, 10)]
        query_results = [
            boar_hours + deer_hours,
            [("wild_boar", "Wild boar", 60), ("red_deer", "Red deer", 40)],
            boar_hours,
            deer_hours,
            [("River", 65), ("Wood", 25), ("Hill", 10)],
        ]
        db.execute.side_effect = [MagicMock(all=lambda rows=rows: rows) for rows in query_results]

        summaries = self.namespace["_correlations"](db)

        self.assertEqual(
            [row["kind"] for row in summaries], ["time", "time", "time", "location"]
        )
        self.assertIn("05:00–08:00", summaries[0]["statement"])
        self.assertIn("60% of recorded sightings", summaries[0]["statement"])
        self.assertIn("wild boar", summaries[1]["statement"])
        self.assertIn("05:00–08:00", summaries[1]["statement"])
        self.assertIn("19:00–22:00", summaries[2]["statement"])
        self.assertEqual([row["sample"] for row in summaries], [100, 60, 40, 100])
        self.assertIn("River and Wood recorded 90%", summaries[3]["statement"])
        for row in summaries:
            self.assertIn("camera", row["statement"])
            self.assertNotIn("most active", row["statement"])
            self.assertNotIn("moon", row["statement"].lower())
        # Only the total count is needed: moon analysis must remain in patterns.py.
        db.scalar.assert_called_once()

    def test_small_sample_has_no_summary(self):
        db = MagicMock()
        db.scalar.return_value = 19

        self.assertEqual(self.namespace["_correlations"](db), [])
        db.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
