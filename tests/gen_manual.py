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

    # W8-E1 是单入口 + 子命令：子命令以 CMD_RV_SUB_* 文档常量登记进手册
    rv_fns = []
    for cname, cval in consts.items():
        if cname.startswith("CMD_RV_SUB_"):
            pseudo = "_rv_" + cname
            entries.append((cval, "复活地球子命令（见 #复活地球 帮助）", pseudo))
            rv_fns.append(pseudo)
    rv_fns.append("handle_rv")

    # W8-E2 同为单入口 + 子命令
    sm_fns = []
    for cname, cval in consts.items():
        if cname.startswith("CMD_SM_SUB_"):
            pseudo = "_sm_" + cname
            entries.append((cval, "剑与魔法子命令（见 #剑与魔法 帮助）", pseudo))
            sm_fns.append(pseudo)
    sm_fns += ["handle_sm", "handle_sm_draw"]

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
                 "handle_world_steal", "handle_world_jiaoguan", "handle_world_temple",
                 "handle_world_temple2", "handle_world_tame", "handle_world_place",
                 "handle_world_recall", "handle_world_recall2", "handle_world_guard_set",
                 "handle_world_guard_unset", "handle_world_habitat", "handle_world_tour")),
        ("星阁 · 竞价拍卖", ("handle_xg_help", "handle_xg_rules", "handle_xg_list",
                   "handle_xg_show", "handle_xg_bid", "handle_xg_hall",
                   "handle_xg_official_bid", "handle_xg_open", "handle_xg_cancel",
                   "handle_xg_close", "handle_xg_inner_show", "handle_xg_inner_hall",
                   "handle_xg_inner_bid", "handle_xg_verify", "handle_xg_inner_open",
                   "handle_xg_inner_cancel", "handle_xg_inner_close")),
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
        ("证道与道伤", ("handle_dz_panel", "handle_dz_rules", "handle_dz_reshape",
                    "handle_dz_repair", "handle_dz_prove", "handle_dz_reprove",
                    "handle_dz_charge", "handle_dz_charge_extreme", "handle_dz_guard",
                    "handle_dz_unguard", "handle_dz_heart")),
        ("至尊线", ("handle_sp_panel", "handle_sp_rules", "handle_sp_inherit",
                  "handle_sp_chop", "handle_sp_chop_nirvana", "handle_sp_ultimate",
                  "handle_sp_trial", "handle_sp_learn", "handle_sp_learn_nirvana",
                  "handle_sp_immortal", "handle_sp_pupil", "handle_sp_merge")),
        ("本命法宝", ("handle_bm_help", "handle_bm_panel", "handle_bm_rules", "handle_bm_mats", "handle_bm_refine_w", "handle_bm_refine_a", "handle_bm_refine_t", "handle_bm_repair_w",
                  "handle_bm_repair_a", "handle_bm_repair_t", "handle_bm_quench_w", "handle_bm_quench_a", "handle_bm_quench_t", "handle_bm_ascend_w",
                  "handle_bm_ascend_a", "handle_bm_ascend_t", "handle_bm_embed_1", "handle_bm_embed_2", "handle_bm_embed_3", "handle_bm_embed_4",
                  "handle_bm_embed_5", "handle_bm_embed_6", "handle_bm_embed_all", "handle_bm_summon_w", "handle_bm_summon_a", "handle_bm_summon_t",
                  "handle_bm_name_w", "handle_bm_name_a", "handle_bm_name_t", "handle_bm_gender_w", "handle_bm_gender_a", "handle_bm_gender_t",
                  "handle_bm_status_w", "handle_bm_status_a", "handle_bm_status_t", "handle_bm_temper_base", "handle_bm_temper_w", "handle_bm_temper_a",
                  "handle_bm_temper_t", "handle_bm_resonance_w", "handle_bm_resonance_a", "handle_bm_resonance_t", "handle_bm_sheath_on", "handle_bm_sheath_off",
                  "handle_bm_ultimate", "handle_bm_battle")),
        ("先天至宝", ("handle_xt_catalog", "handle_xt_panel", "handle_xt_help", "handle_xt_rules",
                  "handle_xt_claim", "handle_xt_equip", "handle_xt_transfer", "handle_xt_guard",
                  "handle_xt_copy", "handle_xt_evolve", "handle_xt_transform", "handle_xt_fuse",
                  "handle_xt_landscape", "handle_xt_landscape_invite", "handle_xt_landscape_harvest",
                  "handle_xt_pangu", "handle_xt_zhuxian", "handle_xt_donghuang", "handle_xt_cut_time",
                  "handle_xt_decree", "handle_xt_borrow", "handle_xt_reinc", "handle_xt_taiji",
                  "handle_xt_reverse", "handle_xt_ship_invite", "handle_xt_ship_accept",
                  "handle_xt_ship_panel", "handle_xt_ship_leave", "handle_xt_taichu",
                  "handle_xt_wuliang", "handle_xt_star", "handle_xt_spring", "handle_xt_furnace",
                  "handle_xt_bodhi", "handle_xt_causality", "handle_xt_temper", "handle_xt_dinghai",
                  "handle_xt_eternal", "handle_xt_history", "handle_xt_rewrite")),
        ("大道炼器", ("handle_dt_help", "handle_dt_rules", "handle_dt_mats",
                  "handle_dt_forge", "handle_dt_open", "handle_dt_fuel",
                  "handle_dt_guard", "handle_dt_trib", "handle_dt_my",
                  "handle_dt_rename", "handle_dt_decree", "handle_dt_repair",
                  "handle_dt_life", "handle_dt_fate", "handle_dt_apt",
                  "handle_dt_accept", "handle_dt_tech", "handle_dt_world")),
        ("锻炉 · 锻造深层", ("handle_furn_help", "handle_furn_rules", "handle_furn_mats", "handle_furn_eval", "handle_furn_show_furnace", "handle_furn_install", "handle_furn_show_fire", "handle_furn_light_fire", "handle_furn_show_gongfa", "handle_furn_learn_gongfa", "handle_furn_recipe", "handle_furn_synth", "handle_furn_melt", "handle_furn_start", "handle_furn_open", "handle_furn_oneclick", "handle_furn_perfect", "handle_furn_clear", "handle_furn_panel", "handle_furn_name", "handle_furn_board", "handle_furn_clear_all")),
        ("诡异大祭 · 厄土高原", ("handle_ss_help", "handle_ss_rules", "handle_ss_status", "handle_ss_slash", "handle_ss_fight_small", "handle_ss_fight_big", "handle_ss_open_small", "handle_ss_open_big", "handle_ss_close_small", "handle_ss_close_big", "handle_ss_settle", "handle_ss_restore", "handle_ss_rank", "handle_ss_planes", "handle_ss_repair_all", "handle_ss_yongji")),
        ("组队迎战帝尊 · 团本", ("handle_tb_help", "handle_tb_rules", "handle_tb_create", "handle_tb_join", "handle_tb_start", "handle_tb_status", "handle_tb_dps", "handle_tb_log", "handle_tb_leave", "handle_tb_mojun", "handle_tb_loot", "handle_tb_system", "handle_tb_enable", "handle_tb_disable", "handle_tb_reset_cd", "handle_tb_shutdown", "handle_tb_awaken", "handle_tb_revive")),
        ("若陀龙王 · 竞价团", ("handle_dr_help", "handle_dr_rules", "handle_dr_system", "handle_dr_list", "handle_dr_status", "handle_dr_rank", "handle_dr_fight", "handle_dr_join", "handle_dr_leave", "handle_dr_loot", "handle_dr_bid", "handle_dr_assign", "handle_dr_open", "handle_dr_close")),
        ("复活地球 · 平行开局", tuple(rv_fns)),
        ("剑与魔法 · 艾瑟兰", tuple(sm_fns)),
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
