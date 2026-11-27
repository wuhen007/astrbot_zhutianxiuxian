# -*- coding: utf-8 -*-
"""对 triage_raw.csv 施加判定，产出 triage.csv 与模块汇总。

判定口径：
- alias   功能已在，仅需补原版命令名（或原名已被正则别名覆盖）
- missing 需要实现
- frag    正则伪影 / 宽泛前缀 / 本地机制不同但功能在，不单独实现
- skip    按要求不做或原版缺陷
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "triage_raw.csv"
OUT = HERE / "triage.csv"

FRAG = set("""
一键 传音给作者s 使用s 全体发 以S 召唤S 发 取 存 去 以 借助 查看 消耗 服用 探索 探索s 寻宝 前往s
上d 下d 左d 右d 左上d 左下d 右上d 右下d 灌顶至d 古史打击n 支取时间线n 查 查一下我 大 小 代 领取 我同意
请私信发我一条消息 将米娜桑的纳戒里叫 /取下 /查看 /强化 /镶嵌 战 召唤 讨伐
""".split())

ALIAS = set("""
为其逆天改命s 人皇敕令s 仙钓签到 众生仙钓签到 垂钓签到 全部取出内景地 分配功法感悟s 切换太极s 切换练气排版s
切换重抽命格s 创造帝经s 剑云海兑换 副本结算 功法参悟 加工 合成 孵化 打开 卸下 参悟 合成呼吸法s 合道s 垂钓众生
复活选择s 大成神王体 小成神王体 太阳圣皇体成就 太阴圣皇体成就 太阳神体觉醒 太阴神体觉醒 太古魔土s 库洛牌祈愿s
我的股票 股市 股票详情 股票走势 打听天机s 执掌先天至宝s 执行寿元流逝 抹除至尊印记s 掌控生死 探索圣墟s 搜魂
收摄山河s 无相蜕生s 永恒改命s 混沌变幻s 混沌复制s 混沌演化s 炼妖融合s 沉迷圣墟s 法身探索圣墟s 法身沉迷圣墟s
狠人 狠人关系 狠人剧情 瞅瞅纳戒 纳戒丹药 纳戒功法 纳戒材料 纳戒盒子 纳戒草药 纳戒装备 纳戒道具 纳戒食材
破王成帝 神游S 神识共享天骄位置s 秘境结算 立下世愿s 花粉渡劫状态 苏灵 苏灵关系 苏灵剧情 超维改写命格s
超维改写天资s 超维改写时代s 超维改写灵根s 超维造物s 道途 降临 领取众生鱼谱奖励 黑皇传授阵道 黑皇关系
副本掉落s 法身清除沉迷记录 法身清除沉迷记录s 法穿梭s 熔炼灵宝s 探索仙遗宝地s 收取仙遗宝地s 查询遗落纳戒
求取位面线索 参悟先天禁制s 护持天地灵脉s 挑战守护灵s 立下道心s 任命 任命宗门弟子s 培养宗门弟子s 逐出
逐出师门 开宗立派 探索宗门秘境 沉迷宗门秘境 一键服用修为丹 一键服用天药 一键服用寿命丹 一键服用神药
一键服用血气丹 一键服用道心果 一键服用食材 切换称号s 更换称号s 称号列表 升级无尽至宝s 卸下无尽至宝s
装备无尽至宝s 参悟道碑s 劫境购买s 无尽购买s 无尽选择s 无尽下一层 退出无尽劫境 取消退出无尽轮回 确认退出无尽轮回
无尽轮回 轮回兑换s 轮回档案s 轮回选择s 劫境难度 取消重置万劫道碑 万象归一s 劫后选择s 星图定途s 星图建议s
星图情报s 勘石s 天师辨石s 对决选石s 购石s 源石坊对决s 源石坊帮助 源石坊外园 源石坊地字号 源石坊天字号
金银坊记录 为帝兵更名s 以雷劫洗礼帝兵 炼制 悬赏 补发职业等级 批量分解遗珍 洗劫图鉴 洗劫列表图鉴
更新公告s 预览练气皮肤s 上传练气皮肤s 问仙令帮助 彼岸状态 组队遨游时间长河 淬炼s 天地无极s 赐福s 挑选s
炼制s 服用s 收服s 解除s 参见s 参悟s 请安s 赠礼s 邀请s 挑战s 修炼s 突破s
复苏 偷菜 分配仙宠 十遣龙 百遣龙 十遣虎 百遣虎 职业等级 天意一刀 无尽 无尽挑战
""".split())

SKIP = set("""
上传纳戒皮肤 自选存档皮肤 上传练气皮肤 练气皮肤图鉴 预览练气皮肤
诸天调研问卷 诸天调研统计
""".split())

# 原版缺陷：照搬会崩或明显不合理，按"修正后移植"处理
DEFECT = set("""
破王成帝
""".split())

rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
for r in rows:
    c = r["cmd"]
    if c in SKIP:
        r["verdict"], r["confidence"] = "skip", "high"
    elif c in FRAG:
        r["verdict"], r["confidence"] = "frag", "high"
    elif c in ALIAS:
        r["verdict"], r["confidence"] = "alias", "high"
    elif c in DEFECT:
        r["verdict"], r["confidence"] = "alias", "medium"
    else:
        r["verdict"], r["confidence"] = "missing", "high"

# 组级修正：同一 reg 展开的成组命令统一判定
GROUP = {
    "一键取出": ("missing", "内景地分类取出"),
    "装备技能": ("missing", "战斗技能装配"),
    "卸下技能": ("missing", "战斗技能装配"),
    "神祇代行": ("missing", "代行补类"),
    "灵身代行": ("missing", "代行补类"),
    "寻宝分支": ("missing", "寻宝五分支"),
    "沉迷区域": ("missing", "位面沉迷子集"),
    "法身探索区域": ("missing", "区域子集"),
    "法身沉迷区域": ("missing", "区域子集"),
    "彼岸": ("missing", "远征层"),
}
for r in rows:
    c = r["cmd"]
    if c.startswith("一键取出"):
        r["verdict"], r["note"] = "missing", "内景地分类取出"
    elif any(c.startswith(p) for p in ("装备回血", "装备复活", "装备恢复", "装备生机", "装备防御",
                                       "卸下回血", "卸下复活", "卸下恢复", "卸下生机", "卸下防御")) or c == "卸下":
        r["verdict"], r["note"] = "missing", "战斗技能装配"
    elif c.startswith(("神祇代行", "灵身代行")):
        r["verdict"], r["note"] = "missing", "代行补类"
    elif c.startswith("寻宝") and c not in ("寻宝",):
        r["verdict"], r["note"] = "missing", "寻宝五分支"
    elif c.startswith("沉迷") and c not in ("沉迷圣墟s",):
        r["verdict"], r["note"] = "missing", "位面沉迷子集"
    elif c.startswith("法身探索") and c not in ("法身探索圣墟s", "法身清除沉迷记录"):
        r["verdict"], r["note"] = "missing", "区域子集"
    elif c.startswith("法身沉迷") and c not in ("法身沉迷圣墟s",):
        r["verdict"], r["note"] = "missing", "区域子集"
    elif c in ("取回彼岸行囊", "存放彼岸战利品", "建设前线营地", "强制撤离", "彼岸层级", "彼岸灾厄",
               "彼岸行囊", "抗击禁宝司", "救援彼岸修士", "斩灭彼岸魔主", "炼化彼岸魔主", "讨伐彼岸魔主",
               "迎战彼岸威胁", "推进区域战役", "进入区域远征", "远征撤离", "沧澜星图", "沧澜网页",
               "领取古文明战果", "领取彼岸战果", "领取彼岸远征战果", "返回沧澜界", "轰击成仙路",
               "探索大星", "观测大星", "锚定大星", "前往大星s"):
        r["verdict"], r["note"] = "missing", "彼岸远征层"

with OUT.open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

by_mod: dict[str, Counter] = defaultdict(Counter)
for r in rows:
    by_mod[r["module"]][r["verdict"]] += 1
total = Counter(r["verdict"] for r in rows)
print(f"总计 {len(rows)} 条:", dict(total))
print(f"\n{'模块':<28} {'missing':>8} {'alias':>7} {'frag':>6} {'skip':>6}")
for mod, c in sorted(by_mod.items(), key=lambda x: -x[1]["missing"]):
    print(f"{mod:<28} {c['missing']:>8} {c['alias']:>7} {c['frag']:>6} {c['skip']:>6}")
