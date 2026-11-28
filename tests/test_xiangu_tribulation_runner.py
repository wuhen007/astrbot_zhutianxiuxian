import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import xiangu, xiangu_dao
from core.player import PlayerDoc


class _AlwaysSuccess:
    def random(self):
        return 0.0


class XianguTribulationRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_wave_callback_is_invoked_and_can_prevent_lethal_damage(self):
        doc = PlayerDoc(uid="xiangu-callback", realm_index=30, exp=500_000,
                        ext={"potential": 50, "hp": 900_000,
                             "hp_max": 900_000, "xueqi": 500_000})
        state = xiangu.state_of(doc)
        state["active"] = True
        state["map"] = xiangu.new_run_map("callback-test")
        state["map"]["fragment_id"] = "flame_abyss"
        state["gains"]["daoyun"] = 600
        calls = []

        def survive(current_doc, raw_damage, wave_no, stage_name, rng):
            calls.append((raw_damage, wave_no, stage_name))
            return {"damage": 0, "hp": current_doc.ext["hp"], "dead": False,
                    "avoided": True, "messages": ["防御已结算"]}

        text, events = await xiangu_dao.tribulation_run(
            doc, state, _AlwaysSuccess(), 1.0, wave_runner=survive)

        self.assertTrue(calls)
        self.assertGreaterEqual(len(events["waves"]), 10)
        self.assertTrue(events["success"], text[-300:])
        self.assertEqual(events["waves"][0]["hp"], 900_000)
        self.assertEqual(state["shenhuo"]["神火品质"], "唯一")


if __name__ == "__main__":
    unittest.main()
