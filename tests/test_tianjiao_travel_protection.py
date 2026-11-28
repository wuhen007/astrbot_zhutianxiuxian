import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import story_npc, tianjiao
from core.player import PlayerDoc


class _SequenceRng:
    def __init__(self, *values):
        self.values = iter(values)

    def random(self):
        return next(self.values)


class _ZeroRng:
    def random(self):
        return 0.0


class TianjiaoTravelProtectionTests(unittest.TestCase):
    def test_legacy_npc_protector_starts_one_24_hour_intervention_cooldown(self):
        doc = PlayerDoc(uid="traveler", ext={"legacy_source": {
            "大帝庇护": 1, "护道人": "柳神",
        }})
        state = story_npc.state_of(doc)

        protector = story_npc.begin_travel_protector(doc, state, 100.0)

        self.assertEqual(protector["name"], "柳神")
        self.assertEqual(state["protector_cd"], 100.0 + story_npc.PROTECTOR_CD)
        self.assertEqual(state["protector_uses"], 1)
        self.assertIsNone(story_npc.begin_travel_protector(doc, state, 101.0))

    def test_legacy_millisecond_cooldown_blocks_travel_intervention(self):
        doc = PlayerDoc(uid="traveler", ext={"legacy_source": {
            "大帝庇护": 1, "护道人": "狠人大帝",
            "护道人下次出手时间": 1_700_000_300_000,
        }})
        state = story_npc.state_of(doc)

        self.assertIsNone(story_npc.begin_travel_protector(doc, state, 1_700_000_000.0))

    def test_independent_escape_uses_a_random_chance_and_a_separate_roll(self):
        escaped = tianjiao.roll_independent_escape(_SequenceRng(0.75, 0.74))
        stayed = tianjiao.roll_independent_escape(_SequenceRng(0.75, 0.75))

        self.assertEqual(escaped, (0.75, 0.74, True))
        self.assertEqual(stayed, (0.75, 0.75, False))

    def test_refusing_travel_offer_consumes_it_once(self):
        doc = PlayerDoc(uid="traveler", ext={"tianjiao_offer": {
            "name": "天骄甲", "source": "travel_ambush", "until": 200.0,
            "normal": [], "extras": [],
        }})

        offer = tianjiao.take_travel_ambush_offer(doc, "天骄甲", 100.0)

        self.assertEqual(offer["source"], "travel_ambush")
        self.assertNotIn("tianjiao_offer", doc.ext)
        self.assertIsNone(tianjiao.take_travel_ambush_offer(doc, "天骄甲", 100.0))

    def test_evil_player_can_reject_travel_offer_into_execution_window(self):
        doc = PlayerDoc(uid="evil", ext={"modao": 1000, "tianjiao_offer": {
            "name": "天骄乙", "source": "travel_ambush", "until": 200.0,
        }})

        ok, message = tianjiao.reject_offer(doc, "天骄乙", 100.0)

        self.assertTrue(ok)
        self.assertIn("5 分钟", message)
        self.assertEqual(doc.ext["tianjiao_exec"]["name"], "天骄乙")

    def test_runtime_profile_restores_original_template_and_advances_rebirth_metadata(self):
        source = {
            "name": "天骄丙", "realm": 20, "atk": 100, "defense": 80, "hp": 60,
            "攻击": 100, "防御": 80, "当前血量": 60, "血量上限": 60,
            "轮回世数": 3, "踪迹代数": 4, "轮回称号": "旧称号",
            "初始模板": {"攻击": 75, "防御": 65, "当前血量": 50,
                         "血量上限": 50, "realm": 10, "atk": 75, "defense": 65, "hp": 50},
            "攻击加成": 0.5, "吞噬本源次数": 2,
        }
        world = {"bosses": {}}
        boss = tianjiao.boss_of(world, "天骄丙")
        runtime = tianjiao.runtime_row(source, boss)
        runtime["攻击"] = 999
        runtime["atk"] = 999
        boss["profile"] = runtime
        boss["轮回世数"] = 3
        boss["踪迹代数"] = 4
        boss["轮回称号"] = "旧称号"

        tianjiao.on_kill(boss, "killer", 123.0, source_row=source,
                         rng=_SequenceRng(0.0, 0.0))
        reborn = tianjiao.runtime_row(source, boss)

        self.assertEqual(reborn["攻击"], 75)
        self.assertEqual(reborn["atk"], 75)
        self.assertEqual(reborn["轮回世数"], 4)
        self.assertEqual(reborn["踪迹代数"], 5)
        self.assertEqual(reborn["轮回称号"], "紫微转世身")
        self.assertNotIn("攻击加成", reborn)
        self.assertNotIn("吞噬本源次数", reborn)
        self.assertEqual(source["攻击"], 100)

    def test_refeed_returns_half_to_worn_source_and_consumes_imitation_card(self):
        imitation = {
            "仿制名": "仿·星河剑", "来源装备名": "星河剑", "槽位": "武器",
            "词条": {"atk": 0.06, "def": 0.03},
        }
        item_card = tianjiao.imitation_item_card(imitation, "owner")
        doc = PlayerDoc(uid="owner", ext={
            "equipment": {"武器": "星河剑"},
            "tianjiao_private_equipment": {"仿·星河剑": item_card},
        })
        inventory = {"仿·星河剑": 1}
        base = {"name": "星河剑", "class": "装备", "type": "武器",
                "归一属性": {"百分比": {"atk": 0.1}}}

        ok, message, result = tianjiao.refeed_imitation(
            doc, "星河剑", inventory, lambda _name: base)

        self.assertTrue(ok)
        self.assertIn("atk +0.0300", message)
        self.assertEqual(result["item"]["归一属性"]["百分比"], {"atk": 0.13, "def": 0.015})
        self.assertNotIn("仿·星河剑", doc.ext["tianjiao_private_equipment"])
        self.assertEqual(inventory["仿·星河剑"], 1)

    def test_refeed_requires_source_to_be_worn_and_preserves_imitation_on_failure(self):
        imitation = {
            "仿制名": "仿·星河剑", "来源装备名": "星河剑", "槽位": "武器",
            "词条": {"atk": 0.06},
        }
        doc = PlayerDoc(uid="owner", ext={
            "equipment": {"护具": "铜甲"},
            "tianjiao_private_equipment": {
                "仿·星河剑": tianjiao.imitation_item_card(imitation, "owner"),
            },
        })

        ok, message, _ = tianjiao.refeed_imitation(
            doc, "星河剑", {"仿·星河剑": 1}, lambda _name: {"name": "星河剑"})

        self.assertFalse(ok)
        self.assertIn("先穿戴", message)
        self.assertIn("仿·星河剑", doc.ext["tianjiao_private_equipment"])

    def test_tianjiao_copies_sixty_percent_of_equipped_percent_stats_once_daily(self):
        doc = PlayerDoc(uid="wearer", name="仿制来源", ext={
            "equipment": {"武器": "星河剑"},
        })
        boss = {"profile": {}}
        item = {"归一属性": {"百分比": {"atk": 0.1, "def": 0.05, "HP": 0.2}}}
        imitation = tianjiao.try_create_imitation(
            doc, boss, "天骄己", lambda _name: item, 100.0, _ZeroRng())

        self.assertEqual(imitation["词条"], {"atk": 0.06, "def": 0.03, "HP": 0.12})
        self.assertEqual(boss["profile"]["参悟仿制"], imitation)
        self.assertIsNone(tianjiao.try_create_imitation(
            doc, boss, "天骄己", lambda _name: item, 101.0, _ZeroRng()))
        card = tianjiao.imitation_item_card(imitation, doc.uid)
        self.assertEqual(card["绑定者"], "wearer")
        self.assertEqual(card["atk"], 0.06)

    def test_contribution_rewards_use_original_rank_counts_and_killer_bonus(self):
        rewards = tianjiao.roll_contribution_rewards({
            "contrib": {"killer": 100, "support": 80},
        }, {"掉落物": [{"name": "战利品", "数量": 1, "概率": 1.0}]},
           "killer", _ZeroRng())

        self.assertEqual(rewards["killer"], {"战利品": 4})
        self.assertEqual(rewards["support"], {"战利品": 2})

    def test_independent_tianjiao_reborn_with_original_starter_equipment(self):
        world = {"bosses": {}}
        source = {"name": "天骄丁", "位面": 2.5, "攻击": 100, "装备": {
            "武器": {"name": "旧武器"}, "帝兵": {"name": "旧帝兵"},
        }}
        boss = tianjiao.boss_of(world, "天骄丁")
        starter = {
            "武器": {"name": "烂铁匕首"}, "护具": {"name": "破铜护具"},
            "法宝": {"name": "廉价炮仗"}, "帝兵": {"name": "废铁"},
        }

        tianjiao.on_kill(boss, "killer", 123.0, source_row=source,
                         starter_equipment=starter, rng=_SequenceRng(0.0, 0.0))
        reborn = tianjiao.runtime_row(source, boss)

        self.assertTrue(tianjiao.is_independent_tianjiao(source))
        self.assertEqual(reborn["装备"], starter)
        self.assertEqual(source["装备"]["武器"]["name"], "旧武器")

    def test_non_independent_tianjiao_reborn_with_snapshotted_equipment(self):
        world = {"bosses": {}}
        source = {"name": "天骄戊", "位面": 1, "攻击": 100, "装备": {
            "武器": {"name": "本命武器"},
        }}
        boss = tianjiao.boss_of(world, "天骄戊")
        tianjiao.runtime_row(source, boss)
        boss["profile"]["装备"] = {"武器": {"name": "被替换武器"}}

        tianjiao.on_kill(boss, "killer", 123.0, source_row=source,
                         starter_equipment={"武器": {"name": "烂铁匕首"}},
                         rng=_SequenceRng(0.0, 0.0))

        self.assertEqual(boss["profile"]["装备"], source["装备"])

    def test_travel_refusal_rolls_regular_and_special_drops_individually(self):
        drops = tianjiao.roll_travel_rejection_drops({
            "掉落物": [
                {"name": "保底战利品", "数量": 1, "概率": 1.0},
                {"name": "未命中战利品", "数量": 1, "概率": 0.0},
            ],
            "特殊掉落": [{"name": "特殊材料", "最小数量": 2, "最大数量": 3, "概率": 1.0}],
        }, _SequenceRng(0.0, 0.0, 0.0, 0.0, 0.99))

        self.assertEqual(drops, {"保底战利品": 1, "特殊材料": 3})


if __name__ == "__main__":
    unittest.main()
