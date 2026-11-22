import ast
import asyncio
import random
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import MethodType, SimpleNamespace

from core import idle_proxy
from core.player import PlayerDoc
from infra.db import DataBase


class ZeroRandom:
    def random(self):
        return 0.0

    def randrange(self, start, stop):
        return 2


class MiningRandom:
    def __init__(self):
        self.values = iter((0.0, 0.2))

    def random(self):
        return next(self.values, 0.0)


class VeinRandom(ZeroRandom):
    pass


class IdleProxyTests(unittest.TestCase):
    def eligible_doc(self, *, realm_index=21):
        return PlayerDoc(uid="u1", name="药师", realm_index=realm_index, exp=20_000_000,
                         ext={"xueqi": 20_000_000, "occupation": "采药师",
                              "occupation_level": 1})

    def test_condense_spirit_checks_gate_and_spends_both_resources_once(self):
        doc = self.eligible_doc()
        ok, message, formed = idle_proxy.condense_spirit(doc)
        self.assertTrue(ok, message)
        self.assertEqual(formed.exp, 0)
        self.assertEqual(formed.ext["xueqi"], 0)
        self.assertEqual(idle_proxy.state_of(formed)["spirit"], {"tier": 1, "exp": 0, "task": None})
        again, _, unchanged = idle_proxy.condense_spirit(formed)
        self.assertFalse(again)
        self.assertEqual(unchanged.exp, formed.exp)

        low = self.eligible_doc(realm_index=3)
        low.exp = low.ext["xueqi"] = 50_000_000
        denied, _, untouched = idle_proxy.condense_spirit(low)
        self.assertFalse(denied)
        self.assertEqual((untouched.exp, untouched.ext["xueqi"]), (50_000_000, 50_000_000))

    def test_legacy_spirit_state_is_loaded_without_overwriting_source_archive(self):
        doc = self.eligible_doc()
        doc.ext["legacy_source"] = {"灵身": 2, "灵性": 4, "灵性经验": 75}
        state = idle_proxy.state_of(doc)
        self.assertEqual(state["spirit"], {"tier": 4, "exp": 75, "task": None})
        self.assertEqual(doc.ext["legacy_source"]["灵身"], 2)

    def test_duration_parser_defaults_converts_caps_and_rejects_invalid_input(self):
        self.assertEqual(idle_proxy.parse_duration(""), (120, False))
        self.assertEqual(idle_proxy.parse_duration("90分钟"), (90, False))
        self.assertEqual(idle_proxy.parse_duration("3小时"), (180, False))
        self.assertEqual(idle_proxy.parse_duration("3天"), (2880, True))
        for raw in ("0分钟", "-2小时", "abc"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                idle_proxy.parse_duration(raw)

    def test_herb_proxy_uses_original_formula_caps_elapsed_time_and_advances_spirit(self):
        doc = self.eligible_doc()
        ok, msg, doc = idle_proxy.condense_spirit(doc)
        self.assertTrue(ok, msg)
        ok, msg, doc = idle_proxy.start_herb_proxy(doc, 1_000, 480, "task-1")
        self.assertTrue(ok, msg)
        self.assertFalse(idle_proxy.start_herb_proxy(doc, 1_001, 15, "task-2")[0])

        ok, result, settled = idle_proxy.finish_herb_proxy(
            doc, 1_000 + 600 * 60, ZeroRandom(), [])
        self.assertTrue(ok, result)
        self.assertEqual(result["minutes"], 480)
        self.assertEqual(result["occupation_exp"], 48_000)
        self.assertEqual(result["items"], {
            "万年凝血草": 2, "万年何首乌": 3, "万年血精草": 2,
            "万年甜甜花": 2, "万年清心草": 2,
        })
        self.assertEqual(result["spirit_tier"], 1)
        self.assertIsNone(idle_proxy.state_of(settled)["spirit"]["task"])
        self.assertFalse(idle_proxy.finish_herb_proxy(settled, 1_000 + 600 * 60,
                                                      ZeroRandom(), [])[0])

    def test_finish_without_a_full_minute_clears_task_without_rewards(self):
        doc = self.eligible_doc()
        formed, _, doc = idle_proxy.condense_spirit(doc)
        self.assertTrue(formed)
        started = idle_proxy.start_herb_proxy(doc, 10_000, 120, "task-short")[2]
        ok, result, settled = idle_proxy.finish_herb_proxy(
            started, 10_059, random.Random(1), [])
        self.assertTrue(ok)
        self.assertEqual(result["items"], {})
        self.assertEqual(result["occupation_exp"], 0)
        self.assertIsNone(idle_proxy.state_of(settled)["spirit"]["task"])

    def test_high_realm_uses_the_original_rare_herb_pool(self):
        doc = self.eligible_doc(realm_index=35)
        doc.ext["idle_proxy"] = {"spirit": {"tier": 1, "exp": 0, "task": {
            "kind": "herb", "task_id": "rare", "started_at": 1_000.0,
            "ends_at": 29_800.0, "minutes": 480,
        }}}
        ok, result, _ = idle_proxy.finish_herb_proxy(doc, 1_000 + 480 * 60, ZeroRandom(), [])
        self.assertTrue(ok)
        self.assertEqual(set(result["items"]), set(idle_proxy.HERB_NAMES))
        self.assertEqual(result["items"]["太玄仙草"], 1)

    def test_mining_proxy_uses_source_rate_realm_and_spirit_multipliers(self):
        doc = self.eligible_doc()
        doc.ext["occupation"] = "采矿师"
        doc.ext["occupation_level"] = 10
        doc.ext["idle_proxy"] = {"spirit": {"tier": 1, "exp": 0, "task": {
            "kind": "mine", "task_id": "mine-1", "started_at": 1_000.0,
            "ends_at": 29_800.0, "minutes": 480,
        }}}
        exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        ok, result, settled = idle_proxy.finish_proxy(
            doc, 1_000 + 480 * 60, MiningRandom(), exp_table)
        self.assertTrue(ok)
        self.assertEqual(result["minutes"], 480)
        self.assertEqual(result["occupation_exp"], 48_000)
        self.assertEqual(result["items"], {
            "庚金": 11_499, "玄土": 11_499, "绿色石胚": 7,
        })
        self.assertIsNone(idle_proxy.state_of(settled)["spirit"]["task"])

    def test_hunt_proxy_uses_original_level_band_factor_and_fixed_prey_bundle(self):
        doc = self.eligible_doc(realm_index=24)
        doc.ext["occupation"] = "猎户"
        doc.ext["occupation_level"] = 10
        doc.ext["idle_proxy"] = {"spirit": {"tier": 1, "exp": 0, "task": {
            "kind": "hunt", "task_id": "hunt-1", "started_at": 1_000.0,
            "ends_at": 29_800.0, "minutes": 480,
        }}}
        exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        ok, result, settled = idle_proxy.finish_proxy(
            doc, 1_000 + 480 * 60, ZeroRandom(), exp_table)
        self.assertTrue(ok)
        self.assertEqual(result["items"], {
            "野兔": 234, "野猪": 234, "野牛": 234, "野鸡": 234, "野羊": 234,
        })
        self.assertEqual(result["occupation_exp"], 48_000)
        self.assertIsNone(idle_proxy.state_of(settled)["spirit"]["task"])

    def test_source_proxy_awards_legacy_item_tiers_not_source_currency(self):
        doc = self.eligible_doc()
        doc.ext["occupation"] = "源师"
        doc.ext["occupation_level"] = 10
        doc.ext["occupation_exp"] = 0
        doc.ext["yuanshi"] = {"amount": 123_456, "ledger": [{"test": "kept"}]}
        doc.ext["idle_proxy"] = {"spirit": {"tier": 1, "exp": 0, "task": {
            "kind": "source", "task_id": "source-1", "started_at": 1_000.0,
            "ends_at": 29_800.0, "minutes": 480,
        }}}
        exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        ok, result, settled = idle_proxy.finish_proxy(
            doc, 1_000 + 480 * 60, ZeroRandom(), exp_table)
        self.assertTrue(ok)
        self.assertEqual(result["occupation_exp"], 48_000)
        self.assertEqual(result["items"], {
            "下品源石": 15_681, "中品源石": 15_681, "上品源石": 188,
            "神源石": 92, "凡源药": 92,
        })
        self.assertEqual(settled.ext["yuanshi"], {"amount": 123_456, "ledger": [{"test": "kept"}]})
        self.assertIsNone(idle_proxy.state_of(settled)["spirit"]["task"])

    def test_earth_qi_proxy_uses_source_realm_band_and_three_source_stone_items(self):
        doc = self.eligible_doc()
        doc.ext["occupation"] = "源地师"
        doc.ext["occupation_level"] = 10
        doc.ext["yuanshi"] = {"amount": 654_321}
        doc.ext["idle_proxy"] = {"spirit": {"tier": 1, "exp": 0, "task": {
            "kind": "earth_qi", "task_id": "qi-1", "started_at": 1_000.0,
            "ends_at": 29_800.0, "minutes": 480,
        }}}
        exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        ok, result, settled = idle_proxy.finish_proxy(
            doc, 1_000 + 480 * 60, ZeroRandom(), exp_table)
        self.assertTrue(ok)
        self.assertEqual(result["occupation_exp"], 48_000)
        self.assertEqual(result["items"], {
            "上品源石": 206, "超品源石": 206, "神源石": 206, "地源药": 50,
        })
        self.assertEqual(settled.ext["yuanshi"]["amount"], 654_321)
        self.assertIsNone(idle_proxy.state_of(settled)["spirit"]["task"])

    def test_vein_proxy_uses_legacy_rate_factor_xueyuan_and_rare_essence(self):
        doc = self.eligible_doc()
        doc.ext["occupation"] = "源天师"
        doc.ext["occupation_level"] = 10
        doc.ext["occupation_exp"] = 0
        doc.ext["yuanshi"] = {"amount": 789_012}
        doc.ext["idle_proxy"] = {"spirit": {"tier": 1, "exp": 0, "task": {
            "kind": "vein", "task_id": "vein-1", "started_at": 1_000.0,
            "ends_at": 29_800.0, "minutes": 480,
        }}}
        exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        ok, result, settled = idle_proxy.finish_proxy(
            doc, 1_000 + 480 * 60, VeinRandom(), exp_table)
        self.assertTrue(ok)
        self.assertEqual(result["occupation_exp"], 9_600)
        self.assertEqual(result["items"], {
            "超品源石": 5_544, "上品神源石": 3_294, "神源液": 3_294,
            "超品神源石": 1_087, "神源药": 1_087, "龙脉精华": 1,
        })
        self.assertEqual(settled.ext["yuanshi"]["amount"], 789_012)

    def test_deity_gate_migrates_legacy_tier_and_keeps_tasks_separate_from_spirit(self):
        doc = self.eligible_doc(realm_index=12)
        doc.ext["occupation"] = "采药师"
        doc.ext["legacy_source"] = {"神祇": 2, "神祇经验": 35, "神祇重伤至": 0}
        deity = idle_proxy.deity_state_of(doc)
        self.assertEqual((deity["tier"], deity["exp"]), (2, 35))

        formed, _, unchanged = idle_proxy.condense_deity(doc)
        self.assertFalse(formed)
        self.assertEqual(unchanged.exp, doc.exp)
        low = self.eligible_doc(realm_index=11)
        low.ext["occupation"] = "采药师"
        self.assertFalse(idle_proxy.condense_deity(low)[0])

        fresh = self.eligible_doc(realm_index=12)
        fresh.ext["occupation"] = "采药师"
        formed, _, fresh = idle_proxy.condense_deity(fresh)
        self.assertTrue(formed)
        fresh.ext["idle_proxy"]["spirit"] = {"tier": 1, "exp": 0, "task": None}
        spirit_started = idle_proxy.start_proxy(fresh, 1_000, 60, "spirit-task", "herb")[2]
        deity_started = idle_proxy.start_deity_herb_proxy(
            spirit_started, 1_001, 60, "deity-task")[2]
        self.assertEqual(idle_proxy.state_of(deity_started)["spirit"]["task"]["task_id"], "spirit-task")
        self.assertEqual(idle_proxy.deity_state_of(deity_started)["task"]["task_id"], "deity-task")

    def test_deity_herb_rewards_and_progress_use_deity_factor(self):
        doc = self.eligible_doc(realm_index=21)
        doc.ext["occupation"] = "采药师"
        doc.ext["occupation_level"] = 1
        doc.ext["idle_proxy"] = {"spirit": {"tier": 0, "exp": 0, "task": None},
                                 "deity": {"tier": 1, "exp": 0, "injured_until": 0, "task": {
                                     "kind": "herb", "task_id": "deity-herb", "started_at": 1_000,
                                     "ends_at": 29_800, "minutes": 480, "group_id": "g1"}}}
        exp_table = [{"id": 1, "rate": 0.1, "experience": 1_000_000}]
        ok, result, settled = idle_proxy.finish_deity_herb_proxy(
            doc, 1_000 + 480 * 60, ZeroRandom(), exp_table)
        self.assertTrue(ok)
        self.assertEqual(result["factor"], 0.55)
        self.assertEqual(result["occupation_exp"], 48_000)
        self.assertEqual(result["items"], {
            "万年凝血草": 2, "万年何首乌": 3, "万年血精草": 2,
            "万年甜甜花": 2, "万年清心草": 2,
        })
        self.assertIsNone(idle_proxy.deity_state_of(settled)["task"])
        self.assertIsNone(idle_proxy.state_of(settled)["spirit"]["task"])

    def test_deity_mining_uses_deity_multiplier_and_leaves_spirit_progress_unchanged(self):
        doc = self.eligible_doc()
        doc.ext["occupation"] = "采矿师"
        doc.ext["occupation_level"] = 10
        doc.ext["idle_proxy"] = {
            "spirit": {"tier": 2, "exp": 77, "task": None},
            "deity": {"tier": 1, "exp": 15, "injured_until": 0, "task": {
                "kind": "mine", "task_id": "deity-mine", "started_at": 1_000.0,
                "ends_at": 29_800.0, "minutes": 480,
            }},
        }
        exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        ok, result, settled = idle_proxy.finish_deity_proxy(
            doc, 1_000 + 480 * 60, MiningRandom(), exp_table)
        self.assertTrue(ok)
        self.assertEqual(result["factor"], 0.55)
        self.assertEqual(result["items"], {
            "庚金": 11_499, "玄土": 11_499, "绿色石胚": 7,
        })
        self.assertEqual(idle_proxy.state_of(settled)["spirit"],
                         {"tier": 2, "exp": 77, "task": None})
        self.assertEqual(idle_proxy.deity_state_of(settled)["exp"], 495)


def command_handlers():
    plugin_root = Path(__file__).resolve().parents[1]
    tree = ast.parse((plugin_root / "main.py").read_text(encoding="utf-8"))
    wanted = {"handle_condense_spirit", "handle_spirit_proxy",
              "handle_finish_spirit_proxy", "handle_condense_deity",
              "handle_deity_proxy", "handle_finish_deity_proxy"}
    methods = [node for node in ast.walk(tree)
               if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted]
    for method in methods:
        method.decorator_list = []
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *methods,
    ], type_ignores=[])
    from core import occupation as occupation_mod
    env = {"PlayerDoc": PlayerDoc, "idle_proxy_mod": idle_proxy,
           "occupation": occupation_mod, "random": random, "time": __import__("time"),
           "secrets": __import__("secrets"), "CMD_SPIRIT_PROXY": "#灵身代行采药",
           "CMD_DEITY_PROXY": "#神祇代行采药",
           "CMD_DEITY_MINE_PROXY": "#神祇代行采矿",
           "CMD_DEITY_HUNT_PROXY": "#神祇代行狩猎"}
    exec(compile(ast.fix_missing_locations(module), "main.py:idle-proxy-handlers", "exec"), env)
    return {name: env[name] for name in wanted if name in env}


class IdleProxyHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = DataBase(Path(self.temp.name) / "idle-proxy.sqlite")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        self.locks = {}
        self.host = SimpleNamespace(db=self.db, _allowed=lambda event: True, occ_exp_table=[])

        def pl_lock(uid):
            return self.locks.setdefault(str(uid), asyncio.Lock())

        async def require_player(event):
            raw = await self.db.get_player(event.get_sender_id())
            return (PlayerDoc(**raw), None) if raw else (None, "missing")

        self.host._pl_lock = pl_lock
        self.host._require_player = require_player
        self.host._msg_of = lambda event: event.message_str
        for name, method in command_handlers().items():
            setattr(self.host, name, MethodType(method, self.host))
        self.assertTrue(hasattr(self.host, "handle_condense_spirit"))
        self.assertTrue(hasattr(self.host, "handle_spirit_proxy"))
        self.assertTrue(hasattr(self.host, "handle_finish_spirit_proxy"))
        self.assertTrue(hasattr(self.host, "handle_condense_deity"))
        self.assertTrue(hasattr(self.host, "handle_deity_proxy"))
        self.assertTrue(hasattr(self.host, "handle_finish_deity_proxy"))

    @staticmethod
    def event(uid, message, group="g1"):
        return SimpleNamespace(message_str=message,
                               get_sender_id=lambda: uid,
                               get_group_id=lambda: group,
                               plain_result=lambda text: text)

    async def invoke(self, uid, message, handler):
        async with self.host._pl_lock(uid):
            return [result async for result in getattr(self.host, handler)(self.event(uid, message))]

    async def test_settlement_survives_restart_and_second_end_does_not_duplicate_rewards(self):
        doc = PlayerDoc(uid="u1", name="药师", realm_index=21, exp=20_000_000,
                        ext={"xueqi": 20_000_000, "occupation": "采药师",
                             "occupation_level": 1})
        await self.db.save_player(doc.model_dump())
        await self.invoke("u1", "#凝聚洞天灵身", "handle_condense_spirit")
        await self.invoke("u1", "#灵身代行采药 480分钟", "handle_spirit_proxy")
        raw = await self.db.get_player("u1")
        raw["ext"]["idle_proxy"]["spirit"]["task"]["started_at"] -= 480 * 60
        await self.db.save_player(raw)

        restarted = SimpleNamespace(**vars(self.host))
        for name, method in command_handlers().items():
            setattr(restarted, name, MethodType(method, restarted))
        self.host = restarted
        self.host._pl_lock = lambda uid: self.locks.setdefault(str(uid), asyncio.Lock())
        first = await self.invoke("u1", "#结束灵身代行", "handle_finish_spirit_proxy")
        inventory = await self.db.get_inventory("u1")
        self.assertTrue(inventory)
        self.assertTrue(any("采药归来" in str(line) for line in first))
        saved = await self.db.get_player("u1")
        self.assertIsNone(saved["ext"]["idle_proxy"]["spirit"]["task"])
        self.assertEqual(saved["ext"]["occupation_exp"], 48_000)

        second = await self.invoke("u1", "#结束灵身代行", "handle_finish_spirit_proxy")
        self.assertEqual(await self.db.get_inventory("u1"), inventory)
        self.assertTrue(any("没有等待结算" in str(line) for line in second))

    async def test_mining_route_persists_and_settles_mining_materials(self):
        doc = PlayerDoc(uid="u3", name="矿师", realm_index=21,
                        ext={"occupation": "采矿师", "occupation_level": 10,
                             "occupation_exp": 0,
                             "idle_proxy": {"spirit": {"tier": 1, "exp": 0, "task": None}}})
        await self.db.save_player(doc.model_dump())
        self.host.occ_exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        await self.invoke("u3", "#灵身代行采矿 480分钟", "handle_spirit_proxy")
        raw = await self.db.get_player("u3")
        raw["ext"]["idle_proxy"]["spirit"]["task"]["started_at"] -= 480 * 60
        await self.db.save_player(raw)

        await self.invoke("u3", "#结束灵身代行", "handle_finish_spirit_proxy")
        inventory = await self.db.get_inventory("u3")
        self.assertGreater(inventory.get("庚金", 0), 0)
        self.assertGreater(inventory.get("玄土", 0), 0)
        saved = await self.db.get_player("u3")
        self.assertEqual(saved["ext"]["occupation_exp"], 48_000)

    async def test_hunt_route_persists_and_settles_food_bundle(self):
        doc = PlayerDoc(uid="u4", name="猎户", realm_index=24,
                        ext={"occupation": "猎户", "occupation_level": 10,
                             "idle_proxy": {"spirit": {"tier": 1, "exp": 0, "task": None}}})
        await self.db.save_player(doc.model_dump())
        self.host.occ_exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        await self.invoke("u4", "#灵身代行狩猎 480分钟", "handle_spirit_proxy")
        raw = await self.db.get_player("u4")
        raw["ext"]["idle_proxy"]["spirit"]["task"]["started_at"] -= 480 * 60
        await self.db.save_player(raw)

        await self.invoke("u4", "#结束灵身代行", "handle_finish_spirit_proxy")
        inventory = await self.db.get_inventory("u4")
        self.assertEqual({name: inventory[name] for name in ("野兔", "野猪", "野牛", "野鸡", "野羊")},
                         {name: 234 for name in ("野兔", "野猪", "野牛", "野鸡", "野羊")})

    async def test_source_route_awards_items_without_crediting_source_wallet(self):
        doc = PlayerDoc(uid="u5", name="源师", realm_index=21,
                        ext={"occupation": "源师", "occupation_level": 10,
                             "yuanshi": {"amount": 321},
                             "idle_proxy": {"spirit": {"tier": 1, "exp": 0, "task": None}}})
        await self.db.save_player(doc.model_dump())
        self.host.occ_exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        await self.invoke("u5", "#灵身代行寻源 480分钟", "handle_spirit_proxy")
        raw = await self.db.get_player("u5")
        raw["ext"]["idle_proxy"]["spirit"]["task"]["started_at"] -= 480 * 60
        await self.db.save_player(raw)

        await self.invoke("u5", "#结束灵身代行", "handle_finish_spirit_proxy")
        inventory = await self.db.get_inventory("u5")
        self.assertGreater(inventory["下品源石"], 0)
        self.assertGreater(inventory["神源石"], 0)
        saved = await self.db.get_player("u5")
        self.assertEqual(saved["ext"]["yuanshi"]["amount"], 321)

    async def test_earth_qi_route_awards_only_inventory_items(self):
        doc = PlayerDoc(uid="u6", name="源地师", realm_index=21,
                        ext={"occupation": "源地师", "occupation_level": 10,
                             "yuanshi": {"amount": 654_321},
                             "idle_proxy": {"spirit": {"tier": 1, "exp": 0, "task": None}}})
        await self.db.save_player(doc.model_dump())
        self.host.occ_exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        await self.invoke("u6", "#灵身代行地脉引气 480分钟", "handle_spirit_proxy")
        raw = await self.db.get_player("u6")
        raw["ext"]["idle_proxy"]["spirit"]["task"]["started_at"] -= 480 * 60
        await self.db.save_player(raw)

        await self.invoke("u6", "#结束灵身代行", "handle_finish_spirit_proxy")
        inventory = await self.db.get_inventory("u6")
        self.assertEqual(inventory["上品源石"], 206)
        self.assertEqual(inventory["地源药"], 50)
        saved = await self.db.get_player("u6")
        self.assertEqual(saved["ext"]["yuanshi"]["amount"], 654_321)

    async def test_vein_route_awards_items_and_special_drop_without_wallet_credit(self):
        doc = PlayerDoc(uid="u7", name="源天师", realm_index=21,
                        ext={"occupation": "源天师", "occupation_level": 10,
                             "occupation_exp": 0, "yuanshi": {"amount": 789_012},
                             "idle_proxy": {"spirit": {"tier": 1, "exp": 0, "task": None}}})
        await self.db.save_player(doc.model_dump())
        self.host.occ_exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        await self.invoke("u7", "#灵身代行寻脉定源 480分钟", "handle_spirit_proxy")
        raw = await self.db.get_player("u7")
        raw["ext"]["idle_proxy"]["spirit"]["task"]["started_at"] -= 480 * 60
        await self.db.save_player(raw)

        await self.invoke("u7", "#结束灵身代行", "handle_finish_spirit_proxy")
        inventory = await self.db.get_inventory("u7")
        self.assertGreater(inventory["超品源石"], 0)
        self.assertTrue(any(name in inventory for name in ("龙脉精华", "超品神源石")))
        saved = await self.db.get_player("u7")
        self.assertEqual(saved["ext"]["occupation_exp"], 9_600)
        self.assertEqual(saved["ext"]["yuanshi"]["amount"], 789_012)

    async def test_deity_herb_commands_form_start_and_settle(self):
        doc = PlayerDoc(uid="u8", name="药师", realm_index=12, exp=20_000_000,
                        ext={"xueqi": 20_000_000, "occupation": "采药师",
                             "occupation_level": 1, "occupation_exp": 0})
        await self.db.save_player(doc.model_dump())
        await self.invoke("u8", "#凝聚道宫神祇", "handle_condense_deity")
        await self.invoke("u8", "#神祇代行采药 480分钟", "handle_deity_proxy")
        raw = await self.db.get_player("u8")
        raw["ext"]["idle_proxy"]["deity"]["task"]["started_at"] -= 480 * 60
        await self.db.save_player(raw)

        result = await self.invoke("u8", "#结束神祇代行", "handle_finish_deity_proxy")
        inventory = await self.db.get_inventory("u8")
        self.assertTrue(inventory)
        self.assertTrue(any("神祇采药归来" in str(line) for line in result))
        saved = await self.db.get_player("u8")
        self.assertEqual(saved["ext"]["occupation_exp"], 48_000)
        self.assertIsNone(idle_proxy.deity_state_of(PlayerDoc(**saved))["task"])

    async def test_deity_mining_route_awards_minerals_and_advances_only_deity_tier(self):
        doc = PlayerDoc(uid="u9", name="矿师", realm_index=21,
                        ext={"occupation": "采矿师", "occupation_level": 10,
                             "occupation_exp": 0,
                             "idle_proxy": {"spirit": {"tier": 3, "exp": 90, "task": None},
                                 "deity": {"tier": 1, "exp": 0, "injured_until": 0, "task": None}}})
        await self.db.save_player(doc.model_dump())
        self.host.occ_exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        await self.invoke("u9", "#神祇代行采矿 480分钟", "handle_deity_proxy")
        raw = await self.db.get_player("u9")
        raw["ext"]["idle_proxy"]["deity"]["task"]["started_at"] -= 480 * 60
        await self.db.save_player(raw)

        await self.invoke("u9", "#结束神祇代行", "handle_finish_deity_proxy")
        saved = await self.db.get_player("u9")
        inventory = await self.db.get_inventory("u9")
        self.assertGreater(inventory.get("庚金", 0), 0)
        self.assertEqual(saved["ext"]["occupation_exp"], 48_000)
        self.assertEqual(idle_proxy.deity_state_of(PlayerDoc(**saved))["exp"], 480)
        self.assertEqual(idle_proxy.state_of(PlayerDoc(**saved))["spirit"],
                         {"tier": 3, "exp": 90, "task": None})

    async def test_deity_hunt_route_awards_food_and_advances_only_deity_progress(self):
        foods = ("野兔", "野猪", "野牛", "野鸡", "野羊")
        doc = PlayerDoc(uid="u10", name="猎户", realm_index=24,
                        ext={"occupation": "猎户", "occupation_level": 10,
                             "occupation_exp": 0,
                             "idle_proxy": {"spirit": {"tier": 2, "exp": 90, "task": None},
                                 "deity": {"tier": 1, "exp": 0, "injured_until": 0, "task": None}}})
        await self.db.save_player(doc.model_dump())
        self.host.occ_exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        started = await self.invoke("u10", "#神祇代行狩猎 480分钟", "handle_deity_proxy")
        self.assertTrue(any("神祇代行狩猎启程" in str(line) for line in started))
        raw = await self.db.get_player("u10")
        raw["ext"]["idle_proxy"]["deity"]["task"]["started_at"] -= 480 * 60
        await self.db.save_player(raw)

        result = await self.invoke("u10", "#结束神祇代行", "handle_finish_deity_proxy")
        inventory = await self.db.get_inventory("u10")
        self.assertEqual({name: inventory[name] for name in foods}, {name: 234 for name in foods})
        saved = await self.db.get_player("u10")
        saved_doc = PlayerDoc(**saved)
        self.assertEqual(saved["ext"]["occupation_exp"], 48_000)
        self.assertEqual(idle_proxy.deity_state_of(saved_doc)["exp"], 480)
        self.assertEqual(idle_proxy.state_of(saved_doc)["spirit"],
                         {"tier": 2, "exp": 90, "task": None})
        self.assertIsNone(idle_proxy.deity_state_of(saved_doc)["task"])
        self.assertTrue(any("神祇狩猎归来" in str(line) for line in result))

    async def test_deity_source_route_awards_source_items_and_advances_only_deity_progress(self):
        doc = PlayerDoc(uid="u11", name="源师", realm_index=21,
                        ext={"occupation": "源师", "occupation_level": 10,
                             "occupation_exp": 0, "yuanshi": {"amount": 321},
                             "idle_proxy": {"spirit": {"tier": 2, "exp": 77, "task": None},
                                 "deity": {"tier": 1, "exp": 0, "injured_until": 0, "task": None}}})
        await self.db.save_player(doc.model_dump())
        self.host.occ_exp_table = [{"id": 10, "rate": 1.0, "experience": 1_000_000}]
        with mock.patch.object(random, "Random", return_value=ZeroRandom()):
            started = await self.invoke("u11", "#神祇代行寻源 480分钟", "handle_deity_proxy")
        self.assertTrue(any("神祇代行寻源启程" in str(line) for line in started))
        raw = await self.db.get_player("u11")
        raw["ext"]["idle_proxy"]["deity"]["task"]["started_at"] -= 480 * 60
        await self.db.save_player(raw)

        with mock.patch.object(random, "Random", return_value=ZeroRandom()):
            result = await self.invoke("u11", "#结束神祇代行", "handle_finish_deity_proxy")
        inventory = await self.db.get_inventory("u11")
        self.assertEqual({name: inventory[name] for name in ("下品源石", "中品源石", "上品源石", "神源石", "凡源药")},
                         {"下品源石": 15_681, "中品源石": 15_681, "上品源石": 188,
                          "神源石": 92, "凡源药": 92})
        saved = await self.db.get_player("u11")
        saved_doc = PlayerDoc(**saved)
        self.assertEqual(saved["ext"]["occupation_exp"], 48_000)
        self.assertEqual(idle_proxy.deity_state_of(saved_doc)["exp"], 480)
        self.assertEqual(idle_proxy.state_of(saved_doc)["spirit"],
                         {"tier": 2, "exp": 77, "task": None})
        self.assertIsNone(idle_proxy.deity_state_of(saved_doc)["task"])
        self.assertEqual(saved["ext"]["yuanshi"]["amount"], 321)
        self.assertTrue(any("神祇寻源归来" in str(line) for line in result))

    async def test_failed_inventory_write_rolls_back_task_and_experience(self):
        doc = PlayerDoc(uid="u2", name="药师", realm_index=21,
                        ext={"occupation": "采药师", "occupation_level": 1,
                             "idle_proxy": {"spirit": {"tier": 1, "exp": 0,
                                 "task": {"kind": "herb", "task_id": "tx-fail",
                                          "started_at": 1.0, "ends_at": 28_801.0,
                                          "minutes": 480, "group_id": "g1"}}}})
        await self.db.save_player(doc.model_dump())
        original = self.db.add_items

        async def fail_add_items(uid, items):
            raise RuntimeError("inventory write failed")

        self.db.add_items = fail_add_items
        with self.assertRaisesRegex(RuntimeError, "inventory write failed"):
            await self.invoke("u2", "#结束灵身代行", "handle_finish_spirit_proxy")
        self.db.add_items = original
        saved = await self.db.get_player("u2")
        self.assertEqual(saved["ext"].get("occupation_exp", 0), 0)
        self.assertEqual(saved["ext"]["idle_proxy"]["spirit"]["task"]["task_id"], "tx-fail")
        self.assertEqual(await self.db.get_inventory("u2"), {})


if __name__ == "__main__":
    unittest.main()
