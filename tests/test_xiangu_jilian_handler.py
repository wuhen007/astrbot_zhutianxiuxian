import ast
import random as std_random
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import (dao_heart, memory, trib, xiangu, xiangu_dao,
                  xiangu_tribulation)
from core.player import PlayerDoc


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


class _ImportRewriter(ast.NodeTransformer):
    MODULES = {
        "xiangu_tribulation": "wave_defense_mod",
        "memory": "trib_memory_mod",
        "dao_heart": "dao_heart_mod",
        "trib": "trib_mod",
    }

    def visit_ImportFrom(self, node):
        if node.level == 1 and node.module == "core":
            assigns = []
            for alias in node.names:
                local_name = self.MODULES[alias.name]
                assigns.append(ast.Assign(
                    targets=[ast.Name(id=local_name, ctx=ast.Store())],
                    value=ast.Name(id=alias.name, ctx=ast.Load())))
            return assigns
        return node


def load_jilian_handler():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    handler = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.AsyncFunctionDef)
                   and node.name == "handle_xgd_jilian")
    handler.decorator_list = []
    handler = _ImportRewriter().visit(handler)
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        handler,
    ], type_ignores=[])
    namespace = {
        "AstrMessageEvent": object,
        "PlayerDoc": PlayerDoc,
        "CMD_REVIVE_SELECT": "#复活选择",
        "asyncio": __import__("asyncio"),
        "dao_heart": dao_heart,
        "memory": memory,
        "random": SimpleNamespace(Random=lambda *_args: std_random.Random(0)),
        "time": SimpleNamespace(time=lambda: 1_000.0),
        "trib": trib,
        "xiangu": xiangu,
        "xgm_mod": xiangu,
        "xdd_mod": xiangu_dao,
        "xiangu_dao": xiangu_dao,
        "xiangu_tribulation": xiangu_tribulation,
    }
    exec(compile(ast.fix_missing_locations(module), str(MAIN_PATH), "exec"), namespace)
    return namespace["handle_xgd_jilian"]


class XianguJilianHandlerTests(unittest.IsolatedAsyncioTestCase):
    def make_host(self, *, start_realm=30):
        doc = PlayerDoc(uid="jilian", name="祭炼者", realm_index=start_realm,
                        exp=500_000, ext={
                            "potential": 50, "hp": 900_000, "hp_max": 900_000,
                            "xueqi": 500_000, "xueqi_max": 1_200_000,
                        })
        state = xiangu.state_of(doc)
        state["active"] = True
        state["map"] = xiangu.new_run_map("handler-test")
        state["map"]["fragment_id"] = "flame_abyss"
        state["gains"]["daoyun"] = 600
        saved = []

        class Host:
            def __init__(self):
                self._xiangu_revives = {}

            def _allowed(self, _event):
                return True

            async def _require_player(self, _event):
                return doc, None

            def _stats(self, _doc):
                return SimpleNamespace(hp=900_000)

            async def _pe_save(self, actual_doc, delta):
                saved.append((actual_doc.model_copy(deep=True), dict(delta or {})))

            async def _smart(self, _event, text, _title=""):
                yield text

        return Host(), doc, saved

    async def test_jilian_executes_each_wave_and_awards_only_after_success(self):
        host, _doc, saved = self.make_host()
        calls = []
        event = SimpleNamespace(plain_result=lambda text: text)

        def light_damage(_doc, _raw, _rng):
            calls.append(1)
            return {"damage": 1, "messages": [], "adaptations": []}

        with patch.object(xiangu_tribulation, "apply_wave_defenses", side_effect=light_damage):
            result = [row async for row in load_jilian_handler()(host, event)]

        self.assertGreaterEqual(len(calls), 10)
        self.assertEqual(len(saved), 1)
        self.assertEqual(xiangu_dao.shenhuo_of(xiangu.state_of(saved[0][0]))["神火品质"], "唯一")
        self.assertEqual(saved[0][1], {"草字剑诀": 1})
        self.assertTrue(any("天地共鸣" in text for text in result))

    async def test_jilian_manual_revival_waits_for_the_selected_skill(self):
        host, doc, saved = self.make_host()
        doc.ext["life_source"] = 50
        doc.ext["gongfa"] = ["柳神法"]
        doc.ext["trib_revive_mode"] = "手动"
        sent = []
        calls = []

        class Plain:
            def __init__(self, text):
                self.text = text

        class MessageChain:
            def __init__(self, chain):
                self.chain = chain

        event_module = __import__("types").ModuleType("astrbot.api.event")
        event_module.MessageChain = MessageChain
        event_module.Plain = Plain
        astrbot_module = __import__("types").ModuleType("astrbot")
        astrbot_module.__path__ = []
        api_module = __import__("types").ModuleType("astrbot.api")
        api_module.__path__ = []

        async def send(chain):
            sent.append(chain.chain[0].text)
            host._xiangu_revives[doc.uid]["future"].set_result("柳神法")

        event = SimpleNamespace(plain_result=lambda text: text, send=send)

        def first_wave_lethal_then_survive(_doc, raw, _rng):
            calls.append(raw)
            damage = 2_000_000 if len(calls) == 1 else 1
            return {"damage": damage, "messages": [], "adaptations": []}

        modules = {"astrbot": astrbot_module, "astrbot.api": api_module,
                   "astrbot.api.event": event_module}
        with patch.object(xiangu_tribulation, "apply_wave_defenses",
                          side_effect=first_wave_lethal_then_survive), \
                patch.dict("sys.modules", modules):
            result = [row async for row in load_jilian_handler()(host, event)]

        self.assertTrue(sent)
        self.assertIn("#复活选择", sent[0])
        self.assertEqual(doc.ext["life_source"], 0)
        self.assertGreaterEqual(len(calls), 10)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0][1], {"草字剑诀": 1})
        self.assertTrue(any("柳神法" in text for text in result))

    async def test_jilian_failure_applies_original_drop_and_restoration_without_reward(self):
        host, _doc, saved = self.make_host()
        event = SimpleNamespace(plain_result=lambda text: text)

        def lethal(_doc, raw, _rng):
            return {"damage": raw + 1_000_000, "messages": [], "adaptations": []}

        with patch.object(xiangu_tribulation, "apply_wave_defenses", side_effect=lethal):
            result = [row async for row in load_jilian_handler()(host, event)]

        self.assertEqual(len(saved), 1)
        failed = saved[0][0]
        self.assertEqual(failed.realm_index, 29)
        self.assertEqual(failed.ext["hp"], 900_000)
        self.assertEqual(failed.ext["xueqi"], 1_200_000)
        self.assertFalse(saved[0][1])
        self.assertFalse(failed.ext.get("shenhuo", {}).get("已点燃"))
        self.assertTrue(any("未能令三千道火归一" in text for text in result))


if __name__ == "__main__":
    unittest.main()
