import random
import unittest

from core.combat import legacy_spar


class LegacySparSessionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            name: {"name": name, "cd": 2, "pr": 0.1, "last": 2, "msg": f"施展{name}"}
            for name in legacy_spar.SKILL_NAMES
        }
        units = {
            side: {"name": side.upper(), "atk": 100, "defense": 100,
                   "hp": 10_000, "hp_max": 10_000, "bao": 0.4,
                   "crit_damage": 2.0, "orb": 0.0}
            for side in ("a", "b")
        }
        self.state = legacy_spar.create_session(
            "test-session", "qq", "group", "a", "b", units, self.catalog, 100.0)

    def test_catalog_requires_the_original_ten_complete_skill_rows(self):
        self.assertEqual(legacy_spar.missing_definitions(self.catalog), [])
        self.assertEqual(legacy_spar.missing_definitions({}), list(legacy_spar.SKILL_NAMES))

    def test_catalog_rejects_incomplete_or_invalid_original_fields(self):
        incomplete = dict(self.catalog)
        incomplete["长生诀"] = {**incomplete["长生诀"]}
        del incomplete["长生诀"]["pr"]
        malformed = dict(self.catalog)
        malformed["祝水咒"] = {**malformed["祝水咒"], "cd": "unknown"}

        self.assertEqual(legacy_spar.missing_definitions(incomplete), ["长生诀"])
        self.assertEqual(legacy_spar.missing_definitions(malformed), ["祝水咒"])

    def test_catalog_uses_the_first_duplicate_like_source_find(self):
        rows = [*self.catalog.values(), {**self.catalog["长生诀"], "cd": 99}]

        catalog = legacy_spar.normalize_catalog(rows)

        self.assertEqual(catalog["长生诀"]["cd"], 2)

    def test_each_player_can_select_at_most_three_per_submission(self):
        ok, _ = legacy_spar.choose_skills(self.state, "a", [1, 2, 3, 4], 101.0)
        self.assertTrue(ok)
        self.assertEqual(len(self.state["choices"]["a"]), 3)
        self.assertEqual(self.state["phase"], "select")

    def test_uid_isolation_and_release_phase_validation(self):
        ok, msg = legacy_spar.choose_skills(self.state, "intruder", [1], 101.0)
        self.assertFalse(ok)
        self.assertIn("不在本场", msg)
        ok, msg = legacy_spar.release_skill(self.state, "a", 1, 101.0)
        self.assertFalse(ok)
        self.assertIn("还不能提交释放技能", msg)

    def test_original_round_resolves_a_first_and_skips_b_after_a_kill(self):
        self.state["units"]["a"].update(atk=10_000_000, defense=100, hp=10_000, hp_max=10_000)
        self.state["units"]["b"].update(atk=10, defense=100, hp=10_000, hp_max=10_000)
        result = legacy_spar.resolve_round(self.state, random.Random(1))

        self.assertEqual(result["winner"], "a")
        self.assertEqual(sum("普通攻击" in line for line in result["log"]), 1)
        self.assertEqual(self.state["phase"], "finished")

    def test_skills_can_be_added_during_release_after_initial_selection_window(self):
        legacy_spar.begin_round(self.state, 150.0)

        ok, _ = legacy_spar.choose_skills(self.state, "a", [1], 150.0)

        self.assertTrue(ok)
        self.assertEqual(len(self.state["choices"]["a"]), 1)

    def test_release_can_be_changed_after_prompt_deadline_before_resolution(self):
        legacy_spar.choose_skills(self.state, "a", [1], 100.0)
        legacy_spar.begin_round(self.state, 101.0)

        ok, _ = legacy_spar.release_skill(self.state, "a", 1, 122.0)

        self.assertTrue(ok)
        self.assertEqual(self.state["release"]["a"], 0)

    def test_zero_is_not_an_explicit_basic_attack_command(self):
        legacy_spar.begin_round(self.state, 101.0)

        ok, msg = legacy_spar.release_skill(self.state, "a", 0, 102.0)

        self.assertFalse(ok)
        self.assertIn("序号", msg)
        self.assertIsNone(self.state["release"]["a"])

    def test_uncommitted_round_action_defaults_to_basic_attack(self):
        legacy_spar.begin_round(self.state, 101.0)

        result = legacy_spar.resolve_round(self.state, random.Random(1))

        self.assertTrue(any("普通攻击" in line for line in result["log"]))

if __name__ == "__main__":
    unittest.main()
