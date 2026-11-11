"""社交经济：灵石红包 + 物品赠送——原版 `apps/User/MoneyOperation.js`
（871 行）中的发红包/抢红包/赠送三件套（深度核查补漏 W28）。

玩法：
- `#发红包 灵石*个数`：扣「总额 + 运输费」挂上全服红包墙，任意修士
  `#抢红包 @发送者` 逐份领取（每份 = 单份灵石）；抢有 CD（原版配置
  CD.honbao → 端口 3 分钟）；发送者下线/红包发完前一直挂着。
  shortcut：原版无过期退回，端口 24 小时懒退回未领部分（防资产滞留）；
  原版维度壁垒跨层校验不移植（端口位面无层级隔离）；灵石取整到万沿用
  （÷1000 后改为取整到百，保持「整数份」观感）。
- `#赠送 @对方 物品*数量`：库存物品直转（唯一物品/装备不可转）。
  双方 per-uid 锁由 handler 按 uid 排序获取。

全服态挂 calamity_state["hongbao"]（{sender_uid: {per, left, at}}），
调用方持 calamity_lock。运输费沿用端口转账口径 1%（原版 percentage.cost）。
"""

from __future__ import annotations

import time
from typing import Any

FEE_RATE = 0.01            # 运输费（端口转账口径 1%）
GRAB_CD_MS = 3 * 60 * 1000  # 抢红包 CD（原版 CD.honbao）
EXPIRE_MS = 24 * 3600 * 1000  # 未领部分 24h 懒退回（原版无，登记 shortcut）
UNIT_ROUND = 100            # 单份灵石取整（原版取整到万 ÷1000 → 百）


def wall_of(world: dict) -> dict:
    hb = world.get("hongbao")
    if not isinstance(hb, dict):
        hb = {}
        world["hongbao"] = hb
    return hb


def _refund_due(world: dict, now_ms: float) -> list[tuple[str, int]]:
    """过期红包 → [(sender_uid, 退回灵石)]，并从墙上摘除。"""
    wall = wall_of(world)
    due = []
    for uid, rec in list(wall.items()):
        if now_ms - float(rec.get("at", 0) or 0) > EXPIRE_MS and int(rec.get("left", 0) or 0) > 0:
            per = int(rec.get("per", 0) or 0)
            left = int(rec.get("left", 0) or 0)
            due.append((uid, per * left))
            del wall[uid]
    return due


def send(world: dict, sender_uid: str, sender_name: str, per: int, count: int,
         stones_have: int, now_ms: float) -> tuple[bool, str, int]:
    """#发红包 灵石*个数。返回 (ok, text, 总扣款)。"""
    per = max(0, int(per or 0))
    count = max(0, int(count or 0))
    if per <= 0 or count <= 0:
        return False, "用法：#发红包 单份灵石*个数（如 #发红包 10000*5）", 0
    per = max(UNIT_ROUND, per // UNIT_ROUND * UNIT_ROUND)
    if count > 99:
        count = 99
    total = per * count
    fee = total * FEE_RATE // 1
    if stones_have < total + fee:
        return False, (f"灵石不足：需 {total + fee:,}（红包 {total:,} + 运输费 {fee:,}），"
                       f"持有 {stones_have:,}。"), 0
    wall = wall_of(world)
    # 退回到期旧红包（同 sender 只挂一份，旧未领部分先退回）
    old = wall.pop(str(sender_uid), None)
    refund = 0
    if old and int(old.get("left", 0) or 0) > 0:
        refund = int(old["per"]) * int(old["left"])
    wall[str(sender_uid)] = {"per": per, "left": count, "name": str(sender_name),
                             "at": now_ms}
    text = (f"【全服公告】{sender_name} 发了 {count} 个 {per:,} 灵石的红包！"
            f"（运输费 {fee:,}）\n抢红包：#抢红包 @他")
    if refund > 0:
        text = f"（旧红包未领 {refund:,} 灵石已退回）\n" + text
    return True, text, total + fee - refund


def grab(world: dict, sender_uid: str, grabber_uid: str, grabber_name: str,
         last_grab_ms: float, now_ms: float) -> tuple[bool, str, int]:
    """#抢红包 @发送者。返回 (ok, text, 到手灵石)。"""
    if last_grab_ms > 0 and now_ms - last_grab_ms < GRAB_CD_MS:
        remain = int((GRAB_CD_MS - (now_ms - last_grab_ms)) / 1000)
        return False, f"抢红包 CD 中，还需 {remain // 60}分{remain % 60}秒。", 0
    wall = wall_of(world)
    rec = wall.get(str(sender_uid))
    if not rec or int(rec.get("left", 0) or 0) <= 0:
        return False, "TA 的红包已经空了（或没有挂红包）。", 0
    if str(sender_uid) == str(grabber_uid):
        return False, "不能抢自己的红包。", 0
    per = int(rec["per"])
    rec["left"] = int(rec["left"]) - 1
    left = int(rec["left"])
    if left <= 0:
        del wall[str(sender_uid)]
    tail = ("红包已抢空！" if left <= 0 else f"还剩 {left} 份。")
    return True, (f"【抢红包】{grabber_name} 抢到 {per:,} 灵石！{tail}"), per


def wall_text(world: dict, now_ms: float) -> str:
    wall = wall_of(world)
    alive = {u: r for u, r in wall.items() if int(r.get("left", 0) or 0) > 0}
    if not alive:
        return "【红包墙】当前空空如也——#发红包 单份灵石*个数 挂一个吧！"
    lines = [f"【红包墙】{len(alive)} 份在挂（24h 未领完自动退回）：", ""]
    for u, r in alive.items():
        remain_h = max(0, int((EXPIRE_MS - (now_ms - float(r.get("at", 0) or 0))) / 3600000))
        lines.append(f"· {r.get('name') or u}：单份 {int(r['per']):,} × 剩 {r['left']} 份"
                     f"（{remain_h}h 后退回）——#抢红包 @TA")
    return "\n".join(lines)


def gift_check(item: dict, qty: int) -> str | None:
    """赠送前物品校验。返回错误文案或 None。"""
    if not item:
        return "纳戒里没有这件物品。"
    if int(qty or 0) < 1:
        return "数量至少 1。"
    if item.get("class") == "装备" or str(item.get("type")) == "装备":
        return "装备不可赠送。"
    if item.get("不可交易") or item.get("unique"):
        return "该物品天地唯一/绑定，不可转赠。"
    return None


def rules_text() -> str:
    return "\n".join([
        "【红包与赠送·规则】",
        "· #发红包 单份灵石*个数 —— 扣总额+1% 运输费挂上红包墙",
        "· #抢红包 @发送者 —— 逐份领取，3 分钟 CD，不能抢自己的",
        "· #红包墙 —— 查看当前在挂红包；24h 未领完自动退回",
        "· #赠送 @对方 物品*数量 —— 库存物品直转（装备/唯一物品不可赠）",
    ])
