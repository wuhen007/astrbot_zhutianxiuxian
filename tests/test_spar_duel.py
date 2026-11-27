import unittest

from core.combat import spar_duel


def make_duel(hp_a=10000, hp_b=10000):
    return spar_duel.new_duel(
        "u1", "甲", {"atk": 500, "defense": 300, "hp": hp_a, "bao": 0.0, "orb": 0.0},
        "u2", "乙", {"atk": 500, "defense": 300, "hp": hp_b, "bao": 0.0, "orb": 0.0},
        now=0.0,
    )


def start(duel, picks_a=(1, 5, 10), picks_b=(2, 3, 4)):
    spar_duel.pick(duel, "u1", list(picks_a), 0.0)
    spar_duel.pick(duel, "u2", list(picks_b), 0.0)
    return duel


class SparDuelRulesTests(unittest.TestCase):
    def test_pick_limits_dedupes_and_rejects_bad_index(self):
        duel = make_duel()
        ok, _ = spar_duel.pick(duel, "u1", [1, 1, 2, 3, 4], 0.0)
        self.assertTrue(ok)
        self.assertEqual(duel["a"]["picks"], ["四象封印", "桃园结义", "长生诀"])
        self.assertFalse(spar_duel.pick(duel, "u2", [99], 0.0)[0])
        self.assertFalse(spar_duel.pick(duel, "u3", [1], 0.0)[0])

    def test_both_picked_enters_fight(self):
        duel = start(make_duel())
        self.assertEqual(duel["phase"], "fight")
        self.assertEqual(duel["round"], 1)

    def test_cooldown_blocks_repeat_and_zero_is_basic_attack(self):
        duel = start(make_duel(), picks_a=(1, 2, 3))
        spar_duel.act(duel, "u1", 1, 0.0)
        spar_duel.act(duel, "u2", 0, 0.0)
        spar_duel.tick(duel, 0.0)
        self.assertEqual(duel["a"]["cd"]["四象封印"], 4)
        ok, msg = spar_duel.act(duel, "u1", 1, 1.0)
        self.assertFalse(ok)
        self.assertIn("冷却", msg)
        self.assertTrue(spar_duel.act(duel, "u1", 0, 1.0)[0])

    def test_seal_blocks_enemy_skill_next_round(self):
        duel = start(make_duel(), picks_a=(1, 6, 7), picks_b=(8, 9, 10))
        spar_duel.act(duel, "u1", 1, 0.0)     # 四象封印
        spar_duel.act(duel, "u2", 1, 0.0)     # 失魂落魄
        spar_duel.tick(duel, 0.0)
        spar_duel.act(duel, "u2", 1, 1.0)     # 下回合乙仍被封
        spar_duel.act(duel, "u1", 0, 1.0)
        log = spar_duel.tick(duel, 1.0)
        self.assertTrue(any("神通被封" in line for line in log))

    def test_atk_down_and_def_down_are_applied(self):
        duel = start(make_duel(), picks_a=(5, 7, 10), picks_b=(2, 3, 4))
        spar_duel.act(duel, "u1", 1, 0.0)     # 阴风蚀骨 -12% 攻
        spar_duel.act(duel, "u2", 0, 0.0)
        spar_duel.tick(duel, 0.0)
        atk, _def, _bao, _mult = spar_duel._stats(duel["b"], duel["round"])
        self.assertLess(atk, duel["b"]["atk"])
        duel2 = start(make_duel(), picks_a=(7, 5, 10), picks_b=(2, 3, 4))
        spar_duel.act(duel2, "u1", 1, 0.0)    # 心烦意乱 -12% 防
        spar_duel.act(duel2, "u2", 0, 0.0)
        spar_duel.tick(duel2, 0.0)
        _atk, dfn, _b, _m = spar_duel._stats(duel2["b"], duel2["round"])
        self.assertLess(dfn, duel2["b"]["defense"])

    def test_crit_zero_skill_zeroes_crit(self):
        duel = make_duel()
        duel["b"]["bao"] = 0.5
        start(duel, picks_a=(9, 5, 10), picks_b=(2, 3, 4))
        spar_duel.act(duel, "u1", 1, 0.0)     # 玄冰封印
        spar_duel.act(duel, "u2", 0, 0.0)
        spar_duel.tick(duel, 0.0)
        _atk, _def, bao, _mult = spar_duel._stats(duel["b"], duel["round"])
        self.assertEqual(bao, 0.0)

    def test_heal_self_and_heal_both(self):
        duel = make_duel()
        duel["a"]["hp"] = 1000
        duel["b"]["hp"] = 1000
        duel["b"]["atk"] = 1          # 排除对拼伤害对回血断言的干扰
        start(duel, picks_a=(3, 2, 10), picks_b=(2, 3, 4))
        spar_duel.act(duel, "u1", 1, 0.0)     # 长生诀 回上限 20%
        spar_duel.act(duel, "u2", 0, 0.0)
        spar_duel.tick(duel, 0.0)
        self.assertGreater(duel["a"]["hp"], 1000)
        duel2 = make_duel()
        duel2["a"]["hp"] = 1000
        duel2["b"]["hp"] = 1000
        duel2["a"]["atk"] = 1
        duel2["b"]["atk"] = 1
        start(duel2, picks_a=(2, 3, 10), picks_b=(2, 3, 4))
        spar_duel.act(duel2, "u1", 1, 0.0)    # 桃园结义 双方各回
        spar_duel.act(duel2, "u2", 0, 0.0)
        spar_duel.tick(duel2, 0.0)
        self.assertGreater(duel2["a"]["hp"], 1000)
        self.assertGreater(duel2["b"]["hp"], 1000)

    def test_timeout_falls_back_to_basic_attack(self):
        duel = start(make_duel())
        spar_duel.tick(duel, spar_duel.TURN_SECONDS + 1)
        self.assertEqual(duel["round"], 2)
        self.assertTrue(any("超时" in line for line in duel["log"]))

    def test_dead_side_ends_duel_with_winner(self):
        duel = start(make_duel(hp_b=1), picks_a=(10, 5, 9), picks_b=(2, 3, 4))
        spar_duel.act(duel, "u1", 1, 0.0)     # 诛仙三剑加持后一击必杀
        spar_duel.act(duel, "u2", 0, 0.0)
        spar_duel.tick(duel, 0.0)
        self.assertEqual(duel["phase"], "done")
        self.assertEqual(duel["winner"], 0)

    def test_round_cap_decides_by_hp_ratio(self):
        duel = make_duel(hp_a=10000, hp_b=10000)
        duel["round"] = spar_duel.MAX_ROUNDS
        duel["b"]["hp"] = 9000
        start(duel)
        spar_duel.act(duel, "u1", 0, 0.0)
        spar_duel.act(duel, "u2", 0, 0.0)
        spar_duel.tick(duel, 0.0)
        self.assertEqual(duel["phase"], "done")

    def test_skill_entries_are_well_formed(self):
        self.assertEqual(len(spar_duel.SKILLS), 10)
        for s in spar_duel.SKILLS:
            self.assertGreaterEqual(s["cd"], 1)
            self.assertIn(s["kind"], {"seal", "heal_both", "heal_self", "hot",
                                      "atk_down", "def_down", "crit_zero", "dmg_up"})


if __name__ == "__main__":
    unittest.main()
