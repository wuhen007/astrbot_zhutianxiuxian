"""神界系统（移植原版 apps/shenjie/shenren.js，纯函数无 IO）。

- #供奉神石：全部神石入供奉进度（/200）；魔道值 > 0 者被神界拒之门外。
- #参悟神石*N：8 神石/次 → 随机限定丹药（Timelimit/限定丹药.json）。
- #敲开闪闪发光的石头*N：1 石/次 → 随机限定丹药（赌石）。
- #踏入神界：供奉进度 ≥200 + 220 万灵石 + 每日 1 次 → 神界中 30 分钟 → 归来大奖。
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any

SHENSHI_NEED = 200          # 供奉进度门槛
CANWU_COST = 8              # 参悟单价（神石/次）
SHENJIE_STONES = 2_200_000  # 踏入神界灵石
SHENJIE_MINUTES = 30        # 神界历练时长
SHENJIE_REWARD_STONES = 8_000_000   # 归来灵石大奖
SHENJIE_REWARD_SHENSHI = 10         # 归来神石返还


def offer_gate(modao: int, linggen_type: str) -> tuple[bool, str]:
    """神界资格：魔道值 > 0 且非转生/命运灵根 → 拒绝（对齐原版）。"""
    if int(modao or 0) > 0 and str(linggen_type) not in ("转生", "命运"):
        return False, "你身上带着罪孽亦或者并非轮回者，神界不接受你的供奉。"
    return True, ""


def offer_shenshi(progress: int, shenshi_owned: int) -> tuple[int, int]:
    """供奉：全部神石入进度。返回 (新进度, 消耗数)。"""
    n = max(0, int(shenshi_owned))
    return int(progress) + n, n


def pick_pill(pill_table: Sequence[Mapping], rng: random.Random) -> Mapping | None:
    """随机抽一枚限定丹药。"""
    if not pill_table:
        return None
    return pill_table[int(rng.random() * len(pill_table)) % len(pill_table)]


def canwu_rewards(pill_table: Sequence[Mapping], times: int, rng: random.Random) -> dict[str, int]:
    """参悟 N 次 → 限定丹药聚合表。"""
    out: dict[str, int] = {}
    for _ in range(max(1, int(times))):
        pill = pick_pill(pill_table, rng)
        if pill and pill.get("name"):
            out[str(pill["name"])] = out.get(str(pill["name"]), 0) + 1
    return out


def shenjie_entry_gate(progress: int, stones: int, modao: int, linggen_type: str,
                       used_today: bool) -> tuple[bool, str]:
    """踏入神界四重门槛。"""
    ok, why = offer_gate(modao, linggen_type)
    if not ok:
        return False, why
    if int(progress) < SHENSHI_NEED:
        return False, f"【神界·供奉不足】供奉进度不足（{progress}/{SHENSHI_NEED}），先 #供奉神石。"
    if int(stones) < SHENJIE_STONES:
        return False, f"灵石不足（需 {SHENJIE_STONES}）。"
    if used_today:
        return False, "今日神界次数已用光，请明日再来。"
    return True, ""


def shenjie_rewards() -> dict[str, int]:
    """神界归来奖励：灵石 + 神石返还（原版结算在定时任务，此处定标）。"""
    return {
        "__stones__": SHENJIE_REWARD_STONES,
        "神石": SHENJIE_REWARD_SHENSHI,
    }


def evil_profile(doc: Mapping[str, Any]) -> str:
    """#我的邪道 简版展示（魔头 PvP 禁术链延后，展示已实装维度）。"""
    modao = int(doc.get("ext", {}).get("modao", 0) or 0)
    yeli = int(doc.get("ext", {}).get("yeli", 0) or 0)
    lines = ["--- 邪道状态 ---", f"魔道值：{modao}", f"业力值：{yeli}"]
    if modao > 0:
        lines.append("禁术体系（镇魂/魂奴/人傀/道果）尚封印中，魔道将随版本释放。")
    else:
        lines.append("正道之身，魔气未侵。")
    return "\n".join(lines)
