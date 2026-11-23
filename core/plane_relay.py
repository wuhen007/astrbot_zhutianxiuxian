"""位面中转（W22-F1）——原版 `main.py` 位面帮助四条：#接引 / #送往 /
#消耗位面传送阵 / #激活五色祭坛 的纯函数移植，复用 `core/plane.py` 的
ext["plane"] 状态（current / coords / known / marks）。

原版语义：
- #接引 @目标：仙王级，需自身已知双方坐标；目标 60 秒内 #同意接引，
  可 #拒绝接引。
- #送往 @目标 @位面：把目标送往已知位面。
- #消耗位面传送阵：走传送阵仍需时间，低级阵易遇虚空乱流；需先刻画坐标。
- #激活五色祭坛：圣人以下前往遮天位面的手段，激活即记下遮天坐标。

本移植（shortcut）：
- 「已知双方坐标」折算为「已知该位面」（known 列表）；接引落点=发送者
  当前位面与坐标。
- 传送阵：需位面传送阵 ×1 + 已知该位面；25% 虚空乱流 → 修为 -10%
  （原版按阵等级分级，未搬）。
- 五色祭坛：权柄 <14（圣人折算）、修为血气各 500,000；激活即把「遮天位面」
  记入 known 与坐标（中心 500,500）。
"""

from __future__ import annotations

from typing import Any, Mapping

from .player import PlayerDoc
from .wallet import authority, pay_exp_xq

RELAY_AUTH = 18                 # 仙王折算
WUXI_GATE = 14                  # 圣人折算（圣人以下可激活）
WUXI_COST = 500_000
WUXI_PLANE = "遮天位面"
PORTAL_ITEM = "位面传送阵"
TURBULENCE = 0.25
OFFER_SECONDS = 60


def _center() -> dict:
    return {"x": 500, "y": 500}


# ---------------------------------------------------------------- 五色祭坛

def wuxi_activate(doc: PlayerDoc, st: dict[str, Any], now: float,
                  ) -> tuple[bool, str]:
    """#激活五色祭坛：圣人以下记下遮天坐标，可直达。"""
    if authority(doc) >= WUXI_GATE:
        return False, "你已是圣人之境——穿梭遮天无需借祭坛之力。"
    if WUXI_PLANE in (st.get("known") or []):
        return False, "五色祭坛早已激活——遮天坐标在册（#位面 直接前往）。"
    err = pay_exp_xq(doc, WUXI_COST)
    if err:
        return False, f"【位面中继·条件不足】激活需修为与血气各 {WUXI_COST:,}。{err}"
    st.setdefault("known", []).append(WUXI_PLANE)
    st.setdefault("coords", {})[WUXI_PLANE] = _center()
    return True, ("【五色祭坛】五彩灵光冲天而起——遮天位面坐标已刻入识海！\n"
                  "此后 #穿梭 遮天位面 直达，无需记坐标。")


# ---------------------------------------------------------------- 接引 / 送往

def jiesong_offer(sender_st: Mapping[str, Any], sender_auth: int, sender_name: str,
                  target_st: dict[str, Any], target_name: str, now: float,
                  ) -> tuple[bool, str]:
    """#接引 @目标：仙王级，写入 60 秒待确认（存目标档）。"""
    if sender_auth < RELAY_AUTH:
        return False, f"接引需仙王之力（权柄 ≥{RELAY_AUTH}），当前 {sender_auth}。"
    plane = str(sender_st.get("current") or "")
    coord = (sender_st.get("coords") or {}).get(plane)
    if not isinstance(coord, dict):
        coord = _center()
    old = target_st.get("plane_offer")
    if isinstance(old, dict) and float(old.get("until", 0) or 0) > now:
        return False, f"「{target_name}」尚有待应答的接引（60 秒内）。"
    target_st["plane_offer"] = {
        "from_uid": "", "from_name": sender_name, "plane": plane,
        "x": int(coord.get("x", 500)), "y": int(coord.get("y", 500)),
        "until": now + OFFER_SECONDS,
    }
    return True, (f"【接引】仙光垂落——{target_name} 被你的道音牵引，"
                  f"60 秒内 #同意接引 可瞬至「{plane}」（#拒绝接引 拒之）。")


def jiesong_accept(doc: PlayerDoc, st: dict[str, Any], now: float,
                   ) -> tuple[bool, str]:
    offer = st.get("plane_offer")
    if not isinstance(offer, dict):
        return False, "没有人正在接引你。"
    if float(offer.get("until", 0) or 0) < now:
        st.pop("plane_offer", None)
        return False, "接引的仙光已散（60 秒未应答）。"
    plane = str(offer.get("plane") or "")
    st["current"] = plane
    st.setdefault("coords", {})[plane] = {
        "x": int(offer.get("x", 500)), "y": int(offer.get("y", 500))}
    if plane not in (st.get("known") or []):
        st.setdefault("known", []).append(plane)
    st.pop("plane_offer", None)
    return True, f"【同意接引】仙光卷身——瞬至「{plane}」！"


def jiesong_reject(st: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(st.get("plane_offer"), dict):
        return False, "没有人正在接引你。"
    st.pop("plane_offer", None)
    return True, "【拒绝接引】仙光散去——各安其位。"


def songwang(target_st: dict[str, Any], plane: str, coord: Mapping[str, int],
             target_name: str) -> tuple[bool, str]:
    """#送往：把目标送往已知位面（发送者需已记该位面坐标）。"""
    target_st["current"] = plane
    target_st.setdefault("coords", {})[plane] = {
        "x": int(coord.get("x", 500)), "y": int(coord.get("y", 500))}
    if plane not in (target_st.get("known") or []):
        target_st.setdefault("known", []).append(plane)
    target_st.pop("plane_offer", None)
    return True, f"【送往】{target_name} 被道音裹挟，瞬至「{plane}」！"


# ---------------------------------------------------------------- 传送阵

def portal_use(doc: PlayerDoc, st: dict[str, Any], plane: str, inv: Mapping[str, int],
               now: float, rng: Any) -> tuple[bool, str, dict[str, int]]:
    """#消耗位面传送阵 位面名：阵符×1，25% 虚空乱流 → 修为 -10%。"""
    plane = (plane or "").strip()
    if plane not in (st.get("known") or []):
        return False, f"传送阵上未刻画「{plane}」坐标——先 #记坐标 {plane}。", {}
    if int((inv or {}).get(PORTAL_ITEM, 0) or 0) < 1:
        return False, f"你并没有「{PORTAL_ITEM}」。", {}
    st["current"] = plane
    if not isinstance((st.get("coords") or {}).get(plane), dict):
        st.setdefault("coords", {})[plane] = _center()
    if plane not in (st.get("known") or []):
        st.setdefault("known", []).append(plane)
    if rng.random() < TURBULENCE:
        loss = int(float(getattr(doc, "exp", 0) or 0) * 0.10)
        doc.exp = int(getattr(doc, "exp", 0) or 0) - loss
        return True, (f"【位面传送阵】灵光大作——却在虚空遭遇乱流！\n"
                      f"抵达「{plane}」，修为 -{loss:,}（乱流 25%）。"), {PORTAL_ITEM: -1}
    return True, f"【位面传送阵】一步跨过万界——抵达「{plane}」！", {PORTAL_ITEM: -1}
