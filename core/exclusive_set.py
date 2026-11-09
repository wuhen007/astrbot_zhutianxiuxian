"""专属套装挑战（W13-F1）——原版 `apps/User/WanhuaTianmoSet.js` +
`model/wanhuaTianmoSetTrial.js`（万化天魔路）、`apps/User/TerminalGodDemonSet.js` +
`model/terminalGodDemonTrial.js`（终焉神魔路）、`model/exclusiveEquipmentSets.js`
（套装奖励）的纯函数移植。

原版语义：
- 万化天魔路：限【无相·万化天魔体】+ 权柄 ≥18（仙王级）。三阶段依次：
  #万相夺道（9 魔相，每关封印一项权柄）→ #无相蜕生 化万相|归无相（7 蜕，
  化万相 攻+25% 防-15%，归无相反之）→ #万灵幡祭（3 关，末关禁减免+禁复活）。
  敌力 scale 0.72+i*0.06 / 0.88+i*0.065 / 1.05+i*0.13；连续失败败拍：
  每 5 次 +10% 自身属性（上限 +30%）。奖励【万化】三件套。
- 终焉神魔路：限【终焉神魔体】+ 权柄 ≥18。#黄昏神国（13 旧神）→
  #太古魔土 吞噬魔血|保持本心（9 关，吞血回 25% 但侵蚀 +1、敌强 +2%/层）→
  #诸世归墟（6 个时间线自我）。奖励【终焉】三件套。

本移植（shortcut）：
- 无多阶段战斗引擎：每关一次判定聚合输出；敌力 scale 折算为逐关成功率
  `0.62 - 0.03×关序`；败拍折算为 `+3pp×连败`（上限 +9pp），阶段完成清零。
- 吞噬魔血：侵蚀折算后续关成功率 -1.5pp/层；保持本心：全程 -3pp。
- 套装三维乘区由装备/战斗系统承担，此处只发道具入纳戒（特殊装备表可后挂）。
- 邪道镇魂（魂印/魂奴/人傀/道果）已在 `core/motou.py` 接线（#冲击魂印 等）。
"""

from __future__ import annotations

import random
import time
from typing import Any, Mapping

from .player import PlayerDoc

EXT_KEY = "excl"

GATE_AUTH = 18
BASE_CHANCE = 0.62
RAGE_STEP = 0.03
RAGE_CAP = 0.09
CORRUPT_STEP = 0.015

WANHUA_STAGES: tuple[tuple[str, int, str], ...] = (
    ("万相夺道", 9, "【万化】万相天魔刃"),
    ("无相蜕生", 7, "【万化】无相魔神袍"),
    ("万灵幡祭", 3, "【万化】万灵魔幡"),
)
ZHONGyan_STAGES: tuple[tuple[str, int, str], ...] = (
    ("黄昏神国", 13, "【终焉】诸神黄昏"),
    ("太古魔土", 9, "【终焉】神魔葬天衣"),
    ("诸世归墟", 6, "【终焉】万劫归墟轮"),
)
WANHUA_NAME = "万化天魔路"
ZHONGYAN_NAME = "终焉神魔路"


def _defaults() -> dict[str, Any]:
    return {"wanhua": 0, "zhongyan": 0, "rage": 0, "corrupt": 0, "wins": 0}


def save(doc: Any, st: Mapping[str, Any]) -> None:
    ext = getattr(doc, "ext", None)
    if isinstance(ext, dict):
        ext[EXT_KEY] = dict(st)


def state_of(doc: Any) -> dict[str, Any]:
    ext = getattr(doc, "ext", None)
    raw = ext.get(EXT_KEY) if isinstance(ext, dict) else None
    st = _defaults()
    if isinstance(raw, dict):
        st.update(raw)
    for k in ("wanhua", "zhongyan", "rage", "corrupt", "wins"):
        st[k] = int(st.get(k, 0) or 0)
    save(doc, st)
    return st


def _authority(doc: Any) -> int:
    try:
        from . import authority as _auth
        return int(_auth.authority_of(doc))
    except Exception:
        return max(int(getattr(doc, "realm_index", 0) or 0),
                   int(getattr(doc, "physique_index", 0) or 0))


def _lg_name(doc: Any) -> str:
    lg = (getattr(doc, "ext", {}) or {}).get("linggen")
    return str(lg.get("name") or "") if isinstance(lg, dict) else ""


def _gate(doc: Any, line_name: str) -> str | None:
    if _authority(doc) < GATE_AUTH:
        return f"{line_name}需权柄 ≥{GATE_AUTH}（仙王级），当前 {_authority(doc)}。"
    if line_name == WANHUA_NAME and "万化天魔" not in _lg_name(doc):
        return "万化天魔路限【无相·万化天魔体】行走。"
    if line_name == ZHONGYAN_NAME and "终焉神魔" not in _lg_name(doc):
        return "终焉神魔路限【终焉神魔体】行走。"
    return None


def challenge(doc: PlayerDoc, line_name: str, stage_arg: str, now: float | None = None,
              rng: random.Random | None = None) -> tuple[bool, str, dict[str, int]]:
    """#万相夺道 / #无相蜕生 / #万灵幡祭 / #黄昏神国 / #太古魔土 / #诸世归墟。"""
    now = time.time() if now is None else float(now)
    rng = rng or random.Random()
    line_name = (line_name or "").strip()
    stages = WANHUA_STAGES if line_name == WANHUA_NAME else ZHONGyan_STAGES
    err = _gate(doc, line_name)
    if err:
        return False, err, {}
    st = state_of(doc)
    done = st["wanhua"] if line_name == WANHUA_NAME else st["zhongyan"]
    if done >= len(stages):
        return False, f"【{line_name}】三阶段已全部铸成——套装在身，魔威自显。", {}
    stage_name, rounds, reward = stages[done]
    stage_arg = (stage_arg or "").strip()
    if line_name == WANHUA_NAME and stage_name == "无相蜕生" and stage_arg not in ("化万相", "归无相"):
        return False, "用法：#无相蜕生 化万相 / #无相蜕生 归无相。", {}
    if line_name == ZHONGYAN_NAME and stage_name == "太古魔土" and stage_arg not in ("吞噬魔血", "保持本心"):
        return False, "用法：#太古魔土 吞噬魔血 / #太古魔土 保持本心。", {}

    log: list[str] = []
    cleared = 0
    for i in range(rounds):
        chance = BASE_CHANCE - 0.03 * i + min(RAGE_CAP, st["rage"] * RAGE_STEP)
        if line_name == ZHONGYAN_NAME and stage_name == "太古魔土":
            if stage_arg == "吞噬魔血":
                chance -= CORRUPT_STEP * (st["corrupt"] + i)
            else:
                chance -= 0.03
        chance = max(0.08, min(0.95, chance))
        if rng.random() < chance:
            cleared += 1
            log.append(f"✔ 第{i + 1}关（{chance:.0%}）")
        else:
            log.append(f"✘ 第{i + 1}关（{chance:.0%}）")
            break
    st["rage"] = 0 if cleared == rounds else int(st["rage"]) + 1
    if cleared == rounds:
        delta = {reward: 1}
        st["wins"] = int(st["wins"]) + 1
        if line_name == WANHUA_NAME:
            st["wanhua"] = done + 1
        else:
            st["zhongyan"] = done + 1
            if stage_name == "太古魔土" and stage_arg == "吞噬魔血":
                st["corrupt"] = int(st["corrupt"]) + rounds
        save(doc, st)
        full = "三阶段皆成——套装共鸣，魔音贯诸天！" if done + 1 == len(stages) else ""
        log_text = "\n".join(log)
        return True, (f"≡≡≡ {line_name} · {stage_name} 铸成 ≡≡≡\n{log_text}\n"
                      f"获得 {reward}！{full}"), delta
    save(doc, st)
    log_text = "\n".join(log)
    return True, (f"【{line_name} · {stage_name}】魔关未破——{cleared}/{rounds} 关。\n"
                  f"{log_text}\n败拍蓄力：连败 {st['rage']} 次（下次挑战成功率 +"
                  f"{min(RAGE_CAP, st['rage'] * RAGE_STEP):.0%}）。"), {}


def panel(doc: Any) -> str:
    st = state_of(doc)
    w_rows = []
    for idx, (sname, rounds, reward) in enumerate(WANHUA_STAGES):
        mark = "✔" if st["wanhua"] > idx else ("▶" if st["wanhua"] == idx else "·")
        w_rows.append(f"{mark} {sname}（{rounds} 关）→ {reward}")
    z_rows = []
    for idx, (sname, rounds, reward) in enumerate(ZHONGyan_STAGES):
        mark = "✔" if st["zhongyan"] > idx else ("▶" if st["zhongyan"] == idx else "·")
        z_rows.append(f"{mark} {sname}（{rounds} 关）→ {reward}")
    return "\n".join([
        "--- 专属套装挑战 ---",
        "【万化天魔路】限无相·万化天魔体：", *w_rows,
        "【终焉神魔路】限终焉神魔体：", *z_rows,
        f"败拍连败 {st['rage']} 次（+{min(RAGE_CAP, st['rage'] * RAGE_STEP):.0%}）"
        f"｜魔土侵蚀 {st['corrupt']} 层｜铸成 {st['wins']} 件",
        "指令：#万相夺道 / #无相蜕生 化万相|归无相 / #万灵幡祭 / "
        "#黄昏神国 / #太古魔土 吞噬魔血|保持本心 / #诸世归墟",
    ])
