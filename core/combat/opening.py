"""开场阶段（W1-4）：高境镇杀 / 宿云同境裁决 / 帝骑助战。

原版语义（model/highRealmBarrier.js + model/suiyunPvp.js + model/decadeCombat.js）：

- 高境镇杀：双方权柄 ≥20（准仙帝档）且有差距 → 低境者开场被镇杀
  （全战斗属性 -90%、封 一气化三清/皆字秘/临字秘、不可复活、气血归零）。
  「境界差是先于行动条、技能、反伤与复活的战斗规则」——故 1v1 直接判高境胜。
- 岁云同境裁决：PVP 中岁云灵根持有者（SUIYUN_STAGES 五阶）可把权柄更高的对手
  压到与自己同级。原版压的是额外体系（秘境/仙古/花粉）等效境界；本移植三轨未开
  （见推进计划 W0-3），适配为**压对手高轨的基础表值**到持有者权柄档位——
  只削境界带来的基础属性，装备/功法加成保留。
- 帝骑助战：原版召唤骑士分身（60% 战力、3 回合、上限 2、团战多单位）。
  1v1 引擎不装多单位，适配为**开场合击**一次：trunc(攻 × 0.6 × 2)，
  需诸天镜帝骑卡组三卡齐编（tags["decade_deck"]）。

镇杀/裁决/助战均只改战斗副本，不落库；调用方在 run_1v1 之前依次执行。
"""

from __future__ import annotations

from typing import Any

from .engine import Fighter

HIGH_REALM_GATE = 20          # 原版权柄档门槛（准仙帝）
DECADE_AVATAR_RATIO = 0.6     # 分身继承本体战力比例
DECADE_AVATAR_MAX = 2         # 原版同场上限（合击等效 ×2）

SUIYUN_NAMES = {"月华之体", "月华似剑", "霜月剑尊", "岁云化身", "岁云剑尊"}

REALM_VISIONS = {
    20: "帝光初生，诸界的喧嚣一寸寸沉寂。",
    21: "路尽之处，一道眸光落下。诸天的日月仍在轮转，此间的岁月却已凝成一张薄纸。",
}


def _row(table: list[dict], idx: int) -> dict:
    return table[max(0, min(int(idx or 0), len(table) - 1))] if table else {}


def high_realm_exec(a: Fighter, b: Fighter) -> tuple[int, list[str]] | None:
    """高境镇杀：返回 (winner, msgs) 或 None（未触发）。

    判定依据 tags["auth21"]（build_fighter 挂的 0-21 权柄档）。
    """
    la = int(a.tags.get("auth21", 0) or 0)
    lb = int(b.tags.get("auth21", 0) or 0)
    if la == lb or max(la, lb) < HIGH_REALM_GATE:
        return None
    winner = 0 if la > lb else 1
    high, low = (a, b) if la > lb else (b, a)
    if int(low.tags.get("suiyun_stage", 0) or 0) >= 3:
        return None       # W8-B4 岁云常青：免即死 / 免禁复活，镇杀对其无效
    low.hp = 0
    low.effects["sealed"] = True       # 不可复活（_try_revive 前 sealed 单位已无血，此处仅作文案）
    vision = REALM_VISIONS.get(max(la, lb), "道果横隔，天地相隔。")
    msgs = [
        f"【{max(la, lb)} 档道果·境界天堑】{vision}",
        f"{high.name}的道果横隔在前，{low.name}全战斗属性降低90%，"
        f"一气化三清、皆字秘、临字秘与全部灵根技能失效，复生之机一并沉寂——气血归零。",
    ]
    return winner, msgs


def suiyun_verdict(
    a: Fighter, b: Fighter, qi_table: list[dict], body_table: list[dict]
) -> list[str]:
    """岁云同境裁决：压高境对手的高轨基础表值到岁云持有者的权柄档位。

    需 build_fighter 挂 tags：realm_index / physique_index / auth_of / linggen_name。
    双方都可持有岁云灵根；先处理权柄低的一方为持有者的组合。
    """
    msgs: list[str] = []
    for holder, foe in ((a, b), (b, a)):
        if str(holder.tags.get("linggen_name") or "") not in SUIYUN_NAMES:
            continue
        h_auth = int(holder.tags.get("auth_of", 0) or 0)
        o_auth = int(foe.tags.get("auth_of", 0) or 0)
        if o_auth <= h_auth:
            continue
        o_realm = int(foe.tags.get("realm_index", 0) or 0)
        o_phy = int(foe.tags.get("physique_index", 0) or 0)
        track_is_qi = o_realm >= o_phy
        table = qi_table if track_is_qi else body_table
        if not table:
            continue
        loc = o_realm if track_is_qi else o_phy
        target = min(loc, h_auth)
        if target >= loc:
            continue
        old_row, new_row = _row(table, loc), _row(table, target)
        pressed = []
        for col, attr in (("基础攻击", "atk"), ("基础防御", "defense"), ("基础血量", "hp_max")):
            delta = float(old_row.get(col, 0) or 0) - float(new_row.get(col, 0) or 0)
            if delta > 0:
                setattr(foe, attr, max(1, int(getattr(foe, attr) - delta)))
                pressed.append(f"{col[2:]} -{int(delta):,}")
        foe.hp = min(foe.hp, foe.hp_max)
        # 同步降权柄档（原版 capRealmAuthorityForBattle 改境界字段 → 镇杀判定用压后值，
        # 故岁云持有者永远不会被同一场镇杀）
        foe.tags["auth_of"] = h_auth
        foe.tags["auth21"] = min(int(foe.tags.get("auth21", 0) or 0), h_auth * 21 // 63)
        msgs.append(
            f"【岁云·同境裁决】{holder.name}令{foe.name}的"
            f"{'练气' if track_is_qi else '炼体'}境界由第 {loc + 1} 重压至第 {target + 1} 重"
            f"（{'、'.join(pressed) if pressed else '属性归位'}），本场切磋强制同境。"
        )
    return msgs


def decade_assist(attacker: Fighter, defender: Fighter, deck: list[str] | None) -> str | None:
    """帝骑开场合击：三卡齐编 → 两道分身（各 60% 战力）合击一击。

    返回战报；若一击致对方气血归零，调用方应直接判胜（开场即溃）。
    """
    if len(deck or []) < 3:
        return None
    dmg = max(1, int(attacker.atk * DECADE_AVATAR_RATIO * DECADE_AVATAR_MAX))
    defender.hp = max(0, defender.hp - dmg)
    return (f"【骑士助战】{'、'.join(str(x) for x in deck[:3])} 三骑撕裂次元壁踏临战场，"
            f"各继承 60% 战力发起合击——{defender.name} 受 {dmg} 点伤害！")
