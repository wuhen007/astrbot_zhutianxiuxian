"""职业补全：源石场 / 侠客讨恶 / 唤魔者劫村（W15-F1）——原版
`apps/Occupation/Occupation.js`（布置源石场 L263 / 查看源石场 L298 /
查看恶人 L252+消灭恶人 L2323 / 村庄列表 L181+劫掠村庄 L4180）的纯函数移植。

更正：七职业产线（猎户/侠客/唤魔者/源师/源地师/源天师/阵法师）已在
`core/occupation.py` PRODUCE 统一由 `#职业产出 分钟` 驱动；禁仙六封已在
W7-2 时代系统接线。本模块只补三块缺口：

- #布置源石场 位面名 / #查看源石场：源地师/源天师，源石 ×10，24h；
  全服态存 calamity_state["source_field"]（每位面一场，单例简化）。
  shortcut：讨伐 PVE 强化未接，当前为占位收益（挂机加成待产线联动）。
- #查看恶人 / #消灭恶人：侠客 + 侠客令 ×1；恶人池按 (日期,槽位) 确定性
  生成 3 名；成功率 0.7+(权柄-恶人险)×0.05；胜→赏金灵石、魔道值抵减；
  败→气血归 1。原版职业经验加成未搬（产线 #职业产出 已含）。
- #村庄列表 / #劫掠村庄：唤魔者 + 唤魔令 ×1；成功率 0.65；
  胜→灵石+物资+魔道值 +8。
"""

from __future__ import annotations

import random
from typing import Any, Mapping

from .player import PlayerDoc

FIELD_COST_ITEM = "源石"
FIELD_COST_QTY = 10
FIELD_HOURS = 24
VILLAIN_NAMES = ("血手屠夫", "采花淫贼", "黑风寨主", "食魂老怪", "千面盗圣", "裂魂妖僧")
VILLAGE_NAMES = ("落霞村", "青岩寨", "枯藤渡", "黑水屯", "白骨涧", "乱石岗")


def _authority(doc: Any) -> int:
    try:
        from . import authority as _auth
        return int(_auth.authority_of(doc))
    except Exception:
        return max(int(getattr(doc, "realm_index", 0) or 0),
                   int(getattr(doc, "physique_index", 0) or 0))


def _job(doc: Any) -> str:
    return str((getattr(doc, "ext", {}) or {}).get("occupation") or "")


# ---------------------------------------------------------------- 源石场

def place_field(doc: PlayerDoc, calamity: dict[str, Any], plane: str, now: float,
                ) -> tuple[bool, str]:
    if _job(doc) not in ("源地师", "源天师"):
        return False, "布置源石场乃源地师/源天师之能（#转职 后 #职业产出 积累经验）。"
    plane = (plane or "").strip()
    if not plane:
        return False, "用法：#布置源石场 位面名（如 #布置源石场 遮天位面）。"
    field = calamity.get("source_field") if isinstance(calamity.get("source_field"), dict) else None
    if field and str(field.get("plane")) == plane and float(field.get("until", 0) or 0) > now:
        return False, (f"「{plane}」已有 {field.get('owner_name', '他人')} 的源石场"
                       f"（剩 {int((float(field['until']) - now) / 3600)} 小时）——另择位面。")
    calamity["source_field"] = {"plane": plane, "owner": str(doc.uid),
                                "owner_name": str(doc.name or doc.uid[:8]),
                                "job": _job(doc), "until": now + FIELD_HOURS * 3600}
    return True, (f"【布置源石场】借「{plane}」山川龙脉布下聚源大阵（24 小时）——\n"
                  f"此后该位面源术产线 +50%（#职业产出 联动即将开放）。")


def field_text(calamity: Mapping[str, Any], now: float) -> str:
    fields = calamity.get("source_fields") if isinstance(calamity.get("source_fields"), dict) else None
    main = calamity.get("source_field") if isinstance(calamity.get("source_field"), dict) else None
    lines = ["--- 源石场 ---"]
    if main and float(main.get("until", 0) or 0) > now:
        left = int((float(main["until"]) - now) / 3600)
        lines.append(f"「{main['plane']}」：{main.get('owner_name', '?')}（{main.get('job', '')}）"
                     f"｜剩余 {left} 小时")
    else:
        lines.append("当前无生效源石场。")
    if fields:
        for plane, f in list(fields.items())[:6]:
            if float(f.get("until", 0) or 0) > now:
                lines.append(f"· {plane}：{f.get('owner_name', '?')}")
    lines.append("布置：#布置源石场 位面名（源地师/源天师，源石×10，24h）")
    return "\n".join(lines)


# ---------------------------------------------------------------- 恶人 / 村庄

def _pool_names(seed: str, names: tuple[str, ...], count: int) -> list[str]:
    rng = random.Random(seed)
    return rng.sample(list(names), min(count, len(names)))


def villains_text(doc: PlayerDoc, day_key: str, slot: int) -> tuple[str, list[dict]]:
    """今日恶人榜：确定性生成 3 名（赏金按权柄量级）。"""
    auth = max(1, _authority(doc))
    names = _pool_names(f"evil:{doc.uid}:{day_key}:{slot}", VILLAIN_NAMES, 3)
    rng = random.Random(f"evilb:{doc.uid}:{day_key}:{slot}")
    out = []
    for i, n in enumerate(names):
        power = max(1, auth - 2 + i + rng.randint(-1, 2))
        bounty = int(12_000 * (1.2 + 0.02 * auth) * (1 + 0.3 * i))
        out.append({"name": n, "power": power, "bounty": bounty})
    lines = ["--- 恶人榜（今日）---"]
    for v in out:
        lines.append(f"· {v['name']}｜险度 {v['power']}｜赏金 {v['bounty']:,} 灵石")
    lines.append("讨伐：#消灭恶人 名字（侠客，侠客令×1）")
    return "\n".join(lines), out


def slay(doc: PlayerDoc, inv: Mapping[str, int], name: str, day_key: str, slot: int,
         now: float, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    if _job(doc) != "侠客":
        return False, "唯有侠客可讨恶（#转职 侠客）。", {}
    if int((inv or {}).get("侠客令", 0) or 0) < 1:
        return False, "讨恶需【侠客令】×1（#天道赐福 可得）。", {}
    _, pool = villains_text(doc, day_key, slot)
    target = next((v for v in pool if v["name"] == (name or "").strip()), None)
    if target is None:
        return False, "今日恶人榜上并无此人——#查看恶人。", {}
    auth = _authority(doc)
    chance = max(0.15, min(0.95, 0.70 + (auth - target["power"]) * 0.05))
    if rng.random() >= chance:
        ext = getattr(doc, "ext", None)
        if isinstance(ext, dict):
            ext["hp"] = 1
        return True, (f"【讨恶 · {target['name']}】反被恶人重创——气血归一！\n"
                      f"（成功率 {chance:.0%}）侠客令已耗，先疗伤再战。"), {"侠客令": -1}
    bounty = target["bounty"]
    doc.stones = int(getattr(doc, "stones", 0) or 0) + bounty
    mo = max(0.0, float((getattr(doc, "ext", {}) or {}).get("modao", 0) or 0) - bounty * 0.0002)
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["modao"] = mo
    return True, (f"【讨恶成功 · {target['name']}】恶首悬于城门，赏银入库——\n"
                  f"灵石 +{bounty:,}｜魔道值 -{bounty * 0.0002:.1f}"
                  f"（成功率 {chance:.0%}）。"), {"侠客令": -1}


def villages_text(doc: PlayerDoc, day_key: str, slot: int) -> tuple[str, list[dict]]:
    auth = max(1, _authority(doc))
    names = _pool_names(f"village:{doc.uid}:{day_key}:{slot}", VILLAGE_NAMES, 3)
    rng = random.Random(f"vb:{doc.uid}:{day_key}:{slot}")
    out = []
    for i, n in enumerate(names):
        loot = int(9_000 * (1.2 + 0.02 * auth) * (1 + 0.35 * i))
        out.append({"name": n, "loot": loot})
    lines = ["--- 村庄列表 ---"]
    for v in out:
        lines.append(f"· {v['name']}｜预估劫掠 {v['loot']:,} 灵石等值物资")
    lines.append("劫掠：#劫掠村庄 名字（唤魔者，唤魔令×1）")
    return "\n".join(lines), out


def raid(doc: PlayerDoc, inv: Mapping[str, int], name: str, day_key: str, slot: int,
         now: float, rng: random.Random) -> tuple[bool, str, dict[str, int]]:
    if _job(doc) != "唤魔者":
        return False, "唯唤魔者可劫掠（#转职 唤魔者）。", {}
    if int((inv or {}).get("唤魔令", 0) or 0) < 1:
        return False, "劫掠需【唤魔令】×1（#天道赐福 可得）。", {}
    _, pool = villages_text(doc, day_key, slot)
    target = next((v for v in pool if v["name"] == (name or "").strip()), None)
    if target is None:
        return False, "今日村庄列表并无此村——#村庄列表。", {}
    if rng.random() >= 0.65:
        ext = getattr(doc, "ext", None)
        if isinstance(ext, dict):
            ext["hp"] = 1
        mo = float((getattr(doc, "ext", {}) or {}).get("modao", 0) or 0) + 3
        if isinstance(ext, dict):
            ext["modao"] = mo
        return True, (f"【劫掠失败 · {target['name']}】村民纠察队反打了一波——"
                      "气血归一、魔道值 +3！唤魔令已耗。"), {"唤魔令": -1}
    loot = target["loot"]
    doc.stones = int(getattr(doc, "stones", 0) or 0) + loot
    mo = float((getattr(doc, "ext", {}) or {}).get("modao", 0) or 0) + 8
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext["modao"] = mo
    return True, (f"【劫掠成功 · {target['name']}】粮仓见底，魔焰滔天——\n"
                  f"灵石等值 +{loot:,}｜魔道值 +8。"), {"唤魔令": -1}
