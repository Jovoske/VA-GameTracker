"""Insights payload regression without database or ML dependencies.

Execute the actual summary and time-window functions against known visit counts.
These tests check the summary contract, not SQL integration.
"""
import ast
import unittest
from pathlib import Path

FORECASTING = Path(__file__).parents[1] / "app" / "forecasting"


def load_function(filename, name, namespace):
    source = FORECASTING / filename
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    )
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, str(source), "exec"), namespace)


def rows(camera, species_id, name, hours):
    """Visit rows (camera, species id, species name, hour, visits)."""
    return [(camera, species_id, name, hour, n) for hour, n in hours]


class InsightsCopyTests(unittest.TestCase):
    def setUp(self):
        from app.i18n import clock, t  # the words come from the catalogs, in English here

        self.namespace = {"SITTABLE_HOURS": tuple(range(16, 24)) + (0, 1), "t": t,
                          "clock": clock}
        load_function("model.py", "_best_window", self.namespace)
        load_function("insights.py", "_clock", self.namespace)
        load_function("insights.py", "_summaries", self.namespace)
        self.summaries = self.namespace["_summaries"]

    def test_summaries_describe_recordings_and_include_morning_peak(self):
        visits = (
            rows("River", "wild_boar", "Wild boar", [(5, 10), (6, 20), (7, 25)])
            + rows("Wood", "wild_boar", "Wild boar", [(7, 5)])
            + rows("Wood", "red_deer", "Red deer", [(19, 15), (20, 15)])
            + rows("Hill", "red_deer", "Red deer", [(21, 10)])
        )
        summaries = self.summaries(visits)

        self.assertEqual(
            [row["kind"] for row in summaries], ["time", "time", "time", "location"]
        )
        self.assertIn("between 05:00 and 08:00", summaries[0]["statement"])
        # The share stays in `strength` for the folded numbers, not in the sentence
        # a hunter reads first.
        self.assertEqual(summaries[0]["strength"], 0.6)
        self.assertIn("wild boar", summaries[1]["statement"])
        self.assertIn("between 05:00 and 08:00", summaries[1]["statement"])
        self.assertIn("between 19:00 and 22:00", summaries[2]["statement"])
        self.assertEqual([row["sample"] for row in summaries], [100, 60, 40, 100])
        # Three cameras, and the third sees under half what the second does.
        self.assertEqual(summaries[3]["statement"],
                         "Most of the action is at River and Wood. The other cameras see far less.")
        for row in summaries:
            self.assertIn("camera", row["statement"])
            self.assertNotIn("%", row["statement"])
            self.assertNotIn("—", row["statement"])
            self.assertNotIn("most active", row["statement"])
            self.assertNotIn("moon", row["statement"].lower())

    def test_midnight_reads_as_a_word_and_split_cameras_stay_plain(self):
        visits = (
            rows("River", "wild_boar", "Wild boar", [(21, 10), (22, 10), (23, 10)])
            + rows("Wood", "wild_boar", "Wild boar", [(0, 5), (21, 10)])
            + rows("Hill", "wild_boar", "Wild boar", [(9, 35), (22, 10), (23, 10)])
        )
        summaries = self.summaries(visits)

        self.assertIn("between 21:00 and midnight", summaries[0]["statement"])
        # 55 / 30 / 15: the third camera sees half the second, not "far less".
        self.assertEqual(summaries[2]["statement"], "Hill and River are your busiest cameras.")

    def test_two_cameras_are_never_the_other_cameras(self):
        """G-24: with two cameras the top two always hold everything."""
        visits = (rows("Track", "wild_boar", "Wild boar", [(22, 90)])
                  + rows("Wallow", "wild_boar", "Wild boar", [(22, 10)]))
        location = [s for s in self.summaries(visits) if s["kind"] == "location"][0]
        self.assertEqual(location["statement"], "Track and Wallow are your busiest cameras.")

    def test_near_equal_cameras_are_not_far_apart(self):
        visits = [(cam, "wild_boar", "Wild boar", 22, n)
                  for cam, n in (("A", 30), ("B", 25), ("C", 25), ("D", 20))]
        location = [s for s in self.summaries(visits) if s["kind"] == "location"][0]
        self.assertEqual(location["statement"], "A and B are your busiest cameras.")

    def test_small_sample_has_no_summary(self):
        self.assertEqual(self.summaries(rows("River", "wild_boar", "Wild boar", [(22, 19)])), [])

    def test_an_unnamed_animal_counts_but_is_never_a_species(self):
        visits = (rows("River", None, None, [(22, 50)])
                  + rows("River", "wild_boar", "Wild boar", [(21, 20)]))
        summaries = self.summaries(visits)
        self.assertEqual(summaries[0]["sample"], 70)
        self.assertEqual([s["sample"] for s in summaries if s["kind"] == "time"][1:], [20])


if __name__ == "__main__":
    unittest.main()
