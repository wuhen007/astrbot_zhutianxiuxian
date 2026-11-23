import ast
import unittest
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.player import PlayerDoc


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"
NOW = 1_800_000_000


@cache
def shenpo_handler_code():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    plugin = next(node for node in tree.body
                  if isinstance(node, ast.ClassDef) and node.name == "ZhutianPlugin")
    handler = next(node for node in plugin.body
                   if isinstance(node, ast.AsyncFunctionDef) and node.name == "_shenpo_round")
    constants = [node for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id.startswith("SHENPO_")
                         for target in node.targets)]
    return compile(ast.Module(body=[*constants, handler], type_ignores=[]), str(MAIN_PATH), "exec")


def load_shenpo_handler(specs, harm):
    namespace = {"AstrMessageEvent": object, "boss": SimpleNamespace(shenpo_specs=specs),
                 "battle": SimpleNamespace(harm=harm), "time": SimpleNamespace(time=lambda: NOW)}
    exec(shenpo_handler_code(), namespace)
    return namespace["_shenpo_round"]


class ShenpoLimitsTests(unittest.IsolatedAsyncioTestCase):
    async def play(self, *, stage=0, one_shot=False, limit=20, zero_at=None,
                   defeat_at=None, last_attempt=0):
        doc = PlayerDoc(uid="shenpo-test", exp=10000,
                        ext={"shenpo": stage, "xueqi": 7, "shenpo_ts": last_attempt})
        save = AsyncMock()
        stages = []
        turns = 0

        def specs(seg):
            self.assertLessEqual(len(stages), limit, "started a challenge beyond the safe limit")
            stages.append(seg)
            return 10, 200, 50, 100

        def harm(atk, _defense, _rng):
            nonlocal turns
            if atk == 10:
                turns += 1
                self.assertLessEqual(turns, 1002, "exceeded the allowed number of combat turns")
                return (0 if len(stages) == zero_at else 10), False
            return (100 if len(stages) == defeat_at else 1), False

        host = SimpleNamespace(_require_player=AsyncMock(return_value=(doc, None)),
                               _stats=lambda _: SimpleNamespace(atk=10, defense=50, hp=100),
                               db=SimpleNamespace(save_player=save))
        event = SimpleNamespace(plain_result=lambda text: text)
        handler = load_shenpo_handler(specs, harm)

        replies = [reply async for reply in handler(host, event, one_shot=one_shot)]

        self.assertEqual(len(replies), 1)
        data = None
        if stages:
            save.assert_awaited_once()
            data = save.await_args.args[0]
            self.assertEqual(data["ext"]["shenpo_ts"], NOW)
        else:
            save.assert_not_awaited()
        return replies[0], data, stages, turns

    async def test_batch_stops_after_twenty_successes_and_persists_rewards(self):
        reply, data, stages, turns = await self.play()

        self.assertEqual(stages, [1, *range(5, 100, 5)])
        self.assertEqual(turns, 20)
        self.assertEqual(data["ext"]["shenpo"], 100)
        self.assertEqual(data["ext"]["xueqi"], 2007)
        self.assertEqual(data["exp"], 10000)
        self.assertIn("连破 20 段", reply)
        self.assertIn("本次连破已达上限", reply)

    async def test_single_challenge_only_plays_one_stage(self):
        reply, data, stages, turns = await self.play(one_shot=True, limit=1)

        self.assertEqual((stages, turns), ([1], 1))
        self.assertEqual(data["ext"]["shenpo"], 5)
        self.assertEqual(data["ext"]["xueqi"], 107)
        self.assertNotIn("本次连破已达上限", reply)

    async def test_stalled_stage_keeps_prior_rewards_without_defeat_penalty(self):
        reply, data, stages, turns = await self.play(zero_at=2, limit=2)

        self.assertEqual((stages, turns), ([1, 5], 1001))
        self.assertEqual(data["ext"]["shenpo"], 5)
        self.assertEqual(data["ext"]["xueqi"], 107)
        self.assertEqual(data["exp"], 10000)
        self.assertIn("1000 回合", reply)
        self.assertIn("未扣修为", reply)

    async def test_near_stage_cap_plays_no_extra_boss(self):
        reply, data, stages, turns = await self.play(stage=49998, limit=1)

        self.assertEqual((stages, turns), ([49998], 1))
        self.assertEqual(data["ext"]["shenpo"], 50000)
        self.assertEqual(data["ext"]["xueqi"], 107)
        self.assertIn("已臻圆满", reply)

    async def test_defeat_persists_prior_rewards_and_exp_penalty(self):
        reply, data, stages, turns = await self.play(defeat_at=2, limit=2)

        self.assertEqual((stages, turns), ([1, 5], 2))
        self.assertEqual(data["ext"]["shenpo"], 5)
        self.assertEqual(data["ext"]["xueqi"], 107)
        self.assertEqual(data["exp"], 9800)
        self.assertIn("修为 -200", reply)

    async def test_cooldown_does_not_play_or_save(self):
        reply, data, stages, turns = await self.play(last_attempt=NOW - 5, limit=0)

        self.assertEqual((data, stages, turns), (None, [], 0))
        self.assertIn("115 秒后再来", reply)
