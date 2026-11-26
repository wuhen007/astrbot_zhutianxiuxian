"""仙古秘境（W25 引擎）——原版 `apps/SecretPlace/xianguPlace.js`(11764 行) +
`xianguMap.js` + `xianguEvacuation.js` + `xianguBag.js` + `apps/tasks/xianguLifecycle.js`
的网格引擎移植：14 碎片 × 11×11 迷雾地图、八方向移动、格子结算、探索选项、
秘境背包、撤离状态机、生命周期状态机、道种掉落表。

对齐设计（用户确认）：完整网格引擎 / NPC 交互 W26 做生态简化 / 道种神火 W27 完整移植。

shortcut（相对原版，均在本 docstring 登记）：
- 独立「仙古境界」轨（仙古今世法 11 境）端口未单开，映射主轨：
  xg_level = min(11, 2 + realm_index // 4)（铭文 5 → realm_index 12，尊者 7 → 20，
  神火 8 → 24）；区域门槛按此换算。
- 原 Redis 会话/收据（player_set、撤离锁、结算 receipt）单进程 SQLite 下收敛为
  玩家档 ext["xiangu"] + calamity_state["xiangu"] 单例；唯一机缘/机缘格认领以
  claims 表做全服幂等（等价 receipt 的「applied 即不再发」）。
- 生命周期 cron（2000 年一查）改为指令入口 + #时代 懒推进，状态存
  calamity_state["xiangu"]["lifecycle"]，世界年取 era.years_total。
- 血量类伤害原版为绝对值（亿级），端口量级失真 → 改当前血量百分比制；
  奖励公式保留「2000 + 系数×境界²×随机×乘区」形状，系数 ÷1000。
- NPC 生态按原版 15 秒初始延迟、每 30 秒轮转一步 BFS；私人地图由后台任务推进。
- 多玩家同图相遇（presence/peer）不做（单服群聊低频，擂台 PvP 走 ext 报名表 W26）。
- 机缘宝池 worldUnique=False 按个人地图结算，无跨玩家争抢。

rng 约定：只使用 rng.random()。
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 常量：格子 / 方向

CELL_EMPTY, CELL_WALL, CELL_TREASURE, CELL_DANGER, CELL_NPC = 0, 1, 2, 3, 4
CELL_EXIT, CELL_VOID, CELL_EXPLORED, CELL_UNIQUE = 5, 6, 7, 8

MARROW_POOL_NAME = "万道仙髓池"
MARROW_POOL_KIND = "wandao_xiansui_pool"

# 移动时需要文字说明的格子
_MOVE_TEXT_CELLS = {CELL_TREASURE, CELL_DANGER, CELL_NPC, CELL_VOID, CELL_UNIQUE}

DIRECTIONS: dict[str, dict[str, Any]] = {
    "上": {"dx": 0, "dy": -1, "name": "上方"},
    "下": {"dx": 0, "dy": 1, "name": "下方"},
    "左": {"dx": -1, "dy": 0, "name": "左方"},
    "右": {"dx": 1, "dy": 0, "name": "右方"},
    "左上": {"dx": -1, "dy": -1, "name": "左上方"},
    "右上": {"dx": 1, "dy": -1, "name": "右上方"},
    "左下": {"dx": -1, "dy": 1, "name": "左下方"},
    "右下": {"dx": 1, "dy": 1, "name": "右下方"},
}
_OPPOSITE = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}

# ---------------------------------------------------------------- 常量：碎片 / 区域

FRAGMENTS: dict[str, dict[str, Any]] = {
    "edge_camp": {"name": "接引营地", "zone": "边缘区域", "risk": 0.10,
                  "npc": 0.30, "treasure": 0.10,
                  "desc": "仙古花蕾绽放入口，各族天骄汇集之处",
                  "features": ("交易NPC", "安全区", "法则石碑")},
    "spirit_lake": {"name": "灵湖", "zone": "边缘区域", "risk": 0.20,
                    "npc": 0.20, "treasure": 0.25,
                    "desc": "灵气浓郁成液，湖中可见灵鱼游弋",
                    "features": ("灵药", "治愈", "源石矿脉")},
    "ancient_ruins": {"name": "古战场遗迹", "zone": "中层区域", "risk": 0.40,
                      "npc": 0.40, "treasure": 0.35,
                      "desc": "仙古大战的残留，破碎的战兵遍地",
                      "features": ("道种", "残兵", "战魂")},
    "true_dragon_nest": {"name": "真龙巢穴", "zone": "中层区域", "risk": 0.55,
                         "npc": 0.30, "treasure": 0.50,
                         "desc": "真龙曾伏之地，龙威未散",
                         "features": ("十凶宝术", "龙威压制", "Boss区")},
    "chaos_rift": {"name": "混沌裂隙", "zone": "中层区域", "risk": 0.70,
                   "npc": 0.10, "treasure": 0.10,
                   "desc": "空间不稳定，虚空风暴肆虐",
                   "features": ("虚空风暴", "随机传送", "隐藏入口")},
    "dark_prison": {"name": "黑暗牢笼", "zone": "深层区域", "risk": 0.85,
                    "npc": 0.20, "treasure": 0.45,
                    "desc": "十凶黑暗物质泄露之地，令人心悸",
                    "features": ("十凶觉醒", "黑暗物质", "折仙咒残留")},
    "immortal_podium": {"name": "仙王讲道台", "zone": "深层区域", "risk": 0.50,
                        "npc": 0.60, "treasure": 0.30,
                        "desc": "仙王曾在此讲道，道则还未消散",
                        "features": ("功法感悟", "天骄聚集", "道韵浓郁")},
    "bone_forest": {"name": "天骄埋骨地", "zone": "深层区域", "risk": 0.70,
                    "npc": 0.30, "treasure": 0.50,
                    "desc": "历代天骄折戟之地，白骨堆积如山",
                    "features": ("战魂", "遗物机缘", "诅咒")},
    "flame_abyss": {"name": "火道禁区", "zone": "火道禁区", "risk": 0.80,
                    "npc": 0.10, "treasure": 0.50,
                    "desc": "万火深渊，三千道火永恒燃烧",
                    "features": ("万火深渊", "三千道火", "祭炼场", "道种孕育")},
    "xiangu_core": {"name": "仙古花蕾·核心", "zone": "核心区域", "risk": 0.90,
                    "npc": 0.40, "treasure": 0.80,
                    "desc": "仙古花蕾深处，承载归途法则与道种融合道台",
                    "features": ("撤离点", "道种融合地")},
    "xiangu_arena": {"name": "仙古擂台", "zone": "擂台区域", "risk": 0.75,
                     "npc": 0.10, "treasure": 0.15,
                     "desc": "连接深层区域与仙古花蕾核心的古老战台",
                     "features": ("擂台报名", "冠军争霸", "本轮排名")},
    "xiangu_ultimate": {"name": "终极造化地", "zone": "终极区域", "risk": 0.95,
                        "npc": 0.00, "treasure": 0.25,
                        "desc": "仅向本轮仙古第一开启的终极造化空间",
                        "features": ("冠军固定造化", "仙王经文", "帝血")},
    "chaos_mosquito": {"name": "混沌蚊湖", "zone": "深层区域", "risk": 1.00,
                       "npc": 0.00, "treasure": 0.60,
                       "desc": "混沌蚊群栖息地，连天神亦避之不及",
                       "features": ("蚊群", "嗜血", "借势灭敌", "绝地翻盘")},
    "void_rift": {"name": "虚空夹层", "zone": "隐藏区域", "risk": 0.95,
                  "npc": 0.00, "treasure": 0.90,
                  "desc": "秘境第二层，黑色古船横亘虚空",
                  "features": ("黑色古船", "大罗剑胎", "空间扭曲")},
}

ZONE_POOLS: dict[str, tuple[str, ...]] = {
    "边缘区域": ("edge_camp", "spirit_lake"),
    "中层区域": ("ancient_ruins", "true_dragon_nest", "chaos_rift"),
    "深层区域": ("dark_prison", "immortal_podium", "bone_forest", "chaos_mosquito"),
    "火道禁区": ("flame_abyss",),
    "擂台区域": ("xiangu_arena",),
    "核心区域": ("xiangu_core",),
    "终极区域": ("xiangu_ultimate",),
    "隐藏区域": ("void_rift",),
}

# 区域准入的仙古境界（原版 ZONE_LEVEL_REQUIREMENTS）
ZONE_XG_GATE: dict[str, int] = {
    "边缘区域": 5, "中层区域": 6, "深层区域": 7, "火道禁区": 7,
    "擂台区域": 7, "核心区域": 7, "终极区域": 7, "隐藏区域": 8,
}

# 擂台固定承接深层与核心，核心再通往冠军专属的终极造化地。
PROGRESS_TARGETS: dict[str, tuple[str, ...]] = {
    "边缘区域": ("边缘区域", "中层区域"),
    "中层区域": ("深层区域",),
    "深层区域": ("火道禁区", "擂台区域"),
    "火道禁区": ("擂台区域",),
    "擂台区域": ("深层区域", "核心区域"),
    "核心区域": ("擂台区域", "终极区域", "隐藏区域"),
    "终极区域": ("核心区域",),
    "隐藏区域": ("核心区域",),
}

XG_REALM_NAMES: dict[int, str] = {
    1: "凡人", 2: "搬血境", 3: "洞天境", 4: "化灵境", 5: "铭文境", 6: "列阵境",
    7: "尊者境", 8: "神火境", 9: "真一境", 10: "圣祭境", 11: "天神境",
}

XG_LEVEL_DIV = 4          # 主轨 realm_index 每 4 境 = 仙古 1 境（docstring shortcut）
XG_ENTRY_MIN, XG_ENTRY_MAX = 5, 7   # 秘境准入仙古境界带（铭文~尊者）
CORE_FRAGMENT = "xiangu_core"
ARENA_FRAGMENT = "xiangu_arena"
ULTIMATE_FRAGMENT = "xiangu_ultimate"

# 仙古境界 → 主轨门槛（由 XG_LEVEL_DIV 推导的整表，供文案与校验共用）
def xg_gate_index(zone: str) -> int:
    """区域准入对应的主轨 realm_index 门槛（0-based）。"""
    return (ZONE_XG_GATE.get(zone, 5) - 2) * XG_LEVEL_DIV


def xg_level_of(doc: Any) -> int:
    """主轨 realm_index → 仙古境界（2-11）。
    已点燃神火者钉到 ≥8（神火境；W27 道种孕育/苦修/服丹/祭炼真我共用）。"""
    ri = int(getattr(doc, "realm_index", 0) or 0)
    base = min(11, 2 + max(0, ri) // XG_LEVEL_DIV)
    try:
        st = ((getattr(doc, "ext", {}) or {}).get("xiangu") or {})
        if (st.get("shenhuo") or {}).get("已点燃"):
            return max(base, 8)
    except Exception:
        pass
    return base


def realm_name(level: int) -> str:
    return XG_REALM_NAMES.get(int(level or 0), "未知境")


def zone_entry_block(doc: Any, zone: str) -> str | None:
    """区域境界拦截文案；满足则 None。"""
    lv = xg_level_of(doc)
    gate = ZONE_XG_GATE.get(zone, 5)
    if lv < gate:
        return (f"【境界不足·无法穿越】{zone}需要{realm_name(gate)}方可进入！\n"
                f"当前仙古境界：{realm_name(lv)}（{lv}/11）")
    return None


def fragment_entry_block(doc: Any, fragment_id: str, crowned: bool = False) -> str | None:
    frag = FRAGMENTS.get(fragment_id)
    if not frag:
        return f"碎片数据异常：{fragment_id}。"
    block = zone_entry_block(doc, frag["zone"])
    if block:
        return block
    if fragment_id == ULTIMATE_FRAGMENT and not crowned:
        return "【终极法则·冠冕不应】终极造化地只回应「本轮仙古第一」的冠冕烙印。"
    return None


# ---------------------------------------------------------------- 数据表加载

_DIR = Path(__file__).resolve().parent.parent / "data"
_CONFIG: dict[str, Any] | None = None
_XG_LEVELS: list[dict] | None = None


def load_config() -> dict[str, Any]:
    """data/xianguSecretPlace.json（缺文件回退内置极简表）。"""
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    try:
        _CONFIG = json.loads((_DIR / "xianguSecretPlace.json").read_text(encoding="utf-8"))
    except Exception:
        _CONFIG = {"撤离配置": {"正常撤离": {"基础时间": 10, "每份战利品时间": 2, "最长时间": 60, "完成窗口": 120},
                              "紧急撤离": {"基础时间": 30, "最长时间": 90}, "冷却时间": 12},
                   "机缘宝池": {"探索概率": 0.03, "NPC邀请概率": 0.18, "仙道潜力": 50, "修血倍率": 5}}
    return _CONFIG


def load_xg_levels() -> list[dict]:
    """data/Level/仙古今世法.json（Boss 属性缩放依据）。"""
    global _XG_LEVELS
    if _XG_LEVELS is not None:
        return _XG_LEVELS
    try:
        _XG_LEVELS = json.loads((_DIR / "Level" / "仙古今世法.json").read_text(encoding="utf-8"))
    except Exception:
        _XG_LEVELS = []
    return _XG_LEVELS


def evac_config() -> dict[str, Any]:
    cfg = load_config().get("撤离配置") or {}
    return {
        "normal": {"base": int((cfg.get("正常撤离") or {}).get("基础时间", 10) or 10),
                   "per_loot": int((cfg.get("正常撤离") or {}).get("每份战利品时间", 2) or 2),
                   "max": int((cfg.get("正常撤离") or {}).get("最长时间", 60) or 60)},
        "emergency": {"base": int((cfg.get("紧急撤离") or {}).get("基础时间", 30) or 30),
                      "per_loot": int((cfg.get("紧急撤离") or {}).get("每份战利品时间", 2) or 2),
                      "max": int((cfg.get("紧急撤离") or {}).get("最长时间", 90) or 90)},
        "window": int((cfg.get("正常撤离") or {}).get("完成窗口", 120) or 120),
        "cooldown_h": int((cfg.get("冷却时间") or 12) or 12),
    }


def marrow_config() -> dict[str, Any]:
    cfg = load_config().get("机缘宝池") or {}
    return {"chance": float(cfg.get("探索概率", 0.03) or 0.03),
            "npc_invite": float(cfg.get("NPC邀请概率", 0.18) or 0.18),
            "potential": int(cfg.get("仙道潜力", 50) or 50),
            "mult": float(cfg.get("修血倍率", 5) or 5)}


# ---------------------------------------------------------------- 种子随机（FNV-1a + mulberry32）

def _imul(a: int, b: int) -> int:
    return (a * b) & 0xFFFFFFFF


class _Mulberry:
    """原版 createXianguSeededRandom：FNV-1a 种子 → mulberry32；同种子同序列。
    暴露 .random() 以对齐端口 rng 约定（core 层只用 rng.random()）。"""

    __slots__ = ("_state",)

    def __init__(self, seed: str) -> None:
        state = 2166136261
        for ch in str(seed):
            state = _imul(state ^ ord(ch), 16777619)
        self._state = state

    def random(self) -> float:
        state = (self._state + 0x6D2B79F5) & 0xFFFFFFFF
        self._state = state
        t = state
        t = _imul(t ^ (t >> 15), t | 1)
        t ^= (t + _imul(t ^ (t >> 7), t | 61)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0


def seeded_rng(seed: str) -> _Mulberry:
    return _Mulberry(seed)


def _pick(rng: Callable[[], float], seq: list) -> Any:
    return seq[min(len(seq) - 1, int(rng.random() * len(seq)) % max(1, len(seq)))]


def _shuffle(rng: Callable[[], float], seq: list) -> list:
    out = list(seq)
    for i in range(len(out) - 1, 0, -1):
        j = int(rng.random() * (i + 1)) % (i + 1)
        out[i], out[j] = out[j], out[i]
    return out


# ---------------------------------------------------------------- 拓扑：连接 / 出口

_REQUIRED_DIRS = ("top", "bottom", "left", "right")


def _required_targets(seed: str, fragment_id: str) -> list[str]:
    frag = FRAGMENTS.get(fragment_id)
    if not frag:
        return []
    rnd = seeded_rng(f"{seed}:{fragment_id}:required-connections")
    used: set[str] = set()
    targets: list[str] = []
    for zone in PROGRESS_TARGETS.get(frag["zone"], ()):
        pool = [f for f in ZONE_POOLS.get(zone, ()) if f not in used]
        target = _pick_different(fragment_id, pool, rnd)
        if target:
            targets.append(target)
            used.add(target)
    return targets


def _pick_different(current: str, candidates: list[str], rng: Callable[[], float]) -> str | None:
    avail = list(dict.fromkeys(c for c in candidates if c and c != current))
    return _pick(rng, avail) if avail else None


def _sanitize_special(fragment_id: str, connections: Mapping[str, Any]) -> dict[str, Any]:
    """擂台/核心/终极/隐藏的主线路径清理（原版 sanitizeXianguSpecialConnections）。"""
    src_zone = (FRAGMENTS.get(fragment_id) or {}).get("zone")
    out = {d: connections.get(d) for d in _REQUIRED_DIRS}
    for d in _REQUIRED_DIRS:
        target = out.get(d)
        if not target:
            continue
        tgt_zone = (FRAGMENTS.get(target) or {}).get("zone")
        skips_arena = (target == CORE_FRAGMENT
                       and fragment_id not in (ARENA_FRAGMENT, ULTIMATE_FRAGMENT, "void_rift"))
        skips_champion = target == ULTIMATE_FRAGMENT and fragment_id != CORE_FRAGMENT
        skips_arena_in = (target == ARENA_FRAGMENT
                          and src_zone not in ("深层区域", "火道禁区", "核心区域"))
        leaves_core = (fragment_id == CORE_FRAGMENT
                       and target not in (ARENA_FRAGMENT, ULTIMATE_FRAGMENT, "void_rift"))
        leaves_arena = (fragment_id == ARENA_FRAGMENT
                        and target != CORE_FRAGMENT and tgt_zone != "深层区域")
        leaves_terminal = fragment_id in (ULTIMATE_FRAGMENT, "void_rift") and target != CORE_FRAGMENT
        if skips_arena or skips_champion or skips_arena_in or leaves_core or leaves_arena or leaves_terminal:
            out[d] = None
    return out


def _ensure_required(fragment_id: str, connections: Mapping[str, Any],
                     required: list[str], rng: Callable[[], float],
                     protected: str | None = None) -> dict[str, Any]:
    cur = str(fragment_id or "")
    prot = protected if protected in _REQUIRED_DIRS else None
    result = {d: (connections.get(d) if str(connections.get(d) or "") not in ("", cur) else None)
              for d in _REQUIRED_DIRS}
    req = [str(t) for t in dict.fromkeys(required) if t and str(t) != cur]
    req_keys = set(req)

    for target in req:
        if any(str(result.get(d) or "") == target for d in _REQUIRED_DIRS):
            continue
        cands = [d for d in _REQUIRED_DIRS if d != prot and not result.get(d)]
        if not cands:
            counts: dict[str, int] = {}
            for d in _REQUIRED_DIRS:
                if d == prot:
                    continue
                key = str(result.get(d))
                counts[key] = counts.get(key, 0) + 1
            cands = [d for d in _REQUIRED_DIRS if d != prot and counts.get(str(result.get(d)), 0) > 1]
        if not cands:
            cands = [d for d in _REQUIRED_DIRS
                     if d != prot and str(result.get(d)) not in req_keys]
        if not cands:
            break
        result[_pick(rng, cands)] = target

    seen: set[str] = set()
    if prot and result.get(prot):
        seen.add(str(result[prot]))
    for d in _REQUIRED_DIRS:
        if d == prot:
            continue
        key = str(result.get(d) or "")
        if not result.get(d) or key == cur or key in seen:
            result[d] = None
        else:
            seen.add(key)
    return result


def create_connections(seed: str, fragment_id: str) -> dict[str, Any]:
    """碎片四向连接：随机 60% + 主线必需目标 + 专用路径清理。"""
    rnd = seeded_rng(f"{seed}:{fragment_id}:connections")
    frag = FRAGMENTS.get(fragment_id)
    if not frag:
        return {}

    def pick_target() -> str | None:
        zones = [z for z, gate in ZONE_XG_GATE.items() if z in ZONE_POOLS]
        cand = [z for z in zones if z != frag["zone"] or rnd.random() < 0.3]
        zone = _pick(rnd, cand) if cand else "边缘区域"
        direct = _pick_different(fragment_id, list(ZONE_POOLS.get(zone, ())), rnd)
        if direct:
            return direct
        fallback = [f for z in zones for f in ZONE_POOLS.get(z, ())]
        return _pick_different(fragment_id, fallback, rnd)

    connections = {d: (pick_target() if rnd.random() < 0.6 else None) for d in _REQUIRED_DIRS}
    if not any(connections.values()):
        connections[_pick(rnd, list(_REQUIRED_DIRS))] = pick_target()
    safe = _sanitize_special(fragment_id, connections)
    return _ensure_required(fragment_id, safe, _required_targets(seed, fragment_id), rnd)


def bind_return_connection(seed: str, fragment_id: str, connections: Mapping[str, Any],
                           return_dir: str, previous_id: str) -> dict[str, Any]:
    """进入新碎片时绑定返程方向，并保证主线目标不被返程挤掉。"""
    rnd = seeded_rng(f"{seed}:{fragment_id}:return-connections")
    result = _ensure_required(fragment_id, connections,
                              _required_targets(seed, fragment_id), rnd,
                              protected=return_dir if return_dir in _REQUIRED_DIRS else None)
    displaced = result.get(return_dir)
    for d in _REQUIRED_DIRS:
        if d != return_dir and result.get(d) == previous_id:
            result[d] = None
    result[return_dir] = previous_id

    if displaced and displaced in _required_targets(seed, fragment_id) \
            and displaced not in [result.get(d) for d in _REQUIRED_DIRS]:
        spare = next((d for d in _REQUIRED_DIRS if d != return_dir and not result.get(d)), None) \
            or next((d for d in _REQUIRED_DIRS if d != return_dir
                     and result.get(d) not in _required_targets(seed, fragment_id)), None)
        if spare:
            result[spare] = displaced
    return result


def _exit_positions(w: int, h: int, connections: Mapping[str, Any],
                    rng: Callable[[], float]) -> list[dict]:
    positions = []
    for d in _REQUIRED_DIRS:
        if not connections.get(d):
            continue
        if d in ("top", "bottom"):
            positions.append({"x": 1 + int(rng.random() * (w - 2)) % max(1, w - 2),
                              "y": 0 if d == "top" else h - 1})
        else:
            positions.append({"x": 0 if d == "left" else w - 1,
                              "y": 1 + int(rng.random() * (h - 2)) % max(1, h - 2)})
    return positions


def _exit_direction(point: Mapping, w: int, h: int) -> str | None:
    if not point:
        return None
    if point.get("y") == 0:
        return "top"
    if point.get("y") == h - 1:
        return "bottom"
    if point.get("x") == 0:
        return "left"
    if point.get("x") == w - 1:
        return "right"
    return None


def _find_exit_position(map_st: Mapping, direction: str) -> dict | None:
    w, h = int(map_st["w"]), int(map_st["h"])
    grid = map_st["grid"]
    for p in map_st.get("exit_positions", ()):
        if _exit_direction(p, w, h) == direction \
                and grid[p["y"]][p["x"]] == CELL_EXIT:
            return {"x": p["x"], "y": p["y"]}
    for y in range(h):
        for x in range(w):
            if grid[y][x] == CELL_EXIT and _exit_direction({"x": x, "y": y}, w, h) == direction:
                return {"x": x, "y": y}
    return None


def _ensure_exit_connectivity(grid: list[list[int]], spawn: Mapping,
                              exits: list[Mapping]) -> list[list[int]]:
    """出生点到每个出口刻 L 形通路，防随机墙隔断。"""
    h, w = len(grid), len(grid[0])
    sx, sy = int(spawn["x"]), int(spawn["y"])
    if not (0 <= sx < w and 0 <= sy < h):
        return grid
    for exit_ in exits:
        tx = min(w - 2, max(1, int(exit_["x"])))
        ty = min(h - 2, max(1, int(exit_["y"])))
        x, y = sx, sy
        while x != tx:
            x += (tx > x) - (tx < x)
            if grid[y][x] == CELL_WALL:
                grid[y][x] = CELL_EMPTY
        while y != ty:
            y += (ty > y) - (ty < y)
            if grid[y][x] == CELL_WALL:
                grid[y][x] = CELL_EMPTY
    return grid


# ---------------------------------------------------------------- 网格生成

def generate_fragment_grid(seed: str, fragment_id: str,
                           connections: Mapping[str, Any],
                           rng: Callable[[], float]) -> dict[str, Any]:
    """原版 generateFragmentGrid：边界墙→出口→内墙→裂缝→机缘→危险→NPC→
    唯一机缘→出生点→出口连通刻路。"""
    frag = FRAGMENTS.get(fragment_id)
    if not frag:
        return {"grid": [[]], "pos": {"x": 0, "y": 0}, "specials": {}}
    w, h = 11, 11
    grid = [[CELL_EMPTY] * w for _ in range(h)]
    for x in range(w):
        grid[0][x] = CELL_WALL
        grid[h - 1][x] = CELL_WALL
    for y in range(h):
        grid[y][0] = CELL_WALL
        grid[y][w - 1] = CELL_WALL

    exits = _exit_positions(w, h, connections, rng)
    for p in exits:
        grid[p["y"]][p["x"]] = CELL_EXIT

    # 内墙（risk × 0.15 × 121）
    for _ in range(int(w * h * frag["risk"] * 0.15)):
        wx, wy = 1 + int(rng.random() * (w - 2)) % (w - 2), 1 + int(rng.random() * (h - 2)) % (h - 2)
        if grid[wy][wx] == CELL_EMPTY:
            grid[wy][wx] = CELL_WALL

    # 虚空裂缝
    if fragment_id in ("chaos_rift", "dark_prison", "void_rift"):
        for _ in range(3 if fragment_id == "chaos_rift" else 1):
            rx, ry = 1 + int(rng.random() * (w - 2)) % (w - 2), 1 + int(rng.random() * (h - 2)) % (h - 2)
            if grid[ry][rx] == CELL_EMPTY:
                grid[ry][rx] = CELL_VOID

    # 机缘点
    for _ in range(int(w * h * frag["treasure"])):
        tx, ty = 1 + int(rng.random() * (w - 2)) % (w - 2), 1 + int(rng.random() * (h - 2)) % (h - 2)
        if grid[ty][tx] == CELL_EMPTY:
            grid[ty][tx] = CELL_TREASURE

    # 危险点
    for _ in range(int(w * h * frag["risk"] * 0.2)):
        dx_, dy_ = 1 + int(rng.random() * (w - 2)) % (w - 2), 1 + int(rng.random() * (h - 2)) % (h - 2)
        if grid[dy_][dx_] == CELL_EMPTY:
            grid[dy_][dx_] = CELL_DANGER

    # NPC 格（实体对象 W26 生成；此处先记坐标）
    npc_locations: list[dict] = []
    for _ in range(int(w * h * frag["npc"])):
        nx, ny = 1 + int(rng.random() * (w - 2)) % (w - 2), 1 + int(rng.random() * (h - 2)) % (h - 2)
        if grid[ny][nx] == CELL_EMPTY:
            grid[ny][nx] = CELL_NPC
            npc_locations.append({"x": nx, "y": ny})

    # 唯一机缘
    unique_treasures: dict[str, dict] = {}

    def place_unique(name: str, treasure: dict) -> bool:
        cands = [{"x": x, "y": y} for y in range(1, h - 1) for x in range(1, w - 1)
                 if grid[y][x] not in (CELL_WALL, CELL_EXIT, CELL_UNIQUE)]
        if not cands:
            return False
        pos = _pick(rng, cands)
        grid[pos["y"]][pos["x"]] = CELL_UNIQUE
        unique_treasures[name] = {**treasure, "pos": pos, "claimed": False}
        return True

    if fragment_id == ULTIMATE_FRAGMENT:
        place_unique("玉石匣·仙王经文", {
            "name": "玉石匣", "type": "道具", "dist_echo": 3, "unique": True,
            "desc": "仙古神玉凿成的无缝古匣，内封一卷仙王经文；时机未至，强开只会令经文化为流光。",
            "echo": {3: "心神不宁，似有大道在远方共鸣...",
                     2: "一股浩瀚道韵从前方传来，令你体内功法自行运转！",
                     1: "你面前的空间微微扭曲，一件被时光尘封的器物若隐若现..."}})
        place_unique("一滴帝血", {
            "name": "帝血", "type": "道具", "dist_echo": 2, "unique": True,
            "desc": "一位无上存在跨越万古时空留下的一滴精血，万古岁月也未能磨灭其中的帝道意志。",
            "echo": {2: "脚下大地隐隐传来温热...似有沉睡的力量在苏醒",
                     1: "万物土在震动！一滴璀璨的金色血液缓缓浮出地面！"}})
        place_unique("本轮仙古第一造化", {
            "name": "本轮仙古第一造化", "type": "冠军造化", "dist_echo": 2,
            "claim_scope": "round-champion", "unique": True,
            "desc": "终极道台为本轮仙古第一凝成的专属造化。",
            "echo": {2: "本轮冠冕烙印微微发热，前方有一道造化与之共鸣。",
                     1: "终极道台绽放仙光，正等待本轮仙古第一落印。"}})
    if fragment_id == "void_rift":
        ax, ay = 1 + int(rng.random() * (w - 2)) % (w - 2), 1 + int(rng.random() * (h - 2)) % (h - 2)
        if grid[ay][ax] != CELL_WALL:
            grid[ay][ax] = CELL_UNIQUE
            unique_treasures["大罗剑胎"] = {
                "pos": {"x": ax, "y": ay}, "dist_echo": 3, "claimed": False,
                "name": "大罗剑胎", "class": "装备", "type": "武器", "unique": True,
                "stats": {"atk": 3_000_000, "def": 3_000_000, "HP": 3_000_000,
                          "bao": 0.2, "pinji": 6, "不可交易": 1},
                "desc": "黑色古船横渡虚空而来，剑胎无锋无饰，却承载着斩开岁月长河的杀机。",
                "echo": {3: "远方似有剑鸣传来，古老而深邃...",
                         2: "剑意越来越强！这是来自超越仙王的力量...",
                         1: "黑色古船上，一柄剑胎正在沉睡！大罗剑胎！"}}

    # 出生点（安全空地，邻墙/危险 ≤2）
    spawn = {"x": w // 2, "y": h // 2}
    found = False
    for _ in range(50):
        sx, sy = 1 + int(rng.random() * (w - 2)) % (w - 2), 1 + int(rng.random() * (h - 2)) % (h - 2)
        if grid[sy][sx] in (CELL_EMPTY, CELL_EXPLORED):
            bad = sum(1 for ddx in (-1, 0, 1) for ddy in (-1, 0, 1)
                      if 0 <= sy + ddy < h and 0 <= sx + ddx < w
                      and grid[sy + ddy][sx + ddx] in (CELL_DANGER, CELL_WALL))
            if bad <= 2:
                spawn = {"x": sx, "y": sy}
                found = True
                break
    if not found:
        fallback = [{"x": x, "y": y} for y in range(1, h - 1) for x in range(1, w - 1)
                    if grid[y][x] not in (CELL_WALL, CELL_UNIQUE)]
        spawn = _pick(rng, fallback) if fallback else spawn
        grid[spawn["y"]][spawn["x"]] = CELL_EMPTY

    _ensure_exit_connectivity(grid, spawn, exits)
    return {"grid": grid, "pos": spawn,
            "specials": {"unique_treasures": unique_treasures,
                         "npc_locations": npc_locations, "exit_positions": exits}}


def _instance_id(seed: str, fragment_id: str, connections: Mapping[str, Any]) -> str:
    routes = ",".join(f"{d}={connections.get(d) or '-'}" for d in _REQUIRED_DIRS)
    return f"{seed}:{fragment_id}:{routes}"


def create_fragment_state(seed: str, fragment_id: str,
                          connections: Mapping[str, Any]) -> dict[str, Any]:
    frag = FRAGMENTS[fragment_id]
    iid = _instance_id(seed, fragment_id, connections)
    gen = generate_fragment_grid(seed, fragment_id, connections, seeded_rng(f"{iid}:grid"))
    return {
        "instance_id": iid, "fragment_id": fragment_id,
        "w": 11, "h": 11,
        "grid": gen["grid"],
        "revealed": [[False] * 11 for _ in range(11)],
        "pos": dict(gen["pos"]),
        "connections": dict(connections),
        "unique_treasures": gen["specials"]["unique_treasures"],
        "npc_locations": gen["specials"]["npc_locations"],
        "exit_positions": gen["specials"]["exit_positions"],
        "steps": 0,
        "discovered": [fragment_id],
    }


def new_run_map(seed: str) -> dict[str, Any]:
    """进入秘境：固定从边缘区域出生（同轮共享入口图池）。"""
    rnd = seeded_rng(f"{seed}:entry")
    start = _pick(rnd, list(ZONE_POOLS["边缘区域"]))
    connections = create_connections(seed, start)
    return create_fragment_state(seed, start, connections)


# ---------------------------------------------------------------- 快照 / 恢复（碎片穿越）

def _snapshot(map_st: Mapping) -> dict | None:
    return {"fragment_id": map_st["fragment_id"], "grid": [row[:] for row in map_st["grid"]],
            "revealed": [row[:] for row in map_st["revealed"]], "pos": dict(map_st["pos"]),
            "connections": dict(map_st["connections"]),
            "unique_treasures": json.loads(json.dumps(map_st["unique_treasures"], ensure_ascii=False)),
            "npc_locations": json.loads(json.dumps(map_st["npc_locations"], ensure_ascii=False)),
            "exit_positions": [dict(p) for p in map_st["exit_positions"]],
            "w": map_st["w"], "h": map_st["h"], "steps": map_st.get("steps", 0),
            "instance_id": map_st.get("instance_id", "")}


def _restore(snapshot: Mapping | None, fragment_id: str) -> dict | None:
    if not snapshot or snapshot.get("fragment_id") != fragment_id:
        return None
    return json.loads(json.dumps(snapshot, ensure_ascii=False))


# ---------------------------------------------------------------- 神识 / 揭示 / 渲染

def divine_range(doc: Any) -> int:
    lv = xg_level_of(doc)
    if lv <= 7:
        return 1
    if lv == 8:
        return 2
    if lv <= 10:
        return 3
    return 4


def reveal(map_st: dict, pos: Mapping, rng_range: int) -> None:
    w, h = int(map_st["w"]), int(map_st["h"])
    for dy in range(-rng_range, rng_range + 1):
        for dx in range(-rng_range, rng_range + 1):
            nx, ny = pos["x"] + dx, pos["y"] + dy
            if 0 <= ny < h and 0 <= nx < w:
                map_st["revealed"][ny][nx] = True


def revealed_exits(map_st: Mapping) -> list[dict]:
    w, h = int(map_st["w"]), int(map_st["h"])
    out = []
    for p in map_st.get("exit_positions", ()):
        if map_st["grid"][p["y"]][p["x"]] == CELL_EXIT \
                and map_st["revealed"][p["y"]][p["x"]] \
                and _exit_direction(p, w, h) \
                and map_st["connections"].get(_exit_direction(p, w, h)):
            out.append({"x": p["x"], "y": p["y"],
                        "direction": _exit_direction(p, w, h),
                        "target": map_st["connections"][_exit_direction(p, w, h)]})
    return out


def check_echo(map_st: Mapping) -> list[dict]:
    """唯一机缘的道韵共鸣（按曼哈顿距离分层播报）。"""
    echoes = []
    px, py = map_st["pos"]["x"], map_st["pos"]["y"]
    for name, treasure in (map_st.get("unique_treasures") or {}).items():
        if treasure.get("claimed"):
            continue
        dist = abs(px - treasure["pos"]["x"]) + abs(py - treasure["pos"]["y"])
        limit = int(treasure.get("dist_echo", 2) or 2)
        if dist <= limit:
            msg = (treasure.get("echo") or {}).get(dist) or f"感应到{name}的道韵波动..."
            echoes.append({"name": name, "dist": dist, "msg": msg})
    return echoes


_GRID_ICON = {
    CELL_EMPTY: "·", CELL_WALL: "▓", CELL_EXPLORED: "·", CELL_TREASURE: "💎",
    CELL_DANGER: "⚡", CELL_NPC: "👤", CELL_EXIT: "🚪", CELL_VOID: "🌀",
    CELL_UNIQUE: "✨",
}
_SENSE_ICON = {
    CELL_TREASURE: "$$", CELL_DANGER: "⚡", CELL_NPC: "🙂", CELL_EXIT: "➤",
    CELL_VOID: "🌀", CELL_UNIQUE: "∞", CELL_EXPLORED: "·",
}


def render_grid(map_st: Mapping, doc: Any, gains: Mapping | None = None) -> str:
    """迷雾网格（文本版；出图模板由 handler 另行渲染）。"""
    frag = FRAGMENTS.get(map_st["fragment_id"], {})
    rng_range = divine_range(doc)
    px, py = map_st["pos"]["x"], map_st["pos"]["y"]
    lines = [f"═══ {frag.get('name', '未知区域')} · {map_st['w']}×{map_st['h']} · 神识感知中 ═══",
             f"👤 {getattr(doc, 'name', '') or '修士'}｜{realm_name(xg_level_of(doc))}｜"
             f"神识：{rng_range}格｜💎 道韵：{int((gains or {}).get('daoyun', 0) or 0)}",
             f"📍 区域：{frag.get('zone', '?')}｜危险：{'★' * max(1, int(frag.get('risk', 0.2) * 5))}",
             ""]
    for y in range(int(map_st["h"])):
        row = ""
        for x in range(int(map_st["w"])):
            cell = map_st["grid"][y][x]
            dist = abs(x - px) + abs(y - py)
            if x == px and y == py:
                row += "🐉"
            elif map_st["revealed"][y][x]:
                row += _GRID_ICON.get(cell, "·")
            elif dist <= rng_range:
                row += _SENSE_ICON.get(cell, "·")
            else:
                row += "▓"
        lines.append("  " + row)
    lines += ["", "🐉玩家 💎机缘 ⚡危险 👤NPC 🚪出口 🌀裂缝 ✨唯一机缘 💧仙髓池",
              "▓迷雾/墙 ·空地 $$道韵感应 ≈仙髓感应 ∞绝世机缘 ➤出口感召"]
    return "\n".join(lines)


# ---------------------------------------------------------------- 玩家态（ext["xiangu"]）

def _reachable_cells(grid: list[list[int]], start: Mapping) -> set[tuple[int, int]]:
    if not grid or not isinstance(grid[0], list):
        return set()
    h, w = len(grid), len(grid[0])
    if w < 3 or h < 3 or any(not isinstance(row, list) or len(row) != w for row in grid):
        return set()
    x, y = start.get("x"), start.get("y")
    if type(x) is not int or type(y) is not int or not (0 <= x < w and 0 <= y < h):
        return set()
    if grid[y][x] == CELL_WALL:
        return set()
    seen = {(x, y)}
    queue = [(x, y)]
    for cx, cy in queue:
        for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0),
                       (1, 0), (-1, 1), (0, 1), (1, 1)):
            nx, ny = cx + dx, cy + dy
            if (0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen
                    and grid[ny][nx] != CELL_WALL):
                seen.add((nx, ny))
                queue.append((nx, ny))
    return seen


def _repair_saved_map(st: dict) -> bool:
    """修补旧图拓扑：清理自环/重复路，补出口并仅为断路开墙。"""
    map_st = st.get("map")
    if not isinstance(map_st, dict):
        return False
    fragment_id = str(map_st.get("fragment_id") or "")
    if fragment_id not in FRAGMENTS:
        return False
    grid = map_st.get("grid")
    if (not isinstance(grid, list) or not grid or not isinstance(grid[0], list)
            or not grid[0]):
        return False
    h, w = len(grid), len(grid[0])
    if h < 3 or w < 3 or any(not isinstance(row, list) or len(row) != w for row in grid):
        return False
    pos = map_st.get("pos")
    if not isinstance(pos, Mapping):
        return False
    px, py = pos.get("x"), pos.get("y")
    if type(px) is not int or type(py) is not int or not (0 <= px < w and 0 <= py < h):
        return False
    if grid[py][px] == CELL_WALL:
        return False

    seed = str(st.get("world_seed") or "legacy")
    current = map_st.get("connections")
    current = current if isinstance(current, Mapping) else {}
    known = {d: (current.get(d) if isinstance(current.get(d), str)
                 and current.get(d) in FRAGMENTS else None) for d in _REQUIRED_DIRS}
    required = _required_targets(seed, fragment_id)
    repaired = _ensure_required(
        fragment_id,
        _sanitize_special(fragment_id, known),
        required,
        seeded_rng(f"{seed}:{fragment_id}:repair"),
        _exit_direction(pos, w, h),
    )
    player_direction = _exit_direction(pos, w, h)
    if player_direction and not repaired.get(player_direction):
        rescue = next((target for target in required if target not in repaired.values()), None)
        if rescue:
            for direction in _REQUIRED_DIRS:
                if repaired[direction] == rescue:
                    repaired[direction] = None
            repaired[player_direction] = rescue

    changed = (not isinstance(map_st.get("connections"), Mapping)
               or any(current.get(d) != repaired.get(d) for d in _REQUIRED_DIRS))
    if map_st.get("w") != w or map_st.get("h") != h:
        map_st["w"], map_st["h"] = w, h
        changed = True

    old_positions = map_st.get("exit_positions")
    old_positions = old_positions if isinstance(old_positions, list) else []
    kept: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    for point in old_positions:
        if not isinstance(point, Mapping):
            changed = True
            continue
        x, y = point.get("x"), point.get("y")
        if type(x) is not int or type(y) is not int or not (0 <= x < w and 0 <= y < h):
            changed = True
            continue
        direction = _exit_direction(point, w, h)
        key = (x, y)
        valid = (direction and repaired.get(direction) and key not in seen
                 and grid[y][x] == CELL_EXIT)
        if not valid:
            if grid[y][x] == CELL_EXIT and key != (px, py):
                grid[y][x] = CELL_WALL
            changed = True
            continue
        seen.add(key)
        kept.append({"x": x, "y": y})

    for direction in _REQUIRED_DIRS:
        if not repaired.get(direction):
            continue
        position = _find_exit_position({**map_st, "exit_positions": kept}, direction)
        if position is None:
            generated = _exit_positions(
                w, h, {direction: repaired[direction]},
                seeded_rng(f"{seed}:{fragment_id}:repair-exit:{direction}"),
            )
            if not generated:
                continue
            base = generated[0]
            if direction in ("top", "bottom"):
                candidates = [{"x": x, "y": 0 if direction == "top" else h - 1}
                              for x in range(1, w - 1)]
            else:
                candidates = [{"x": 0 if direction == "left" else w - 1, "y": y}
                              for y in range(1, h - 1)]
            start_index = next((i for i, p in enumerate(candidates)
                                if p["x"] == base["x"] and p["y"] == base["y"]), 0)
            candidates = candidates[start_index:] + candidates[:start_index]
            position = next((p for p in candidates
                             if grid[p["y"]][p["x"]] == CELL_WALL
                             and (p["x"], p["y"]) != (px, py)), None)
            if position is None:
                continue
            grid[position["y"]][position["x"]] = CELL_EXIT
            kept.append(position)
            changed = True
        elif not any(p["x"] == position["x"] and p["y"] == position["y"] for p in kept):
            kept.append(position)
            changed = True

    valid_positions = {(p["x"], p["y"]) for p in kept}
    for y in (0, h - 1):
        for x in range(w):
            if (grid[y][x] == CELL_EXIT and (x, y) not in valid_positions
                    and (x, y) != (px, py)):
                grid[y][x] = CELL_WALL
                changed = True
    for x in (0, w - 1):
        for y in range(1, h - 1):
            if (grid[y][x] == CELL_EXIT and (x, y) not in valid_positions
                    and (x, y) != (px, py)):
                grid[y][x] = CELL_WALL
                changed = True

    reachable = _reachable_cells(grid, pos)
    blocked = [p for p in kept if (p["x"], p["y"]) not in reachable]
    if blocked:
        before = [row[:] for row in grid]
        _ensure_exit_connectivity(grid, pos, blocked)
        if grid != before:
            changed = True

    if changed:
        map_st["connections"] = repaired
        map_st["exit_positions"] = kept
    return changed


def state_of(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        ext = {}
        try:
            setattr(doc, "ext", ext)
        except Exception:
            pass
    st = ext.get("xiangu")
    if not isinstance(st, dict):
        st = {}
        ext["xiangu"] = st
    st.setdefault("active", False)
    st.setdefault("location", "边缘区域")
    st.setdefault("gains", {})
    st.setdefault("bag", bag_new())
    st.setdefault("history", {})
    st.setdefault("infamy", 0)
    st.setdefault("kills", 0)
    st.setdefault("cd", {})
    st.setdefault("heavy_until", 0.0)
    _repair_saved_map(st)
    return st


def clear_session(st: dict, summary: dict | None = None) -> None:
    """一轮结束（撤离/死亡/闭合）：清临时态，保留 gains 供查看/奖励。"""
    for key in ("map", "history", "run", "evac", "options", "pending_defeat",
                "soul_target", "teammate", "npc_interactions", "defeated_npcs",
                "fusion", "hp_max_hint"):
        st.pop(key, None)
    st["active"] = False
    st["location"] = "边缘区域"
    st["gains"] = {}
    st["bag"] = bag_new()
    if summary:
        st["last_run"] = summary


def begin_run(st: dict, seed: str, now: float, rng: Callable[[], float]) -> None:
    # 冠冕/融合意图属于上一轮 world_seed，新一轮一律作废
    st.pop("crowned", None)
    st.pop("fusion", None)
    st.pop("hp_max_hint", None)
    st["world_seed"] = seed
    st["entry_at"] = now
    st["run"] = {
        "run_id": f"xiangu-{int(now):x}-{int(rng.random() * 0xFFFFFFFF):07x}",
        "started_at": now,
        "start_items": bag_item_count(st["bag"]),
        "start_kills": int(st.get("kills", 0) or 0),
        "start_infamy": float(st.get("infamy", 0) or 0),
        "seeds": [],
    }
    st["map"] = new_run_map(seed)
    st["active"] = True
    reveal(st["map"], st["map"]["pos"], 1)


# ---------------------------------------------------------------- 秘境背包

def bag_new() -> dict[str, Any]:
    return {"xiuwei": 0, "xueqi": 0, "source_stone": 0, "potential": 0,
            "items": [], "seeds": [], "techniques": []}


def bag_item_count(bag: Mapping) -> int:
    return int(sum(int(i.get("quantity", 0) or 0) for i in bag.get("items", ())))


def bag_add_growth(bag: dict, xiuwei: int = 0, xueqi: int = 0,
                   source_stone: int = 0) -> None:
    bag["xiuwei"] = int(bag.get("xiuwei", 0) or 0) + max(0, int(xiuwei))
    bag["xueqi"] = int(bag.get("xueqi", 0) or 0) + max(0, int(xueqi))
    bag["source_stone"] = int(bag.get("source_stone", 0) or 0) + max(0, int(source_stone))


def bag_add_potential(bag: dict, amount: int) -> None:
    bag["potential"] = int(bag.get("potential", 0) or 0) + max(0, int(amount))


def bag_add_item(bag: dict, item: Mapping) -> None:
    name = str(item.get("name") or item.get("名称") or "").strip()
    if not name:
        return
    itype = str(item.get("type") or item.get("类型") or "道具").strip() or "道具"
    qty = max(1, int(item.get("quantity", 1) or 1))
    for entry in bag["items"]:
        if entry.get("name") == name and entry.get("type") == itype:
            entry["quantity"] = int(entry.get("quantity", 0) or 0) + qty
            return
    saved = {k: v for k, v in item.items()
             if k not in ("name", "名称", "type", "类型", "quantity", "数量")}
    bag["items"].append({**saved, "name": name, "type": itype, "quantity": qty})


def bag_add_seed(bag: dict, seed: Mapping) -> None:
    if seed and seed.get("名称"):
        bag["seeds"].append(json.loads(json.dumps(seed, ensure_ascii=False)))


def bag_add_technique(bag: dict, technique: Mapping | str) -> None:
    name = (technique if isinstance(technique, str)
            else str(technique.get("name") or technique.get("名称") or ""))
    if not name:
        return
    if any((t.get("name") if isinstance(t, dict) else t) == name for t in bag["techniques"]):
        return
    saved = {"name": name} if isinstance(technique, str) \
        else json.loads(json.dumps(technique, ensure_ascii=False))
    bag["techniques"].append(saved)


def bag_summary(bag: Mapping) -> dict[str, Any]:
    items = list(bag.get("items", ()))
    units = sum(int(i.get("quantity", 0) or 0) for i in items)
    units += len(bag.get("seeds", ())) + len(bag.get("techniques", ()))
    units += sum(1 for k in ("xiuwei", "xueqi", "source_stone", "potential")
                 if int(bag.get(k, 0) or 0) > 0)
    return {**{k: bag.get(k, 0) for k in ("xiuwei", "xueqi", "source_stone", "potential")},
            "items": items, "seeds": list(bag.get("seeds", ())),
            "techniques": list(bag.get("techniques", ())),
            "item_count": bag_item_count(bag), "seed_count": len(bag.get("seeds", ())),
            "technique_count": len(bag.get("techniques", ())), "loot_units": units}


def bag_format(bag: Mapping) -> str:
    s = bag_summary(bag)
    item_text = "、".join(f"{i.get('name')}×{i.get('quantity')}" for i in s["items"]) or "无"
    seed_text = "、".join(str(g.get("名称") or g) for g in s["seeds"]) or "无"
    tech_text = "、".join(str(t.get("name") if isinstance(t, dict) else t)
                          for t in s["techniques"]) or "无"
    return "\n".join([
        "【仙古秘境背包】",
        f"修为：{s['xiuwei']:,}", f"血气：{s['xueqi']:,}",
        f"源石：{s['source_stone']:,}", f"仙道潜力：{s['potential']:,}",
        f"物品：{item_text}", f"道种：{seed_text}", f"功法：{tech_text}",
        f"战利品单位：{s['loot_units']}",
    ])


# ---------------------------------------------------------------- 奖励公式（÷1000 缩放）

def calc_rewards(doc: Any, mult: float = 1.0,
                 rng: Callable[[], float] | None = None) -> tuple[int, int]:
    """探索修为/血气：保留原形状 2000 + 10000×lv²×mijing×xiangu×t×mult，
    端口系数 100×主轨境²（仙古/秘境轨并入主轨，量级对齐冲关成本）。"""
    rng = rng or random.Random()
    lv = int(getattr(doc, "realm_index", 0) or 0) + 1
    plv = int(getattr(doc, "physique_index", 0) or 0) + 1
    t1, t2 = 0.8 + rng.random() * 0.4, 0.8 + rng.random() * 0.4
    xiuwei = int(2000 + (100 * lv * lv * t1) * float(mult))
    xueqi = int(2000 + (100 * plv * plv * t2) * float(mult))
    return xiuwei, xueqi


def source_stone_reward(doc: Any, rolls: int = 1) -> int:
    lv = int(getattr(doc, "realm_index", 0) or 0) + 1
    return 2_000 * max(1, lv) * max(1, int(rolls or 1))


def grant_growth(doc: Any, xiuwei: int = 0, xueqi: int = 0,
                 stone_rolls: int = 0) -> dict:
    """收获入背包（原版 grantXianguGrowthRewards → addXianguBagGrowth）。
    只写 state_of(doc)["bag"]——调用方的 st 必须就是 state_of(doc) 的同一对象。"""
    out = {"xiuwei": max(0, int(xiuwei)), "xueqi": max(0, int(xueqi)), "source_stone": 0}
    if stone_rolls > 0:
        out["source_stone"] = source_stone_reward(doc, stone_rolls)
    bag_add_growth(state_of(doc)["bag"], **out)
    return out


def apply_heavy_injury(st: dict, now: float) -> None:
    """重伤：30 分钟探索效率 -50%。"""
    st["heavy_until"] = max(float(st.get("heavy_until", 0) or 0), now + 1800)


def explore_efficiency(st: Mapping, now: float) -> float:
    return 0.5 if float(st.get("heavy_until", 0) or 0) > now else 1.0


def _hp_of(doc: Any) -> int:
    """当前血量（原版 当前血量 / 血气上限）：端口用 ext["hp"]，缺省回退血气。"""
    ext = getattr(doc, "ext", {}) or {}
    hp = int(float(ext.get("hp", 0) or 0))
    if hp > 0:
        return hp
    return int(float(ext.get("xueqi", 0) or 0)) or 1


def _set_hp(doc: Any, value: int) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["hp"] = max(1, int(value))


# ---------------------------------------------------------------- Boss / 敌人规格

def boss_scaled_stats(xg_level: int, zone_factor: float) -> dict[str, int]:
    """按仙古今世法表缩放（÷1000）：血=玩家境界基础血×factor，攻防减半再减。"""
    row = next((r for r in load_xg_levels() if int(r.get("level_id", 0) or 0) == int(xg_level)), None)
    base_hp = float((row or {}).get("基础血量", 500_000 * xg_level * xg_level) or 0) / 1000.0
    base_atk = float((row or {}).get("基础攻击", 300_000 * xg_level * xg_level) or 0) / 1000.0
    base_def = float((row or {}).get("基础防御", 200_000 * xg_level * xg_level) or 0) / 1000.0
    return {"hp": max(1, int(base_hp * zone_factor)),
            "atk": max(1, int(base_atk * zone_factor * 0.5)),
            "defense": max(1, int(base_def * zone_factor * 0.4))}


def make_enemy(name: str, xg_level: int, zone_factor: float, *,
               bao: float = 0.05, orb: float = 0.1, skills: tuple[str, ...] = (),
               crit: float = 0.1, hp_scale: float = 1.0, atk_scale: float = 1.0,
               def_scale: float = 1.0) -> dict[str, Any]:
    s = boss_scaled_stats(xg_level, zone_factor)
    hp = max(1, int(s["hp"] * hp_scale))
    return {"name": name, "atk": max(1, int(s["atk"] * atk_scale)),
            "defense": max(1, int(s["defense"] * def_scale)), "hp": hp, "hp_max": hp,
            "bao": bao, "orb": orb, "crit": crit, "skills": list(skills),
            "xg_level": xg_level}


# ---------------------------------------------------------------- 道种掉落（xianguSeed.js 移植）

REGULAR_SEED_POOLS: dict[str, tuple[dict, ...]] = {
    "边缘区域": (
        {"名称": "灵火灵种", "类型": "火", "品质": "普通", "融合成功率": 0.6,
         "属性加成": {"攻击加成": 0.02, "血气加成": 0.03}},
        {"名称": "灵水灵种", "类型": "水", "品质": "普通", "融合成功率": 0.6,
         "属性加成": {"防御加成": 0.02, "血气加成": 0.03}},
        {"名称": "灵木灵种", "类型": "木", "品质": "普通", "融合成功率": 0.6,
         "属性加成": {"血气加成": 0.04, "攻击加成": 0.01}},
        {"名称": "灵金灵种", "类型": "金", "品质": "普通", "融合成功率": 0.6,
         "属性加成": {"攻击加成": 0.015, "防御加成": 0.015}},
        {"名称": "灵土灵种", "类型": "土", "品质": "普通", "融合成功率": 0.6,
         "属性加成": {"血气加成": 0.05, "防御加成": 0.01}},
    ),
    "中层区域": (
        {"名称": "灵火道种", "类型": "火", "品质": "普通", "融合成功率": 0.6,
         "属性加成": {"攻击加成": 0.02, "血气加成": 0.03}},
        {"名称": "灵水道种", "类型": "水", "品质": "普通", "融合成功率": 0.6,
         "属性加成": {"防御加成": 0.02, "血气加成": 0.03}},
        {"名称": "灵木道种", "类型": "木", "品质": "普通", "融合成功率": 0.6,
         "属性加成": {"血气加成": 0.04, "攻击加成": 0.01}},
        {"名称": "青鸾焰", "类型": "火", "品质": "稀有", "融合成功率": 0.7,
         "属性加成": {"攻击加成": 0.05, "暴击加成": 0.05}, "专属技能": "青鸾焚天"},
        {"名称": "玄冰魄", "类型": "水", "品质": "稀有", "融合成功率": 0.7,
         "属性加成": {"防御加成": 0.05, "血气加成": 0.03}, "专属技能": "玄冰护体"},
        {"名称": "乙木精", "类型": "木", "品质": "稀有", "融合成功率": 0.7,
         "属性加成": {"血气加成": 0.08, "恢复加成": 0.1}, "专属技能": "乙木逢春"},
        {"名称": "锐金刃", "类型": "金", "品质": "稀有", "融合成功率": 0.7,
         "属性加成": {"攻击加成": 0.06, "穿透加成": 0.1}, "专属技能": "锐金破甲"},
        {"名称": "厚土印", "类型": "土", "品质": "稀有", "融合成功率": 0.7,
         "属性加成": {"防御加成": 0.06, "减伤加成": 0.1}, "专属技能": "厚土无敌"},
    ),
    "深层区域": (
        {"名称": "青鸾焰", "类型": "火", "品质": "稀有", "融合成功率": 0.7,
         "属性加成": {"攻击加成": 0.05, "暴击加成": 0.05}, "专属技能": "青鸾焚天"},
        {"名称": "玄冰魄", "类型": "水", "品质": "稀有", "融合成功率": 0.7,
         "属性加成": {"防御加成": 0.05, "血气加成": 0.03}, "专属技能": "玄冰护体"},
        {"名称": "乙木精", "类型": "木", "品质": "稀有", "融合成功率": 0.7,
         "属性加成": {"血气加成": 0.08, "恢复加成": 0.1}, "专属技能": "乙木逢春"},
        {"名称": "锐金刃", "类型": "金", "品质": "稀有", "融合成功率": 0.7,
         "属性加成": {"攻击加成": 0.06, "穿透加成": 0.1}, "专属技能": "锐金破甲"},
        {"名称": "厚土印", "类型": "土", "品质": "稀有", "融合成功率": 0.7,
         "属性加成": {"防御加成": 0.06, "减伤加成": 0.1}, "专属技能": "厚土无敌"},
        {"名称": "朱雀焚天炎", "类型": "火", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"攻击加成": 0.12, "暴击加成": 0.15, "血气加成": 0.05},
         "专属技能": "朱雀降世", "额外效果": "修炼效率+20%"},
        {"名称": "鲲鹏水灵", "类型": "水", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"血气加成": 0.15, "防御加成": 0.08},
         "专属技能": "鲲鹏展翅", "额外效果": "寿元消耗-30%"},
        {"名称": "混沌金莲", "类型": "金", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"攻击加成": 0.1, "防御加成": 0.1, "血气加成": 0.05},
         "专属技能": "混沌归一", "额外效果": "可兼容多种道则"},
        {"名称": "太虚神土", "类型": "土", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"防御加成": 0.12, "血气加成": 0.08, "减伤加成": 0.15},
         "专属技能": "太虚护体", "额外效果": "减伤额外+15%"},
    ),
    "火道禁区": (
        {"名称": "青鸾焰", "类型": "火", "品质": "稀有", "融合成功率": 0.7,
         "属性加成": {"攻击加成": 0.05, "暴击加成": 0.05}, "专属技能": "青鸾焚天"},
        {"名称": "朱雀焚天炎", "类型": "火", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"攻击加成": 0.12, "暴击加成": 0.15, "血气加成": 0.05},
         "专属技能": "朱雀降世", "额外效果": "修炼效率+20%"},
        {"名称": "太阳神火", "类型": "火", "品质": "传说", "融合成功率": 0.78,
         "属性加成": {"攻击加成": 0.16, "暴击加成": 0.18},
         "专属技能": "大日临空", "额外效果": "火道威能+20%"},
    ),
    "核心区域": (
        {"名称": "朱雀焚天炎", "类型": "火", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"攻击加成": 0.12, "暴击加成": 0.15, "血气加成": 0.05},
         "专属技能": "朱雀降世", "额外效果": "修炼效率+20%"},
        {"名称": "鲲鹏水灵", "类型": "水", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"血气加成": 0.15, "防御加成": 0.08},
         "专属技能": "鲲鹏展翅", "额外效果": "寿元消耗-30%"},
        {"名称": "混沌金莲", "类型": "金", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"攻击加成": 0.1, "防御加成": 0.1, "血气加成": 0.05},
         "专属技能": "混沌归一", "额外效果": "可兼容多种道则"},
        {"名称": "太虚神土", "类型": "土", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"防御加成": 0.12, "血气加成": 0.08, "减伤加成": 0.15},
         "专属技能": "太虚护体", "额外效果": "减伤额外+15%"},
    ),
    "隐藏区域": (
        {"名称": "鲲鹏水灵", "类型": "水", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"血气加成": 0.15, "防御加成": 0.08},
         "专属技能": "鲲鹏展翅", "额外效果": "寿元消耗-30%"},
        {"名称": "混沌金莲", "类型": "金", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"攻击加成": 0.1, "防御加成": 0.1, "血气加成": 0.05},
         "专属技能": "混沌归一", "额外效果": "可兼容多种道则"},
        {"名称": "太虚神土", "类型": "土", "品质": "传说", "融合成功率": 0.75,
         "属性加成": {"防御加成": 0.12, "血气加成": 0.08, "减伤加成": 0.15},
         "专属技能": "太虚护体", "额外效果": "减伤额外+15%"},
    ),
}

QUALITY_WEIGHTS: dict[str, tuple[tuple[str, float], ...]] = {
    "边缘区域": (("普通", 1.0),),
    "中层区域": (("普通", 0.6), ("稀有", 0.4)),
    "深层区域": (("稀有", 0.6), ("传说", 0.4)),
    "火道禁区": (("稀有", 0.25), ("传说", 0.75)),
    "核心区域": (("传说", 1.0),),
    "隐藏区域": (("传说", 1.0),),
}

SEED_NAME_ALIASES = {"世界树嫩芽": "世界树幼苗", "世界树种子": "世界树幼苗",
                     "宇宙雏形种子": "宇宙雏形种", "万道树苗": "万道树", "青月焰种": "青月焰"}


def normalize_seed_name(name: str) -> str:
    return SEED_NAME_ALIASES.get(str(name or "").strip(), str(name or "").strip())


def top_seed_catalog(cfg: Mapping | None = None) -> list[dict]:
    return list(((cfg or load_config()).get("道种配置") or {}).get("顶级道种") or [])


def find_top_seed(name: str, cfg: Mapping | None = None) -> dict | None:
    canon = normalize_seed_name(name)
    return next((s for s in top_seed_catalog(cfg) if s.get("名称") == canon), None)


def find_regular_seed(name: str) -> dict | None:
    canon = normalize_seed_name(name)
    for pool in REGULAR_SEED_POOLS.values():
        for s in pool:
            if s["名称"] == canon:
                return s
    return None


def resolve_seed_record(seed: Mapping | str, cfg: Mapping | None = None) -> dict | None:
    """字符串/旧格式 → 统一道种档案（顶级仙种优先）。"""
    if isinstance(seed, str):
        seed = {"名称": normalize_seed_name(seed)}
    name = normalize_seed_name(str(seed.get("名称") or seed.get("name") or ""))
    if not name:
        return None
    out = {**seed, "名称": name}
    top = find_top_seed(name, cfg)
    if top:
        return {**out, **top, "顶级道种": True}
    reg = find_regular_seed(name)
    if reg:
        return {**out, **reg, "顶级道种": False}
    return out


def _seed_drop_rule(cfg: Mapping, location: str) -> dict:
    return ((cfg.get("道种配置") or {}).get("区域掉落") or {}).get(location) or {}


def should_drop_seed(cfg: Mapping, location: str, source: str = "treasure",
                     rng: Callable[[], float] | None = None) -> bool:
    rule = _seed_drop_rule(cfg, location)
    key = {"boss": "Boss道种率", "unique": "唯一机缘道种率"}.get(source, "机缘格道种率")
    return (rng or random.Random()).random() < max(0.0, min(1.0, float(rule.get(key, 0) or 0)))


def should_drop_seed_b(doc: Any, cfg: Mapping, location: str, source: str = "treasure",
                       rng: Callable[[], float] | None = None) -> bool:
    """带天神书院仙院加成（×1.1）的道种掉落判定（W28）。"""
    try:
        from . import academy as _acd
        bonus = _acd.seed_rate_bonus(doc)
    except Exception:
        bonus = 0.0
    rule = _seed_drop_rule(cfg, location)
    key = {"boss": "Boss道种率", "unique": "唯一机缘道种率"}.get(source, "机缘格道种率")
    chance = max(0.0, min(1.0, float(rule.get(key, 0) or 0))) * (1.0 + max(0.0, bonus))
    return (rng or random.Random()).random() < min(1.0, chance)


def _weighted_pick(entries: list, get_weight: Callable, rng: Callable[[], float]) -> Any:
    if not entries:
        return None
    total = sum(max(0.0, float(get_weight(e)) or 0) for e in entries)
    if total <= 0:
        return _pick(rng, entries)
    roll = rng.random() * total
    for e in entries:
        roll -= max(0.0, float(get_weight(e)) or 0)
        if roll < 0:
            return e
    return entries[-1]


def draw_seed(cfg: Mapping, location: str, fragment_id: str | None = None,
              source: str = "treasure", force_top: bool = False,
              rng: Callable[[], float] | None = None) -> dict:
    """先按区域/碎片判定顶级仙种，再回退区域常规池（原版 drawXianguSeed）。"""
    rng = rng or random.Random()
    rule = _seed_drop_rule(cfg, location)
    top_key = {"boss": "Boss顶级道种占比", "unique": "唯一机缘顶级道种占比"}.get(source, "顶级道种占比")
    top_chance = 1.0 if force_top else max(0.0, min(1.0, float(rule.get(top_key, 0) or 0)))
    catalog = top_seed_catalog(cfg)
    regional = [s for s in catalog
                if location in (s.get("出现区域") or [])
                and (not fragment_id or not s.get("出现碎片") or fragment_id in (s.get("出现碎片") or []))]
    if regional and rng.random() < top_chance:
        chosen = _weighted_pick(regional, lambda s: s.get("权重", 1), rng)
        return {"名称": chosen["名称"], "品质": chosen.get("品质", "神话"),
                "类型": chosen.get("类型"), "融合成功率": float(chosen.get("融合成功率", 0.8) or 0.8),
                "属性加成": dict(chosen.get("属性加成") or {}),
                "专属技能": chosen.get("专属技能"), "额外效果": chosen.get("额外效果"),
                "极境名称": f"神火极境·{chosen['名称']}", "顶级道种": True, "掉落来源": source}
    pool = list(REGULAR_SEED_POOLS.get(location) or REGULAR_SEED_POOLS["边缘区域"])
    weights = QUALITY_WEIGHTS.get(location) or QUALITY_WEIGHTS["边缘区域"]
    quality = _weighted_pick(list(weights), lambda w: w[1], rng)
    quality = quality[0] if isinstance(quality, tuple) else quality
    cands = [s for s in pool if s["品质"] == quality] or pool
    chosen = _pick(rng, cands)
    return {"名称": chosen["名称"], "品质": chosen["品质"], "类型": chosen["类型"],
            "融合成功率": chosen["融合成功率"], "属性加成": dict(chosen["属性加成"]),
            "专属技能": chosen.get("专属技能"), "额外效果": chosen.get("额外效果"),
            "顶级道种": False}


def seed_view_text(st: Mapping, cfg: Mapping | None = None) -> str:
    """#查看道种：背包道种 + 纳戒可借道种（列表）。"""
    bag = st.get("bag") or {}
    lines = ["【道种·仙古遗泽】"]
    if bag.get("seeds"):
        for s in bag["seeds"]:
            rec = resolve_seed_record(s, cfg)
            lines.append(f"◇ {rec['名称']} [{rec.get('品质', '普通')}] "
                         f"融合成功率 {(float(rec.get('融合成功率', 0.6)) * 100):.0f}%"
                         + ("（顶级仙种）" if rec.get("顶级道种") else ""))
    else:
        lines.append("尚未寻得任何道种。")
    lines += ["", "核心区域可 #借助<道种名>点燃神火；顶级仙种可达成对应神火极境。"]
    return "\n".join(lines)


# ---------------------------------------------------------------- 生命周期（xianguLifecycle.js 简化移植）

LIFE_BLOOM_INTERVAL_Y = 2_000
LIFE_PREPARE_Y = 1_000
LIFE_OPEN_Y = 10_000
LIFE_REOPEN_COOLDOWN_Y = 10_000


def world_state(cal: Mapping) -> dict[str, Any]:
    """calamity_state["xiangu"] 读写入口（调用方持 calamity_lock）。"""
    raw = cal.get("xiangu")
    return raw if isinstance(raw, dict) else {}


def lifecycle_of(world: Mapping) -> dict[str, Any]:
    lc = world.get("lifecycle")
    if not isinstance(lc, dict):
        lc = {}
    lc.setdefault("stage", "closed")            # closed / preparing / open
    lc.setdefault("prep_end_year", 0)
    lc.setdefault("open_year", 0)
    lc.setdefault("close_year", 0)
    lc.setdefault("next_check_year", 0)
    lc.setdefault("session", "")
    lc.setdefault("prob", 0.05)
    return lc


def advance_lifecycle(lc: dict, world_year: int, rng: Callable[[], float]) -> str | None:
    """推进一轮：preparing 到期开秘境；open 到期闭合；closed 到 2000 年里程碑掷概率。
    返回 transition：None / 'preparing' / 'opened' / 'closed'。"""
    year = max(0, int(world_year))
    stage = lc.get("stage")
    if stage == "preparing":
        if year < int(lc.get("prep_end_year", 0) or 0):
            return None
        lc["stage"] = "open"
        lc["open_year"] = year
        lc["close_year"] = year + LIFE_OPEN_Y
        lc["next_check_year"] = year + LIFE_REOPEN_COOLDOWN_Y
        lc["session"] = f"xiangu-{year}"
        lc["prob"] = 0.05
        return "opened"
    if stage == "open":
        if year < int(lc.get("close_year", 0) or 0):
            return None
        lc["stage"] = "closed"
        lc["session"] = ""
        return "closed"
    # closed
    if year < int(lc.get("next_check_year", 0) or 0):
        return None
    lc["next_check_year"] = year + LIFE_BLOOM_INTERVAL_Y
    if rng.random() < float(lc.get("prob", 0.05) or 0.05):
        lc["prob"] = 0.05
        lc["stage"] = "preparing"
        lc["prep_end_year"] = year + LIFE_PREPARE_Y
        return "preparing"
    lc["prob"] = min(1.0, float(lc.get("prob", 0.05) or 0.05) + 0.10)
    return None


def lifecycle_brief(lc: Mapping, world_year: int) -> str:
    stage = lc.get("stage", "closed")
    year = max(0, int(world_year))
    icon = {"open": "🌺", "preparing": "🌱", "closed": "❄️"}.get(stage, "❄️")
    if stage == "open":
        remain = max(0, int(lc.get("close_year", 0)) - year)
        return f"{icon} 仙古花蕾·绽放中（ session {lc.get('session') or '-'}｜余 {remain} 年）"
    if stage == "preparing":
        remain = max(0, int(lc.get("prep_end_year", 0)) - year)
        return f"{icon} 仙古花蕾·现世凝聚（尚需 {remain} 年绽放）"
    return f"{icon} 仙古花蕾·沉寂（气运汇聚中，开启概率 {float(lc.get('prob', 0.05)):.0%}）"


def entry_gate(doc: Any, st: Mapping, lc: Mapping, world_year: int, now: float,
               plane_name: str) -> str | None:
    """#进入仙古秘境 四重门：生命周期 / 境界带 / 位面 / 冷却。"""
    if lc.get("stage") != "open":
        return ("【仙古未开·时机未至】\n仙古花蕾尚未绽放，秘境壁垒坚如仙金。\n"
                + lifecycle_brief(lc, world_year))
    lv = xg_level_of(doc)
    if lv < XG_ENTRY_MIN:
        return (f"【仙古未开·境界不足】非铭文境不可撼动秘境壁垒！\n"
                f"当前仙古境界：{realm_name(lv)}（{lv}/11），"
                f"需 {realm_name(XG_ENTRY_MIN)}（主轨第 {(XG_ENTRY_MIN - 2) * XG_LEVEL_DIV + 1} 境）。")
    if lv > XG_ENTRY_MAX:
        return ("【境界超限·秘境排斥】尊者境以上威能会破坏秘境平衡。\n"
                f"当前仙古境界：{realm_name(lv)}——请以天骄之身另寻机缘。")
    if plane_name != "九天十地":
        return f"【时空错乱·位面不符】仙古秘境只在九天十地位面显现（当前：{plane_name}）。"
    cd_until = float((st.get("cd") or {}).get("enter_until", 0) or 0)
    if now < cd_until:
        remain_h = (cd_until - now) / 3600
        return f"【秘境休整·冷却中】还需 {remain_h:.1f} 小时方可再入。"
    return None


# ---------------------------------------------------------------- 唯一机缘 / 机缘格认领（全服幂等）

def claim_scope(seed: str, fragment_id: str, entity: str) -> str:
    return f"{seed}:{fragment_id}:{entity}"


def prune_round_claims(world: dict, seed: str) -> int:
    """轮次闭合后清理该轮的一次性认领（机缘格 cell:* / NPC 死亡 npc:*）。
    唯一机缘 unique:* 与冠军造化 claim_scope=round-champion 永久保留
    （原版 Redis TTL 语义：一次性键随轮次过期，天地唯一键永存）。"""
    claims = world.get("claims") or {}
    stale = [k for k in claims
             if k.startswith(f"{seed}:") and (":cell:" in k or ":npc:" in k)]
    for k in stale:
        del claims[k]
    return len(stale)


def world_claim(world: dict, scope: str) -> dict | None:
    return ((world.get("claims") or {}).get(scope)) or None


def world_claim_put(world: dict, scope: str, claimant_id: str, claimant_name: str,
                    now: float) -> dict:
    claims = world.setdefault("claims", {})
    rec = {"claimant": str(claimant_id), "name": str(claimant_name), "at": now}
    claims[scope] = rec
    return rec


def sync_shared_claims(st: dict, world: Mapping) -> bool:
    """把全服认领同步进个人地图（机缘格/唯一机缘→已搜/已领）。"""
    seed = str(st.get("world_seed") or "")
    map_st = st.get("map")
    if not map_st:
        return False
    changed = False
    for name, treasure in (map_st.get("unique_treasures") or {}).items():
        if treasure.get("claimed") or treasure.get("kind") == MARROW_POOL_KIND:
            continue
        if world_claim(world, claim_scope(seed, map_st["fragment_id"], f"unique:{name}")):
            treasure["claimed"] = True
            tx, ty = treasure["pos"]["x"], treasure["pos"]["y"]
            if map_st["grid"][ty][tx] == CELL_UNIQUE:
                map_st["grid"][ty][tx] = CELL_EXPLORED
            changed = True
    for y in range(int(map_st["h"])):
        for x in range(int(map_st["w"])):
            if map_st["grid"][y][x] == CELL_TREASURE and \
                    world_claim(world, claim_scope(seed, map_st["fragment_id"], f"cell:{x},{y}")):
                map_st["grid"][y][x] = CELL_EXPLORED
                changed = True
    return changed


def exit_discovery_daoyun(st: dict, map_st: Mapping, before_count: int, doc: Any) -> int:
    """出口悟道：新探明出口 × 5 × 仙古境界（写入调用方传入的 st）。"""
    newly = max(0, len(revealed_exits(map_st)) - before_count)
    if newly == 0:
        return 0
    gain = newly * 5 * max(1, xg_level_of(doc))
    gains = st.setdefault("gains", {})
    gains["daoyun"] = int(gains.get("daoyun", 0) or 0) + gain
    return gain


# ---------------------------------------------------------------- 仙髓池

def is_marrow_position(map_st: Mapping, x: int, y: int) -> bool:
    return any(t.get("kind") == MARROW_POOL_KIND and t["pos"]["x"] == x and t["pos"]["y"] == y
               for t in (map_st.get("unique_treasures") or {}).values())


def place_marrow_pool(map_st: dict, rng: Callable[[], float]) -> dict | None:
    """放置万道仙髓池（个人地图结算，无跨玩家争抢）。"""
    for name, t in (map_st.get("unique_treasures") or {}).items():
        if t.get("kind") == MARROW_POOL_KIND:
            return None
    h, w = int(map_st["h"]), int(map_st["w"])
    cands = [{"x": x, "y": y} for y in range(1, h - 1) for x in range(1, w - 1)
             if map_st["grid"][y][x] == CELL_EMPTY
             and not (x == map_st["pos"]["x"] and y == map_st["pos"]["y"])]
    if not cands:
        return None
    pos = _pick(rng, cands)
    key = f"{MARROW_POOL_NAME}@{pos['x']},{pos['y']}"
    suffix = 2
    while key in map_st["unique_treasures"]:
        key = f"{MARROW_POOL_NAME}@{pos['x']},{pos['y']}#{suffix}"
        suffix += 1
    map_st["unique_treasures"][key] = {
        "kind": MARROW_POOL_KIND, "name": MARROW_POOL_NAME, "pos": pos,
        "claimed": False, "dist_echo": 2,
        "echo": {2: "远处传来水波声，万道残韵随之轻鸣...",
                 1: "仙髓气息扑面而来，一方宝池已近在眼前！"},
        "desc": "仙古万道残韵沉积而成的仙髓宝池，可洗炼根骨、增益潜力"}
    map_st["grid"][pos["y"]][pos["x"]] = CELL_UNIQUE
    map_st["revealed"][pos["y"]][pos["x"]] = True
    _ensure_exit_connectivity(map_st["grid"], map_st["pos"], [pos])
    return {"key": key, "pos": pos}


def marrow_rewards(doc: Any, mult: float, rng: Callable[[], float]) -> dict[str, int]:
    """仙髓池浸泡收益（原版 calculateXianguMarrowPoolRewards ÷1000）。"""
    lv = int(getattr(doc, "realm_index", 0) or 0) + 1
    plv = int(getattr(doc, "physique_index", 0) or 0) + 1
    xg = xg_level_of(doc)
    xiuwei = int((2000 + 100 * lv * lv * xg * (2 + rng.random())) * mult)
    xueqi = int((2000 + 100 * plv * plv * xg * (2 + rng.random())) * mult)
    return {"xiuwei": xiuwei, "xueqi": xueqi}


# ---------------------------------------------------------------- 撤离（xianguEvacuation.js 移植）

def evac_duration(mode: str, loot_units: int) -> int:
    cfg = evac_config()
    m = cfg["emergency" if mode == "emergency" else "normal"]
    return int(min(m["max"], m["base"] + max(0, int(loot_units)) * m["per_loot"]))


def begin_evacuation(doc: Any, st: dict, mode: str, now: float) -> dict | None:
    """创建撤离读条状态；normal 需在核心碎片。返回 None 表示不可发起。"""
    map_st = st.get("map") or {}
    if not st.get("active"):
        return None
    if mode == "normal" and map_st.get("fragment_id") != CORE_FRAGMENT:
        return None
    loot = bag_summary(st.get("bag") or {})["loot_units"]
    duration = evac_duration(mode, loot)
    # st 内时间统一毫秒（对齐原版 Date.now()；ready_at/expires_at/cd/heavy_until 均为 ms）
    ready_at = now + duration * 1000
    st["evac"] = {"mode": mode, "started_at": now, "ready_at": ready_at,
                  "expires_at": ready_at + evac_config()["window"] * 1000,
                  "fragment_id": map_st.get("fragment_id", ""),
                  "pos": dict(map_st.get("pos") or {"x": 0, "y": 0}),
                  "hp": _hp_of(doc),
                  "loot_units": loot, "run_id": (st.get("run") or {}).get("run_id", "")}
    return st["evac"]


def validate_evacuation(st: Mapping, doc: Any, now: float) -> tuple[bool, str, int]:
    """返回 (ok, code, remaining_seconds)。"""
    evac = st.get("evac")
    if not isinstance(evac, dict):
        return False, "missing", 0
    run_id = str((st.get("run") or {}).get("run_id", ""))
    if not run_id or run_id != str(evac.get("run_id", "")):
        return False, "run_mismatch", 0
    if now >= float(evac.get("expires_at", 0) or 0):
        return False, "expired", 0
    if not st.get("active"):
        return False, "not_in_xiangu", 0
    map_st = st.get("map") or {}
    fid = str(map_st.get("fragment_id", ""))
    if str(evac.get("mode")) == "normal" and \
            (str(evac.get("fragment_id")) != CORE_FRAGMENT or fid != CORE_FRAGMENT):
        return False, "not_in_core", 0
    pos = evac.get("pos") or {}
    cur = map_st.get("pos") or {}
    if fid != str(evac.get("fragment_id")) or \
            int(cur.get("x", -1)) != int(pos.get("x", -2)) or \
            int(cur.get("y", -1)) != int(pos.get("y", -2)):
        return False, "moved", 0
    hp0 = int(float(evac.get("hp", 0) or 0))
    if hp0 > 0 and _hp_of(doc) < hp0:
        return False, "damaged", 0
    remain = int(float(evac.get("ready_at", 0)) - now)
    if remain > 0:
        return False, "not_ready", (remain + 999) // 1000
    return True, "ready", 0


def convert_evacuation_items(bag: Mapping) -> dict[str, Any]:
    """撤离物品转化：残兵→庚金玄土；基础战利品→源石/灵石（原版 convertXianguEvacuationItems）。"""
    refine = {"残破战戟", "断裂古剑", "破碎神甲碎片", "古盾残片", "仙古符骨"}
    currency = {"普通道种碎片", "仙古矿材", "古兽残骨", "秘境灵药", "远古符纸"}
    value = 10_000  # 原版 1_000_000 ÷1000
    out: list[dict] = []
    source_stone = lingshi = refined = currency_count = 0
    for item in bag.get("items", ()):
        name = str(item.get("name") or "").strip()
        qty = max(0, int(item.get("quantity", 0) or 0))
        if not name or qty <= 0:
            continue
        if name in refine:
            for e in out:
                if e["name"] == "庚金玄土":
                    e["quantity"] += qty
                    break
            else:
                out.append({"name": "庚金玄土", "type": "材料", "quantity": qty,
                            "desc": "以仙古战场残兵碎片熔炼出的庚金玄土，可用于锻造与祭炼。"})
            refined += qty
            continue
        if name in currency:
            source_stone += qty * value
            lingshi += qty * value
            currency_count += qty
            continue
        out.append(json.loads(json.dumps(item, ensure_ascii=False)))
    return {"items": out, "source_stone": source_stone, "lingshi": lingshi,
            "refined": refined, "currency_count": currency_count}


def run_summary(st: Mapping, now: float) -> dict[str, Any]:
    """本轮汇总（撤离结算与目标页共用）。"""
    run = st.get("run") or {}
    bag = bag_summary(st.get("bag") or {})
    started = float(run.get("started_at", 0) or st.get("entry_at", 0) or now)
    return {
        "run_id": str(run.get("run_id", "")),
        "minutes": max(0, int((now - started) / 60000)),
        "item_count": bag["item_count"], "seed_count": bag["seed_count"],
        "seed_names": [str(s.get("名称") or s) for s in bag["seeds"]],
        "technique_count": bag["technique_count"],
        "source_stone": int(bag.get("source_stone", 0) or 0),
        "xiuwei": int(bag.get("xiuwei", 0) or 0), "xueqi": int(bag.get("xueqi", 0) or 0),
        "potential": int(bag.get("potential", 0) or 0),
        "daoyun": int((st.get("gains") or {}).get("daoyun", 0) or 0),
        "unique_found": int((st.get("gains") or {}).get("unique_found", 0) or 0),
        "kill_delta": max(0, int(st.get("kills", 0) or 0) - int(run.get("start_kills", 0) or 0)),
        "infamy_delta": float(st.get("infamy", 0) or 0) - float(run.get("start_infamy", 0) or 0),
        "loot_units": bag["loot_units"],
    }


# ---------------------------------------------------------------- 探索选项（performExplore）

_LOCATION_RISKS: dict[str, dict[str, float]] = {
    "边缘区域": {"risk": 0.10, "reward": 30, "boss": 0.02, "success": 0.70},
    "中层区域": {"risk": 0.30, "reward": 60, "boss": 0.15, "success": 0.60},
    "深层区域": {"risk": 0.50, "reward": 100, "boss": 0.30, "success": 0.50},
    "核心区域": {"risk": 0.70, "reward": 150, "boss": 0.50, "success": 0.40},
    "火道禁区": {"risk": 0.80, "reward": 200, "boss": 0.60, "success": 0.35},
}

_LOCATION_ITEMS: dict[str, tuple[dict, ...]] = {
    "边缘区域": (
        {"name": "残破灵符", "type": "道具", "rarity": "普通", "desc": "蕴含微弱灵力的符箓，可用于基础交易"},
        {"name": "源石矿髓", "type": "材料", "rarity": "普通", "desc": "仙古矿脉凝结的源石矿髓"},
        {"name": "引气丹", "type": "丹药", "rarity": "优秀", "desc": "帮助引气入体的丹药，效果微弱"},
        {"name": "百断山碎片", "type": "材料", "rarity": "稀有", "desc": "百断山崩碎后遗留的碎片，蕴藏古老符文"},
        {"name": "原始骨文", "type": "材料", "rarity": "稀有", "desc": "刻画在上古兽骨上的原始骨文"},
        {"name": "灵血草", "type": "丹药", "rarity": "普通", "desc": "可补充少量血气的常见灵草"}),
    "中层区域": (
        {"name": "神源石", "type": "道具", "rarity": "优秀", "desc": "封存着浓郁源气的神源石"},
        {"name": "破境丹", "type": "丹药", "rarity": "稀有", "desc": "增加突破成功率的神秘丹药"},
        {"name": "仙古遗种蛋", "type": "道具", "rarity": "史诗", "desc": "一枚沉睡的遗种之蛋，蕴含古老血脉"},
        {"name": "十凶残魂", "type": "材料", "rarity": "稀有", "desc": "十凶残留的一缕魂魄，可用于炼器"},
        {"name": "鲲鹏羽", "type": "材料", "rarity": "稀有", "desc": "鲲鹏脱落的一根羽毛，蕴含极速道则"},
        {"name": "雷池液", "type": "道具", "rarity": "史诗", "desc": "雷帝沐浴的雷池遗液，可淬炼肉身"},
        {"name": "柳神法残篇", "type": "材料", "rarity": "传说", "desc": "柳神涅槃大法的残篇，蕴含生命真谛"}),
    "深层区域": (
        {"name": "上品神源石", "type": "道具", "rarity": "稀有", "desc": "源气近乎化液的上品神源石"},
        {"name": "悟道古茶叶", "type": "道具", "rarity": "传说", "desc": "蕴含大道道韵，可用于古茶悟道"},
        {"name": "仙血精华", "type": "材料", "rarity": "传说", "desc": "蕴含仙古纪元仙人血液的精华"},
        {"name": "天角蚁宝术残篇", "type": "功法", "rarity": "传说", "desc": "天角蚁一族的力之极尽奥义残篇"},
        {"name": "仙火髓", "type": "材料", "rarity": "传说", "desc": "仙域神火燃尽后留下的精髓"},
        {"name": "折仙咒碎片", "type": "材料", "rarity": "传说", "desc": "折仙咒碑碎裂脱落的碎片，蕴含诅咒之力"},
        {"name": "补天术残篇", "type": "材料", "rarity": "传说", "desc": "女娲补天之术的残篇，可修补道基缺陷"},
        {"name": "黑暗物质样本", "type": "材料", "rarity": "史诗", "desc": "黑暗牢笼中逸散的神秘物质"}),
    "核心区域": (
        {"name": "超品神源石", "type": "道具", "rarity": "传说", "desc": "仙古矿脉核心孕育的超品神源石"},
        {"name": "道韵碎片", "type": "材料", "rarity": "传说", "desc": "蕴含完整道则的碎片，价值连城"},
        {"name": "仙古真血", "type": "材料", "rarity": "史诗", "desc": "一滴仙古纪元真仙的精血"},
        {"name": "无上神物", "type": "道具", "rarity": "神话", "desc": "弥合帝劫道基并修复一处道果瑕疵"}),
    "火道禁区": (
        {"name": "万火深渊", "type": "试炼", "rarity": "传说", "trial": True,
         "desc": "万火深渊深处——祭炼真我者感悟大道的试炼地，渡过者可得火道道种"},
        {"name": "神火本源", "type": "材料", "rarity": "神话", "desc": "神火的本源之力，可大幅提升神火品质"}),
}

_SPECIAL_ITEMS: dict[str, tuple[dict, ...]] = {
    "边缘区域": (),
    "中层区域": (
        {"name": "仙药园令牌", "type": "道具", "rarity": "稀有", "desc": "可召唤一处临时仙药园的令牌"},
        {"name": "传承石碑", "type": "传承", "rarity": "史诗", "desc": "刻有古代修士传承的石碑"},
        {"name": "不死神药种子", "type": "仙种", "rarity": "传说", "desc": "传说中能活出第二世的不死神药之种"},
        {"name": "真龙逆鳞", "type": "材料", "rarity": "传说", "desc": "真龙身上最坚硬的逆鳞，可炼制至宝"}),
    "深层区域": (
        {"name": "仙王讲道录", "type": "传承", "rarity": "传说", "desc": "记载仙王讲道的玉简，蕴含无上道法"},
        {"name": "黑暗牢笼钥匙", "type": "道具", "rarity": "史诗", "desc": "传说可开启黑暗牢笼深处秘藏的钥匙"},
        {"name": "三千道火", "type": "试炼", "rarity": "传说", "trial": True,
         "desc": "触及三千道火试炼——三千种大道之火汇聚成的火海，熬过去可淬炼出三千道火种！"}),
    "核心区域": (
        {"name": "唯一道则碎片", "type": "传说", "rarity": "神话", "desc": "蕴含完整大道的至高之物，全图仅此一份"},
        {"name": "仙古花蕾精华", "type": "材料", "rarity": "神话", "desc": "仙古花蕾凝聚的至高精华"},
        {"name": "鸿蒙紫气", "type": "材料", "rarity": "神话", "desc": "开天辟地前的原始之气，价值无法估量"},
        {"name": "唯一真血", "type": "材料", "rarity": "神话", "desc": "来自不可名状存在的唯一真血，世间仅此一滴"}),
}

_BOSS_DEFS: dict[str, tuple[dict, ...]] = {
    "中层区域": (
        {"name": "真龙残魂", "skills": ("龙吟九天", "真龙摆尾", "龙战于野"),
         "drops": (("真龙宝术", "功法", 0.10, "史诗"), ("真龙龙鳞", "道具", 0.50, "稀有"))},
        {"name": "仙药守护兽", "skills": ("守护之怒", "药香迷惑", "灵根护体"),
         "drops": (("不死神药幼苗", "仙种", 0.05, "传说"), ("守护兽内丹", "材料", 0.40, "稀有"))}),
    "深层区域": (
        {"name": "仙王残念", "skills": ("轮回印", "无终一击", "仙王道则"),
         "drops": (("六道轮回天功", "功法", 0.08, "传说"), ("仙王精血", "材料", 0.30, "传说"))},
        {"name": "黑暗古祖", "skills": ("黑暗侵蚀", "不朽之触", "黑暗牢笼"),
         "drops": (("黑暗物质样本", "材料", 0.40, "稀有"), ("折仙咒原本", "材料", 0.15, "传说"))}),
    "核心区域": (
        {"name": "仙古意志投影", "skills": ("法则压制", "道则领域", "天罚降临"),
         "drops": (("道韵结晶", "材料", 0.30, "神话"), ("法则感悟", "材料", 0.50, "传说"))},
        {"name": "纪元终结者", "skills": ("纪元终结", "时间静止", "因果抹杀"),
         "drops": (("时间法则碎片", "材料", 0.20, "神话"), ("唯一道则", "材料", 0.05, "神话"))}),
}


def explore_options(location: str, rng: Callable[[], float]) -> list[dict]:
    base = [
        {"id": "daoyun", "icon": "🌊", "label": "东方·灵力波动涌来——感应到浓郁道韵",
         "bias": {"daoyun": 0.5, "item": 0.2, "fight": 0.15, "special": 0.1}},
        {"id": "item", "icon": "💎", "label": "西方·古物气息弥漫——似乎有宝物埋藏",
         "bias": {"item": 0.5, "daoyun": 0.2, "lingshi": 0.2, "special": 0.1}},
        {"id": "fight", "icon": "⚔️", "label": "深处·隐约传来打斗声——或有战斗",
         "bias": {"fight": 0.5, "lingshi": 0.2, "item": 0.2, "daoyun": 0.1}},
    ]
    if location in ("深层区域", "核心区域", "火道禁区"):
        base.append({"id": "special", "icon": "✨", "label": "北方·古老遗迹显现——可能有惊天发现",
                     "bias": {"special": 0.5, "daoyun": 0.2, "item": 0.2, "fight": 0.1}})
    if location == "火道禁区":
        base.append({"id": "seed", "icon": "🌟", "label": "深渊·三千道火翻涌——感悟火道道种气息",
                     "bias": {"item": 0.5, "special": 0.2, "daoyun": 0.2, "fight": 0.1}})
    return _shuffle(rng, base)[:3]


def options_text(options: list[dict]) -> str:
    lines = ["【神识探索·三径择一】"]
    for i, opt in enumerate(options, 1):
        lines.append(f"{i}. {opt['icon']} {opt['label']}")
    lines += ["", "回复 1/2/3 选择探索方向。"]
    return "\n".join(lines)


def _flame_trial(doc: Any, st: dict, now: float,
                 rng: Callable[[], float]) -> tuple[str, dict]:
    """三千道火试炼：三波焚身，扛过得三千道火种 + 道火精粹。"""
    hp_max = _hp_max_of(doc)
    hp = _hp_of(doc)
    for i in range(3):
        burn = int(hp_max * 0.15 * (1 + i * 0.3))
        hp -= burn
        if hp <= 0:
            _set_hp(doc, 1)
            return ("\n".join([
                "【三千道火·大道试炼】", "",
                "第一波道火焚身，肉身龟裂！",
                "第二波道火袭来，道基震颤！",
                "第三波道火铺天盖地，你终于支撑不住...", "",
                "【试炼失败】生命降至 1 点，需休养后再挑战。"]), {})
        _set_hp(doc, hp)
    _set_hp(doc, max(1, int(hp_max * 0.2)))
    st["daohuo_jingcui"] = int(st.get("daohuo_jingcui", 0) or 0) + 1
    seed = {"名称": "三千道火种", "品质": "神话", "类型": "火道", "融合成功率": 0.95,
            "属性加成": {"攻击加成": 0.1, "血气加成": 0.1},
            "专属技能": "万火共鸣", "额外效果": "不受秘境境界压制", "顶级道种": False}
    bag_add_seed(st["bag"], seed)
    return "\n".join([
        "【三千道火·大道试炼·通过！！！】", "",
        "第一波道火焚身——肉身抽搐，却咬牙坚持！",
        "第二波道火更烈——道基轰鸣，血液都在沸腾！",
        "第三波道火铺天盖地——你硬扛三千道火！", "",
        "【获得】三千道火种 [神话]｜道火精粹 +1",
        "专属技能：万火共鸣｜融合成功率 95%"]), {"daoyun": 20}


def perform_explore(doc: Any, st: dict, location: str, bias: Mapping | None,
                    cfg: Mapping, rng: Callable[[], float], now: float,
                    battle: Callable[[dict, str], tuple[bool, list[str]]] | None = None,
                    crowned: bool = False) -> tuple[str, dict]:
    """探索选择结算（原版 performExplore）。返回 (message, extra_gains)。

    battle(enemy_spec, battle_type) -> (won, log_lines)：handler 组装双方走
    combat.run_1v1；core 只产出敌规格并消费战果。
    """
    gains: dict[str, int] = {}
    risk = _LOCATION_RISKS.get(location) or _LOCATION_RISKS["边缘区域"]
    infamy = int(st.get("infamy", 0) or 0)
    eff = explore_efficiency(st, now)
    risk_mult = min(1.0, risk["risk"] + min(0.5, infamy / 500))
    boss_chance = min(1.0, risk["boss"] + infamy / 1000)
    success = min(0.95, risk["success"] + (xg_level_of(doc) - 5) * 0.03) * eff

    # 门槛检查：凶名 PvP 伏击预警（不做真实 PvP，警示文案）
    thresholds = {"daoyun": 0.40, "lingshi": 0.30, "item": 0.15, "fight": 0.10, "special": 0.05}
    for key, boost in (bias or {}).items():
        thresholds[key] = thresholds.get(key, 0.1) + float(boost) * 0.5
    total = sum(thresholds.values()) or 1.0
    thresholds = {k: v / total for k, v in thresholds.items()}

    if rng.random() >= success:
        fails = (f"{getattr(doc, 'name', '')}在{location}中搜索良久，却一无所获...",
                 "岁月沧桑，此地机缘早已被前人取尽...",
                 "迷雾重重，方向难辨，探索无果...")
        return ("\n".join(["【探索·无果】", "", _pick(rng, list(fails)), "",
                           f"【探索统计】位置：{location}｜危险：{'★' * int(risk['risk'] * 5 + 1)}"]), gains)

    mult = risk["reward"] / 30.0
    roll = rng.random()
    cum = 0.0
    kind = "special"
    for key in ("daoyun", "lingshi", "item", "fight"):
        cum += thresholds[key]
        if roll < cum:
            kind = key
            break

    if kind == "daoyun":
        gain = int(risk["reward"] * (0.8 + rng.random() * 0.4))
        gains["daoyun"] = gains.get("daoyun", 0) + gain
        st.setdefault("gains", {})
        st["gains"]["daoyun"] = int(st["gains"].get("daoyun", 0) or 0) + gain
        xw, xq = calc_rewards(doc, mult, rng)
        rw = grant_growth(doc, xw, xq)
        msg = "\n".join([
            "【探索·道韵领悟】", "",
            f"{getattr(doc, 'name', '')}盘膝而坐，感悟{location}中的残留道则...", "",
            f"【获得】道韵 +{gain}｜修为 +{rw['xiuwei']:,}｜血气 +{rw['xueqi']:,}",
            f"当前位置道韵：{st['gains']['daoyun']} 💎"])
        return msg, gains

    if kind == "lingshi":
        xw, xq = calc_rewards(doc, mult, rng)
        stone = int(5_000 * mult * (0.8 + rng.random() * 0.4))
        rw = grant_growth(doc, xw, xq, stone_rolls=1)
        msg = "\n".join([
            "【探索·源石矿脉】", "",
            f"{getattr(doc, 'name', '')}挖掘出一处仙古源石矿脉，浓郁源气自裂隙间喷薄而出！", "",
            f"【获得】源石 +{rw['source_stone']:,}（暂存秘境背包）｜"
            f"修为 +{rw['xiuwei']:,}｜血气 +{rw['xueqi']:,}"])
        return msg, gains

    if kind == "item":
        items = list(_LOCATION_ITEMS.get(location) or _LOCATION_ITEMS["边缘区域"])
        item = _pick(rng, items)
        if item.get("trial"):
            text, extra = _flame_trial(doc, st, now, rng)
            for k, v in extra.items():
                gains[k] = gains.get(k, 0) + v
            return "【探索·奇遇·试炼】" + text, gains
        bag_add_item(st["bag"], item)
        gains[item["name"]] = 1
        xw, xq = calc_rewards(doc, mult, rng)
        rw = grant_growth(doc, xw, xq)
        msg = "\n".join([
            f"【探索·奇遇·{item['rarity']}】", "",
            f"{getattr(doc, 'name', '')}在{location}深处发现一处隐蔽的遗迹...", "",
            f"【获得】{item['name']} × 1｜修为 +{rw['xiuwei']:,}｜血气 +{rw['xueqi']:,}",
            "", f"【物品说明】{item['desc']}"])
        return msg, gains

    if kind == "fight":
        if rng.random() < min(0.3, infamy / 500):
            return "\n".join([
                "【遭遇·伏击】", "",
                f"{getattr(doc, 'name', '')}在{location}探索时突感杀意凛然——有修士伏击！", "",
                f"因凶名过盛（{infamy}），你的行踪已经暴露！",
                "建议前往核心区域撤离，或循地图反杀猎手。"]), gains
        zone_factor = {"边缘区域": 0.1, "中层区域": 0.2, "深层区域": 0.4,
                       "核心区域": 0.6, "火道禁区": 0.8}.get(location, 0.1)
        if rng.random() < boss_chance:
            return _explore_boss(doc, st, location, cfg, rng, mult, battle, zone_factor), gains
        enemy_names = ("仙古遗种", "秘境守卫", "迷途怨灵", "异域修士")
        name = _pick(rng, list(enemy_names))
        lv = xg_level_of(doc)
        enemy = make_enemy(name, max(2, lv - 1), zone_factor, bao=0.03, orb=0.08,
                           crit=0.03, hp_scale=0.5, atk_scale=0.5, def_scale=0.5)
        if battle is None:
            won, log_lines = True, ["（演武：跳过战斗）"]
        else:
            won, log_lines = battle(enemy, "xiangu_normal")
        if won:
            xw, xq = calc_rewards(doc, mult * 1.5, rng)
            rw = grant_growth(doc, xw, xq, stone_rolls=1)
            infamy_gain = int(5 * mult)
            st["infamy"] = int(st.get("infamy", 0) or 0) + infamy_gain
            gains["xiongmng"] = infamy_gain
            drop_txt = ""
            if should_drop_seed_b(doc, cfg, location, "treasure", rng):
                seed = draw_seed(cfg, location, None, "treasure", rng=rng)
                bag_add_seed(st["bag"], seed)
                drop_txt = (f"\n\n【意外之喜！】击败{name}后发现其体内蕴含道种！\n"
                            f"◇ {seed['名称']} [{seed['品质']}]｜"
                            f"融合成功率 {(seed['融合成功率'] * 100):.0f}%")
            msg = "\n".join([
                "【探索·遭遇·战斗】", "",
                f"{getattr(doc, 'name', '')}在{location}遭遇一头{name}！",
                *log_lines[-4:], "",
                f"【获得】修为 +{rw['xiuwei']:,}｜血气 +{rw['xueqi']:,}｜"
                f"源石 +{rw['source_stone']:,}｜凶名 +{infamy_gain}"]) + drop_txt
            return msg, gains
        hp_loss = int(_hp_of(doc) * 0.25)
        _set_hp(doc, max(1, _hp_of(doc) - hp_loss))
        apply_heavy_injury(st, now)
        pending = {"npc": name, "expires_at": now + 60_000, "source": "explore"}
        st["pending_defeat"] = pending
        msg = "\n".join([
            "【探索·遭遇·战斗】", "",
            f"{getattr(doc, 'name', '')}在{location}遭遇一头{name}！",
            *log_lines[-4:], "",
            f"{getattr(doc, 'name', '')}力战不敌，重伤倒地！",
            f"【损失】血量 -{hp_loss:,}｜状态：重伤（30 分钟探索效率 -50%）", "",
            _defeat_menu(name)])
        return msg, gains

    # special：惊天发现
    specials = list(_SPECIAL_ITEMS.get(location) or ())
    if not specials:
        return "【探索·无果】四周一片虚无...", gains
    special = _pick(rng, specials)
    if special.get("trial"):
        text, extra = _flame_trial(doc, st, now, rng)
        for k, v in extra.items():
            gains[k] = gains.get(k, 0) + v
        return "【探索·惊天发现·试炼】" + text, gains
    bag_add_item(st["bag"], special)
    gains[special["name"]] = 1
    xw, xq = calc_rewards(doc, mult * 2, rng)
    rw = grant_growth(doc, xw, xq)
    msg = "\n".join([
        f"【探索·惊天发现·{special['rarity']}】", "",
        f"{getattr(doc, 'name', '')}在{location}深处感应到一股浩瀚的气息...", "",
        f"【发现】{special['name']}",
        f"【获得】修为 +{rw['xiuwei']:,}｜血气 +{rw['xueqi']:,}",
        "", f"【物品说明】{special['desc']}"])
    return msg, gains


def _explore_boss(doc: Any, st: dict, location: str, cfg: Mapping,
                  rng: Callable[[], float], mult: float,
                  battle: Callable | None, zone_factor: float) -> str:
    defs = _BOSS_DEFS.get(location) or _BOSS_DEFS["中层区域"]
    bdef = _pick(rng, list(defs))
    boss_lv = {"中层区域": 7, "深层区域": 9, "核心区域": 11, "火道禁区": 13}.get(location, 7)
    infamy = int(st.get("infamy", 0) or 0)
    atk_scale = 1.0 + (infamy / 500 if infamy > 100 else 0.0)
    hp_scale = 1.0 + (infamy / 1000 if infamy > 100 else 0.0)
    enemy = make_enemy(bdef["name"], boss_lv, zone_factor, bao=0.10, orb=0.15,
                       skills=tuple(bdef["skills"][:2]), crit=0.1,
                       hp_scale=hp_scale, atk_scale=atk_scale)
    if battle is None:
        won, log_lines = True, ["（演武：跳过战斗）"]
    else:
        won, log_lines = battle(enemy, "xiangu_boss")
    if won:
        risk_mult = {"深层区域": 2, "核心区域": 3}.get(location, 1)
        xw, xq = calc_rewards(doc, 3 * risk_mult, rng)
        rw = grant_growth(doc, xw, xq, stone_rolls=1)
        infamy_gain = int(20 * risk_mult)
        st["infamy"] = int(st.get("infamy", 0) or 0) + infamy_gain
        st.setdefault("gains", {})
        st["gains"]["daoyun"] = int(st["gains"].get("daoyun", 0) or 0) + int(50 * risk_mult)
        drops = []
        for d_name, d_type, d_chance, d_rarity in bdef["drops"]:
            if rng.random() < d_chance:
                bag_add_item(st["bag"], {"name": d_name, "type": d_type, "rarity": d_rarity,
                                         "desc": f"击败{bdef['name']}掉落的战利品"})
                drops.append(f"{d_name}（{d_rarity}）")
        seed_txt = ""
        if should_drop_seed_b(doc, cfg, location, "boss", rng):
            seed = draw_seed(cfg, location, None, "boss", rng=rng)
            bag_add_seed(st["bag"], seed)
            seed_txt = f"\n【Boss 道种掉落】{seed['名称']} [{seed['品质']}]"
        return "\n".join([
            f"【Boss遭遇·激战】", "",
            f"{getattr(doc, 'name', '')}在{location}遭遇了{bdef['name']}！",
            *log_lines[-4:], "",
            f"【战斗奖励】",
            f"修为 +{rw['xiuwei']:,}｜血气 +{rw['xueqi']:,}｜源石 +{rw['source_stone']:,}",
            f"凶名 +{infamy_gain}｜道韵 +{int(50 * risk_mult)}",
            *(f"掉落：{d}" for d in drops)]) + seed_txt
    hp_loss = int(_hp_of(doc) * 0.4)
    _set_hp(doc, max(1, _hp_of(doc) - hp_loss))
    apply_heavy_injury(st, time.time())
    return "\n".join([
        "【Boss遭遇·惨败】", "",
        f"{getattr(doc, 'name', '')}在{location}遭遇了{bdef['name']}，拼尽全力仍难以为敌！",
        *log_lines[-4:], "",
        f"【损失】血量 -{hp_loss:,}｜状态：重伤（30 分钟探索效率 -50%）"])


def _defeat_menu(npc_name: str) -> str:
    return "\n".join([
        "【生死抉择·60 秒】",
        f"「{npc_name}」的兵刃已经架上你的脖颈——",
        "#求饶　卑辞厚礼，或可苟活（邪恶存在仍可能痛下杀手，道心 -50）",
        "#任凭鱼肉　不存侥幸，任其处置（失去全部秘境收获，道心 -35）"])


# ---------------------------------------------------------------- 移动（XianguRealmMove 移植）

def _boundary(map_st: Mapping, cur: Mapping, nxt: Mapping) -> dict | None:
    w, h = int(map_st["w"]), int(map_st["h"])
    vert = "top" if nxt["y"] < 0 else ("bottom" if nxt["y"] >= h else None)
    horiz = "left" if nxt["x"] < 0 else ("right" if nxt["x"] >= w else None)
    direction = vert or horiz
    if not direction:
        return None
    return {"direction": direction, "enter_direction": _OPPOSITE[direction],
            "border": {"x": 0 if horiz == "left" else (w - 1 if horiz == "right" else cur["x"]),
                       "y": 0 if vert == "top" else (h - 1 if vert == "bottom" else cur["y"])}}


def _exit_unlocked(map_st: Mapping, x: int, y: int) -> bool:
    return any(e["x"] == x and e["y"] == y for e in revealed_exits(map_st))


def move(doc: Any, st: dict, key: str, steps: int, cfg: Mapping,
         rng: Callable[[], float], now: float,
         battle: Callable | None = None,
         claims: Mapping | None = None) -> tuple[str, dict]:
    """移动状态机：多步不跨界、单步可穿越出口切碎片；返回 (message, events)。

    events: {"transition": fragment_id|None, "pending_defeat": bool, "hp_loss": int}
    handler 负责同步 claims 后落库。
    """
    events: dict[str, Any] = {"transition": None, "pending_defeat": False, "hp_loss": 0}
    map_st = st.get("map")
    if not map_st:
        return "秘境地图已失效，请重新进入。", events
    dirinfo = DIRECTIONS.get(key)
    if not dirinfo:
        return f"未知的方向：{key}（可用：上/下/左/右/左上/右上/左下/右下，可带步数）", events
    steps = max(1, min(20, int(steps or 1)))
    dx, dy = dirinfo["dx"], dirinfo["dy"]

    # 多步：遇墙/特殊格/边界即停
    if steps > 1:
        exits_before = len(revealed_exits(map_st))
        moved = 0
        stop: tuple[str, str] | None = None
        cell_names = {CELL_TREASURE: "机缘之地", CELL_DANGER: "危险区域", CELL_NPC: "修士驻足",
                      CELL_VOID: "虚空裂缝", CELL_UNIQUE: "唯一机缘", CELL_EXIT: "碎片出口"}
        for _ in range(steps):
            cur = map_st["pos"]
            nxt = {"x": cur["x"] + dx, "y": cur["y"] + dy}
            b = _boundary(map_st, cur, nxt)
            if b:
                cell = map_st["grid"][b["border"]["y"]][b["border"]["x"]]
                stop = (("【出口在前】", "前方是碎片出口，多步移动不会跨界，请单步移动穿越。")
                        if cell == CELL_EXIT and _exit_unlocked(map_st, b["border"]["x"], b["border"]["y"])
                        else ("【边界受阻】", "连续前行，却撞上了一面无形的空间壁垒，只能停下。"))
                break
            cell = map_st["grid"][nxt["y"]][nxt["x"]]
            if cell == CELL_WALL:
                stop = ("【道则壁垒】", "连续前行，被一道古老的道则屏障挡住去路。")
                break
            if cell == CELL_EXIT or cell in _MOVE_TEXT_CELLS:
                stop = ("【前路有变】",
                        f"行至{cell_names.get(cell, '一处特殊之地')}前，止步观望。"
                        f"如需进入请单步移动触发。")
                break
            map_st["pos"] = nxt
            map_st["steps"] = int(map_st.get("steps", 0) or 0) + 1
            moved += 1
        if moved == 0:
            head, body = stop or ("【止步】", "原地未动。")
            return f"{head}\n{body}", events
        reveal(map_st, map_st["pos"], divine_range(doc))
        exit_discovery_daoyun(st, map_st, exits_before, doc)
        if map_st.get("fragment_id") == "chaos_mosquito":
            events["hp_loss"] = _mosquito_drain(doc)
        return (f"【连续移动】向{dirinfo['name']}前行 {moved} 格"
                + (f"（目标 {steps} 格，中途止步）" if moved < steps else "")), events

    # 单步
    cur = map_st["pos"]
    nxt = {"x": cur["x"] + dx, "y": cur["y"] + dy}
    b = _boundary(map_st, cur, nxt)
    if b:
        bx, by = b["border"]["x"], b["border"]["y"]
        if map_st["grid"][by][bx] == CELL_EXIT and _exit_unlocked(map_st, bx, by):
            target = map_st["connections"].get(b["direction"])
            if not target:
                return "【前方无路】\n却发现前方是虚空深渊，没有可去的碎片。", events
            block = fragment_entry_block(doc, target, bool((st.get("crowned") or "")))
            if block:
                return block, events
            seed = str(st.get("world_seed") or "")
            prev_id = map_st["fragment_id"]
            snapshot = _snapshot(map_st)
            if snapshot:
                st.setdefault("history", {})[prev_id] = snapshot
            restored = _restore(st.get("history", {}).get(target), target)
            if restored:
                st["history"].pop(target, None)
                map_st.clear()
                map_st.update(restored)
            else:
                connections = bind_return_connection(seed, target,
                                                     create_connections(seed, target),
                                                     b["enter_direction"], prev_id)
                new_state = create_fragment_state(seed, target, connections)
                map_st.clear()
                map_st.update(new_state)
                reveal(map_st, map_st["pos"], 1)
            if claims is not None:
                sync_shared_claims(st, claims)
            map_st["steps"] = int(map_st.get("steps", 0) or 0) + 1
            st["location"] = FRAGMENTS[target]["zone"]
            events["transition"] = target
            if target == "chaos_mosquito":
                events["hp_loss"] = _mosquito_drain(doc)
            return f"【碎片穿越】你穿过出口，踏入「{FRAGMENTS[target]['name']}」！\n{FRAGMENTS[target]['desc']}", events
        return "【边界受阻】\n向该方向走去，却撞上了一面无形的空间壁垒...此处并非出口。", events

    cell = map_st["grid"][nxt["y"]][nxt["x"]]
    if cell == CELL_WALL:
        return "【道则壁垒】\n却被一道无形的道则屏障阻挡！此处是一面古老的壁垒。", events

    map_st["pos"] = nxt
    map_st["steps"] = int(map_st.get("steps", 0) or 0) + 1
    exits_before = len(revealed_exits(map_st))
    reveal(map_st, nxt, divine_range(doc))
    exit_discovery_daoyun(st, map_st, exits_before, doc)

    msg = ""
    frag = FRAGMENTS.get(map_st["fragment_id"], {})
    zone = frag.get("zone", "边缘区域")
    risk_mult = 1.0 + float(frag.get("risk", 0.2))
    if cell == CELL_TREASURE:
        msg = _cell_treasure(doc, st, map_st, nxt, cfg, rng, claims)
    elif cell == CELL_DANGER:
        msg = _cell_danger(doc, st, map_st, nxt, zone, rng, now, battle)
        events["pending_defeat"] = bool(st.get("pending_defeat"))
    elif cell == CELL_NPC:
        msg = _cell_npc(doc, map_st, nxt)
    elif cell == CELL_VOID:
        msg = _cell_void(doc, st, map_st, nxt, rng)
        events["hp_loss"] = max(events["hp_loss"], 0)
    elif cell == CELL_UNIQUE:
        msg = _cell_unique(doc, st, map_st, nxt, claims, rng, now, battle)
    elif cell == CELL_EMPTY:
        if rng.random() < 0.2:
            ambient = (f"{getattr(doc, 'name', '')}缓步前行，四周一片寂静...",
                       "微风吹过，带来远古的气息。",
                       "脚步在荒芜的大地上回响。",
                       "远处似有微光闪烁，转眼又消失不见。")
            msg = _pick(rng, list(ambient))
    if map_st.get("fragment_id") == "chaos_mosquito":
        loss = _mosquito_drain(doc)
        events["hp_loss"] = max(events["hp_loss"], loss)
        msg += f"\n🦟 混沌蚊群疯狂吸血！生命力在流逝（-{loss:,}）..."
        if _hp_of(doc) <= _hp_max_of(doc) * 0.1:
            msg += "\n⚠️ 血气过低！速离此地！"
    return msg, events


def _mosquito_drain(doc: Any) -> int:
    loss = int(_hp_of(doc) * (0.02 + random.random() * 0.03))
    _set_hp(doc, max(1, _hp_of(doc) - loss))
    return loss


def _hp_max_of(doc: Any) -> int:
    """血量上限：handler 经 set_hp_hint 写入 ext["xiangu"]["hp_max_hint"]；
    缺省回退当前血量（仅量级兜底，强度失真由 handler 保证不再发生）。"""
    st = ((getattr(doc, "ext", {}) or {}).get("xiangu") or {})
    hint = int(float(st.get("hp_max_hint", 0) or 0))
    if hint > 0:
        return hint
    return max(1, int(float((getattr(doc, "ext", {}) or {}).get("hp_max", 0) or 0)) or _hp_of(doc))


def set_hp_hint(st: dict, hp_max: int) -> None:
    """handler 在移动/探索入口写入真实血量上限（原版按 血量上限 结算强度）。"""
    if int(hp_max or 0) > 0:
        st["hp_max_hint"] = int(hp_max)


def _cell_treasure(doc: Any, st: dict, map_st: dict, pos: Mapping,
                   cfg: Mapping, rng: Callable[[], float],
                   claims: Mapping | None) -> str:
    x, y = pos["x"], pos["y"]
    map_st["grid"][y][x] = CELL_EXPLORED
    map_st["revealed"][y][x] = True
    frag = FRAGMENTS.get(map_st["fragment_id"], {})
    zone = frag.get("zone", "边缘区域")
    seed = str(st.get("world_seed") or "")
    risk_mult = 1.0 + float(frag.get("risk", 0.2))
    if claims is not None:
        scope = claim_scope(seed, map_st["fragment_id"], f"cell:{x},{y}")
        if world_claim(claims, scope):
            return "💨【机缘已失】此处造化已被另一位天骄先一步搜走，只余残存道痕。"
        world_claim_put(claims, scope, getattr(doc, "uid", ""), getattr(doc, "name", ""), time.time())
    if should_drop_seed_b(doc, cfg, zone, "treasure", rng):
        sd = draw_seed(cfg, zone, map_st["fragment_id"], "treasure", rng=rng)
        bag_add_seed(st["bag"], sd)
        xw, xq = calc_rewards(doc, risk_mult * 2, rng)
        rw = grant_growth(doc, xw, xq)
        return "\n".join([
            f"💎🔥【机缘·道种现世·{sd['品质']}】",
            f"{getattr(doc, 'name', '')}在{frag.get('name', zone)}深处感应到一枚道种，",
            "仙古法则齐鸣，神话仙种破土而出！" if sd.get("顶级道种") else "道种在残存的仙古法则中缓缓搏动...", "",
            f"获得：{sd['名称']} [{sd['品质']}]｜融合成功率 {(sd['融合成功率'] * 100):.0f}%",
            f"修为 +{rw['xiuwei']:,}｜血气 +{rw['xueqi']:,}", "",
            f"提示：前往核心区域使用 #借助{sd['名称']}点燃神火"])
    roll = rng.random()
    if zone == "核心区域" and roll < 0.25:
        items = list(_LOCATION_ITEMS.get(zone) or ())
        if items:
            item = _pick(rng, items)
            bag_add_item(st["bag"], item)
            xw, xq = calc_rewards(doc, risk_mult * 2, rng)
            rw = grant_growth(doc, xw, xq)
            return "\n".join([
                f"💎✨【机缘·稀世宝物·{item.get('rarity', '稀有')}】",
                f"{getattr(doc, 'name', '')}在{frag.get('name', zone)}深处发现一件宝物...", "",
                f"获得：{item['name']} × 1｜修为 +{rw['xiuwei']:,}｜血气 +{rw['xueqi']:,}"])
    def _pool_run() -> str:
        kind = _weighted_pick(
            [("daoyun", 0.25), ("stone", 0.30), ("blood", 0.20), ("faqi", 0.15), ("mind", 0.10)],
            lambda t: t[1], rng)
        key = kind[0] if isinstance(kind, tuple) else str(kind)
        if key == "stone":
            stone = source_stone_reward(doc, 1)
            xw, xq = calc_rewards(doc, risk_mult, rng)
            rw = grant_growth(doc, xw, xq, stone_rolls=0)
            bag_add_growth(st["bag"], source_stone=stone)
            return (f"发现小型源石矿脉！\n秘境背包：源石 +{stone:,}｜"
                    f"修为 +{rw['xiuwei']:,}｜血气 +{rw['xueqi']:,}")
        if key == "blood":
            xq = max(1, int((2_000 + rng.random() * 8_000) * risk_mult / 10))
            bag_add_growth(st["bag"], xueqi=xq)
            return f"寻得古兽残留精血...\n获得：血气 +{xq:,}"
        if key == "faqi":
            fn = _pick(rng, ["残破战戟", "断裂古剑", "破碎神甲碎片", "古盾残片", "仙古符骨"])
            bag_add_item(st["bag"], {"name": fn, "type": "材料",
                                     "desc": "仙古宝池中出土的残破法器遗片"})
            stone = source_stone_reward(doc, 1)
            xw, xq = calc_rewards(doc, risk_mult, rng)
            rw = grant_growth(doc, xw, xq)
            bag_add_growth(st["bag"], source_stone=stone)
            return (f"挖出{fn}，源石矿脉同时喷薄！\n秘境背包：源石 +{stone:,}｜"
                    f"修为 +{rw['xiuwei']:,}｜血气 +{rw['xueqi']:,}")
        if key == "mind":
            st.setdefault("gains", {})
            st["gains"]["daoyun"] = int(st["gains"].get("daoyun", 0) or 0) + 3
            return "拾得仙古修士遗留的神识碎片！\n获得：3 道韵"
        dg = 1 + int(rng.random() * 5 * risk_mult)
        st.setdefault("gains", {})
        st["gains"]["daoyun"] = int(st["gains"].get("daoyun", 0) or 0) + dg
        xw, xq = calc_rewards(doc, risk_mult, rng)
        rw = grant_growth(doc, xw, xq)
        return (f"盘膝感悟道则...\n获得：{dg} 道韵｜修为 +{rw['xiuwei']:,}｜"
                f"血气 +{rw['xueqi']:,}")

    body = _pool_run()
    return "\n".join([f"💎【机缘搜刮】", f"{getattr(doc, 'name', '')}{body}",
                      f"（区域：{frag.get('name', '未知')}｜加持 ×{risk_mult:.2f}）"])


def _cell_danger(doc: Any, st: dict, map_st: dict, pos: Mapping, zone: str,
                 rng: Callable[[], float], now: float,
                 battle: Callable | None) -> str:
    x, y = pos["x"], pos["y"]
    map_st["revealed"][y][x] = True
    frag = FRAGMENTS.get(map_st["fragment_id"], {})
    risk_mult = 1.0 + float(frag.get("risk", 0.2))
    boss_chance = min(0.5, float(frag.get("risk", 0.2)) * 0.6)
    if rng.random() < boss_chance:
        name = _pick(rng, ["仙古遗种·王", "远古守护者", "堕落天骄", "秘境镇守者", "黑暗物质聚合体"])
        enemy = make_enemy(name, xg_level_of(doc), risk_mult * 0.5, bao=0.05, orb=0.1,
                           crit=0.05, hp_scale=0.8, atk_scale=0.8, def_scale=0.8)
        if battle is None:
            won, log_lines = True, ["（演武：跳过战斗）"]
        else:
            won, log_lines = battle(enemy, "xiangu_boss")
        if won:
            stone = source_stone_reward(doc, 2)
            bag_add_growth(st["bag"], source_stone=stone)
            dg = 3 + int(rng.random() * 8)
            st.setdefault("gains", {})
            st["gains"]["daoyun"] = int(st["gains"].get("daoyun", 0) or 0) + dg
            st["infamy"] = int(st.get("infamy", 0) or 0) + 10
            map_st["grid"][y][x] = CELL_EXPLORED
            drop_txt = ""
            if should_drop_seed_b(doc, load_config(), zone, "boss", rng):
                sd = draw_seed(load_config(), zone, map_st["fragment_id"], "boss", rng=rng)
                bag_add_seed(st["bag"], sd)
                drop_txt = f"\n【Boss 道种掉落】{sd['名称']} [{sd['品质']}]"
            return "\n".join([
                f"⚡🐲【遭遇·{name}】", "",
                *log_lines[-4:], "",
                f"⚔️【Boss击败】力战{name}！",
                f"秘境背包：源石 +{stone:,}｜道韵 +{dg}｜凶名 +10"]) + drop_txt
        hp_loss = int(_hp_of(doc) * 0.3)
        _set_hp(doc, max(1, _hp_of(doc) - hp_loss))
        apply_heavy_injury(st, now)
        return "\n".join([f"⚡🐲【遭遇·{name}】", "", *log_lines[-4:], "",
                          f"【战败】血量 -{hp_loss:,}，陷入重伤。"])

    dangers = (
        {"name": "道则陷阱", "desc": "脚下道则突然炸裂，杀阵启动！",
         "pct": (0.04, 0.10)},
        {"name": "守护兽", "desc": "一头远古守护兽从暗处扑来！",
         "pct": (0.08, 0.18), "daoyun": True},
        {"name": "毒瘴", "desc": "前方弥漫着腐蚀万物的剧毒瘴气...",
         "pct": (0.03, 0.08), "herb": True},
        {"name": "空间乱流", "desc": "空间突然扭曲，乱流撕裂一切！",
         "pct": (0.05, 0.12), "teleport": True},
    )
    danger = _pick(rng, list(dangers))
    lo, hi = danger["pct"]
    loss = max(1, int(_hp_of(doc) * (lo + rng.random() * (hi - lo)) * risk_mult / 1.0))
    _set_hp(doc, max(1, _hp_of(doc) - loss))
    map_st["grid"][y][x] = CELL_EXPLORED
    body = f"当前血量 -{loss:,}｜剩余 {_hp_of(doc):,}"
    extra = ""
    if danger.get("daoyun"):
        dg = 1 + int(rng.random() * 3)
        st.setdefault("gains", {})
        st["gains"]["daoyun"] = int(st["gains"].get("daoyun", 0) or 0) + dg
        extra = f"\n反杀守护兽，获得 {dg} 道韵！"
    elif danger.get("herb") and rng.random() < 0.3:
        xw, _ = calc_rewards(doc, risk_mult * 0.5, rng)
        grant_growth(doc, xiuwei=xw)
        extra = f"\n毒瘴中竟生长着稀有灵药！修为 +{xw:,}"
    elif danger.get("teleport") and rng.random() < 0.3:
        cands = [{"x": tx, "y": ty} for ty in range(int(map_st["h"]))
                 for tx in range(int(map_st["w"]))
                 if map_st["grid"][ty][tx] != CELL_WALL and (tx, ty) != (x, y)]
        if cands:
            np_ = _pick(rng, cands)
            map_st["pos"] = np_
            reveal(map_st, np_, 2)
            extra = f"\n🌀空间乱流将你吹向远方！新位置：[{np_['x']}, {np_['y']}]"
    return "\n".join([f"⚡【{danger['name']}·遭遇】",
                      f"{getattr(doc, 'name', '')}{danger['desc']}", body + extra])


def _cell_npc(doc: Any, map_st: Mapping, pos: Mapping) -> str:
    spot = next((s for s in map_st.get("npc_locations", ())
                 if s.get("x") == pos["x"] and s.get("y") == pos["y"]), None)
    npc = (spot or {}).get("npc") or {}
    name = npc.get("name") or npc.get("名号") or "神秘修士"
    return (f"👤 {getattr(doc, 'name', '')}遇见了【{name}】！\n"
            "可使用 #与NPC交谈、#攻击NPC 或 #NPC组队。")


def _cell_void(doc: Any, st: dict, map_st: dict, pos: Mapping,
               rng: Callable[[], float]) -> str:
    x, y = pos["x"], pos["y"]
    map_st["revealed"][y][x] = True
    roll = rng.random()
    if roll < 0.3:
        cands = [{"x": tx, "y": ty} for ty in range(int(map_st["h"]))
                 for tx in range(int(map_st["w"]))
                 if map_st["grid"][ty][tx] != CELL_WALL and (tx, ty) != (x, y)]
        if cands:
            np_ = _pick(rng, cands)
            map_st["pos"] = np_
            reveal(map_st, np_, 2)
            return "\n".join(["🌀【虚空传送】", "被虚空裂缝吸入，天旋地转后出现在全新之地！",
                              f"新坐标：[{np_['x']}, {np_['y']}]"])
    if roll < 0.7:
        stone = source_stone_reward(doc, 1)
        bag_add_growth(st["bag"], source_stone=stone)
        map_st["grid"][y][x] = CELL_EXPLORED
        return "\n".join(["🌀【虚空宝藏】", "裂缝中竟有源石喷薄！",
                          f"将 {stone:,} 源石收入秘境背包。"])
    loss = 500 + int(rng.random() * 2000)
    _set_hp(doc, max(1, _hp_of(doc) - loss))
    return "\n".join(["🌀【虚空风暴】", "裂缝中涌出虚空风暴，被波及受伤！",
                      f"损失生命：-{loss:,}｜剩余血量：{_hp_of(doc):,}"])


def _cell_unique(doc: Any, st: dict, map_st: dict, pos: Mapping,
                 claims: Mapping | None, rng: Callable[[], float], now: float,
                 battle: Callable | None = None) -> str:
    x, y = pos["x"], pos["y"]
    map_st["revealed"][y][x] = True
    found_name = found = None
    for name, treasure in (map_st.get("unique_treasures") or {}).items():
        if treasure["pos"]["x"] == x and treasure["pos"]["y"] == y and not treasure.get("claimed"):
            found_name, found = name, treasure
            break
    if not found:
        return "【机缘已逝】此处的造化已被取走。"
    if found.get("kind") == MARROW_POOL_KIND:
        return _cell_marrow(doc, st, map_st, pos, found, found_name, battle=battle, rng=rng)
    champion = found.get("claim_scope") == "round-champion"
    crowned = bool(st.get("crowned") or "")
    if champion and not crowned:
        return "【冠军造化·法则不应】此造化只回应本轮仙古第一。"
    seed = str(st.get("world_seed") or "")
    scope = claim_scope(seed, map_st["fragment_id"], f"unique:{found_name}")
    if claims is not None:
        prior = world_claim(claims, scope)
        if prior:
            found["claimed"] = True
            map_st["grid"][y][x] = CELL_EXPLORED
            mine = str(prior.get("claimant")) == str(getattr(doc, "uid", ""))
            if champion:
                return ("【冠军造化】你已领取本轮固定造化，不可重复获得。" if mine else
                        f"【冠军造化】本轮固定造化已被{prior.get('name') or '他人'}领取。")
            return ("✨【天地唯一】该造化已由你于过往轮次获得，天机不可复得。" if mine else
                    f"✨【天地唯一】{found_name}已被{prior.get('name') or '他人'}获得，"
                    "此等造化举世唯一，再无第二份。")
        world_claim_put(claims, scope, getattr(doc, "uid", ""), getattr(doc, "name", ""), now)
    found["claimed"] = True
    map_st["grid"][y][x] = CELL_EXPLORED
    st.setdefault("gains", {})
    if champion:
        bag_add_potential(st["bag"], 100)
        st["gains"]["daoyun"] = int(st["gains"].get("daoyun", 0) or 0) + 1000
        st["gains"]["unique_found"] = int(st["gains"].get("unique_found", 0) or 0) + 1
        return "\n".join([
            "🏆【冠军造化·落印】", "",
            f"{found.get('desc', '')}", "",
            "【获得】仙道潜力 +100｜道韵 +1000"])
    if found_name == "大罗剑胎":
        # 表内 stats 已按 ÷1000 登记（grid 生成处），直接入包
        stats = found.get("stats") or {}
        bag_add_item(st["bag"], {"name": "大罗剑胎", "type": "武器", "class": "装备",
                                 "unique": True, **stats,
                                 "desc": found.get("desc", "")})
    else:
        bag_add_item(st["bag"], {**found, "unique": True})
    st["gains"]["unique_found"] = int(st["gains"].get("unique_found", 0) or 0) + 1
    st["gains"]["daoyun"] = int(st["gains"].get("daoyun", 0) or 0) + 50
    return "\n".join([
        f"✨【天地唯一·{found_name}】", "",
        f"{found.get('desc', '')}", "",
        "【获得】该造化已入秘境背包，撤离时结算｜道韵 +50"])


def _cell_marrow(doc: Any, st: dict, map_st: dict, pos: Mapping,
                 pool: dict, pool_key: str,
                 battle: Callable | None = None,
                 rng: Callable[[], float] | None = None) -> str:
    if pool.get("claimed"):
        return f"【{MARROW_POOL_NAME}】这方机缘已经被你浸取过了。"
    cfg = marrow_config()
    rng = rng or random.Random()
    x, y = pos["x"], pos["y"]
    if pool.get("is_trap"):
        # 假池杀局（原版 handleXianguMarrowPoolCell·trap）：伏兵自杀阵中齐出
        pool["claimed"] = True
        map_st["grid"][y][x] = CELL_EXPLORED
        invited_by = str(pool.get("invited_by") or "")
        if invited_by:
            rels = st.setdefault("npc_relations", {})
            rels[invited_by] = int(rels.get(invited_by, 0) or 0) - 30
        enemy = make_enemy("蒙面猎手", xg_level_of(doc), 0.8, bao=0.1, orb=0.12, crit=0.15)
        if battle is None:
            won, log_lines = True, ["（演武：跳过战斗）"]
        else:
            won, log_lines = battle(enemy, "xiangu_ambush")
        if won:
            st.setdefault("gains", {})
            st["gains"]["daoyun"] = int(st["gains"].get("daoyun", 0) or 0) + 20
            return "\n".join([
                "🩸【万道仙髓池·伏杀反转】",
                "假池为饵，伏兵自杀阵中齐出——你反杀猎手，识破杀局！", "",
                *log_lines[-3:], "",
                "道韵 +20"])
        hp_loss = max(1, int(_hp_of(doc) * 0.35))
        _set_hp(doc, max(1, _hp_of(doc) - hp_loss))
        apply_heavy_injury(st, time.time())
        return "\n".join([
            "🩸【万道仙髓池·伏杀】",
            "假池为饵，伏兵自杀阵中齐出！你拼死突围，身受重伤。", "",
            *log_lines[-3:], "",
            f"【损失】血量 -{hp_loss:,}｜状态：重伤"])
    rw = marrow_rewards(doc, cfg["mult"], rng)
    bag_add_growth(st["bag"], xiuwei=rw["xiuwei"], xueqi=rw["xueqi"])
    bag_add_potential(st["bag"], cfg["potential"])
    pool["claimed"] = True
    map_st["grid"][y][x] = CELL_EXPLORED
    st.setdefault("gains", {})
    st["gains"]["unique_found"] = int(st["gains"].get("unique_found", 0) or 0) + 1
    st["gains"][f"仙髓池浸泡"] = int(st["gains"].get("仙髓池浸泡", 0) or 0) + 1
    return "\n".join([
        f"💧【机缘·{MARROW_POOL_NAME}】",
        "池中承载着仙古残存的万道精粹，入池浸泡，根骨与道基一同蜕变。", "",
        "【浸泡所得】",
        f"仙道潜力 +{cfg['potential']}",
        f"修为 +{rw['xiuwei']:,}", f"血气 +{rw['xueqi']:,}",
        f"（寻宝算法 ×{cfg['mult']:.0f}）"])


# ---------------------------------------------------------------- 推演 / 目标 / 寻找NPC

def divine_scan(doc: Any, st: dict) -> tuple[str, int]:
    """#秘境推演：5 道韵扫 4 格。返回 (text, spent)。道韵不足返回 (text, 0)。"""
    gains = st.setdefault("gains", {})
    daoyun = int(gains.get("daoyun", 0) or 0)
    if daoyun < 5:
        return (f"【道韵不足】当前道韵 {daoyun} 💎，需 5 💎。\n"
                "提示：探索机缘地或击败修士可获得道韵。"), 0
    gains["daoyun"] = daoyun - 5
    map_st = st.get("map") or {}
    scan_range = min(4, divine_range(doc) + 2)
    px, py = map_st["pos"]["x"], map_st["pos"]["y"]
    conn_names = {d: (FRAGMENTS.get(t) or {}).get("name", t)
                  for d, t in (map_st.get("connections") or {}).items() if t}
    results: list[tuple[int, str]] = []
    for dy in range(-scan_range, scan_range + 1):
        for dx in range(-scan_range, scan_range + 1):
            if dx == 0 and dy == 0:
                continue
            sx, sy = px + dx, py + dy
            if not (0 <= sy < int(map_st["h"]) and 0 <= sx < int(map_st["w"])):
                continue
            cell = map_st["grid"][sy][sx]
            dist = abs(dx) + abs(dy)
            cardinal = _direction_name(dx, dy)
            if cell == CELL_TREASURE:
                results.append((dist, f"道韵感应到{cardinal}{dist}格处有【💎机缘】——灵光吞吐，必有宝物！"))
            elif cell == CELL_DANGER:
                results.append((dist, f"杀意从{cardinal}{dist}格处传来——【⚡危险】潜伏！"))
            elif cell == CELL_NPC:
                results.append((dist, f"一道神识在{cardinal}{dist}格处盘桓——有【👤修士】在此！"))
            elif cell == CELL_EXIT:
                d = _exit_direction({"x": sx, "y": sy}, int(map_st["w"]), int(map_st["h"]))
                tgt = conn_names.get(d, "无连接") if d else "未知碎片"
                results.append((dist, f"空间紊乱——{cardinal}{dist}格处【🚪出口】通向「{tgt}」！"))
            elif cell == CELL_VOID:
                results.append((dist, f"危险！{cardinal}{dist}格处空间扭曲成【🌀虚空裂缝】——勿靠近！"))
            elif cell == CELL_UNIQUE:
                if is_marrow_position(map_st, sx, sy):
                    results.append((dist, f"💧 万道水声共鸣！{cardinal}{dist}格处有【{MARROW_POOL_NAME}】！"))
                else:
                    results.append((dist, f"🔥🔥🔥 天机震动！{cardinal}{dist}格处有【✨绝世机缘】——此乃大造化！"))
    results.sort(key=lambda t: t[0])
    lines = ["🔮【神识推演·天机窥探】", "以道韵为引，推演前方吉凶！（消耗 5 💎 道韵）", ""]
    if not results:
        lines.append("四周一片虚无...神识未能探测到任何特殊之物。")
    else:
        for _, text in results[:8]:
            lines.append(f"· {text}")
        if len(results) > 8:
            lines.append(f"...（共 {len(results)} 处异常，神识无法尽数显化）")
    exits_before = len(revealed_exits(map_st))
    reveal(map_st, map_st["pos"], scan_range)
    lines += ["", f"剩余道韵：{gains['daoyun']} 💎"]
    exit_gain = exit_discovery_daoyun(st, map_st, exits_before, doc)
    if exit_gain > 0:
        lines.append(f"探明新出口，道韵回响 +{exit_gain}。")
    return "\n".join(lines), 5


def _direction_name(dx: int, dy: int) -> str:
    if dy < 0:
        return "西北方" if dx < 0 else ("正北方" if dx == 0 else "东北方")
    if dy == 0:
        return "正西方" if dx < 0 else ("正东方" if dx > 0 else "当前位置")
    return "西南方" if dx < 0 else ("正南方" if dx == 0 else "东南方")


def goal_text(doc: Any, st: Mapping, lc: Mapping, world_year: int) -> str:
    """#秘境目标：道种持有 + 神火路线进度 + 快捷提示。"""
    daoyun = int((st.get("gains") or {}).get("daoyun", 0) or 0)
    location = str(st.get("location") or "边缘区域")
    shenhuo = st.get("shenhuo") or {}
    if shenhuo.get("已点燃"):
        goal = (f"✅ 神火已点燃·极境达成（{shenhuo.get('极境名称') or shenhuo.get('点燃方式')}）"
                if shenhuo.get("极境达成")
                else f"🔶 神火已燃（{shenhuo.get('神火品质', '下品')}）")
    elif shenhuo.get("路线") in ("以身为种", "祭炼真我"):
        goal = "🔶 祭炼真我路线：需火道禁区 + 500道韵 + 六大极境"
    else:
        need = max(0, 100 - daoyun)
        goal = f"🔶 距点燃神火：还需{need}道韵" if need else "🔶 道韵已足！"
    seeds = list((st.get("bag") or {}).get("seeds", ()))
    return "\n".join([
        "【仙古秘境·探索目标】", "",
        f"当前位置：{location}", f"当前道韵：{daoyun} 点",
        f"可用道种：{len(seeds)} 个", "",
        "【目标进度】", goal, "",
        "【点燃神火·四种方式】",
        "① #点燃神火（自身苦修·下品）",
        "② #服用XXX点燃神火（天材地宝·中品）",
        "③ #借助XX道种点燃神火（品质对应，顶级仙种修仙气）",
        "④ #祭炼真我（三千道火淬炼·唯一，火道禁区·修仙气）", "",
        "【快捷提示】",
        f"→ {'#祭炼真我 尝试最强路线（需六大极境·火道禁区）' if daoyun >= 500 else f'道韵不足（{daoyun}/500），继续探索'}",
        ("→ 已在核心区域，可借助道种点燃神火！" if location == "核心区域"
         else "→ #秘境移动 前往核心区域（借助道种点燃需在核心区域）"),
        "", lifecycle_brief(lc, world_year)])


def find_npc_text(doc: Any, st: Mapping) -> str:
    """#寻找NPC：列出本碎片 NPC 与相对方位（W26 补交互指令）。"""
    map_st = st.get("map") or {}
    location = FRAGMENTS.get(map_st.get("fragment_id", ""), {}).get("zone", "边缘区域")
    spots = [s for s in map_st.get("npc_locations", ()) if s.get("npc")]
    if not spots:
        return f"【寻找NPC】在{location}没有发现任何修士的踪迹..."
    lines = [f"【寻找NPC·{location}】", "",
             f"{getattr(doc, 'name', '')}放出神识，搜索周围的修士...", ""]
    px, py = map_st["pos"]["x"], map_st["pos"]["y"]
    for spot in spots:
        npc = spot["npc"]
        tag = ("【原著天骄】" if npc.get("is_canon")
               else "⚠️敌意" if npc.get("hostile")
               else {"good": "✦善良", "evil": "▼邪恶"}.get(npc.get("faction"), "◆中立"))
        dx, dy = spot["x"] - px, spot["y"] - py
        dist = abs(dx) + abs(dy)
        direction = "就在身前" if dist == 0 else f"{_direction_name(dx, dy)}·{dist}格"
        lines.append(f"{tag} {npc.get('name') or npc.get('名号')}"
                     + ("　💱可交易" if npc.get("trade") else ""))
        lines.append(f"  坐标：[{spot['x']}, {spot['y']}]（{direction}）")
        if npc.get("desc"):
            lines.append(f"  {npc['desc']}")
        dialogs = npc.get("dialogs") or ()
        if dialogs:
            lines.append(f'  "{dialogs[0]}"')
        trade = npc.get("trade") or {}
        if trade.get("items"):
            lines.append(f"  出售：{'、'.join(i.get('name', '') for i in trade['items'])}")
        lines.append("")
    lines.append("移动到对应NPC格后，使用 #与NPC交谈、#攻击NPC 或 #NPC组队")
    return "\n".join(lines)


# ---------------------------------------------------------------- NPC 生成基础（W26 交互的前提；名字池/境界合成）

NPC_NAME_POOL = {
    "姓": ("叶", "楚", "萧", "林", "苏", "姜", "姬", "风", "云", "龙", "秦", "石", "紫", "玄",
           "古", "荒", "冥", "幽", "虚", "辰", "莫", "白", "夜", "君", "洛", "凌", "薛", "夏", "沈"),
    "名首": ("无", "天", "羽", "清", "寒", "长", "独", "太", "万", "九", "一", "初", "道", "剑",
             "仙", "帝", "神", "魔", "尘", "霄", "玄", "苍", "青", "紫", "金", "银"),
    "名尾": ("尘", "霄", "寒", "渊", "峰", "岳", "霆", "泽", "河", "洛", "云", "月", "星", "辰",
             "曦", "晔", "灵", "真", "玄", "道", "一", "无", "极", "天", "心", "魂", "骨", "命",
             "机", "缘", "劫", "灭", "生", "死", "轮", "回"),
    "道号": ("太虚", "无上", "九幽", "万古", "紫霄", "混元", "大罗", "清微", "玄黄", "鸿蒙",
             "苍冥", "太初", "寂灭", "轮回", "混沌", "灵虚"),
    "称号": ("流浪剑客", "云游散修", "秘境猎手", "古道追寻者", "天骄争渡人", "秘境独行者",
             "道种寻访者", "仙古遗民", "散修奇人", "不世天骄", "隐世修士", "无名散人"),
}

def generate_npc_name(rng: Callable[[], float]) -> dict[str, str]:
    surname = _pick(rng, list(NPC_NAME_POOL["姓"]))
    single = rng.random() < 0.4
    given = (_pick(rng, list(NPC_NAME_POOL["名尾"])) if single
             else _pick(rng, list(NPC_NAME_POOL["名首"])) + _pick(rng, list(NPC_NAME_POOL["名尾"])))
    dao = _pick(rng, list(NPC_NAME_POOL["道号"])) + _pick(
        rng, ["散人", "真人", "道人", "尊者", "居士", "老祖", "仙师"])
    title = _pick(rng, list(NPC_NAME_POOL["称号"]))
    return {"name": surname + given, "dao": dao, "title": title}


def generate_npc(location: str, infamy: int, rng: Callable[[], float],
                 npc_id: str = "") -> dict[str, Any]:
    """随机修士 NPC（原版 generateRandomNPC 的生成半边；交互在 W26）。"""
    info = generate_npc_name(rng)
    personalities = ("proud", "scheming", "friendly", "hostile", "neutral")
    personality = _pick(rng, list(personalities))
    faction = {"hostile": "evil", "friendly": "good"}.get(personality, "neutral")
    common_gongfa = ("补天术", "狻猊宝术", "青天鹏宝术", "朱雀宝术", "剑道真解",
                     "九天剑诀", "五行真解", "紫气东来", "天雷诀", "冰魄玄功")
    gongfa = list(dict.fromkeys(_pick(rng, list(common_gongfa))
                                for _ in range(1 + int(rng.random() * 2))))
    # 随机修士境界：凶名越高遇见的强者越凶（5-9 境钳制，原版 strengthenXianguNpc 简化）
    lv = max(5, min(9, 5 + int(infamy / 100)))
    return {
        "id": npc_id or f"random_{int(rng.random() * 1_000_000_000):09d}",
        "name": info["name"], "title": f"{info['dao']}·{info['title']}",
        "faction": faction, "personality": personality,
        "hostile": personality == "hostile",
        "desc": f"{info['name']}，在{location or '仙古秘境'}中磨砺至今的{info['title']}。",
        "xg": lv,
        "crit": 0.1 + rng.random() * 0.25,
        "crit_dmg": 1.5 + rng.random() * 2,
        "skills": gongfa,
        "dialogs": ("哼，将你的东西交出来！" if personality == "hostile"
                    else "道友也是来寻机缘的？",
                    "听闻这仙古秘境深处有大造化...",
                    "此地凶险，独自探索需万分小心。"),
        "trade": None,
        "is_canon": False,
    }





def status_text(doc: Any, st: Mapping, lc: Mapping, world_year: int) -> str:
    """#秘境状态：位置 / 收获 / 撤离读条 / 生命周期。"""
    if not st.get("active"):
        return ("【仙古秘境·未入】\n使用 #进入仙古秘境 踏入秘境。\n"
                + lifecycle_brief(lc, world_year))
    map_st = st.get("map") or {}
    frag = FRAGMENTS.get(map_st.get("fragment_id", ""), {})
    bag = bag_summary(st.get("bag") or {})
    gains = st.get("gains") or {}
    revealed = sum(1 for row in map_st.get("revealed", ()) for c in row if c)
    evac = st.get("evac")
    evac_line = ""
    if isinstance(evac, dict):
        remain = max(0, int(float(evac.get("ready_at", 0)) - time.time() * 1000) // 1000)
        evac_line = (f"\n🚪 撤离读条：{'紧急' if evac.get('mode') == 'emergency' else '正常'}"
                     f"｜{'就绪，可 #确认撤离' if remain == 0 else f'还需 {remain} 秒'}")
    return "\n".join([
        "【仙古秘境·状态】",
        f"👤 {getattr(doc, 'name', '')}｜{realm_name(xg_level_of(doc))}（{xg_level_of(doc)}/11）",
        f"📍 {frag.get('name', '未知区域')}（{frag.get('zone', '?')}）｜"
        f"坐标 [{map_st.get('pos', {}).get('x', 0)}, {map_st.get('pos', {}).get('y', 0)}]",
        f"👣 步数：{map_st.get('steps', 0)}｜揭示 {revealed}/{int(map_st.get('w', 11)) * int(map_st.get('h', 11))} 格",
        f"💎 道韵：{int(gains.get('daoyun', 0) or 0)}｜唯一机缘：{int(gains.get('unique_found', 0) or 0)}",
        f"🎒 背包：物品 {bag['item_count']}｜道种 {bag['seed_count']}｜"
        f"源石 {bag['source_stone']:,}｜战利品单位 {bag['loot_units']}",
        f"😈 凶名：{int(st.get('infamy', 0) or 0)}｜击杀：{int(st.get('kills', 0) or 0)}"
        + ("｜🩸重伤中" if explore_efficiency(st, time.time()) < 1 else "")
        + evac_line,
        "", lifecycle_brief(lc, world_year)])


def rules_text() -> str:
    cfg = load_config()
    ec = evac_config()
    return "\n".join([
        "【仙古秘境·规则】",
        "「仙古纪元碎片化作花蕾，三千道州气运汇聚时绽放，秘境门户开启。」",
        "",
        "【准入】仙古境界 铭文(5)~尊者(7)｜位面：九天十地｜冷却 12 小时",
        "【地图】14 碎片 × 11×11 迷雾网格｜八方向移动（#上/#左上5）",
        "【区域】边缘(5铭文)→中层(6列阵)→深层/火道/擂台/核心(7尊者)→终极(冠军)/隐藏(8神火)",
        "【撤离】核心区域 #离开仙古秘境（10-60s 读条）；任意区域 #紧急撤离（30-90s）；"
        "确认窗口 120s，移动/掉血中断",
        "【道种】机缘格/Boss/唯一机缘三路掉落；区域越深品质越高",
        "【神火】苦修/丹药/道种孕育/祭炼真我 四路点燃；顶级仙种→神火极境→仙气",
        f"【生命周期】闭合 → 花蕾现世({LIFE_PREPARE_Y}年) → 绽放({LIFE_OPEN_Y}年) → 闭合，"
        f"每 {LIFE_BLOOM_INTERVAL_Y} 年判定一次，逐次 +10% 开启概率",
        "",
        "【指令速查】#进入仙古秘境 / #秘境状态 / #秘境地图 / #秘境探索(1/2/3) / "
        "#上#下#左#右#左上… / #秘境推演 / #秘境背包 / #秘境目标 / #寻找NPC / "
        "#离开仙古秘境 / #紧急撤离 / #确认撤离 / #查看道种 / #查看神火 / #祭炼真我",
    ])


# ---------------------------------------------------------------- 探索回合编排（#秘境探索 / 1|2|3）

EXPLORE_CD_MS = 25_000
MOVE_CD_MS = 2_000
OPTIONS_TTL_MS = 60_000


def _cd_ready(st: dict, key: str, now_ms: float) -> tuple[bool, int]:
    until = float((st.get("cd") or {}).get(key, 0) or 0)
    if now_ms < until:
        return False, int((until - now_ms) / 1000) + 1
    return True, 0


def _cd_set(st: dict, key: str, until_ms: float) -> None:
    st.setdefault("cd", {})[key] = float(until_ms)


def explore_turn(doc: Any, st: dict, rng: Callable[[], float], now_ms: float,
                 claims: Mapping | None = None) -> tuple[str, dict]:
    """#秘境探索：仙髓池显化 + 揭示 + 出口悟道 + 共鸣/神识反馈 + 三选项。"""
    events: dict[str, Any] = {"placed_pool": None}
    map_st = st.get("map")
    if not map_st:
        return "秘境地图已失效，请重新进入。", events
    ok, remain = _cd_ready(st, "explore", now_ms)
    if not ok:
        return (f"【探索冷却中】稍作休整，等待下一次探索...剩余 {remain} 秒。\n"
                "提示：秘境中不宜频繁探索，以免惊动守护者"), events
    _cd_set(st, "explore", now_ms + EXPLORE_CD_MS)
    if claims is not None:
        sync_shared_claims(st, claims)
    cfg = marrow_config()
    exits_before = len(revealed_exits(map_st))
    placed = None
    if rng.random() < cfg["chance"] * explore_efficiency(st, now_ms / 1000):
        placed = place_marrow_pool(map_st, rng)
        if placed:
            events["placed_pool"] = placed["pos"]
    reveal(map_st, map_st["pos"], divine_range(doc))
    exit_gain = exit_discovery_daoyun(st, map_st, exits_before, doc)

    lines: list[str] = []
    if placed:
        lines += [f"💧【机缘显化·{MARROW_POOL_NAME}】",
                  "神识扫过时，万道水光忽然冲破迷雾！",
                  f"宝池坐标：[{placed['pos']['x']}, {placed['pos']['y']}]，可按地图方向前往。", ""]
    if exit_gain > 0:
        lines.append(f"⊕【出口悟道】新出口的空间法则显化，道韵 +{exit_gain}。")
    if explore_efficiency(st, now_ms / 1000) < 1:
        lines.append("🩸【重伤】神识运转受阻，本次机缘发现率降低50%。")
    for echo in check_echo(map_st):
        lines.append(f"🔥【道韵共鸣】{echo['msg']}")
    perceptions = divine_perception(map_st, doc, rng)
    if perceptions:
        lines.append("👁️【神识反馈】")
        lines += [f"· {p}" for p in perceptions[:6]]
    if map_st.get("fragment_id") == "chaos_mosquito":
        loss = _mosquito_drain(doc)
        lines.append(f"🦟 混沌蚊群疯狂吸血！-{loss:,}...")
    options = explore_options(str(st.get("location") or FRAGMENTS.get(map_st["fragment_id"], {}).get("zone", "边缘区域")), rng)
    st["options"] = {"expires_at": now_ms + OPTIONS_TTL_MS,
                     "list": json.loads(json.dumps(options, ensure_ascii=False))}
    frag = FRAGMENTS.get(map_st["fragment_id"], {})
    revealed = sum(1 for row in map_st["revealed"] for c in row if c)
    lines += ["", render_grid(map_st, doc, st.get("gains")),
              "", options_text(options),
              "",
              f"碎片：{frag.get('name', '未知')}｜探索步数：{map_st.get('steps', 0)}｜"
              f"揭示进度：{revealed}/{int(map_st['w']) * int(map_st['h'])}格",
              f"描述：{frag.get('desc', '')}"]
    return "\n".join(lines), events


def divine_perception(map_st: Mapping, doc: Any, rng: Callable[[], float]) -> list[str]:
    """神识反馈（按方向去重取最近，空地 30% 氛围文案）。"""
    rng_range = divine_range(doc)
    px, py = map_st["pos"]["x"], map_st["pos"]["y"]
    grouped: dict[str, tuple[int, str]] = {}
    for dy in range(-rng_range, rng_range + 1):
        for dx in range(-rng_range, rng_range + 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = px + dx, py + dy
            if not (0 <= ny < int(map_st["h"]) and 0 <= nx < int(map_st["w"])):
                continue
            cell = map_st["grid"][ny][nx]
            dist = abs(dx) + abs(dy)
            dir_name = _direction_name(dx, dy)
            msg = {
                CELL_WALL: "前方虚空断裂，无法逾越",
                CELL_TREASURE: "有灵光吞吐，似有机缘",
                CELL_DANGER: "杀意凛然，令人心悸",
                CELL_NPC: "一道气息正在徘徊——有修士在此",
                CELL_EXIT: "隐约感应到出口的气息",
                CELL_VOID: "空间扭曲——有虚空裂缝！",
                CELL_UNIQUE: ("万道水声轻鸣——仙髓宝池就在附近！" if is_marrow_position(map_st, nx, ny)
                              else "🔥浩瀚道韵波动——绝世机缘就在附近！"),
                CELL_EXPLORED: "已被搜刮，空空如也",
            }.get(cell)
            if msg is None and cell == CELL_EMPTY and rng.random() < 0.3:
                msg = _pick(rng, ["气息平静，暂无异常", "灵气稀薄，似乎没什么特别", "风过无痕，一片荒芜"])
            if msg and (dir_name not in grouped or grouped[dir_name][0] > dist):
                grouped[dir_name] = (dist, f"{dir_name}：{msg}")
    return [v[1] for v in grouped.values()]


def choose_explore(doc: Any, st: dict, idx: int, cfg: Mapping, rng: Callable[[], float],
                   now_ms: float, battle: Callable | None = None,
                   claims: Mapping | None = None) -> tuple[str, dict]:
    """1/2/3 选项结算：过期作废、战败抉择拦截、收益入账。"""
    events: dict[str, Any] = {}
    options = st.get("options") or {}
    lst = options.get("list") if isinstance(options, dict) else None
    if not lst or now_ms > float(options.get("expires_at", 0) or 0):
        st.pop("options", None)
        return "【选项已消散】机缘稍纵即逝，请重新 #秘境探索。", events
    if not 1 <= idx <= len(lst):
        return f"【无效选择】请回复 1-{len(lst)}。", events
    pending = st.get("pending_defeat")
    if isinstance(pending, dict):
        if float(pending.get("expires_at", 0) or 0) < now_ms:
            text = settle_defeat_choice(doc, st, "slaughter", now_ms)
            return text, {**events, "defeated": True}
        return ("【身陷绝境】你正被「" + str(pending.get("npc") or "秘境存在")
                + "」压制，生死未卜！\n\n请先发送 #求饶 或 #任凭鱼肉 做出抉择。"), events
    chosen = lst[idx - 1]
    st.pop("options", None)
    if claims is not None:
        sync_shared_claims(st, claims)
    location = str(st.get("location") or FRAGMENTS.get((st.get("map") or {}).get("fragment_id", ""), {}).get("zone", "边缘区域"))
    text, gains = perform_explore(doc, st, location, chosen.get("bias"), cfg, rng,
                                  now_ms / 1000, battle)
    gains_st = st.setdefault("gains", {})
    for key, value in gains.items():
        if key in ("daoyun", "xiongmng"):
            continue
        gains_st[key] = int(gains_st.get(key, 0) or 0) + int(value)
    events["defeated"] = bool(st.get("pending_defeat"))
    return text, events


# ---------------------------------------------------------------- 战败抉择（#求饶 / #任凭鱼肉）

DAOHEART_TARNISH_MS = 24 * 3600 * 1000


def settle_defeat_choice(doc: Any, st: dict, choice: str, now_ms: float) -> str:
    """求饶 / 任凭鱼肉 / 逾期兜底（slaughter）。返回文案；eject 由 handler 落库。"""
    pending = st.pop("pending_defeat", None) or {}
    npc_name = str(pending.get("npc") or "秘境存在")
    overdue = choice == "slaughter" and float(pending.get("expires_at", 0) or 0) < now_ms
    lost = bag_summary(st.get("bag") or {})
    if choice == "mercy":
        # 善良存在放行；邪恶存在仍会痛下杀手（原版掷定）
        evil = str((pending.get("faction") or "evil")) == "evil"
        if not evil:
            return "\n".join([
                "【求饶·幸免】",
                f"「{npc_name}」见你卑辞厚礼，冷哼一声，拂袖而去。", "",
                "【后果】秘境收获保留｜道心蒙尘 24 小时（道韵收益减半）"])
        bag_new_clear(st)
        st["daoheart_tarnish_until"] = now_ms + DAOHEART_TARNISH_MS
        return "\n".join([
            "【求饶·仍遭毒手】",
            f"「{npc_name}」眼中杀意不减——邪恶存在不会因求饶止步！", "",
            "【后果】秘境背包全部收获被夺走｜被击杀逐出秘境｜道心 -50"])

    bag_new_clear(st)
    st["daoheart_tarnish_until"] = now_ms + DAOHEART_TARNISH_MS
    head = "【犹豫不决·身死道消】" if overdue else "【任凭鱼肉·任人宰割】"
    tail = "犹豫之间，杀机已至！" if overdue else '"倒是有几分自知之明..."'
    return "\n".join([
        head,
        f"你不做反抗，任由「{npc_name}」处置——{tail}", "",
        "【后果】",
        f"秘境背包中的全部收获被夺走（物品 {lost['item_count']}｜道种 {lost['seed_count']}）",
        "被击杀，逐出秘境",
        "秘境界限：冷却中（伤愈后方可再入）"])


def bag_new_clear(st: dict) -> None:
    """清空背包（战败损失）。"""
    st["bag"] = bag_new()


def eject_after_defeat(doc: Any, st: dict, now_ms: float) -> tuple[str, dict]:
    """被击杀逐出：清会话 + 12h 冷却。返回 (summary, record)。"""
    summary = run_summary(st, now_ms / 1000)
    clear_session(st, summary)
    ecfg = evac_config()
    st.setdefault("cd", {})["enter_until"] = now_ms + ecfg["cooldown_h"] * 3600 * 1000
    return summary, {"reason": "defeat"}
