"""钱包与权柄公共助手（审计修复 #12 合并）——收编此前散落在
zhengdao / daolu / selfdao / ownway / plane_events / physique /
exclusive_set / occupation_extra / wudao 九个模块里的同名私有助手。

语义与被收编实现逐字节一致，仅改集中出处：
- authority(doc)          权柄：authority_of 优先，异常时回退双轨 max
- xueqi(doc) / set_xueqi  血气读写在 doc.ext["xueqi"]（int 口径）
- pay_exp_xq(doc, amount) 修为与血气同额扣费；不足返回错误文案，足则 None
- pay_potential(doc, amt) 仙道潜力扣费；不足返回错误文案，足则 None

调用方一律 `from .wallet import x as _x` 保持原私有名，调用点零改动。
"""

from __future__ import annotations

from typing import Any

from .player import PlayerDoc


def authority(doc: Any) -> int:
    """权柄（双轨 max 折算）：authority_of 优先，异常回退。"""
    try:
        from . import authority as _auth
        return int(_auth.authority_of(doc))
    except Exception:
        return max(int(getattr(doc, "realm_index", 0) or 0),
                   int(getattr(doc, "physique_index", 0) or 0))


def xueqi(doc: Any) -> int:
    return int(float((getattr(doc, "ext", {}) or {}).get("xueqi", 0) or 0))


def set_xueqi(doc: Any, value: int) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["xueqi"] = max(0, int(value))


def pay_exp_xq(doc: PlayerDoc, amount: int) -> str | None:
    """修为与血气同额扣费；不足返回错误文案，足则扣并返回 None。"""
    if int(getattr(doc, "exp", 0) or 0) < amount or xueqi(doc) < amount:
        return (f"需修为与血气各 {amount:,}（当前 "
                f"{int(getattr(doc, 'exp', 0) or 0):,} / {xueqi(doc):,}）。")
    doc.exp = int(getattr(doc, "exp", 0) or 0) - amount
    set_xueqi(doc, xueqi(doc) - amount)
    return None


def pay_potential(doc: PlayerDoc, amount: int) -> str | None:
    """仙道潜力扣费；不足返回错误文案（不扣），足则扣并返回 None。"""
    pot = int(float((getattr(doc, "ext", {}) or {}).get("potential", 0) or 0))
    if pot < amount:
        return f"仙道潜力不足：需 {amount}（现有 {pot}）。"
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["potential"] = pot - amount
    return None
