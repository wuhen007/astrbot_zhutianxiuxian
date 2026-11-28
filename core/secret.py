"""秘境探索：地点分级 + 程序化遭遇（纯函数，无 IO）。

借鉴原版 SecretPlace 的骨架（地点/门槛/逃离）与 huaxianhu 的标签式生成：
怪物属性 = 玩家境界基础值 × 地点系数 × 深度系数 × 词缀标签；掉落按稀有度过滤物品池。
收益累积在探索会话里，撤离（或被打出局）时由调用方一次性发放。
"""

from __future__ import annotations

import hashlib
import json
import random
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .battle import spar_full, Unit
from .combat import run_1v1

# 秘境地点：名称 → (境界门槛 realm_index, 地点系数, 描述)
PLACES: dict[str, tuple[int, float, str]] = {
    "青冥山": (0, 0.6, "入门试炼地，妖兽横行的青翠山脉。"),
    "落霞谷": (2, 1.0, "落霞与孤鹜齐飞，谷中机缘与凶险并存。"),
    "幽冥渊": (5, 1.8, "终年不见天日的深渊，遍地灵物，遍地枯骨。"),
    "太古战场": (9, 3.0, "上古大能陨落之地，一步一机缘，一步一杀机。"),
}

MONSTER_PREFIX = ("受伤的", "凶暴的", "远古的", "嗜血的", "变异的")
MONSTER_KIND = ("妖狼", "妖狐", "石魔", "血蝠", "藤妖", "骷髅兵")

# 遭遇权重：怪物 / 精英 / 宝箱 / 灵物 / 无事
ENCOUNTER_WEIGHTS = (45, 8, 20, 15, 12)

# 程序化怪物词缀系数
ELITE_MULT = 2.2
PREFIX_MULT = {"受伤的": 0.7, "凶暴的": 1.15, "远古的": 1.4, "嗜血的": 1.25, "变异的": 1.3}

# 出金档位（W7-2 时代法则 one/two/three 三连判定；对齐原版 SecretPlaceTask.js:270-300）
# 档位 → (灵石系数, 可掉稀有度上浮)
LOOT_GRADES: dict[str, tuple[float, int]] = {
    "none": (0.5, 0),
    "low": (1.0, 0),
    "mid": (1.15, 1),
    "high": (1.35, 2),
}
DEFAULT_LOOT_RATES = (0.99, 0.5, 0.25)

# model/XiuxianData.js getMonsterByLocation 原版路由。只引用 Python 迁入库已有的
# 玩家数据 JSON，不重录原版的生物描述或内容资产。
ORIGINAL_MONSTER_TABLES: dict[str, str] = {
    "low": "item/怪物/怪物列表筑基",
    "middle": "item/怪物/怪物列表金丹",
    "high": "item/怪物/怪物列表化神",
    "combined": "item/怪物/怪物列表合体",
    "mahayana": "item/怪物/怪物列表大乘",
    "earth_immortal": "item/怪物/怪物列表地仙",
    "small_world": "item/怪物/怪物列表小千世界",
    "great_world": "item/怪物/怪物列表大千世界",
    "heavens": "item/怪物/诸天怪物列表",
    "true_demon": "item/怪物/真魔怪物列表",
    "burial": "item/怪物/生死道天怪物列表",
    "forbidden": "item/怪物/荒古禁地怪物列表",
    "outsider_time": "item/怪物/光阴之外怪物列表",
    "mine": "item/怪物/太初古矿怪物列表",
    "purple_mountain": "item/怪物/北斗星紫山怪物列表",
    "divine_region": "item/怪物/神域怪物列表",
    "wangjia": "item/怪物/王家古地怪物列表",
    "jiehai": "item/怪物/界海怪物列表",
    "jieyin": "item/怪物/接引古殿怪物列表",
    "default": "item/怪物列表",
}
ORIGINAL_MONSTER_PLACES: dict[str, str] = {
    **dict.fromkeys(("三清山", "张家界", "啵唧的小金库", "太玄门", "瑶池旧址",
                     "小涅槃界天墟"), "low"),
    **dict.fromkeys(("华山之巅", "武当山", "天下会", "职场", "昆仑墟", "须弥"), "middle"),
    **dict.fromkeys(("试炼", "华山", "衡山", "嵩山", "桃花岛", "轮回池",
                     "神龙山", "火域", "大夏祖庙"), "high"),
    **dict.fromkeys(("神兽试炼", "灭仙洞", "禁忌海", "雷风岛", "仙遗之地", "无欲天仙"), "combined"),
    **dict.fromkeys(("剑冢", "影界", "太极之阴", "太极之阳", "剑帝传承", "荧惑古星",
                     "灵墟洞天"), "mahayana"),
    **dict.fromkeys(("蓬莱岛", "昆仑山", "方诸山", "杀神崖", "斩魔谷", "仙界矿场",
                     "诸神黄昏·旧神界", "瑞泽云海"), "earth_immortal"),
    **dict.fromkeys(("永恒海", "永恒海尽头", "诸天"), "heavens"),
    **dict.fromkeys(("紫薇星域", "真魔殿", "北斗南域"), "true_demon"),
    "葬天星墟": "burial",
    **dict.fromkeys(("荒古禁地", "姬家祖地", "姜家祖地", "青铜仙殿", "万龙巢", "圣崖"), "forbidden"),
    "始源·混沌初开之地": "forbidden",
    "太初古矿": "mine",
    "北斗星紫山": "purple_mountain",
    "神域星宫": "divine_region",
    "王家古地·平乱剑界": "wangjia",
    "接引古殿": "jieyin",
}


def original_monster_table(place: str, xianfu_tier: int = -1, place_id: int | None = None) -> str:
    """返回原版 getMonsterByLocation 对应的已迁入怪物 JSON 路径。"""
    name = str(place or "").strip()
    if name in ("低级", "中级", "高级") and int(xianfu_tier) == 1:
        return ORIGINAL_MONSTER_TABLES[{"低级": "small_world", "中级": "great_world",
                                        "高级": "earth_immortal"}[name]]
    if name in ("低级", "中级", "高级") and int(xianfu_tier) == 0:
        return ORIGINAL_MONSTER_TABLES[{"低级": "low", "中级": "middle", "高级": "high"}[name]]
    table_name = ORIGINAL_MONSTER_PLACES.get(name)
    if table_name:
        return ORIGINAL_MONSTER_TABLES[table_name]
    if int(place_id or 0) == 5200:
        return ORIGINAL_MONSTER_TABLES["low"]
    return ORIGINAL_MONSTER_TABLES["default"]


def original_monster(place: str, rng: random.Random, content: Any,
                     xianfu_tier: int = -1, place_id: int | None = None) -> Mapping | None:
    """从原版地点所属怪物表抽取一名遭遇者，返回本地原表行。"""
    pool = content(original_monster_table(place, xianfu_tier, place_id)) or []
    eligible = [row for row in pool if isinstance(row, Mapping)]
    return rng.choice(eligible) if eligible else None


def original_drop(row: Mapping, rng: random.Random,
                  rates: tuple[float, float, float] = DEFAULT_LOOT_RATES) -> dict[str, Any] | None:
    """按 SecretPlaceTask 三次判定抽原版三个档位，保留空抽救命丹回落。"""
    def passed(probability: float) -> bool:
        return rng.random() < min(1.0, max(0.0, float(probability)))

    one, two, three = rates
    if not passed(one):
        t1, t2 = 0.5 + rng.random() * 0.5, 0.5 + rng.random() * 0.5
        return {"name": "起死回生丹", "class": "丹药", "quantity": 1,
                "tier": "none", "t1": t1, "t2": t2}
    tier = "one"
    if passed(two):
        tier = "two"
        if passed(three):
            tier = "three"
    items = [item for item in (row.get(tier) or []) if isinstance(item, Mapping)]
    if not items:
        return {"name": "起死回生丹", "class": "丹药", "quantity": 1,
                "tier": "none", "t1": 0.5 + rng.random() * 0.5,
                "t2": 0.5 + rng.random() * 0.5}
    item = rng.choice(items)
    name = str(item.get("name") or "")
    if not name:
        return None
    t1, t2 = ((2 + rng.random(), 2 + rng.random()) if tier == "three" else
              (1 + rng.random(), 1 + rng.random()) if tier == "two" else
              (0.5 + rng.random() * 0.5, 0.5 + rng.random() * 0.5))
    quantity = 1
    if tier == "two" and name in ("太极之阳", "太极之阴"):
        quantity = 5
    elif tier == "two" and str(row.get("name") or "") == "须弥":
        quantity = 80
    elif tier == "one" and str(row.get("name") or "") == "须弥":
        quantity = 5
    elif tier == "one" and name in ("太极之阳", "太极之阴"):
        quantity = 5
    return {"name": name, "class": str(item.get("class") or "道具"),
            "quantity": quantity, "tier": tier, "t1": t1, "t2": t2}


def original_win_rewards(realm_id: int, physique_id: int, rng: random.Random | None = None,
                         loot: Mapping | None = None) -> dict[str, int]:
    """按原版秘境胜利结算，以 1-based 境界和本次品质档系数计算奖励。"""
    loot = loot if isinstance(loot, Mapping) else {}
    t1 = float(loot.get("t1", 0.5 + (rng.random() if rng else 0.0) * 0.5) or 0)
    t2 = float(loot.get("t2", 0.5 + (rng.random() if rng else 0.0) * 0.5) or 0)
    return {
        "exp": int(2000 + (100 * int(realm_id) ** 2 * t1 * 0.1) / 5),
        "xueqi": int(2000 + 100 * int(physique_id) ** 2 * t2 * 0.1),
    }


def original_loss_rewards() -> dict[str, int]:
    """普通战败且没有护道者/复活特权时，原版只给修为并将当前气血设为零。"""
    return {"exp": 800, "xueqi": 0, "hp": 0}


def original_session(place: str, kind: str, row: Mapping, encounter: Mapping | None,
                     starts_at: float, ends_at: float, seed: str) -> dict[str, Any]:
    """构造可 JSON 序列化的定时遭遇快照，供调用方写入玩家 ext。"""
    enemy = {}
    if encounter:
        for key in ("名号", "攻击", "防御", "当前血量", "暴击率", "速度", "法球倍率"):
            if key in encounter:
                enemy[key] = encounter[key]
    return {"kind": str(kind), "place": str(place), "row": dict(row), "enemy": enemy,
            "starts_at": float(starts_at), "ends_at": float(ends_at), "seed": str(seed)}


def exploration_steps(rng: random.Random, speed_bonus: float = 0.0) -> int:
    """秘境加速按百分比概率令一次寻宝额外推进一层。"""
    chance = min(1.0, max(0.0, float(speed_bonus or 0)))
    return 2 if chance and rng.random() < chance else 1


def loot_grade(rates: tuple[float, float, float], rng: random.Random,
               luck_bonus: float = 0.0) -> str:
    """三连判定：低级必过（默认 0.99），中级 0.5，高级 0.25 → 约 12% 出高级。"""
    one, two, three = (min(1.0, max(0.0, float(x) + luck_bonus)) for x in rates)
    if rng.random() > one:
        return "none"
    if rng.random() > two:
        return "low"
    if rng.random() > three:
        return "mid"
    return "high"


def original_settlement(won: bool, action: Mapping, realm_id: int, physique_id: int,
                        rng: random.Random | None = None) -> dict[str, Any]:
    """形成定时历练的胜负增量；调用方在玩家/背包事务中应用。"""
    if not won:
        return {**original_loss_rewards(), "items": {}, "item_name": "",
                "item_count": 0, "action": str(action.get("kind") or "")}
    loot = action.get("loot")
    loot = loot if isinstance(loot, Mapping) else None
    rewards = original_win_rewards(realm_id, physique_id, rng, loot)
    items: dict[str, int] = {}
    if loot and loot.get("name"):
        items[str(loot["name"])] = max(0, int(loot.get("quantity", 1) or 1))
    return {**rewards, "hp": -1, "items": items,
            "item_name": str(loot.get("name") or "") if loot else "",
            "item_count": max(0, int(loot.get("quantity", 0) or 0)) if loot else 0,
            "tier": str(loot.get("tier") or "") if loot else "",
            "action": str(action.get("kind") or "")}


@dataclass
class Session:
    """一次秘境探索会话（序列化到玩家 ext["explore"]）。

    factor > 0 时覆盖地点系数（宗门秘境等动态地点用）。
    """

    place: str
    floor: int = 0
    stones: int = 0
    items: dict[str, int] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    factor: float = 0.0
    sect_name: str = ""    # 非空 = 宗门秘境（每 5 层守关 Boss）
    boss_kills: int = 0    # 本会话击杀守关 Boss 数（结算时宗门基金加成）
    dungeon: str = ""      # 非空 = 表驱动副本（W7-5b，掉落池/系数来自副本地表）
    settlement_id: str = field(default_factory=lambda: secrets.token_hex(16))



def session_settlement_id(uid: str, raw: Mapping[str, Any], created_at: float = 0) -> str:
    current = str(raw.get("settlement_id") or "").strip()
    if current:
        return current
    stable = {key: raw.get(key) for key in ("place", "floor", "stones", "items", "sect_name", "dungeon")}
    seed = f"{uid}|{created_at}|{json.dumps(stable, ensure_ascii=False, sort_keys=True)}"
    return "legacy:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()

def combat_name(daohao: Any, uid: Any, nickname: Any = "") -> str:
    """显示道号优先，其次当前平台昵称；永不把 UID 当成角色名。"""
    uid = str(uid or "").strip()
    uid_label = f"{uid[:8]}…" if uid else ""
    for candidate in (daohao, nickname):
        name = str(candidate or "").strip()
        truncated_uid = (name.endswith("…") and len(name) > 8
                         and uid.startswith(name[:-1]))
        if name and name not in (uid, uid_label) and not truncated_uid:
            return name
    return "道友"


def remember_defeat(ext: dict[str, Any], session: Session) -> None:
    ext["secret_defeat"] = {"place": str(session.place), "floor": int(session.floor)}


def defeat_notice(ext: Mapping[str, Any]) -> str | None:
    record = ext.get("secret_defeat")
    if not isinstance(record, Mapping) or not record.get("place"):
        return None
    try:
        floor = max(0, int(record.get("floor") or 0))
    except (TypeError, ValueError):
        floor = 0
    place = str(record["place"])
    return (f"上次在「{place}」第 {floor} 层寻宝战败，已被迫脱出秘境，收获已经结算。"
            f"重新探索请发「#降临秘境 {place}」。")


def clear_defeat_notice(ext: dict[str, Any]) -> None:
    ext.pop("secret_defeat", None)


def place_factor(name: str) -> float:
    return PLACES.get(name, PLACES["青冥山"])[1]


def depth_mult(floor: int) -> float:
    return 1.0 + 0.15 * max(0, floor)


def make_monster(
    place: str,
    floor: int,
    base: tuple[int, int, int],
    rng: random.Random,
    elite: bool = False,
    factor_override: float = 0.0,
    speed: int = 100,
) -> Unit:
    """程序化怪物：基础三维 × 地点系数 × 深度系数 × 词缀。"""
    patk, pdef, php = base
    pf = factor_override if factor_override > 0 else place_factor(place)
    factor = pf * depth_mult(floor) * (ELITE_MULT if elite else 1.0)
    prefix = rng.choice(MONSTER_PREFIX)
    kind = rng.choice(MONSTER_KIND)
    m = PREFIX_MULT[prefix]
    name = f"{prefix}{kind}"
    return Unit(
        name,
        max(1, int(patk * factor * m * (0.85 + 0.3 * rng.random()))),
        max(1, int(pdef * factor * m * (0.85 + 0.3 * rng.random()))),
        max(1, int(php * factor * m * (0.9 + 0.2 * rng.random()))),
        speed=max(1, int(speed)),
    )


def roll_encounter(rng: random.Random) -> str:
    """掷遭遇类型。"""
    total = sum(ENCOUNTER_WEIGHTS)
    x = rng.random() * total
    acc = 0.0
    for kind, w in zip(("monster", "elite", "chest", "herb", "calm"), ENCOUNTER_WEIGHTS):
        acc += w
        if x < acc:
            return kind
    return "monster"


def roll_drop(
    item_pool: list[Mapping], rng: random.Random, floor: int, elite: bool,
    rar_bonus: int = 0,
) -> Mapping | None:
    """按稀有度过滤掉落：深度、精英与出金档位共同提升可掉稀有度上限。"""
    if not item_pool:
        return None
    cap = 2 + floor // 3 + (2 if elite else 0) + max(0, int(rar_bonus))
    candidates = [e for e in item_pool if int(e.get("稀有度", 1) or 1) <= cap]
    pool = candidates or [e for e in item_pool if int(e.get("稀有度", 1) or 1) <= 2]
    return rng.choice(pool) if pool else None


def _battle_fighters(me: Unit, monster: Unit, buff: Any, me_fighter: Any = None):
    """阵法回调 → Fighter 对（W1-3：阵法乘区/定身走引擎效果槽，不再战前改值）。

    me_fighter：调用方预构建的我方 Fighter（W4-1——技能池/灵根法球/复活技进 PvE）；
    缺省仍从 Unit 转换（行为与 W1-3 完全一致）。
    返回 (me_f, foe_f, skip_first)；buff 只在真正进入战斗时消耗一次。
    """
    from .combat import Fighter

    me_f = me_fighter or Fighter.from_unit(me)
    if me_fighter is not None:
        me_f.hp = max(0, int(me.hp))   # 探索层以 me.hp 为准，保持同步
    foe_f = Fighter.from_unit(monster)
    skip: tuple[int, ...] = ()
    if buff:
        b = buff() or {}
        if b.get("atk_mult"):
            me_f.effects["dmg_dealt_mult"] = float(b["atk_mult"])
        if b.get("bao_add"):
            me_f.bao = min(1.0, me_f.bao + float(b["bao_add"]))
        enemy = b.get("enemy") or {}
        if enemy:
            foe_f.effects["dmg_dealt_mult"] = float(enemy.get("atk", 1) or 1)
            foe_f.effects["dmg_taken_mult"] = float(enemy.get("def", 1) or 1)
        if b.get("stun"):
            skip = (1,)
    return me_f, foe_f, skip


def explore(
    session: Session,
    base: tuple[int, int, int],
    me: Unit,
    item_pool: list[Mapping],
    rng: random.Random,
    stone_scale: float = 1.0,
    sect_mode: bool = False,
    buff: Any = None,
    protect: Any = None,
    me_fighter: Any = None,
    treasure_bonus: float = 0.0,
    luck_bonus: float = 0.0,
    loot_rates: tuple[float, float, float] | None = None,
    loot_bonus: int = 0,
    item_multiplier: Callable[[str], int] | None = None,
) -> tuple[Session, Unit, str, bool]:
    """寻宝一次。返回 (更新后的会话, 战斗后的我, 文本, 是否被打出局)。

    宗门秘境（sect_mode）每 5 层强制遭遇守关 Boss（强度 ×3、奖励 ×5）。
    我方血量由调用方以 Unit.hp 传入（当前气血），战斗后同步回 ext。
    buff：战斗开始时的阵法回调 () -> {atk_mult, bao_add, enemy:{atk,def}, stun}；
    只在真正进入战斗时调用，避免空探索白烧次数。
    protect：护道回调 (place, floor, enemy) -> (护道人, 文案) | None；
    战败瞬间调用，触发则气血全复、收益不减、留在秘境。
    loot_rates：时代法则的秘境出金率 (one, two, three)；None = 不套用（旧行为）。
    loot_bonus：道法卡额外档位（W7-4），直接抬高可掉稀有度上限。
    """
    session.floor += 1
    boss_floor = sect_mode and (session.floor % 5 == 0)
    kind = roll_encounter(rng)
    depth = depth_mult(session.floor)
    pf = session.factor if session.factor > 0 else place_factor(session.place)

    def add_item(name: str) -> int:
        multiplier = max(1, int(item_multiplier(name) if item_multiplier else 1))
        session.items[name] = session.items.get(name, 0) + multiplier
        return multiplier

    def grade() -> tuple[str, float, int]:
        """掷出金档（无时代配置时按 low 折算，保持历史行为）。"""
        if not loot_rates:
            return "low", 1.0, int(loot_bonus or 0)
        g = loot_grade(tuple(loot_rates), rng, luck_bonus)
        mult, rar = LOOT_GRADES[g]
        return g, mult, rar + int(loot_bonus or 0)

    if boss_floor:
        monster = make_monster(
            session.place, session.floor - 1, base, rng,
            elite=False, factor_override=pf * 3.0,
        )
        me_f, foe_f, skip = _battle_fighters(me, monster, buff, me_fighter)
        res = run_1v1(me_f, foe_f, rng, skip_first=skip)
        winner, log, hp_left = res.winner, res.log, res.a_hp
        me.hp = max(0, hp_left)
        skill_lines = [x for x in log if x.startswith("【")]
        tail = "\n".join(skill_lines + [log[-1]]) if skill_lines and log else (log[-1] if log else "")
        if winner == 0:
            g, gmult, rar = grade()
            stones = int((1500 + 800 * session.floor) * depth * pf * gmult)
            session.stones += max(1, int(stones * (1.0 + float(treasure_bonus or 0))))
            session.boss_kills += 1
            drops = []
            for _ in range(0 if g == "none" else 2):
                drop = roll_drop(item_pool, rng, session.floor + 4, elite=True, rar_bonus=rar)
                if drop:
                    multiplier = add_item(str(drop["name"]))
                    drops.append(f"{drop['name']}×{multiplier}" if multiplier > 1 else drop["name"])
            got = f"，掉落「{'」「'.join(drops)}」" if drops else ""
            session.log.append(f"第{session.floor}层：击败守关Boss·{monster.name}{tail}，得 {stones} 灵石{got}")
            return session, me, tail, False
        saved = protect(session.place, session.floor, monster.name) if protect else None
        if saved:
            name, msg = saved
            me.hp = base[2]
            session.log.append(f"第{session.floor}层：不敌守关Boss·{monster.name}，护道人「{name}」出手相护")
            return session, me, msg, False
        lost = session.stones // 3
        session.stones -= lost
        session.log.append(f"第{session.floor}层：守关Boss·{monster.name}太强{tail}，败退，散失 {lost} 灵石")
        return session, me, tail, True

    if kind in ("monster", "elite"):
        monster = make_monster(
            session.place, session.floor - 1, base, rng,
            elite=(kind == "elite"), factor_override=pf,
        )
        me_f, foe_f, skip = _battle_fighters(me, monster, buff, me_fighter)
        res = run_1v1(me_f, foe_f, rng, skip_first=skip)
        winner, log, hp_left = res.winner, res.log, res.a_hp
        me.hp = max(0, hp_left)
        skill_lines = [x for x in log if x.startswith("【")]
        tail = "\n".join(skill_lines + [log[-1]]) if skill_lines and log else (log[-1] if log else "")
        if winner == 0:
            g, gmult, rar = grade()
            stones = int((300 + 200 * session.floor) * depth * pf * stone_scale
                         * (3 if kind == "elite" else 1) * gmult)
            session.stones += max(1, int(stones * (1.0 + float(treasure_bonus or 0))))
            drop = None if g == "none" else roll_drop(
                item_pool, rng, session.floor, elite=(kind == "elite"), rar_bonus=rar)
            got = ""
            if drop:
                multiplier = add_item(str(drop["name"]))
                got = f"，掉落「{drop['name']}" + (f"×{multiplier}" if multiplier > 1 else "") + "」"
            session.log.append(f"第{session.floor}层：击败{monster.name}{tail}，得 {stones} 灵石{got}")
            return session, me, tail, False
        saved = protect(session.place, session.floor, monster.name) if protect else None
        if saved:
            name, msg = saved
            me.hp = base[2]
            session.log.append(f"第{session.floor}层：不敌{monster.name}，护道人「{name}」出手相护")
            return session, me, msg, False
        # 战败：损失全部带入收益的一半灵石（物品保留），被传送出秘境
        lost = session.stones // 2
        session.stones -= lost
        session.log.append(f"第{session.floor}层：不敌{monster.name}{tail}，血战脱身，散失 {lost} 灵石")
        return session, me, tail, True

    if kind == "chest":
        g, gmult, _rar = grade()
        stones = int((500 + 300 * session.floor) * depth * pf * stone_scale * gmult)
        session.stones += max(1, int(stones * (1.0 + float(treasure_bonus or 0))))
        session.log.append(f"第{session.floor}层：发现古旧宝箱，开出 {stones} 灵石")
        return session, me, "古旧宝箱中灵光一闪。", False

    if kind == "herb":
        g, _gmult, rar = grade()
        drop = None if g == "none" else roll_drop(item_pool, rng, session.floor,
                                                  elite=False, rar_bonus=rar)
        if drop:
            multiplier = add_item(str(drop["name"]))
            session.log.append(f"第{session.floor}层：采得灵物「{drop['name']}" +
                               (f"×{multiplier}" if multiplier > 1 else "") + "」")
            return session, me, "灵气扑面，有所收获。", False

    session.log.append(f"第{session.floor}层：静观云海，心神澄明（无事发生）")
    return session, me, "此地灵气平和，并无异动。", False
