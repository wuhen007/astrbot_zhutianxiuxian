"""锻造深层 / 锻炉 · 神兵榜 · 炼器师（W8-C4，纯函数无 IO）。

原版取证：`apps/duanzao/duanzao.js`（1547 行 / **19 条 rule，0 别名**）、
`model/duanzaofu.js`（299 行）、`resources/data/item/{炼器炉,炼器火,锻造材料,
锻造武器,锻造护具,锻造宝物,功法列表,隐藏灵根}.json`。

流程（按源码实际顺序，规划稿写的「加温 → 熔炼 → 开炉 → 出炉」是错的）：
    建档(#炼器师能力评测) → 安装炉阶 → 点燃炉火 → 投料(#熔炼)
    → 温养(#开始炼制) → 出炉(#开炉 / #一键开炉 / #一键完美开炉)
**没有温度、没有成功率、没有评级表、没有升阶炉、没有独立的「出炉」指令。**
`#熔炼` 是投料，`#开炉` 就是出炉；`xishu` 是加法系数不是概率。

shortcut（与原版差异，写清楚便于以后升级）：
1. 原版 `duanlu.json` 是**全服共用一个数组**（按 qq 索引），本移植改为玩家私有
   `doc.ext["forge"]`：单人单档写回，避免整档互相覆盖，也复用既有 `_dz_apply` 事务。
2. 原版产出是带九维的动态装备对象，塞进纳戒「装备」数组；本移植背包是
   `dict[str,int]`、穿戴按名字查 `item_index`，故私有神兵卡存 `ext["forge"]["artifacts"]`，
   由 `main._stats` 注入 lookup（复用「本命帝兵」既有模式）消费。
3. 原版成品三维封顶 499（百分比倍率语义）；本移植 `_split` 把 >1 当固定值，
   故 `item_card()` 统一 clamp 到 0.99 走比例乘区；原始数值另存 artifacts 供赋名门槛/评分。
4. 原版开铸三项分处两处存储（炉阶在 duanlu.json、炉火/熟练度在玩家档），
   本移植统一在 `ext["forge"]`；**未建档的旧存档回退 C3 职业等级 ≥20**，
   建档后走原版严格三项（见 `gate()`），保证 C3 已有进度不被卡死。
5. 时间单位：原版毫秒 → 本移植秒，分钟数不变（温养 180、开炉下限 30、
   完美窗口 (80*sum+10) 分钟、榜单 CD 30 分钟）。
6. 神兵榜：原版扫 custom.json + 全服纳戒，本移植扫 `all_players()` 的私有
   artifacts，Top20 缓存进全服状态，30 分钟重建；同样**无奖励**。
7. `#神兵重铸` 与既有 `CMD_RECAST` 撞名 → 不重复注册，只在既有 handler 里补同步。
8. 跳过：仙宠炼器加成、丹药备用位、万道神炉待用、天骄夺炉战、岁云月华仙炉
   月华值分支、五行 `Restraint()` 随机词缀（收敛为固定表）、redis 动作互斥、
   FileRollbackTransaction、puppeteer 榜单截图。`#全体清空锻炉` 保留为管理员指令。
9. 炉阶「月华仙炉」容量取源码硬编码 34（`duanzaofu.js:29`，测试亦断言 34），
   而非 `炼器炉.json` 的 77。
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

WORLD_KEY = "forge"
EXT_KEY = "forge"

# 炉阶：name / 阶位 / 容纳量 / xishu（与 data/item/炼器炉.json 一致）
FURNACES: tuple[dict[str, Any], ...] = (
    {"name": "凡铁炉", "阶位": 0, "容纳量": 10, "xishu": 0.0},
    {"name": "玄铁炉", "阶位": 1, "容纳量": 12, "xishu": 0.03},
    {"name": "地火炉", "阶位": 2, "容纳量": 15, "xishu": 0.05},
    {"name": "天火炉", "阶位": 3, "容纳量": 18, "xishu": 0.10},
    {"name": "混沌炉", "阶位": 4, "容纳量": 21, "xishu": 0.18},
    {"name": "造化仙炉", "阶位": 5, "容纳量": 34, "xishu": 0.35},
    {"name": "月华仙炉", "阶位": 5, "容纳量": 34, "xishu": 0.35, "岁云专属": True},
)
# 炉火：name / 品级 / 缩短比例（与 data/item/炼器火.json 一致）
FIRES: tuple[dict[str, Any], ...] = (
    {"name": "凡火", "品级": 1, "缩短比例": 0.0},
    {"name": "灵火", "品级": 2, "缩短比例": 0.18},
    {"name": "帝火", "品级": 3, "缩短比例": 0.32},
    {"name": "仙火", "品级": 4, "缩短比例": 0.45},
    {"name": "道火", "品级": 5, "缩短比例": 0.60},
    {"name": "大空火种", "品级": 6, "缩短比例": 0.72},
)
# 功法：name / xishu / windowBonus(分钟) / timeCut / cost(灵石)
GONGFA: tuple[dict[str, Any], ...] = (
    {"name": "锻铁诀", "品级": "凡", "xishu": 0.03, "windowBonus": 0, "timeCut": 0.0, "cost": 0},
    {"name": "百炼诀", "品级": "灵", "xishu": 0.08, "windowBonus": 2, "timeCut": 0.0, "cost": 50_000},
    {"name": "九转炼器诀", "品级": "仙", "xishu": 0.14, "windowBonus": 0, "timeCut": 0.15, "cost": 200_000},
    {"name": "乾坤炼器经", "品级": "帝", "xishu": 0.20, "windowBonus": 3, "timeCut": 0.10, "cost": 800_000},
    {"name": "无上炼器道", "品级": "道", "xishu": 0.30, "windowBonus": 4, "timeCut": 0.20, "cost": 2_000_000},
)

WARM_MIN = 180.0            # 温养基准 180 分钟
OPEN_MIN = 30.0             # 普通开炉的最短经过时长
BOARD_CD = 1_800.0          # 神兵榜 30 分钟
BOARD_TOP = 20
NAME_MAX = 8                # 赋名 8 码点（equipmentNaming.js:1）
MAX_CARD_RATIO = 0.99       # item_card 收敛上限，见 shortcut 3
ARTIFACT_PREFIX = ("锻造武器", "锻造护具", "锻造宝物")

# 五行词缀：非零五维个数 → (词缀, xishu 加成)。原版 2 项由 Restraint() 随机给 0.5/0.3/0.2/0.08，
# 这里收敛为固定 0.08，避免引入无消费者的削防分支。
ELEMENT_AFFIX: dict[int, tuple[str, float]] = {
    5: ("五行杂灵", 0.10), 4: ("四圣显化", 0.07), 3: ("三灵共堂", 0.05),
    2: ("双相共鸣", 0.08), 1: ("纯灵", 0.15), 0: ("终极至宝", 0.35),
}

# 时光令配方（data/item/合成列表.json 已有条目，但「传承要求」在本移植无消费者）
TIME_TOKEN_MATS: dict[str, int] = {"时光石": 2, "世界石": 1, "天外清风": 1, "符纸": 10}
TIME_TOKEN = "时光令"
RECIPE_ITEM = "时光令配方"
PERFECT_MATS = {TIME_TOKEN: 1, "造化本源": 1}


def _ok(msg: str, delta: dict[str, int] | None = None) -> tuple[bool, str, dict[str, int]]:
    return True, msg, delta or {}


def _no(msg: str) -> tuple[bool, str, dict[str, int]]:
    return False, msg, {}


def _furnace(name: Any) -> dict[str, Any] | None:
    return next((f for f in FURNACES if f["name"] == str(name or "")), None)


def _fire(name: Any) -> dict[str, Any] | None:
    return next((f for f in FIRES if f["name"] == str(name or "")), None)


def _gongfa(name: Any) -> dict[str, Any] | None:
    return next((g for g in GONGFA if g["name"] == str(name or "")), None)


# ── 状态 ────────────────────────────────────────────────────────────────
def _blank() -> dict[str, Any]:
    return {
        "built": False, "talent": 0, "hidden": "", "furnace": "凡铁炉",
        "owned_furnaces": ["凡铁炉"], "fire": "凡火", "owned_fires": ["凡火"],
        "gongfa": None, "proficiency": 0, "recipe": False,
        "materials": [],          # list[[材料名, 数量]]
        "TIME": 0.0, "status": 0,
        "artifacts": {},          # 神兵名 → 原始卡（含 atk/def/HP/bao/score）
        "forges": 0,
    }


def state_of(doc: Any) -> dict[str, Any]:
    """懒建档：不写 built，只保证字段齐全（built 由 #炼器师能力评测 置位）。"""
    st = doc.ext.get(EXT_KEY)
    if not isinstance(st, dict):
        st = {}
        doc.ext[EXT_KEY] = st
    for k, v in _blank().items():
        st.setdefault(k, v if not isinstance(v, (dict, list)) else type(v)(v))
    if not isinstance(st.get("materials"), list):
        st["materials"] = []
    if not isinstance(st.get("artifacts"), dict):
        st["artifacts"] = {}
    return st


def world_of(state: Mapping[str, Any]) -> dict[str, Any]:
    w = state.get(WORLD_KEY)
    if not isinstance(w, dict):
        return {"named": {}, "board_cd": 0.0, "board": [], "rumors": []}
    w.setdefault("named", {})
    w.setdefault("board_cd", 0.0)
    w.setdefault("board", [])
    w.setdefault("rumors", [])
    return w  # type: ignore[return-value]


def set_world(state: dict[str, Any], world: Mapping[str, Any]) -> None:
    state[WORLD_KEY] = dict(world)


def item_card(doc: Any, name: str) -> dict[str, Any] | None:
    """供 `main._stats` 注入 lookup：把私有神兵卡转成 equipment.aggregate 认得的形状。"""
    st = doc.ext.get(EXT_KEY)
    if not isinstance(st, dict):
        return None
    art = (st.get("artifacts") or {}).get(name)
    if not isinstance(art, dict):
        return None
    return {
        "name": name, "class": "装备", "type": art.get("type") or "武器",
        "atk": min(float(art.get("atk") or 0), MAX_CARD_RATIO),
        "def": min(float(art.get("def") or 0), MAX_CARD_RATIO),
        "HP": min(float(art.get("HP") or 0), MAX_CARD_RATIO),
        "bao": float(art.get("bao") or 0), "稀有度": int(art.get("稀有度") or 1),
    }


# ── C3 回填：开铸三项校验 ────────────────────────────────────────────────
def gate(doc: Any) -> tuple[bool, str, bool]:
    """原版 `DaoTreasure.js:207-214` 的炉阶/炉火/无上炼器道熟练度。

    返回 (通过?, 失败文案, 是否走严格口径)。未建档的旧存档返回 strict=False，
    由 `daotreasure.open_forge` 回退到职业等级 ≥20，避免卡死 C3 已有进度。
    """
    raw = doc.ext.get(EXT_KEY)
    if not isinstance(raw, dict) or not raw.get("built"):
        return True, "", False
    st = state_of(doc)
    if st.get("furnace") not in ("混沌炉", "造化仙炉"):
        return False, "开铸需安装【混沌炉】或【造化仙炉】，当前为「%s」。" % st.get("furnace"), True
    if st.get("fire") != "道火":
        return False, "开铸需点燃【道火】，当前为「%s」。" % st.get("fire"), True
    if st.get("gongfa") != "无上炼器道" or int(st.get("proficiency") or 0) < 100:
        return False, "需将【无上炼器道】修至 100 熟练度，方能承受文明炉火。", True
    return True, "", True


# ── 建档 / 炉阶 / 炉火 / 功法 ────────────────────────────────────────────
def evaluate(doc: Any, rng: random.Random,
             hidden_table: Sequence[Mapping[str, Any]] | None = None
             ) -> tuple[bool, str, dict[str, int]]:
    """`#炼器师能力评测`：一次性随机天赋 80~119 + 隐藏灵根，赠凡铁炉/凡火。"""
    st = state_of(doc)
    if st.get("built"):
        return _no("您已经测评过了。")
    if str(doc.ext.get("occupation") or "") != "炼器师":
        return _no("请先转职为炼器师，再来评测锻造天赋。")
    st["built"] = True
    st["talent"] = int(80 + rng.random() * 40)
    rows = [r for r in (hidden_table or ()) if isinstance(r, Mapping) and r.get("name")]
    st["hidden"] = str(rows[int(rng.random() * len(rows))]["name"]) if rows else "真火灵根"
    return _ok(f"获得煅炉，天赋[{st['talent']}]，隐藏灵根为[{st['hidden']}]。\n"
               "发 #炼器炉 看炉阶、#炉火 看火种、#我的锻炉 看炉内明细。")


def show_furnace(doc: Any) -> str:
    st = state_of(doc)
    lines = [f"【炼器炉】当前：{st['furnace']}（{_furnace(st['furnace']) or {}}）"]
    lines.append("已拥有：" + "、".join(st.get("owned_furnaces") or ["凡铁炉"]))
    lines.append("—— 七阶炉表 ——")
    for f in FURNACES:
        lines.append(f"· {f['name']}（{f['阶位']} 阶）容纳 {f['容纳量']}｜系数 +{f['xishu']:.2f}")
    lines.append("安装：#安装锻炉 <炉名>（需先拥有该炉道具；月华仙炉需岁云传承）")
    return "\n".join(lines)


def install_furnace(doc: Any, arg: str, inv: Mapping[str, int]
                    ) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    name = (arg or "").strip()
    f = _furnace(name)
    if not f:
        return _no(f"查无此炉「{name}」。发 #炼器炉 看炉表。")
    if int(st.get("status") or 0) == 1:
        return _no("炼制中不能更换锻炉。")
    if f.get("岁云专属"):
        return _no("月华仙炉需岁云传承后由 #炼器师能力评测 补领。")
    owned = list(st.get("owned_furnaces") or ["凡铁炉"])
    if name not in owned:
        if int(inv.get(name, 0) or 0) < 1:
            return _no(f"你尚未拥有【{name}】，请先前往 #战功商店 兑换。")
        owned.append(name)
        st["owned_furnaces"] = owned
    st["furnace"] = name
    return _ok(f"已安装【{name}】：容纳 {f['容纳量']}，开炉系数 +{f['xishu']:.2f}。")


def show_fire(doc: Any) -> str:
    st = state_of(doc)
    lines = [f"【炉火】当前：{st['fire']}"]
    lines.append("已拥有：" + "、".join(st.get("owned_fires") or ["凡火"]))
    lines.append("—— 六品火种 ——")
    for f in FIRES:
        lines.append(f"· {f['name']}（{f['品级']} 品）温养提速 {f['缩短比例'] * 100:.0f}%")
    return "\n".join(lines)


def light_fire(doc: Any, arg: str, inv: Mapping[str, int]
               ) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    name = (arg or "").strip()
    f = _fire(name)
    if not f:
        return _no(f"查无此火种「{name}」。发 #炉火 看火种表。")
    if int(st.get("status") or 0) == 1:
        return _no("炼制中不能更换炉火。")
    owned = list(st.get("owned_fires") or ["凡火"])
    if name not in owned:
        if int(inv.get(name, 0) or 0) < 1:
            return _no(f"你尚未拥有【{name}】火种。")
        owned.append(name)
        st["owned_fires"] = owned
    st["fire"] = name
    return _ok(f"已点燃【{name}】：温养提速 {f['缩短比例'] * 100:.0f}%。")


def show_gongfa(doc: Any) -> str:
    st = state_of(doc)
    lines = [f"【炼器功法】当前：{st.get('gongfa') or '未修炼'}｜熟练度 {int(st.get('proficiency') or 0)}/100"]
    lines.append("—— 五部功法 ——")
    for g in GONGFA:
        lines.append(f"· {g['name']}（{g['品级']}）系数 +{g['xishu']:.2f}"
                     f"｜完美窗口 +{g['windowBonus']} 分｜提速 {g['timeCut'] * 100:.0f}%｜{g['cost']:,} 灵石")
    lines.append("每次开炉熟练度 +2（满 100）；换功法重置为 0。")
    return "\n".join(lines)


def learn_gongfa(doc: Any, arg: str, inv: Mapping[str, int]
                 ) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    name = (arg or "").strip()
    g = _gongfa(name)
    if not g:
        return _no(f"查无此功法「{name}」。发 #炼器功法 看列表。")
    if st.get("gongfa") == name:
        return _no(f"你已在修炼【{name}】。")
    delta: dict[str, int] = {}
    cost = int(g["cost"])
    if int(inv.get(name, 0) or 0) >= 1:
        delta[name] = -1                       # 有功法本体则免灵石
    elif int(doc.stones or 0) >= cost:
        doc.stones = int(doc.stones or 0) - cost   # 灵石在玩家档，不走物品 delta
    else:
        return _no(f"修炼【{name}】需功法本体或 {cost:,} 灵石。")
    st["gongfa"] = name
    st["proficiency"] = 0
    return _ok(f"已修炼【{name}】，熟练度重置为 0。", delta)


def learn_recipe(doc: Any, inv: Mapping[str, int]) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    if st.get("recipe"):
        return _no("你已参悟【时光令配方】，无需重复。")
    if int(inv.get(RECIPE_ITEM, 0) or 0) < 1:
        return _no("参悟需要【时光令配方】（圣地战功商店兑换）。")
    st["recipe"] = True
    return _ok("已参悟【时光令配方】！可用 #合成时光令 消耗时光石×2 / 世界石×1 / "
               "天外清风×1 / 符纸×10 合成。", {RECIPE_ITEM: -1})


def synth_token(doc: Any, inv: Mapping[str, int], arg: str
                ) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    if not st.get("recipe"):
        return _no("需先 #参悟时光令配方。")
    try:
        n = max(1, min(99, int((arg or "1").strip() or "1")))
    except ValueError:
        return _no("格式：#合成时光令 数量")
    for k, q in TIME_TOKEN_MATS.items():
        if int(inv.get(k, 0) or 0) < q * n:
            return _no(f"材料不足：{k} 需 {q * n}，现有 {int(inv.get(k, 0) or 0)}。")
    delta = {k: -q * n for k, q in TIME_TOKEN_MATS.items()}
    delta[TIME_TOKEN] = n
    return _ok(f"合成【时光令】×{n}。", delta)


# ── 投料 / 温养 / 面板 ──────────────────────────────────────────────────
def _parse_qty(arg: str) -> tuple[str, int] | None:
    raw = (arg or "").strip().replace("×", "*").replace("x", "*")
    if "*" in raw:
        name, _, num = raw.rpartition("*")
        try:
            n = int(num.strip())
        except ValueError:
            return None
        return name.strip(), n
    return raw, 1


def capacity(st: Mapping[str, Any], doc: Any) -> int:
    f = _furnace(st.get("furnace")) or FURNACES[0]
    return int(f["容纳量"]) + int(doc.ext.get("occupation_level") or 0) // 2


def used(st: Mapping[str, Any]) -> int:
    return sum(int(q or 0) for _, q in (st.get("materials") or []))


def time_speed(st: Mapping[str, Any]) -> float:
    f = _fire(st.get("fire")) or FIRES[0]
    g = _gongfa(st.get("gongfa"))
    cut = float(f["缩短比例"]) + (float(g["timeCut"]) if g else 0.0)
    return 1.0 - min(0.95, cut)


def melt(doc: Any, inv: Mapping[str, int], arg: str,
         item_lookup: Callable[[str], Mapping[str, Any] | None]
         ) -> tuple[bool, str, dict[str, int]]:
    """`#熔炼<材料名>*<数量>` = 投料（不是加热）。"""
    st = state_of(doc)
    if str(doc.ext.get("occupation") or "") != "炼器师":
        return _no("切换到炼器师后再来吧。")
    parsed = _parse_qty(arg)
    if not parsed or not parsed[0] or parsed[1] <= 0:
        return _no("格式：#熔炼 材料名*数量")
    name, n = parsed
    row = item_lookup(name)
    if not isinstance(row, Mapping) or str(row.get("type")) != "锻造":
        return _no("凡界物品无法放入煅炉（仅 type=锻造 的九维材料可投）。")
    if int(inv.get(name, 0) or 0) < n:
        return _no("材料不足，无法放入。")
    if int(st.get("status") or 0) == 1:
        return _no("正在炼制中，无法熔炼更多材料。")
    cap = capacity(st, doc)
    if used(st) + n > cap:
        return _no(f"该煅炉当前只能容纳 {cap} 件物品（已投 {used(st)}）。")
    mats = list(st.get("materials") or [])
    for i, (mn, _q) in enumerate(mats):
        if mn == name:
            mats[i] = [mn, int(_q) + n]
            break
    else:
        mats.append([name, n])
    st["materials"] = mats
    return _ok(f"投入【{name}】×{n}（炉内 {used(st)}/{cap}）。", {name: -n})


def start(doc: Any, now: float) -> tuple[bool, str, dict[str, int]]:
    """`#开始炼制` = 温养启动。"""
    st = state_of(doc)
    if not st.get("materials"):
        return _no("炉子为空，无法炼制。")
    if int(st.get("status") or 0) == 1:
        return _no("锻炉已经在炼制中，无需重复启动。")
    st["status"] = 1
    st["TIME"] = float(now)
    mins = WARM_MIN * time_speed(st)
    return _ok(f"现在开始锻造武器，预计 {mins:.0f} 分钟后完成温养"
               f"（炉火/功法提速 {(1 - time_speed(st)) * 100:.0f}%）。\n"
               f"普通 #开炉 最短需 {OPEN_MIN * time_speed(st):.0f} 分钟；"
               "想省时间可 #一键开炉（耗时光令）或 #一键完美开炉。")


def clear(doc: Any) -> tuple[bool, str, dict[str, int]]:
    st = state_of(doc)
    st["materials"], st["TIME"], st["status"] = [], 0.0, 0
    return _ok("已清空锻炉：材料、温养计时与炼制状态复位（炉阶/炉火/功法保留）。")


def optimal_min(st: Mapping[str, Any], item_lookup: Callable[[str], Mapping[str, Any] | None]) -> float:
    """原版 `overtime = (80*num + 10) 分钟 × timeSpeed`，num = 材料九维前三项之和。"""
    s = _nine(st, item_lookup)
    return (80.0 * (s[0] + s[1] + s[2]) + 10.0) * time_speed(st)


def panel(doc: Any, now: float,
          item_lookup: Callable[[str], Mapping[str, Any] | None]) -> str:
    st = state_of(doc)
    f = _furnace(st.get("furnace")) or FURNACES[0]
    g = _gongfa(st.get("gongfa"))
    lines = [f"【我的锻炉】{f['name']}｜炉火 {st['fire']}｜功法 {st.get('gongfa') or '未修炼'}"
             f"（熟练 {int(st.get('proficiency') or 0)}/100）",
             f"天赋 {int(st.get('talent') or 0)}｜隐藏灵根 {st.get('hidden') or '未评测'}"
             f"｜时光令配方 {'已参悟' if st.get('recipe') else '未参悟'}",
             f"容量 {used(st)}/{capacity(st, doc)}｜温养提速 {(1 - time_speed(st)) * 100:.0f}%"
             f"｜开炉系数 +{(f['xishu'] + (g['xishu'] if g else 0.0) + int(st.get('proficiency') or 0) / 100 * 0.1):.2f}"]
    mats = st.get("materials") or []
    if mats:
        lines.append("—— 炉内材料 ——")
        lines += [f"· {n} ×{q}" for n, q in mats]
    else:
        lines.append("炉内空空如也。")
    if int(st.get("status") or 0) == 1:
        elapsed = max(0.0, now - float(st.get("TIME") or 0)) / 60.0
        best = optimal_min(st, item_lookup)
        wb = int(g["windowBonus"]) if g else 0
        lines.append(f"炼制中：已温养 {elapsed:.1f} 分钟｜完美窗口 {best:.1f} ±{2 + wb} 分钟"
                     f"（偏离 >{8 + wb} 分 -0.1，>{12 + wb} 分 -0.2）")
    else:
        lines.append("状态：空闲。发 #熔炼 投料 → #开始炼制 温养。")
    arts = st.get("artifacts") or {}
    if arts:
        lines.append(f"已铸神兵 {len(arts)} 件：" + "、".join(list(arts)[:6]))
    return "\n".join(lines)


# ── 开炉（三种模式共用一条实现，对齐 doForgeLocked） ─────────────────────
def _nine(st: Mapping[str, Any],
          item_lookup: Callable[[str], Mapping[str, Any] | None]) -> list[float]:
    """材料九维按数量加权求和：攻/防/血/暴/金/木/土/水/火。"""
    out = [0.0] * 9
    for name, q in (st.get("materials") or []):
        row = item_lookup(str(name))
        if not isinstance(row, Mapping):
            continue
        n = int(q or 0)
        for i, k in enumerate(("攻", "防", "血", "暴", "金", "木", "土", "水", "火")):
            try:
                out[i] += float(row.get(k) or 0) * n
            except (TypeError, ValueError):
                pass
    return out


def _affix(s: Sequence[float]) -> tuple[str, float]:
    n = sum(1 for v in s[4:9] if float(v) > 0)
    return ELEMENT_AFFIX.get(min(5, n), ELEMENT_AFFIX[5])


def open_forge(doc: Any, mode: str, inv: Mapping[str, int], now: float, *,
               item_lookup: Callable[[str], Mapping[str, Any] | None],
               templates: Sequence[Mapping[str, Any]],
               rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    """开炉 = 出炉。mode ∈ {normal, oneclick, perfect}。"""
    st = state_of(doc)
    if str(doc.ext.get("occupation") or "") != "炼器师":
        return _no("唯有炼器师能够开炉。")
    if not st.get("materials"):
        return _no("煅炉里面空空如也，也许自己还没有放入材料。")
    delta: dict[str, int] = {}
    if mode == "normal":
        if not float(st.get("TIME") or 0) or int(st.get("status") or 0) != 1:
            return _no("煅炉里面空空如也，也许自己还没有启动它。")
        elapsed_min = (now - float(st["TIME"])) / 60.0
        if elapsed_min < OPEN_MIN * time_speed(st):
            return _no("炼制时间过短，无法获得装备，再等等吧。")
    elif mode == "oneclick":
        if int(inv.get(TIME_TOKEN, 0) or 0) < 1:
            return _no("一键开炉需要【时光令】，你还没有此物（可 #合成时光令）。")
        delta[TIME_TOKEN] = -1
    elif mode == "perfect":
        if int(inv.get(TIME_TOKEN, 0) or 0) < 1 or int(inv.get("造化本源", 0) or 0) < 1:
            return _no("一键完美开炉需要【时光令】+【造化本源】。")
        delta[TIME_TOKEN] = -1
        delta["造化本源"] = -1
    else:
        return _no("未知开炉模式。")

    s = _nine(st, item_lookup)
    furn = _furnace(st.get("furnace")) or FURNACES[0]
    gf = _gongfa(st.get("gongfa"))
    affix_name, affix_x = _affix(s)
    xishu = 1.0 + float(furn["xishu"]) + (float(gf["xishu"]) if gf else 0.0) \
        + int(st.get("proficiency") or 0) / 100 * 0.1 + affix_x
    window_note = ""
    if mode == "perfect":
        xishu += 0.1
        window_note = "强制完美 +0.10"
    elif mode == "normal":
        wb = int(gf["windowBonus"]) if gf else 0
        diff = abs(optimal_min(st, item_lookup) - (now - float(st["TIME"])) / 60.0)
        if diff < 2 + wb:
            xishu += 0.1
            window_note = f"踏中完美窗口（偏离 {diff:.1f} 分）+0.10"
        elif diff > 12 + wb:
            xishu -= 0.2
            window_note = f"火候过头（偏离 {diff:.1f} 分）-0.20"
        elif diff > 8 + wb:
            xishu -= 0.1
            window_note = f"火候略偏（偏离 {diff:.1f} 分）-0.10"
    else:
        window_note = "一键开炉：跳过时间衰减"

    atk = min(499.0, int(s[0] * xishu * 1000) / 1000)
    defense = min(499.0, int(s[1] * xishu * 1000) / 1000)
    hp = min(499.0, int(s[2] * xishu * 1000) / 1000)
    bao = int(s[3] * 1000) / 1000          # 原版 bao 不乘 xishu
    if atk + defense + hp <= 0:
        return _no("材料没有可提炼的三元之气，开炉无所得。")

    # 产出类型（原版 635-650）
    if s[0] > s[1] * 2:
        typ = "武器"
    elif s[0] * 2 < s[1]:
        typ = "护具"
    elif rng.random() > 0.8:
        typ = "法宝"
    elif s[0] > s[1]:
        typ = "武器"
    else:
        typ = "护具"
    slot = {"武器": "武器", "护具": "护具", "法宝": "法宝"}[typ]
    cand = [t for t in templates if isinstance(t, Mapping)
            and str(t.get("type")) == typ and t.get("name")]
    tmpl = min(cand, key=lambda t: abs(float(t.get("atk") or 0) - atk)
               + abs(float(t.get("def") or 0) - defense)
               + abs(float(t.get("HP") or 0) - hp)) if cand else None
    base_name = str((tmpl or {}).get("name") or "无名神兵")
    rarity = max(1, min(10, int((tmpl or {}).get("稀有度") or 2)))
    new_name = f"{base_name}·{affix_name}·{int(now * 1000) % 100000:05d}"
    score = int((atk * 1.2 + defense * 1.5 + hp * 1.5) * 10000
                + {"法宝": 2000, "护具": 1000}.get(slot, 0))

    st["artifacts"][new_name] = {
        "name": new_name, "type": slot, "atk": atk, "def": defense, "HP": hp,
        "bao": bao, "稀有度": rarity, "score": score, "affix": affix_name,
        "author": doc.name or doc.uid[:8], "created": float(now), "named": False,
    }
    delta[new_name] = 1

    # 职业经验：原版 z = floor(sum*1000*0.7*k+200)，k 由天赋/隐藏灵根决定
    talent = int(st.get("talent") or 100)
    v = 1.0 if not st.get("hidden") else 0.8
    k = ((talent + 100) * v) / 200 + 1
    gain = int((s[0] + s[1] + s[2]) * 1000 * 0.7 * k + 200)
    st["proficiency"] = min(100, int(st.get("proficiency") or 0) + 2)
    st["forges"] = int(st.get("forges") or 0) + 1
    st["materials"], st["TIME"], st["status"] = [], 0.0, 0
    doc.ext["occupation_exp"] = int(doc.ext.get("occupation_exp") or 0) + gain

    return _ok(
        f"【开炉·{'完美' if mode == 'perfect' else '一键' if mode == 'oneclick' else '常规'}】\n"
        f"获得 {new_name}（{slot}｜{rarity} 阶｜灵韵 {score:,}）\n"
        f"三维 攻 {atk:.3f} / 防 {defense:.3f} / 血 {hp:.3f}｜暴 {bao:.3f}\n"
        f"词缀【{affix_name}】｜总系数 ×{xishu:.2f}｜{window_note}\n"
        f"熟练度 +2（现 {st['proficiency']}/100）｜炼器经验 +{gain:,}\n"
        f"发 #赋名 {new_name}*新名 可登记神兵榜；#我的锻炉 看全部产出。", delta)


# ── 赋名 / 神兵榜 / 管理员 ──────────────────────────────────────────────
def _nameable(a: Mapping[str, Any]) -> bool:
    """原版 isNameablePercentageEquipment（用未 clamp 的原始数值判定）。"""
    atk, df = float(a.get("atk") or 0), float(a.get("def") or 0)
    return atk >= 1.5 or df >= 1.2 or (a.get("type") == "法宝" and (atk >= 1 or df >= 1)) \
        or atk + df > 1.95


def name_it(doc: Any, inv: Mapping[str, int], arg: str, world: dict[str, Any],
            now: float, name_exists: Callable[[str], bool]
            ) -> tuple[bool, str, dict[str, int]]:
    """`#赋名<原名>*<新名>`：8 码点、全服唯一、无灵石消耗、写榜单登记。"""
    old, _, new = (arg or "").strip().replace("×", "*").rpartition("*")
    old, new = old.strip(), new.strip()
    if not old or not new:
        return _no("格式：#赋名 原神兵名*新名")
    if len(new) > NAME_MAX or any(c in new for c in "\r\n<>*"):
        return _no("字符超出最大限制（8 字），或含非法字符，请重新赋名。")
    st = state_of(doc)
    arts = st.setdefault("artifacts", {})
    a = arts.get(old)
    if not isinstance(a, dict):
        return _no("只能给 #开炉 产出的神兵赋名（发 #我的锻炉 查看）。")
    if int(inv.get(old, 0) or 0) < 1:
        return _no(f"你没有这件神兵（{old}）。")
    if a.get("named"):
        return _no("一个装备只能赋名一次（改名请用 #神兵重铸）。")
    if new == old or new in arts or new in (world.get("named") or {}) or name_exists(new):
        return _no("这个世间已经拥有这把武器了。")
    if not _nameable(a):
        return _no("您的装备太弱了，无法赋予名字。")
    arts.pop(old)
    a.update({"name": new, "named": True, "named_at": float(now)})
    arts[new] = a
    eq = doc.ext.get("equipment")
    if isinstance(eq, dict):
        for slot, n in list(eq.items()):
            if n == old:
                eq[slot] = new
    named = world.setdefault("named", {})
    named[new] = {"uid": doc.uid, "author": a.get("author"), "owner": doc.name or doc.uid[:8],
                  "type": a.get("type"), "atk": a.get("atk"), "def": a.get("def"),
                  "HP": a.get("HP"), "score": int(a.get("score") or 0),
                  "稀有度": a.get("稀有度"), "Time": float(now)}
    world.setdefault("rumors", []).append(
        {"uid": doc.uid, "name": new, "old": old, "Time": float(now), "event": "赋名"})
    world["rumors"] = world["rumors"][-30:]
    world["board_cd"] = 0.0                 # 赋名后强制下次重建
    return _ok(f"【{new}】已刻入诸天神兵谱（灵韵 {int(a.get('score') or 0):,}）。\n"
               "发 #神兵榜 看全服排行。", {old: -1, new: 1})


def sync_recast(doc: Any, old: str, new: str, world: dict[str, Any]) -> None:
    """既有 `CMD_RECAST` 改名后同步私有神兵卡与榜单登记（不改榜单 score）。"""
    st = doc.ext.get(EXT_KEY)
    if not isinstance(st, dict):
        return
    arts = st.get("artifacts") or {}
    a = arts.pop(old, None)
    if isinstance(a, dict):
        a["name"] = new
        arts[new] = a
    rec = (world.get("named") or {}).pop(old, None)
    if isinstance(rec, dict):
        rec["name"] = new
        world.setdefault("named", {})[new] = rec
    world["board_cd"] = 0.0


def board(world: dict[str, Any], players: Sequence[Mapping[str, Any]], now: float) -> str:
    """神兵榜：扫全服私有神兵（仅已赋名登记者上榜），Top20，30 分钟缓存。"""
    if not world.get("board_cd") or float(now) - float(world["board_cd"]) > BOARD_CD:
        rows: list[dict[str, Any]] = []
        for p in players:
            ext = p.get("ext")
            if not isinstance(ext, dict):
                continue
            st = ext.get(EXT_KEY)
            if not isinstance(st, dict):
                continue
            for n, a in (st.get("artifacts") or {}).items():
                if not isinstance(a, dict) or not a.get("named"):
                    continue
                rows.append({"name": n, "type": a.get("type") or "武器",
                             "score": int(a.get("score") or 0),
                             "author": a.get("author") or "神秘匠师",
                             "owner": p.get("name") or str(p.get("uid") or "?")[:8]})
        rows.sort(key=lambda r: r["score"], reverse=True)
        world["board"] = rows[:BOARD_TOP]
        world["board_cd"] = float(now)
    rows = world.get("board") or []
    if not rows:
        return "【神兵榜】此刻诸天尚无留名神兵。\n先 #开炉 铸器，再 #赋名 刻谱。"
    lines = [f"【神兵榜 · Top{len(rows)}】", "No. 兵器名｜类别｜缔造者｜持兵者｜灵韵值"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i:>2}. {r['name']}｜{r['type']}｜{r['author']}｜{r['owner']}｜{r['score']:,}")
    lines.append("（纯展示、无奖励；榜单 30 分钟自动重建）")
    return "\n".join(lines)


def clear_state(st: dict[str, Any]) -> None:
    """管理员 `#全体清空锻炉`：只复位炉内材料/计时，保留炉阶、功法与神兵。"""
    st["materials"], st["TIME"], st["status"] = [], 0.0, 0


# ── 文案 ────────────────────────────────────────────────────────────────
def help_text() -> str:
    return "\n".join([
        "【锻炉 · 全部指令】",
        "建档：#炼器师能力评测",
        "炉：#炼器炉 / #安装锻炉 炉名 / #炉火 / #点燃炉火 火种名",
        "功法：#炼器功法 / #修炼功法 功法名 / #参悟时光令配方 / #合成时光令 数量",
        "炼制：#熔炼 材料名*数量 → #开始炼制 → #开炉",
        "      #一键开炉（时光令×1，跳过时间） / #一键完美开炉（时光令+造化本源，系数 +0.1）",
        "查询：#我的锻炉 / #清空锻炉 / #全体清空锻炉（管理员）",
        "神兵：#赋名 原名*新名 / #神兵榜 / #神兵重铸 原名 新名",
        "说明：#锻炉帮助（本页） / #锻炉规则 / #锻炉材料",
        "⚠️ #大道权柄（C3）开铸需：混沌炉或造化仙炉 + 道火 + 无上炼器道熟练度 100。",
    ])


def rules_text() -> str:
    return "\n".join([
        "【锻炉规则】",
        "1. 顺序：评测建档 → 装炉/点火 → #熔炼 投料 → #开始炼制 温养 → #开炉 出炉。",
        "   #熔炼 是投料不是加热；#开炉 就是出炉，没有独立出炉指令。",
        "2. 温度/成功率/评级表/升阶炉均不存在（取证纠偏）。xishu 是加法系数，不是概率：",
        "   1 + 炉阶 + 功法 + 熟练度/100×0.1 + 五行词缀 + 完美窗口修正。",
        "3. 温养基准 180 分钟，普通开炉下限 30 分钟；炉火与功法按 timeCut 缩短（下限 5%）。",
        f"   完美窗口 = (80×(攻+防+血之和)+10) 分钟 × timeSpeed；偏离 <2+wb 分 +0.1，",
        "   >8+wb 分 -0.1，>12+wb 分 -0.2（wb = 功法 windowBonus）。",
        "4. 成品三维 = 材料九维 × xishu，封顶 499；暴击不乘 xishu。稀有度取自成品模板，",
        "   与材料稀有度、炉阶、炉火、熟练度全无关。",
        "5. 赋名：8 字以内、全服唯一、一件一次、无消耗；上榜后按 攻×1.2+防×1.5+血×1.5 评分。",
        "   神兵榜 Top20、30 分钟重建、无奖励。改名用 #神兵重铸（耗重铸卡）。",
        "6. 每次开炉熟练度 +2（满 100），换功法重置 0；#大道权柄 开铸要求熟练度 100。",
        "7. shortcut：原版 duanlu.json 全服共用 → 本移植玩家私有；动态装备 → 私有神兵卡",
        "   注入装备聚合，三维按本移植比例语义 clamp 到 0.99；跳过天骄夺炉战、",
        "   仙宠加成、岁云月华值分支、redis 互斥与全服广播。未建档旧档沿用 C3 职业等级门槛。",
    ])


def materials_text(item_lookup: Callable[[str], Mapping[str, Any] | None],
                   names: Sequence[str]) -> str:
    lines = ["【可投炉材料】（仅 type=锻造 的九维材料）", "名称｜攻 / 防 / 血 / 暴｜五行(金木土水火)"]
    for n in names:
        r = item_lookup(n)
        if not isinstance(r, Mapping) or str(r.get("type")) != "锻造":
            continue
        v = [float(r.get(k) or 0) for k in ("攻", "防", "血", "暴")]
        e = [int(r.get(k) or 0) for k in ("金", "木", "土", "水", "火")]
        lines.append(f"· {n}｜{' / '.join(f'{x:.3f}' for x in v)}｜{''.join(str(x) for x in e)}")
    return "\n".join(lines)
