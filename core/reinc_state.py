"""Stateful port of the original mist-terminal reincarnation run."""
from __future__ import annotations

import copy
import json
import random
import time
from pathlib import Path
from typing import Any

from . import reinc_story as base

with Path(__file__).with_name("reincarnation_data.json").open("r", encoding="utf-8") as _data_file:
    DATA = json.load(_data_file)

PROFESSIONS = DATA["professions"]
NPC_TEMPLATES = DATA["npcs"]
MONSTERS = DATA["monsters"]
EXCHANGES = DATA["exchanges"]
SCENES = DATA["scenes"]
ENDINGS = DATA["endings"]
ATTRIBUTE_GROUPS = DATA["attributeGroups"]
BRANCH_GRADES = DATA["branchGrades"]
SCENE_ORDER = list(SCENES)
ETHICS = {
    "rescue": ({"利他", "责任"}, {"谨慎"}),
    "truth": ({"好奇", "求知"}, {"谨慎"}),
    "unity": ({"守序", "冷静", "责任"}, {"多疑"}),
    "pragmatic": ({"谨慎", "坚韧"}, {"利他"}),
    "coercion": ({"坚韧"}, {"利他", "守序", "冷静"}),
    "sacrifice": (set(), {"利他", "责任", "守序", "冷静"}),
}


def _clamp(value: int | float, low: int | float, high: int | float) -> int | float:
    return min(high, max(low, value))


def _rand(st: dict) -> float:
    state = int(st.get("rngState", 0) or 0) & 0xFFFFFFFF
    if not state:
        state = 0x9E3779B9
    state ^= (state << 13) & 0xFFFFFFFF
    state ^= state >> 17
    state ^= (state << 5) & 0xFFFFFFFF
    st["rngState"] = state & 0xFFFFFFFF
    return st["rngState"] / 0x100000000


def _active_npcs(st: dict) -> list[dict]:
    return [npc for npc in st.get("npcs", []) if npc.get("alive") and not npc.get("separated")]


def _profession(st: dict) -> dict:
    return st.get("profession") or next(
        (p for p in PROFESSIONS if p["name"] == st.get("job")), {}
    )


def _interpolate(st: dict, text: str) -> str:
    npcs = st.get("npcs") or []
    focus = next((npc for npc in npcs if npc.get("id") == st.get("focusNpcId")), None)
    values = {
        "profession": _profession(st).get("name", st.get("job", "轮回者")),
        "focus": (focus or (npcs[0] if npcs else {})).get("name", "一名同伴"),
        "npc0": npcs[0].get("name", "同行者") if len(npcs) > 0 else "同行者",
        "npc1": npcs[1].get("name", "同行者") if len(npcs) > 1 else "同行者",
        "npc2": npcs[2].get("name", "同行者") if len(npcs) > 2 else "同行者",
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def _choice_available(st: dict, choice: dict) -> bool:
    flags = st.get("flags", {})
    if any(not flags.get(flag) for flag in choice.get("requiresFlags", [])):
        return False
    any_flags = choice.get("requiresAnyFlags", [])
    if any_flags and not any(flags.get(flag) for flag in any_flags):
        return False
    if any(flags.get(flag) for flag in choice.get("excludesFlags", [])):
        return False
    required = choice.get("requiresNpcSkill")
    return not required or any(required in npc.get("specialties", []) for npc in _active_npcs(st))


def _current_encounter(st: dict) -> dict | None:
    return next((row for row in reversed(st.get("encounters", []))
                 if row.get("scene_id") == st.get("scene_id")), None)


def _prepare_scene(st: dict, scene_id: str) -> None:
    st["scene_id"] = scene_id
    visits = st.setdefault("scene_visits", {})
    visits[scene_id] = int(visits.get(scene_id, 0) or 0) + 1
    encounters = st.setdefault("encounters", [])
    if not isinstance(encounters, list):
        encounters = list(encounters.values())
        st["encounters"] = encounters
    if not any(row.get("scene_id") == scene_id for row in encounters):
        eligible = [m for m in MONSTERS if scene_id in m.get("scenes", [])]
        used = {row.get("id") for row in encounters}
        fresh = [m for m in eligible if m["id"] not in used]
        pool = fresh or eligible
        if pool:
            monster = copy.deepcopy(pool[min(len(pool) - 1, int(_rand(st) * len(pool)))])
            monster.update({"scene_id": scene_id, "hp": monster["maxHp"], "status": "active"})
            encounters.append(monster)
    scene = SCENES.get(scene_id, {})
    st["event_dialogue"] = []
    if scene.get("autonomy"):
        focus = sorted(_active_npcs(st), key=lambda npc: (-npc.get("stress", 0), npc.get("trust", 0)))
        if focus:
            st["focusNpcId"] = focus[0]["id"]
            focus[0]["stress"] = int(_clamp(focus[0].get("stress", 0) + 7, 0, 100))
            st["event_dialogue"].append({
                "speaker": focus[0]["name"],
                "text": f"{focus[0]['bottomLine']}。继续服从之前，他要求你公开真正的风险。",
            })


def _initialize_npcs(st: dict) -> None:
    pool = copy.deepcopy(NPC_TEMPLATES)
    for index in range(len(pool) - 1, 0, -1):
        swap = min(index, int(_rand(st) * (index + 1)))
        pool[index], pool[swap] = pool[swap], pool[index]
    st["npcs"] = [dict(npc, hp=100, maxHp=100, trust=10, stress=8,
                       alive=True, separated=False) for npc in pool[:3]]
    st["focusNpcId"] = st["npcs"][0]["id"] if st["npcs"] else ""


def state_of(doc: Any) -> dict[str, Any]:
    st = base.state_of(doc)
    st.setdefault("phase", "scene" if st.get("active") else "idle")
    st.setdefault("worldline", 0)
    st.setdefault("geneLockStage", 0)
    st.setdefault("geneLockStability", 0)
    st.setdefault("geneLockUsed", False)
    st.setdefault("geneLockAwakened", False)
    st.setdefault("scene_visits", {})
    st.setdefault("branchEvents", [])
    st.setdefault("defeated_monsters", [])
    st.setdefault("encounters", {})
    st.setdefault("history", [])
    st.setdefault("flags", {})
    if not isinstance(st["flags"], dict):
        st["flags"] = {}
    if not isinstance(st.get("attributes"), dict):
        st["attributes"] = {}
    if not isinstance(st.get("npcs"), list):
        st["npcs"] = []
    if st.get("active") and not st.get("scene_id"):
        st["scene_id"] = SCENE_ORDER[min(max(0, int(st.get("scene", 0) or 0)), len(SCENE_ORDER) - 1)]
        if not st["npcs"]:
            seed = int(getattr(doc, "uid", "0")[-8:] or "0") if str(getattr(doc, "uid", "0"))[-8:].isdigit() else 1
            st["rngState"] = seed or 1
            _initialize_npcs(st)
        _prepare_scene(st, st["scene_id"])
    st["hp"] = max(0, int(st.get("hp", 100) or 0))
    st["max_hp"] = max(1, int(st.get("max_hp", 100) or 100))
    st["stress"] = max(0, int(st.get("stress", 0) or 0))
    return st


def save(doc: Any, st: dict[str, Any]) -> None:
    base.save(doc, st)


def profession_names() -> tuple[str, ...]:
    return tuple(p["name"] for p in PROFESSIONS)


def start(doc: Any, job: str, seed: int | None = None) -> tuple[bool, str]:
    job = (job or "").strip()
    profession = next((p for p in PROFESSIONS if job in (p["name"], p["id"])), None)
    if profession is None:
        return False, "用法：#开启无尽轮回 " + "/".join(profession_names())
    ok, text = base.start(doc, "老兵")
    if not ok:
        return ok, text
    st = base.state_of(doc)
    st.update({
        "job": profession["name"], "profession": copy.deepcopy(profession),
        "active": True, "phase": "scene", "scene": 0, "scene_id": "awakening",
        "stress": 8, "max_stress": 100, "hp": 100, "max_hp": 100,
        "worldline": 0, "flags": {}, "npcs": [], "encounters": {},
        "defeated_monsters": [], "branchEvents": [], "history": [],
        "scene_visits": {}, "geneLockStage": 0, "geneLockStability": 0,
        "geneLockUsed": False, "geneLockAwakened": False,
        "lastOutcome": None, "ending": None, "settlement": None,
        "rngState": int(seed if seed is not None else time.time_ns()) & 0xFFFFFFFF,
        "attributes": {name: max(1, 5 + int(profession.get("attributes", {}).get(name, 0))
                                  + int((st.get("meta_attributes") or {}).get(name, 0))
                                  + int((st.get("meta_attributes") or {}).get("*", 0))
                                  + int((st.get("meta_groups") or {}).get(group, 0))
                                  + int((st.get("attrs") or {}).get(legacy, 0)))
                       for group, names in ATTRIBUTE_GROUPS.items()
                       for name in names
                       for legacy in [ {"生命力": "体术", "战斗力": "体术",
                                        "智力": "心智", "精神力": "源能"}[group] ]},
    })
    _initialize_npcs(st)
    _prepare_scene(st, "awakening")
    scene = scene_view(st)
    save(doc, st)
    body = "\n".join(scene["narrative"] + [
        f"身份：{profession['name']}｜专长：{'、'.join(profession['specialties'])}",
        "可选：" + "；".join(f"{row['index']}. {row['text']}（{row['risk']}）" for row in scene["choices"]),
    ])
    return True, f"【无尽轮回 · 开启】终点站·雾海市\n{scene['title']}\n{body}"


def scene_view(source: Any) -> dict | None:
    st = source if isinstance(source, dict) else state_of(source)
    if st.get("phase") != "scene":
        return None
    scene = SCENES.get(st.get("scene_id"))
    if not scene:
        return None
    encounter = _current_encounter(st)
    choices = []
    for choice in scene["choices"]:
        if not _choice_available(st, choice):
            continue
        check = choice.get("check")
        check_text = "无需判定" if not check else (
            f"{' + '.join(check.get('attributes', []))}｜难度"
            f"{check.get('difficulty', 0) + (encounter or {}).get('difficulty', 0)}"
            f"｜{check.get('specialty', '无')}专长"
        )
        choices.append({
            "index": len(choices) + 1,
            "text": _interpolate(st, choice["text"]),
            "risk": choice.get("risk", ""), "checkText": check_text,
        })
    return {
        "id": st["scene_id"], "title": scene["title"], "location": scene["location"],
        "narrative": [_interpolate(st, text) for text in scene.get("narrative", [])],
        "dialogue": [dict(item, speaker=_interpolate(st, item.get("speaker", "")),
                           text=_interpolate(st, item.get("text", "")))
                     for item in scene.get("dialogue", []) + st.get("event_dialogue", [])],
        "choices": choices, "encounter": copy.deepcopy(encounter),
    }


def choice_count(doc: Any) -> int:
    scene = scene_view(doc)
    return len(scene["choices"]) if scene else 0


def _encounter_weakness(st: dict, encounter: dict | None) -> tuple[int, list[str]]:
    if not encounter:
        return 0, []
    weaknesses = set(encounter.get("weaknessSpecialties", []))
    names = []
    if weaknesses.intersection(_profession(st).get("specialties", [])):
        names.append(_profession(st).get("name", "职业"))
    names.extend(npc["name"] for npc in _active_npcs(st)
                 if weaknesses.intersection(npc.get("specialties", [])))
    return min(4, 2 * len(names)), names


def _try_gene_lock(st: dict, choice: dict, score: int, difficulty: int) -> tuple[int, dict]:
    if not choice.get("crisis") or (not choice.get("forceGeneLock") and score >= difficulty):
        return score, {"used": False, "awakened": False}
    stability_reduction = int(st.get("geneLockStability", 0)) // 20
    stage = int(st.get("geneLockStage", 0))
    if stage <= 0:
        threshold = (int(st["attributes"].get("意志力", 0))
                     + int(st["attributes"].get("抗压力", 0))
                     + int(st.get("stress", 0)) // 12)
        if threshold < 12:
            return score, {"used": False, "awakened": False}
        st["geneLockStage"] = 1
        st["geneLockAwakened"] = True
        st["geneLockUsed"] = True
        st["flags"]["geneLockUsed"] = True
        st["stress"] = int(_clamp(st["stress"] + max(8, 18 - stability_reduction), 0, st["max_stress"]))
        return score + 7, {"used": True, "awakened": True}
    st["geneLockUsed"] = True
    st["flags"]["geneLockUsed"] = True
    st["stress"] = int(_clamp(st["stress"] + max(5, 14 - stability_reduction), 0, st["max_stress"]))
    return score + 4 + stage, {"used": True, "awakened": False}


def _resolve_check(st: dict, choice: dict) -> dict:
    check = choice.get("check")
    if not check:
        return {"success": True, "score": None, "difficulty": None, "roll": None,
                "supporters": [], "geneLock": None}
    encounter = _current_encounter(st)
    active = _active_npcs(st)
    supporters = [npc for npc in active if check.get("specialty") in npc.get("specialties", [])]
    weakness_bonus, weakness_names = _encounter_weakness(st, encounter)
    profession_bonus = 3 if check.get("specialty") in _profession(st).get("specialties", []) else 0
    support_bonus = min(4, 2 * len(supporters))
    stress_penalty = min(4, int(st.get("stress", 0)) // 25)
    difficulty = int(check.get("difficulty", 0)) + int((encounter or {}).get("difficulty", 0))
    roll = 1 + int(_rand(st) * 6)
    score = sum(int(st["attributes"].get(name, 0)) for name in check.get("attributes", []))
    score += profession_bonus + support_bonus + weakness_bonus + roll - stress_penalty
    score, gene_lock = _try_gene_lock(st, choice, score, difficulty)
    return {"success": score >= difficulty, "score": score, "difficulty": difficulty,
            "roll": roll, "supporters": [npc["name"] for npc in supporters],
            "weaknessSupporters": weakness_names, "encounter": (encounter or {}).get("name"),
            "geneLock": gene_lock}


def _add_branch(st: dict, branch: dict | None) -> None:
    if not branch or any(item.get("id") == branch.get("id") for item in st["branchEvents"]):
        return
    st["branchEvents"].append(dict(branch, atScene=st["scene_id"]))


def _apply_effects(st: dict, effects: dict | None) -> None:
    effects = effects or {}
    st["hp"] = int(_clamp(st["hp"] + int(effects.get("hp", 0) or 0), 0, st["max_hp"]))
    st["stress"] = int(_clamp(st["stress"] + int(effects.get("stress", 0) or 0), 0, st["max_stress"]))
    st["worldline"] = max(0, int(st["worldline"]) + int(effects.get("worldline", 0) or 0))
    for flag in effects.get("flags", []):
        st["flags"][flag] = True
    for npc in st["npcs"]:
        npc["trust"] = int(_clamp(npc.get("trust", 0) + int(effects.get("trustAll", 0) or 0), -100, 100))
        npc["stress"] = int(_clamp(npc.get("stress", 0) + int(effects.get("npcStressAll", 0) or 0), 0, 100))
    active = _active_npcs(st)
    if effects.get("damageNpc") and active:
        target = active[min(len(active) - 1, int(_rand(st) * len(active)))]
        target["hp"] = max(0, int(target.get("hp", 0)) - int(effects["damageNpc"]))
        target["alive"] = target["hp"] > 0
    if effects.get("separateFocus"):
        focus = next((npc for npc in st["npcs"] if npc["id"] == st.get("focusNpcId")), None)
        if focus:
            focus["separated"] = True
    if effects.get("killLowestTrustNpc") and active:
        target = min(active, key=lambda npc: npc.get("trust", 0))
        target["hp"], target["alive"] = 0, False
    _add_branch(st, effects.get("branch"))


def _npc_reaction(st: dict, ethic: str | None, success: bool) -> dict | None:
    preference = ETHICS.get(ethic or "")
    if not preference:
        return None
    approve, oppose = preference
    strongest = None
    for npc in _active_npcs(st):
        likes = bool(approve.intersection(npc.get("traits", [])))
        dislikes = bool(oppose.intersection(npc.get("traits", [])))
        delta = (3 if success else 1) if likes else (-3 if success else -2) if dislikes else 0
        npc["trust"] = int(_clamp(npc.get("trust", 0) + delta, -100, 100))
        if dislikes:
            npc["stress"] = int(_clamp(npc.get("stress", 0) + 3, 0, 100))
        if strongest is None or abs(delta) > abs(strongest["delta"]):
            strongest = {"npc": npc, "delta": delta, "likes": likes}
    if not strongest or not strongest["delta"]:
        return None
    npc = strongest["npc"]
    return {"speaker": npc["name"], "text": npc["approveLine"] if strongest["delta"] > 0 else npc["opposeLine"],
            "trustDelta": strongest["delta"]}


def _resolve_encounter(st: dict, choice: dict, success: bool) -> dict | None:
    encounter = _current_encounter(st)
    if not encounter or encounter.get("status") != "active":
        return None
    weakness_bonus, weakness_names = _encounter_weakness(st, encounter)
    check = choice.get("check") or {}
    countered = check.get("specialty") in encounter.get("weaknessSpecialties", []) or bool(weakness_names)
    target = None
    player_damage = npc_damage = 0
    if success:
        encounter["status"] = "defeated" if countered else "repelled"
        encounter["hp"] = 0 if countered else int(encounter["maxHp"] * 0.35 + 0.999999)
        if countered and encounter["id"] not in st["defeated_monsters"]:
            st["defeated_monsters"].append(encounter["id"])
    else:
        encounter["status"] = "escaped"
        player_damage = int(encounter.get("attack", 0))
        st["hp"] = max(0, st["hp"] - player_damage)
        st["stress"] = int(_clamp(st["stress"] + encounter.get("terror", 0), 0, st["max_stress"]))
        for npc in _active_npcs(st):
            npc["trust"] = int(_clamp(npc.get("trust", 0) - encounter.get("trustLoss", 0), -100, 100))
            npc["stress"] = int(_clamp(npc.get("stress", 0) + encounter.get("stressAll", 0), 0, 100))
        if encounter.get("npcDamage") and _active_npcs(st):
            active = _active_npcs(st)
            target = active[min(len(active) - 1, int(_rand(st) * len(active)))]
            npc_damage = int(encounter["npcDamage"])
            target["hp"] = max(0, int(target.get("hp", 0)) - npc_damage)
            target["alive"] = target["hp"] > 0
    result = {
        "id": encounter["id"], "name": encounter["name"], "rank": encounter["rank"],
        "skill": encounter["skill"], "success": success, "countered": countered,
        "status": encounter["status"], "weaknessSupporters": weakness_names,
        "playerDamage": player_damage, "npcTarget": target.get("name") if target else None,
        "npcDamage": npc_damage,
    }
    result["text"] = (f"队伍抓住‘{encounter['weakness']}’的弱点，击破了{encounter['name']}。"
                       if success and countered else
                       f"你们挣脱了{encounter['name']}的追击，但没能彻底消灭它。"
                       if success else
                       f"{encounter['name']}发动【{encounter['skill']}】，轮回者受到{player_damage}点伤害。")
    st.setdefault("encounterLog", []).append(copy.deepcopy(result))
    return result


def _all_returned(st: dict) -> bool:
    return all(npc.get("alive") and not npc.get("separated") for npc in st.get("npcs", []))


def _resolve_ending_id(st: dict, requested: str) -> str:
    if requested == "evacuate":
        return "team_escape" if _all_returned(st) else "escape"
    if requested == "truth":
        return "deep_truth" if st["flags"].get("crewTruth") and st["flags"].get("ghostNumber") else "truth"
    if requested == "reverse":
        required = ["childSaved", "loopKey", "blackBox", "selfTruth", "unity", "geneLockUsed"]
        return "true" if _all_returned(st) and all(st["flags"].get(flag) for flag in required) else "reverse"
    return requested


def _finish(st: dict, requested: str) -> None:
    ending_id = _resolve_ending_id(st, requested)
    ending = copy.deepcopy(ENDINGS.get(ending_id, ENDINGS["failure"]))
    returned = sum(1 for npc in st["npcs"] if npc.get("alive") and not npc.get("separated"))
    grade_index = {grade: index for index, grade in enumerate(BRANCH_GRADES)}
    branch_bonus = sum(60 + grade_index.get(event.get("grade"), 0) * 50 for event in st["branchEvents"])
    monster_bonus = len(st["defeated_monsters"]) * 120
    points = int(ending["points"] + st["worldline"] * 120 + returned * 80 + branch_bonus + monster_bonus)
    if not ending["survived"]:
        points = int(points * 0.25)
    rights = {grade: 0 for grade in BRANCH_GRADES}
    if ending["survived"]:
        for event in st["branchEvents"]:
            if event.get("grade") in rights:
                rights[event["grade"]] += 1
    st["phase"] = "ending"
    st["active"] = True
    st["ending"] = {"id": ending_id, **ending}
    st["settlement"] = {
        "worldName": "终点站·雾海市", "endingId": ending_id, "ending": ending,
        "evaluation": ending["grade"], "points": points, "rights": rights,
        "branchEvents": copy.deepcopy(st["branchEvents"]), "worldline": st["worldline"],
        "returnedNpcs": returned, "totalNpcs": len(st["npcs"]),
        "defeatedMonsters": copy.deepcopy(st["defeated_monsters"]),
        "monsterBonus": monster_bonus,
    }
    st["run_points"] = int(st.get("run_start_points", 0) or 0) + points
    st["grade"] = ending["grade"]


def choose(doc: Any, pick: int, now: float | None = None,
           rng: random.Random | None = None) -> tuple[bool, str]:
    st = state_of(doc)
    if not st["active"] or st["phase"] != "scene":
        return False, "当前没有等待选择的轮回剧情。"
    scene = SCENES.get(st.get("scene_id"))
    if not scene:
        return False, "当前世界线已经失效。"
    choices = [choice for choice in scene["choices"] if _choice_available(st, choice)]
    if pick < 1 or pick > len(choices):
        return False, f"请选择1至{len(choices)}。"
    choice = choices[pick - 1]
    check = _resolve_check(st, choice)
    success = check["success"]
    _apply_effects(st, choice.get("effects"))
    _apply_effects(st, choice.get("successEffects") if success else choice.get("failureEffects"))
    encounter = _resolve_encounter(st, choice, success)
    st["stress"] = int(_clamp(st["stress"] + scene.get("threat", 0), 0, st["max_stress"]))
    reaction = _npc_reaction(st, choice.get("ethic"), success)
    outcome = {
        "sceneId": st["scene_id"], "sceneTitle": scene["title"],
        "choice": _interpolate(st, choice["text"]), "success": success,
        "text": _interpolate(st, choice.get("successText" if success else "failureText", "")),
        "check": check, "encounter": encounter, "reaction": reaction,
        "hp": st["hp"], "stress": st["stress"],
    }
    st["lastOutcome"] = outcome
    st.setdefault("history", []).append(copy.deepcopy(outcome))
    requested = (choice.get("successEnding") or choice.get("ending")) if success else (choice.get("failureEnding") or choice.get("ending"))
    next_scene = (choice.get("successNext") or choice.get("next")) if success else (choice.get("failureNext") or choice.get("next"))
    if st["hp"] <= 0:
        _finish(st, "failure")
    elif st["stress"] >= st["max_stress"]:
        _finish(st, "madness")
    elif requested:
        _finish(st, requested)
    elif next_scene in SCENES:
        st["scene"] = SCENE_ORDER.index(next_scene)
        _prepare_scene(st, next_scene)
    else:
        _finish(st, "failure")
    save(doc, st)
    tail = f"生命 {st['hp']}/{st['max_hp']}｜压力 {st['stress']}/{st['max_stress']}｜本局点数 {st['run_points']}｜可用点数 {st['points']}"
    response = (f"【{scene['title']} · {_interpolate(st, choice['text'])}】{'成功' if success else '失败'}\n"
                f"{outcome['text']}\n")
    if encounter:
        response += encounter["text"] + "\n"
    if reaction:
        response += f"{reaction['speaker']}：{reaction['text']}\n"
    response += tail
    if st["phase"] == "ending":
        response += f"\n结局【{st['ending']['name']}】：{st['ending']['description']}\n发送 #退出无尽轮回 结算评价。"
    else:
        next_view = scene_view(st)
        response += "\n下一幕【" + next_view["title"] + "】\n"
        response += "\n".join(f"{row['index']}. {row['text']}（{row['risk']}；{row['checkText']}）" for row in next_view["choices"])
    return True, response


def settle(doc: Any) -> tuple[bool, str]:
    st = state_of(doc)
    if not st["active"]:
        return False, "不在轮回之中。"
    if st.get("phase") != "ending":
        return False, "轮回尚未结束；可继续选择，或完成当前结局后结算。"
    settlement = st.get("settlement") or {}
    ok, base_text = base.settle(doc)
    if not ok:
        return ok, base_text
    st = base.state_of(doc)
    st["ending"] = None
    st["phase"] = "idle"
    st["active"] = False
    save(doc, st)
    ending = settlement.get("ending", {})
    return True, (f"{base_text}\n原版结局：【{ending.get('name', '轮回结局')}】\n"
                  f"{ending.get('description', '')}\n支线权限：{settlement.get('rights', {})}")


def enhance(doc: Any, attr: str) -> tuple[bool, str]:
    aliases = {"体术": "战斗力", "心智": "智力", "源能": "精神力"}
    group = aliases.get((attr or "").strip(), (attr or "").strip())
    if group not in ATTRIBUTE_GROUPS:
        return False, "用法：#轮回强化 生命力/战斗力/智力/精神力（600点/次，上限10）。"
    st = base.state_of(doc)
    levels = st.setdefault("meta_groups", {})
    current = int(levels.get(group, 0) or 0)
    if current >= 10:
        return False, f"【{group}】训练已达上限（10/10）。"
    if st["points"] < base.ENHANCE_COST:
        return False, f"潜能点不足：需 {base.ENHANCE_COST}（现有 {st['points']}）。"
    st["points"] -= base.ENHANCE_COST
    levels[group] = current + 1
    save(doc, st)
    return True, f"【{group}训练】{current} → {current + 1}；{', '.join(ATTRIBUTE_GROUPS[group])}永久+1（消耗 {base.ENHANCE_COST} 点）。"


def exchange(doc: Any, name: str) -> tuple[bool, str]:
    name = (name or "").strip()
    product = next((row for row in EXCHANGES if name in (row["name"], row["key"])), None)
    if product is None:
        legacy = next((row[0] for row in base.EXCHANGES if row[0] == name), None)
        if legacy:
            return base.exchange(doc, legacy)
        lines = "\\n".join(
            f"· {row['name']}｜{row['pointCost']:,} 点｜{row['description']}"
            for row in EXCHANGES
        )
        return False, "--- 轮回兑换 ---\\n" + lines + "\\n用法：#轮回兑换 名称"

    st = base.state_of(doc)
    counts = st.setdefault("original_exchanges", {})
    count = int(counts.get(product["key"], 0) or 0)
    if count >= int(product.get("max", 1)):
        return False, f"【{product['name']}】已达购买上限。"
    required = product.get("requiredGrade")
    if required:
        required_points = min((int(row["points"]) for row in ENDINGS.values()
                               if row.get("grade") == required), default=10**18)
        if int(st.get("best", 0) or 0) < required_points:
            return False, f"【{product['name']}】需历史评价达到 {required} 档。"
    cost = int(product["pointCost"])
    if int(st.get("points", 0) or 0) < cost:
        return False, f"点数不足：{product['name']} 需 {cost:,}（现有 {st['points']:,}）。"

    st["points"] -= cost
    counts[product["key"]] = count + 1
    attrs = st.setdefault("meta_attributes", {})
    for attribute, amount in product.get("attributes", {}).items():
        attrs[attribute] = int(attrs.get(attribute, 0) or 0) + int(amount)
    attrs["*"] = int(attrs.get("*", 0) or 0) + int(product.get("allAttributes", 0) or 0)
    st["geneLockStability"] = int(st.get("geneLockStability", 0) or 0) + int(product.get("geneStability", 0) or 0)
    save(doc, st)
    return True, f"【轮回兑换·{product['name']}】{product['description']}（消耗 {cost:,} 点）。"


def _task_status(st: dict, scene_id: str, success_flag: str, failure_flag: str | None = None) -> str:
    if st["flags"].get(success_flag):
        return "complete"
    if failure_flag and st["flags"].get(failure_flag):
        return "failed"
    current = SCENE_ORDER.index(st["scene_id"]) if st.get("scene_id") in SCENE_ORDER else len(SCENE_ORDER)
    task = SCENE_ORDER.index(scene_id)
    return "failed" if current > task or st.get("phase") == "ending" else "active" if current == task else "locked"


def tasks(doc: Any) -> list[dict[str, str]]:
    st = state_of(doc)
    ending = st.get("phase") == "ending"
    return [
        {"kind": "主线", "title": "在04:44前抵达终点站", "status":
         ("complete" if st.get("ending", {}).get("survived") else "failed") if ending else "active"},
        {"kind": "支线", "title": "确认第十三名乘客", "status": _task_status(st, "rule_test", "ghostNumber")},
        {"kind": "支线", "title": "救下月台失踪者", "status": _task_status(st, "child_signal", "childSaved", "childAbandoned")},
        {"kind": "支线", "title": "取得列车黑匣子", "status": "complete" if st["flags"].get("blackBox") else "partial" if st["flags"].get("damagedBlackBox") else _task_status(st, "black_box", "blackBox")},
        {"kind": "人物", "title": "让所有NPC共同返回", "status": "complete" if ending and _all_returned(st) else "failed" if ending else "active" if st["flags"].get("unity") else "locked"},
        {"kind": "隐藏", "title": "改写04:44事故", "status": "complete" if st["flags"].get("worldRewritten") else "active" if all(st["flags"].get(flag) for flag in ("childSaved", "blackBox", "selfTruth", "unity")) else "hidden" if st["active"] else "locked"},
    ]


def task_text(doc: Any, rng: random.Random | None = None) -> str:
    return "--- 轮回任务 ---\n" + "\n".join(
        f"· [{task['status']}] {task['kind']}：{task['title']}" for task in tasks(doc)
    )


def squad_text(doc: Any) -> str:
    st = state_of(doc)
    lines = ["--- 轮回小队 ---"]
    for npc in st.get("npcs", []):
        status = "阵亡" if not npc.get("alive") else "脱队" if npc.get("separated") else "同行"
        lines.append(f"· {npc['name']}（{npc['profession']}）：{status}，生命 {npc['hp']}/{npc['maxHp']}，压力 {npc['stress']}，信任 {npc['trust']}。{npc['expertise']}")
    return "\n".join(lines)


def monster_text(doc: Any) -> str:
    st = state_of(doc)
    seen = {entry.get("id"): entry for entry in (st.get("encounters") or [])}
    lines = ["--- 轮回怪物图鉴 ---"]
    for monster in MONSTERS:
        record = next((entry for entry in seen.values() if entry.get("id") == monster["id"]), None)
        status = "未遭遇" if not record else {"defeated": "已击败", "repelled": "已击退", "escaped": "曾逃脱", "active": "正在遭遇"}.get(record.get("status"), "已遭遇")
        lines.append(f"· {monster['name']}（{monster['rank']}）：{status}；弱点：{monster['weakness']}；{monster['description']}")
    return "\n".join(lines)


def panel(doc: Any) -> str:
    st = state_of(doc)
    scene = SCENES.get(st.get("scene_id"), {})
    ending = st.get("ending") or {}
    return (f"--- 无尽轮回 ---\n职业：{st.get('job', '无')}｜阶段：{scene.get('title') or ending.get('name', '中枢')}\n"
            f"生命 {st['hp']}/{st['max_hp']}｜压力 {st['stress']}/{st.get('max_stress', 100)}｜世界线 {st.get('worldline', 0)}\n"
            f"队员存活 {_all_returned(st)}｜击败怪物 {len(st.get('defeated_monsters', []))}\n"
            f"本局点数 {st['run_points']}｜可用点数 {st['points']}｜历史最高 {st['best']}")
