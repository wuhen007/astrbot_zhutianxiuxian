"""团本讨伐：组队共享血条 + 伤害账本 + 按贡献分奖（纯函数，无 IO）。

对齐原版：
- apps/Battle/tuanben.js：`#创建讨伐队伍 名字` / `#加入讨伐队伍 队伍码` / `#发起讨伐` /
  `#查看队伍信息` / `#解散队伍` / `#结算团本奖励`；队伍上限 5 人；参战 24h CD；击杀者加成
- apps/TeamBoss/TeamBoss.js：若陀龙王（全服伤害榜 / 龙王榜 / 伤害账本分奖）

本移植改编（已写入《B档推进规划》）：
- 原版 5 人同时回合制结算；本插件为「队员各自出手」的共享血条战，
  每次出手与 Boss 法身单挑（复用黑暗动乱 dark_damage 的产出模型），按伤害记账
- 原版奖励走 redis 拍卖/分配；本插件击杀即按伤害占比自动分灵石，另给每人一份材料
- 原版 24h 参战 CD；本插件胜利后 12h、失败/解散 1h（小服节奏）
"""

from __future__ import annotations
from .clock import day_key

import random
import time
from collections.abc import Mapping, Sequence

from .battle import harm

MAX_MEMBERS = 5
HITS_PER_MEMBER = 3
HIT_COOLDOWN = 20          # 秒
RAID_TTL = 24 * 3600       # 招募/讨伐状态最长 24 小时
CLEAR_CD = 12 * 3600       # 胜利后 12 小时才能再开团
FAIL_CD = 3600             # 解散/逾期 1 小时

BOSSES: dict[str, dict] = {
    "若陀龙王": {
        "tier": 1.0,
        "realm": 15,
        "gate": "",
        "loot": "五行神石",
        "loot_qty": 1,
        "desc": "岩之神明所创之物，龙形岩躯盘踞层岩巨渊。一爪裂山，一吼断河。",
        "title": "岩龙",
    },
    "九幽魔君": {
        "tier": 1.6,
        "realm": 25,
        "gate": "魔君讨伐令",
        "loot": "混沌源石",
        "loot_qty": 2,
        "desc": "九幽之下执令者，麾下魔军百万。非持讨伐令者，不得入其魔域。",
        "title": "魔君",
    },
    "尸骸仙帝": {
        "tier": 2.3,
        "realm": 35,
        "gate": "",
        "loot": "欺天石",
        "loot_qty": 1,
        "desc": "尸骸成帝，一身死气。所过之处，万道凋零，连天机都不愿照见其名。",
        "title": "尸帝",
    },
}

STATUS_LABEL = {
    "recruiting": "招募中",
    "fighting": "讨伐中",
    "victory": "已讨伐",
    "closed": "已解散",
}


def boss_of(name: str) -> dict | None:
    return BOSSES.get(str(name or "").strip())


def boss_names() -> list[str]:
    return list(BOSSES)


def realm_ok(doc, boss: Mapping) -> bool:
    need = int(boss.get("realm", 0) or 0)
    return (int(getattr(doc, "realm_index", 0) or 0) + 1) >= need


def boss_stats(avg_atk: int, member_count: int, tier: float) -> dict:
    """按队伍平均攻击定标：血厚到需要多人多轮，奖励随血量走。"""
    avg = max(1, int(avg_atk or 1))
    n = max(1, min(MAX_MEMBERS, int(member_count or 1)))
    hp = max(1, int(avg * (3 + 2.5 * n) * float(tier)))
    return {
        "hp": hp,
        "hp_max": hp,
        "atk": max(1, int(avg * 1.15 * float(tier))),
        "defense": max(1, int(avg * 0.32 * float(tier))),
        "reward": max(1, int(hp * 0.18)),
    }


def shadow_of(team: Mapping, round_no: int = 1) -> tuple[str, int, int, int]:
    """Boss 法身：血量为本体 1/40，供单次出手单挑。"""
    name = f"{team.get('boss') or '团本Boss'}·法身"
    hp = max(1, int(team.get("hp_max", 1) or 1) // 40)
    return name, int(team.get("atk", 1) or 1), int(team.get("defense", 1) or 1), hp


def hit_damage(won: bool, atk: int, boss_def: int, hp_max: int, rng: random.Random) -> int:
    """对 Boss 本体伤害：胜 4% 上限 + 2×Harm；负 2% + 1.2×Harm（保底产出）。"""
    base = int(hp_max * (0.04 if won else 0.02))
    raw = harm(max(1, atk * 0.9), max(1, int(boss_def)), rng)[0]
    return int(base + raw * (2.0 if won else 1.2))


def split_rewards(
    reward: int, ledger: Sequence[tuple[str, str, int]], killer_uid: str | None = None,
    bonus: float = 0.10,
) -> list[dict]:
    """按伤害占比分灵石，击杀者额外 +10% 奖池。返回 [{uid,name,dmg,stones,share}]。"""
    total = sum(max(0, int(d[2])) for d in ledger)
    if total <= 0 or not ledger:
        return []
    out = []
    for uid, name, dmg in ledger:
        stones = int(reward * max(0, int(dmg)) / total)
        if killer_uid and uid == killer_uid:
            stones += int(reward * bonus)
        out.append({
            "uid": uid, "name": name, "dmg": int(dmg), "stones": stones,
            "share": round(max(0, int(dmg)) * 100 / total, 1),
        })
    out.sort(key=lambda x: -x["stones"])
    return out


def make_code(rng: random.Random, taken: set[str] | None = None) -> str:
    taken = taken or set()
    for _ in range(50):
        code = f"{rng.randint(0, 999999):06d}"
        if code not in taken:
            return code
    return f"{rng.randint(0, 999999):06d}"


def can_create(doc, boss_name: str, active: bool) -> tuple[bool, str, dict | None]:
    boss = boss_of(boss_name)
    if not boss:
        return False, f"没有「{boss_name}」这个团本。可讨伐：{'、'.join(BOSSES)}", None
    if active:
        return False, "你已在别的讨伐队伍中（#查看队伍信息 / #解散队伍）。", None
    if not realm_ok(doc, boss):
        return False, f"【{boss_name}】需第 {boss['realm']} 境，道友境界未至。", None
    return True, "", boss


def can_join(doc, team: Mapping, count: int, active: bool) -> tuple[bool, str]:
    if str(team.get("status")) != "recruiting":
        return False, "该队伍已不在招募阶段。"
    if active:
        return False, "你已在别的讨伐队伍中。"
    if count >= MAX_MEMBERS:
        return False, f"队伍已满（{MAX_MEMBERS}/{MAX_MEMBERS}）。"
    return True, ""


def can_start(team: Mapping, count: int, is_leader: bool) -> tuple[bool, str]:
    if not is_leader:
        return False, "只有队长可以发起讨伐。"
    if str(team.get("status")) != "recruiting":
        return False, "队伍已发起过讨伐。"
    if count < 1:
        return False, "队伍里还没有人。"
    return True, ""


def can_hit(team: Mapping, member: Mapping, now: float) -> tuple[bool, str]:
    if str(team.get("status")) != "fighting":
        return False, "队伍尚未发起讨伐（#发起讨伐）。"
    if int(team.get("hp", 0) or 0) <= 0:
        return False, "Boss 已被讨伐。"
    today = time_key(now)
    hits = int(member.get("hits_today", 0) or 0) if str(member.get("hits_day") or "") == today else 0
    if hits >= HITS_PER_MEMBER:
        return False, f"今日出手次数已尽（{HITS_PER_MEMBER}/{HITS_PER_MEMBER}），明日再来。"
    left = HIT_COOLDOWN - (float(now) - float(member.get("last_ts", 0) or 0))
    if left > 0:
        return False, f"法力未复，{int(left) + 1} 秒后再出手。"
    return True, ""


def time_key(ts: float) -> str:
    import time

    return day_key(ts)


def hits_today(member: Mapping, now: float) -> int:
    if str(member.get("hits_day") or "") != time_key(now):
        return 0
    return int(member.get("hits_today", 0) or 0)


def status_text(team: Mapping, members: Sequence[Mapping], now: float) -> str:
    status = STATUS_LABEL.get(str(team.get("status")), str(team.get("status")))
    lines = [
        f"--- 团本讨伐 · {team.get('boss')} ---",
        f"队伍码：{team.get('code')}｜状态：{status}",
    ]
    if str(team.get("status")) in ("fighting", "victory"):
        hp = max(0, int(team.get("hp", 0) or 0))
        hp_max = max(1, int(team.get("hp_max", 1) or 1))
        pct = round(hp * 100 / hp_max, 1)
        lines.append(f"Boss 血量：{hp:,} / {hp_max:,}（{pct}%）")
        lines.append(f"奖池：{int(team.get('reward', 0) or 0):,} 灵石")
    lines.append(f"成员：{len(members)}/{MAX_MEMBERS}")
    for m in members:
        tag = "（队长）" if m.get("uid") == team.get("leader_uid") else ""
        hits = hits_today(m, now)
        lines.append(
            f"· {m.get('name')}{tag}｜伤害 {int(m.get('dmg', 0) or 0):,}｜今日出手 {hits}/{HITS_PER_MEMBER}"
        )
    if str(team.get("status")) == "recruiting":
        lines.append(f"加入：#加入讨伐队伍 {team.get('code')}")
        lines.append("队长：#发起讨伐 开战")
    elif str(team.get("status")) == "fighting":
        lines.append("队员：#讨伐出手（今日 3 次，20 秒间隔）")
    elif str(team.get("status")) == "victory":
        lines.append("已按伤害分奖，#结算团本奖励 查看明细")
    return "\n".join(lines)
