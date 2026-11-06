"""指令手册生成器：扫描 main.py 的 @filter.command 注册，输出《指令手册》。

用法：python tests/gen_manual.py [输出路径]
- 指令名取 CMD 常量值或字面量；说明取装饰器第二参数；handler 函数名与所在分组一并输出。
- 与代码同步：每次加指令后重跑即可。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()

    # CMD 常量表
    consts = dict(re.findall(r'(CMD_\w+)\s*=\s*"([^"]+)"', src))

    # @filter.command(名, 说明) —— 名可为常量或字面量
    entries = []
    for m in re.finditer(
        r'@filter\.command\(\s*(CMD_\w+|"#[^"]+")\s*(?:,\s*"([^"]*)")?\s*'
        r'(?:,\s*alias=\{[^}]*\})?\s*\)\s*\n\s*async def (\w+)',
        src,
    ):
        name_tok, desc, fn = m.group(1), m.group(2) or "", m.group(3)
        name = consts.get(name_tok, name_tok.strip('"')) if name_tok.startswith("CMD_") else name_tok.strip('"')
        entries.append((name, desc, fn))

    # 分组归属：按 handler 名与帮助分组的近似映射（人工维护组标签）
    GROUPS = [
        ("基础修炼", ("handle_start", "handle_status", "handle_sign", "handle_closed", "handle_open", "handle_break",
                   "handle_body_break", "handle_body_my")),
        ("每日任务", ("handle_task_get", "handle_task_my", "handle_task_submit", "handle_task_claim")),
        ("灵根天资", ("handle_linggen", "handle_linggen_my", "handle_yaoxiao")),
        ("物品装备", ("handle_bag", "handle_shop", "handle_buy", "handle_sell", "handle_use", "handle_equip",
                    "handle_my_equip", "handle_unequip", "handle_enhance", "handle_gem_set", "handle_gem_unset")),
        ("战斗秘境", ("handle_spar", "handle_boss", "handle_boss_fight", "handle_heal", "handle_secret",
                    "handle_enter", "handle_search", "handle_flee",
                    "handle_addict", "handle_addict_claim", "handle_addict_clear",
                    "handle_rob", "handle_biwu", "handle_trib", "handle_ascend",
                    "handle_prof", "handle_prof_alloc", "handle_shouyuan",
                    "handle_mingge", "handle_mingge_reroll", "handle_river", "handle_river_info", "handle_lingshi", "handle_ls_buy",
                   "handle_ls_sell", "handle_ls_my", "handle_ls_trend",
                   "handle_ls_tip", "handle_ls_chat", "handle_ls_loan",
                   "handle_ls_repay", "handle_ls_rank")),
        ("黑暗动乱·神魄", ("handle_dark_open", "handle_dark_close", "handle_dark_status",
                       "handle_dark_fight", "handle_dark_rank", "handle_shenpo", "handle_shenpo_all")),
        ("宗门", ("handle_sect_create", "handle_sect_join", "handle_sect_quit", "handle_sect_mine",
                 "handle_sect_list", "handle_sect_donate", "handle_sect_up", "handle_salary",
                 "handle_sect_secret", "handle_sect_war", "handle_sect_shop", "handle_sect_exchange")),
        ("职业体系", ("handle_job", "handle_job_swap", "handle_job_my", "handle_plant", "handle_plant_end",
                   "handle_mine", "handle_mine_end", "handle_make")),
        ("炼丹锻造", ("handle_recipes", "handle_craft", "handle_alchemy_lv", "handle_danfang", "handle_fufang",
                   "handle_forge_recipes", "handle_forge", "handle_forge_lv", "handle_imperial", "handle_imperial_my")),
        ("交易社交", ("handle_pay", "handle_list_item", "handle_market", "handle_buy_lot", "handle_delist",
                   "handle_my_lots", "handle_rank", "handle_duel", "handle_duel_rank")),
        ("仙宠功法", ("handle_pet_get", "handle_pet_my", "handle_pet_feed", "handle_pet_free",
                   "handle_pet_duel", "handle_pet_rank", "handle_pet_adv",
                   "handle_gongfa_learn", "handle_gongfa_my")),
        ("图鉴查询", ("handle_lou", "handle_lou_danyao", "handle_lou_zhuangbei", "handle_lou_gongfa",
                   "handle_lou_daoju", "handle_lou_xianchong", "handle_lou_duanzaocailiao",
                   "handle_catalog_linggen", "handle_where")),
        ("剧情人物", ("handle_story", "handle_story_alias", "handle_npc", "handle_fierce_talk",
                   "handle_fierce_ask", "handle_su_talk", "handle_su_ask", "handle_essence",
                   "handle_protect_liu", "handle_protect_su", "handle_protect_hen",
                   "handle_protect_my", "handle_protect_off",
                   "handle_hei", "handle_hei_state", "handle_hei_talk", "handle_hei_teach",
                   "handle_hei_arrays", "handle_hei_engrave", "handle_array_off", "handle_array_on")),
        ("位面旅行", ("handle_plane", "handle_plane_map", "handle_plane_go",
                   "handle_plane_remember", "handle_plane_known", "handle_plane_clue",
                   "handle_plane_explore", "handle_plane_travel", "handle_plane_arrive")),
        ("裂界副本", ("handle_rift", "handle_rift_enter", "handle_rift_stable",
                   "handle_rift_loot", "handle_rift_force", "handle_rift_out",
                   "handle_rift_exchange")),
        ("千年灾劫", ("handle_calamity_summon", "handle_calamity_list", "handle_calamity_fight",
                   "handle_calamity_claim", "handle_overlord_info", "handle_overlord_fight",
                   "handle_overlord_contrib", "handle_overlord_claim", "handle_overlord_refine",
                   "handle_foreign_combine", "handle_era_status", "handle_era_next",
                   "handle_era_losses", "handle_era_charm", "handle_era_events")),
        ("彼岸古文明", ("handle_ancient", "handle_ancient_push", "handle_ancient_claim")),
        ("彼岸世界", ("handle_other_shore", "handle_other_shore_leave", "handle_other_shore_status",
                     "handle_other_shore_coord", "handle_other_shore_observe", "handle_other_shore_goto",
                     "handle_other_shore_explore", "handle_other_shore_anchor", "handle_other_shore_clear",
                     "handle_other_shore_nearest")),
        ("小世界", ("handle_world_create", "handle_world_up", "handle_world_my",
                 "handle_world_avatar", "handle_world_harvest", "handle_world_plant",
                 "handle_world_batch", "handle_world_water", "handle_world_workshop",
                 "handle_world_workshop_up", "handle_world_guard", "handle_world_ripen",
                 "handle_world_steal")),
        ("团本讨伐", ("handle_team_create", "handle_team_join", "handle_team_start",
                   "handle_team_hit", "handle_team_info", "handle_team_list",
                   "handle_team_dismiss", "handle_team_claim")),
        ("无尽劫境", ("handle_endless", "handle_endless_start", "handle_endless_map",
                   "handle_endless_route", "handle_endless_next", "handle_endless_pick",
                   "handle_endless_checkpoint", "handle_endless_build", "handle_endless_quit",
                   "handle_endless_tier", "handle_endless_celestial", "handle_endless_rank",
                   "handle_endless_shop", "handle_endless_buy", "handle_endless_merchant",
                   "handle_endless_merchant_buy", "handle_endless_titles",
                   "handle_endless_titles_alias", "handle_endless_title_equip",
                   "handle_endless_weekend", "handle_endless_meta", "handle_endless_meta_up",
                   "handle_endless_meta_reset", "handle_endless_meta_reset_yes",
                   "handle_endless_reroll", "handle_endless_treasure",
                   "handle_endless_treasure_up", "handle_endless_treasure_equip",
                   "handle_endless_treasure_unequip", "handle_endless_treasure_slot",
                   "handle_endless_sweep")),
        ("花粉进化路", ("handle_fl_start", "handle_fl_panel", "handle_fl_levels",
                    "handle_fl_plane", "handle_fl_sense", "handle_fl_evolve",
                    "handle_fl_fruit", "handle_fl_purify", "handle_fl_reshape",
                    "handle_fl_wudao", "handle_fl_seed_wudao", "handle_fl_breed",
                    "handle_fl_super", "handle_fl_trib", "handle_fl_extreme")),
        ("岁云灵根", ("handle_sy_seek", "handle_sy_awake", "handle_sy_panel",
                    "handle_sy_stages", "handle_sy_witness", "handle_sy_cultivate",
                    "handle_sy_years", "handle_sy_lotus", "handle_sy_refine",
                    "handle_sy_soul", "handle_sy_redeem", "handle_sy_create",
                    "handle_sy_change", "handle_sy_grant", "handle_sy_fish",
                    "handle_sy_dungeon", "handle_sy_addict", "handle_sy_shop",
                    "handle_sy_buy", "handle_sy_authority", "handle_sy_unseal",
                    "handle_sy_dream", "handle_sy_sword", "handle_sy_descent",
                    "handle_sy_root", "handle_sy_pray", "handle_sy_skill",
                    "handle_sy_genesis")),
        ("帮助", ("handle_help",)),
    ]
    grouped = {}
    for g, fns in GROUPS:
        grouped[g] = list(fns)
    assigned = {fn for _, fns in GROUPS for fn in fns}
    for name, desc, fn in entries:
        if fn not in assigned and fn not in [f for fns in grouped.values() for f in fns]:
            grouped.setdefault("其它", []).append(fn)

    out = ["# 诸天修仙 · 指令手册（自动生成，与代码同步）", "",
           f"> 生成自 main.py 的 @filter.command 注册，共 {len(entries)} 条指令。", ""]
    total = 0
    for g, fns in grouped.items():
        rows = [(n, d, f) for n, d, f in entries if f in fns]
        if not rows:
            continue
        out.append(f"\n## {g}\n")
        out.append("| 指令 | 说明 |")
        out.append("| --- | --- |")
        for n, d, _f in rows:
            total += 1
            out.append(f"| `{n}` | {d} |")
    out.append(f"\n---\n\n合计 {total} 条指令。玩家侧另见「#修仙帮助」与「#修仙帮助 目录」（源版 14 分组帮助）。")

    dst = sys.argv[1] if len(sys.argv) > 1 else r"Z:\dsh\指令手册.md"
    open(dst, "w", encoding="utf-8").write("\n".join(out))
    print(f"written {dst}：{total} 条指令")
    return 0


if __name__ == "__main__":
    sys.exit(main())
