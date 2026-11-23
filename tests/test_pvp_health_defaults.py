import unittest

from core import pvp
from core.player import PlayerDoc


class PvpHealthDefaultTests(unittest.TestCase):
    def test_syncing_resolved_full_health_allows_new_players_through_biwu_gate(self):
        first = PlayerDoc(uid="first")
        second = PlayerDoc(uid="second")

        pvp.sync_health(first, 100, 100)
        pvp.sync_health(second, 100, 100)

        self.assertIsNone(pvp.biwu_check(first, second, 1_800_000_000))

    def test_syncing_resolved_health_allows_uninjured_new_target_through_rob_gate(self):
        actor = PlayerDoc(uid="actor", ext={"xueqi": 1_000_000})
        target = PlayerDoc(uid="target", stones=pvp.ROB_MIN_LOOT)

        pvp.sync_health(actor, pvp.ROB_MIN_HP, pvp.ROB_MIN_HP)
        pvp.sync_health(target, pvp.ROB_MIN_HP, pvp.ROB_MIN_HP)

        self.assertIsNone(pvp.rob_check(actor, target, 1_800_000_000))


if __name__ == "__main__":
    unittest.main()
