"""炼丹生活职业：配方 + 制造结算（纯函数，无 IO）。

配方取自原版 resources/data/occupation/炼丹配方.json（21 条，材料 100% 在物品索引）。
等级经验制：成功得 exp[0]、失败得 exp[1]（原版字段），等级 = 阈值表升档；
成功率 = 配方 rate + 等级加成（每级 +2%），封顶 1.0。
产物在物品索引中且效果已实装（修为/血量/血气/天资洗炼类）的配方才开放。
"""

from __future__ import annotations

import random
from collections.abc import Mapping

# 对齐原版炼丹师等级刻度（0-20 级，配方 level_limit 最高 20）
LEVEL_THRESHOLDS = (
    0, 100, 300, 700, 1200, 2000, 3000, 4500, 6500, 9000,
    12000, 16000, 21000, 27000, 34000, 42000, 51000, 61000, 72000, 85000, 100000,
)
LEVEL_RATE_BONUS = 0.02
MAX_LEVEL = 20


def level_of(exp: int) -> int:
    lv = 0
    for i, t in enumerate(LEVEL_THRESHOLDS):
        if exp >= t:
            lv = i
    return lv


def next_threshold(exp: int) -> int | None:
    lv = level_of(exp)
    return LEVEL_THRESHOLDS[lv + 1] if lv < MAX_LEVEL else None


def success_rate(recipe: Mapping, alchemy_lv: int) -> float:
    try:
        raw = recipe.get("rate", 1.0)
        base = float(raw) if raw is not None else 1.0
    except (TypeError, ValueError):
        base = 1.0
    return min(1.0, base + LEVEL_RATE_BONUS * max(0, alchemy_lv))


def missing_materials(recipe: Mapping, inventory: Mapping[str, int]) -> list[tuple[str, int, int]]:
    """返回 [(材料名, 需要, 现有)]，仅含不足项。"""
    out = []
    for m in recipe.get("materials") or []:
        need = int(m.get("amount", 1))
        have = int(inventory.get(str(m.get("name")), 0))
        if have < need:
            out.append((str(m.get("name")), need, have))
    return out


def level_locked(recipe: Mapping, alchemy_lv: int) -> bool:
    try:
        return alchemy_lv < int(recipe.get("level_limit", 0) or 0)
    except (TypeError, ValueError):
        return False


# 原版 zhizuo_dan 直接产出名单（不入品质分档）
SPECIAL_DIRECT = frozenset({"起死回生丹", "天命轮回丹", "大衍悟道丹"})
QUALITY_TIERS = ("凡品", "极品", "仙品")


def craft_pills(
    recipe: Mapping, alchemy_lv: int, rng: random.Random, qty: int = 1
) -> tuple[dict[str, int], int]:
    """原版炼丹语义（必成 + 品质分档）。返回 (产物分桶, 新经验)。

    对齐 apps/Occupation/Occupation.js zhizuo_dan：
    - 特殊丹（SPECIAL_DIRECT）→ {"": qty} 直接得原丹；
    - 其余掷品质：凡品阈值 = clamp(0.1 + 炼丹等级×3%, 0, 0.95)（等级越高凡品越少），
      未过阈值再以 40% 出仙品，否则极品 → {"凡品": n, "极品": m, ...}。
    经验按配方 exp[0] × 数量（必成无失败经验）。
    """
    ok_n = max(1, int(qty))
    name = str(recipe.get("name", "?"))
    exp_gain = int(recipe.get("exp", [0, 0])[0]) * ok_n
    if name in SPECIAL_DIRECT:
        return {"": ok_n}, exp_gain
    fanpin = max(0.0, min(0.95, 0.1 + max(0, alchemy_lv) * 3 / 100))
    counts: dict[str, int] = {}
    for _ in range(ok_n):
        r1, r2 = rng.random(), rng.random()
        if r1 >= fanpin:
            tier = "凡品"
        elif r2 < 0.4:
            tier = "仙品"
        else:
            tier = "极品"
        counts[tier] = counts.get(tier, 0) + 1
    return counts, exp_gain


def craft(
    recipe: Mapping, alchemy_exp: int, rng: random.Random, qty: int = 1
) -> tuple[bool, int, str]:
    """炼制 qty 次。返回 (全部成功?, 新累计经验, 文本)。

    逐次掷骰；材料扣减由调用方在事务中完成（这里只算结果与经验）。
    """
    lv = level_of(alchemy_exp)
    rate = success_rate(recipe, lv)
    ok_n = sum(1 for _ in range(max(1, qty)) if rng.random() < rate)
    fail_n = qty - ok_n
    exp_gain = int(recipe.get("exp", [0, 0])[0]) * ok_n + int(recipe.get("exp", [0, 0])[1]) * fail_n
    name = str(recipe.get("name", "?"))
    if ok_n == qty:
        return True, alchemy_exp + exp_gain, f"丹炉火候正好，{name} ×{ok_n} 炼制成功！"
    if ok_n == 0:
        return False, alchemy_exp + exp_gain, f"丹炉炸了……{name} 全部炼废（材料已耗）。"
    return (
        ok_n == qty,
        alchemy_exp + exp_gain,
        f"{name} ×{qty}：成 {ok_n} 炉、废 {fail_n} 炉。",
    )
