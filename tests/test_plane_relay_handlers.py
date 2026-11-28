import ast
import asyncio
import copy
import random
import sys
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import authority, extra_cultivation, plane, plane_relay
from core.player import PlayerDoc


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


def load_song_handler():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    fn = next(node for node in ast.walk(tree)
              if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_pr_song")
    fn.decorator_list = []
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), fn,
    ], type_ignores=[])
    namespace = {
        "AstrMessageEvent": object,
        "PlayerDoc": PlayerDoc,
        "authority_mod": authority,
        "plane": plane,
        "pr_mod": plane_relay,
        "time": SimpleNamespace(time=lambda: 100.0),
        "_uk_row": lambda buttons, **_kwargs: buttons,
        "_uk_btn": lambda *args, **kwargs: (args, kwargs),
    }
    exec(compile(ast.fix_missing_locations(module), str(MAIN_PATH), "exec"), namespace)
    return namespace["handle_pr_song"]


class FakeDB:
    def __init__(self, players):
        self.players = {uid: doc.model_dump() for uid, doc in players.items()}
        self.saved = []

    async def get_player(self, uid):
        return copy.deepcopy(self.players.get(str(uid)))

    async def save_player(self, player):
        saved = copy.deepcopy(player)
        self.saved.append(saved)
        self.players[str(saved["uid"])] = saved

    @asynccontextmanager
    async def transaction(self):
        yield


class PlaneRelayHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_songwang_opens_target_confirmation_offer(self):
        sender = PlayerDoc(uid="sender", name="仙王", ext={
            "plane": {"current": "凡间", "known": ["凡间", "仙界"],
                      "coords": {"仙界": {"x": 12, "y": 34}}},
        })
        target = PlayerDoc(uid="target", name="道友", ext={
            "plane": {"current": "凡间", "known": ["凡间"], "coords": {"凡间": {"x": 1, "y": 2}}},
        })
        db = FakeDB({"sender": sender, "target": target})

        class Host:
            def __init__(self):
                self.db = db
                self.lock = asyncio.Lock()

            def _allowed(self, _event):
                return True

            async def _require_player(self, _event):
                return sender, None

            def _at_target(self, _event):
                return "target"

            def _pl_lock(self, _uid):
                return self.lock

            async def _dead_planes(self):
                return {}

            def _kb(self, _event, _text, _row):
                return None

        event = SimpleNamespace(plain_result=lambda message: message)
        host = Host()
        with patch.object(authority, "authority_of", return_value=plane_relay.RELAY_AUTH), \
                patch.object(extra_cultivation, "realm_authority_level", return_value=plane_relay.RELAY_AUTH), \
                patch.object(plane_relay, "_destination_check", return_value=(True, "")):
            replies = [reply async for reply in load_song_handler()(host, event, "仙界")]

        self.assertEqual(len(replies), 1)
        self.assertIn("送往请求", replies[0])
        saved_target = await db.get_player("target")
        offer = saved_target["ext"]["plane"]["plane_offer"]
        self.assertEqual(offer["type"], "songwang")
        self.assertEqual(offer["plane"], "仙界")
        self.assertEqual(offer["coord"], {"x": 12, "y": 34})


if __name__ == "__main__":
    unittest.main()
