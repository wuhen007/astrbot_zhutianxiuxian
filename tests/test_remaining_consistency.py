import random
import unittest

from core import mingge
import json
from pathlib import Path

from core import (alchemy, equipment, lifespan, occupation, plane_events, secret,
                  duanzao, mingge, yuanshen, zhengdao)
from core.combat import engine, loadout
from core.items import sell
from core.items import use_item
from core.player import PlayerDoc


class SequenceRandom:
    def __init__(self, *values):
        self.values = iter(values)

    def random(self):
        return next(self.values)


class RemainingConsistencyTests(unittest.TestCase):
    def test_alchemy_fate_bonus_changes_success_rate_and_failed_exp(self):
        recipe = {"name": "试验丹", "rate": 0.5, "exp": [100, 10]}
        buckets, exp = alchemy.craft_pills(
            recipe, 0, random.Random(4), 2, success_bonus=-0.5)
        self.assertEqual(buckets, {})
        self.assertEqual(exp, 20)
        buckets, exp = alchemy.craft_pills(
            recipe, 0, random.Random(4), 2, success_bonus=0.5)
        self.assertEqual(sum(buckets.values()), 2)
        self.assertEqual(exp, 200)

    def test_luck_bonus_changes_secret_grade_chances(self):
        self.assertEqual(secret.loot_grade((0.5, 0.5, 0.25), SequenceRandom(0.6)), "none")
        self.assertEqual(
            secret.loot_grade((0.5, 0.5, 0.25), SequenceRandom(0.6, 0.6, 0.0), 0.2),
            "high",
        )

    def test_secret_speed_bonus_can_add_one_floor(self):
        self.assertEqual(secret.exploration_steps(SequenceRandom(0.5), 0.6), 2)
        self.assertEqual(secret.exploration_steps(SequenceRandom(0.8), 0.6), 1)

    def test_unimplemented_inner_open_chance_is_not_drawn_or_claimed(self):
        row = {"name": "空间天赋", "effects": {"内景地开启概率": 0.4}}

        class Content:
            def table(self, _name):
                return [row]

        doc = PlayerDoc(uid="legacy_fate", ext={"mingge": row})
        self.assertEqual(mingge.roll(Content(), random.Random(1)), {})
        self.assertEqual(mingge.effects_of(doc), {})

    def test_fate_costs_and_flat_lifespan_effects_apply(self):
        doc = PlayerDoc(uid="fate_costs", realm_index=0, ext={
            "shouyuan": 100,
            "mingge": {"effects": {
                "心神额外上限": 10, "心神消耗减少": 0.3,
                "修复道伤代价减少": 0.2, "寿元额外": -20,
            }},
        })
        mingge.apply_initial(doc)
        self.assertEqual(yuanshen.heart_max(doc), 40)
        self.assertEqual(yuanshen.heart_cost(doc, 10), 7)
        self.assertLess(zhengdao.repair_cost(doc, 0, 1),
                        zhengdao.repair_cost(PlayerDoc(uid="plain"), 0, 1))
        self.assertEqual(lifespan.grant(doc, 100), 180)

    def test_origin_repair_cost_effect_changes_reshape_price(self):
        doc = PlayerDoc(uid="repair_origin", stones=400_000, ext={
            "mingge": {"effects": {"修复本源代价减少": 0.2}},
        })
        state = zhengdao.state_of(doc, 1.0)
        state["wounds"] = 1.0
        zhengdao.save(doc, state)
        ok, msg, delta = zhengdao.reshape(doc, {"五行本源": 5}, now=1.0)
        self.assertTrue(ok, msg)
        self.assertEqual(doc.stones, 0)
        self.assertEqual(delta["五行本源"], -5)

    def test_red_dust_sign_persists_for_24_hours_and_expires(self):
        doc = PlayerDoc(uid="sign", stones=600_000, ext={})
        ok, _msg = plane_events.ask_sign(doc, "问道签", now=1000)
        self.assertTrue(ok)
        self.assertEqual(doc.stones, 100_000)
        self.assertEqual(plane_events.sign_bonus(doc, "悟道收益", 1000 + 86_399), 0.1)
        self.assertEqual(plane_events.sign_bonus(doc, "悟道收益", 1000 + 86_400), 0.0)

    def test_sale_multiplier_is_applied(self):
        doc = PlayerDoc(uid="seller", stones=100, ext={
            "mingge": {"effects": {"出售价格倍率": 2}},
        })
        ok, _msg, sold = sell(doc, {"name": "物品", "出售价": 100}, 2)
        self.assertTrue(ok)
        self.assertEqual(sold.stones, 500)

    def test_talisman_bonus_adds_expected_output(self):
        ok, _msg, qty = occupation.talisman_make(
            {"name": "符", "level_limit": 0}, 0, 2, bonus=0.5,
            rng=SequenceRandom(),
        )
        self.assertTrue(ok)
        self.assertEqual(qty, 3)

    def test_equipment_special_fields_load_into_combat(self):
        doc = PlayerDoc(uid="special_gear", ext={"equipment": {
            "护具": "逍遥仙袍", "法宝": "魂河渡世灯", "武器": "小塔·有缺",
            "帝兵": "葬帝玄甲",
        }})
        items = {
            "逍遥仙袍": {"闪避率": 0.1, "首次免控": 1},
            "魂河渡世灯": {"元神伤害减免": 0.2, "首次免控": 1},
            "小塔·有缺": {"神力": 400},
            "葬帝玄甲": {"低血护盾": 0.2, "低血阈值": 0.3},
        }
        fighter = loadout.build_fighter(doc, "测试", 100, 100, 1000, 0, items.get)
        self.assertEqual(fighter.eff("dodge_after_control"), 0.1)
        self.assertEqual(fighter.eff("damage_reduction"), 0.2)
        self.assertTrue(fighter.eff("first_control_immunity"))
        self.assertEqual(fighter.eff("low_hp_shield_ratio"), 0.2)
        self.assertEqual(fighter.eff("orb_damage_flat"), 400)

    def test_sword_fetus_uses_supreme_and_other_multipliers(self):
        item = {"name": "大罗剑胎", "class": "装备", "type": "武器",
                "atk": 10, "def": 10, "HP": 10,
                "至尊体全属性倍率": 15, "其他灵根全属性倍率": 7.5}
        table = [{"基础攻击": 100, "基础防御": 100, "基础血量": 100}]
        supreme = PlayerDoc(uid="supreme", ext={
            "equipment": {"武器": "大罗剑胎"},
            "linggen": {"name": "天生至尊", "type": "至尊体"},
            "mingge": {"effects": {"生命本源额外": 50}},
        })
        other = PlayerDoc(uid="other", ext={"equipment": {"武器": "大罗剑胎"}})
        supreme_stats = equipment.aggregate(supreme, table, lambda _name: item)
        other_stats = equipment.aggregate(other, table, lambda _name: item)
        self.assertEqual(supreme_stats.atk, 250)
        self.assertEqual(other_stats.atk, 175)
        self.assertEqual(supreme_stats.hp, 50_250)

    def test_qiling_pill_requires_evaluation_and_caps_talent(self):
        pill = {"name": "凡品器灵丹", "class": "丹药", "type": "器灵", "天赋": 20}
        unevaluated = PlayerDoc(uid="unevaluated_forge", ext={"occupation": "炼器师"})
        ok, _msg, after, consumed = use_item(unevaluated, pill, 1)
        self.assertFalse(ok)
        self.assertIs(after, unevaluated)
        self.assertFalse(consumed)

        doc = PlayerDoc(uid="qiling_pill", ext={
            "occupation": "炼器师",
            duanzao.EXT_KEY: {"built": True, "talent": 190},
        })
        ok, msg, after, consumed = use_item(doc, pill, 1)
        self.assertTrue(ok, msg)
        self.assertTrue(consumed)
        self.assertEqual(duanzao.state_of(after)["talent"], 200)

        ok, _msg, capped, consumed = use_item(after, pill, 1)
        self.assertFalse(ok)
        self.assertIs(capped, after)
        self.assertFalse(consumed)
        ok, _msg, unchanged, consumed = use_item(after, pill, 2)
        self.assertFalse(ok)
        self.assertIs(unchanged, after)
        self.assertFalse(consumed)

    def test_true_artifact_pill_expands_next_forge_once(self):
        doc = PlayerDoc(uid="true_artifact_pill", ext={
            "occupation": "炼器师",
            duanzao.EXT_KEY: {"built": True, "talent": 100},
        })
        pill = {"name": "帝品真器丹", "class": "丹药", "type": "锻造上限",
                "额外数量": 10}
        ok, msg, after, consumed = use_item(doc, pill, 1)
        self.assertTrue(ok, msg)
        self.assertTrue(consumed)
        self.assertEqual(duanzao.capacity(duanzao.state_of(after), after), 20)

        ok, _msg, unchanged, consumed = use_item(after, pill, 1)
        self.assertFalse(ok)
        self.assertIs(unchanged, after)
        self.assertFalse(consumed)
        self.assertIn("待用真器丹效果保留", duanzao.clear(after)[1])
        self.assertEqual(duanzao.capacity(duanzao.state_of(after), after), 20)
        self.assertIn("真器丹容量加成 10", duanzao.panel(after, 1000, lambda _name: None))

        mat = {"星银": {"name": "星银", "type": "锻造", "攻": 1.0, "防": 0.8,
                        "血": 0.6, "暴": 0.2, "金": 1, "木": 0, "土": 0,
                        "水": 0, "火": 0}}
        lookup = mat.get
        ok, msg, _delta = duanzao.melt(after, {"星银": 11}, "星银*11", lookup)
        self.assertTrue(ok, msg)
        failed, _msg, _delta = duanzao.open_forge(
            after, "normal", {}, 1000, item_lookup=lookup, templates=[],
            rng=random.Random(0),
        )
        self.assertFalse(failed)
        self.assertEqual(duanzao.state_of(after)["furnace_bonus"], 10)

        duanzao.start(after, 1000)
        ok, msg, _delta = duanzao.open_forge(
            after, "normal", {}, 1000 + 60 * 60, item_lookup=lookup,
            templates=[{"name": "赤马阔刀", "type": "武器", "atk": 0.02,
                        "def": 0.01, "HP": 0.01, "稀有度": 1}],
            rng=random.Random(1),
        )
        self.assertTrue(ok, msg)
        self.assertEqual(duanzao.state_of(after)["furnace_bonus"], 0)

    def test_merchant_topans_have_equippable_records(self):
        path = Path(__file__).resolve().parents[1] / "data/item/装备列表.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        catalog = {row["name"]: row for row in rows}
        self.assertEqual(catalog["仙尊战袍·拓本"]["type"], "护具")
        self.assertEqual(catalog["仙尊战袍·拓本"]["全属性"], 0.18)
        self.assertEqual(catalog["弑帝枪·拓本"]["atk"], 0.25)
        self.assertEqual(catalog["万劫不侵钟·拓本"]["def"], 0.25)

    def test_equipment_special_combat_triggers(self):
        target = engine.Fighter("护持者", 10, 10, 1000, 1000, effects={
            "first_control_immunity": True,
            "dodge_after_control": 0.1,
            "low_hp_shield_ratio": 0.2,
            "low_hp_shield_threshold": 0.3,
        })
        self.assertIn("首次免疫控制", engine._apply_control(target, "眩晕", "定身"))
        self.assertFalse(target.eff("first_control_immunity"))
        self.assertTrue(engine._dodges_next_attack(target, SequenceRandom(0.05)))
        self.assertFalse(engine._dodges_next_attack(target, SequenceRandom(0.05)))
        hp, loss, text = engine._low_hp_shield(target, 500, 400)
        self.assertEqual((hp, loss), (300, 200))
        self.assertIn("低血护盾触发", text)
        self.assertEqual(target.eff("shield"), 0)


if __name__ == "__main__":
    unittest.main()
