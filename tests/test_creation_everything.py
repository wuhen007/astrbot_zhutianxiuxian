import unittest

from core import creation_everything
from core.player import PlayerDoc


class CreationEverythingTests(unittest.TestCase):
    def test_original_creation_quote_uses_ceil_rarity_and_per_item_bearing_cost(self):
        item = {"name": "玄品灵丹", "稀有度": 2.1}
        sale_item = {"出售价": 101}

        quote = creation_everything.quote(21, item, sale_item, 2)

        self.assertEqual(quote, {
            "authority_level": 21,
            "rarity": 3,
            "amount": 2,
            "unit_bearing_cost": 2,
            "bearing_cost": 4,
            "quantity_multiplier": 1,
            "minutes": 15,
            "causal_debt": 15,
        })

    def test_missing_or_zero_rarity_uses_original_minimum_one(self):
        sale_item = {"出售价": 100}
        self.assertEqual(creation_everything.quote(
            21, {"name": "旧档灵物"}, sale_item, 1)["rarity"], 1)
        self.assertEqual(creation_everything.quote(
            21, {"name": "凡品灵物", "稀有度": 0}, sale_item, 1)["rarity"], 1)

    def test_jidao_costs_and_creation_time_follow_original_tier(self):
        item = {"name": "圣品道果", "稀有度": 3}
        sale_item = {"出售价": 10_001}

        jidao = creation_everything.quote(22, item, sale_item, 1)
        unique = creation_everything.quote(23, item, sale_item, 1)

        self.assertEqual((jidao["unit_bearing_cost"], jidao["minutes"],
                          jidao["causal_debt"]), (2, 9, 9))
        self.assertEqual((unique["unit_bearing_cost"], unique["minutes"],
                          unique["causal_debt"]), (0, 3, 0))

    def test_quantity_multiplier_applies_cumulative_original_thresholds(self):
        item = {"name": "仙丹", "稀有度": 1}
        sale_item = {"出售价": 100}

        self.assertEqual(creation_everything.quote(21, item, sale_item, 10)["quantity_multiplier"], 1)
        self.assertEqual(creation_everything.quote(21, item, sale_item, 11)["quantity_multiplier"], 2)
        self.assertEqual(creation_everything.quote(21, item, sale_item, 1000)["quantity_multiplier"], 64)
        self.assertEqual(creation_everything.quote(21, item, sale_item, 1200)["quantity_multiplier"], 64)
        self.assertEqual(creation_everything.quote(21, item, sale_item, 1201)["quantity_multiplier"], 192)

    def test_rejects_forbidden_items_and_unsafe_quantity_or_cost(self):
        with self.assertRaises(ValueError):
            creation_everything.quote(21, {"name": "唯一仙器", "稀有度": 1, "不可创造": 1},
                                      {"出售价": 100}, 1)
        with self.assertRaises(ValueError):
            creation_everything.quote(21, {"name": "仙丹", "稀有度": 1},
                                      {"出售价": 100}, 0)
        with self.assertRaises(ValueError):
            creation_everything.quote(21, {"name": "仙丹", "稀有度": 1},
                                      {"出售价": 2**70}, 1)

    def test_action_waits_for_deadline_then_can_be_claimed_once(self):
        doc = PlayerDoc(uid="creator", state="空闲")
        quote = creation_everything.quote(
            21, {"name": "仙丹", "稀有度": 1}, {"出售价": 100}, 3)

        ok, _message = creation_everything.begin(doc, "仙丹", quote, 100.0)
        waiting = creation_everything.claim(doc, 100.0 + quote["minutes"] * 60 - 1)
        settled = creation_everything.claim(doc, 100.0 + quote["minutes"] * 60)
        repeated = creation_everything.claim(doc, 100.0 + quote["minutes"] * 60 + 1)

        self.assertTrue(ok)
        self.assertIsNone(waiting)
        self.assertEqual(settled["amount"], 3)
        self.assertIsNone(repeated)
        self.assertEqual(doc.state, "空闲")

    def test_begin_requires_idle_and_backlash_drops_highest_extra_route(self):
        from core import extra_cultivation, selfdao

        active = PlayerDoc(uid="busy", state="闭关中")
        quote = creation_everything.quote(
            21, {"name": "仙丹", "稀有度": 1}, {"出售价": 100}, 1)
        ok, _message = creation_everything.begin(active, "仙丹", quote, 100.0)
        self.assertFalse(ok)
        self.assertEqual(active.state, "闭关中")

        emperor = PlayerDoc(uid="emperor", ext={
            "extra_cultivation": {"version": 1,
                "levels": {"mijing": 21, "xiangu": 20, "huafen": 19},
                "synced": {"mijing": 1, "xiangu": 2, "huafen": 1},
                "overrides": {"mijing": True, "xiangu": True, "huafen": True}},
            "selfdao": {"layers": 20},
            "daoshang": {"reached": True, "emperor_title": "无名天帝"},
            "ownway": {"jidao": True, "unique": True, "seg": 500},
        })
        struck = creation_everything.apply_ancestral_backlash(
            emperor, authority_level=21, bearing=999_999, roll=0.39)
        self.assertTrue(struck)
        self.assertEqual(extra_cultivation.level_of(emperor, "mijing"), 20)
        self.assertEqual(selfdao.state_of(emperor)["layers"], 0)
        self.assertFalse(emperor.ext["daoshang"]["reached"])
        self.assertFalse(emperor.ext["ownway"]["unique"])

        jidao = PlayerDoc(uid="jidao", realm_index=63)
        self.assertFalse(creation_everything.apply_ancestral_backlash(
            jidao, authority_level=22, bearing=0, roll=0.0))
        self.assertEqual(jidao.realm_index, 63)


class CreationSpecTests(unittest.TestCase):
    def test_spec_parser_supports_optional_count_and_rejects_other_players(self):
        self.assertEqual(creation_everything.parse_spec("混沌丹 12"), ("混沌丹", 12))
        self.assertEqual(creation_everything.parse_spec("混沌丹*12"), ("混沌丹", 12))
        with self.assertRaises(ValueError):
            creation_everything.parse_spec("混沌丹 @道友")

if __name__ == "__main__":
    unittest.main()
