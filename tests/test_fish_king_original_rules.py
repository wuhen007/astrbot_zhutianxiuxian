import random
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import fishing


class FishKingOriginalRules(unittest.TestCase):
    def spawn(self):
        world = {}
        with patch.object(fishing, 'king_of', return_value={
            'name': '测试鱼王', 'speed': 100, '灵根': {}, 'skills': [],
        }):
            team, _ = fishing.fk_spawn(
                world, 'group-a', 'owner', '垂钓者', '测试位面', 100,
                random.Random(1), now=1_800_000_000)
        return world, team

    def test_team_id_allows_cross_group_member_and_keeps_owner(self):
        world, team = self.spawn()
        joined, _ = fishing.fk_join(
            world, 'other-plane', 'guest', 0, group_id='group-b',
            team_id=team['team_id'], name='来援道友')
        self.assertTrue(joined)
        owner_left, _ = fishing.fk_leave(world, 'owner')
        self.assertFalse(owner_left)
        guest_left, message = fishing.fk_leave(world, 'guest')
        self.assertTrue(guest_left, message)

    def test_kill_reward_pool_is_three_unique_groups_per_member(self):
        _, team = self.spawn()
        assignments, relics = fishing.fk_kill_rewards(
            team, random.Random(17))
        for member in team['members']:
            ordinary = len(assignments.get(member['id'], {}))
            special_relics = len(relics.get(member['id'], []))
            self.assertEqual(ordinary + special_relics, 3)

    def test_each_chest_always_grants_fifteen_to_thirty_wish_scales(self):
        rewards, _ = fishing.fk_roll_chest(random.Random(4), 3)
        self.assertGreaterEqual(rewards[fishing.SCALE_ITEM], 45)
        self.assertLessEqual(rewards[fishing.SCALE_ITEM], 90)


if __name__ == '__main__':
    unittest.main()
