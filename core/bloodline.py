"""灵根觉醒·体质线（W8-B1a）：圣体 / 霸体 / 妖体 两阶觉醒。

原版：`apps/User/linggenjuexing.js` 1250 行（17 条指令）。

本批保留：
- **三体质各两阶**：小成（第 7 境起、两大秘境 ≥50%）→ 大成（第 15 境起、四大秘境圆满）
- **秘境完成度**（轮海 / 道宫 / 四极 / 化龙）：原版由 `#修炼圣体秘术` 提升，本移植改为
  **每次秘境寻宝 +3**（`#秘境寻宝` 结算后自动打磨），沿用同一四秘境口径
- **觉醒即替换灵根快照**：直接取 `data/item/灵根列表.json` 里的
  「小成·荒古圣体 / 大成·荒古圣体 / 小成·苍天霸体 / 大成·苍天霸体 / 天妖王体 / 天妖皇体」
  六行，走既有 `linggen.stats_of` 进装备聚合——与原版 `player.灵根 = {...}` 同语义，
  W7-4 的通用觉醒档位（0-3）保留不清零

shortcut：原版霸体/妖体的小成要吃【不灭霸血】/【天妖真血】血脉道具，本移植没有对应产出链，
统一改为「两大秘境 ≥50%」；至尊骨 / 仙骨 / 重瞳 / 往世乐土（真我觉醒、流萤觉醒）属 B1b，
本批未做；境界门槛用 realm_index 代理原版 mijinglevel_id（秘境等级）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SECRETS: tuple[str, ...] = ("轮海", "道宫", "四极", "化龙")
GRIND_PER_RUN = 3
GRIND_CAP = 100

# 体质线 → 两阶配置：(灵根表行名, 境界门槛 realm_index, 需达标秘境数, 达标线)
LINES: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "圣体": (
        {"row": "小成·荒古圣体", "realm": 6, "need": 2, "line": 50},
        {"row": "大成·荒古圣体", "realm": 14, "need": 4, "line": 100},
    ),
    "霸体": (
        {"row": "小成·苍天霸体", "realm": 6, "need": 2, "line": 50},
        {"row": "大成·苍天霸体", "realm": 14, "need": 4, "line": 100},
    ),
    "妖体": (
        {"row": "天妖王体", "realm": 6, "need": 2, "line": 50},
        {"row": "天妖皇体", "realm": 14, "need": 4, "line": 100},
    ),
}

LINE_LABEL = {"圣体": "荒古圣体", "霸体": "苍天霸体", "妖体": "天妖体"}
TYPE_MAP = {
    "圣体": "圣体", "小成圣体": "圣体", "大成圣体": "圣体",
    "霸体": "霸体", "小成霸体": "霸体", "大成霸体": "霸体",
    "妖体": "妖体", "小成妖体": "妖体", "大成妖体": "妖体",
}


def state_of(doc: Any) -> dict[str, Any]:
    raw = doc.ext.get("bloodline") if isinstance(getattr(doc, "ext", None), Mapping) else None
    st = dict(raw) if isinstance(raw, Mapping) else {}
    st.setdefault("line", "")
    st.setdefault("stage", 0)
    sec = st.get("secret")
    st["secret"] = {k: max(0, min(GRIND_CAP, int(dict(sec).get(k, 0) or 0)))
                    for k in SECRETS} if isinstance(sec, Mapping) else {k: 0 for k in SECRETS}
    return st


def set_state(doc: Any, st: Mapping[str, Any]) -> None:
    doc.ext["bloodline"] = dict(st)


def line_of(doc: Any) -> str:
    """从灵根快照的 type 反推体质线；不是三体质返回空串。"""
    snap = doc.ext.get("linggen")
    if not isinstance(snap, Mapping):
        return ""
    return TYPE_MAP.get(str(snap.get("type") or ""), "")


def progress(doc: Any) -> dict[str, int]:
    return dict(state_of(doc)["secret"])


def grind(doc: Any, amount: int = GRIND_PER_RUN) -> str:
    """秘境寻宝后打磨：补最低的一处秘境，返回提升的秘境名（满了返回空串）。"""
    st = state_of(doc)
    row = st["secret"]
    if all(row[k] >= GRIND_CAP for k in SECRETS):
        return ""
    low = min(SECRETS, key=lambda k: (row[k], -SECRETS.index(k)))
    row[low] = min(GRIND_CAP, row[low] + max(1, int(amount)))
    set_state(doc, st)
    return low


def _check(st: Mapping, row: Mapping, realm: int) -> tuple[bool, str]:
    if realm < int(row["realm"]):
        return False, f"需第 {int(row['realm']) + 1} 境以上（当前第 {realm + 1} 境）"
    hit = sum(1 for k in SECRETS if int(st["secret"][k]) >= int(row["line"]))
    if hit < int(row["need"]):
        detail = "、".join(f"{k}{int(st['secret'][k])}%" for k in SECRETS)
        return False, (f"需 {int(row['need'])} 处秘境达到 {int(row['line'])}%"
                       f"（现 {hit} 处；{detail}）")
    return True, ""


def status_text(doc: Any) -> str:
    st = state_of(doc)
    line = line_of(doc)
    stage = int(st.get("stage", 0) or 0)
    lines = ["【血脉·体质】"]
    if not line:
        lines.append("当前灵根不是圣体 / 霸体 / 妖体，无法走体质觉醒线。")
        lines.append("（可服天命轮回丹重新洗炼灵根）")
        return "\n".join(lines)
    lines.append(f"体质：{LINE_LABEL.get(line, line)}｜觉醒：{stage}/2 阶"
                 + ("（大成）" if stage >= 2 else ""))
    lines.append("秘境完成度：")
    for k in SECRETS:
        v = int(st["secret"][k])
        bar = "█" * (v // 10) + "░" * (10 - v // 10)
        lines.append(f"　{k}：{bar} {v}%")
    nxt = stage
    if nxt < 2:
        row = LINES[line][nxt]
        lines.append(f"下一阶【{row['row']}】：第 {int(row['realm']) + 1} 境起，"
                     f"{int(row['need'])} 处秘境达 {int(row['line'])}%")
        lines.append(f"提升：每次秘境 #秘境寻宝 自动打磨 +{GRIND_PER_RUN}%（补最低的一处）")
    else:
        lines.append("已至大成，体质线圆满。")
    return "\n".join(lines)


def awaken(doc: Any, table: Sequence[Mapping], expect: str = "") -> tuple[bool, str]:
    """按当前体质线推一阶；成功时替换灵根快照（保留通用觉醒档）。

    expect：指令指定的体质线（#圣体觉醒 等），与当前灵根不符时直接拒绝。
    """
    st = state_of(doc)
    line = line_of(doc)
    if not line:
        return False, "当前灵根不是圣体 / 霸体 / 妖体，无法觉醒。"
    if expect and line != expect:
        return False, (f"你的体质是【{LINE_LABEL.get(line, line)}】，"
                       f"不能走【{LINE_LABEL.get(expect, expect)}】觉醒线。")
    stage = int(st.get("stage", 0) or 0)
    if stage >= 2:
        return False, f"{LINE_LABEL.get(line, line)}已至大成，无需再觉醒。"
    row = LINES[line][stage]
    ok, why = _check(st, row, int(getattr(doc, "realm_index", 0) or 0))
    if not ok:
        return False, f"【{row['row']}·条件不足】{why}"
    target = next((r for r in table
                   if isinstance(r, Mapping) and str(r.get("name")) == str(row["row"])), None)
    if target is None:
        return False, f"灵根表缺少【{row['row']}】，请检查 data/item/灵根列表.json。"
    from . import linggen
    old = doc.ext.get("linggen") if isinstance(doc.ext.get("linggen"), Mapping) else {}
    snap = linggen.snapshot(target)
    snap["awaken"] = int(dict(old).get("awaken", 0) or 0)     # 保留 W7-4 通用觉醒档
    doc.ext["linggen"] = snap
    st["line"] = line
    st["stage"] = stage + 1
    set_state(doc, st)
    atk, dfn, hp, origin = linggen.stats_of(snap)
    return True, (
        f"【{row['row']}·觉醒】\n"
        f"血气冲霄，{LINE_LABEL.get(line, line)}由凡入圣！\n"
        f"灵根已换为【{snap.get('name')}】：修炼效率 ×{float(snap.get('eff', 1)):g}\n"
        f"四维：攻 +{atk:.0%}｜防 +{dfn:.0%}｜血 +{hp:.0%}｜生命本源 +{origin:,.0f} 气血\n"
        f"觉醒 {st['stage']}/2 阶。"
    )
