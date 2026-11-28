"""Restart-safe #洗劫 state machine ported from the pinned original JS snapshot."""
from __future__ import annotations
import copy
import json
import random
import re
import secrets
import time
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo
from . import adventure, dao_heart, flower, linggen, story_npc, suiyun, timed_action, xtzb
from .authority import authority_21, authority_of

# Original: apps/Xijie/Xijie.js, Xijietask.js, Taopaotask.js,
# ShopGradetask.js, Shoptask.js (04af6a9a7ec11e700a0aedb85a5981e48826035c).
SHOP_LOCK_SECONDS = 4 * 3600
RAID_COOLDOWN_SECONDS = 2 * 3600
SKY_COOLDOWN_SECONDS = 3600
PREPARATION_ACTION_MINUTES = 15
PREPARATION_BATTLE_MINUTES = 10
LOOT_SEARCH_MINUTES = 5          # Xijietask's end_time - time + 5m trigger.
PURSUIT_FIRST_DELAY_SECONDS = 5 * 60  # Taopaotask's actual first trigger.
PURSUIT_TICK_SECONDS = 60       # Original task runs once per minute.
PURSUIT_NOMINAL_MINUTES = 30    # Original escape action.time.
GUARD_JAIL_MINUTES = 60
PURSUIT_JAIL_MINUTES = 120
DAO_HEART_PENALTY = 20
MODAO_PER_GRADE = 25
LOOT_SLOTS_PER_GRADE = 2
PANGU_LOOT_MULTIPLIER = 2
GUARD_DEFENSE_HP_GRADE_RATE = .05
IMPERIAL_REALM_REQUIREMENTS = {"mijinglevel_id": 16, "huafenlevel_id": 16, "xiangulevel_id": 15}
SEALED_TECHNIQUES = ("临字秘", "皆字秘", "一气化三清")
SHANGHAI = ZoneInfo("Asia/Shanghai")
WEEKLY_REFRESH_DAYS = frozenset((1, 3, 5, 7))  # Source comment: Mon/Wed/Fri/Sun.
ROOT_LAW_MITIGATION = (
 (re.compile(r"先天混沌圣体道胎|混沌圣体道胎"), .50),
 (re.compile(r"彼岸.*命运神道体"), .50),
 (re.compile(r"天命青儿|始源之律者.*爱莉希雅"), .48),
 (re.compile(r"终焉神魔体|无相.*万化天魔体|无化天魔体"), .46),
 (re.compile(r"终极涅槃至尊|涅槃.*至尊|涅槃至尊体"), .44),
 (re.compile(r"先天圣体道胎|圣体道胎"), .42),
 (re.compile(r"混沌体"), .40),
 (re.compile(r"大成.*荒古圣体|大成圣体"), .38),
 (re.compile(r"人之律者.*爱莉希雅"), .38), (re.compile(r"命运神道体"), .36),
 (re.compile(r"九转轮回体"), .25), (re.compile(r"八转轮回体"), .20),
 (re.compile(r"七转轮回体"), .16), (re.compile(r"六转轮回体"), .12),
 (re.compile(r"五转轮回体"), .08),
)
SUPPRESSED_FIELDS = (
 "攻击", "防御", "血量上限", "当前血量", "速度", "法球倍率", "暴击率", "暴击伤害",
 "闪避率", "吸血率", "穿透", "攻击加成", "防御加成", "生命加成", "元神伤害加成",
 "元神伤害减免", "神通伤害加成", "神通伤害减免", "近战伤害加成", "近战伤害减免",
 "全伤害类型加成", "全类型减免", "减伤", "治疗效果加成", "每回合恢复",
)


def _number(value: Any, fallback: float = 0) -> float:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else fallback
    except (TypeError, ValueError):
        return fallback


def _int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(_number(value, fallback))


def _realm_authority(source: Mapping[str, Any], fallback: int = 0) -> int:
    keys = ("mijinglevel_id", "xiangulevel_id", "huafenlevel_id")
    if not any(key in source for key in keys):
        return fallback
    xiangu_map = ((25, 24), (24, 23), (23, 22), (22, 21), (21, 20),
                  (19, 19), (17, 18), (16, 17), (15, 16), (14, 15),
                  (13, 14), (12, 13), (11, 12), (9, 11), (8, 10))
    xg = _int(source.get("xiangulevel_id"))
    xg = next((equivalent for required, equivalent in xiangu_map if xg >= required), xg)
    fl = _int(source.get("huafenlevel_id"))
    flower_level = max((rank for required, rank in flower.AUTHORITY_MAP.items()
                        if fl >= required), default=fl)
    return max(_int(source.get("mijinglevel_id")), xg, flower_level)


def _legacy(doc: Any) -> dict[str, Any]:
    raw = (getattr(doc, "ext", {}) or {}).get("legacy_source")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _player_authority(doc: Any) -> int:
    from . import extra_cultivation
    return _realm_authority(extra_cultivation.legacy_fields(doc), authority_of(doc))

def _npc_authority(npc: Mapping[str, Any]) -> int:
    return _realm_authority(npc, _int(npc.get("level_id")))


def _realm_authority21(value: int) -> int:
    return max(0, min(21, int(value) * 21 // 63))


def _root_mitigation(doc: Any) -> float:
    root = (getattr(doc, "ext", {}) or {}).get("linggen")
    root_name = root.get("name") or root.get("type") or "" if isinstance(root, Mapping) else root or ""
    old = _legacy(doc)
    text = " ".join(str(v or "") for v in (
        root_name, old.get("体质"), old.get("特殊体质"), old.get("灵根")))
    return next((value for pattern, value in ROOT_LAW_MITIGATION if pattern.search(text)), 0.0)


def _shop_index(rows: list[dict], name: str) -> int:
    return next((i for i, row in enumerate(rows) if row.get("name") == name), -1)


def _has_stock(shop: Mapping[str, Any]) -> bool:
    return any(_int(item.get("数量")) > 0 for item in (shop.get("one") or [])
               if isinstance(item, Mapping))


def _clone_shops(rows: Any) -> list[dict]:
    return [copy.deepcopy(dict(row)) for row in rows if isinstance(row, Mapping) and row.get("name")]


def _refresh_shops(catalog: list[dict], runtime: list[dict]) -> list[dict]:
    known = {x["name"]: x for x in runtime if isinstance(x, Mapping) and x.get("name")}
    out = []
    for source in catalog:
        row = copy.deepcopy(source)
        previous = known.get(row["name"], {})
        row["Grade"] = min(3, max(1, _int(previous.get("Grade", row.get("Grade", 1)), 1)))
        row["state"] = 0
        row.pop("state_until", None)
        out.append(row)
    return out


def _dao_heart(doc: Any, now: float) -> int:
    return dao_heart.ensure(doc, now)


def _dao_heart_loss(doc: Any, now: float) -> int:
    result = max(0, _dao_heart(doc, now) - DAO_HEART_PENALTY)
    doc.ext["daoxin"] = result
    old = doc.ext.get("legacy_source")
    if isinstance(old, dict):
        for key in ("道心", "道心值"):
            if key in old:
                old[key] = result
    return result


class XijieService:
    """One SQLite singleton for shops, active raids, and delayed jail release."""
    def __init__(self, db: Any, content: Any, item_lookup: Any,
                 player_fighter: Any, player_stats: Any, player_lock: Any = None):
        self.db, self.content = db, content
        self.item_lookup = item_lookup.get if hasattr(item_lookup, "get") else item_lookup
        self.player_fighter, self.player_stats = player_fighter, player_stats
        self.player_lock = player_lock
        import asyncio
        self._loop_lock = asyncio.Lock()

    def _catalog(self) -> list[dict]:
        return _clone_shops(self.content.table("item/shop列表") or [])

    def _npcs(self) -> list[dict]:
        return self.content.table("item/npc列表") or []

    async def initialize(self) -> None:
        async with self.db.transaction() as conn:
            await conn.execute("CREATE TABLE IF NOT EXISTS xijie_state (id INTEGER PRIMARY KEY CHECK (id=1), payload TEXT NOT NULL)")
            async with conn.execute("SELECT payload FROM xijie_state WHERE id=1") as cur:
                row = await cur.fetchone()
            try:
                state = json.loads(row[0]) if row else {}
            except (TypeError, ValueError):
                state = {}
            if not isinstance(state.get("shops"), list):
                state = {"shops": self._catalog(), "actions": {}, "jails": {},
                         "last_shop_reset_day": "", "last_grade_decay_day": ""}
            state.setdefault("actions", {})
            state.setdefault("jails", {})
            state.setdefault("last_shop_reset_day", "")
            state.setdefault("last_grade_decay_day", "")
            await self._save(state)

    async def _load(self) -> dict[str, Any]:
        async with self.db.conn.execute("SELECT payload FROM xijie_state WHERE id=1") as cur:
            row = await cur.fetchone()
        try:
            state = json.loads(row[0]) if row else {}
        except (TypeError, ValueError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        state.setdefault("shops", self._catalog())
        state.setdefault("actions", {})
        state.setdefault("jails", {})
        state.setdefault("last_shop_reset_day", "")
        state.setdefault("last_grade_decay_day", "")
        return state

    async def _save(self, state: Mapping[str, Any]) -> None:
        await self.db.conn.execute(
            "INSERT INTO xijie_state (id,payload) VALUES (1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")),))

    @asynccontextmanager
    async def _locked(self, uid: str):
        if self.player_lock:
            async with self.player_lock(str(uid)):
                yield
        else:
            yield

    async def _player(self, uid: str) -> Any | None:
        raw = await self.db.get_player(uid)
        if not raw:
            return None
        from .player import PlayerDoc
        return PlayerDoc(**raw)

    def _unlock_expired(self, shop: dict[str, Any], now_ms: int) -> bool:
        if _int(shop.get("state")) != 1 or _int(shop.get("state_until")) > now_ms:
            return False
        shop["state"] = 0
        shop.pop("state_until", None)
        return True

    def _busy_text(self, action: Mapping[str, Any], now: float) -> str:
        stage = {"approach": "洗劫准备", "loot": "搜刮", "pursuit": "逃亡"}.get(action.get("phase"), "洗劫")
        left = max(0, int(_number(action.get("blocking_until")) - now))
        return f"正在{stage}中，剩余 {left // 60} 分 {left % 60} 秒。"

    def _clear_action(self, doc: Any) -> None:
        doc.ext.pop("xijie_action", None)
        doc.state, doc.state_start = "空闲", 0.0

    def _set_action(self, doc: Any, action: dict[str, Any]) -> None:
        doc.ext["xijie_action"] = action
        doc.state, doc.state_start = "洗劫中", float(action["started_at"])

    async def list_text(self) -> str:
        now_ms = int(time.time() * 1000)
        async with self.db.transaction():
            state = await self._load()
            changed = False
            lines = ["--- 洗劫地点（洗劫有风险，魔道 +25×档）---"]
            for shop in state["shops"]:
                changed |= self._unlock_expired(shop, now_ms)
                price = _int(shop.get("price")) * max(1, _int(shop.get("Grade"), 1))
                loot = "、".join(str(row.get("name") or "未知") for row in (shop.get("one") or [])[:4])
                guard = "（戒备中）" if _int(shop.get("state")) == 1 else ""
                lines.append(f"· {shop['name']}（{shop.get('Grade', 1)} 档｜强化费 {price:,}）{guard}｜可掠：{loot}…")
            lines.append("#探查 地点（0.3×价格）｜#洗劫 地点（2h CD，战斗定胜负）")
            if changed:
                await self._save(state)
        return "\n".join(lines)

    def _has_authority(self, doc: Any, seal: str) -> bool:
        st = suiyun.state_of(doc)
        return bool(st and seal in (st.get("seals") or {}))

    def _ultimate_gate(self, doc: Any) -> tuple[bool, str, bool]:
        level = _int(doc.realm_index) + 1
        if level >= 63:
            return True, "你的道行震古烁今，独自横渡界海堤坝直奔终极古地。", False
        if level < 18:
            return False, "界海浪潮汹涌，每一朵浪花都是残破宇宙。至少达到仙王境，才有资格借三世铜棺横渡界海。", False
        return False, "横渡界海需要仙王境修为并持有三世铜棺。", True

    def _raid_fields(self, doc: Any, stats: Any) -> dict[str, Any]:
        old, ext = _legacy(doc), doc.ext
        root = ext.get("linggen")
        return {
            "名号": str(doc.name or doc.uid), "攻击": _int(stats.atk), "防御": _int(stats.defense),
            "血量上限": _int(stats.hp), "当前血量": _int(stats.hp), "暴击率": _number(stats.bao),
            "暴击伤害": _number(getattr(stats, "crit_damage", 1.5), 1.5),
            "速度": _int(getattr(stats, "speed", 100), 100),
            "法球倍率": linggen.orb_of(root if isinstance(root, Mapping) else None),
            "灵根": (root.get("name") or root.get("type")) if isinstance(root, Mapping) else root or old.get("灵根") or "普通灵根",
            "体质": str(old.get("体质") or ""), "特殊体质": str(old.get("特殊体质") or ""),
            "学习的功法": copy.deepcopy(ext.get("gongfa") or []),
            "当前使用的功法": str(old.get("当前使用的功法") or ""),
            **{key: _int(old.get(key)) for key in IMPERIAL_REALM_REQUIREMENTS},
            **{key: _number(old[key]) for key in SUPPRESSED_FIELDS if key in old},
        }

    async def spy(self, uid: str, place_name: str) -> tuple[bool, str]:
        uid = str(uid)
        async with self._locked(uid):
            async with self.db.transaction():
                doc = await self._player(uid)
                if not doc:
                    return False, "道友尚未踏入仙途，请先建立存档。"
                if doc.state != "空闲":
                    action = (await self._load()).get("actions", {}).get(uid)
                    return False, self._busy_text(action, time.time()) if action else "修仙：游戏进行中..."
                state = await self._load()
                index = _shop_index(state["shops"], place_name.strip())
                if index < 0:
                    return False, f"未找到洗劫地点：{place_name}（#洗劫列表 查看）。"
                shop = state["shops"][index]
                self._unlock_expired(shop, int(time.time() * 1000))
                cost = int(_int(shop.get("price")) * .3)
                if uid != "3196383818" and doc.stones < cost:
                    await self._save(state)
                    return False, f"打探消息需要 {cost:,} 灵石，家底不足。"
                if uid != "3196383818":
                    doc.stones -= cost
                loot = [x for x in (shop.get("one") or []) if isinstance(x, Mapping) and _int(x.get("数量")) > 0]
                preview = "、".join(f"{x.get('name')}×{_int(x.get('数量'), 1) or 1}" for x in loot[:5]) or "（已搬空）"
                await self.db.save_player(doc.model_dump())
                await self._save(state)
                guard = adventure.raid_guard_preview(_int(shop.get("Grade"), 1))
                return True, (f"你花 {cost:,} 灵石买通了 {shop['name']} 的账房……\n"
                              f"传闻库中藏着：{preview} 等。\n守卫实力约 {shop.get('Grade', 1)} 档（血 {guard['hp']:,}）。\n"
                              f"#洗劫 {shop['name']} 干一票大的！")

    async def start(self, uid: str, place_name: str, platform_id: str = "",
                    group_id: str = "") -> tuple[bool, str]:
        uid, name = str(uid), str(place_name or "").strip()
        if not name:
            return False, "格式：#洗劫 地点名（#洗劫列表 查看）。"
        now = time.time()
        async with self._locked(uid):
            async with self.db.transaction():
                doc = await self._player(uid)
                if not doc:
                    return False, "道友尚未踏入仙途，请先建立存档。"
                state = await self._load()
                current = state["actions"].get(uid)
                if current and (_number(current.get("blocking_until")) > now
                              or _number(current.get("stage_at")) > now):
                    return False, self._busy_text(current, now)
                if current:
                    state["actions"].pop(uid, None)
                    self._clear_action(doc)
                if doc.state not in ("空闲", "洗劫中"):
                    return False, "修仙：游戏进行中..."
                inventory = await self.db.get_inventory(uid)
                sky = self._has_authority(doc, "天空")
                cooldown = SKY_COOLDOWN_SECONDS if sky else RAID_COOLDOWN_SECONDS
                last = _number(doc.ext.get("raid_ts"))
                if last and now - last < cooldown:
                    if _int(inventory.get("劫光令")) < 1:
                        remain = max(0, int(last + cooldown - now))
                        return False, (f"每 {cooldown // 60} 分钟洗劫一次，正在 CD 中，剩余 CD："
                                       f"{remain // 60} 分 {remain % 60} 秒；劫光令可重置。")
                    if not await self.db.remove_item(uid, "劫光令", 1):
                        return False, "劫光令已不在纳戒中，无法重置洗劫冷却。"
                    notices = ["你祭出一枚劫光令，劫光一闪间，天道禁制化为虚无，洗劫冷却已重置！"]
                else:
                    notices = []
                if name == "终极古地":
                    allowed, text, uses_coffin = self._ultimate_gate(doc)
                    if not allowed:
                        if uses_coffin and _int(inventory.get("三世铜棺")) > 0:
                            if not await self.db.remove_item(uid, "三世铜棺", 1):
                                return False, text
                            allowed = True
                        if not allowed:
                            return False, text
                    notices.append(text)
                if name == "逆道界":
                    if not await self.db.remove_item(uid, "逆道令", 1):
                        return False, ("逆道界的规则之力十分恐怖，会磨灭一切天地大道，若没有逆道令的庇护，"
                                       "你此去定然十死无生，想到这里你放弃了前往洗劫这个念头。")
                    notices.append("逆道令化为流光，庇护你踏入逆道界。")
                if name == "超维真界" and _int(doc.realm_index) + 1 < 63:
                    return False, "你并非永恒境强者，无法超脱维宙。"
                index = _shop_index(state["shops"], name)
                if index < 0:
                    return False, f"未找到洗劫地点：{name}。"
                place = state["shops"][index]
                self._unlock_expired(place, int(now * 1000))
                if _int(place.get("state")) == 1:
                    return False, f"{name}已经戒备森严了，还是不要硬闯好了。"
                grade = min(3, max(1, _int(place.get("Grade"), 1)))
                fee = _int(place.get("price")) * grade
                if doc.stones < fee:
                    return False, f"洗劫前需花 {fee:,} 灵石强化防备，家底不足。"
                doc.stones -= fee
                doc.ext["modao"] = _number(doc.ext.get("modao")) + MODAO_PER_GRADE * grade
                if not isinstance(doc.ext.get("linggen"), Mapping):
                    rng = random.Random(f"xijie:{uid}:{int(now * 1000)}")
                    root = linggen.roll(self.content.table("item/灵根列表") or [], rng)
                    if root:
                        doc.ext["linggen"] = root
                        doc.ext["cultivation_efficiency"] = (
                            _number(doc.ext.get("cultivation_efficiency")) + _number(root.get("eff")))
                stats = self.player_stats(doc)
                buff = max(1, grade + 1)
                xt = xtzb.state_of(doc, now)
                xt_flags = xt.get("flags") or {}
                pangu_ready = _number(xt_flags.get("盘古开天待用")) > now
                # The original consumes this one-shot reward flag only when loot
                # is actually found; an empty shop leaves it available.
                pangu_loot_ready = bool(xt_flags.get("盘古洗劫翻倍待用", False))
                legacy_fields = self._raid_fields(doc, stats)
                legacy_fields["防御"] = max(1, _int(stats.defense) * buff)
                legacy_fields["血量上限"] = max(1, _int(stats.hp) * buff)
                legacy_fields["当前血量"] = max(1, _int(stats.hp) * buff)
                snap = {
                    "atk": max(1, _int(stats.atk)), "defense": max(1, _int(stats.defense) * buff),
                    "hp_max": max(1, _int(stats.hp) * buff), "current_hp": max(1, _int(stats.hp) * buff),
                    "bao": _number(stats.bao), "crit_damage": _number(getattr(stats, "crit_damage", 1.5), 1.5),
                    "speed": _int(getattr(stats, "speed", 100), 100),
                    "name": str(doc.name or uid), "grade": grade,
                    "legacy": legacy_fields, "realm_authority": _player_authority(doc),
                    "ideal_escape": self._has_authority(doc, "理想"),
                    "pangu_ready": pangu_ready, "pangu_loot_ready": pangu_loot_ready,
                    "pangu_passive": xtzb.current(doc, now) == "盘古幡",
                    "captured_doc": doc.model_dump(),
                }
                action_multiplier = timed_action.multiplier(doc, now)
                action = {
                    "id": secrets.token_hex(8), "phase": "approach", "place": copy.deepcopy(place),
                    "grade": grade, "player": snap, "started_at": now,
                    "stage_at": now + max(0, PREPARATION_BATTLE_MINUTES * 60 - PREPARATION_ACTION_MINUTES * 60 * (1 - action_multiplier)),
                    "blocking_until": now + PREPARATION_ACTION_MINUTES * 60 * action_multiplier,
                    "platform_id": str(platform_id or ""), "group_id": str(group_id or ""),
                    "loot": [], "search_log": [],
                }
                doc.ext["raid_ts"] = now
                place["state"] = 1
                place["state_until"] = int(now * 1000) + SHOP_LOCK_SECONDS * 1000
                self._set_action(doc, action)
                state["actions"][uid] = action
                await self.db.save_player(doc.model_dump())
                await self._save(state)
                bonus_pct = int((buff - buff / (1 + grade * GUARD_DEFENSE_HP_GRADE_RATE)) * 100)
                text = (f"你消费了 {fee:,} 灵石，防御力和生命值提高了 {bonus_pct}%。")
                if notices:
                    text += "\n" + "\n".join(notices)
                return True, text + f"\n开始前往{name}，约 10 分钟后遭遇守卫，祝你好运！"

    async def reset_shop(self, place_name: str, authorized: bool) -> tuple[bool, str]:
        if not authorized:
            return False, "此命令仅修仙管理员可用。"
        async with self.db.transaction():
            state = await self._load()
            index = _shop_index(state["shops"], str(place_name or "").strip())
            if index < 0:
                return False, f"未找到重置地点：{place_name}"
            shop = state["shops"][index]
            shop["state"] = 0
            shop.pop("state_until", None)
            await self._save(state)
        return True, "重置成功!"

    async def tick(self, now: float | None = None) -> list[dict[str, str]]:
        """Advance due persisted stages and return messages for the original QQ scene."""
        if self._loop_lock.locked():
            return []
        async with self._loop_lock:
            now = time.time() if now is None else float(now)
            await self._refresh_if_due(now)
            async with self.db.transaction():
                state = await self._load()
                actions, jails = list(state["actions"]), list(state["jails"])
            messages: list[dict[str, str]] = []
            for uid in actions:
                async with self._locked(uid):
                    async with self.db.transaction():
                        state = await self._load()
                        action = state["actions"].get(uid)
                        doc = await self._player(uid)
                        if not action or doc is None:
                            state["actions"].pop(uid, None)
                            await self._save(state)
                            continue
                        sent = await self._advance(doc, state, action, uid, now)
                        if sent:
                            await self.db.save_player(doc.model_dump())
                            await self._save(state)
                            messages.extend({"uid": uid, "platform_id": action.get("platform_id", ""),
                                             "group_id": action.get("group_id", ""), "text": text}
                                            for text in sent)
            for uid in jails:
                async with self._locked(uid):
                    async with self.db.transaction():
                        state = await self._load()
                        deadline = _number(state["jails"].get(uid))
                        if deadline <= 0 or deadline > now:
                            continue
                        state["jails"].pop(uid, None)
                        doc = await self._player(uid)
                        if doc:
                            doc.ext.pop("jail_until", None)
                            doc.ext.pop("banned", None)
                            doc.state, doc.state_start = "空闲", 0.0
                            await self.db.save_player(doc.model_dump())
                        await self._save(state)
            return messages

    async def _refresh_if_due(self, now: float) -> None:
        local = datetime.fromtimestamp(now, SHANGHAI)
        day = local.strftime("%Y-%m-%d")
        minute = local.hour * 60 + local.minute
        async with self.db.transaction():
            state = await self._load()
            changed = False
            if minute >= 20 * 60 + 59 and state.get("last_grade_decay_day") != day:
                for shop in state["shops"]:
                    shop["Grade"] = max(1, _int(shop.get("Grade"), 1) - 1)
                state["last_grade_decay_day"] = day
                changed = True
            if (minute >= 12 * 60 and local.isoweekday() in WEEKLY_REFRESH_DAYS
                    and state.get("last_shop_reset_day") != day):
                state["shops"] = _refresh_shops(self._catalog(), state["shops"])
                state["last_shop_reset_day"] = day
                changed = True
            if changed:
                await self._save(state)

    async def _advance(self, doc: Any, state: dict[str, Any], action: dict[str, Any],
                       uid: str, now: float) -> list[str]:
        if doc.state != "洗劫中":
            self._clear_action(doc)
            state["actions"].pop(uid, None)
            return ["洗劫动作已解除，人物状态恢复正常。"]
        phase, due = action.get("phase"), _number(action.get("stage_at"))
        if now < due:
            return []
        if phase == "approach":
            return await self._fight_guard(doc, state, action, uid, now)
        if phase == "loot":
            return await self._loot(doc, action, uid, now)
        if phase == "pursuit":
            return await self._pursuit(doc, state, action, uid, now)
        self._clear_action(doc)
        state["actions"].pop(uid, None)
        return ["洗劫行动状态异常，已安全终止。"]

    def _unlock_shop(self, state: dict[str, Any], name: str) -> None:
        index = _shop_index(state["shops"], name)
        if index >= 0:
            state["shops"][index]["state"] = 0
            state["shops"][index].pop("state_until", None)

    def _skill_tables(self) -> dict[str, Any]:
        return {key: self.content.table(f"item/技能组/{source}") or [] for key, source in (
            ("atk", "攻击技能"), ("def", "防御技能"),
            ("heal", "治疗技能"), ("boost", "灵根增幅技能"))}

    def _player_doc(self, data: Mapping[str, Any]) -> Any:
        from .player import PlayerDoc
        return PlayerDoc(**copy.deepcopy(dict(data)))

    async def _fight_guard(self, doc: Any, state: dict[str, Any], action: dict[str, Any],
                           uid: str, now: float) -> list[str]:
        from .combat import opening
        from .combat.engine import run_1v1
        from .combat.loadout import build_xijie_npc_fighter
        player, place, grade = action["player"], action["place"], int(action["grade"])
        rng = random.Random(f"xijie:{uid}:{action['id']}:guard")
        monster = adventure.raid_npc(place["name"], grade, self._npcs(), rng)
        if not monster:
            self._unlock_shop(state, str(place["name"]))
            self._clear_action(doc)
            state["actions"].pop(uid, None)
            return [f"{place['name']} 的守卫数据缺失，洗劫已取消，强化费用不退。"]
        combat_doc = self._player_doc(player.get("captured_doc") or doc.model_dump())
        stats = self.player_stats(combat_doc)
        raid_stats = type(stats)(
            atk=player["atk"], defense=player["defense"], hp=player["hp_max"],
            bao=player["bao"], set_lines=getattr(stats, "set_lines", ()),
            speed=player["speed"], crit_damage=player["crit_damage"],
            action_bar=getattr(stats, "action_bar", 0),
        )
        me = self.player_fighter(combat_doc, player["name"], raid_stats, player["current_hp"])
        me.name = player["name"]
        me.atk, me.defense = player["atk"], player["defense"]
        me.hp_max, me.hp = player["hp_max"], player["current_hp"]
        me.bao, me.crit_damage, me.speed = player["bao"], player["crit_damage"], player["speed"]
        raw_guard = adventure.raid_guard(monster, {
            "atk": player["atk"], "defense": player["defense"],
            "hp_max": player["hp_max"], "current_hp": player["current_hp"],
        }, grade)
        guard = build_xijie_npc_fighter(raw_guard, self.item_lookup, self._skill_tables())
        npc_authority = _npc_authority(monster)
        guard.tags["auth_of"] = npc_authority
        guard.tags["auth21"] = _realm_authority21(npc_authority)
        player_authority = int(player.get("realm_authority", authority_of(combat_doc)))
        me.tags["auth_of"] = player_authority
        me.tags["auth21"] = _realm_authority21(player_authority)

        # Original formation consumer selects one active formation and consumes a charge here.
        story = player.get("story") or story_npc.state_of(combat_doc)
        mods, formations = story_npc.battle_mods(story)
        player["story"] = story
        doc.ext["story"] = copy.deepcopy(story)
        if mods.get("enemy"):
            guard.atk = max(1, int(guard.atk * float(mods["enemy"].get("atk", 1))))
            guard.defense = max(1, int(guard.defense * float(mods["enemy"].get("def", 1))))
        if mods.get("atk_mult"):
            me.atk = max(1, int(me.atk * float(mods["atk_mult"])))
        if mods.get("bao_add"):
            me.bao = min(1, me.bao + float(mods["bao_add"]))

        suppression_message = ""
        if monster.get("帝道规则") or monster.get("皇道法则") or monster.get("道途压制"):
            player_fields = dict(player.get("legacy") or {})
            gap = max(0, npc_authority - player_authority)
            missing_imperial = not any(
                _int(player_fields.get(field)) >= required
                for field, required in IMPERIAL_REALM_REQUIREMENTS.items())
            if missing_imperial or gap:
                dominant = npc_authority >= 16 and player_authority < 16
                configured = min(.9, max(0, _number(monster.get("法则压制比例"))))
                realm_reduction = (min(.85, .70 + max(0, gap - 1) * .05) if dominant
                                   else min(.60, max(1, gap) * .18))
                base = max(configured, realm_reduction) if missing_imperial else realm_reduction
                mitigation = _root_mitigation(combat_doc)
                reduction = min(.90, base * (1 - mitigation))
                remain = 1 - reduction
                for field in SUPPRESSED_FIELDS:
                    if field not in player_fields:
                        continue
                    value = _number(player_fields[field]) * remain
                    player_fields[field] = (max(1, int(value)) if field in
                                            ("攻击", "防御", "血量上限", "当前血量", "速度") else max(0, value))
                sealed = []
                if missing_imperial:
                    skills = list(player_fields.get("学习的功法") or [])
                    sealed = [name for name in skills if any(
                        name == base_name or name.startswith(base_name + "·")
                        for base_name in SEALED_TECHNIQUES)]
                    player_fields["学习的功法"] = [name for name in skills if name not in sealed]
                    if player_fields.get("当前使用的功法") in sealed:
                        player_fields["当前使用的功法"] = next(iter(player_fields["学习的功法"]), "")
                    # The sealed technique list only changes the battle snapshot.
                    combat_doc.ext["gongfa"] = list(player_fields["学习的功法"])
                    from .combat.loadout import equip_skill_pool
                    for tag in ("atk_skills", "def_skills", "heal_skills"):
                        me.tags[tag] = [sk for sk in me.tags.get(tag, []) if sk.get("name") not in sealed]
                    me.skills = tuple(name for name in me.skills if name not in sealed)
                me.atk = max(1, _int(player_fields.get("攻击"), me.atk))
                me.defense = max(1, _int(player_fields.get("防御"), me.defense))
                me.hp_max = max(1, _int(player_fields.get("血量上限"), me.hp_max))
                me.hp = min(me.hp_max, max(1, _int(player_fields.get("当前血量"), me.hp)))
                me.speed = max(1, _int(player_fields.get("速度"), me.speed))
                me.bao = min(1, max(0, _number(player_fields.get("暴击率"), me.bao)))
                me.crit_damage = max(1, _number(player_fields.get("暴击伤害"), me.crit_damage))
                for source, target in (("法球倍率", "orb"), ("吸血率", "lifesteal"),
                                       ("闪避率", "dodge_chance")):
                    if source in player_fields:
                        me.effects[target] = max(0, _number(player_fields[source]))
                law = ("皇道法则" if monster.get("皇道法则") else
                       "帝道规则" if monster.get("帝道规则") else "道途法则")
                suppression_message = (
                    f"【{law}压制】灵根抵消 {int(mitigation * 100)}% 法则威压，"
                    f"全属性保留 {int(remain * 100)}%"
                    + (f"；{'、'.join(sealed)}失效" if sealed else "") + "。"
                )

        if player.get("pangu_ready"):
            xstate = xtzb.state_of(combat_doc, now)
            xstate["flags"].pop("盘古开天待用", None)
            xtzb.save(combat_doc, xstate)
            doc.ext["xtzb"] = copy.deepcopy(combat_doc.ext.get("xtzb"))

        player_first = _number(player.get("modao")) <= 999
        first, second = (me, guard) if player_first else (guard, me)
        guard_side = 1 if player_first else 0
        skip_first = (guard_side,) if mods.get("stun") else ()
        opening_result = opening.high_realm_exec(me, guard)
        prefix = ([f"【黑皇阵道·{'、'.join(formations)}】阵纹复苏，笼罩战场！"]
                  if formations else [])
        if opening_result:
            winner, open_log = opening_result
            player_won = winner == 0
            hp_left = me.hp if player_won else 0
            battle_log = [*prefix, *open_log]
        else:
            result = run_1v1(first, second, rng, skip_first=skip_first)
            player_side = 0 if player_first else 1
            player_won = result.winner == player_side
            hp_left = result.a_hp if player_first else result.b_hp
            if result.winner is None:
                guard_hp = result.b_hp if player_first else result.a_hp
                player_won = hp_left >= guard_hp
            battle_log = [*prefix, *([suppression_message] if suppression_message else []), *result.log]

        player["current_hp"] = max(0, min(player["hp_max"], int(hp_left)))
        action["player"] = player
        if player_won:
            action.update({"phase": "loot", "stage_at": now + LOOT_SEARCH_MINUTES * 60,
                           "blocking_until": now + LOOT_SEARCH_MINUTES * 60,
                           "guard_name": guard.name, "guard_log": battle_log[-4:]})
            self._set_action(doc, action)
            return [f"【洗劫战报】{player['name']}悄悄靠近{guard.name}，经过一番战斗击败守卫，"
                    f"剩余 {player['current_hp']:,} 气血，开始搜刮。\n"
                    + "\n".join(battle_log[-4:])
                    + f"\n约 5 分钟后开始追逃。{'生效阵法：' + '、'.join(formations) if formations else ''}"]

        self._unlock_shop(state, str(place["name"]))
        _dao_heart_loss(doc, now)
        await self.db.add_items(uid, {"秘境之匙": grade})
        self._clear_action(doc)
        doc.state, doc.state_start = "禁闭中", now
        doc.ext["banned"] = True
        doc.ext["jail_until"] = now + GUARD_JAIL_MINUTES * 60
        doc.ext["hp"] = player["current_hp"]
        state["actions"].pop(uid, None)
        state["jails"][uid] = doc.ext["jail_until"]
        return [f"【洗劫失败】你被 {guard.name} 抓进地牢，道心 −{DAO_HEART_PENALTY}，"
                f"秘境之匙 ×{grade}，禁闭 {GUARD_JAIL_MINUTES} 分钟。\n"
                + "\n".join(battle_log[-4:])]

    async def _loot(self, doc: Any, action: dict[str, Any], uid: str,
                    now: float) -> list[str]:
        player = action["player"]
        place_name = str(action["place"].get("name") or "")
        async with self.db.transaction():
            state = await self._load()
            index = _shop_index(state["shops"], place_name)
            loot = []
            if index < 0 or not _has_stock(state["shops"][index]):
                message = "已经被搬空了。"
            else:
                shop = state["shops"][index]
                multiplier = (PANGU_LOOT_MULTIPLIER
                              if player.get("pangu_loot_ready") else 1)
                rng = random.Random(f"xijie:{uid}:{action['id']}:loot")
                for _ in range(int(action["grade"]) * LOOT_SLOTS_PER_GRADE):
                    pool = [item for item in (shop.get("one") or [])
                            if isinstance(item, Mapping) and _int(item.get("数量")) > 0]
                    if not pool:
                        break
                    picked = copy.deepcopy(rng.choice(pool))
                    picked["数量"] = (_int(picked.get("数量"), 1) or 1) * multiplier
                    loot.append(picked)
                    for item in shop.get("one") or []:
                        if item.get("name") == picked.get("name") and _int(item.get("数量")) > 0:
                            item["数量"] = 0
                            break
                if loot and player.get("pangu_loot_ready"):
                    xt = xtzb.state_of(doc, now)
                    (xt.get("flags") or {}).pop("盘古洗劫翻倍待用", None)
                    xtzb.save(doc, xt)
                reward_lines = "\n".join(f"{item['name']} ×{item['数量']}" for item in loot)
                bonus = "\n盘古幡开天余威令本次洗劫奖励翻倍。" if multiplier > 1 else ""
                message = ("经过一番搜寻，你找到了：\n" + reward_lines if reward_lines
                           else "已经被搬空了。") + bonus + "\n万仙盟的人已盯上你，趁乱逃跑！"
            action["loot"] = loot
            action["phase"] = "pursuit"
            action["tries_left"] = int(action["grade"]) + 1
            action["tries_used"] = 0
            action["stage_at"] = now + PURSUIT_FIRST_DELAY_SECONDS
            action["blocking_until"] = now + PURSUIT_NOMINAL_MINUTES * 60
            action["pursuit_log"] = []
            self._set_action(doc, action)
            await self._save(state)
        return [f"【搜刮结算】{message}\n万仙盟追兵约 5 分钟后赶到。"]

    async def _pursuit(self, doc: Any, state: dict[str, Any], action: dict[str, Any],
                       uid: str, now: float) -> list[str]:
        player, grade = action["player"], int(action["grade"])
        rng = random.Random(f"xijie:{uid}:{action['id']}:pursuit:{action.get('tries_used', 0)}")
        npc = adventure.raid_npc("万仙盟", grade, self._npcs(), rng)
        if not npc:
            return await self._finish(doc, state, action, uid, "万仙盟未能赶到，你趁势脱身。")
        divisor = 1 + grade * GUARD_DEFENSE_HP_GRADE_RATE
        enemy_atk = _number(npc.get("atk")) * _number(player["atk"])
        enemy_def = _number(npc.get("def")) * _number(player["defense"]) / divisor
        root = npc.get("灵根") or {}
        orb = _number(root.get("法球倍率") if isinstance(root, Mapping) else 0)
        attack = enemy_atk * (.85 + orb) + enemy_def * .1
        ratio = attack / max(1, _number(player["defense"]))
        factor = .1 if ratio < 1 else 1.0 if ratio > 2.5 else .6 * ratio - .5
        base_damage = int(factor * attack * (int(rng.random() * 11) / 100 + .95))
        roll = rng.random()
        outcomes = ((.1, 1.0, "似乎不屑追你，只随手丢出神通"),
                    (.25, .3, "对你来了兴趣，只用三分力试探"),
                    (.5, 1.5, "因你的逃跑而愤怒，发出更强攻击"),
                    (.7, 1.3, "吸引了全部仇恨，强劲攻势已到眼前"),
                    (.9, 1.8, "与你贴脸飞行，攻势愈发猛烈"),
                    (1.0, .5, "你拖着疲惫身躯，拼尽全力加快脚步"))
        multiplier, flavor = next((scale, text) for limit, scale, text in outcomes if roll < limit)
        damage = int(base_damage * multiplier)
        player["current_hp"] = max(0, _int(player["current_hp"]) - damage)
        action["tries_left"] = max(0, _int(action.get("tries_left")) - 1)
        action["tries_used"] = _int(action.get("tries_used")) + 1
        text = (f"{npc.get('name', '万仙盟追兵')}{flavor}，受到 {damage:,} 点伤害，"
                f"剩余气血 {player['current_hp']:,}。")
        action.setdefault("pursuit_log", []).append(text)
        if player["current_hp"] <= 0:
            if player.get("ideal_escape"):
                return await self._finish(doc, state, action, uid,
                                          text + "\n【理想】捷克罗姆击碎天牢锁链，你已脱身。")
            self._unlock_shop(state, str(action["place"].get("name") or ""))
            _dao_heart_loss(doc, now)
            await self.db.add_items(uid, {"秘境之匙": grade + 1})
            self._clear_action(doc)
            doc.state, doc.state_start = "天牢中", now
            doc.ext["banned"] = True
            doc.ext["jail_until"] = now + PURSUIT_JAIL_MINUTES * 60
            doc.ext["hp"] = 0
            state["actions"].pop(uid, None)
            state["jails"][uid] = doc.ext["jail_until"]
            return [f"【洗劫逃亡失败】{text}\n你被关入天牢，道心 −{DAO_HEART_PENALTY}，"
                    f"秘境之匙 ×{grade + 1}，禁闭 {PURSUIT_JAIL_MINUTES} 分钟。"]
        if _int(action["tries_left"]) == 0:
            return await self._finish(doc, state, action, uid,
                                      text + "\n你已躲过万仙盟追杀，带着战利品逃回宗门。")
        doc.ext["hp"] = player["current_hp"]
        action["stage_at"] = now + PURSUIT_TICK_SECONDS
        self._set_action(doc, action)
        return [f"【逃亡·{action['tries_used']}/{grade + 1}】{text}"]

    async def _finish(self, doc: Any, state: dict[str, Any], action: dict[str, Any],
                      uid: str, ending: str) -> list[str]:
        player, place = action["player"], action["place"]
        gains: dict[str, int] = {}
        for item in action.get("loot") or []:
            item_name = str(item.get("name") or "").strip()
            quantity = max(0, _int(item.get("数量")))
            if item_name and quantity:
                gains[item_name] = gains.get(item_name, 0) + quantity
        if gains:
            await self.db.add_items(uid, gains)
        # The raid snapshot was buffed for combat; returned HP is clamped to the player's real cap.
        actual_hp_cap = max(1, _int(self.player_stats(doc).hp))
        doc.ext["hp"] = min(actual_hp_cap, max(0, _int(player.get("current_hp"))))
        index = _shop_index(state["shops"], str(place.get("name") or ""))
        grade = int(action["grade"])
        if index >= 0:
            shop = state["shops"][index]
            shop["Grade"] = min(3, max(1, _int(shop.get("Grade"), grade) + 1))
            shop["state"] = 0
            shop.pop("state_until", None)
            grade = shop["Grade"]
        self._clear_action(doc)
        state["actions"].pop(uid, None)
        rewards = "、".join(f"{name}×{amount}" for name, amount in gains.items()) or "无战利品"
        return [f"【洗劫成功】{ending}\n带回：{rewards}。地点戒备提升至 {grade} 档。"]
