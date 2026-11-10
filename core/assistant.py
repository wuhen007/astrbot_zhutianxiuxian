"""修仙助手（W24-F1）——按玩家当前进度输出阶段建议（纯函数，原版 #修仙助手 的规则化推荐）。

每条建议带 (优先级, 文案)，按优先级降序输出前 6 条。
"""

from __future__ import annotations

from typing import Any

from .player import PlayerDoc


def advice(doc: PlayerDoc, era_name: str = "天命时代",
           extra_name: str = "", beast_buff: bool = False,
           ) -> str:
    ri = int(getattr(doc, "realm_index", 0) or 0)
    pi = int(getattr(doc, "physique_index", 0) or 0)
    stones = int(getattr(doc, "stones", 0) or 0)
    ext = getattr(doc, "ext", {}) or {}
    lines: list[tuple[int, str]] = []

    # 硬门槛类
    if ri >= 39 and int(ext.get("power", 0) or 0) < 2:
        lines.append((99, "🔴 你已至无妄真劫境——**先 #渡劫** 再 #登仙，否则修为白白溢出！"))
    if ri >= 25 and not ext.get("linggen"):
        lines.append((90, "🔴 灵根未开——#灵根 查看当前灵根。"))
    if ri + 1 >= 26 and int(ext.get("potential", 0) or 0) < 4:
        lines.append((88, "🟡 仙道潜力偏低（<4）——每日任务 / 剧情支线可补。"))
    if float(ext.get("shouyuan", 9999) or 9999) < 200:
        lines.append((85, "🟡 寿元不足 200 年——#服用寿命丹 或 #供奉神石。"))

    # 额外体系
    if ri >= 31 and pi >= 41 and not extra_name:
        lines.append((80, "🟢 练气 32 + 炼体 42 已达标——选择额外体系：#证道 / #冲关 / #踏上花粉路（三选一不可并修）"))
    elif extra_name == "仙古":
        lines.append((72, "🟢 仙古路线：#冲关 推境界 / #冲关极境 打磨 / 尊者后 #申请入院"))
    elif extra_name == "花粉":
        lines.append((72, "🟢 花粉路线：#感应异变 / #花粉悟道 / 觉醒后 #穿梭圣墟位面"))

    # 帝路
    if ri >= 40 or pi >= 40:
        lines.append((70, "🟢 帝路开放：#渡斩道雷劫 起步——逐档而进（斩道/圣人/圣人王/大圣/准帝）。"))
    if ri >= 45:
        lines.append((68, "🟢 可尝试 #悟道（燃烧寿元参悟己道）——先 #我的道途 查看真实寿元。"))

    # 日常
    lines.append((60, "⬜ 每日：#修仙签到 → #获取每日任务 → #提交每日任务 → #领取每日奖励 → #每日抽奖"))
    lines.append((58, "⬜ 每日：#一键挑战镇妖塔 + #一键炼神魄 + #垂纶"))
    if era_name == "神话时代":
        lines.append((55, "🟢 当前神话时代——消耗 ×0.4、成功率 +25%，**冲关黄金期**！"))
    elif era_name == "绝灵时代":
        lines.append((55, "🔴 当前绝灵时代——消耗 ×3.0，别硬冲突破！"))
    elif era_name == "末法时代":
        lines.append((55, "🟡 末法时代——消耗 ×1.8，苟着采药炼丹。"))

    # 经济
    if stones < 50_000 and ri >= 10:
        lines.append((50, "🟡 灵石紧张——#降妖 或 #职业产出 挂机。"))
    if stones > 500_000:
        lines.append((48, "⬜ 灵石充裕——可考虑 #建设宗门 / #宗门捐赠灵石 / 星阁投资。"))

    lines.sort(key=lambda t: -t[0])
    return "\n".join(["--- 修仙助手 ---"] + [msg for _, msg in lines[:6]]
                     + ["\n以本服回执为准｜#基础帮助 查全部指令"])
