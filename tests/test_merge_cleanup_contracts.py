"""Tests for grand_universe legacy migration and sect_war support/ranking contracts."""

from __future__ import annotations

import ast
import collections
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import grand_universe as gu_mod
from core import sect_war as sw_mod
from core.player import PlayerDoc


class TestMergeCleanupContracts(unittest.TestCase):
    def test_grand_universe_migrates_legacy_state(self) -> None:
        doc = PlayerDoc(
            uid="u_legacy",
            name="古修",
            ext={
                "universe": {
                    "name": "紫霄大宇宙",
                    "ascend_ts": 1234.5,
                    "law": 3,
                    "aura": 640,
                    "open": False,
                    "dungeons": [
                        {"name": "轮回古路", "intro": "试炼", "enemy": "残魂", "cleared": 2},
                    ],
                }
            },
        )
        st = gu_mod.state_of(doc)
        self.assertIsNotNone(st)
        self.assertNotIn("universe", doc.ext)
        self.assertEqual(st["name"], "紫霄大宇宙")
        self.assertEqual(st["level"], 3)
        self.assertEqual(st["aura"], 640)
        self.assertFalse(st["open"])
        self.assertEqual(len(st["dungeons"]), 1)
        self.assertEqual(st["dungeons"][0]["name"], "轮回古路")
        self.assertEqual(st["dungeons"][0]["enemyName"], "残魂")
        self.assertEqual(st["dungeons"][0]["runs"], 2)
        self.assertEqual(gu_mod.law_stage(st["level"])[2], "绝顶仙王")

    def test_sect_war_support_ranking_and_merits(self) -> None:
        war = sw_mod.create("mine", {"name": "摇光圣地"}, {"name": "瑶池圣地"}, timestamp=100.0)
        ok, msg = sw_mod.join(war, "u1", "甲", "attacker")
        self.assertTrue(ok, msg)

        ok, msg, _ = sw_mod.support(war, "u1", 500, 101.0)
        self.assertFalse(ok)
        self.assertIn("1,000", msg)

        for i in range(3):
            ok, msg, res = sw_mod.support(war, "u1", 10_000, 102.0 + i)
            self.assertTrue(ok, msg)
            self.assertGreater(res["contribution"], 0)
            self.assertGreater(res["supplies"], 0)

        ok, msg, _ = sw_mod.support(war, "u1", 10_000, 106.0)
        self.assertFalse(ok)
        self.assertIn("3 批", msg)

        rank_txt = sw_mod.ranking_text(war, my_merits=50)
        self.assertIn("甲", rank_txt)
        self.assertIn("50", rank_txt)

        rewards = sw_mod.settle_rewards(war, 10_000_000)
        self.assertEqual(len(rewards), 1)
        self.assertGreater(rewards[0]["merits"], 0)
        self.assertTrue(rewards[0]["top"])

    def test_main_has_no_duplicate_command_registrations(self) -> None:
        src = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        consts: dict[str, str] = {}
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.startswith("CMD_")
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                consts[node.targets[0].id] = node.value.value
        regs: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "command"
                and node.args
            ):
                a = node.args[0]
                v = a.value if isinstance(a, ast.Constant) else consts.get(a.id, a.id)
                regs.append(str(v))
                for kw in node.keywords:
                    if kw.arg == "alias" and isinstance(kw.value, (ast.Set, ast.Tuple, ast.List)):
                        for el in kw.value.elts:
                            av = el.value if isinstance(el, ast.Constant) else consts.get(el.id, str(el))
                            regs.append(str(av))
        dups = [k for k, c in collections.Counter(regs).items() if c > 1]
        self.assertEqual(dups, [])


if __name__ == "__main__":
    unittest.main()
