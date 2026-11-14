import random
import unittest

from core.projection_story import EVENTS, _eligible, resolve_event, select_event, state_of
from core.player import PlayerDoc
from core import zhutian


class ProjectionStoryTests(unittest.TestCase):
    def test_choice_persists_relation_flag_material_and_followup(self):
        zt = zhutian.system_of(PlayerDoc(uid="projection", ext={}))
        first = next(e for e in EVENTS["魔卡少女樱"] if e["id"] == "sakura_mirror_start")
        state_of(zt, "魔卡少女樱")
        ok, result, followup = resolve_event(zt, first["id"], 1)
        self.assertTrue(ok)
        state = state_of(zt, "魔卡少女樱")
        self.assertEqual(2, state["relations"]["木之本樱"])
        self.assertIn("识破镜牌", state["flags"])
        self.assertEqual(2, zt["materials"]["镜尘"])
        self.assertEqual("sakura_mirror_end", state["pending"])
        self.assertEqual("sakura_mirror_end", followup["id"])
        self.assertIn("真实出口", result)

    def test_followup_eligibility_uses_any_flag_and_completion_is_stateful(self):
        zt = zhutian.system_of(PlayerDoc(uid="projection", ext={}))
        state = state_of(zt, "魔卡少女樱")
        state["pending"] = "sakura_mirror_end"
        state["flags"].append("识破镜牌")
        pending = select_event(zt, "魔卡少女樱", random.Random(1))
        self.assertEqual("sakura_mirror_end", pending["id"])
        ok, _, next_event = resolve_event(zt, pending["id"], 2)
        self.assertTrue(ok)
        self.assertIsNone(next_event)
        state = state_of(zt, "魔卡少女樱")
        self.assertIn("镜界锚点", state["flags"])
        self.assertEqual("", state["pending"])

    def test_projection_begin_stores_event_menu(self):
        doc = PlayerDoc(uid="projection", ext={"zhutian": {"bound": True, "tier": 1, "energy": 2}})
        ok, text, zt, projection = zhutian.begin_projection(doc, "魔卡少女樱", 1234.0)
        self.assertTrue(ok)
        self.assertEqual(2, zt["energy"])
        self.assertTrue(projection["event_id"])
        self.assertEqual(projection["max_choice"], len(projection["options"]))
        self.assertIn(projection["title"], text)

    def test_catalog_covers_all_original_world_events(self):
        self.assertEqual(30, sum(len(events) for events in EVENTS.values()))
        self.assertEqual(10, len(EVENTS["魔卡少女樱"]))
        self.assertEqual(10, len(EVENTS["魔法少女小圆"]))
        self.assertEqual(10, len(EVENTS["假面骑士帝骑"]))

    def test_relation_gates_and_stat_paths_are_applied(self):
        zt = zhutian.system_of(PlayerDoc(uid="projection", ext={}))
        state = state_of(zt, "魔卡少女樱")
        event = next(e for e in EVENTS["魔卡少女樱"] if e["id"] == "sakura_tomoyo_album")
        self.assertFalse(_eligible(event, state))
        state["relations"]["大道寺知世"] = 2
        self.assertTrue(_eligible(event, state))

        ok, _, _ = resolve_event(zt, "madoka_tea_start", 2)
        self.assertTrue(ok)
        self.assertEqual(3, zt["story_stats"]["希望系统"]["希望碎片"])

    def test_resolution_id_prevents_duplicate_rewards(self):
        zt = zhutian.system_of(PlayerDoc(uid="projection", ext={}))
        for _ in range(2):
            ok, _, _ = resolve_event(zt, "sakura_mirror_start", 1, "same-choice")
            self.assertTrue(ok)
        state = state_of(zt, "魔卡少女樱")
        self.assertEqual(2, state["relations"]["木之本樱"])
        self.assertEqual(1, state["count"])
        self.assertEqual(2, zt["materials"]["镜尘"])


if __name__ == "__main__":
    unittest.main()
