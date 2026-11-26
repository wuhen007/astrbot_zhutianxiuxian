"""世界 Boss：轮次递进的共享实体（纯函数部分，无 IO）。

对齐原版 apps/Boss/BOSS.js 的核心规则：
- 幻影属性 = 讨伐者属性 × (0.8 + 0.6×随机)，人人打的是"自己的妖王幻影"
- 胜：对 Boss 本体伤害 = 上限×5% + Harm(攻×0.85, 幻影防)×6
- 负：上限×3% + Harm(攻×0.85, 幻影防)×4
- 参战门槛：当前血量 > 上限×10%
- 击杀者额外奖励（原版固定 100w → 这里改为奖池加成比例，可配）
轮次递进：血量/奖池 = 基数 × 1.5^(轮次-1)。
"""

from __future__ import annotations

import random
import time
from collections.abc import Mapping

from .battle import Unit, harm

BASE_HEALTH = 1_000_000
BASE_REWARD = 500_000
GROWTH = 1.5
SHADOW_RANGE = (0.8, 1.4)   # 幻影属性浮动区间（原版 0.8 + 0.6×random）
WIN_RATE, LOSE_RATE = 0.05, 0.03
WIN_MULT, LOSE_MULT = 6, 4
KILLER_BONUS = 0.10         # 击杀者额外奖励（占奖池比例）


def boss_specs(round_no: int) -> tuple[int, int]:
    """第 round_no 轮的 (血量, 奖池)。"""
    factor = GROWTH ** (round_no - 1)
    return int(BASE_HEALTH * factor), int(BASE_REWARD * factor)


def make_shadow(atk: int, defense: int, hp: int, rng: random.Random,
                speed: int = 100, crit_damage: float | None = None,
                bao: float = 0.0) -> Unit:
    """按讨伐者属性生成妖王幻影；行动速度与暴击沿用 BOSS.js 玩家快照。"""
    lo, hi = SHADOW_RANGE

    def roll(v: int) -> int:
        return max(1, int(v * (lo + (hi - lo) * rng.random())))

    return Unit("妖王幻影", roll(atk), roll(defense), roll(hp), bao=float(bao or 0),
                speed=max(1, int(speed)), crit_damage=crit_damage)


def boss_damage(won: bool, atk: int, shadow_def: int, health_max: int, rng: random.Random) -> int:
    """讨伐对 Boss 本体造成的伤害（无论幻影战胜负都有产出，对齐原版）。"""
    base = health_max * (WIN_RATE if won else LOSE_RATE)
    mult = WIN_MULT if won else LOSE_MULT
    raw = harm(atk * 0.85, shadow_def, rng)[0]
    return int(base + raw * mult)


def split_rewards(
    reward: int,
    ledger: Mapping[str, tuple[str, int]],
    killer_uid: str | None,
) -> list[tuple[str, str, int]]:
    """按贡献比例分奖池；击杀者额外 +KILLER_BONUS。返回 (uid, 名字, 灵石)。"""
    total = sum(d for _, d in ledger.values())
    if total <= 0 or not ledger:
        return []
    out: list[tuple[str, str, int]] = []
    for uid, (name, dmg) in ledger.items():
        share = int(reward * dmg / total)
        if killer_uid and uid == killer_uid:
            share += int(reward * KILLER_BONUS)
        if share > 0:
            out.append((uid, name, share))
    out.sort(key=lambda x: -x[2])
    return out


# ---- 原版共享 Boss 规则（apps/Boss/BOSS.js） ----

WORLD_LEVEL_GATE = 42
WORLD_HP_GATE = 0.10
WORLD_FIGHT_COOLDOWN = 300
WORLD_HEAL_CHANCE = 0.05
WORLD_HEAL_FRACTION = 0.20
WORLD_RESCUE_CHANCE = 0.05
WORLD_RESCUE_FRACTION = 0.15
WORLD_KILLER_BONUS = 1_000_000
WORLD_CONTRIBUTION_FLOOR = 200_000
DARK_HP_GATE = 0.10
DARK_PERSONAL_COOLDOWN = 300
DARK_MIN_SECRET_LEVEL = 12
DARK_STATUS_REWARD = 30_000_000
DARK_REWARD_SMALL_POPULATION = 15_000_000
DARK_REWARD_LARGE_POPULATION = 30_000_000
DARK_WIN_PROGRESS = 20
DARK_LOSS_PROGRESS = 1
DARK_EMPOWERED_WIN_PROGRESS = 40
DARK_EMPOWERED_LOSS_PROGRESS = 2
DARK_SUPREME_ORBS = (3.2, 3.4, 3.1, 3.3, 3.5, 3.4)
DARK_SUPREME_FACTORS = (
    (3.6, 4.2, 4.8),
    (4.5, 5.2, 5.8),
    (3.8, 4.1, 4.6),
    (3.7, 4.7, 5.1),
    (4.2, 4.3, 5.2),
    (4.0, 4.0, 4.9),
)
DARK_CULTIVATION_FALLBACK = {
    "qi": (10_000_000_000, 10_000_000_000, 20_000_000_000),
    "body": (1_600_000_000, 16_500_000_000, 33_500_000_000),
    "secret": (830_000_000, 830_000_000, 830_000_000),
    "ancient": (0, 0, 0),
}


def trimmed_population_attack(attacks, trim_above: int = 15) -> tuple[int, int]:
    """复刻 GetAverageDamage：15 人以上剔除最高两人、最低四人。"""
    values = sorted((max(0, int(value or 0)) for value in attacks), reverse=True)
    count = len(values)
    if count > trim_above:
        values = values[2:count - 4]
    return (int(sum(values) / len(values)) if values else 0, count)


def original_world_specs(average_attack: int, eligible_count: int) -> tuple[int, int]:
    """BOSS.js 开妖王：上限=(平均攻×1%)×150×人数×200，奖池 600/1200 万。"""
    count = max(0, int(eligible_count))
    if not count:
        return 0, 0
    base = max(0, int(average_attack)) * 0.01
    return int(base * 150 * count * 200), (12_000_000 if count >= 5 else 6_000_000)


def original_world_entry_allowed(realm_id: int, current_hp: int, max_hp: int,
                                  remaining_boss_health: int, maximum_boss_health: int,
                                  active: bool = True, busy: bool = False) -> tuple[bool, str]:
    """BOSS.js 参战门槛：仙界、体力高于10%、未锁且本体仍高于10%。"""
    if not active:
        return False, "妖王未开启。"
    if int(realm_id) < WORLD_LEVEL_GATE:
        return False, "尚未达到仙界，无法挑战妖王。"
    if busy:
        return False, "有人正在与妖王激战，请稍后再试。"
    if int(current_hp) <= int(max_hp) * WORLD_HP_GATE:
        return False, "气血低于 10%，请先疗伤再参战。"
    if int(remaining_boss_health) <= int(maximum_boss_health) * WORLD_HP_GATE:
        return False, "妖王已经气息奄奄，本轮不能再上前挑战。"
    return True, ""


def original_world_kill_bonus() -> int:
    """BOSS.js 讨伐者每次首杀的固定灵石奖，不计入贡献奖池。"""
    return WORLD_KILLER_BONUS


def split_original_world_rewards(reward: int, ledger: Mapping[str, tuple[str, int]],
                                 limit: int = 20) -> list[tuple[str, str, int]]:
    """BOSS.js 前 20 名按贡献分奖且最低 20 万，其余参战者各 20 万。"""
    ranked = sorted(((str(uid), str(name), max(0, int(dmg)))
                     for uid, (name, dmg) in ledger.items()), key=lambda item: -item[2])
    top = ranked[:max(0, int(limit))]
    total = sum(dmg for _, _, dmg in top)
    out = []
    for index, (uid, name, damage) in enumerate(ranked):
        share = max(WORLD_CONTRIBUTION_FLOOR,
                    int(max(0, int(reward)) * damage / total) if index < max(0, int(limit)) and total else 0)
        out.append((uid, name, share))
    return out


def original_world_aftermath(won: bool, health: int, health_max: int,
                             rng: random.Random) -> dict[str, int | str]:
    """结算 BOSS.js 的 5%妖王回春 / 5%韩立助战分支。"""
    roll = rng.random()
    if roll < WORLD_HEAL_CHANCE and won:
        return {"kind": "heal", "damage": 0, "healing": 0,
                "boss_healing": int(max(0, int(health_max)) * WORLD_HEAL_FRACTION)}
    if roll > 1 - WORLD_RESCUE_CHANCE and not won:
        damage = int(max(0, int(health)) * WORLD_RESCUE_FRACTION)
        return {"kind": "rescue", "damage": damage, "healing": -1, "boss_healing": 0}
    return {"kind": "none", "damage": 0, "healing": 0, "boss_healing": 0}


def original_boss_damage_effect(won: bool, atk: int, shadow_defense: int,
                                health_max: int, rng: random.Random) -> int:
    """BOSS.js 单场伤害，按战果使用 5%/6 倍或 3%/4 倍基数。"""
    return boss_damage(won, atk, shadow_defense, health_max, rng)


# ---- BOSS2：原版黑暗动乱六阶段规则 ----


def _level_row(rows, level_id: int, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if not isinstance(rows, list):
        return fallback
    row = next((item for item in rows
                if isinstance(item, Mapping) and int(item.get("level_id", 0) or 0) == level_id), None)
    if not row:
        return fallback
    return tuple(max(0, int(row.get(key, 0) or 0))
                 for key in ("基础攻击", "基础防御", "基础血量"))


def original_dark_stage_specs(levels: Mapping, player_count: int,
                              average_attack: int = 0, stage: int = 0) -> dict[str, int]:
    """按 model/darkRevolt.js 逐项计算一位至尊的攻、防、血及共享血条。"""
    fallback = DARK_CULTIVATION_FALLBACK
    qi = _level_row(levels.get("Level_list"), max(
        (int(row.get("level_id", 0) or 0) for row in levels.get("Level_list", [])
         if isinstance(row, Mapping)), default=0), fallback["qi"])
    body = _level_row(levels.get("LevelMax_list"), max(
        (int(row.get("level_id", 0) or 0) for row in levels.get("LevelMax_list", [])
         if isinstance(row, Mapping)), default=0), fallback["body"])
    secret = _level_row(levels.get("Levelmijing_list"), 16, fallback["secret"])
    ancient = _level_row(levels.get("xiangujinshi_list"), 1, fallback["ancient"])
    base_totals = tuple(qi[index] + body[index] + secret[index] + ancient[index]
                        for index in range(3))
    weapon_base = tuple(secret[index] + ancient[index] for index in range(3))
    factors = DARK_SUPREME_FACTORS[max(0, min(len(DARK_SUPREME_FACTORS) - 1, int(stage)))]
    scale = 1.0 + max(0, int(stage)) * 0.04
    attribute = tuple(int((base_totals[index] * 2 + weapon_base[index] * 120
                           + 10_000_000_000_000) * factors[index] * scale)
                      for index in range(3))
    health = max(int(attribute[2] * (10 + max(1, int(player_count)) * 2)
                     + max(1, int(average_attack)) * 100), 1)
    return {"atk": attribute[0], "defense": attribute[1], "hp_max": attribute[2],
            "health": health, "health_max": health, "origin_health": health,
            "stage": max(0, min(len(DARK_SUPREME_FACTORS) - 1, int(stage)))}


def original_dark_status(levels: Mapping, player_count: int,
                         average_attack: int = 0, started_at: float = 0.0) -> dict[str, Any]:
    """BOSS2 v2 六位至尊会话快照；名称/剧情从产品数据层按 phase 展示。"""
    count = max(1, int(player_count))
    bosses = []
    for index in range(len(DARK_SUPREME_FACTORS)):
        spec = original_dark_stage_specs(levels, count, average_attack, index)
        bosses.append({**spec, "alive": True, "defeated": False, "angry": 0,
                       "weak": 0, "ascended": False})
    reward = DARK_REWARD_SMALL_POPULATION if count < 5 else DARK_REWARD_LARGE_POPULATION
    return {"version": 2, "bosses": bosses, "phase": 0,
            "reward": reward,
            "harvested_lives": count * 10_000_000,
            "started_at": float(started_at), "killed_at": -1}


def original_dark_suppression(player: Mapping, stage: int) -> dict[str, Any]:
    """帝道规则按 BOSS2 原版秘境/仙古等级，将战斗镜像三维降至 30%。"""
    result = dict(player)
    legacy = result.get("legacy_source") if isinstance(result.get("legacy_source"), Mapping) else {}
    secret = max(1, int(result.get("mijinglevel_id", legacy.get("mijinglevel_id", 1)) or 1))
    ancient = max(1, int(result.get("xiangulevel_id", legacy.get("xiangulevel_id", 1)) or 1))
    suppressed = max(secret, ancient) < 16 and not bool(result.get("corpseRescueActive"))
    if suppressed:
        for field in ("攻击", "防御", "血量上限", "当前血量", "攻击加成", "防御加成", "生命加成"):
            if field in result:
                result[field] = max(1, int(int(result[field]) * 0.3))
    return {"player": result, "suppressed": suppressed, "reduction": 0.7 if suppressed else 0.0}


def original_dark_aftermath(state: dict, damage: int, stage: int,
                            rng: random.Random | None = None,
                            roll: float | None = None) -> dict[str, int | bool]:
    """按 BOSS2 阶段规则记伤、触发升华/重创虚弱与至尊回生。"""
    bosses = state.get("bosses") if isinstance(state.get("bosses"), list) else []
    index = max(0, min(len(bosses) - 1, int(stage))) if bosses else -1
    if index < 0:
        return {"damage": 0, "remaining": 0, "defeated": True,
                "ascended": False, "weakened": False, "restored": 0}
    target = bosses[index]
    dealt = max(0, int(damage))
    target["health"] = max(0, int(target.get("health", 0) or 0) - dealt)
    defeated = target["health"] == 0
    if defeated:
        target["alive"] = False
        target["defeated"] = True
        state["phase"] = next((i for i, boss_state in enumerate(bosses)
                               if boss_state.get("alive") and not boss_state.get("defeated")), len(bosses))
    ascended = bool(dealt >= int(target.get("origin_health", target.get("health_max", 0)) * 0.1)
                    and not target.get("ascended") and not defeated)
    if ascended:
        target["angry"] = 30
        target["ascended"] = True
    weakened = bool(not defeated and int(target["health"]) <= int(target.get("health_max", 0) * 0.25))
    if weakened:
        target["weak"] = max(int(target.get("weak", 0) or 0), 3)
    restored = 0
    random_value = float(roll) if roll is not None else (rng.random() if rng else 1.0)
    if (not defeated and dealt >= int(target.get("origin_health", target.get("health_max", 0)) * 0.15)
            and int(target.get("weak", 0) or 0) > 0 and random_value < 0.2):
        restored = min(int(target["health_max"] - target["health"]),
                       int(target["health_max"] * 0.3))
        target["health"] += restored
    return {"damage": dealt, "remaining": int(target["health"]), "defeated": defeated,
            "ascended": ascended, "weakened": weakened, "restored": restored,
            "next_phase": int(state.get("phase", len(bosses)))}


def original_dark_combat_stats(boss_state: Mapping) -> dict[str, int]:
    """将 BOSS2 狂暴/虚弱回合映射成该场交战用的攻防。"""
    angry = max(0, int(boss_state.get("angry", 0) or 0))
    weak = max(0, int(boss_state.get("weak", 0) or 0))
    attack_rate = 1.8 if angry else (0.7 if weak else 1.0)
    defense_rate = 0.7 if weak else 1.0
    return {"atk": int(int(boss_state.get("atk", 1) or 1) * attack_rate),
            "defense": int(int(boss_state.get("defense", 1) or 1) * defense_rate)}


def original_dark_turn(state: dict, stage: int, damage: int, won: bool,
                        player_hp: int, player_hp_max: int, realm_id: int,
                        rng: random.Random) -> dict[str, Any]:
    """同一乱数串行驱动 BOSS2 单场升华、回复、救援及强敌回合递减。"""
    roll = rng.random()
    progress = original_dark_aftermath(state, damage, stage, rng, roll=roll)
    recovery = original_dark_death_events(state, stage, won, player_hp,
                                          player_hp_max, realm_id, rng, roll=roll)
    bosses = state.get("bosses") if isinstance(state.get("bosses"), list) else []
    active_index = max(0, min(len(bosses) - 1, int(stage))) if bosses else -1
    if active_index >= 0 and int(recovery.get("boss_damage", 0) or 0) > 0:
        active = bosses[active_index]
        progress["remaining"] = int(active.get("health", 0) or 0)
        progress["defeated"] = bool(active.get("defeated"))
        progress["next_phase"] = int(state.get("phase", len(bosses)) or 0)
    if active_index >= 0:
        target = bosses[active_index]
        target["angry"] = max(0, int(target.get("angry", 0) or 0) - 1)
        target["weak"] = max(0, int(target.get("weak", 0) or 0) - 1)
    if int(progress.get("next_phase", len(bosses)) or 0) >= len(bosses):
        state["alive"] = False
        state["killed_at"] = time.time()
    return {"roll": roll, "progress": progress, **recovery}


def original_dark_death_events(state: dict, stage: int, won: bool, player_hp: int,
                               player_hp_max: int, realm_id: int,
                               rng: random.Random | None = None,
                               roll: float | None = None) -> dict[str, int]:
    """复刻帝战战败后同一 roll 驱动的顿悟、救命与救场伤害分支。"""
    if won or max(0, int(player_hp)) > 0:
        return {"exp": 0, "xueqi": 0, "hp": max(0, int(player_hp)), "boss_damage": 0}
    roll = float(roll) if roll is not None else (rng.random() if rng else 1.0)
    exp = 1_000_000 + max(0, int(realm_id)) * 21_000 if roll < 0.45 else 0
    hp = max(0, int(player_hp))
    if roll > 0.1 and roll < 0.35:
        heal = max(0, int(5_000 + max(0, int(player_hp_max)) * 0.2))
        if hp + heal > max(0, int(player_hp_max)):
            heal = max(0, int(player_hp_max) - hp)
        hp += heal
    assist = 0
    bosses = state.get("bosses") if isinstance(state.get("bosses"), list) else []
    index = max(0, min(len(bosses) - 1, int(stage))) if bosses else -1
    if index >= 0 and roll < 0.1:
        assist = int(max(0, int(bosses[index].get("health", 0) or 0)) * 0.25)
    elif index >= 0 and roll > 0.1 and roll < 0.3:
        assist = int(max(0, int(bosses[index].get("health", 0) or 0)) * 0.15)
    if assist:
        original_dark_aftermath(state, assist, index, rng, roll=roll)
    return {"exp": exp, "xueqi": exp, "hp": hp, "boss_damage": assist}


# The pinned original's black-revolt item JSON is absent from the snapshot. Keep its
# source-defined rank counts, and use a deliberately narrow port-designed pool from
# existing ordinary inventory data until the original table is available.
DARK_RANK_ITEM_COUNTS = (5, 4, 3, 2, 1)  # top 1, 2, 3, 4-5, 6-10
DARK_KILLER_ITEM_COUNT = 2
PORT_DESIGNED_DARK_ITEM_RARITIES = frozenset((5, 6))
PORT_DESIGNED_DARK_ITEM_CLASSES = frozenset(("丹药", "道具", "材料", "草药"))


def dark_rank_item_count(rank: int) -> int:
    rank = int(rank)
    if rank < 1 or rank > 10:
        return 0
    if rank <= 3:
        return DARK_RANK_ITEM_COUNTS[rank - 1]
    return DARK_RANK_ITEM_COUNTS[3] if rank <= 5 else DARK_RANK_ITEM_COUNTS[4]


def port_dark_item_pool(items) -> list[dict[str, Any]]:
    """Use existing rarity 5-6 consumables/materials; do not invent item names."""
    pool = []
    seen = set()
    for item in items or ():
        if not isinstance(item, Mapping) or item.get("class") not in PORT_DESIGNED_DARK_ITEM_CLASSES:
            continue
        name = str(item.get("name") or "").strip()
        if not name or name in seen or item.get("不可交易") is True:
            continue
        try:
            rarity = int(float(item.get("稀有度") or 1))
        except (TypeError, ValueError):
            continue
        if rarity not in PORT_DESIGNED_DARK_ITEM_RARITIES:
            continue
        seen.add(name)
        pool.append({"name": name, "class": str(item.get("class") or "道具"), "amount": 1})
    return pool


def draw_port_dark_items(pool, count: int, rng) -> dict[str, int]:
    """One existing item per slot; the original pool's content/quantities are unavailable."""
    candidates = list(pool or ())
    if not candidates:
        return {}
    rewards: dict[str, int] = {}
    for _ in range(max(0, int(count))):
        item = rng.choice(candidates)
        name = str(item.get("name") or "").strip()
        amount = max(1, int(item.get("amount", 1) or 1))
        if name:
            rewards[name] = rewards.get(name, 0) + amount
    return rewards


def original_dark_rewards(reward: int, ledger: Mapping[str, tuple[str, int]],
                          limit: int = 20) -> list[tuple[str, str, int]]:
    """BOSS2 帝战排名榜奖励：前 20 按贡献计算，钳制 1,500~1,000,000。"""
    ranked = sorted(((str(uid), str(name), max(0, int(dmg)))
                     for uid, (name, dmg) in ledger.items()), key=lambda item: -item[2])
    total = sum(damage for _, _, damage in ranked)
    return [(uid, name, max(1_500, min(1_000_000,
                                      int(int(reward) * damage / total) if total else 1_500)))
            for index, (uid, name, damage) in enumerate(ranked[:max(0, int(limit))])]


# ---- 位面天骄 BOSS4：独立的胜负与共享进度口径 ----


def original_tianjiao_multiplier(name: str, player_level: int,
                                 realm_tier: str, independent_stats: bool = False) -> int | None:
    """返回旧 BOSS4 的镜像倍率；None 表示天骄此刻禁止越级挑战。"""
    if str(name) == "猪咪岁岁":
        return None if int(player_level) > 41 else 5
    if independent_stats:
        return None if realm_tier == "below" else 1
    if realm_tier == "below":
        return None
    return 5 if realm_tier == "full" else 3


def original_tianjiao_entry_allowed(name: str, player_level: int,
                                    current_hp: int, max_hp: int,
                                    realm_tier: str,
                                    independent_stats: bool = False,
                                    ideal_challenge: bool = False) -> tuple[bool, str, int]:
    """检查旧 BOSS4 的练气/血量与位面天骄境界差规则，返回对手镜像倍率。"""
    if not ideal_challenge and int(player_level) < 32:
        return False, "练气境界至少达到第 32 境才能讨伐天骄。", 0
    if not ideal_challenge and int(current_hp) <= int(max_hp) * 0.1:
        return False, "气血低于 10%，先疗伤再挑战天骄。", 0
    multiplier = original_tianjiao_multiplier(name, player_level, realm_tier,
                                               independent_stats)
    if multiplier is None and ideal_challenge:
        multiplier = 1 if independent_stats else (5 if name == "猪咪岁岁" else 3)
    if multiplier is None:
        return False, ("成仙者不得挑战低阶天骄。" if name == "猪咪岁岁"
                       else "境界不足以承受天骄本源，挑战被拒绝。"), 0
    return True, "", int(multiplier)


def original_tianjiao_progress(won: bool, empowered: bool = False) -> int:
    """按原版 sui yun 战斗倍率逐场削共享天骄血量百分比（40/2 或 20/1）。"""
    if empowered:
        return DARK_EMPOWERED_WIN_PROGRESS if won else DARK_EMPOWERED_LOSS_PROGRESS
    return DARK_WIN_PROGRESS if won else DARK_LOSS_PROGRESS


def original_tianjiao_battle_damage(won: bool, player_hp_max: int,
                                    attribute_multiplier: float = 1.0) -> int:
    """BOSS4 旧共享贡献榜按玩家血量上限计贡献；战败仅计 10%。"""
    fraction = float(attribute_multiplier) * (1.0 if won else 0.1)
    return max(0, int(max(0, int(player_hp_max)) * fraction))


def dark_specs(avg_atk: int, player_count: int) -> tuple[int, int, int, int]:
    """黑暗 Boss 数值（对齐 InitWorldBoss2）：返回 (血量, 奖池, 攻击, 防御)。

    基数 = 均伤×0.01；血量 = 基数×150×人数×200；奖池 1200 万（<5 人 600 万）；
    攻/防取基数的 2.2/1.1 倍（原版 Boss 攻防来自幻影生成，此处定标）。
    """
    base = max(1, int(avg_atk)) * 0.01
    count = max(1, int(player_count))
    health = int(base * 150 * count * 200)
    reward = 12_000_000 if count >= 5 else 6_000_000
    atk = int(base * 2.2) + 1
    defense = int(base * 1.1) + 1
    return health, reward, atk, defense


def dark_damage(won: bool, atk: int, boss_def: int, health_max: int, rng) -> int:
    """平定黑暗动乱单次伤害（对齐 WorldBossBattle）：
    胜 = 血上限×16% + Harm(攻×0.85, Boss防)×10；败 = 血上限×4% + Harm×6。
    """
    base_harm = harm(atk * 0.85, boss_def, rng)[0]
    if won:
        return int(health_max * 0.16 + base_harm * 10)
    return int(health_max * 0.04 + base_harm * 6)


def shenpo_specs(seg: int) -> tuple[int, int, int, int]:
    """锻神池 Boss 数值（对齐 pata DSC）：段数缩放。返回 (血, 攻, 防, 奖励)。"""
    s = max(0, int(seg))
    reward = min(400_000, 1200 * s)
    return 100_000 * s, 250_000 * s, 200_000 * s, reward
