import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import lifespan
from core.player import PlayerDoc


class TravelAvatarRebirthTests(unittest.TestCase):
    def test_expired_travel_rebirth_waits_for_avatar_to_return_to_origin(self):
        fallen = PlayerDoc(uid="travel-avatar", realm_index=9, exp=50, stones=100, ext={
            "shouyuan": 2400, "hp": 1, "awaiting_rescue": True,
            "rescue_deadline": 300.0, "travel_ambush_rebirth": True,
            "zhutian": {"current": "化身甲"},
        })

        waiting = lifespan.resolve_if_due(fallen, 301.0, forced=False)

        self.assertIsNone(waiting)
        self.assertTrue(lifespan.pending(fallen))
        self.assertNotIn("rebirths", fallen.ext)

        fallen.ext["zhutian"]["current"] = ""
        resolved = lifespan.resolve_if_due(fallen, 302.0, forced=False)

        self.assertIn("轮回往生", resolved)
        self.assertEqual(fallen.ext["rebirths"], 1)
        self.assertFalse(lifespan.pending(fallen))


if __name__ == "__main__":
    unittest.main()
