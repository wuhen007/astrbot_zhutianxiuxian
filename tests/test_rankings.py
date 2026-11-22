import unittest

from core import rankings
from core.equipment import Stats
from core.player import PlayerDoc


class RankingsTests(unittest.TestCase):
    def test_cultivation_counts_prior_breakthroughs_and_displays_own_position(self):
        table = [{"level_id": 1, "level": "一境", "exp": 100},
                 {"level_id": 2, "level": "二境", "exp": 200}]
        players = [PlayerDoc(uid="private-a", name="甲", exp=90),
                   PlayerDoc(uid="private-b", name="乙", realm_index=1, exp=5)]
        text = rankings.board_text("天榜", players, "private-a", lambda _: table)
        self.assertIn("1. 乙（二境）｜总修为 105", text)
        self.assertIn("你的名次：第 2 名", text)
        self.assertNotIn("private-", text)

    def test_mortal_and_immortal_boards_use_original_boundary_and_weights(self):
        table = [{"level_id": i, "level": "无妄真劫境" if i == 41 else "地仙" if i == 42 else "凡境"}
                 for i in range(1, 43)]
        players = [PlayerDoc(uid="a", name="凡修", realm_index=40),
                   PlayerDoc(uid="b", name="仙修", realm_index=41)]
        def stats(_):
            return Stats(atk=100, defense=50, hp=200, bao=0.25)

        mortal = rankings.board_text("至尊榜", players, "b", lambda _: table, stats)
        self.assertIn("战力 325", mortal)
        self.assertNotIn("仙修", mortal)
        self.assertIn("你的名次：未上榜", mortal)
        immortal = rankings.board_text("封神榜", players, "b", lambda _: table, stats)
        self.assertIn("战力 437", immortal)
        self.assertNotIn("凡修", immortal)

    def test_balance_soul_and_demonic_boards_read_player_state(self):
        players = [
            PlayerDoc(uid="a", name="甲", stones=5000, ext={"legacy_source": {"神魄段数": 8}, "modao": 30}),
            PlayerDoc(uid="b", name="乙", stones=1000, ext={"shenpo": 12, "modao": 80}),
        ]
        for board, leader, score in (("灵榜", "甲", "灵石 5,000"),
                                     ("神魄榜", "乙", "神魄段数 12"),
                                     ("魔道榜", "乙", "魔道值 80")):
            with self.subTest(board=board):
                text = rankings.board_text(board, players, "a", lambda _: [])
                self.assertIn(f"1. {leader}｜{score}", text)
        self.assertIn("神魄段数 8", rankings.board_text("神魄榜", players, "a", lambda _: []))

    def test_immortal_ranking_uses_the_same_combat_formula_as_original(self):
        table = [{"level_id": i, "level": "凡境"} for i in range(1, 42)] + [
            {"level_id": 42, "level": "地仙"},
        ]
        doc = PlayerDoc(uid="immortal", name="仙修", realm_index=41)
        text = rankings.board_text("封神榜", [doc], "immortal", lambda _: table,
                                  lambda _: Stats(atk=100, defense=50, hp=200, bao=0.25))
        self.assertIn("仙修（地仙）｜战力 437", text)

    def test_otherworld_and_secret_rankings_keep_their_own_eligibility(self):
        table = [{"level_id": i, "level": f"境界{i}"} for i in range(1, 43)]
        players = [
            PlayerDoc(uid="xg", name="仙古", ext={"xiangu": {"shenhuo": {"已点燃": True}}}),
            PlayerDoc(uid="secret", name="秘境", ext={"legacy_source": {"mijinglevel_id": 2}}),
            PlayerDoc(uid="other", name="凡人"),
        ]
        stats = lambda _: Stats(atk=100, defense=50, hp=200, bao=0.25)
        perfect = rankings.board_text("完美世界榜", players, "xg", lambda _: table, stats)
        self.assertIn("仙古（神火境）｜战力 437", perfect)
        self.assertIn("凡人（搬血境）｜战力 437", perfect)
        zetian = rankings.board_text("遮天榜", players, "secret", lambda _: table, stats)
        self.assertIn("秘境（人体秘境 2）｜战力 437", zetian)
        self.assertNotIn("凡人", zetian)
