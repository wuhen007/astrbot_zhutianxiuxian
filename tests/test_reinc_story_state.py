import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import reinc_state as rs
from core.player import PlayerDoc


class ReincarnationStateTests(unittest.TestCase):
    def _start(self, uid="reinc-state", profession="special_forces", seed=1):
        doc = PlayerDoc(uid=uid, ext={})
        ok, _ = rs.start(doc, profession, seed=seed)
        self.assertTrue(ok)
        return doc

    def _boost_attributes(self, doc, value=30):
        state = rs.state_of(doc)
        state["attributes"] = {key: value for key in state["attributes"]}
        rs.save(doc, state)

    def test_catalog_and_seven_scene_branch_are_persisted(self):
        self.assertEqual(8, len(rs.PROFESSIONS))
        self.assertEqual(20, len(rs.NPC_TEMPLATES))
        self.assertEqual(14, len(rs.MONSTERS))
        self.assertEqual(7, len(rs.SCENES))
        doc = self._start()
        scene = rs.scene_view(doc)
        self.assertEqual("awakening", scene["id"])
        self.assertEqual(3, len(scene["choices"]))
        self.assertEqual(3, len(rs.state_of(doc)["npcs"]))

        self._boost_attributes(doc)
        self.assertTrue(rs.choose(doc, 2)[0])  # loopClue
        self.assertEqual("rule_test", rs.state_of(doc)["scene_id"])
        self.assertTrue(rs.choose(doc, 1)[0])  # ghostNumber
        self.assertEqual("child_signal", rs.state_of(doc)["scene_id"])
        self.assertTrue(rs.choose(doc, 3)[0])  # requires loopClue or ghostNumber
        state = rs.state_of(doc)
        self.assertTrue(state["flags"]["childSaved"])
        self.assertTrue(state["flags"]["loopKey"])
        self.assertEqual("black_box", state["scene_id"])

    def test_encounters_and_tasks_reflect_persistent_original_state(self):
        doc = self._start("reinc-monster")
        self._boost_attributes(doc)
        rs.choose(doc, 1)
        scene = rs.scene_view(doc)
        self.assertEqual("rule_test", scene["id"])
        self.assertIsNotNone(scene["encounter"])
        self.assertEqual("active", scene["encounter"]["status"])
        self.assertEqual(6, len(rs.tasks(doc)))
        self.assertEqual("active", rs.tasks(doc)[0]["status"])

        rs.choose(doc, 1)
        state = rs.state_of(doc)
        self.assertEqual("child_signal", state["scene_id"])
        encounter = next(row for row in state["encounters"] if row["scene_id"] == "rule_test")
        self.assertIn(encounter["status"], {"defeated", "repelled"})
        self.assertIn("信任", rs.squad_text(doc))
        self.assertIn("已击败", rs.monster_text(doc))

    def test_failed_encounter_damages_player_and_party(self):
        doc = self._start("reinc-fail")
        rs.choose(doc, 1)
        state = rs.state_of(doc)
        state["attributes"] = {key: 0 for key in state["attributes"]}
        rs.save(doc, state)
        hp_before = state["hp"]
        party_hp_before = [npc["hp"] for npc in state["npcs"]]
        ok, _ = rs.choose(doc, 1)
        self.assertTrue(ok)
        state = rs.state_of(doc)
        self.assertLess(state["hp"], hp_before)
        self.assertEqual("escaped", next(row for row in state["encounters"]
                                         if row["scene_id"] == "rule_test")["status"])
        self.assertTrue(any(npc["hp"] < old for npc, old in zip(state["npcs"], party_hp_before)))

    def test_completed_run_settles_original_ending_points_into_wallet(self):
        doc = self._start("reinc-ending", seed=17)
        self._boost_attributes(doc)
        for choice in (2, 1, 3, 1, 1, 3, 2):
            ok, _ = rs.choose(doc, choice)
            self.assertTrue(ok)
            if rs.state_of(doc)["phase"] == "ending":
                break
        state = rs.state_of(doc)
        self.assertEqual("ending", state["phase"])
        self.assertEqual("deep_truth", state["settlement"]["endingId"])
        self.assertGreaterEqual(state["settlement"]["points"], 3400)
        self.assertTrue(rs.settle(doc)[0])
        self.assertFalse(rs.state_of(doc)["active"])
        self.assertGreaterEqual(rs.state_of(doc)["points"], 3400)
    def test_original_training_and_exchange_apply_permanent_attributes(self):
        doc = PlayerDoc(uid="reinc-meta", ext={})
        state = rs.state_of(doc)
        state["points"] = 600
        rs.save(doc, state)
        self.assertTrue(rs.enhance(doc, "生命力")[0])
        self.assertEqual(0, rs.state_of(doc)["points"])
        self.assertTrue(rs.start(doc, "special_forces", seed=3)[0])
        attrs = rs.state_of(doc)["attributes"]
        profession_bonus = rs._profession(rs.state_of(doc)).get("attributes", {})
        self.assertEqual(6 + int(profession_bonus.get("体力", 0)), attrs["体力"])
        self.assertEqual(6 + int(profession_bonus.get("免疫力", 0)), attrs["免疫力"])
        self.assertEqual(6 + int(profession_bonus.get("恢复力", 0)), attrs["恢复力"])

        doc = PlayerDoc(uid="reinc-exchange", ext={})
        state = rs.state_of(doc)
        state["points"] = 9000
        state["best"] = 3399
        rs.save(doc, state)
        self.assertFalse(rs.exchange(doc, "causality_observer")[0])
        self.assertEqual(9000, rs.state_of(doc)["points"])
        state["best"] = 3400
        rs.save(doc, state)
        self.assertTrue(rs.exchange(doc, "causality_observer")[0])
        self.assertTrue(rs.start(doc, "special_forces", seed=4)[0])
        attributes = rs.state_of(doc)["attributes"]
        profession_bonus = rs._profession(rs.state_of(doc)).get("attributes", {})
        self.assertTrue(all(value == 6 + int(profession_bonus.get(name, 0))
                            for name, value in attributes.items()))

    def test_exchange_purchase_limit_is_enforced(self):
        doc = PlayerDoc(uid="reinc-limit", ext={})
        state = rs.state_of(doc)
        state["points"] = 6000
        state["best"] = 900
        rs.save(doc, state)
        for _ in range(5):
            self.assertTrue(rs.exchange(doc, "gene_stabilizer")[0])
        self.assertFalse(rs.exchange(doc, "gene_stabilizer")[0])
        self.assertEqual(50, rs.state_of(doc)["geneLockStability"])


if __name__ == "__main__":
    unittest.main()
