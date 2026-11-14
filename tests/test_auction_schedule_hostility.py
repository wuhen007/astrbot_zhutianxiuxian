import random
import unittest
from datetime import datetime, timedelta, timezone

from core import auction


class AuctionScheduleAndHostilityTests(unittest.TestCase):
    def setUp(self):
        self.tz = timezone(timedelta(hours=8))

    def stamp(self, hour, minute=0):
        return datetime(2026, 11, 15, hour, minute, tzinfo=self.tz).timestamp()

    def test_windows_match_original_evening_schedule(self):
        self.assertEqual(auction.open_kinds_at(self.stamp(19, 59)), set())
        self.assertEqual(auction.open_kinds_at(self.stamp(20)), {"official"})
        self.assertEqual(auction.open_kinds_at(self.stamp(21)), {"inner"})
        self.assertEqual(auction.open_kinds_at(self.stamp(22, 59)), {"inner"})
        self.assertEqual(auction.open_kinds_at(self.stamp(23)), set())

    def test_enabled_lots_only_open_inside_window_and_registered_groups(self):
        w = auction.world_of({})
        w["enabled"] = True
        w["groups"] = ["g1"]
        pools = {"official": [{"name": "灵剑", "出售价": 100}]}
        notes, _ = auction.tick(w, self.stamp(19), pools, random.Random(1), {}, set())
        self.assertEqual(notes, [])
        self.assertIsNone(w["official"])
        notes, _ = auction.tick(w, self.stamp(20), pools, random.Random(1), {}, {"official"})
        self.assertEqual(len(notes), 1)
        self.assertEqual(w["official"]["groups"], ["g1"])

    def test_hated_available_tianjiao_is_weighted_then_event_gated(self):
        doc = type("Doc", (), {"ext": {"tianjiao_hatred": {"仇恨者": 61, "未达标": 60}}})()
        rows = [{"name": "仇恨者"}, {"name": "未达标"}, {"name": "已陨落"}]
        world = {"bosses": {"已陨落": {"hp_pct": 0, "alive_until": 0}}}

        class FixedRandom:
            def __init__(self, values):
                self.values = iter(values)
            def random(self):
                return next(self.values)

        picked = auction.select_hostile_tianjiao(doc, rows, world, 1000, FixedRandom([0, 0]))
        self.assertEqual(picked, "仇恨者")
        self.assertIsNone(auction.select_hostile_tianjiao(doc, rows, world, 1000, FixedRandom([0, .3])))

    def test_scheduled_tick_does_not_open_or_settle_player_market(self):
        w = auction.world_of({})
        w["enabled"] = True
        w["groups"] = ["g1"]
        w["player"] = {"id": "player-1", "kind": "player", "name": "灵石", "price": 100,
                       "amount": 1, "bid_ts": 1, "bidder": "0", "seller": "7"}
        notes, ops = auction.tick(w, 10_000, {"player": [{"name": "new"}]},
                                  random.Random(1), {}, set(),
                                  allow_player_open=False, scheduled=True)
        self.assertEqual(notes, [])
        self.assertEqual(ops, [])
        self.assertIsNotNone(w["player"])

    def test_inner_npc_bids_only_during_scheduled_minute_tick(self):
        class FixedRandom:
            def random(self):
                return 0.1
            def choices(self, population, weights, k):
                return [population[0]]
            def uniform(self, low, high):
                return low
            def choice(self, population):
                return population[0]

        w = auction.world_of({})
        w["inner"] = {"id": "inner-1", "name": "灵药", "price": 100,
                      "bidder": "42", "bid_ts": 0}
        pools = {"inner": []}
        notes, _ = auction.tick(w, 60, pools, FixedRandom(), {}, set(), scheduled=False)
        self.assertEqual(notes, [])
        self.assertEqual(w["inner"]["bidder"], "42")
        notes, _ = auction.tick(w, 60, pools, FixedRandom(), {}, set(), scheduled=True)
        self.assertEqual(len(notes), 1)
        self.assertEqual(w["inner"]["price"], 105)
        self.assertEqual(w["inner"]["bidder"], "-1")
        self.assertEqual(w["inner"]["npcBidder"], "隐世高人")

    def test_counterbid_once_per_player_and_sets_original_auction_fields(self):
        w = {"official": {"price": 100, "bidder": "42", "bid_ts": 1}}
        class FixedRandom:
            def random(self):
                return 0
        rng = FixedRandom()
        applied, price = auction.apply_tianjiao_counterbid(w, "official", "仇恨者", "42", rng, 120)
        self.assertTrue(applied)
        self.assertEqual(price, 111)
        self.assertEqual(w["official"]["bidder"], "-1")
        self.assertEqual(w["official"]["last_offer_player"], -1)
        self.assertEqual(w["official"]["tianjiaoBidder"], "仇恨者")
        self.assertEqual(w["official"]["tianjiaoCounteredPlayers"], ["42"])
        self.assertEqual(auction.apply_tianjiao_counterbid(w, "official", "仇恨者", "42", rng, 130), (False, 111))


if __name__ == "__main__":
    unittest.main()
