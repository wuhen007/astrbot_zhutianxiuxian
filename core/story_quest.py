"""可移植隐藏支线：何为他人嫁衣（原版任务 1）。"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

TASK_ONE = 1
TASK_ONE_NAME = "何为他人嫁衣"
TASK_ONE_ITEM = "华云飞的执念"
TASK_ONE_TECHNIQUE = "吞天魔功"
TASK_ONE_SKILLS = ("斩天道", "星耀天地", "十方皆杀")
TASK_TWO = 2
TASK_TWO_NAME = "重走大帝路"
TASK_TWO_ITEM = "王腾的执念"
TASK_THREE = 3
TASK_THREE_NAME = "异域追杀"
TASK_THREE_ITEM = "跨界追杀令"
REWARD_CLAIMS_KEY = "支线任务奖励领取记录"


def _legacy(doc: Any, create: bool = False) -> dict | None:
    ext = getattr(doc, "ext", None)
    if not isinstance(ext, dict):
        return None
    value = ext.get("legacy_source")
    if not isinstance(value, dict) and create:
        value = ext["legacy_source"] = {}
    return value if isinstance(value, dict) else None


def active_ids(doc: Any) -> list[int]:
    legacy = _legacy(doc)
    tasks = legacy.get("支线任务") if legacy else None
    if not isinstance(tasks, list):
        return []
    out = []
    for value in tasks:
        try:
            task_id = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if task_id not in out:
            out.append(task_id)
    return out


def completed_record(doc: Any, task_id: int = TASK_ONE) -> dict | None:
    legacy = _legacy(doc)
    records = legacy.get("支线任务完成记录") if legacy else None
    if not isinstance(records, Mapping):
        return None
    row = records.get(task_id, records.get(str(task_id)))
    return dict(row) if isinstance(row, Mapping) else None


def is_active(doc: Any, task_id: int = TASK_ONE) -> bool:
    return int(task_id) in active_ids(doc)


def is_completed(doc: Any, task_id: int = TASK_ONE) -> bool:
    return completed_record(doc, task_id) is not None


def activate_huayunfei(doc: Any) -> tuple[bool, str]:
    legacy = _legacy(doc, create=True)
    if legacy is None:
        return False, "支线任务档案无法建立。"
    if is_completed(doc, TASK_ONE):
        return False, "何为他人嫁衣已完成，无需再次触发。"
    if is_active(doc, TASK_ONE):
        return False, "你已与华云飞的执念产生过因果，无法再次触发。"
    tasks = legacy.get("支线任务")
    if not isinstance(tasks, list):
        tasks = legacy["支线任务"] = []
    progress = legacy.get("支线任务进度")
    if not isinstance(progress, dict):
        progress = legacy["支线任务进度"] = {}
    tasks.append(TASK_ONE)
    progress[str(TASK_ONE)] = {"阶段": 1}
    return True, (
        "【隐藏任务触发：何为他人嫁衣】\n\n"
        "你捏碎了那枚执念结晶，刹那间，一股不甘的意志冲天而起！\n"
        "恍惚间，你看到了白衣胜雪的青年，独立于星峰之巅，眼中满是不甘。\n\n"
        "『我华云飞，一生不弱于人，为何要沦为他人嫁衣？』\n\n"
        "面对狠人一脉的宿命，你必须做出最终选择：\n"
        "· #选择支线1选项1 继承执念（需已学《吞天魔功》）\n"
        "· #选择支线1选项2 斩断因果，走出自己的道。")


def detail_huayunfei(doc: Any) -> str:
    if is_completed(doc, TASK_ONE):
        record = completed_record(doc, TASK_ONE) or {}
        choice = int(record.get("选择", 0) or 0)
        label = "继承执念" if choice == 1 else "斩断因果" if choice == 2 else "已完成"
        return f"【{TASK_ONE_NAME}】已完成｜选择：{label}。"
    if not is_active(doc, TASK_ONE):
        return f"你未接取【{TASK_ONE_NAME}】；使用「{TASK_ONE_ITEM}」触发。"
    return (f"【{TASK_ONE_NAME}】阶段 1/1：面对狠人一脉的宿命，做出最终选择。\n"
            f"选项1：继承执念（需已学《{TASK_ONE_TECHNIQUE}》）。\n"
            "选项2：斩断因果，获得潜力、道心与功法。\n"
            "发送 #选择支线1选项1 或 #选择支线1选项2。")


def choose_huayunfei(doc: Any, choice: int, root_snapshot: Mapping | None = None,
                      avatar_loaded: bool = False, now: float | None = None) -> tuple[bool, str]:
    if choice not in (1, 2):
        return False, "选项只能是 1 或 2。"
    if is_completed(doc, TASK_ONE):
        return False, "何为他人嫁衣已完成，奖励不会重复领取。"
    if not is_active(doc, TASK_ONE):
        return False, "你尚未接取何为他人嫁衣；请先使用「华云飞的执念」。"
    ext = doc.ext
    if choice == 1 and avatar_loaded:
        return False, "当前正装载诸天化身，请先发送「#装载化身 本源」，再继承支线灵根。"
    if choice == 1:
        techniques = ext.get("gongfa") if isinstance(ext.get("gongfa"), list) else []
        legacy = _legacy(doc) or {}
        old_techniques = legacy.get("学习的功法") if isinstance(legacy.get("学习的功法"), list) else []
        if TASK_ONE_TECHNIQUE not in techniques and TASK_ONE_TECHNIQUE not in old_techniques:
            return False, ("【选择失败】你想继承吞天魔功的传承，却发现从未修习过这门无上魔功。\n"
                           "『未曾入门，岂敢妄谈继承？』华云飞的执念在你面前消散。\n"
                           f"需要先学会《{TASK_ONE_TECHNIQUE}》，本次选择未结算，可再选择。")
        if not isinstance(root_snapshot, Mapping):
            return False, "灵根数据表中缺少【魔胎仙体】，未结算任务奖励。"

    legacy = _legacy(doc, create=True)
    if legacy is None:
        return False, "支线任务档案无法建立。"
    claims = legacy.get(REWARD_CLAIMS_KEY)
    if not isinstance(claims, dict):
        claims = legacy[REWARD_CLAIMS_KEY] = {}
    claim_key = f"zhixian:{TASK_ONE}:choice:{choice}"
    if not claims.get(claim_key):
        if choice == 1:
            ext["linggen"] = dict(root_snapshot or {})
            from . import motou
            state = motou.state_of(doc)
            state["modao"] = float(state.get("modao", 0) or 0) + 100
            ext["evil"] = state
            ext["modao"] = state["modao"]
        else:
            ext["potential"] = max(0, int(float(ext.get("potential", 0) or 0))) + 50
            from .items import DAOXIN_CAP
            ext["daoxin"] = min(DAOXIN_CAP, max(0, int(ext.get("daoxin", 0) or 0)) + 30)
            techniques = ext.get("gongfa")
            if not isinstance(techniques, list):
                techniques = ext["gongfa"] = []
            for name in TASK_ONE_SKILLS:
                if name not in techniques:
                    techniques.append(name)
            old_techniques = legacy.get("学习的功法")
            if isinstance(old_techniques, list):
                for name in TASK_ONE_SKILLS:
                    if name not in old_techniques:
                        old_techniques.append(name)
        claims[claim_key] = {"amount": 1, "claimedAt": float(now if now is not None else time.time())}

    from . import life_source
    life_source.reset_to_root_base(doc)
    tasks = legacy.get("支线任务")
    if isinstance(tasks, list):
        tasks[:] = [value for value in tasks if str(value) != str(TASK_ONE)]
    progress = legacy.get("支线任务进度")
    if isinstance(progress, dict):
        progress.pop(TASK_ONE, None)
        progress.pop(str(TASK_ONE), None)
    records = legacy.get("支线任务完成记录")
    if not isinstance(records, dict):
        records = legacy["支线任务完成记录"] = {}
    records[str(TASK_ONE)] = {
        "完成时间": float(now if now is not None else time.time()),
        "选择": choice, "奖励状态": "已领取",
    }
    if choice == 1:
        message = ("【选择：继承执念】吞天魔功自行运转，你将华云飞的不甘纳入神魂，"
                   "获得灵根【魔胎仙体】与魔道值 +100。")
    else:
        message = ("【选择：斩断因果】华云飞的执念化作光雨。"
                   "仙道潜力 +50、道心 +30，并领悟《斩天道》《星耀天地》《十方皆杀》。")
    return True, message


def activate_wangteng(doc: Any) -> tuple[bool, str]:
    legacy = _legacy(doc, create=True)
    if legacy is None:
        return False, "支线任务档案无法建立。"
    if is_completed(doc, TASK_TWO):
        return False, "重走大帝路已完成，无需再次触发。"
    if is_active(doc, TASK_TWO):
        return False, "大帝之路已启，无需重复触发。"
    tasks = legacy.get("支线任务")
    if not isinstance(tasks, list):
        tasks = legacy["支线任务"] = []
    progress = legacy.get("支线任务进度")
    if not isinstance(progress, dict):
        progress = legacy["支线任务进度"] = {}
    tasks.append(TASK_TWO)
    progress[str(TASK_TWO)] = {"阶段": 1}
    return True, (
        "【隐藏任务触发：重走大帝路】\n\n"
        "执念破碎的刹那，一道霸绝天地的意志撕裂虚空而来！\n"
        "你看到了背负天帝圣剑的紫衣青年，乱古大帝的传承者终究未能成帝。\n"
        "王腾的执念在识海中咆哮：『我不甘！重活一世，我必成帝！』\n\n"
        "选择一：觉醒武道天眼（道心 500、元神仙台级）。\n"
        "选择二：不继承王腾执念，获得潜力、道心与乱古帝符。\n"
        "发送 #选择支线2选项1 或 #选择支线2选项2。")


def detail_wangteng(doc: Any) -> str:
    if is_completed(doc, TASK_TWO):
        record = completed_record(doc, TASK_TWO) or {}
        choice = int(record.get("选择", 0) or 0)
        label = "觉醒武道天眼" if choice == 1 else "不继承王腾执念" if choice == 2 else "已完成"
        return f"【{TASK_TWO_NAME}】已完成｜选择：{label}。"
    if not is_active(doc, TASK_TWO):
        return f"你未接取【{TASK_TWO_NAME}】；使用「{TASK_TWO_ITEM}」触发。"
    return (f"【{TASK_TWO_NAME}】阶段 1/1。\n"
            "选项1：道心达到 500 且元神达到仙台级，觉醒武道天眼与乱古战意。\n"
            "选项2：不继承执念，获得潜力 +50、道心 +50、乱古帝符×1。\n"
            "发送 #选择支线2选项1 或 #选择支线2选项2。")


def choose_wangteng(doc: Any, choice: int, now: float | None = None) -> tuple[bool, str, dict[str, int]]:
    if choice not in (1, 2):
        return False, "选项只能是 1 或 2。", {}
    if is_completed(doc, TASK_TWO):
        return False, "重走大帝路已完成，奖励不会重复领取。", {}
    if not is_active(doc, TASK_TWO):
        return False, "你尚未接取重走大帝路；请先使用「王腾的执念」。", {}
    if choice == 1:
        from . import yuanshen
        daoxin = max(0, int(doc.ext.get("daoxin", 0) or 0))
        spirit_level = yuanshen.level_of(doc)
        if daoxin < 500:
            return False, f"道心不足，觉醒武道天眼需达到 500（当前 {daoxin}）。", {}
        if spirit_level is None or spirit_level < 1:
            return False, "元神境界不足，觉醒武道天眼需达到仙台级。", {}

    legacy = _legacy(doc, create=True)
    if legacy is None:
        return False, "支线任务档案无法建立。", {}
    claims = legacy.get(REWARD_CLAIMS_KEY)
    if not isinstance(claims, dict):
        claims = legacy[REWARD_CLAIMS_KEY] = {}
    claim_key = f"zhixian:{TASK_TWO}:choice:{choice}"
    items: dict[str, int] = {}
    before = max(0, int(doc.ext.get("daoxin", 0) or 0))
    if not claims.get(claim_key):
        if choice == 1:
            doc.ext["乱古战意"] = 1
            doc.ext["武道天眼"] = 1
        else:
            doc.ext["potential"] = max(0, int(doc.ext.get("potential", 0) or 0)) + 50
            from .items import DAOXIN_CAP
            doc.ext["daoxin"] = min(DAOXIN_CAP, before + 50)
            items["乱古帝符"] = 1
        claims[claim_key] = {"amount": 1, "claimedAt": float(now if now is not None else time.time())}

    tasks = legacy.get("支线任务")
    if isinstance(tasks, list):
        tasks[:] = [value for value in tasks if str(value) != str(TASK_TWO)]
    progress = legacy.get("支线任务进度")
    if isinstance(progress, dict):
        progress.pop(TASK_TWO, None)
        progress.pop(str(TASK_TWO), None)
    records = legacy.get("支线任务完成记录")
    if not isinstance(records, dict):
        records = legacy["支线任务完成记录"] = {}
    records[str(TASK_TWO)] = {
        "完成时间": float(now if now is not None else time.time()),
        "选择": choice, "奖励状态": "已领取",
    }
    if choice == 1:
        return True, "【觉醒武道天眼】道心如磐，仙台元神绽放神光！武道天眼开启，乱古战意令战斗开局行动值 +50%。", items
    return True, (f"【不继承王腾执念】仙道潜力 +50、道心 +{int(doc.ext['daoxin']) - before}、"
                  "获得乱古帝符×1。"), items


def activate_foreign_hunt(doc: Any) -> tuple[bool, str]:
    legacy = _legacy(doc, create=True)
    if legacy is None:
        return False, "支线任务档案无法建立。"
    if is_completed(doc, TASK_THREE):
        return False, "异域追杀支线已完成，无需再次开启追杀令。"
    if is_active(doc, TASK_THREE):
        return False, "追杀令已激活，异域之门仍在开启中。"
    from . import extra_cultivation
    tracks = extra_cultivation.levels_of(doc)
    if tracks["mijing"] < 18 and tracks["xiangu"] < 16:
        return False, ("你凝视着染血古令，感到一界杀意压来。『跨界而战，九死一生。』"
                       "需秘境境界达到 18 或仙古境界达到 16，方可开启异域追杀。")
    tasks = legacy.get("支线任务")
    if not isinstance(tasks, list):
        tasks = legacy["支线任务"] = []
    progress = legacy.get("支线任务进度")
    if not isinstance(progress, dict):
        progress = legacy["支线任务进度"] = {}
    tasks.append(TASK_THREE)
    progress[str(TASK_THREE)] = {
        "阶段": 1, "击败化身": 0, "抵抗鹤鸣": 0, "收集仙血": 0, "击败真身": 0,
    }
    return True, (
        "【特殊任务开启：异域追杀】\n"
        "鹤无双的杀意穿越界壁而来。先真正抵达异域，系统记录跨界准备；"
        "此后挑战位面天骄「鹤无双」，逐步追索化身、鹤鸣与不朽之血。\n"
        "阶段详情：#支线任务详情3｜阶段提交：#提交支线任务3。")


def _foreign_progress(doc: Any) -> tuple[dict | None, dict | None]:
    legacy = _legacy(doc)
    if legacy is None:
        return None, None
    progress = legacy.get("支线任务进度")
    row = progress.get(str(TASK_THREE), progress.get(TASK_THREE)) if isinstance(progress, Mapping) else None
    return legacy, row if isinstance(row, dict) else None


def record_foreign_hunt_arrival(doc: Any, target: Any) -> str:
    """由真实跨界到达事件调用；只按到达目的地推进，不读取玩家当前站位。"""
    _legacy_doc, row = _foreign_progress(doc)
    if row is None or TASK_THREE not in active_ids(doc):
        return ""
    if int(row.get("阶段", 1) or 1) != 1:
        return ""
    if isinstance(target, Mapping):
        raw_target = (target.get("target") or target.get("destination")
                      or target.get("plane") or target.get("name") or target.get("id") or "")
    else:
        raw_target = target
    target_name = str(raw_target or "").strip().replace(" ", "").lower()
    if target_name not in {"异域", "异域位面", "foreign", "foreignplane"}:
        return ""
    if int(row.get("跨界准备", 0) or 0) >= 1:
        return ""
    row["跨界准备"] = 1
    return "【异域追杀】已真实抵达异域，跨界准备完成；发送 #提交支线任务3 开始追索鹤无双化身。"


def detail_foreign_hunt(doc: Any) -> str:
    if is_completed(doc, TASK_THREE):
        return "【异域追杀】已完成：鹤鸣九霄、不朽之王传承、异域法则已收入纳戒。"
    legacy, row = _foreign_progress(doc)
    if row is None or TASK_THREE not in active_ids(doc):
        return f"你未接取【异域追杀】；使用「{TASK_THREE_ITEM}」开启，门槛为秘境18或仙古16。"
    stage = max(1, int(row.get("阶段", 1) or 1))
    stages = {
        1: f"跨界之门：通过真实跨界到达事件完成准备（{int(row.get('跨界准备', 0) or 0)}/1）。",
        2: f"化身迷局：在「#讨伐天骄 鹤无双」中获胜 {int(row.get('击败化身', 0) or 0)}/3 次。",
        3: f"鹤鸣九霄：在后续鹤无双战中取胜并存活（{int(row.get('抵抗鹤鸣', 0) or 0)}/1）。",
        4: f"不朽之血：在鹤无双战中收集仙血 {int(row.get('收集仙血', 0) or 0)}/5。",
        5: f"终极对决：彻底击败鹤无双真身（{int(row.get('击败真身', 0) or 0)}/1）。",
        6: "跨界归来：原版此阶段无额外需求，提交领取三项纳戒奖励。",
    }
    return (f"【{TASK_THREE_NAME}】阶段 {stage}/6\n{stages.get(stage, '任务进度异常。')}\n"
            f"挑战入口：#讨伐天骄 鹤无双；阶段结算：#提交支线任务3。")


def record_foreign_hunt_victory(doc: Any, final_kill: bool, now: float | None = None) -> str:
    _legacy_doc, row = _foreign_progress(doc)
    if row is None or TASK_THREE not in active_ids(doc):
        return ""
    stage = int(row.get("阶段", 1) or 1)
    if stage == 2:
        row["击败化身"] = min(3, max(0, int(row.get("击败化身", 0) or 0)) + 1)
        return f"【异域追杀】击败鹤无双化身 {row['击败化身']}/3。"
    if stage == 3:
        row["抵抗鹤鸣"] = 1
        return "【异域追杀】你在胜战中抵住鹤鸣九霄，元神未散。"
    if stage == 4:
        row["收集仙血"] = min(5, max(0, int(row.get("收集仙血", 0) or 0)) + 1)
        return f"【异域追杀】收集鹤无双洒落的不朽之血 {row['收集仙血']}/5。"
    if stage == 5 and final_kill:
        row["击败真身"] = 1
        return "【异域追杀】鹤无双真身已伏诛，追杀令指向归途。"
    return ""


def submit_foreign_hunt(doc: Any, now: float | None = None) -> tuple[bool, str, dict[str, int]]:
    if is_completed(doc, TASK_THREE):
        return False, "异域追杀已完成，传承不会重复领取。", {}
    legacy, row = _foreign_progress(doc)
    if row is None or TASK_THREE not in active_ids(doc):
        return False, "你尚未接取异域追杀。", {}
    stage = int(row.get("阶段", 1) or 1)
    items: dict[str, int] = {}
    if stage == 1:
        if int(row.get("跨界准备", 0) or 0) < 1:
            return False, "尚未通过真实跨界到达异域，跨界准备进度为 0/1。", {}
        doc.exp += 10_000
        row["阶段"] = 2
        return True, "【跨界之门】你已真实踏入异域，跨界准备完成，修为 +10,000。下一阶段：击败鹤无双化身 3 次。", items
    if stage == 2:
        if int(row.get("击败化身", 0) or 0) < 3:
            return False, f"鹤无双化身尚未击败三次（{int(row.get('击败化身', 0) or 0)}/3）。", {}
        from . import yuanshen
        yuanshen.add_cur(doc, 80)
        row["阶段"] = 3
        return True, "【化身迷局】三道鹤无双化身皆败，元神强度 +80；继续抵抗鹤鸣九霄。", items
    if stage == 3:
        if int(row.get("抵抗鹤鸣", 0) or 0) < 1:
            return False, "尚未在战胜鹤无双的战斗中抵抗鹤鸣九霄。", {}
        row["阶段"] = 4
        return True, "【鹤鸣九霄】你守住元神，继续收集五份不朽之血。", items
    if stage == 4:
        if int(row.get("收集仙血", 0) or 0) < 5:
            return False, f"不朽之血不足（{int(row.get('收集仙血', 0) or 0)}/5）。", {}
        row["阶段"] = 5
        return True, "【不朽之血】五份仙血已收齐，鹤无双真身现身边荒。", items
    if stage == 5:
        if int(row.get("击败真身", 0) or 0) < 1:
            return False, "鹤无双真身尚未被彻底击败。", {}
        doc.exp += 50_000
        row["阶段"] = 6
        return True, "【终极对决】鹤无双真身伏诛，修为 +50,000；原版归来阶段无额外门槛。", items
    if stage == 6:
        claims = legacy.get(REWARD_CLAIMS_KEY)
        if not isinstance(claims, dict):
            claims = legacy[REWARD_CLAIMS_KEY] = {}
        old_claims = legacy.get("_rewardClaims") if isinstance(legacy.get("_rewardClaims"), Mapping) else {}
        claim_key = f"zhixian:{TASK_THREE}:final"
        prior_bundle_claim = bool(old_claims.get(claim_key) or claims.get(claim_key))
        reward_names = ("鹤鸣九霄", "不朽之王传承", "异域法则")
        for reward_name in reward_names:
            per_item_key = f"zhixian:{TASK_THREE}:final:{reward_name}"
            # 旧版通用奖励引擎分别登记每件物品；旧移植曾打包登记两件道具。
            if old_claims.get(per_item_key) or claims.get(per_item_key):
                continue
            if prior_bundle_claim and reward_name != "鹤鸣九霄":
                continue
            items[reward_name] = 1
            claims[per_item_key] = {"amount": 1, "claimedAt": float(now if now is not None else time.time())}
        claims[claim_key] = {"amount": 1, "claimedAt": float(now if now is not None else time.time())}
        tasks = legacy.get("支线任务")
        if isinstance(tasks, list):
            tasks[:] = [value for value in tasks if str(value) != str(TASK_THREE)]
        progress = legacy.get("支线任务进度")
        if isinstance(progress, dict):
            progress.pop(str(TASK_THREE), None)
            progress.pop(TASK_THREE, None)
        records = legacy.get("支线任务完成记录")
        if not isinstance(records, dict):
            records = legacy["支线任务完成记录"] = {}
        records[str(TASK_THREE)] = {"完成时间": float(now if now is not None else time.time()),
                                    "选择": 0, "奖励状态": "已领取"}
        return True, "【异域追杀完成】鹤鸣九霄、不朽之王传承与异域法则×1已收入纳戒。", items
    return False, "任务阶段数据异常，请联系管理员。", {}
