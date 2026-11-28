# -*- coding: utf-8 -*-
"""按路线图阶段给 triage.csv 打 Phase 标签，输出汇总。"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "triage.csv"
OUT = HERE / "triage_summary.md"

P2_PREFIX = ("一键取出", "神祇代行", "灵身代行", "装备回血", "装备复活", "装备恢复", "装备生机",
             "装备防御", "卸下回血", "卸下复活", "卸下恢复", "卸下生机", "卸下防御")
P2_EXACT = {"回炉重造", "卸下"}

P3_PREFIX = ("无尽", "冲水堂", "聚宝堂", "柳神", "张五爷", "抽凡界", "抽灵界", "抽天地",
             "寻宝", "沉迷", "法身探索", "法身沉迷", "大宇宙")
P3_EXACT = {
    "加入摇光", "加入瑶池", "职位晋升", "脱离势力", "取消脱离势力", "确认脱离势力",
    "领取摇光俸禄", "领取瑶池俸禄", "开启剑云海秘库", "开启剑宫宝库",
    "万灵魔幡", "魔幡状态", "召唤魂奴", "斩断魂印", "进入万相魔冢", "天魔化生", "吞天魔功",
    "献祭魔石", "吞噬", "使用引灵仙符", "使用锁灵仙符", "保留引灵结果", "选择引灵结果",
    "前往禁地", "前往九天十地", "前往下界八域", "前往上苍之上", "前往遮天位面",
    "关闭大宇宙", "开放大宇宙", "进入大宇宙", "离开大宇宙", "大宇宙列表",
    "开启裂界", "关闭裂界", "关闭所有裂界", "裂界探索",
    "设置公告群", "移除公告群", "自动设置公告群", "称号列表",
    "仙府", "探索仙府", "剑云海选择", "神城兑换源石", "神城一键兑换源石",
    "升级纳戒", "升级内景地空间", "开辟内景地空间",
}

P4_PREFIX = ("彼岸", "兵字秘", "记忆", "虚天", "违禁品", "域外邪", "妖王", "天魔炼化",
             "天意一刀", "维度镇守", "大道至宝惊鸿")
P4_EXACT = {
    "取回彼岸行囊", "存放彼岸战利品", "建设前线营地", "强制撤离", "抗击禁宝司", "救援彼岸修士",
    "斩灭彼岸魔主", "炼化彼岸魔主", "讨伐彼岸魔主", "迎战彼岸威胁", "推进区域战役",
    "进入区域远征", "远征撤离", "沧澜星图", "沧澜网页", "领取古文明战果", "领取彼岸战果",
    "领取彼岸远征战果", "返回沧澜界", "轰击成仙路", "探索大星", "观测大星", "锚定大星",
    "月下观兵", "以器证兵", "参悟问仙古碑", "调查战端", "跟踪月灵公主", "追查蔡族",
    "辨认石山", "查看夺宝进度", "绝美仙子", "星神觐见", "六相冰封", "行者之旅",
    "关闭妖王", "开启妖王", "关闭天骄", "开启天骄", "救场黑暗动乱", "驾驭大成圣体尸骸",
    "组队时间长河", "加入时间长河队伍", "解散时间长河队伍", "退出时间长河队伍",
    "探索宗门秘境", "沉迷宗门秘境", "赏金榜", "清空赏金榜", "猎户转", "打造",
    "结束地脉引气", "结束寻源", "结束寻脉定源", "结束狩猎", "讨伐目标", "我的药效",
    "参悟大衍悟道丹配方", "装备图纸",
}


def phase_of(cmd: str) -> str:
    if cmd in P2_EXACT or cmd.startswith(P2_PREFIX):
        return "P2"
    if cmd in P3_EXACT or cmd.startswith(P3_PREFIX):
        return "P3"
    if cmd in P4_EXACT or cmd.startswith(P4_PREFIX):
        return "P4"
    return "P5"


rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
for r in rows:
    r["phase"] = phase_of(r["cmd"]) if r["verdict"] == "missing" else "-"

with SRC.open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

miss = [r for r in rows if r["verdict"] == "missing"]
cnt = Counter(r["phase"] for r in miss)
mods: dict[str, Counter] = defaultdict(Counter)
for r in miss:
    mods[r["phase"]][r["module"]] += 1

lines = ["# 分诊汇总（Phase 0.5 产出）", "",
         f"待判 {len(rows)} 条：missing {len(miss)} / alias "
         f"{sum(1 for r in rows if r['verdict'] == 'alias')} / frag "
         f"{sum(1 for r in rows if r['verdict'] == 'frag')} / skip "
         f"{sum(1 for r in rows if r['verdict'] == 'skip')}", "",
         "| 阶段 | 待实现条数 | 主要模块 |", "|---|---|---|"]
for p in ("P2", "P3", "P4", "P5"):
    top = "、".join(f"{m}({n})" for m, n in mods[p].most_common(5))
    lines.append(f"| {p} | {cnt[p]} | {top} |")
lines += ["", "> missing 合计 %d 条；Phase 1（战斗规则）为行为改造，不产生新命令，不计入本表。" % len(miss)]
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
