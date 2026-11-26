"""Exercise the real blessing handler and SQLite; AstrBot event delivery is a test double."""
import ast
import asyncio
from pathlib import Path
import sys
import tempfile
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.player import PlayerDoc
from core import sect_extra as se_mod, sect_deep as sec_mod
from infra.db import DataBase


def handler_methods():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8'))
    names = {'_sec_open', '_sec_flush', 'handle_sec_bless'}
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
    for node in nodes:
        node.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    env = {'se_mod': se_mod, 'sec_mod': sec_mod,
           'time': types.SimpleNamespace(time=lambda: 1800000000.0),
           'random': types.SimpleNamespace(Random=lambda seed: types.SimpleNamespace(random=lambda: .99))}
    exec(compile(ast.fix_missing_locations(module), 'main.py:extracted-blessing-methods', 'exec'), env)
    return {name: env[name] for name in names}


class BlessHandlerRegression(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = DataBase(Path(self.tmp.name) / 'game.db')
        self.addAsyncCleanup(self.db.close)
        await self.db.connect()
        for uid in ('A', 'B'):
            await self.db.save_player(PlayerDoc(uid=uid, ext={'sect': 'test'}).model_dump())
        await self.db.create_sect('test', 'A', 1800000000.0)
        await self.db.update_sect('test', 5, 100000)
        cal = {}
        state = sec_mod.state_of(cal, 'test')
        state['beast'] = '青龙'
        sec_mod.commit(cal, 'test', state)
        await self.db.save_calamity(cal)
        pools = {
            'item/丹药列表': [],
            'item/功法列表': [],
            'item/装备列表': [],
            'Timelimit/麒麟': [],
            'Timelimit/青龙': [{'name': '限定青龙功法', 'class': '功法', '稀有度': 4}],
            'Timelimit/玄武朱雀白虎': [],
        }
        self.host = types.SimpleNamespace(
            db=self.db, _allowed=lambda event: True,
            content=types.SimpleNamespace(table=lambda name: pools.get(name, [])))
        async def require(event):
            return PlayerDoc(**await self.db.get_player(event.uid)), None
        self.host._require_player = require
        for name, fn in handler_methods().items():
            setattr(self.host, name, types.MethodType(fn, self.host))

    async def invoke(self, uid):
        event = types.SimpleNamespace(uid=uid, plain_result=lambda msg: msg)
        return [msg async for msg in self.host.handle_sec_bless(event)]

    async def test_concurrent_members_persist_only_one_reward_each(self):
        await asyncio.gather(self.invoke('A'), self.invoke('A'), self.invoke('B'))
        self.assertEqual((await self.db.get_sect('test'))['fund'], 100000)
        for uid in ('A', 'B'):
            self.assertEqual(await self.db.get_inventory(uid), {'限定青龙功法': 1})
            self.assertIn('beast_bless_day', (await self.db.get_player(uid))['ext'])

    async def test_item_failure_rolls_back_mark_fund_and_reward(self):
        async def fail(uid, items):
            raise RuntimeError('injected inventory write failure')
        self.db.add_items = fail
        with self.assertRaisesRegex(RuntimeError, 'injected inventory'):
            await self.invoke('A')
        self.assertEqual((await self.db.get_sect('test'))['fund'], 100000)
        self.assertNotIn('beast_bless_day', (await self.db.get_player('A'))['ext'])
        self.assertEqual(await self.db.get_inventory('A'), {})


if __name__ == '__main__':
    unittest.main()
