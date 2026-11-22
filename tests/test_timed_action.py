import unittest
import ast
import time
from pathlib import Path
from types import MethodType, SimpleNamespace

from core import plane, timed_action
from core.player import PlayerDoc


class TimedActionTests(unittest.TestCase):
    def test_equipped_innate_treasure_multiplier_matches_catalogued_clock_rates(self):
        cases = (("混沌钟", 0.7), ("东皇钟", 0.8), ("无", 1.0))
        for treasure, expected in cases:
            with self.subTest(treasure=treasure):
                doc = PlayerDoc(uid=treasure, ext={"xtzb": {
                    "current": "" if treasure == "无" else treasure,
                    "owned": [] if treasure == "无" else [treasure],
                }})
                self.assertEqual(timed_action.multiplier(doc, 1_000), expected)

    def test_elapsed_real_time_converts_to_credited_minutes_at_start_snapshot_rate(self):
        self.assertEqual(timed_action.credited_minutes(1_000, 1_000 + 21 * 60, 0.7), 30)
        self.assertEqual(timed_action.credited_minutes(1_000, 1_000 + 42 * 60, 0.7), 60)
        self.assertEqual(timed_action.credited_minutes(1_000, 1_000 + 21 * 60, 1.0), 21)
        self.assertEqual(timed_action.credited_minutes(1_000, 900, 0.7), 0)

    def test_plane_travel_uses_innate_treasure_multiplier_on_the_quoted_time(self):
        doc = PlayerDoc(uid="plane-clock", realm_index=45, exp=100_000_000,
                        ext={"xueqi": 100_000_000,
                             "xtzb": {"current": "东皇钟", "owned": ["东皇钟"]},
                             "plane": {"current": "凡间", "known": ["凡间", "仙界"]}})
        quoted_minutes = plane.quote(doc, "仙界")["minutes"]

        ok, message = plane.begin_travel(doc, "仙界", {}, 1_000)

        self.assertTrue(ok, message)
        self.assertEqual(plane.state_of(doc)["travel"]["minutes"],
                         max(1, int(quoted_minutes * 0.8 + 0.999999)))

    def test_occupation_timed_action_uses_start_snapshot_multiplier(self):
        plugin_main = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(plugin_main.read_text(encoding="utf-8"))
        wanted = {"_timed_action_start", "_timed_action_end"}
        methods = [node for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name in wanted]
        module = ast.Module(body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *methods,
        ], type_ignores=[])
        env = {"PlayerDoc": PlayerDoc, "timed_action_mod": timed_action,
               "time": time, "math": __import__("math")}
        exec(compile(ast.fix_missing_locations(module), "main.py:timed-action", "exec"), env)
        host = SimpleNamespace()
        for name in wanted:
            setattr(host, name, MethodType(env[name], host))
        doc = PlayerDoc(uid="job-clock", ext={
            "xtzb": {"current": "混沌钟", "owned": ["混沌钟"]}})

        ok, _message, started = host._timed_action_start(doc, "采药中", 30, 15, 48)
        started.state_start = time.time() - 21 * 60
        ok, minutes, settled = host._timed_action_end(started, "采药中", 15, 48)

        self.assertTrue(ok)
        self.assertEqual(minutes, 30)
        self.assertEqual(settled.state, "空闲")


if __name__ == "__main__":
    unittest.main()
