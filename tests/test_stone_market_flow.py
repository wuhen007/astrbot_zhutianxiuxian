import random
import unittest

from core import yuanshi
from core.player import PlayerDoc


class StoneMarketFlowTests(unittest.TestCase):
    def test_garden_and_inspection_usage_persist_per_shanghai_day(self):
        now = 1_800_000_000.0
        y = yuanshi.system_of(PlayerDoc(uid="u1", ext={}))
        yuanshi.set_active_garden(y, "地字号", now)
        stones = yuanshi.make_market("u1", "地字号", now, y)

        first = yuanshi.inspect_market(y, "地字号", stones, 1,
                                       {"occupation": "普通", "occupation_level": 0}, now,
                                       random.Random(4))
        second = yuanshi.inspect_market(y, "地字号", stones, 2,
                                        {"occupation": "普通", "occupation_level": 0}, now,
                                        random.Random(4))
        third = yuanshi.inspect_market(y, "地字号", stones, 3,
                                       {"occupation": "普通", "occupation_level": 0}, now,
                                       random.Random(4))
        self.assertTrue(first[0] and second[0])
        self.assertFalse(third[0])
        self.assertIn("用尽", third[1])

        refreshed = yuanshi.market_state(y, now + 86400)
        self.assertEqual(refreshed["active_garden"], "外园")
        self.assertEqual(refreshed["inspected"], {})

    def test_source_master_check_is_once_per_day_and_reveals_false_signal(self):
        now = 1_800_000_000.0
        y = yuanshi.system_of(PlayerDoc(uid="u1", ext={}))
        stones = [{"no": 1, "name": "空石", "outcome": "empty", "ratio": 0,
                   "item": None, "danger": False, "surface": "源气外散",
                   "surface_truthful": False}]

        denied = yuanshi.heavenly_check(
            y, "外园", stones, stones[0]["no"], {"occupation": "源地师"}, now)
        self.assertFalse(denied[0])
        checked = yuanshi.heavenly_check(
            y, "外园", stones, stones[0]["no"], {"occupation": "源天师"}, now)
        repeated = yuanshi.heavenly_check(
            y, "外园", stones, stones[0]["no"], {"occupation": "源天师"}, now)
        self.assertTrue(checked[0])
        self.assertIn("假象", checked[1])
        self.assertFalse(repeated[0])

    def test_purchase_persists_pending_cut_and_daily_count(self):
        now = 1_800_000_000.0
        y = yuanshi.system_of(PlayerDoc(uid="u1", ext={"yuanshi": {"amount": 1_000_000}}))
        stones = yuanshi.make_market("u1", "地字号", now, y)

        ok, message, cost = yuanshi.purchase_stone(y, "地字号", stones, 1, 0, now)
        self.assertTrue(ok, message)
        self.assertEqual(cost, {"currency": "源石", "amount": stones[0]["price"]})
        self.assertEqual(y["amount"], 1_000_000 - stones[0]["price"])
        self.assertEqual(yuanshi.market_state(y, now)["pending"]["phase"], "choose")

        ok2, msg2, _ = yuanshi.purchase_stone(y, "地字号", stones, 2, 0, now)
        self.assertFalse(ok2)
        self.assertIn("切开", msg2)

    def test_layered_cut_can_be_bought_back_once(self):
        now = 1_800_000_000.0
        stone = {"no": 1, "price": 300_000, "name": "封印太古生物",
                 "outcome": "ancient", "ratio": 0.0, "item": None,
                 "danger": True, "surface": "封纹"}
        y = yuanshi.system_of(PlayerDoc(uid="u1", ext={"yuanshi": {
            "amount": 2_000_000, "cuts": 6, "empty_streak": 2,
        }}))
        stones = [dict(stone)]
        purchased, message, _ = yuanshi.purchase_stone(y, "天字号", stones, 1, 0, now)
        self.assertTrue(purchased, message)
        before_fee = y["amount"]
        ok, msg, _, settlement = yuanshi.cut_pending(
            y, "layered", "普通", 0, random.Random(1), now)
        self.assertTrue(ok)
        self.assertEqual(y["amount"], before_fee - 30_000)
        self.assertEqual(yuanshi.market_state(y, now)["pending"]["phase"], "peeling")
        self.assertEqual(settlement["gains"], {})

        buyback, _, settlement = yuanshi.resolve_buyback(y, now)
        self.assertTrue(buyback)
        self.assertEqual(settlement["currency"], "源石")
        self.assertEqual(y["amount"], before_fee - 30_000 + 315_000)
        self.assertEqual((y["cuts"], y["empty_streak"]), (6, 2))
        self.assertIn("回购 +315,000源石", yuanshi.ledger_text(y))
        self.assertIn("源石净支出 15,000", yuanshi.ledger_text(y))
        self.assertIsNone(yuanshi.market_state(y, now)["pending"])
        repeat, _, _ = yuanshi.resolve_buyback(y, now)
        self.assertFalse(repeat)

    def test_one_cut_damages_fragile_treasure_but_layered_preserves_it(self):
        now = 1_800_000_000.0
        item_stone = {"no": 1, "price": 300_000, "name": "神源液",
                      "outcome": "divine_liquid", "ratio": 0.0,
                      "item": "神源液", "danger": False, "surface": "水声"}
        y = yuanshi.system_of(PlayerDoc(uid="u1", ext={"yuanshi": {"amount": 900_000}}))
        stones = [dict(item_stone)]
        ok, _, _ = yuanshi.purchase_stone(y, "地字号", stones, 1, 0, now)
        self.assertTrue(ok)
        ok, _, _, settlement = yuanshi.cut_pending(y, "one", "普通", 0,
                                                   random.Random(1), now)
        self.assertTrue(ok)
        self.assertTrue(settlement["damaged"])
        self.assertEqual(settlement["gains"], {})

        y2 = yuanshi.system_of(PlayerDoc(uid="u2", ext={"yuanshi": {"amount": 900_000}}))
        ok, _, _ = yuanshi.purchase_stone(y2, "地字号", [dict(item_stone)], 1, 0, now)
        self.assertTrue(ok)
        ok, _, _, settlement = yuanshi.cut_pending(y2, "layered", "普通", 0,
                                                   random.Random(1), now)
        self.assertTrue(ok)
        self.assertFalse(settlement["finished"])
        balance = y2["amount"]
        ok, _, settlement = yuanshi.continue_peeling(y2, random.Random(1), now + 86_400)
        self.assertTrue(ok)
        self.assertEqual(settlement["gains"], {"神源液": 1})
        self.assertEqual(y2["amount"], balance)
        self.assertIn("源石净支出 330,000", yuanshi.ledger_text(y2))
        self.assertFalse(yuanshi.continue_peeling(y2, random.Random(1), now + 86_400)[0])

    def test_mingge_source_income_bonus_applies_to_cut_return(self):
        now = 1_800_000_000.0
        stone = {"no": 1, "price": 100_000, "name": "纯净源", "outcome": "pure",
                 "ratio": 1.0, "item": None, "danger": False, "surface": "源气"}
        y = yuanshi.system_of(PlayerDoc(uid="bonus", ext={"yuanshi": {"amount": 1_000_000}}))
        self.assertTrue(yuanshi.purchase_stone(y, "地字号", [stone], 1, 0, now)[0])
        before = y["amount"]
        ok, _msg, y, settlement = yuanshi.cut_pending(
            y, "one", "普通", 0, random.Random(1), now, source_bonus=0.25)
        self.assertTrue(ok)
        self.assertEqual(settlement["source"], 125_000)
        self.assertEqual(y["amount"], before + 125_000)


if __name__ == "__main__":
    unittest.main()
