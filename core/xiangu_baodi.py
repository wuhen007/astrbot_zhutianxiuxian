"""仙古秘境 仙遗宝地（W27）——原版 `XianyiBaodi.js`（401 行）+
`xianyiBaodiState.js`：修士寿元耗尽身死道消后，其纳戒遗藏化作仙遗宝地现世
诸天，供后来者探索收取。

对齐设计：
- 生成：寿元耗尽转世时（main.py `_drop_legacy_ring` 同点）把玩家当前库存
  （名→量）整体封入宝地；原主境界取转世前 realm_index+1；来源位面取
  当前所在位面。无人拾取 12 小时且原主境界高于 41 层后转化为宝地；现世 30 天。
- #仙遗宝地 列表 / #探索仙遗宝地 序号（10 分钟冷却）：
  40% 搬运 25-45% 未发现→已发现；20% 守护残魂（战力 = 原主境界×6000×0.8~1.2，
  我方战力 = 攻 + 防×0.5 + 幸运×100；胜搬 50-80%，败损 30% 当前血量）；
  40% 一无所获。
- #收取仙遗宝地 序号：已发现物品 → 纳戒（库存）；宝地搬空即消散。
- 并发：单进程 asyncio + calamity_lock 全服单例，等价原版 Redis 锁。

rng 约定：只用 rng.random()。
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

RELIC_EXPIRE_MS = 30 * 24 * 3600 * 1000
RELIC_UNCLAIMED_MS = 12 * 3600 * 1000
RELIC_MIN_LEVEL = 41
EXPLORE_COOLDOWN_MS = 10 * 60 * 1000


def baodi_list(world: Mapping) -> list[dict]:
    """有效宝地（懒清理过期）。"""
    now = time.time() * 1000
    store = world.setdefault("baodi", [])
    alive = [b for b in store if float(b.get("expire_at", 0) or 0) > now
             and (_remaining(b) > 0 or _discovered_total(b) > 0)]
    world["baodi"] = alive
    return alive


def drop_baodi(world: dict, owner_uid: str, owner_name: str, owner_level: int,
               location: str, inventory: Mapping[str, int], *, stones: int = 0,
               source_stones: int = 0, source_drop_id: str = "",
               now_ms: float | None = None) -> dict | None:
    """寿元遗藏转为宝地；源纳戒编号保证重试不会重复生成。"""
    store = world.setdefault("baodi", [])
    source_drop_id = str(source_drop_id or "")
    if source_drop_id:
        existing = next((b for b in store
                         if str(b.get("source_drop_id") or "") == source_drop_id), None)
        if existing:
            return existing
    loot = {str(k): int(v) for k, v in (inventory or {}).items()
            if str(k) and int(v or 0) > 0}
    stones = max(0, int(stones or 0))
    source_stones = max(0, int(source_stones or 0))
    if not loot and not stones and not source_stones:
        return None
    created = time.time() * 1000 if now_ms is None else float(now_ms)
    baodi = {
        "id": (f"baodi-{uuid.uuid5(uuid.NAMESPACE_URL, source_drop_id).hex}"
               if source_drop_id else f"baodi-{uuid.uuid4().hex[:8]}"),
        "source_drop_id": source_drop_id,
        "owner_uid": str(owner_uid), "owner_name": str(owner_name or "无名修士"),
        "owner_level": int(owner_level or 1), "location": str(location or "未知位面"),
        "loot": loot, "discovered": {}, "stones": stones, "source_stones": source_stones,
        "discovered_stones": 0, "discovered_source_stones": 0,
        "discovery_id": "", "explorers": {},
        "created_at": created, "expire_at": created + RELIC_EXPIRE_MS,
    }
    store.append(baodi)
    return baodi


def _total(d: Mapping) -> int:
    return sum(int(v) for v in d.values())


def _remaining(b: Mapping) -> int:
    return (_total(b.get("loot") or {}) + int(b.get("stones", 0) or 0)
            + int(b.get("source_stones", 0) or 0))


def _discovered_total(b: Mapping) -> int:
    return (_total(b.get("discovered") or {}) + int(b.get("discovered_stones", 0) or 0)
            + int(b.get("discovered_source_stones", 0) or 0))


def _move_resources(b: dict, moved: dict, ratio: float) -> None:
    for field, discovered_field, name in (("stones", "discovered_stones", "灵石"),
                                          ("source_stones", "discovered_source_stones", "源石")):
        quantity = int(b.get(field, 0) or 0)
        take = min(quantity, int(quantity * ratio))
        if take:
            b[field] = quantity - take
            b[discovered_field] = int(b.get(discovered_field, 0) or 0) + take
            moved[name] = take


def _fmt(d: Mapping) -> str:
    return "、".join(f"{k}×{v}" for k, v in d.items() if int(v) > 0) or "无"


def list_text(world: dict) -> str:
    lst = baodi_list(world)
    if not lst:
        return "【仙遗宝地】\n当前诸天之中暂无现世的仙遗宝地。"
    lines = [f"【仙遗宝地·诸天现世】共 {len(lst)} 座：", ""]
    for i, b in enumerate(lst, 1):
        lines.append(f"▶ {i}. {b.get('owner_name')}的仙遗宝地")
        lines.append(f"   原主境界：第 {b.get('owner_level')} 层｜来源位面：{b.get('location')}")
        lines.append(f"   遗藏总量：{_remaining(b)} 件｜"
                     f"已发现可收取：{_discovered_total(b)} 件")
        lines.append("")
    lines.append("使用 #探索仙遗宝地 序号 探索，#收取仙遗宝地 序号 收取已发现之物。")
    return "\n".join(lines)


def explore(world: dict, doc: Any, st: Mapping, idx: int, rng: Callable[[], float],
            now_ms: float, combat_power: int) -> tuple[str, dict | None]:
    """探索第 idx 座宝地。返回 (text, baodi 或 None)。"""
    lst = world.get("baodi") or []
    if not 1 <= int(idx) <= len(lst):
        return "未找到对应的仙遗宝地，请先用 #仙遗宝地 查看序号。", None
    b = lst[int(idx) - 1]
    if float(b.get("expire_at", 0) or 0) <= now_ms:
        return "该仙遗宝地已经消散，请重新查看列表。", None
    last = float((b.get("explorers") or {}).get(str(getattr(doc, "uid", "")), 0) or 0)
    if last > 0 and now_ms - last < EXPLORE_COOLDOWN_MS:
        remain = int((EXPLORE_COOLDOWN_MS - (now_ms - last)) / 60000) + 1
        return f"探索需调息恢复，请 {remain} 分钟后再来（探索冷却 10 分钟）。", None
    b.setdefault("explorers", {})[str(getattr(doc, "uid", ""))] = now_ms
    loot = b.setdefault("loot", {})
    disc = b.setdefault("discovered", {})
    roll = rng.random()
    moved = {}
    if roll < 0.40:
        ratio = 0.25 + rng.random() * 0.2
        moved = _move_batch(loot, disc, ratio)
        _move_resources(b, moved, ratio)
        text = (f"【仙遗宝地·探索】\n你于宝地中仔细搜寻，触碰到一缕残存的道韵，有所收获！\n"
                f"发现：{_fmt(moved)}")
    elif roll < 0.60:
        guardian = int((b.get("owner_level") or 1) * 6000 * (0.8 + rng.random() * 0.4))
        if combat_power >= guardian:
            ratio = 0.5 + rng.random() * 0.3
            moved = _move_batch(loot, disc, ratio)
            _move_resources(b, moved, ratio)
            text = (f"【仙遗宝地·探索】\n宝地深处，一尊守护残魂裹挟煞气扑杀而来！\n"
                    f"你以无上法力将其镇压，夺得大批造化！\n发现：{_fmt(moved)}")
        else:
            text = (f"【仙遗宝地·探索】\n宝地深处，一尊守护残魂裹挟煞气扑杀而来！\n"
                    f"你不敌其威，被震退（气血 -30%）。\n需尽快提升实力再来。")
    else:
        text = ("【仙遗宝地·探索】\n你于宝地中搜寻良久，却只见到满地尘埃，"
                "一无所获，只觉此地灵机深不可测。")
    if moved:
        if moved:
            b["discovery_id"] = uuid.uuid4().hex
    text += (f"\n\n宝地：{b.get('owner_name')}的仙遗宝地（第 {b.get('owner_level')} 层）\n"
             f"已发现可收取：{_discovered_total(b)} 件")
    return text, b


def _move_batch(loot: dict, disc: dict, ratio: float) -> dict:
    """按比例把未发现遗藏搬运到已发现（原版 moveBatch）。"""
    moved: dict[str, int] = {}
    for name in sorted(list(loot.keys())):
        qty = int(loot.get(name, 0) or 0)
        if qty <= 0:
            continue
        take = min(qty, max(1, math.ceil(qty * ratio)))
        loot[name] = qty - take
        if loot[name] <= 0:
            del loot[name]
        disc[name] = int(disc.get(name, 0) or 0) + take
        moved[name] = take
    return moved


def claim(world: dict, doc: Any, idx: int, now_ms: float) -> tuple[bool, str, dict]:
    """收取第 idx 座宝地已发现之物 → 库存增量。返回 (ok, text, items)。"""
    lst = world.get("baodi") or []
    if not 1 <= int(idx) <= len(lst):
        return False, "未找到对应的仙遗宝地。", {}
    b = lst[int(idx) - 1]
    if float(b.get("expire_at", 0) or 0) <= now_ms:
        return False, "该仙遗宝地已经消散，请重新查看列表。", {}
    disc = b.get("discovered") or {}
    if _discovered_total(b) <= 0:
        return False, "该仙遗宝地暂无可收取之物，先去 #探索仙遗宝地 吧。", {}
    claimed = {str(k): int(v) for k, v in disc.items() if int(v) > 0}
    if int(b.get("discovered_stones", 0) or 0) > 0:
        claimed["灵石"] = int(b["discovered_stones"])
    if int(b.get("discovered_source_stones", 0) or 0) > 0:
        claimed["源石"] = int(b["discovered_source_stones"])
    b["discovered"] = {}
    b["discovered_stones"] = b["discovered_source_stones"] = 0
    b["discovery_id"] = ""
    exhausted = _remaining(b) <= 0
    if exhausted:
        try:
            (world.get("baodi") or []).remove(b)
        except ValueError:
            pass
        return True, ("【仙遗宝地·收取】\n你收取了全部造化：\n"
                      f"{_fmt(claimed)}\n\n宝地机缘已尽，秘境缓缓消散于虚空之中。"), claimed
    return True, (f"【仙遗宝地·收取】\n你收取了部分造化：\n{_fmt(claimed)}\n\n"
                  "宝地尚有遗藏，可继续探索。"), claimed


def rules_text() -> str:
    return "\n".join([
        "【仙遗宝地·规则】",
        "「修士寿元耗尽、身死道消，其纳戒遗藏化作仙遗宝地现世诸天，30 天后消散。」",
        "",
        "· 生成：转世时库存全数封入宝地（原主境界决定守护残魂强度）",
        "· 探索：#探索仙遗宝地 序号（10 分钟冷却）——",
        "  40% 发现 25-45% 遗藏｜20% 守护残魂（战力判定：胜搬 50-80%，败损 30% 气血）｜40% 无所获",
        "· 收取：#收取仙遗宝地 序号——已发现之物入纳戒；宝地搬空即消散",
    ])
