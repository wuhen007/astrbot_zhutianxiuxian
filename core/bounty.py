"""侠客赏金线 / 江湖传闻（W24-F2）——原版 Occupation.js 悬赏系 +
UserHome.js 江湖传闻的纯函数移植。

- #悬赏目标：确定性生成 3 名悬赏对象（赏金随权柄），24h 刷新。
- #刺杀目标 名：需侠客 + 侠客令 ×1；成功获赏金，失败气血归一。
- #江湖传闻：每日随机 3 条（文案 flavor，无实际效果）。
- shortcut：赏金榜（全服排行）未搬；刺杀与讨恶共享冷却。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc

BOUNTY_NAMES = ("血手人屠", "夺魄书生", "九幽妖僧", "碎骨狂魔", "千面贼王", "焚天老祖")
RUMORS = (
    "听说有人在雾海市看到了已经死去的宗主。",
    "灵市丹鼎阁的股价昨天翻了一倍——有人提前知道消息。",
    "上古战场又出宝物了，据说连大能都去凑热闹。",
    "有人在凡间捡到了一枚戒指，里面的老爷爷教他修炼。",
    "万宝楼掌柜失踪了三天，回来后什么都不说。",
    "天骄榜第一的金翅小鹏王又突破了，赏金翻了一倍。",
    "有一对道侣在世界树下双修，被巡界司罚款了。",
    "听说五色祭坛可以在不记坐标的情况下去遮天。",
    "有人在无尽劫境里遇见了上一世的自己。",
    "某宗门的护山神兽半夜偷偷去隔壁宗门偷菜。",
)


def bounty_pool(uid: str, day_key: str, auth: int) -> list[dict[str, Any]]:
    """确定性生成 3 名悬赏对象（赏金随权柄增长）。"""
    rng = random.Random(f"bounty:{uid}:{day_key}")
    names = rng.sample(list(BOUNTY_NAMES), min(3, len(BOUNTY_NAMES)))
    out = []
    for i, n in enumerate(names):
        power = max(1, auth - 2 + i + rng.randint(-1, 1))
        bounty = int(15_000 * (1.2 + 0.02 * auth) * (1 + 0.4 * i))
        out.append({"name": n, "power": power, "bounty": bounty})
    return out


def bounty_text(doc: PlayerDoc, day_key: str, slot: int) -> tuple[str, list[dict]]:
    auth = max(1, int(getattr(doc, "realm_index", 0) or 0))
    pool = bounty_pool(str(doc.uid), day_key, auth)
    lines = ["--- 悬赏榜（今日）---"]
    for v in pool:
        lines.append(f"· {v['name']}｜险度 {v['power']}｜赏金 {v['bounty']:,} 灵石")
    lines.append("刺杀：#刺杀目标 名字（侠客，侠客令×1）")
    return "\n".join(lines), pool


def assassinate(doc: PlayerDoc, inv: Mapping[str, int], name: str,
                day_key: str, slot: int, now: float, rng: random.Random,
                ) -> tuple[bool, str, dict[str, int]]:
    """#刺杀目标 名：侠客 + 侠客令，胜获赏金，败气血归一。"""
    if doc.ext.get("occupation") != "侠客":
        return False, "唯有侠客可刺杀（#转职 侠客）。", {}
    if int((inv or {}).get("侠客令", 0) or 0) < 1:
        return False, "刺杀需【侠客令】×1。", {}
    auth = max(1, int(getattr(doc, "realm_index", 0) or 0))
    pool = bounty_pool(str(doc.uid), day_key, auth)
    target = next((v for v in pool if v["name"] == (name or "").strip()), None)
    if target is None:
        return False, "今日悬赏榜上并无此人——#悬赏目标。", {}
    chance = max(0.15, min(0.95, 0.60 + (auth - target["power"]) * 0.05))
    if rng.random() >= chance:
        ext = getattr(doc, "ext", None)
        if isinstance(ext, dict):
            ext["hp"] = 1
        return True, (f"【刺杀失败 · {target['name']}】对方早有防备——气血归一！"
                      f"（成功率 {chance:.0%}）侠客令已耗。"), {"侠客令": -1}
    bounty = target["bounty"]
    doc.stones = int(getattr(doc, "stones", 0) or 0) + bounty
    return True, (f"【刺杀成功 · {target['name']}】暗影中的一刀终结了罪恶——\n"
                  f"灵石 +{bounty:,}（成功率 {chance:.0%}）。"), {"侠客令": -1}


def rumors_text(day_key: str, rng_seed: str = "") -> str:
    rng = random.Random(f"rumor:{day_key}:{rng_seed}")
    picks = rng.sample(list(RUMORS), min(3, len(RUMORS)))
    return "\n".join(["--- 江湖传闻 ---"] + [f"· {r}" for r in picks])
