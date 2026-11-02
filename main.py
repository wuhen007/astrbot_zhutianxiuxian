"""诸天修仙 —— AstrBot 原生插件（M0：骨架 + 存储层 + 内容加载 + 建档/面板）。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from .core.player import PlayerDoc, create_player, next_realm_entry, realm_entry
from .core import alchemy, battle, boss, catalog, cultivate, equipment, items, linggen, occupation, pet, quest, secret, sect
from .infra import render
from .infra.content import ContentStore
from .infra.db import DataBase

PLUGIN_DIR = Path(__file__).parent


def talent_desc(t: dict) -> str:
    return {
        "balanced": "三维 +8%",
        "savage": "宠物对战攻击 +20%",
        "rock": "宠物对战防御与血量 +25%",
        "vital": "宠物对战血量 +40%",
        "claw": "宠物对战暴击 +12%",
        "koi": "宠物对战成长获取 +50%",
    }.get(t["id"], "")


# 指令名以原项目（诸天万界修仙）为准，均带 # 前缀
CMD_START = "#踏入仙途"
CMD_STATUS = "#修仙状态"
CMD_HELP = "#修仙帮助"
CMD_SIGN = "#修仙签到"
CMD_CLOSED = "#闭关"
CMD_OPEN = "#出关"
CMD_BREAK = "#突破"
CMD_BAG = "#我的纳戒"
CMD_BAG_ALIAS = "#纳戒"
CMD_SHOP = "#商店"
CMD_BUY = "#购买"
CMD_SELL = "#出售"
CMD_USE = "#使用"
CMD_EQUIP = "#装备"
CMD_UNEQUIP = "#卸下装备"
CMD_MY_EQUIP = "#我的装备"
CMD_SPAR = "#切磋"
CMD_BOSS = "#查看世界boss"
CMD_BOSS_ALIAS = "#世界boss"
CMD_BOSS_FIGHT = "#讨伐boss"
CMD_HEAL = "#疗伤"
CMD_SECRET = "#秘境"
CMD_ENTER = "#降临秘境"
CMD_SEARCH = "#寻宝"
CMD_FLEE = "#逃离"
CMD_SECT_CREATE = "#创建宗门"
CMD_SECT_JOIN = "#加入宗门"
CMD_SECT_QUIT = "#退出宗门"
CMD_SECT_LIST = "#宗门列表"
CMD_SECT_MINE = "#我的宗门"
CMD_SECT_DONATE = "#宗门捐赠灵石"
CMD_SECT_UP = "#升级宗门"
CMD_RANK = "#天地榜"
CMD_ENHANCE = "#强化"
CMD_SALARY = "#宗门俸禄"
CMD_PAY = "#转账"
CMD_LIST_ITEM = "#上架"
CMD_MARKET = "#拍卖行"
CMD_BUY_LOT = "#购买拍卖"
CMD_DELIST = "#下架"
CMD_MY_LOTS = "#我的拍卖"
CMD_RECIPES = "#炼丹配方"
CMD_CRAFT = "#炼丹"
CMD_ALCHEMY_LV = "#炼丹等级"
CMD_LINGGEN = "#灵根"
CMD_LINGGEN_MY = "#我的灵根"
CMD_TASK_GET = "#获取每日任务"
CMD_TASK_MY = "#我的任务"
CMD_TASK_SUBMIT = "#提交每日任务"
CMD_TASK_CLAIM = "#领取每日奖励"
CMD_LOU = "#图鉴楼"
CMD_WHERE = "#哪里有"
CMD_JOB = "#转职"
CMD_JOB_SWAP = "#转换副职"
CMD_JOB_MY = "#我的职业"
CMD_PLANT = "#采药"
CMD_PLANT_END = "#结束采药"
CMD_MINE = "#采矿"
CMD_MINE_END = "#结束采矿"
CMD_MAKE = "#制作"
CMD_DARK_OPEN = "#开启黑暗动乱"
CMD_DARK_CLOSE = "#关闭黑暗动乱"
CMD_DARK_STATUS = "#禁区至尊状态"
CMD_DARK_FIGHT = "#平定黑暗动乱"
CMD_DARK_RANK = "#黑暗动乱帝战贡献榜"
CMD_SHENPO = "#炼神魄"
CMD_SHENPO_ALL = "#一键炼神魄"
CMD_IMPERIAL = "#认主"
CMD_IMPERIAL_MY = "#已认主"
CMD_SECT_SECRET = "#宗门秘境"
CMD_FORGE_RECIPES = "#锻造图纸"
CMD_FORGE = "#锻造"
CMD_FORGE_LV = "#锻造等级"
CMD_DUEL = "#比试"
CMD_DUEL_RANK = "#比试榜"
CMD_GEM_SET = "#镶嵌"
CMD_GEM_UNSET = "#拆除"
CMD_GONGFA_LEARN = "#学习"
CMD_GONGFA_MY = "#我的功法"
CMD_SECT_WAR = "#宗门挑战"
CMD_SECT_SHOP = "#宗门商店"
CMD_SECT_EXCHANGE = "#宗门兑换"
CMD_PET_GET = "#领养仙宠"
CMD_PET_MY = "#我的仙宠"
CMD_PET_FEED = "#喂给仙宠"
CMD_PET_FREE = "#放生仙宠"
CMD_PET_DUEL = "#仙宠对战"
CMD_PET_RANK = "#仙宠榜"
CMD_PET_ADV = "#进阶仙宠"

# 参与全局物品索引的内容表（item/ 目录下）
ITEM_TABLES = (
    "丹药列表", "道具列表", "材料列表", "草药列表", "装备列表", "功法列表",
    "特殊装备列表", "食材列表", "宝石", "盒子列表", "帝兵列表", "锻造杂类",
    "锻造武器", "锻造护具", "锻造宝物", "锻造材料", "炼丹师丹药", "常驻", "限定",
    "仙宠列表", "仙宠口粮列表",
)


@register(
    "astrbot_plugin_zhutian",
    "wuhen",
    "诸天万界修仙（Python 重构版）",
    "v0.1.0",
    "",
)
class ZhutianPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.db = DataBase(StarTools.get_data_dir("zhutian") / "zhutian.db")
        self.panel_dir = StarTools.get_data_dir("zhutian") / "panels"
        self.render_on = bool(config.get("RENDER_ENABLE", True))
        # shortcut: 数据表暂从插件目录读取（随代码分发），表多体积大后改放 StarTools 数据目录
        self.content = ContentStore(PLUGIN_DIR / "data")
        logger.info(f"[zhutian] 内容表 {len(self.content.tables)} 张已加载")
        self.whitelist_groups = [
            str(g) for g in (config.get("ACCESS_CONTROL", {}).get("WHITELIST_GROUPS") or [])
        ]

        # 物品索引：从指定类别表构建 名称→物品（同名以先出现者为准）
        self.item_index: dict[str, dict] = {}
        dupes = 0
        for t in ITEM_TABLES:
            table = self.content.table("item/" + t)
            if not isinstance(table, list):
                continue
            for e in table:
                if not isinstance(e, dict) or not e.get("name") or "class" not in e:
                    continue
                if e["name"] in self.item_index:
                    dupes += 1
                    continue
                self.item_index[e["name"]] = e
        self.shop_stock = [
            e for t in ("item/常驻", "item/限定")
            for e in (self.content.table(t) if isinstance(self.content.table(t), list) else [])
            if isinstance(e, dict) and e.get("name")
        ]
        logger.info(f"[zhutian] 物品索引 {len(self.item_index)} 条（去重 {dupes}），坊市货架 {len(self.shop_stock)} 件")

        # 仙宠图鉴按 id 索引（进阶形态 = id+1，对齐原版）
        self.pet_by_id = {
            int(e["id"]): e for e in self.item_index.values()
            if e.get("class") == "仙宠" and str(e.get("id") or "").isdigit()
        }

        # 秘境掉落池：材料/草药/丹药（稀有度门槛在掉落时过滤）
        self.drop_pool = [
            e for e in self.item_index.values()
            if e.get("class") in ("材料", "草药", "丹药")
        ]

        # 灵根（天资）表：原版 139 条，天资洗炼类丹药重摇用
        self.linggen_table = [
            e for e in (self.content.table("item/灵根列表") or [])
            if isinstance(e, dict) and e.get("name")
        ]

        # 职业经验表（occupation/experience.json 38 档）与职业名单
        self.occ_exp_table = [
            e for e in (self.content.table("occupation/experience") or [])
            if isinstance(e, dict) and e.get("id") is not None
        ]
        self.job_names = [
            str(e.get("name")) for e in (self.content.table("occupation/职业列表") or [])
            if isinstance(e, dict) and e.get("name")
        ]

        # 炼丹配方：原版 21 条；产物双轨判定（对齐原版 zhizuo_dan）
        # direct = 产物原丹有效果（修为/血量/血气/天资洗炼）→ 直接产出
        # quality = 凡品/极品/仙品 三档分档丹在索引（原版品质分档）→ 掷品质
        self.recipes = [
            r for r in (self.content.table("occupation/炼丹配方") or [])
            if isinstance(r, dict) and r.get("name")
        ]
        self.craft_mode: dict[str, str] = {}
        for r in self.recipes:
            name = r["name"]
            p = self.item_index.get(name)
            if p and (
                p.get("exp")
                or float(p.get("HPp") or 0) > 0
                or float(p.get("HP") or 0) > 1
                or float(p.get("xueqi") or 0) > 0
                or float(p.get("linggen") or 0) > 0
                or float(p.get("potential") or 0) > 0
                or float(p.get("heart") or 0) > 0
                or p.get("type") == "天资洗炼"
            ):
                self.craft_mode[name] = "direct"
            elif all(f"{q}{name}" in self.item_index for q in ("凡品", "极品", "仙品")):
                self.craft_mode[name] = "quality"
        self.craftable = [r for r in self.recipes if r["name"] in self.craft_mode]
        logger.info(f"[zhutian] 炼丹配方 {len(self.recipes)} 条，开放 {len(self.craftable)} 条")

        # 锻造图纸：原版 7 条，仅开放产物在索引的
        self.forge_recipes = [
            r for r in (self.content.table("occupation/装备图纸") or [])
            if isinstance(r, dict) and r.get("name") and r["name"] in self.item_index
        ]
        logger.info(f"[zhutian] 锻造图纸 {len(self.forge_recipes)} 条开放（原版 7 条）")

    async def initialize(self) -> None:
        await self.db.connect()
        self._reminder_task = asyncio.create_task(self._daily_reminder_loop())
        logger.info("[zhutian] M0 插件已加载。")

    async def terminate(self) -> None:
        task = getattr(self, "_reminder_task", None)
        if task:
            task.cancel()
        await self.db.close()
        await render.shutdown()

    async def _daily_reminder_loop(self) -> None:
        """每日 00:05（上海时区）向白名单群推送日常刷新提醒（对齐原版 AutoDailyTask 时点）。"""
        from astrbot.api.event import MessageChain
        from astrbot.api.message_components import Plain

        platform_id = "大肥鱼"  # qq_official 平台实例 id
        try:
            while True:
                now = time.time()
                hm = time.strftime("%H:%M", time.gmtime(now + 8 * 3600))
                dkey = time.strftime("%Y-%m-%d", time.gmtime(now + 8 * 3600))
                if hm == "00:05" and getattr(self, "_last_reminder_date", "") != dkey:
                    self._last_reminder_date = dkey
                    text = (
                        "【诸天修仙 · 每日刷新】\n"
                        "#修仙签到 / #获取每日任务 已刷新，道友们今天也别忘了修行。"
                    )
                    for gid in self.whitelist_groups:
                        try:
                            await self.context.send_message(
                                f"{platform_id}:GroupMessage:{gid}",
                                MessageChain(chain=[Plain(text)]),
                            )
                        except Exception as e:  # 单群失败不影响其它群
                            logger.warning(f"[zhutian] 每日提醒发送失败 {gid}: {e}")
                await asyncio.sleep(20)
        except asyncio.CancelledError:
            pass

    # ---- 门禁 ----

    def _allowed(self, event: AstrMessageEvent) -> bool:
        if not self.whitelist_groups:
            return True
        gid = event.get_group_id()
        return not gid or str(gid) in self.whitelist_groups

    async def _find_player(self, event: AstrMessageEvent) -> PlayerDoc | None:
        raw = await self.db.get_player(event.get_sender_id())
        return PlayerDoc(**raw) if raw else None

    async def _require_player(self, event: AstrMessageEvent) -> tuple[PlayerDoc | None, str | None]:
        doc = await self._find_player(event)
        if not doc:
            return None, f"道友尚未踏入仙途，请发送「{CMD_START}」。"
        return doc, None

    # ---- 指令 ----

    @filter.command(CMD_START, "踏入仙途，创建角色")
    async def handle_start(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        uid = event.get_sender_id()
        if await self.db.get_player(uid):
            yield event.plain_result("道友已踏入仙途，无需重复此举。")
            return
        doc = create_player(uid, event.get_sender_name() or "", self.content.table("Level/练气境界"))
        await self.db.save_player(doc.model_dump())
        entry = realm_entry(doc, self.content.table("Level/练气境界"))
        yield event.plain_result(
            f"恭喜道友 {doc.name or uid} 踏入仙途！\n"
            f"起始境界：【{entry.get('level', '凡人')}】\n"
            f"发送「{CMD_STATUS}」查看状态。"
        )

    @filter.command(CMD_STATUS, "查看修仙状态")
    async def handle_status(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc = await self._find_player(event)
        if not doc:
            yield event.plain_result(f"道友尚未踏入仙途，请发送「{CMD_START}」。")
            return
        text, data = self._status_text(doc)
        if self.render_on:
            png = await render.render_panel("status", data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        yield event.plain_result(text)

    def _stats(self, doc: PlayerDoc) -> equipment.Stats:
        return equipment.aggregate(
            doc, self.content.table(doc.realm_table), self.item_index.get,
            doc.ext.get("enh"), set(doc.ext.get("imperial") or []),
        )

    def _hp_pair(self, doc: PlayerDoc) -> tuple[int, int]:
        """(当前气血, 上限)。ext 缺失视为满血；上限缩小时自动钳制。"""
        max_hp = self._stats(doc).hp
        cur = min(float(doc.ext.get("hp", max_hp)), float(max_hp))
        return int(max(cur, 0)), int(max_hp)

    async def _ensure_boss(self) -> dict:
        row = await self.db.get_boss()
        if row is None:
            health, reward = boss.boss_specs(1)
            await self.db.init_boss(1, health, reward)
            row = await self.db.get_boss()
        return row

    def _status_text(self, doc: PlayerDoc) -> tuple[str, dict]:
        # shortcut: 纯文本面板，M1 面板出图时接 Jinja2+Playwright，此处接口保持返回 str
        table = self.content.table(doc.realm_table)
        entry = realm_entry(doc, table)
        nxt = next_realm_entry(doc, table)
        req = entry.get("exp", 0)
        st = self._stats(doc)
        hp_cur, hp_max = self._hp_pair(doc)
        data = {
            "name": doc.name or doc.uid[:8] + "…",
            "realm": entry.get("level", "未知"),
            "exp": doc.exp, "req": req,
            "next": nxt["level"] if nxt else "",
            "progress": min(100.0, doc.exp / req * 100) if req else 100.0,
            "hp_cur": hp_cur, "hp_max": hp_max,
            "stones": doc.stones,
            "atk": st.atk, "defense": st.defense, "hp": st.hp,
            "bao": f"{st.bao:.0%}" if st.bao else "",
            "set_lines": list(st.set_lines),
        }
        lg = doc.ext.get("linggen")
        data["linggen"] = linggen.describe(lg) if isinstance(lg, dict) else ""
        lines = [
            f"--- 道友 {data['name']} 的仙途 ---",
            f"境界：{data['realm']}",
            f"修为：{data['exp']}" + (f" / {data['req']}（下一境 {data['next']}）" if nxt else "（已臻化境）"),
            f"气血：{hp_cur} / {hp_max}",
            f"灵石：{doc.stones}",
            f"攻击 {st.atk} · 防御 {st.defense} · 血量 {st.hp}"
            + (f" · 暴击 {st.bao:.0%}" if st.bao else ""),
        ]
        if data["linggen"]:
            lines.append(f"灵根：{data['linggen']}")
        state_note = ""
        if doc.state == "闭关中":
            cap = int(self._val("CULTIVATE_MAX_MINUTES", 7200))
            period = 30
            planned = doc.ext.get("cultivate_minutes")
            elapsed = max(0.0, (time.time() - doc.state_start) / 60)
            counted = min(elapsed, float(planned) if planned else float(cap), float(cap))
            floored = int(counted // period) * period
            gongfa_bonus = 0
            for gname in (doc.ext.get("gongfa") or []):
                g = self.item_index.get(gname) or {}
                try:
                    gongfa_bonus += float(g.get("修炼加成") or 0)
                except (TypeError, ValueError):
                    pass
            buffs = doc.ext.get("buffs") or {}
            big = buffs.get("biguan") if isinstance(buffs.get("biguan"), dict) else {}
            biguan_bonus = float(big.get("bonus", 0) or 0)
            base_per_min = int(self._val("CULTIVATE_EXP_PER_REALM", 10)) * (max(0, doc.realm_index) + 1)
            eff_rate = max(1, int(
                base_per_min * (1 + linggen.eff_of(doc) + gongfa_bonus + biguan_bonus)))
            note = f"闭关中（已 {int(elapsed)} 分钟"
            note += f"，计划 {planned} 分钟" if planned else ""
            note += f"，现在出关可得修为 {int(floored * eff_rate)}）"
            lines.append("状态：" + note)
            state_note = note
        elif doc.state == "秘境中":
            note = f"正在【{(doc.ext.get('explore') or {}).get('place', '?')}】探索"
            lines.append("状态：" + note)
            state_note = note
        return "\n".join(lines), data

    def _help_groups(self) -> list[dict]:
        """帮助指令分组（出图与纯文本回退同源）。"""
        return [
            {"title": "基础修炼", "lines": [
                (CMD_START, "踏入仙途，创建角色"),
                (CMD_STATUS, "查看状态（含灵根）"),
                (CMD_SIGN, "每日签到领灵石"),
                (f"{CMD_CLOSED} 120分钟", "闭关修炼（时长可省略）"),
                (CMD_OPEN, "出关结算（×灵根效率）"),
                (CMD_BREAK, "境界突破"),
            ]},
            {"title": "灵根天资", "lines": [
                (CMD_LINGGEN, "查看灵根（/我的灵根 同效）"),
                ("天命轮回丹 · 神心丹", "使用后洗炼重摇，资质好坏全凭天命"),
                ("#丹药效果", "查看当前生效的丹药 buff"),
            ]},
            {"title": "每日任务", "lines": [
                (CMD_TASK_GET, "接取/刷新今日三任务"),
                (CMD_TASK_MY, "查看任务进度"),
                (CMD_TASK_SUBMIT, "提交结算（步进奖励）"),
                (CMD_TASK_CLAIM, "领取终极奖励"),
            ]},
            {"title": "源版帮助目录", "lines": [
                (f"{CMD_HELP} 目录", "诸天/灵根/职业/活动/小世界/师徒/基础/宗门/设置/星海/周年/通用/扩展/世界"),
            ]},
            {"title": "职业体系", "lines": [
                (f"{CMD_JOB} 职业名", "转职（需对应转职凭证）"),
                (f"{CMD_JOB_SWAP} 职业名", "切换副职"),
                (CMD_JOB_MY, "查看主职与副职"),
                (f"{CMD_PLANT} 分钟", "采药（采药师，15 分钟周期）"),
                (CMD_PLANT_END, "结束采药结算"),
                (f"{CMD_MINE} 分钟", "采矿（采矿师，30 分钟周期）"),
                (CMD_MINE_END, "结束采矿结算"),
                (f"{CMD_MAKE} 符名 数量", "制作符箓（符师，必成）"),
            ]},
            {"title": "黑暗动乱 · 神魄", "lines": [
                (f"{CMD_DARK_OPEN} / {CMD_DARK_CLOSE}", "管理员开启/关闭黑暗动乱"),
                (CMD_DARK_STATUS, "禁区至尊状态"),
                (CMD_DARK_FIGHT, "平定黑暗动乱（12 境+，5 分钟 CD，败则气血归零）"),
                (CMD_DARK_RANK, "帝战贡献榜"),
                (CMD_SHENPO, "炼神魄（锻神池，2 分钟 CD，胜则神魄+5 血气+）"),
                (CMD_SHENPO_ALL, "一键炼神魄（连破到败）"),
            ]},
            {"title": "图鉴查询", "lines": [
                (f"{CMD_LOU} 类目 页码", "丹药楼/装备楼/功法楼/道具楼/仙宠楼/锻造材料楼/灵根图鉴等"),
                ("#丹药楼 页码 等独立指令", "各楼直接翻页"),
                (f"{CMD_WHERE} 物品名", "查询物品获取渠道"),
            ]},
            {"title": "物品装备", "lines": [
                (f"{CMD_BAG} / {CMD_BAG_ALIAS}", "查看纳戒"),
                (f"{CMD_SHOP} 页码", "坊市"),
                (f"{CMD_BUY} 名字 数量", "购买"),
                (f"{CMD_SELL} 名字 数量", "出售"),
                (f"{CMD_USE} 名字", "使用物品"),
                (f"{CMD_EQUIP} 名字", "穿戴装备（武器/护具/法宝/帝兵/至宝）"),
                (CMD_MY_EQUIP, "查看已穿装备"),
                (f"{CMD_UNEQUIP} 部位", "卸下装备"),
                (f"{CMD_ENHANCE} 部位", "强化（+10%/级，最高+10）"),
                (f"{CMD_GEM_SET} 宝石 部位", "镶嵌宝石（每槽 2 颗）"),
                (f"{CMD_GEM_UNSET} 部位 序号", "拆除宝石"),
            ]},
            {"title": "战斗秘境", "lines": [
                (f"{CMD_SPAR} @道友", "切磋（60 秒冷却）"),
                (CMD_BOSS, "世界 Boss 状态与贡献榜"),
                (CMD_BOSS_FIGHT, "讨伐妖王（气血>10%，按贡献分奖池）"),
                (CMD_HEAL, "花灵石疗伤回满"),
                (CMD_SECRET, "秘境列表"),
                (f"{CMD_ENTER} 名字", "降临秘境（需空闲、气血>30%）"),
                (CMD_SEARCH, "寻宝一次（怪物/宝箱/灵物）"),
                (CMD_FLEE, "携带收获撤离"),
            ]},
            {"title": "宗门", "lines": [
                (f"{CMD_SECT_CREATE} 名字", "创建宗门（需第 6 境 + 1 万灵石）"),
                (f"{CMD_SECT_JOIN} 名字 / {CMD_SECT_QUIT}", "加入与退出"),
                (f"{CMD_SECT_MINE} / {CMD_SECT_LIST}", "宗门信息"),
                (f"{CMD_SECT_DONATE} 数量", "捐灵石入宗门基金"),
                (CMD_SECT_UP, "宗主升级宗门（费用取基金）"),
                (CMD_SALARY, "每日宗门俸禄（等级×1200，宗主×2）"),
                (CMD_SECT_SECRET, "宗门秘境（3 级解锁，系数随等级）"),
                (f"{CMD_SECT_WAR} @对方成员", "宗门挑战（宗门积分战）"),
                (f"{CMD_SECT_SHOP} / {CMD_SECT_EXCHANGE} 商品 数量", "贡献度兑换"),
            ]},
            {"title": "炼丹锻造", "lines": [
                (CMD_RECIPES, "开放配方（简要）"),
                ("#丹药配方", "全量丹方总览（出图）"),
                ("#符道配方", "符方总览（制符后续开放）"),
                (f"{CMD_CRAFT} 丹药名 数量", "炼丹"),
                (CMD_ALCHEMY_LV, "炼丹等级"),
                ("#丹药效果", "当前生效丹药 buff"),
                (CMD_FORGE_RECIPES, "锻造图纸"),
                (f"{CMD_FORGE} 装备名", "锻造（炼器经验制）"),
                (f"{CMD_IMPERIAL} 帝兵名", "帝兵认主（加成翻倍，不可转让）"),
                (CMD_IMPERIAL_MY, "查看已认主帝兵"),
            ]},
            {"title": "交易社交", "lines": [
                (f"{CMD_PAY} @道友 数量", "转账（5% 手续费）"),
                (f"{CMD_LIST_ITEM} 物品 数量 价格", "上架拍卖行"),
                (f"{CMD_MARKET} 页码", "拍卖行浏览"),
                (f"{CMD_BUY_LOT} 单号", "竞拍购买"),
                (f"{CMD_DELIST} 单号 / {CMD_MY_LOTS}", "下架 / 我的挂单"),
                (CMD_RANK, "修为与灵石排行"),
                (f"{CMD_DUEL} @道友 / {CMD_DUEL_RANK}", "比试（胜+3 平+1）与积分榜"),
            ]},
            {"title": "仙宠功法", "lines": [
                (f"{CMD_PET_GET} 名字 / {CMD_PET_MY}", "领取 / 查看仙宠"),
                (f"{CMD_PET_FEED} 灵石 / {CMD_PET_FREE}", "喂养 / 放生"),
                (f"{CMD_PET_DUEL} @道友 / {CMD_PET_RANK}", "宠物对战（+3 成长）与仙宠榜"),
                (CMD_PET_ADV, "进阶仙宠（品级觉醒暴击）"),
                (f"{CMD_GONGFA_LEARN} 功法名", "学习功法（提升闭关效率）"),
                (CMD_GONGFA_MY, "已学功法"),
            ]},
        ]

    # 源版帮助目录（config/help/*.yaml 1:1 迁移至 data/help/*.json）
    HELP_CATALOGS = {
        "诸天": "zhutianhelp", "灵根": "linggenhelp", "职业": "zhiyehelp",
        "活动": "huodonghelp", "小世界": "xiaoshijiehelp", "师徒": "shituhelp",
        "基础": "jichuhelp", "宗门": "Association", "设置": "set",
        "星海": "xinghai", "周年": "zhounianqing", "通用": "helpcopy",
        "扩展": "help2", "世界": "help",
    }

    @filter.command(CMD_HELP, "修仙帮助")
    async def handle_help(self, event: AstrMessageEvent, catalog_name: str = ""):
        if not self._allowed(event):
            return
        key = (catalog_name or "").strip().lstrip("#")
        if key:
            fname = self.HELP_CATALOGS.get(key)
            if not fname:
                names = "、".join(self.HELP_CATALOGS)
                yield event.plain_result(f"查无帮助目录「{key}」。可用：{names}")
                return
            groups = self.content.table("help/" + fname)
            if not isinstance(groups, list) or not groups:
                yield event.plain_result("该帮助目录为空。")
                return
            if self.render_on:
                png = await render.render_panel(
                    "catalog", {"title": f"诸天修仙 · {key}帮助", "groups": groups},
                    self.panel_dir)
                if png:
                    yield event.image_result(str(png))
                    return
            lines = [f"【{key}帮助】"]
            for g in groups:
                lines.append(f"—— {g.get('group', '')} ——")
                for it in g.get("list", []):
                    lines.append(f"{it.get('title', '')}：{it.get('desc', '')}")
            yield event.plain_result("\n".join(lines))
            return
        groups = self._help_groups()
        if self.render_on:
            png = await render.render_panel(
                "help", {"title": "诸天修仙 · 指令总览", "groups": groups}, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        lines = ["【诸天修仙 · 已开放指令】"]
        for g in groups:
            lines.append(f"—— {g['title']} ——")
            for c, d in g["lines"]:
                lines.append(f"{c}：{d}")
        yield event.plain_result("\n".join(lines))

    # ---- 数值辅助 ----

    def _val(self, key: str, default):
        return (self.config.get("VALUES", {}) or {}).get(key, default)

    @filter.command(CMD_SIGN, "每日签到领灵石")
    async def handle_sign(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        import random as _random
        ok, msg, d = cultivate.sign_in(
            doc, int(self._val("SIGN_REWARD_MIN", 100)), int(self._val("SIGN_REWARD_MAX", 500)),
            time.time(), _random.Random(f"{doc.uid}:{int(time.time() // 86400)}"),
        )
        if ok:
            async with self.db.transaction():
                await self.db.save_player(d.model_dump())
                await self.db.add_items(doc.uid, {"秘境之匙": 1})  # 对齐原版 Sign.ticket=1/天
        yield event.plain_result(msg)

    @filter.command(CMD_CLOSED, "闭关修炼")
    async def handle_closed(self, event: AstrMessageEvent, minutes: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        max_minutes = int(self._val("CULTIVATE_MAX_MINUTES", 7200))
        planned: int | None = None
        arg = (minutes or "").strip()
        if arg:
            digits = "".join(ch for ch in arg if ch.isdigit())
            if not digits:
                yield event.plain_result("格式：#闭关 120分钟（时长可省略，上限见帮助）")
                return
            planned = int(digits)
        ok, msg, d = cultivate.start_cultivate(doc, planned, max_minutes)
        if ok:
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_OPEN, "出关结算")
    async def handle_open(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        rate = int(self._val("CULTIVATE_EXP_PER_MIN", 20))
        # 原版效率等式（player_efficiency）：加法聚合 1 + 灵根eff + 功法修炼加成 + 辟谷丹
        gongfa_bonus = 0
        for gname in (doc.ext.get("gongfa") or []):
            g = self.item_index.get(gname) or {}
            try:
                gongfa_bonus += float(g.get("修炼加成") or 0)
            except (TypeError, ValueError):
                pass
        ling_bonus = linggen.eff_of(doc)
        buffs = doc.ext.get("buffs") or {}
        big = buffs.get("biguan") if isinstance(buffs.get("biguan"), dict) else {}
        biguan_bonus = float(big.get("bonus", 0) or 0)
        # 对齐原版 biguan_jiesuan：每周期基础修为 = size(默认10) × 境界id × 效率乘区
        base_per_min = int(self._val("CULTIVATE_EXP_PER_REALM", 10)) * (max(0, doc.realm_index) + 1)
        eff_rate = max(1, int(base_per_min * (1 + ling_bonus + gongfa_bonus + biguan_bonus)))
        ok, msg, d = cultivate.end_cultivate(
            doc, time.time(), eff_rate,
            int(self._val("CULTIVATE_MAX_MINUTES", 7200)),
        )
        if ok:
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    # ---- 物品 / 坊市 ----

    async def _bag_text(self, doc: PlayerDoc) -> str:
        inv = await self.db.get_inventory(doc.uid)
        if not inv:
            return "纳戒空空如也。坊市在等你：#商店"
        kinds = len(inv)
        lines = [f"--- 道友的纳戒（共 {kinds} 种）---"]
        for name, qty in list(inv.items())[:20]:
            item = self.item_index.get(name, {})
            lines.append(f"· {name} ×{qty}（{item.get('class', '?')}/{item.get('稀有度', '?')}阶）")
        if kinds > 20:
            lines.append(f"…其余 {kinds - 20} 种略")
        return "\n".join(lines)

    @filter.command(CMD_BAG, "查看纳戒")
    async def handle_bag(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        yield event.plain_result(await self._bag_text(doc))

    @filter.command(CMD_BAG_ALIAS, "查看纳戒（短指令）")
    async def handle_bag_alias(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        yield event.plain_result(await self._bag_text(doc))

    @filter.command(CMD_SHOP, "坊市货架")
    async def handle_shop(self, event: AstrMessageEvent, page: str = "1"):
        if not self._allowed(event):
            return
        markup = float(self._val("SHOP_BUY_MARKUP", 2.0))
        page_items, pages, cur = items.shop_page(self.shop_stock, int(page or 1), 10, markup)
        if self.render_on and page_items:
            shop_data = {
                "title": "坊市", "sub": "常驻 · 限定", "footer": "诸天修仙",
                "cur": cur, "pages": pages,
                "rows": [{"name": e["name"], "cls": e.get("class", "?"),
                          "typ": e.get("type", "") or "—",
                          "price": items.item_buy_price(e, markup)} for e in page_items],
            }
            png = await render.render_panel("shop", shop_data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        lines = [f"--- 坊市（第 {cur}/{pages} 页）---"]
        for e in page_items:
            lines.append(
                f"· {e['name']}（{e.get('class', '?')}｜{e.get('type', '')}）"
                f" {items.item_buy_price(e, markup)} 灵石"
            )
        lines.append(f"购买：#购买 {page_items[0]['name']} 1")
        yield event.plain_result("\n".join(lines))

    async def _trade(self, event: AstrMessageEvent, item_name: str, qty: int, mode: str):
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if not item_name:
            yield event.plain_result("格式：#购买 名字 数量（数量可省略）")
            return
        qty = max(1, qty)
        item = self.item_index.get(item_name)
        if not item:
            yield event.plain_result(f"坊市与行囊中都找不到「{item_name}」。")
            return
        inv = await self.db.get_inventory(doc.uid)
        markup = float(self._val("SHOP_BUY_MARKUP", 2.0))

        if mode == "buy":
            ok, msg, d, gain = items.buy(doc, item, qty, markup)
            if not ok:
                yield event.plain_result(msg)
                return
            async with self.db.transaction():
                await self.db.save_player(d.model_dump())
                await self.db.add_items(doc.uid, gain)
            yield event.plain_result(msg)
            return

        held = inv.get(item_name, 0)
        lack = f"纳戒中「{item_name}」只有 {held} 件，不足 {qty}。"

        if mode == "sell":
            if held < qty:
                yield event.plain_result(lack)
                return
            ok, msg, d = items.sell(doc, item, qty)
            if not ok:
                yield event.plain_result(msg)
                return
            async with self.db.transaction():
                if not await self.db.remove_item(doc.uid, item_name, qty):
                    raise RuntimeError("INSUFFICIENT")
                await self.db.save_player(d.model_dump())
            yield event.plain_result(msg)
            return

        # use：先查库存，再算效果（纯函数），最后事务内扣减+落盘
        if held < qty:
            yield event.plain_result(lack)
            return
        import random as _random
        ok, msg, d, consume = items.use_item(
            doc, item, qty, self._stats(doc).hp,
            linggen_table=self.linggen_table,
            rng=_random.Random(f"{doc.uid}:{time.time()}"),
        )
        if not ok or not consume:
            yield event.plain_result(msg)
            return
        async with self.db.transaction():
            if not await self.db.remove_item(doc.uid, item_name, qty):
                raise RuntimeError("INSUFFICIENT")
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_BUY, "购买物品")
    async def handle_buy(self, event: AstrMessageEvent, item_name: str = "", qty: int = 1):
        if not self._allowed(event):
            return
        async for r in self._trade(event, item_name, qty, "buy"):
            yield r

    @filter.command(CMD_SELL, "出售物品")
    async def handle_sell(self, event: AstrMessageEvent, item_name: str = "", qty: int = 1):
        if not self._allowed(event):
            return
        async for r in self._trade(event, item_name, qty, "sell"):
            yield r

    @filter.command(CMD_USE, "使用物品")
    async def handle_use(self, event: AstrMessageEvent, item_name: str = "", qty: int = 1):
        if not self._allowed(event):
            return
        async for r in self._trade(event, item_name, qty, "use"):
            yield r

    @filter.command(CMD_BREAK, "境界突破")
    async def handle_break(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        import random as _random
        ok, msg, d = cultivate.breakthrough(
            doc, self.content.table(doc.realm_table),
            float(self._val("BREAKTHROUGH_SUCCESS_RATE", 1.0)),
            float(self._val("BREAKTHROUGH_FAIL_PENALTY", 0.3)),
            _random.Random(f"{doc.uid}:{doc.realm_index}:{int(time.time())}"),
        )
        if ok and d.realm_index != doc.realm_index or ok and d.exp != doc.exp:
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    # ---- 装备 / 切磋 ----

    @filter.command(CMD_EQUIP, "穿戴装备")
    async def handle_equip(self, event: AstrMessageEvent, item_name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        item = self.item_index.get((item_name or "").strip())
        if not item:
            yield event.plain_result(f"物品索引中找不到「{item_name}」。")
            return
        ok, msg, old = equipment.wear(doc, item)
        if not ok:
            yield event.plain_result(msg)
            return
        async with self.db.transaction():
            if not await self.db.remove_item(doc.uid, item["name"], 1):
                raise RuntimeError("INSUFFICIENT")
            if old:
                await self.db.add_items(doc.uid, {old: 1})
            await self.db.save_player(doc.model_dump())
        st = self._stats(doc)
        yield event.plain_result(
            f"{msg}\n当前属性：攻击 {st.atk} · 防御 {st.defense} · 血量 {st.hp}"
            + (f" · 暴击 {st.bao:.0%}" if st.bao else "")
        )

    @filter.command(CMD_UNEQUIP, "卸下装备")
    async def handle_unequip(self, event: AstrMessageEvent, slot: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        ok, msg, old = equipment.unequip(doc, (slot or "").strip())
        if not ok:
            yield event.plain_result(msg)
            return
        async with self.db.transaction():
            await self.db.add_items(doc.uid, {old: 1})
            await self.db.save_player(doc.model_dump())
        yield event.plain_result(msg)

    def _equip_text(self, doc: PlayerDoc) -> str:
        cur = doc.ext.get("equipment") or {}
        st = self._stats(doc)
        lines = ["--- 已穿装备 ---"]
        if not cur:
            lines.append("（尚未穿戴任何装备，#装备 名字 进行穿戴）")
        for slot in equipment.SLOTS:
            name = cur.get(slot)
            if not name:
                lines.append(f"· {slot}：（空）")
                continue
            item = self.item_index.get(name, {})
            lines.append(
                f"· {slot}：{name}"
                f"（攻 {item.get('atk', 0)} · 防 {item.get('def', 0)} · 血 {item.get('HP', 0)}"
                + (f" · 暴击 {item.get('bao', 0):.0%}" if item.get("bao") else "")
                + "）"
            )
        lines.append(f"合计：攻击 {st.atk} · 防御 {st.defense} · 血量 {st.hp}"
                     + (f" · 暴击 {st.bao:.0%}" if st.bao else ""))
        return "\n".join(lines)

    @filter.command(CMD_MY_EQUIP, "查看已穿装备")
    async def handle_my_equip(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        yield event.plain_result(self._equip_text(doc))

    def _at_target(self, event: AstrMessageEvent) -> str | None:
        """取消息里第一个 @ 的目标（排除机器人自己）。

        QQ 官方平台只为 @ 机器人生成 At 组件；@ 群员时腾讯推送的是
        文本标记 <qqbot-at-user id="openid"/>（或 <@openid>），留在 message_str
        里，因此两条路径都要查。
        """
        import re
        comps = getattr(getattr(event, "message_obj", None), "message", None) or []
        exclude = {str(event.get_self_id() or ""), "qq_official"}
        for c in comps:
            ctype = getattr(c, "type", None) or c.__class__.__name__
            if str(ctype).lower() != "at":
                continue
            qq = str(getattr(c, "qq", "") or "")
            if qq and qq not in exclude:
                return qq
        text = event.message_str or ""
        for pat in (r'<qqbot-at-user\s+id="([^"]+)"', r"<@!?(\w+)>"):
            m = re.search(pat, text)
            if m and m.group(1) not in exclude:
                return m.group(1)
        return None

    @filter.command(CMD_SPAR, "切磋")
    async def handle_spar(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        target_uid = self._at_target(event)
        if not target_uid:
            yield event.plain_result(f"请 @ 一位道友再发起{CMD_SPAR}。")
            return
        if target_uid == doc.uid:
            yield event.plain_result("道友岂能与自己过招？")
            return
        now = time.time()
        cd = int(self._val("SPAR_COOLDOWN_SECONDS", 60))
        last = float(doc.ext.get("spar_ts") or 0)
        if now - last < cd:
            yield event.plain_result(f"意犹未尽，气血未复，{int(cd - (now - last))} 秒后再战。")
            return
        raw = await self.db.get_player(target_uid)
        if not raw:
            yield event.plain_result("对方尚未踏入仙途，无法切磋。")
            return
        foe = PlayerDoc(**raw)

        table_a = self.content.table(doc.realm_table)
        table_b = self.content.table(foe.realm_table)
        sa, sb = self._stats(doc), self._stats(foe)
        name_a = doc.name or doc.uid[:8] + "…"
        name_b = foe.name or foe.uid[:8] + "…"

        import random as _random
        rng = _random.Random(f"{doc.uid}:{foe.uid}:{now}")
        winner, log = battle.spar(
            battle.Unit(name_a, sa.atk, sa.defense, sa.hp, sa.bao),
            battle.Unit(name_b, sb.atk, sb.defense, sb.hp, sb.bao),
            rng,
        )
        doc.ext["spar_ts"] = now
        await self.db.save_player(doc.model_dump())

        result = (
            f"切磋结果：{name_a} 胜！" if winner == 0
            else f"切磋结果：{name_b} 胜！" if winner == 1
            else "切磋结果：势均力敌，平局！"
        )
        shown = log[:8] + [f"…（共 {len(log)} 回合）"] if len(log) > 9 else log
        if self.render_on:
            battle_data = {
                "title": "切磋", "sub": "友切无伤", "footer": "诸天修仙",
                "side_a": {"name": name_a, "atk": sa.atk, "defense": sa.defense, "hp": sa.hp},
                "side_b": {"name": name_b, "atk": sb.atk, "defense": sb.defense, "hp": sb.hp},
                "log": shown, "result": result, "extras": [],
            }
            png = await render.render_panel("battle", battle_data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        yield event.plain_result(
            f"【{name_a}】攻 {sa.atk} · 防 {sa.defense} · 血 {sa.hp}"
            f"  VS  【{name_b}】攻 {sb.atk} · 防 {sb.defense} · 血 {sb.hp}\n"
            + "\n".join(shown) + "\n" + result
        )

    # ---- 世界 Boss / 疗伤 ----

    async def _boss_data(self) -> dict:
        b = await self._ensure_boss()
        ledger = await self.db.boss_ledger(b["round"])
        return {
            "round": b["round"],
            "alive": b["alive"],
            "status": "存活" if b["alive"] else "已被讨伐（等待刷新）",
            "health": b["health"], "health_max": b["health_max"],
            "pct": round(b["health"] / b["health_max"] * 100, 1) if b["health_max"] else 0,
            "reward": b["reward"],
            "ledger": list(ledger.items())[:5],
        }

    async def _boss_text(self) -> str:
        b = await self._ensure_boss()
        status = "存活" if b["alive"] else "已被讨伐（等待刷新）"
        lines = [
            f"--- 世界 Boss · 第 {b['round']} 轮 ---",
            f"状态：{status}",
            f"血量：{b['health']} / {b['health_max']}",
            f"奖池：{b['reward']} 灵石（击杀者额外 +10%，按贡献分配）",
        ]
        ledger = await self.db.boss_ledger(b["round"])
        if ledger:
            lines.append("本轮贡献榜：")
            for i, (name, dmg) in enumerate(list(ledger.values())[:5], 1):
                lines.append(f"  {i}. {name} — {dmg}")
        else:
            lines.append("本轮尚无人讨伐。")
        return "\n".join(lines)

    async def _boss_reply(self, event: AstrMessageEvent):
        text = await self._boss_text()
        if self.render_on:
            png = await render.render_panel("boss", await self._boss_data(), self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        yield event.plain_result(text)

    @filter.command(CMD_BOSS, "世界 Boss 状态")
    async def handle_boss_view(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        async for r in self._boss_reply(event):
            yield r

    @filter.command(CMD_BOSS_ALIAS, "世界 Boss 状态（短指令）")
    async def handle_boss_view_alias(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        async for r in self._boss_reply(event):
            yield r

    @filter.command(CMD_BOSS_FIGHT, "讨伐世界 Boss")
    async def handle_boss_fight(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return

        b = await self._ensure_boss()
        if not b["alive"]:
            yield event.plain_result("妖王已被讨伐，正在积蓄力量，稍后再来。")
            return

        now = time.time()
        cd = int(self._val("BOSS_CD_SECONDS", 300))
        last = float(doc.ext.get("boss_ts") or 0)
        if now - last < cd:
            yield event.plain_result(f"刚刚一战消耗了太多气力，{int(cd - (now - last))} 秒后再战。")
            return

        hp_cur, hp_max = self._hp_pair(doc)
        if hp_cur <= hp_max * 0.1:
            yield event.plain_result("还是先疗伤吧，别急着参战了。")
            return

        st = self._stats(doc)
        name = doc.name or doc.uid[:8] + "…"
        import random as _random
        rng = _random.Random(f"{doc.uid}:{b['round']}:{now}")

        shadow = boss.make_shadow(st.atk, st.defense, st.hp, rng)
        me = battle.Unit(name, st.atk, st.defense, hp_cur, st.bao)
        won, log, hp_left, _ = battle.spar_full(me, shadow, rng)
        dmg_to_boss = boss.boss_damage(bool(won == 0), st.atk, shadow.defense, b["health_max"], rng)
        if doc.ext.get("imperial"):
            dmg_to_boss = int(dmg_to_boss * 1.2)   # 认主帝兵特效：兵魂助战，讨伐伤害 +20%
        hp_lost = max(0, hp_cur - hp_left)

        doc.ext["boss_ts"] = now
        doc.ext["hp"] = hp_left
        await self.db.save_player(doc.model_dump())
        left = await self.db.damage_boss(b["round"], doc.uid, name, dmg_to_boss)

        verdict = (
            f"{name}击败了妖王幻影，重创妖王本体！" if won == 0
            else f"{name}不敌妖王幻影，但拼死重创了妖王本体！"
        )
        shown = log[:6] + [f"…（共 {len(log)} 回合）"] if len(log) > 7 else log
        fight_extras = [f"战损 {hp_lost} 气血", f"对妖王伤害 {dmg_to_boss}"]
        if left <= 0:
            fight_extras.append("妖王被讨伐！")
        elif left <= b["health_max"] * 0.25:
            fight_extras.append("妖王濒死！")
        if self.render_on:
            fight_data = {
                "title": f"讨伐妖王 · 第 {b['round']} 轮", "sub": name, "footer": "诸天修仙",
                "side_a": {"name": name, "atk": st.atk, "defense": st.defense, "hp": hp_cur},
                "side_b": {"name": "妖王幻影", "atk": shadow.atk, "defense": shadow.defense, "hp": shadow.hp},
                "log": shown, "result": verdict, "extras": fight_extras,
            }
            png = await render.render_panel("battle", fight_data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        lines = [
            "\n".join(shown),
            f"{verdict}\n战损 {hp_lost} 点气血，对妖王造成 {dmg_to_boss} 点伤害。",
        ]

        if left <= 0:
            ledger = await self.db.boss_ledger(b["round"])
            shares = boss.split_rewards(b["reward"], ledger, doc.uid)
            paid = []
            for uid, _n, share in shares:
                raw = await self.db.get_player(uid)
                if raw:
                    target = PlayerDoc(**raw)
                    target.stones += share
                    await self.db.save_player(target.model_dump())
                    paid.append(f"· {_n} +{share} 灵石")
            nxt_health, nxt_reward = boss.boss_specs(b["round"] + 1)
            await self.db.init_boss(b["round"] + 1, nxt_health, nxt_reward)
            lines.append(
                f"【全服公告】妖王被 {name} 讨伐成功！\n"
                f"奖池 {b['reward']} 灵石按贡献分配：\n" + "\n".join(paid[:8])
                + f"\n第 {b['round'] + 1} 轮妖王已苏醒（血量 {nxt_health}，奖池 {nxt_reward}）。"
            )
        elif left <= b["health_max"] * 0.25:
            lines.append("妖王已濒死，血条见底！")
        yield event.plain_result("\n".join(lines))

    # ---- 黑暗动乱帝战（对齐原版 BOSS2） ----

    async def _avg_atk(self) -> tuple[int, int]:
        """全服玩家平均攻击（黑暗 Boss 血量基数）→ (avg_atk, 人数)。"""
        uids = await self.db.all_player_uids()
        atks = []
        for uid in uids:
            raw = await self.db.get_player(uid)
            if raw:
                p = PlayerDoc(**raw)
                atks.append(self._stats(p).atk)
        if not atks:
            return 0, 0
        return int(sum(atks) / len(atks)), len(atks)

    @filter.command(CMD_DARK_OPEN, "开启黑暗动乱")
    async def handle_dark_open(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        if not event.is_admin:
            yield event.plain_result("唯有道祖级人物（管理员）才能撼动岁月，唤出禁区至尊。")
            return
        cur = await self.db.get_dark_boss()
        if cur and cur["alive"]:
            yield event.plain_result("各大禁区至尊早已出世。")
            return
        avg_atk, count = await self._avg_atk()
        if count == 0:
            yield event.plain_result("没有符合条件的玩家，黑暗动乱开启失败。")
            return
        health, reward, atk, defense = boss.dark_specs(avg_atk, count)
        nxt_round = (cur["round"] + 1) if cur else 1
        await self.db.init_dark_boss(nxt_round, health, reward, atk, defense)
        yield event.plain_result(
            f"禁区至尊提前出世，黑暗动乱开启！（第 {nxt_round} 轮）\n"
            f"血量 {health}｜奖池 {reward}｜参战人数基准 {count}\n"
            f"强者可「{CMD_DARK_FIGHT}」参与帝战。"
        )

    @filter.command(CMD_DARK_CLOSE, "关闭黑暗动乱")
    async def handle_dark_close(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        if not event.is_admin:
            yield event.plain_result("此权柄唯管理员可执。")
            return
        cur = await self.db.get_dark_boss()
        if not cur or not cur["alive"]:
            yield event.plain_result("黑暗动乱早已结束。")
            return
        await self.db.init_dark_boss(cur["round"], cur["health_max"], cur["reward"], cur["atk"], cur["defense"])
        # 关闭 = 掐断时间线：直接置为死亡态（保留账本）
        raw = await self.db.get_dark_boss()
        if raw:
            import sqlite3 as _s
            conn = self.db.conn
            await conn.execute(
                "UPDATE dark_boss SET alive = 0, killed_at = ? WHERE id = 1", (time.time(),))
            await conn.commit()
        yield event.plain_result("如梦道祖睁眼望向诸天，将这段黑暗动乱的历史直接抹去。")

    @filter.command(CMD_DARK_STATUS, "禁区至尊状态")
    async def handle_dark_status(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        cur = await self.db.get_dark_boss()
        if not cur or (not cur["alive"] and time.time() - cur["killed_at"] < 86400):
            if cur and not cur["alive"]:
                nxt = time.strftime("%H:%M", time.localtime(cur["killed_at"] + 86400))
                yield event.plain_result(f"黑暗动乱刚被平定，至尊恢复元气中，下次开启约 {nxt}。")
            else:
                yield event.plain_result("黑暗动乱还未到来！")
            return
        if not cur:
            yield event.plain_result("黑暗动乱还未到来！（管理员可「#开启黑暗动乱」）")
            return
        if not cur["alive"]:
            yield event.plain_result("黑暗动乱刚被平定，可由管理员重新开启。")
            return
        ledger = await self.db.dark_ledger(cur["round"])
        top = sorted(ledger.items(), key=lambda kv: -kv[1][1])[:5]
        lines = [
            f"--- 黑暗动乱 · 第 {cur['round']} 轮 ---",
            f"禁区至尊血量：{cur['health']} / {cur['health_max']}",
            f"奖池：{cur['reward']} 灵石",
        ]
        if top:
            lines.append("贡献榜：" + "、".join(f"{n}({d})" for n, d in top))
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_DARK_RANK, "黑暗动乱贡献榜")
    async def handle_dark_rank(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        cur = await self.db.get_dark_boss()
        if not cur:
            yield event.plain_result("黑暗动乱还未到来！")
            return
        ledger = await self.db.dark_ledger(cur["round"])
        if not ledger:
            yield event.plain_result("尚无人参战。")
            return
        top = sorted(ledger.items(), key=lambda kv: -kv[1][1])[:10]
        lines = [f"--- 帝战贡献榜 · 第 {cur['round']} 轮 ---"]
        for i, (uid, (n, dmg)) in enumerate(top, 1):
            lines.append(f"{i}. {n}：{dmg}")
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_DARK_FIGHT, "平定黑暗动乱")
    async def handle_dark_fight(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        b = await self.db.get_dark_boss()
        if not b or not b["alive"]:
            yield event.plain_result("黑暗动乱还未到来！")
            return
        if not b["alive"] and time.time() - b["killed_at"] < 86400:
            yield event.plain_result("黑暗动乱刚刚被平定，至尊还在恢复元气（24 小时冷却）。")
            return
        realm_id = max(0, doc.realm_index) + 1
        if realm_id < 12:
            yield event.plain_result("境界未至（需第 12 境），尚无资格参与帝战。")
            return
        now = time.time()
        if now - float(doc.ext.get("dark_ts") or 0) < 300:
            left = int(300 - (now - float(doc.ext["dark_ts"])))
            yield event.plain_result(f"刚刚一战消耗了太多法力，{left} 秒后再战。")
            return
        hp_cur, hp_max = self._hp_pair(doc)
        if hp_cur <= hp_max * 0.1:
            yield event.plain_result("生命如风中残烛，先疗伤吧，别急着参战帝战。")
            return
        st = self._stats(doc)
        name = doc.name or doc.uid[:8] + "…"
        import random as _random
        rng = _random.Random(f"{doc.uid}:dark:{b['round']}:{now}")
        shadow = battle.Unit(f"禁区至尊·第{b['round']}轮", b["atk"], b["defense"], max(1, b["health_max"] // 50), 0.05)
        me = battle.Unit(name, st.atk, st.defense, hp_cur, st.bao)
        won, log, hp_left, _ = battle.spar_full(me, shadow, rng, max_rounds=20)
        won_bool = won == 0
        dmg = boss.dark_damage(won_bool, st.atk, b["defense"], b["health_max"], rng)
        doc.ext["dark_ts"] = now
        doc.ext["hp"] = hp_left if won_bool else 0  # 战败代价：血量清零（原版语义）
        await self.db.save_player(doc.model_dump())
        left = await self.db.damage_dark_boss(b["round"], doc.uid, name, dmg)
        verdict = (
            f"{name}击败了禁区至尊法身，撼动大道，造成伤害 {dmg}！"
            if won_bool else
            f"{name}被至尊法身击败，只留下了 {dmg} 伤害的血痕。"
        )
        lines = [verdict, f"至尊剩余血量：{max(0, left)} / {b['health_max']}"]
        if not won_bool:
            lines.append("你重伤倒地（气血归零），快「#疗伤」恢复。")
        if left <= 0:
            ledger = await self.db.dark_ledger(b["round"])
            shares = boss.split_rewards(b["reward"], ledger, doc.uid)
            paid = []
            for uid, _n, share in shares:
                raw2 = await self.db.get_player(uid)
                if raw2:
                    t = PlayerDoc(**raw2)
                    t.stones += share
                    await self.db.save_player(t.model_dump())
                    paid.append(f"· {_n} +{share} 灵石")
            lines.append(
                f"【全服公告】黑暗动乱被 {name} 率先平定！成仙之路开启！\n"
                f"奖池 {b['reward']} 灵石按贡献分配：\n" + "\n".join(paid[:8])
            )
        yield event.plain_result("\n".join(lines))

    # ---- 锻神池 · 炼神魄（对齐原版 pata/DSC） ----

    @filter.command(CMD_SHENPO, "炼神魄")
    async def handle_shenpo(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        async for r in self._shenpo_round(event, one_shot=True):
            yield r

    @filter.command(CMD_SHENPO_ALL, "一键炼神魄")
    async def handle_shenpo_all(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        async for r in self._shenpo_round(event, one_shot=False):
            yield r

    async def _shenpo_round(self, event: AstrMessageEvent, one_shot: bool):
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        seg = int(doc.ext.get("shenpo", 0) or 0)
        if seg >= 50000:
            yield event.plain_result("神魄已臻圆满（50000 段上限）。")
            return
        now = time.time()
        if now - float(doc.ext.get("shenpo_ts") or 0) < 120:
            left = int(120 - (now - float(doc.ext["shenpo_ts"])))
            yield event.plain_result(f"锻神池灵力未复，{left} 秒后再来。")
            return
        st = self._stats(doc)
        name = doc.name or doc.uid[:8] + "…"
        import random as _random
        rng = _random.Random(f"{doc.uid}:shenpo:{now}")
        rounds_won = 0
        seg_gain = 0
        xueqi_gain = 0
        exp_lost = 0
        log: list[str] = []
        while True:
            seg_cur = seg + seg_gain
            health, atk_b, def_b, reward = boss.shenpo_specs(max(1, seg_cur))
            boss_hp = health
            alive = True
            # 逐回合：玩家每回合回满血（原版语义），看能否在倒下前炼化此段
            while boss_hp > 0:
                dmg_p = battle.harm(st.atk, def_b, rng)[0]
                boss_hp -= dmg_p
                dmg_b = battle.harm(atk_b, max(1, int(st.defense * 0.1)), rng)[0]
                if dmg_b >= st.hp:
                    alive = False
                    break
            doc.ext["shenpo_ts"] = now
            if alive:
                rounds_won += 1
                seg_gain += 5
                xueqi_gain += reward
                log.append(f"第 {rounds_won} 段（{seg_cur}）：炼化成功，血气 +{reward}")
                if one_shot:
                    break
            else:
                exp_lost = reward * 2
                log.append(f"第 {rounds_won + 1} 段（{seg_cur}）：锻神池中神魂受创，修为 -{exp_lost}")
                break
        d = doc.model_copy(deep=True)
        d.ext["shenpo"] = min(50000, seg + seg_gain)
        d.ext["xueqi"] = int(d.ext.get("xueqi", 0) or 0) + xueqi_gain
        d.exp = max(0, d.exp - exp_lost)
        await self.db.save_player(d.model_dump())
        head = (
            f"锻神池修行归来：神魄 {seg} → {d.ext['shenpo']} 段"
            + (f"（连破 {rounds_won} 段）" if rounds_won > 1 else "")
        )
        tail = f"血气累计 +{xueqi_gain}" if xueqi_gain else f"修为 -{exp_lost}（参悟失败）"
        yield event.plain_result(head + "\n" + "\n".join(log[-5:]) + f"\n{tail}")

    @filter.command(CMD_HEAL, "灵石疗伤")
    async def handle_heal(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        hp_cur, hp_max = self._hp_pair(doc)
        if hp_cur >= hp_max:
            yield event.plain_result("气血正满，无需疗伤。")
            return
        cost = max(100, int(-(-(hp_max - hp_cur) // 1000)))  # 缺失×0.001 向上取整，最少 100
        if doc.stones < cost:
            yield event.plain_result(
                f"灵石不足：疗伤需 {cost}，道友只有 {doc.stones}。"
            )
            return
        d = doc.model_copy(update={"stones": doc.stones - cost})
        d.ext["hp"] = hp_max
        await self.db.save_player(d.model_dump())
        yield event.plain_result(
            f"花费 {cost} 灵石疗伤，气血尽复：{hp_max} / {hp_max}。"
        )

    # ---- 秘境 ----

    def _session(self, doc: PlayerDoc) -> secret.Session | None:
        raw = doc.ext.get("explore")
        if not raw:
            return None
        fields = secret.Session.__dataclass_fields__
        return secret.Session(**{k: v for k, v in raw.items() if k in fields})

    async def _settle_explore(self, doc: PlayerDoc, sess: secret.Session, reason: str) -> str:
        """发放探索收益并清会话（事务：灵石 + 物品 + 状态复位）。"""
        d = doc.model_copy()
        d.stones += sess.stones
        d.state = "空闲"
        d.state_start = 0.0
        d.ext.pop("explore", None)
        fund_note = ""
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if sess.items:
                await self.db.add_items(doc.uid, sess.items)
            if sess.sect_name and sess.boss_kills:
                sdoc = await self.db.get_sect(sess.sect_name)
                if sdoc:
                    bonus = 5000 * sess.boss_kills
                    await self.db.update_sect(sess.sect_name, sdoc["level"], sdoc["fund"] + bonus)
                    fund_note = f"\n宗门基金 +{bonus}（守关 Boss ×{sess.boss_kills}），现 {sdoc['fund'] + bonus}"
        lines = [
            f"【秘境结算 · {sess.place}】（{reason}，共探 {sess.floor} 层）",
            f"灵石 +{sess.stones}",
        ]
        if sess.items:
            lines.append("物品：" + "、".join(f"{n}×{q}" for n, q in sess.items.items()))
        else:
            lines.append("物品：无")
        if fund_note:
            lines.append(fund_note.strip())
        return "\n".join(lines)

    @filter.command(CMD_SECRET, "秘境列表")
    async def handle_secret(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        table_now = self.content.table(doc.realm_table)
        places_rows = []
        for name, (gate, _f, desc) in secret.PLACES.items():
            places_rows.append({
                "name": name, "open": doc.realm_index >= gate, "desc": desc,
                "gate_name": table_now[min(gate, len(table_now) - 1)]["level"],
            })
        sess = self._session(doc)
        session_note = (
            f"你正在【{sess.place}】第 {sess.floor} 层 · #寻宝 继续 · #逃离 撤离" if sess else ""
        )
        if self.render_on:
            secret_data = {
                "title": "秘境名录", "footer": "诸天修仙",
                "places": places_rows, "session_note": session_note,
            }
            png = await render.render_panel("secret", secret_data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        lines = ["--- 秘境名录 ---"]
        for name, (gate, _f, desc) in secret.PLACES.items():
            mark = "✅" if doc.realm_index >= gate else f"🔒需{table_now[min(gate, len(table_now)-1)]['level']}"
            lines.append(f"· {name}（{mark}）：{desc}")
        if sess:
            lines.append(f"※ 你正在【{sess.place}】第 {sess.floor} 层，发「{CMD_SEARCH}」继续寻宝，「{CMD_FLEE}」撤离。")
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_ENTER, "降临秘境")
    async def handle_enter(self, event: AstrMessageEvent, place: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if self._session(doc):
            yield event.plain_result("道友已在秘境之中，何来再降临之说？")
            return
        if doc.state != "空闲":
            yield event.plain_result(f"道友正在「{doc.state}」中，无法分心。")
            return
        name = (place or "").strip()
        if name not in secret.PLACES:
            yield event.plain_result(f"格式：{CMD_ENTER} 名字（可选：{' / '.join(secret.PLACES)}）")
            return
        gate = secret.PLACES[name][0]
        if doc.realm_index < gate:
            table = self.content.table(doc.realm_table)
            need = table[min(gate, len(table) - 1)]["level"]
            yield event.plain_result(f"【{name}】凶险异常，需修为达到【{need}】方可降临。")
            return
        hp_cur, hp_max = self._hp_pair(doc)
        if hp_cur <= hp_max * 0.3:
            yield event.plain_result("气血太虚，先疗伤再进秘境。")
            return
        d = doc.model_copy()
        d.state = "秘境中"
        sess = secret.Session(place=name)
        d.ext["explore"] = {"place": sess.place, "floor": 0, "stones": 0, "items": {}, "log": []}
        await self.db.save_player(d.model_dump())
        yield event.plain_result(
            f"道友降临【{name}】。{secret.PLACES[name][2]}\n"
            f"发「{CMD_SEARCH}」寻宝，发「{CMD_FLEE}」携带收获撤离。"
        )

    @filter.command(CMD_SEARCH, "秘境寻宝")
    async def handle_search(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        sess = self._session(doc)
        if not sess:
            yield event.plain_result(f"道友不在秘境之中。先「{CMD_ENTER} 名字」降临。")
            return
        hp_cur, hp_max = self._hp_pair(doc)
        if hp_cur <= hp_max * 0.1:
            yield event.plain_result("气血将尽，强寻恐有性命之忧。发「{0}」撤离或先「{1}」".format(CMD_FLEE, CMD_HEAL))
            return
        import random as _random
        rng = _random.Random(f"{doc.uid}:{sess.floor}:{time.time()}")
        st = self._stats(doc)
        table = self.content.table(doc.realm_table)
        entry = realm_entry(doc, table)
        base = (st.atk, st.defense, st.hp)
        me = battle.Unit(doc.name or doc.uid[:8] + "…", st.atk, st.defense, hp_cur, st.bao)
        sess, me, flavor, fled = secret.explore(
            sess, base, me, self.drop_pool, rng, sect_mode=bool(sess.sect_name),
        )
        d = doc.model_copy()
        d.ext["hp"] = me.hp
        d.ext["explore"] = {
            "place": sess.place, "floor": sess.floor, "stones": sess.stones,
            "items": sess.items, "log": sess.log[-30:], "factor": sess.factor,
            "sect_name": sess.sect_name, "boss_kills": sess.boss_kills,
        }
        if not sess.sect_name:  # 每日任务 3：秘境探索计数（宗门秘境不计，对齐原版"沉迷不计入"）
            await self.db.add_daily_secret(doc.uid)
        if fled:
            await self.db.save_player(d.model_dump())
            d.state = "空闲"
            text = await self._settle_explore(d, sess, reason="血战脱身")
            yield event.plain_result(f"{flavor}\n{text}")
            return
        d.state = "秘境中"
        await self.db.save_player(d.model_dump())
        yield event.plain_result(
            f"{flavor}\n第 {sess.floor} 层 · 本次已获 {sess.stones} 灵石 · 气血 {me.hp}/{st.hp}"
        )

    @filter.command(CMD_FLEE, "秘境撤离")
    async def handle_flee(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        sess = self._session(doc)
        if not sess:
            yield event.plain_result("道友不在秘境之中。")
            return
        text = await self._settle_explore(doc, sess, reason="全身而退")
        yield event.plain_result(text)

    # ---- 宗门 / 天地榜 ----

    async def _sect_members(self, name: str) -> list[tuple[str, str]]:
        """宗门成员：uid → (名字)。文档全扫（群服规模可接受）。"""
        members = []
        for p in await self.db.all_players():
            if (p.get("ext") or {}).get("sect") == name:
                members.append((p["uid"], p.get("name") or p["uid"][:8] + "…"))
        return members

    @filter.command(CMD_SECT_CREATE, "创建宗门")
    async def handle_sect_create(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = (name or "").strip()
        if not name or len(name) > 12:
            yield event.plain_result(f"格式：{CMD_SECT_CREATE} 名字（12 字以内）")
            return
        ok, msg = sect.can_create(doc)
        if not ok:
            yield event.plain_result(msg)
            return
        if await self.db.get_sect(name):
            yield event.plain_result(f"「{name}」之名已被占，请另起宗号。")
            return
        d = doc.model_copy(update={"stones": doc.stones - sect.CREATE_COST})
        d.ext["sect"] = name
        async with self.db.transaction():
            await self.db.create_sect(name, doc.uid, time.time())
            await self.db.save_player(d.model_dump())
        yield event.plain_result(
            f"【{name}】立宗成功！道友为开派宗主。\n"
            f"立宗花费 {sect.CREATE_COST} 灵石，当前等级：{sect.level_title(1)}（{sect.member_limit(1)} 人上限）"
        )

    @filter.command(CMD_SECT_JOIN, "加入宗门")
    async def handle_sect_join(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if doc.ext.get("sect"):
            yield event.plain_result("道友已有宗门，先「#退出宗门」再投他派。")
            return
        name = (name or "").strip()
        target = await self.db.get_sect(name)
        if not target:
            yield event.plain_result(f"查无此宗：「{name}」。可发「{CMD_SECT_LIST}」查看。")
            return
        members = await self._sect_members(name)
        limit = sect.member_limit(target["level"])
        if len(members) >= limit:
            yield event.plain_result(f"【{name}】人满（{len(members)}/{limit}），升级宗门可扩员。")
            return
        d = doc.model_copy()
        d.ext["sect"] = name
        await self.db.save_player(d.model_dump())
        yield event.plain_result(f"道友已入【{name}】门墙（{len(members) + 1}/{limit}）。")

    @filter.command(CMD_SECT_QUIT, "退出宗门")
    async def handle_sect_quit(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = doc.ext.get("sect")
        if not name:
            yield event.plain_result("道友本就无宗无门。")
            return
        target = await self.db.get_sect(name)
        if target and target["master_uid"] == doc.uid:
            yield event.plain_result("宗主不可轻退宗门（传位功能后续开放）。")
            return
        d = doc.model_copy()
        d.ext.pop("sect", None)
        await self.db.save_player(d.model_dump())
        yield event.plain_result(f"已退出【{name}】，从此山高水远。")

    @filter.command(CMD_SECT_LIST, "宗门列表")
    async def handle_sect_list(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        rows = await self.db.all_sects()
        if not rows:
            yield event.plain_result(f"天下尚无宗门立派。首个立宗者可发「{CMD_SECT_CREATE} 名字」。")
            return
        lines = ["--- 宗门列表 ---"]
        for s in rows[:10]:
            members = await self._sect_members(s["name"])
            lines.append(
                f"· 【{s['name']}】{sect.level_title(s['level'])}"
                f"（{s['level']}级）基金 {s['fund']} · 成员 {len(members)}/{sect.member_limit(s['level'])}"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_SECT_MINE, "我的宗门")
    async def handle_sect_mine(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = doc.ext.get("sect")
        if not name:
            yield event.plain_result(f"道友尚无宗门。可「{CMD_SECT_LIST}」查看天下宗门。")
            return
        target = await self.db.get_sect(name)
        if not target:
            d = doc.model_copy()
            d.ext.pop("sect", None)
            await self.db.save_player(d.model_dump())
            yield event.plain_result("所属宗门已不复存在，名籍已清。")
            return
        members = await self._sect_members(name)
        is_master = target["master_uid"] == doc.uid
        lines = [
            f"--- 【{name}】 ---",
            f"等级：{target['level']}（{sect.level_title(target['level'])}）· 基金 {target['fund']} 灵石",
            f"成员 {len(members)}/{sect.member_limit(target['level'])}：" + "、".join(n for _, n in members[:10]),
            f"身份：{'宗主' if is_master else '弟子'}",
            f"升级费用（宗主操作）：{sect.upgrade_cost(target['level'])}（取自基金）",
        ]
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_SECT_DONATE, "宗门捐赠灵石")
    async def handle_sect_donate(self, event: AstrMessageEvent, amount: int = 0):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = doc.ext.get("sect")
        if not name:
            yield event.plain_result("道友尚无宗门。")
            return
        if amount < 1:
            yield event.plain_result(f"格式：{CMD_SECT_DONATE} 数量")
            return
        if doc.stones < amount:
            yield event.plain_result(f"灵石不足：欲捐 {amount}，实有 {doc.stones}。")
            return
        target = await self.db.get_sect(name)
        if not target:
            yield event.plain_result("宗门数据异常，请稍后再试。")
            return
        d = doc.model_copy(update={"stones": doc.stones - amount})
        d.ext["sect_contrib"] = int(d.ext.get("sect_contrib", 0)) + amount
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.update_sect(name, target["level"], target["fund"] + amount)
        yield event.plain_result(
            f"道友向【{name}】捐献 {amount} 灵石，基金已达 {target['fund'] + amount}。\n"
            f"个人贡献度 {d.ext['sect_contrib']}（可于宗门商店兑换）。"
        )

    @filter.command(CMD_SECT_UP, "升级宗门")
    async def handle_sect_up(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = doc.ext.get("sect")
        if not name:
            yield event.plain_result("道友尚无宗门。")
            return
        target = await self.db.get_sect(name)
        if not target:
            yield event.plain_result("宗门数据异常，请稍后再试。")
            return
        if target["master_uid"] != doc.uid:
            yield event.plain_result("只有宗主可以升级宗门。")
            return
        if target["level"] >= sect.MAX_LEVEL:
            yield event.plain_result("宗门已至至尊之境，无可再升。")
            return
        cost = sect.upgrade_cost(target["level"])
        if target["fund"] < cost:
            yield event.plain_result(
                f"基金不足：升级需 {cost}，现有 {target['fund']}。可「{CMD_SECT_DONATE} 数量」众筹。"
            )
            return
        new_level = target["level"] + 1
        await self.db.update_sect(name, new_level, target["fund"] - cost)
        yield event.plain_result(
            f"【{name}】升至 {new_level} 级：{sect.level_title(new_level)}！\n"
            f"成员上限扩至 {sect.member_limit(new_level)} 人，耗基金 {cost}。"
        )

    @filter.command(CMD_RANK, "修仙排行")
    async def handle_rank(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        players = await self.db.all_players()
        if not players:
            yield event.plain_result("尚无人踏入仙途。")
            return
        table_cache: dict[str, list[dict]] = {}

        def realm_name(p: dict) -> str:
            tkey = p.get("realm_table") or "Level/练气境界"
            if tkey not in table_cache:
                table_cache[tkey] = self.content.table(tkey) or []
            t = table_cache[tkey]
            if not t:
                return "未知"
            e = t[min(int(p.get("realm_index", 0)), len(t) - 1)]
            return str(e.get("level", "未知"))

        def display(p: dict) -> str:
            return p.get("name") or p["uid"][:8] + "…"

        by_exp = sorted(players, key=lambda p: -int(p.get("exp", 0)))[:10]
        by_stones = sorted(players, key=lambda p: -int(p.get("stones", 0)))[:10]
        rank_data = {
            "by_exp": [{"name": display(p), "realm": realm_name(p), "exp": p.get("exp", 0)} for p in by_exp],
            "by_stones": [{"name": display(p), "stones": p.get("stones", 0)} for p in by_stones],
        }
        if self.render_on:
            png = await render.render_panel("rank", rank_data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        lines = ["--- 天地榜 · 修为前十 ---"]
        for i, p in enumerate(by_exp, 1):
            lines.append(f"{i}. {display(p)}（{realm_name(p)}）修为 {p.get('exp', 0)}")
        lines.append("--- 天地榜 · 富甲前十 ---")
        for i, p in enumerate(by_stones, 1):
            lines.append(f"{i}. {display(p)} 灵石 {p.get('stones', 0)}")
        yield event.plain_result("\n".join(lines))

    # ---- 装备强化 / 宗门俸禄 / 转账 / 拍卖行（M4） ----

    @filter.command(CMD_ENHANCE, "强化装备")
    async def handle_enhance(self, event: AstrMessageEvent, slot: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        slot = (slot or "").strip()
        if slot not in equipment.SLOTS:
            yield event.plain_result(f"格式：{CMD_ENHANCE} 部位（可选：{' / '.join(equipment.SLOTS)}）")
            return
        cur_eq = (doc.ext.get("equipment") or {}).get(slot)
        if not cur_eq:
            yield event.plain_result(f"{slot}位尚未穿戴装备。")
            return
        enh = doc.ext.setdefault("enh", {})
        level = min(max(int(enh.get(slot, 0) or 0), 0), equipment.ENHANCE_MAX)
        if level >= equipment.ENHANCE_MAX:
            yield event.plain_result(f"「{cur_eq}」已强化至 +{equipment.ENHANCE_MAX}，臻于极致。")
            return
        cost = equipment.enhance_cost(level)
        if doc.stones < cost:
            yield event.plain_result(f"灵石不足：强化需 {cost}，道友只有 {doc.stones}。")
            return
        import random as _random
        rate = equipment.enhance_rate(level)
        ok = _random.Random(f"{doc.uid}:{slot}:{level}:{time.time()}").random() < rate
        d = doc.model_copy(update={"stones": doc.stones - cost})
        if ok:
            enh[slot] = level + 1
            d.ext["enh"] = enh
        await self.db.save_player(d.model_dump())
        if ok:
            st = self._stats(d)
            yield event.plain_result(
                f"强化成功！「{cur_eq}」升至 +{level + 1}（成功率 {rate:.0%}，耗 {cost} 灵石）。\n"
                f"当前属性：攻击 {st.atk} · 防御 {st.defense} · 血量 {st.hp}"
            )
        else:
            yield event.plain_result(
                f"强化失败……灵石消散（成功率 {rate:.0%}，耗 {cost}）。装备无损，再接再厉。"
            )

    @filter.command(CMD_SALARY, "宗门俸禄")
    async def handle_salary(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = doc.ext.get("sect")
        if not name:
            yield event.plain_result("道友尚无宗门，何来俸禄。")
            return
        target = await self.db.get_sect(name)
        if not target:
            yield event.plain_result("宗门数据异常，请稍后再试。")
            return
        now = time.time()
        last = float(doc.ext.get("salary_ts") or 0)
        if now - last < 22 * 3600:
            remain = int(22 * 3600 - (now - last))
            yield event.plain_result(f"今日俸禄已领，{remain // 3600} 时 {(remain % 3600) // 60} 分后再来。")
            return
        amount = target["level"] * 1200 * (2 if target["master_uid"] == doc.uid else 1)
        if target["fund"] < amount:
            yield event.plain_result(
                f"宗门基金不足发俸（需 {amount}，现 {target['fund']}），快去「{CMD_SECT_DONATE} 数量」做贡献。"
            )
            return
        d = doc.model_copy(update={"stones": doc.stones + amount})
        d.ext["salary_ts"] = now
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.update_sect(name, target["level"], target["fund"] - amount)
        role = "宗主" if target["master_uid"] == doc.uid else "弟子"
        yield event.plain_result(
            f"领取【{name}】俸禄 {amount} 灵石（{role}·{target['level']}级），基金余 {target['fund'] - amount}。"
        )

    @filter.command(CMD_PAY, "灵石转账")
    async def handle_pay(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        target_uid = self._at_target(event)
        if not target_uid:
            yield event.plain_result(f"格式：{CMD_PAY} @道友 数量")
            return
        if target_uid == doc.uid:
            yield event.plain_result("自己转给自己，左手倒右手？")
            return
        # @某人 是 At 组件会占参数位；且 openid 含数字会被误抓，
        # 先剥掉 @ 标记再从文本提取金额（取最后一个数字）
        import re
        clean = re.sub(r'<qqbot-at-user\s+id="[^"]+"|<@!?\w+>', " ", (event.message_str or ""))
        digits = re.findall(r"\d+", clean)
        amount = int(digits[-1]) if digits else 0
        if amount < 100:
            yield event.plain_result("最少转 100 灵石。")
            return
        fee = int(amount * 0.05)
        total = amount + fee
        if doc.stones < total:
            yield event.plain_result(f"灵石不足：需 {amount} + 手续费 5%（{fee}）= {total}。")
            return
        raw = await self.db.get_player(target_uid)
        if not raw:
            yield event.plain_result("对方尚未踏入仙途，无法转账。")
            return
        foe = PlayerDoc(**raw)
        d1 = doc.model_copy(update={"stones": doc.stones - total})
        d2 = foe.model_copy(update={"stones": foe.stones + amount})
        async with self.db.transaction():
            await self.db.save_player(d1.model_dump())
            await self.db.save_player(d2.model_dump())
        name = foe.name or foe.uid[:8] + "…"
        yield event.plain_result(
            f"已向 {name} 转账 {amount} 灵石（手续费 {fee}），余 {d1.stones}。"
        )

    @filter.command(CMD_LIST_ITEM, "上架拍卖行")
    async def handle_list_item(self, event: AstrMessageEvent, item_name: str = "", qty: int = 0, price: int = 0):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        item_name = (item_name or "").strip()
        if not item_name or qty < 1 or price < 1:
            yield event.plain_result(f"格式：{CMD_LIST_ITEM} 物品名 数量 单价")
            return
        if price > 10_000_000:
            yield event.plain_result("单价不得超过 1000 万。")
            return
        inv = await self.db.get_inventory(doc.uid)
        if inv.get(item_name, 0) < qty:
            yield event.plain_result(f"纳戒中「{item_name}」只有 {inv.get(item_name, 0)} 件。")
            return
        target_item = self.item_index.get(item_name) or {}
        if target_item.get("type") == "帝兵" and item_name in (doc.ext.get("imperial") or []):
            yield event.plain_result(f"「{item_name}」已认主，与道友性命相连，无法转让。")
            return
        async with self.db.transaction():
            if not await self.db.remove_item(doc.uid, item_name, qty):
                raise RuntimeError("INSUFFICIENT")
            lot_id = await self.db.list_auction(
                doc.uid, doc.name or doc.uid[:8] + "…", item_name, qty, price
            )
        yield event.plain_result(
            f"已上架：{item_name} ×{qty}，单价 {price}（单号 {lot_id}）。物品已托管，"
            f"发「{CMD_DELIST} {lot_id}」可取回。"
        )

    @filter.command(CMD_MARKET, "拍卖行一览")
    async def handle_market(self, event: AstrMessageEvent, page: str = "1"):
        if not self._allowed(event):
            return
        rows, pages = await self.db.auction_page(int(page or 1))
        if not rows:
            yield event.plain_result("拍卖行空空如也。发「#上架 物品 数量 单价」开张。")
            return
        lines = [f"--- 拍卖行（第 {pages and min(int(page or 1), pages)}/{pages} 页）---"]
        for r in rows:
            lines.append(f"· {r['id']}号：{r['item']} ×{r['qty']} — {r['price']} 灵石/件（{r['seller_name']}）")
        lines.append(f"购买：{CMD_BUY_LOT} 单号")
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_BUY_LOT, "购买拍卖品")
    async def handle_buy_lot(self, event: AstrMessageEvent, lot_id: int = 0):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        lot = await self.db.get_auction(int(lot_id))
        if not lot:
            yield event.plain_result(f"查无此单：{lot_id}。发「{CMD_MARKET}」查看在售。")
            return
        if lot["seller_uid"] == doc.uid:
            yield event.plain_result("不能购买自己的挂单；要拿回请「#下架」。")
            return
        total = lot["price"] * lot["qty"]
        if doc.stones < total:
            yield event.plain_result(f"灵石不足：需 {total}（{lot['price']}×{lot['qty']}），道友有 {doc.stones}。")
            return
        tax = int(total * 0.05)
        d1 = doc.model_copy(update={"stones": doc.stones - total})
        async with self.db.transaction():
            await self.db.save_player(d1.model_dump())
            await self.db.add_items(doc.uid, {lot["item"]: lot["qty"]})
            if not await self.db.delete_auction(int(lot_id)):
                raise RuntimeError("LOT_GONE")
        raw = await self.db.get_player(lot["seller_uid"])
        if raw:
            seller = PlayerDoc(**raw)
            seller.stones += total - tax
            await self.db.save_player(seller.model_dump())
        yield event.plain_result(
            f"成交：{lot['item']} ×{lot['qty']}，共 {total} 灵石已入纳戒。\n"
            f"卖家 {lot['seller_name']} 收款 {total - tax}（税 {tax}）。"
        )

    @filter.command(CMD_DELIST, "下架拍卖品")
    async def handle_delist(self, event: AstrMessageEvent, lot_id: int = 0):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        lot = await self.db.get_auction(int(lot_id))
        if not lot:
            yield event.plain_result(f"查无此单：{lot_id}。")
            return
        if lot["seller_uid"] != doc.uid:
            yield event.plain_result("只能下架自己的挂单。")
            return
        async with self.db.transaction():
            if not await self.db.delete_auction(int(lot_id)):
                raise RuntimeError("LOT_GONE")
            await self.db.add_items(doc.uid, {lot["item"]: lot["qty"]})
        yield event.plain_result(f"已下架并取回：{lot['item']} ×{lot['qty']}。")

    @filter.command(CMD_MY_LOTS, "我的拍卖")
    async def handle_my_lots(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        lots = await self.db.my_auctions(doc.uid)
        if not lots:
            yield event.plain_result("没有在售挂单。")
            return
        lines = ["--- 我的挂单 ---"]
        for r in lots:
            lines.append(f"· {r['id']}号：{r['item']} ×{r['qty']} — {r['price']} 灵石/件")
        yield event.plain_result("\n".join(lines))

    # ---- 炼丹 / 帝兵认主 / 宗门秘境（M5） ----

    @filter.command(CMD_RECIPES, "炼丹配方")
    async def handle_recipes(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        if not self.craftable:
            yield event.plain_result("暂无开放配方。")
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        lv = alchemy.level_of(int(doc.ext.get("alchemy_exp", 0)))
        lines = [f"--- 炼丹配方（炼丹 {lv} 级，开放 {len(self.craftable)} 条｜必成）---"]
        for r in self.craftable[:12]:
            mats = "+".join(f"{m['name']}×{m['amount']}" for m in r["materials"])
            lock = f"（需{r['level_limit']}级）" if r.get("level_limit") else ""
            mode = self.craft_mode.get(r["name"], "direct")
            out = "直接产出" if mode == "direct" else "凡品/极品/仙品"
            lines.append(f"· {r['name']}{lock}：{mats}｜{out}")
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_CRAFT, "炼丹")
    async def handle_craft(self, event: AstrMessageEvent, pill_name: str = "", qty: int = 1):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        pill_name = (pill_name or "").strip()
        recipe = next((r for r in self.craftable if r["name"] == pill_name), None)
        if not recipe:
            yield event.plain_result(
                f"查无此配方或暂未开放：「{pill_name}」。发「{CMD_RECIPES}」查看。"
            )
            return
        qty = max(1, min(int(qty or 1), 10))
        alchemy_exp = int(doc.ext.get("alchemy_exp", 0))
        lv = alchemy.level_of(alchemy_exp)
        occ_lv, _ = self._ensure_occ(doc)
        # 原版门槛对职业等级（occupation_level）；炼丹等级保留为参考展示
        if occ_lv < int(recipe.get("level_limit", 0) or 0):
            yield event.plain_result(f"炼丹等级不足：此方需 {recipe['level_limit']} 级，道友职业 {occ_lv} 级。")
            return
        inv = await self.db.get_inventory(doc.uid)
        lacking = alchemy.missing_materials(recipe, inv)
        if lacking:
            detail = "、".join(f"{n}(需{need}有{have})" for n, need, have in lacking)
            yield event.plain_result(f"材料不足：{detail}。秘境寻宝可采得灵草。")
            return
        # 预扣全部材料
        consume: dict[str, int] = {}
        for m in recipe["materials"]:
            consume[str(m["name"])] = consume.get(str(m["name"]), 0) + int(m["amount"]) * qty
        import random as _random
        rng = _random.Random(f"{doc.uid}:{pill_name}:{qty}:{time.time()}")
        buckets, new_exp = alchemy.craft_pills(recipe, occ_lv, rng, qty)  # 品质阈值用职业等级（原版 dengjixiuzheng）
        d = doc.model_copy(deep=True)
        d.ext["alchemy_exp"] = new_exp
        gain: dict[str, int] = {}
        parts: list[str] = []
        if "" in buckets:  # 特殊丹直接产出
            gain[recipe["name"]] = buckets[""]
            parts.append(f"{recipe['name']} ×{buckets['']}")
        else:  # 品质分档
            for tier, n in buckets.items():
                gain[f"{tier}{recipe['name']}"] = n
                parts.append(f"{tier}{recipe['name']} ×{n}")
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            for name, n in consume.items():
                if not await self.db.remove_item(doc.uid, name, n):
                    raise RuntimeError("INSUFFICIENT")
            await self.db.add_items(doc.uid, gain)
        new_lv = alchemy.level_of(new_exp)
        lv_note = f"\n炼丹等级升至 {new_lv} 级！" if new_lv > lv else ""
        # 职业经验（原版 zhizuo_dan 调 Add_职业经验；仅炼丹师生效）
        occ_note = ""
        if doc.ext.get("occupation") == "炼丹师":
            olv, oexp = self._ensure_occ(doc)
            gain_exp = int((recipe.get("exp") or [0, 0])[0]) * qty
            nlv2, nexp2 = occupation.add_exp(olv, oexp, gain_exp, self.occ_exp_table)
            d.ext["occupation_level"] = nlv2
            d.ext["occupation_exp"] = nexp2
            await self.db.save_player(d.model_dump())
            occ_note = f"\n职业经验 +{gain_exp}" + (f"，升到 {nlv2} 级！" if nlv2 > olv else "")
        text = f"丹炉火候正好，炼成：{'、'.join(parts)}。"
        yield event.plain_result(f"{text}\n累计经验 {new_exp}{lv_note}{occ_note}")

    @filter.command(CMD_ALCHEMY_LV, "炼丹等级")
    async def handle_alchemy_lv(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        exp = int(doc.ext.get("alchemy_exp", 0))
        lv = alchemy.level_of(exp)
        nxt = alchemy.next_threshold(exp)
        yield event.plain_result(
            f"炼丹等级：{lv} 级（经验 {exp}"
            + (f"，距 {lv + 1} 级还需 {nxt - exp}" if nxt else "，已臻大成") + "）"
        )

    # ---- 灵根（天资） ----

    async def _linggen_view(self, event: AstrMessageEvent):
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        snap = doc.ext.get("linggen")
        if not isinstance(snap, dict) or not snap.get("name"):
            yield event.plain_result(
                "道友尚未洗炼灵根，先天资质未定（修炼效率 ×1.0）。\n"
                "服下「天命轮回丹」或「神心丹」可逆天改命，重塑先天根骨——"
                "资质好坏全凭天命，洗出逆天体质则闭关修为一日千里。"
            )
            return
        try:
            eff = float(snap.get("eff", 1.0) or 1.0)
        except (TypeError, ValueError):
            eff = 1.0
        eff_note = "（低于常人，勤能补拙）" if eff < 1.0 else ("（资质平平，与常人同）" if eff == 1.0 else "（天资卓越！）")
        lines = [
            "--- 灵根 · 天资 ---",
            f"灵根：{snap.get('name')}",
            f"品阶：{snap.get('type')}" + (f"（稀有度 {snap.get('rarity')}）" if snap.get("rarity") else ""),
            f"修炼效率：×{eff:g} {eff_note}",
            "效果：闭关出关所得修为 ×此效率；欲改天命，再服天命轮回丹/神心丹重新洗炼。",
        ]
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_LINGGEN, "查看灵根")
    async def handle_linggen(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        async for r in self._linggen_view(event):
            yield r

    @filter.command(CMD_LINGGEN_MY, "查看灵根（别名）")
    async def handle_linggen_my(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        async for r in self._linggen_view(event):
            yield r

    # ---- 每日任务（移植原版 meirrenwu） ----

    async def _task_view(self, event: AstrMessageEvent):
        """#我的任务：出图 + 纯文本回退。"""
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        rec = await self.db.get_daily_task(doc.uid)
        if not rec or not quest.is_today(rec, quest.date_key()):
            yield event.plain_result(f"你今天还没有接取任务，请发送「{CMD_TASK_GET}」。")
            return
        realm = max(0, int(doc.realm_index))
        data = quest.view(rec, realm)
        if self.render_on:
            png = await render.render_panel(
                "quest",
                {"title": "每日修行任务", "sub": data["date"], **data},
                self.panel_dir,
            )
            if png:
                yield event.image_result(str(png))
                return
        lines = [
            f"--- 每日任务（任务 {data['level']} 级｜经验 {data['exp']}/{data['exp_need']}）---",
        ]
        for t in data["tasks"]:
            lines.append(f"· 任务{t['no']} {t['name']}（{t['desc']}）：{t['prog']}/{t['need']} —— {t['status']}")
        lines.append(f"状态：{data['state']}")
        lines.append(
            f"终极奖励：修为/血气/灵石 ×{data['final']['amount']}，秘境之匙 ×{data['final']['key_n']}"
        )
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_TASK_GET, "接取每日任务")
    async def handle_task_get(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        today = quest.date_key()
        rec = await self.db.get_daily_task(doc.uid)
        if quest.is_today(rec, today):
            yield event.plain_result("今日任务已经接取过了，发「#我的任务」查看进度。")
            return
        realm = max(0, int(doc.realm_index))
        rec = quest.accept_record(rec, doc.uid, today)
        need_spend, need_gain, need_secret = quest.requirements(rec["level"], realm)
        async with self.db.transaction():
            await self.db.upsert_daily_task(rec)
        yield event.plain_result(
            f"今日任务已接取（任务 {rec['level']} 级）：\n"
            f"1. 消耗灵石 {need_spend}\n2. 获取灵石 {need_gain}\n3. 秘境探索 {need_secret} 次\n"
            f"每步完成得 修为/血气/灵石×{quest.step_reward(rec['level'], realm)}；"
            f"发「{CMD_TASK_MY}」看进度，完成后「{CMD_TASK_SUBMIT}」结算。"
        )

    @filter.command(CMD_TASK_MY, "查看每日任务")
    async def handle_task_my(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        async for r in self._task_view(event):
            yield r

    @filter.command(CMD_TASK_SUBMIT, "提交每日任务")
    async def handle_task_submit(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        rec = await self.db.get_daily_task(doc.uid)
        if not rec or not quest.is_today(rec, quest.date_key()):
            yield event.plain_result(f"请先发送「{CMD_TASK_GET}」接取今日任务。")
            return
        if rec.get("renwu") == 2:
            yield event.plain_result("今日奖励已经领取。")
            return
        if quest.all_done(rec):
            yield event.plain_result("今日任务均已完成，请发送「#领取每日奖励」。")
            return
        realm = max(0, int(doc.realm_index))
        msgs, new_rec, completed = quest.settle_submit(rec, realm)
        if not msgs:
            yield event.plain_result("你还有任务没完成哦~（进度见「#我的任务」）")
            return
        rew = quest.step_reward(new_rec["level"], realm) * completed
        d = doc.model_copy(deep=True)
        d.exp += rew
        d.stones += rew
        d.ext["xueqi"] = int(d.ext.get("xueqi", 0)) + rew
        async with self.db.transaction():
            await self.db.upsert_daily_task(new_rec)   # 先落任务（w 置 2，避免奖励灵石被误追踪）
            await self.db.save_player(d.model_dump())
        extra = ""
        if new_rec.get("renwu") == 1:
            extra = "\n今日任务全部完成！发「#领取每日奖励」领取终极奖励。"
        yield event.plain_result("\n".join(msgs) + extra)

    @filter.command(CMD_TASK_CLAIM, "领取每日奖励")
    async def handle_task_claim(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        rec = await self.db.get_daily_task(doc.uid)
        if not rec or not quest.is_today(rec, quest.date_key()):
            yield event.plain_result(f"请先发送「{CMD_TASK_GET}」接取今日任务。")
            return
        if not quest.all_done(rec):
            yield event.plain_result("你还有任务没完成哦~")
            return
        if rec.get("renwu") == 2:
            yield event.plain_result("你已经领取了每日任务奖励。")
            return
        realm = max(0, int(doc.realm_index))
        fr = quest.final_reward(int(rec.get("level", 1)), realm)
        new_rec = quest.settle_claim(rec)
        d = doc.model_copy(deep=True)
        d.exp += fr["amount"]
        d.stones += fr["amount"]
        d.ext["xueqi"] = int(d.ext.get("xueqi", 0)) + fr["amount"]
        async with self.db.transaction():
            await self.db.upsert_daily_task(new_rec)
            await self.db.save_player(d.model_dump())
            await self.db.add_items(doc.uid, {"秘境之匙": fr["keys"]})
        yield event.plain_result(
            f"终极奖励已领取（任务 {rec['level']} 级）：\n"
            f"修为 +{fr['amount']}，血气 +{fr['amount']}，灵石 +{fr['amount']}，秘境之匙 ×{fr['keys']}"
        )

    async def _recipe_overview(self, event: AstrMessageEvent, title: str, recipes: list, mode_map: dict | None, cmd: str, note: str = ""):
        """配方总览（对齐原版 #丹药配方/#符道配方 出图）。"""
        groups = []
        for r in recipes:
            name = r.get("name", "?")
            mats = "+".join(
                f"{m.get('name')}×{m.get('amount')}" for m in (r.get("materials") or []))
            mode = (mode_map or {}).get(name)
            lock = r.get("level_limit") or 0
            status = "✅开放" if mode else "未开放"
            out = {"direct": "直接产出", "quality": "凡品/极品/仙品"}.get(mode or "", "—")
            head = f"{name}（需{lock}级·{status}）" if lock else f"{name}（{status}）"
            groups.append({"group": head, "list": [
                {"title": mats or "（无材料）", "desc": f"产物形态：{out}"}]})
        data = {"title": title, "groups": groups}
        if self.render_on:
            png = await render.render_panel("catalog", data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        lines = [f"【{title}】" + (note if note else "")]
        for g in groups:
            lines.append(f"—— {g['group']} ——")
            for it in g["list"]:
                lines.append(f"{it['title']}｜{it['desc']}")
        yield event.plain_result("\n".join(lines))

    @filter.command("#丹药配方", "丹方总览")
    async def handle_danfang(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        async for r in self._recipe_overview(
            event, "诸天修仙 · 丹药配方总览", self.recipes, self.craft_mode, "#丹药配方"):
            yield r

    @filter.command("#符道配方", "符方总览")
    async def handle_fufang(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        fz = [r for r in (self.content.table("occupation/制符列表") or [])
              if isinstance(r, dict) and r.get("name")]
        async for r in self._recipe_overview(
            event, "诸天修仙 · 符道配方总览", fz, {}, "#符道配方",
            note="制符系统后续开放，配方先览"):
            yield r

    @filter.command("#丹药效果", "查看丹药效果")
    async def handle_yaoxiao(self, event: AstrMessageEvent):
        """对齐原版 Occupation.yaoxiao：展示当前生效的丹药 buff。"""
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        buffs = doc.ext.get("buffs") or {}
        lines = ["丹药效果:"]
        big = buffs.get("biguan") or {}
        if isinstance(big, dict) and float(big.get("times", 0) or 0) > 0:
            lines.append(f"· 辟谷丹药力{float(big.get('bonus', 0)) * 100:.0f}% 药效{int(float(big['times']))}次")
        lian = buffs.get("lianti") or {}
        if isinstance(lian, dict) and float(lian.get("times", 0) or 0) > 0:
            lines.append(f"· 炼神丹药力{float(lian.get('ratio', 0)) * 100:.0f}% 药效{int(float(lian['times']))}次")
        ped = buffs.get("ped") or {}
        if isinstance(ped, dict) and float(ped.get("times", 0) or 0) > 0:
            lines.append(f"· 仙缘丹药力{float(ped.get('bonus', 0)) * 100:.0f}% 药效{int(float(ped['times']))}次")
        sc = buffs.get("shenci") or {}
        if isinstance(sc, dict) and float(sc.get("times", 0) or 0) > 0:
            lines.append(f"· 神赐丹药力{float(sc.get('bonus', 0)) * 100:.0f}% 药效{int(float(sc['times']))}次")
        lk = buffs.get("lucky") or {}
        if isinstance(lk, dict) and float(lk.get("times", 0) or 0) > 0:
            lines.append(f"· 福源丹药力{float(lk.get('bonus', 0)):g} 药效{int(float(lk['times']))}次")
        for key, label in (("potential", "仙道潜力"), ("heart", "心神"), ("wudao", "悟道"), ("daoxin", "道心")):
            v = int(doc.ext.get(key, 0) or 0)
            if v:
                lines.append(f"· {label} 累计 {v}")
        if int(doc.ext.get("modao", 0) or 0):
            lines.append(f"· 魔道值 {int(doc.ext['modao'])}")
        if len(lines) == 1:
            lines.append("· （当前无生效丹药）")
        yield event.plain_result("\n".join(lines))

    # ---- 职业 / 采集 / 制符（移植原版 Occupation） ----

    def _ensure_occ(self, doc: PlayerDoc) -> tuple[int, int]:
        """读职业等级；老玩家无职业字段时从 alchemy/forge 经验映射迁移（只读，不落盘）。"""
        lv = doc.ext.get("occupation_level")
        if lv is not None:
            return int(lv), int(doc.ext.get("occupation_exp", 0) or 0)
        migrated = max(
            alchemy.level_of(int(doc.ext.get("alchemy_exp", 0))),
            alchemy.level_of(int(doc.ext.get("forge_exp", 0))),
        )
        return migrated, 0

    def _occ_rate(self, level: int) -> float:
        return occupation.rate_of(level, self.occ_exp_table)

    @filter.command(CMD_JOB, "转职")
    async def handle_job(self, event: AstrMessageEvent, job_name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        job = (job_name or "").strip()
        if not job:
            yield event.plain_result(f"格式：{CMD_JOB} 职业名（可选：{'、'.join(self.job_names)}）")
            return
        if job not in self.job_names:
            yield event.plain_result(f"没有[{job}]这项职业。可选：{'、'.join(self.job_names)}")
            return
        realm_id = max(0, doc.realm_index) + 1
        if not occupation.job_gate_ok(job, realm_id):
            need = 17 if job == "采矿师" else 25
            yield event.plain_result(f"门槛未至：[{job}]需第 {need} 境，道友当前第 {realm_id} 境。")
            return
        cur = doc.ext.get("occupation")
        if cur == job:
            yield event.plain_result(f"你当前已经是[{job}]。")
            return
        fuzhi = list(doc.ext.get("fuzhi") or [])
        if any(f.get("职业名") == job for f in fuzhi):
            yield event.plain_result(f"你已拥有[{job}]副职，请发「{CMD_JOB_SWAP} {job}」切换。")
            return
        cert = f"{job}转职凭证"
        inv = await self.db.get_inventory(doc.uid)
        if int(inv.get(cert, 0)) < 1:
            yield event.plain_result(f"你没有【{cert}】。")
            return
        lv, exp = self._ensure_occ(doc)
        d = doc.model_copy(deep=True)
        if cur:  # 旧职业快照入副职（对齐原版 saveOccupation）
            fuzhi = [f for f in fuzhi if f.get("职业名") != cur]
            fuzhi.append({"职业名": cur, "职业经验": exp, "职业等级": lv})
        d.ext["fuzhi"] = fuzhi
        d.ext["occupation"] = job
        d.ext["occupation_level"] = 1
        d.ext["occupation_exp"] = 0
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.remove_item(doc.uid, cert, 1)
        yield event.plain_result(
            f"恭喜转职为[{job}]！" + (f"旧职业[{cur}]已存为副职。" if cur else "")
        )

    @filter.command(CMD_JOB_SWAP, "转换副职")
    async def handle_job_swap(self, event: AstrMessageEvent, job_name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        fuzhi = [f for f in (doc.ext.get("fuzhi") or []) if isinstance(f, dict)]
        cur = doc.ext.get("occupation")
        fuzhi = [f for f in fuzhi if f.get("职业名") != cur]
        if not fuzhi:
            yield event.plain_result("您还没有副职哦。")
            return
        target = (job_name or "").strip()
        if not target:
            if len(fuzhi) > 1:
                yield event.plain_result(
                    f"你有多个副职，请发「{CMD_JOB_SWAP} 职业名」。可选：{'、'.join(f['职业名'] for f in fuzhi)}"
                )
                return
            target = str(fuzhi[0]["职业名"])
        tgt = next((f for f in fuzhi if f.get("职业名") == target), None)
        if not tgt:
            yield event.plain_result(f"你还没有[{target}]职业，可发「{CMD_JOB_MY}」查看。")
            return
        lv, exp = self._ensure_occ(doc)
        d = doc.model_copy(deep=True)
        rest = [f for f in fuzhi if f.get("职业名") != target]
        if cur:
            rest = [f for f in rest if f.get("职业名") != cur]
            rest.append({"职业名": cur, "职业经验": exp, "职业等级": lv})
        d.ext["fuzhi"] = rest
        d.ext["occupation"] = target
        d.ext["occupation_level"] = int(tgt.get("职业等级", 1))
        d.ext["occupation_exp"] = int(tgt.get("职业经验", 0))
        await self.db.save_player(d.model_dump())
        yield event.plain_result(
            f"已切换至副职[{target}]（{int(tgt.get('职业等级', 1))} 级）。"
            + (f"原职业[{cur}]已存为副职。" if cur else "")
        )

    @filter.command(CMD_JOB_MY, "我的职业")
    async def handle_job_my(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        lv, exp = self._ensure_occ(doc)
        cur = doc.ext.get("occupation")
        lines = ["--- 职业 ---"]
        if cur:
            row = next((e for e in self.occ_exp_table if int(e.get("id", -1)) == lv), {})
            lines.append(f"主职：{cur}（{row.get('name', '?')} {lv} 级｜经验 {exp}）")
        else:
            lines.append("主职：无业游民（发「#转职 职业名」入职，需对应转职凭证）")
        for f in (doc.ext.get("fuzhi") or []):
            if isinstance(f, dict) and f.get("职业名"):
                lines.append(f"副职：{f['职业名']}（{int(f.get('职业等级', 1))} 级）")
        yield event.plain_result("\n".join(lines))

    def _timed_action_start(self, doc: PlayerDoc, action: str, minutes: int,
                            period: int, cycles: int) -> tuple[bool, str, PlayerDoc]:
        """采集类定时动作（对齐原版 plant/mine：周期档钳制 + state 机）。"""
        if doc.state != "空闲":
            return False, f"道友正在「{doc.state}」中，无法分心。", doc
        t = max(period, min(int(minutes), period * cycles))
        d = doc.model_copy(deep=True)
        d.state = action
        d.state_start = time.time()
        d.ext["action_minutes"] = t
        return True, f"现在开始{action}{t}分钟，完成后发对应「#结束{action[:2]}」结算。", d

    def _timed_action_end(self, doc: PlayerDoc, action: str, period: int, cycles: int) -> tuple[bool, int, PlayerDoc]:
        """结算采集时长：实际分钟按周期向下取整，不足一个周期 0 收益。"""
        if doc.state != action:
            return False, 0, doc
        cap = period * cycles
        elapsed = max(0.0, (time.time() - doc.state_start) / 60)
        planned = doc.ext.get("action_minutes")
        counted = min(elapsed, float(planned) if planned else float(cap), float(cap))
        floored = int(counted // period) * period
        d = doc.model_copy(deep=True)
        d.state = "空闲"
        d.state_start = 0.0
        d.ext.pop("action_minutes", None)
        return True, floored, d

    @filter.command(CMD_PLANT, "采药")
    async def handle_plant(self, event: AstrMessageEvent, minutes: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if doc.ext.get("occupation") != "采药师":
            yield event.plain_result("您采药，您配吗？（需采药师职业）")
            return
        digits = "".join(ch for ch in (minutes or "") if ch.isdigit())
        t = int(digits) if digits else occupation.plant_period()
        ok, msg, d = self._timed_action_start(doc, "采药中", t, occupation.plant_period(), occupation.plant_cycles())
        if ok:
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_PLANT_END, "结束采药")
    async def handle_plant_end(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        ok, minutes, d = self._timed_action_end(doc, "采药中", occupation.plant_period(), occupation.plant_cycles())
        if not ok:
            yield event.plain_result("道友并未采药。")
            return
        realm_id = max(0, doc.realm_index) + 1
        lv, _ = self._ensure_occ(doc)
        import random as _random
        herbs, exp = occupation.plant_yield(minutes, lv, realm_id, _random.Random(f"{doc.uid}:plant:{time.time()}"))
        nlv, nexp = occupation.add_exp(lv, self._ensure_occ(doc)[1], exp, self.occ_exp_table)
        d.ext["occupation_level"] = nlv
        d.ext["occupation_exp"] = nexp
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if herbs:
                await self.db.add_items(doc.uid, herbs)
        lines = [f"采药归来（{minutes} 分钟）：获得职业经验 {exp}" + (f"，升到 {nlv} 级！" if nlv > lv else "")]
        if herbs:
            lines += [f"· {n}×{c}" for n, c in herbs.items()]
        else:
            lines.append("· 产出不足一株，草药散于风中")
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_MINE, "采矿")
    async def handle_mine(self, event: AstrMessageEvent, minutes: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if doc.ext.get("occupation") != "采矿师":
            d = doc.model_copy(deep=True)
            d.stones = max(0, d.stones - 200)
            await self.db.save_player(d.model_dump())
            yield event.plain_result("你挖矿许可证呢？非法挖矿，罚款 200 灵石。")
            return
        digits = "".join(ch for ch in (minutes or "") if ch.isdigit())
        t = int(digits) if digits else occupation.mine_period()
        ok, msg, d = self._timed_action_start(doc, "采矿中", t, occupation.mine_period(), occupation.mine_cycles())
        if ok:
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_MINE_END, "结束采矿")
    async def handle_mine_end(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        ok, minutes, d = self._timed_action_end(doc, "采矿中", occupation.mine_period(), occupation.mine_cycles())
        if not ok:
            yield event.plain_result("道友并未采矿。")
            return
        lv, exp_now = self._ensure_occ(doc)
        import random as _random
        mats, exp = occupation.mine_yield_full(minutes, lv, self.occ_exp_table, _random.Random(f"{doc.uid}:mine:{time.time()}"))
        nlv, nexp = occupation.add_exp(lv, exp_now, exp, self.occ_exp_table)
        d.ext["occupation_level"] = nlv
        d.ext["occupation_exp"] = nexp
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if mats:
                await self.db.add_items(doc.uid, mats)
        lines = [f"采矿归来（{minutes} 分钟）：获得职业经验 {exp}" + (f"，升到 {nlv} 级！" if nlv > lv else "")]
        if mats:
            lines += [f"· {n}×{c}" for n, c in mats.items()]
        else:
            lines.append("· 产出不足以装满一筐")
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_MAKE, "制作符箓")
    async def handle_make(self, event: AstrMessageEvent, fu_name: str = "", qty: int = 1):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if doc.ext.get("occupation") != "符师":
            yield event.plain_result("符道玄奥，非符师不可妄为！")
            return
        fu_name = (fu_name or "").strip().rstrip("*0123456789")
        fufang = next((r for r in (self.content.table("occupation/制符列表") or [])
                       if isinstance(r, dict) and r.get("name") == fu_name), None)
        if not fufang:
            yield event.plain_result(f"符道秘录中无「{fu_name}」记载。发「#符道配方」查看。")
            return
        lv, _ = self._ensure_occ(doc)
        ok, why, n = occupation.talisman_make(fufang, lv, max(1, int(qty or 1)))
        if not ok:
            yield event.plain_result(why)
            return
        inv = await self.db.get_inventory(doc.uid)
        lacking = alchemy.missing_materials(fufang, inv)
        if lacking:
            detail = "、".join(f"{nm}(需{need}有{have})" for nm, need, have in lacking)
            yield event.plain_result(f"材料不足：{detail}")
            return
        d = doc.model_copy(deep=True)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            for m in fufang["materials"]:
                if not await self.db.remove_item(doc.uid, str(m["name"]), int(m["amount"]) * n):
                    raise RuntimeError("INSUFFICIENT")
            await self.db.add_items(doc.uid, {fu_name: n})
        yield event.plain_result(f"成功制作「{fu_name}」×{n}！")

    # ---- 图鉴楼 / 来源查询（对齐原版楼类指令） ----

    CATALOG_TABLES = {
        "丹药楼": "item/丹药列表", "装备楼": "item/装备列表", "功法楼": "item/功法列表",
        "道具楼": "item/道具列表", "仙宠楼": "item/仙宠列表", "锻造材料楼": "item/锻造材料",
        "灵根图鉴": "item/灵根列表", "合成图鉴": "item/合成列表", "成就图鉴": "item/成就列表",
        "宝石图鉴": "item/宝石",
    }

    async def _catalog_view(self, event: AstrMessageEvent, table: str, title: str, cmd: str, page: int):
        items = self.content.table(table)
        if not isinstance(items, list) or not items:
            yield event.plain_result("该图鉴暂无数据。")
            return
        cur, pages, curp = catalog.catalog_page(items, page or 1)
        lines = [f"--- {title}（共 {len(items)} 条｜第 {curp}/{pages} 页）---"]
        for e in cur:
            eff = e["effect"] or (e["desc"][:24] if e["desc"] else "")
            lines.append(
                f"· {e['name']}" + (f"（{e['type']}）" if e["type"] else "")
                + f" 售{e['price']}" + (f"｜{eff}" if eff else "")
            )
        if curp < pages:
            lines.append(f"翻页：{cmd} {curp + 1}")
        yield event.plain_result("\n".join(lines))

    def _catalog_router(self, catalog_name: str):
        return self.CATALOG_TABLES.get((catalog_name or "").strip())

    @filter.command(CMD_LOU, "图鉴楼（统一入口）")
    async def handle_lou(self, event: AstrMessageEvent, catalog_name: str = "", page: str = ""):
        if not self._allowed(event):
            return
        table = self._catalog_router(catalog_name)
        if not table:
            yield event.plain_result(
                f"查无图鉴「{catalog_name}」。可用：{'、'.join(self.CATALOG_TABLES)}"
            )
            return
        digits = "".join(ch for ch in (page or "") if ch.isdigit())
        async for r in self._catalog_view(event, table, catalog_name.strip(), f"{CMD_LOU} {catalog_name.strip()}",
                                          int(digits) if digits else 1):
            yield r

    @filter.command("#丹药楼", "丹药图鉴")
    async def handle_lou_danyao(self, event: AstrMessageEvent, page: int = 1):
        if not self._allowed(event):
            return
        async for r in self._catalog_view(event, "item/丹药列表", "丹药楼", "#丹药楼", page):
            yield r

    @filter.command("#装备楼", "装备图鉴")
    async def handle_lou_zhuangbei(self, event: AstrMessageEvent, page: int = 1):
        if not self._allowed(event):
            return
        async for r in self._catalog_view(event, "item/装备列表", "装备楼", "#装备楼", page):
            yield r

    @filter.command("#功法楼", "功法图鉴")
    async def handle_lou_gongfa(self, event: AstrMessageEvent, page: int = 1):
        if not self._allowed(event):
            return
        async for r in self._catalog_view(event, "item/功法列表", "功法楼", "#功法楼", page):
            yield r

    @filter.command("#道具楼", "道具图鉴")
    async def handle_lou_daoju(self, event: AstrMessageEvent, page: int = 1):
        if not self._allowed(event):
            return
        async for r in self._catalog_view(event, "item/道具列表", "道具楼", "#道具楼", page):
            yield r

    @filter.command("#仙宠楼", "仙宠图鉴")
    async def handle_lou_xianchong(self, event: AstrMessageEvent, page: int = 1):
        if not self._allowed(event):
            return
        async for r in self._catalog_view(event, "item/仙宠列表", "仙宠楼", "#仙宠楼", page):
            yield r

    @filter.command("#锻造材料楼", "锻造材料图鉴")
    async def handle_lou_duanzaocailiao(self, event: AstrMessageEvent, page: int = 1):
        if not self._allowed(event):
            return
        async for r in self._catalog_view(event, "item/锻造材料", "锻造材料楼", "#锻造材料楼", page):
            yield r

    @filter.command("#灵根图鉴", "灵根图鉴")
    async def handle_catalog_linggen(self, event: AstrMessageEvent, page: int = 1):
        if not self._allowed(event):
            return
        async for r in self._catalog_view(event, "item/灵根列表", "灵根图鉴", "#灵根图鉴", page):
            yield r

    @filter.command(CMD_WHERE, "物品来源查询")
    async def handle_where(self, event: AstrMessageEvent, item_name: str = ""):
        if not self._allowed(event):
            return
        item_name = (item_name or "").strip()
        if not item_name:
            yield event.plain_result(f"格式：{CMD_WHERE} 物品名")
            return
        sources = catalog.where_to_get(
            item_name,
            self.recipes,
            {e.get("name") for e in self.shop_stock if isinstance(e, dict)},
            {e.get("name") for e in self.drop_pool if isinstance(e, dict)},
        )
        known = self.item_index.get(item_name)
        head = f"「{item_name}」" + (
            f"（{known.get('class', '?')}/{known.get('type', '')}，售 {known.get('出售价', 0)}）"
            if known else "（索引中无此物）"
        )
        yield event.plain_result(head + "\n" + "\n".join(f"· {s}" for s in sources))

    @filter.command(CMD_IMPERIAL, "帝兵认主")
    async def handle_imperial(self, event: AstrMessageEvent, item_name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        item_name = (item_name or "").strip()
        item = self.item_index.get(item_name)
        if not item or item.get("type") != "帝兵":
            yield event.plain_result(f"「{item_name}」不是帝兵。帝兵现世于世界 Boss 奖池与秘境深处。")
            return
        if item_name in (doc.ext.get("imperial") or []):
            yield event.plain_result(f"「{item_name}」已认你为主。")
            return
        if doc.realm_index < 9:
            yield event.plain_result("帝兵有灵，非第 10 境以上不能驯服。")
            return
        inv = await self.db.get_inventory(doc.uid)
        if inv.get(item_name, 0) < 1:
            yield event.plain_result(f"纳戒中没有「{item_name}」。")
            return
        cost = int(self._val("IMPERIAL_COST", 500000))
        if doc.stones < cost:
            yield event.plain_result(f"认主需以 {cost} 灵石温养兵魂，道友灵石不足。")
            return
        d = doc.model_copy(update={"stones": doc.stones - cost})
        imperial = list(d.ext.get("imperial") or [])
        imperial.append(item_name)
        d.ext["imperial"] = imperial
        await self.db.save_player(d.model_dump())
        st = self._stats(d)
        yield event.plain_result(
            f"「{item_name}」认主成功！兵魂与道友性命相连，属性加成翻倍（耗 {cost} 灵石），不可再转让。\n"
            f"当前属性：攻击 {st.atk} · 防御 {st.defense} · 血量 {st.hp}"
        )

    @filter.command(CMD_IMPERIAL_MY, "查看认主")
    async def handle_imperial_my(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        imperial = doc.ext.get("imperial") or []
        if not imperial:
            yield event.plain_result("尚无认主帝兵。帝兵现世于世界 Boss 奖池与秘境深处。")
            return
        yield event.plain_result("--- 认主帝兵 ---\n" + "\n".join(f"· {n}" for n in imperial))

    @filter.command(CMD_SECT_SECRET, "宗门秘境")
    async def handle_sect_secret(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = doc.ext.get("sect")
        if not name:
            yield event.plain_result("道友尚无宗门，无权踏入宗门秘境。")
            return
        target = await self.db.get_sect(name)
        if not target or target["level"] < 3:
            yield event.plain_result("宗门等级不足：3 级（一流）方能开启宗门秘境，快「#宗门捐赠灵石」众筹升级。")
            return
        if self._session(doc):
            yield event.plain_result("道友已在秘境之中。")
            return
        if doc.state != "空闲":
            yield event.plain_result(f"道友正在「{doc.state}」中，无法分心。")
            return
        hp_cur, hp_max = self._hp_pair(doc)
        if hp_cur <= hp_max * 0.3:
            yield event.plain_result("气血太虚，先疗伤再进秘境。")
            return
        factor = round(2.0 + 0.3 * target["level"], 2)
        d = doc.model_copy()
        d.state = "秘境中"
        d.ext["explore"] = {
            "place": f"{name}·宗门秘境", "floor": 0, "stones": 0,
            "items": {}, "log": [], "factor": factor,
        }
        await self.db.save_player(d.model_dump())
        yield event.plain_result(
            f"踏 入【{name}·宗门秘境】（{target['level']} 级，灵气浓度系数 {factor}，远超野地）。\n"
            f"发「{CMD_SEARCH}」寻宝，「{CMD_FLEE}」撤离。"
        )

    # ---- 锻造炼器 / 比试（M6） ----

    @filter.command(CMD_FORGE_RECIPES, "锻造图纸")
    async def handle_forge_recipes(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        if not self.forge_recipes:
            yield event.plain_result("暂无开放图纸。")
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        lv = alchemy.level_of(int(doc.ext.get("forge_exp", 0)))
        forge_rows = []
        for r in self.forge_recipes:
            item = self.item_index.get(r["name"], {})
            forge_rows.append({
                "name": r["name"],
                "meta": f"{item.get('type', '?')}｜{item.get('稀有度', '?')}阶",
                "mats": "+".join(f"{m['name']}×{m['amount']}" for m in r["materials"]),
                "rate": f"{alchemy.success_rate(r, lv):.0%}",
            })
        if self.render_on:
            forge_data = {"title": "锻造图纸", "footer": "诸天修仙",
                          "forge_lv": lv, "rows": forge_rows}
            png = await render.render_panel("forge", forge_data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        lines = [f"--- 锻造图纸（炼器 {lv} 级，开放 {len(self.forge_recipes)} 张）---"]
        for r in self.forge_recipes:
            mats = "+".join(f"{m['name']}×{m['amount']}" for m in r["materials"])
            item = self.item_index.get(r["name"], {})
            lines.append(
                f"· {r['name']}（{item.get('type', '?')}｜{item.get('稀有度', '?')}阶）\n"
                f"   材料：{mats}｜成功率 {alchemy.success_rate(r, lv):.0%}"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_FORGE, "锻造装备")
    async def handle_forge(self, event: AstrMessageEvent, item_name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        item_name = (item_name or "").strip()
        recipe = next((r for r in self.forge_recipes if r["name"] == item_name), None)
        if not recipe:
            yield event.plain_result(
                f"查无此图纸或暂未开放：「{item_name}」。发「{CMD_FORGE_RECIPES}」查看。"
            )
            return
        forge_exp = int(doc.ext.get("forge_exp", 0))
        lv = alchemy.level_of(forge_exp)
        occ_lv, occ_exp = self._ensure_occ(doc)
        inv = await self.db.get_inventory(doc.uid)
        lacking = alchemy.missing_materials(recipe, inv)
        if lacking:
            detail = "、".join(f"{n}(需{need}有{have})" for n, need, have in lacking)
            yield event.plain_result(f"材料不足：{detail}。")
            return
        import random as _random
        rng = _random.Random(f"{doc.uid}:{item_name}:{time.time()}")
        # 对齐原版 lianqi：成功率 = 图纸 rate × (1 + 职业等级加成)，≥24 级 0.8 封顶
        is_forger = doc.ext.get("occupation") == "炼器师"
        suc = occupation.forge_rate(float(recipe.get("rate", 1) or 1), occ_lv if is_forger else 0, self.occ_exp_table)
        mats_txt = "、".join(f"{m['name']}×{m['amount']}" for m in recipe["materials"])
        d = doc.model_copy(deep=True)
        d.ext["forge_exp"] = forge_exp
        new_exp = forge_exp
        if rng.random() > suc:
            async with self.db.transaction():
                await self.db.save_player(d.model_dump())
                for m in recipe["materials"]:
                    if not await self.db.remove_item(doc.uid, str(m["name"]), int(m["amount"])):
                        raise RuntimeError("INSUFFICIENT")
            flavor = "打造装备时不小心锤断了刃芯，打造失败！" if rng.random() < 0.5 \
                else "打造装备时没有把控好火候，烧毁了，打造失败！"
            yield event.plain_result(f"消耗 {mats_txt}。{flavor}（成功率 {suc:.0%}）")
            return
        pinji = occupation.forge_pinji(rng)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            for m in recipe["materials"]:
                if not await self.db.remove_item(doc.uid, str(m["name"]), int(m["amount"])):
                    raise RuntimeError("INSUFFICIENT")
            await self.db.add_items(doc.uid, {recipe["name"]: 1})
        gain_exp = int((recipe.get("exp") or [0, 0])[0])
        if is_forger:
            nlv, nexp = occupation.add_exp(occ_lv, occ_exp, gain_exp, self.occ_exp_table)
            d.ext["occupation_level"] = nlv
            d.ext["occupation_exp"] = nexp
            await self.db.save_player(d.model_dump())
        yield event.plain_result(
            f"消耗 {mats_txt}。打造成功，获得{item_name}"
            f"（品相：{occupation.PINJI_NAMES[pinji]}）×1｜成功率 {suc:.0%}"
            + (f"，炼器师经验 +{gain_exp}" if is_forger else "")
        )

    @filter.command(CMD_FORGE_LV, "锻造等级")
    async def handle_forge_lv(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        exp = int(doc.ext.get("forge_exp", 0))
        lv = alchemy.level_of(exp)
        nxt = alchemy.next_threshold(exp)
        yield event.plain_result(
            f"炼器等级：{lv} 级（经验 {exp}"
            + (f"，距 {lv + 1} 级还需 {nxt - exp}" if nxt else "，已臻大成") + "）"
        )

    @filter.command(CMD_DUEL, "比试")
    async def handle_duel(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        target_uid = self._at_target(event)
        if not target_uid:
            yield event.plain_result(f"格式：{CMD_DUEL} @道友")
            return
        if target_uid == doc.uid:
            yield event.plain_result("自己跟自己比试，赢了也不光彩。")
            return
        now = time.time()
        cd = int(self._val("SPAR_COOLDOWN_SECONDS", 60))
        last = float(doc.ext.get("duel_ts") or 0)
        if now - last < cd:
            yield event.plain_result(f"比试冷却中，{int(cd - (now - last))} 秒后再战。")
            return
        raw = await self.db.get_player(target_uid)
        if not raw:
            yield event.plain_result("对方尚未踏入仙途，无法比试。")
            return
        foe = PlayerDoc(**raw)

        sa, sb = self._stats(doc), self._stats(foe)
        name_a = doc.name or doc.uid[:8] + "…"
        name_b = foe.name or foe.uid[:8] + "…"
        import random as _random
        rng = _random.Random(f"duel:{doc.uid}:{foe.uid}:{now}")
        winner, log = battle.spar(
            battle.Unit(name_a, sa.atk, sa.defense, sa.hp, sa.bao),
            battle.Unit(name_b, sb.atk, sb.defense, sb.hp, sb.bao),
            rng,
        )
        # 比试为友好切磋积分制：无战损，只计分
        d1 = doc.model_copy()
        d1.ext["duel_ts"] = now
        pts_a = int(d1.ext.get("duel_points", 0))
        win_a, total_a = int(d1.ext.get("duel_win", 0)), int(d1.ext.get("duel_total", 0))
        d2 = foe.model_copy()
        total_b = int(d2.ext.get("duel_total", 0)) + 1
        gain = 3 if winner == 0 else (1 if winner is None else 0)
        d1.ext["duel_points"] = pts_a + gain
        d1.ext["duel_win"] = win_a + (1 if winner == 0 else 0)
        d1.ext["duel_total"] = total_a + 1
        d2.ext["duel_points"] = int(d2.ext.get("duel_points", 0)) + (3 if winner == 1 else (1 if winner is None else 0))
        d2.ext["duel_total"] = total_b
        async with self.db.transaction():
            await self.db.save_player(d1.model_dump())
            await self.db.save_player(d2.model_dump())

        result = (
            f"比试结果：{name_a} 胜！（+3 分）" if winner == 0
            else f"比试结果：{name_b} 胜！（+3 分）" if winner == 1
            else "比试结果：势均力敌，平局（各 +1 分）"
        )
        shown = log[:6] + [f"…（共 {len(log)} 回合）"] if len(log) > 7 else log
        if self.render_on:
            duel_data = {
                "title": "比试", "sub": "积分制", "footer": "诸天修仙",
                "side_a": {"name": name_a, "atk": sa.atk, "defense": sa.defense, "hp": sa.hp},
                "side_b": {"name": name_b, "atk": sb.atk, "defense": sb.defense, "hp": sb.hp},
                "log": shown, "result": result,
                "extras": [f"{name_a} 积分 {d1.ext['duel_points']}（{d1.ext['duel_win']}胜/{d1.ext['duel_total']}战）",
                           f"{name_b} 积分 {d2.ext['duel_points']}"],
            }
            png = await render.render_panel("battle", duel_data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        yield event.plain_result(
            "\n".join(shown) + "\n" + result
            + f"\n{name_a} 积分 {d1.ext['duel_points']}（{d1.ext['duel_win']}胜/{d1.ext['duel_total']}战）"
            + f" · {name_b} 积分 {d2.ext['duel_points']}"
        )

    @filter.command(CMD_DUEL_RANK, "比试榜")
    async def handle_duel_rank(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        players = [p for p in await self.db.all_players() if int((p.get("ext") or {}).get("duel_points", 0)) > 0]
        if not players:
            yield event.plain_result(f"尚无比试记录。发「{CMD_DUEL} @道友」开启战端。")
            return
        players.sort(key=lambda p: -int((p.get("ext") or {}).get("duel_points", 0)))
        lines = ["--- 比试榜 · 积分前十 ---"]
        for i, p in enumerate(players[:10], 1):
            name = p.get("name") or p["uid"][:8] + "…"
            ext = p.get("ext") or {}
            lines.append(
                f"{i}. {name} — {ext.get('duel_points', 0)} 分"
                f"（{ext.get('duel_win', 0)}胜/{ext.get('duel_total', 0)}战）"
            )
        yield event.plain_result("\n".join(lines))

    # ---- 宝石 / 功法 / 宗门挑战（M7） ----

    GEM_SLOTS_PER = 2   # 每槽位可镶宝石数

    @filter.command(CMD_GEM_SET, "镶嵌宝石")
    async def handle_gem_set(self, event: AstrMessageEvent, gem_name: str = "", slot: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        gem_name, slot = (gem_name or "").strip(), (slot or "").strip()
        gem = self.item_index.get(gem_name)
        if not gem or gem.get("class") != "宝石":
            yield event.plain_result(f"「{gem_name}」不是宝石。宝石来自坊市与秘境。")
            return
        if slot not in equipment.SLOTS:
            yield event.plain_result(f"格式：{CMD_GEM_SET} 宝石名 部位（{' / '.join(equipment.SLOTS)}）")
            return
        if not (doc.ext.get("equipment") or {}).get(slot):
            yield event.plain_result(f"{slot}位尚未穿戴装备，无处镶嵌。")
            return
        gems = doc.ext.setdefault("gems", {})
        cur = list(gems.get(slot) or [])
        if len(cur) >= self.GEM_SLOTS_PER:
            yield event.plain_result(f"{slot}位已镶满 {self.GEM_SLOTS_PER} 颗，先「{CMD_GEM_UNSET} {slot} 序号」拆除。")
            return
        if gem_name in cur:
            yield event.plain_result(f"「{gem_name}」已镶在{slot}位。")
            return
        async with self.db.transaction():
            if not await self.db.remove_item(doc.uid, gem_name, 1):
                raise RuntimeError("INSUFFICIENT")
            cur.append(gem_name)
            gems[slot] = cur
            await self.db.save_player(doc.model_dump())
        st = self._stats(doc)
        yield event.plain_result(
            f"「{gem_name}」已镶入{slot}位（{len(cur)}/{self.GEM_SLOTS_PER}）。\n"
            f"当前属性：攻击 {st.atk} · 防御 {st.defense} · 血量 {st.hp}"
            + (f" · 暴击 {st.bao:.0%}" if st.bao else "")
        )

    @filter.command(CMD_GEM_UNSET, "拆除宝石")
    async def handle_gem_unset(self, event: AstrMessageEvent, slot: str = "", idx: str = "1"):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        slot = (slot or "").strip()
        gems = doc.ext.get("gems") or {}
        cur = list(gems.get(slot) or [])
        if slot not in equipment.SLOTS or not cur:
            yield event.plain_result(f"格式：{CMD_GEM_UNSET} 部位 序号（部位：{' / '.join(equipment.SLOTS)}）")
            return
        try:
            i = int(idx) - 1
            if not (0 <= i < len(cur)):
                raise ValueError
        except ValueError:
            yield event.plain_result(f"序号无效：{slot}位现有 {len(cur)} 颗（1~{len(cur)}）。")
            return
        gem_name = cur.pop(i)
        gems[slot] = cur
        async with self.db.transaction():
            await self.db.add_items(doc.uid, {gem_name: 1})
            await self.db.save_player(doc.model_dump())
        yield event.plain_result(f"已从{slot}位拆下「{gem_name}」，回到纳戒。")

    @filter.command(CMD_GONGFA_LEARN, "学习功法")
    async def handle_gongfa_learn(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = (name or "").strip()
        g = self.item_index.get(name)
        if not g or g.get("class") != "功法":
            yield event.plain_result(f"「{name}」不是功法。功法现世于坊市与拍卖行。")
            return
        learned = doc.ext.get("gongfa") or []
        if name in learned:
            yield event.plain_result(f"「{name}」已在参悟之中，无需重修。")
            return
        inv = await self.db.get_inventory(doc.uid)
        if inv.get(name, 0) < 1:
            yield event.plain_result(f"纳戒中没有「{name}」——功法需持原本参悟。")
            return
        cost = int(self._val("GONGFA_COST", 1000))
        if doc.stones < cost:
            yield event.plain_result(f"参悟需静室灵石 {cost}，道友不足。")
            return
        d = doc.model_copy(update={"stones": doc.stones - cost})
        learned = list(learned) + [name]
        d.ext["gongfa"] = learned
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if not await self.db.remove_item(doc.uid, name, 1):
                raise RuntimeError("INSUFFICIENT")
        bonus = int(g.get("修炼加成") or 0)
        yield event.plain_result(
            f"参悟「{name}」成功！闭关修炼效率 +{bonus}%（耗 {cost} 灵石，功法原本化为感悟）。\n"
            f"已学功法 {len(learned)} 门。"
        )

    @filter.command(CMD_GONGFA_MY, "我的功法")
    async def handle_gongfa_my(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        learned = doc.ext.get("gongfa") or []
        if not learned:
            yield event.plain_result(f"尚未参悟任何功法。发「{CMD_GONGFA_LEARN} 功法名」学习。")
            return
        lines = ["--- 已参悟功法 ---"]
        total = 0
        for n in learned:
            g = self.item_index.get(n) or {}
            b = int(g.get("修炼加成") or 0)
            total += b
            lines.append(f"· {n}（闭关效率 +{b}%）")
        lines.append(f"合计：闭关效率 +{total}%")
        yield event.plain_result("\n".join(lines))

    async def _sect_power(self, name: str) -> tuple[int, list[str]]:
        """宗门战力 = 全体成员聚合属性之和。"""
        total = 0
        members = []
        for p in await self.db.all_players():
            if (p.get("ext") or {}).get("sect") != name:
                continue
            doc = PlayerDoc(**{k: v for k, v in p.items() if k in PlayerDoc.model_fields})
            st = self._stats(doc)
            total += st.atk + st.defense + st.hp
            members.append(p.get("name") or p["uid"][:8] + "…")
        return total, members

    @filter.command(CMD_SECT_WAR, "宗门挑战")
    async def handle_sect_war(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        my_sect = doc.ext.get("sect")
        if not my_sect:
            yield event.plain_result("道友尚无宗门，无从发起挑战。")
            return
        target_uid = self._at_target(event)
        if not target_uid:
            yield event.plain_result(f"格式：{CMD_SECT_WAR} @对方宗门的任意成员")
            return
        if target_uid == doc.uid:
            yield event.plain_result("不能挑战自己宗门。")
            return
        raw = await self.db.get_player(target_uid)
        if not raw:
            yield event.plain_result("对方尚未踏入仙途。")
            return
        foe_doc = PlayerDoc(**raw)
        foe_sect = foe_doc.ext.get("sect")
        if not foe_sect:
            yield event.plain_result("对方尚无宗门，无从开战。")
            return
        if foe_sect == my_sect:
            yield event.plain_result("同门相争，伤和气。")
            return
        now = time.time()
        last = float(doc.ext.get("sectwar_ts") or 0)
        if now - last < 300:
            yield event.plain_result(f"宗门战鼓尚未重擂，{int(300 - (now - last))} 秒后可再战。")
            return
        my_sect_doc = await self.db.get_sect(my_sect)
        foe_sect_doc = await self.db.get_sect(foe_sect)
        if not my_sect_doc or not foe_sect_doc:
            yield event.plain_result("宗门数据异常。")
            return
        my_power, my_members = await self._sect_power(my_sect)
        foe_power, foe_members = await self._sect_power(foe_sect)
        import random as _random
        rng = _random.Random(f"war:{my_sect}:{foe_sect}:{now}")
        my_roll = my_power * (0.9 + 0.2 * rng.random())
        foe_roll = foe_power * (0.9 + 0.2 * rng.random())
        won = my_roll >= foe_roll
        d1 = doc.model_copy()
        d1.ext["sectwar_ts"] = now
        await self.db.save_player(d1.model_dump())
        async with self.db.transaction():
            await self.db.add_sect_score(my_sect, 3 if won else 1)
            await self.db.add_sect_score(foe_sect, 1 if won else 3)
        verdict = (
            f"【{my_sect}】攻破【{foe_sect}】山门！宗门积分 +3" if won
            else f"【{my_sect}】不敌【{foe_sect}】，铩羽而归。积分 +1"
        )
        yield event.plain_result(
            f"=== 宗门挑战 ===\n"
            f"【{my_sect}】战力 {my_power}（{len(my_members)} 人）掷骰 {int(my_roll)}\n"
            f"【{foe_sect}】战力 {foe_power}（{len(foe_members)} 人）掷骰 {int(foe_roll)}\n"
            f"{verdict}，对方 {'+1' if won else '+3'}。\n"
            f"当前积分：{my_sect} {my_sect_doc['score'] + (3 if won else 1)}"
            f" vs {foe_sect} {foe_sect_doc['score'] + (1 if won else 3)}"
        )

    # ---- 宗门商店 / 仙宠（M8） ----

    SECT_SHOP_ITEMS = ("血莲丹", "生骨丹", "攻击宝石", "生命宝石", "暴击宝石", "玄铁")
    SECT_PRICE_MULT = 3.0   # 贡献价 = 出售价 ×3

    @filter.command(CMD_SECT_SHOP, "宗门商店")
    async def handle_sect_shop(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = doc.ext.get("sect")
        if not name:
            yield event.plain_result("道友尚无宗门，宗门商店不对外。")
            return
        contrib = int(doc.ext.get("sect_contrib", 0))
        lines = [
            f"--- 【{name}】宗门商店 ---",
            f"道友贡献度：{contrib}",
        ]
        for n in self.SECT_SHOP_ITEMS:
            item = self.item_index.get(n)
            if not item:
                continue
            price = max(1, int(float(item.get("出售价", 1) or 1) * self.SECT_PRICE_MULT))
            lines.append(f"· {n} — {price} 贡献度（{item.get('type', item.get('class', '?'))}）")
        lines.append(f"兑换：{CMD_SECT_EXCHANGE} 商品名 数量")
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_SECT_EXCHANGE, "宗门兑换")
    async def handle_sect_exchange(self, event: AstrMessageEvent, item_name: str = "", qty: int = 1):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = doc.ext.get("sect")
        if not name:
            yield event.plain_result("道友尚无宗门。")
            return
        item_name = (item_name or "").strip()
        qty = max(1, min(int(qty or 1), 10))
        if item_name not in self.SECT_SHOP_ITEMS:
            yield event.plain_result(f"商店无此货：「{item_name}」。发「{CMD_SECT_SHOP}」查看。")
            return
        item = self.item_index.get(item_name)
        if not item:
            yield event.plain_result("商品数据异常。")
            return
        unit = max(1, int(float(item.get("出售价", 1) or 1) * self.SECT_PRICE_MULT))
        cost = unit * qty
        contrib = int(doc.ext.get("sect_contrib", 0))
        if contrib < cost:
            yield event.plain_result(
                f"贡献度不足：需 {cost}，道友有 {contrib}。多「{CMD_SECT_DONATE} 数量」捐献即涨。"
            )
            return
        sdoc = await self.db.get_sect(name)
        if not sdoc:
            yield event.plain_result("宗门数据异常。")
            return
        restock = int(float(item.get("出售价", 1) or 1)) * qty   # 宗门按成本出货
        if sdoc["fund"] < restock:
            yield event.plain_result(
                f"宗门仓库空虚（基金 {sdoc['fund']} < 出货成本 {restock}），快「{CMD_SECT_DONATE}」补货。"
            )
            return
        d = doc.model_copy()
        d.ext["sect_contrib"] = contrib - cost
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.add_items(doc.uid, {item_name: qty})
            await self.db.update_sect(name, sdoc["level"], sdoc["fund"] - restock)
        yield event.plain_result(
            f"兑换 {item_name} ×{qty}：贡献度 -{cost}（余 {d.ext['sect_contrib']}），"
            f"宗门基金 -{restock}（余 {sdoc['fund'] - restock}）。"
        )

    def _pet_info(self, doc: PlayerDoc) -> tuple[dict | None, dict | None]:
        """(宠物会话, 宠物图鉴条目)。"""
        pet = doc.ext.get("pet")
        if not pet or not pet.get("name"):
            return None, None
        return pet, self.item_index.get(str(pet["name"]))

    @filter.command(CMD_PET_GET, "领养仙宠")
    async def handle_pet_get(self, event: AstrMessageEvent, pet_name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if doc.ext.get("pet"):
            yield event.plain_result("道友已有仙宠相伴，一人一宠。")
            return
        pet_name = (pet_name or "").strip()
        info = self.item_index.get(pet_name)
        if not info or info.get("class") != "仙宠":
            yield event.plain_result(f"「{pet_name}」不是仙宠。仙宠现世于坊市与拍卖行。")
            return
        inv = await self.db.get_inventory(doc.uid)
        if inv.get(pet_name, 0) < 1:
            yield event.plain_result(f"纳戒中没有「{pet_name}」——领养需仙宠本体。")
            return
        cost = max(1000, int(float(info.get("出售价", 1000) or 1000) * 2))
        if doc.stones < cost:
            yield event.plain_result(f"领养需以 {cost} 灵石立契约，道友不足。")
            return
        d = doc.model_copy(update={"stones": doc.stones - cost})
        d.ext["pet"] = {"name": pet_name, "level": max(1, int(info.get("等级", 1) or 1))}
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if not await self.db.remove_item(doc.uid, pet_name, 1):
                raise RuntimeError("INSUFFICIENT")
        yield event.plain_result(
            f"「{pet_name}」（{info.get('品级', '?')}）认主成功！契约灵石 {cost}。\n"
            f"发「{CMD_PET_MY}」查看，{CMD_PET_FEED} 灵石 可喂养升级。"
        )

    @filter.command(CMD_PET_MY, "我的仙宠")
    async def handle_pet_my(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        my_pet, info = self._pet_info(doc)
        if not my_pet:
            yield event.plain_result(f"尚无仙宠。领养：{CMD_PET_GET} 名字（仙宠本体需在纳戒）。")
            return
        lv_cap = int((info or {}).get("等级上限", 100) or 100)
        lv = min(int(my_pet.get("level", 1)), lv_cap)
        base_b = float((info or {}).get("初始加成") or 0)
        per_lv = float((info or {}).get("每级增加") or 0)
        bonus = base_b + per_lv * (lv - 1)
        st = self._stats(doc)
        tal = pet.talent_of(my_pet)
        tal_line = f"天赋：【{tal['name']}】（{tal['rarity']}）{talent_desc(tal)}" if tal else "天赋：未觉醒（进阶时随机觉醒）"
        pet_data = {
            "pet_name": my_pet["name"], "grade": (info or {}).get("品级", "?"),
            "level": lv, "cap": lv_cap,
            "wins": int(doc.ext.get("pet_wins", 0)),
            "talent": tal_line, "bonus_pct": f"{bonus * 100:.1f}",
            "desc": ((info or {}).get("desc") or "")[:80],
        }
        if self.render_on:
            png = await render.render_panel("pet", pet_data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        lines = [
            f"--- 仙宠 {my_pet['name']}（{(info or {}).get('品级', '?')}）---",
            f"等级 {lv}/{lv_cap}｜成长 {int(my_pet.get('exp', 0))}/9｜战绩 {int(doc.ext.get('pet_wins', 0))} 胜",
            tal_line,
            f"三维加成 +{bonus:.1%}",
            f" desc：{((info or {}).get('desc') or '')[:60]}",
            f"当前属性：攻击 {st.atk} · 防御 {st.defense} · 血量 {st.hp}",
            f"喂养：{CMD_PET_FEED} 灵石数（每 1000 灵石 = 1 级）",
        ]
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_PET_FEED, "喂养仙宠")
    async def handle_pet_feed(self, event: AstrMessageEvent, stones: int = 0):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        my_pet, info = self._pet_info(doc)
        if not my_pet:
            yield event.plain_result("道友尚无仙宠。")
            return
        stones = int(stones or 0)
        if stones < 1000:
            yield event.plain_result(f"格式：{CMD_PET_FEED} 灵石数（每 1000 灵石升 1 级，最少 1000）")
            return
        lv_cap = int((info or {}).get("等级上限", 100) or 100)
        lv = min(int(my_pet.get("level", 1)), lv_cap)
        if lv >= lv_cap:
            yield event.plain_result(f"「{my_pet['name']}」已达等级上限 {lv_cap}。")
            return
        stones = min(stones, doc.stones)
        gain_lv = min(lv_cap - lv, stones // 1000)
        spent = gain_lv * 1000
        if gain_lv < 1:
            yield event.plain_result("灵石不足升级（每级 1000）。")
            return
        d = doc.model_copy(update={"stones": doc.stones - spent})
        d.ext["pet"] = {"name": my_pet["name"], "level": lv + gain_lv}
        await self.db.save_player(d.model_dump())
        st = self._stats(d)
        yield event.plain_result(
            f"「{pet['name']}」升至 {lv + gain_lv} 级（耗 {spent} 灵石）！加成上涨。\n"
            f"当前属性：攻击 {st.atk} · 防御 {st.defense} · 血量 {st.hp}"
        )

    @filter.command(CMD_PET_FREE, "放生仙宠")
    async def handle_pet_free(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if not doc.ext.get("pet"):
            yield event.plain_result("道友本就没有仙宠。")
            return
        d = doc.model_copy()
        name = d.ext.pop("pet")["name"]
        await self.db.save_player(d.model_dump())
        yield event.plain_result(f"已放生「{name}」，愿它归山快活。（仙宠本体不返还，领养需重新获得）")

    # ---- 宠物对战（M9） ----

    @filter.command(CMD_PET_DUEL, "宠物对战")
    async def handle_pet_duel(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        target_uid = self._at_target(event)
        if not target_uid:
            yield event.plain_result(f"格式：{CMD_PET_DUEL} @道友")
            return
        if target_uid == doc.uid:
            yield event.plain_result("自己的宠物不打自己的宠物。")
            return
        now = time.time()
        last = float(doc.ext.get("petduel_ts") or 0)
        if now - last < 60:
            yield event.plain_result(f"宠物们刚玩闹过，正在歇息，{60 - int(now - last)} 秒后再来。")
            return
        mine, my_info = self._pet_info(doc)
        if not mine:
            yield event.plain_result(f"道友尚无出战仙宠。发「{CMD_PET_GET} 名字」领养。")
            return
        raw = await self.db.get_player(target_uid)
        if not raw:
            yield event.plain_result("对方尚未踏入仙途。")
            return
        foe = PlayerDoc(**raw)
        theirs, foe_info = self._pet_info(foe)
        if not theirs:
            yield event.plain_result("对方还没有仙宠，无处对决。")
            return

        my_pb = pet.build(mine, self.item_index.get)
        foe_pb = pet.build(theirs, self.item_index.get)
        if not my_pb or not foe_pb:
            yield event.plain_result("宠物图鉴数据异常。")
            return
        import random as _random
        rng = _random.Random(f"petduel:{doc.uid}:{target_uid}:{now}")
        winner, log = pet.duel(my_pb, foe_pb, rng)

        # 成长结算：胜 +3 / 平 +1 / 负 0；每 9 成长升 1 级
        d1 = doc.model_copy()
        d1.ext["petduel_ts"] = now
        my_exp_gain = pet.GAIN_WIN if winner == 0 else (pet.GAIN_DRAW if winner is None else 0)
        my_pet, my_up = pet.gain_exp(mine, my_exp_gain, self.item_index.get)
        d1.ext["pet"] = my_pet
        d1.ext["pet_wins"] = int(d1.ext.get("pet_wins", 0)) + (1 if winner == 0 else 0)
        foe_pet, foe_up = pet.gain_exp(theirs, pet.GAIN_WIN if winner == 1 else (pet.GAIN_DRAW if winner is None else 0), self.item_index.get)
        d2 = foe.model_copy()
        d2.ext["pet"] = foe_pet
        d2.ext["pet_wins"] = int(d2.ext.get("pet_wins", 0)) + (1 if winner == 1 else 0)
        async with self.db.transaction():
            await self.db.save_player(d1.model_dump())
            await self.db.save_player(d2.model_dump())

        name_a, name_b = my_pb.unit.name, foe_pb.unit.name
        result = (
            f"宠物对战：{name_a} 胜！（+3 成长）" if winner == 0
            else f"宠物对战：{name_b} 胜！（+3 成长）" if winner == 1
            else "宠物对战：平局（各 +1 成长）"
        )
        shown = log[:6] + [f"…（共 {len(log)} 回合）"] if len(log) > 7 else log
        if self.render_on:
            pdd = {
                "title": "仙宠对战", "sub": "成长赛", "footer": "诸天修仙",
                "side_a": {"name": my_pb.unit.name, "atk": my_pb.unit.atk,
                           "defense": my_pb.unit.defense, "hp": my_pb.unit.hp},
                "side_b": {"name": foe_pb.unit.name, "atk": foe_pb.unit.atk,
                           "defense": foe_pb.unit.defense, "hp": foe_pb.unit.hp},
                "log": shown, "result": result, "extras": [],
            }
            png = await render.render_panel("battle", pdd, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        up_note = ""
        if my_up:
            up_note += f"\n{name_a} 升至 {my_pet['level']} 级！"
        if foe_up:
            up_note += f"\n{name_b} 升至 {foe_pet['level']} 级！"
        yield event.plain_result(
            "\n".join(shown) + "\n" + result + up_note
            + f"\n{name_a} {my_pb.level}级·成长{my_pet['exp']}/9 · {name_b} {foe_pb.level}级·成长{foe_pet['exp']}/9"
        )

    @filter.command(CMD_PET_RANK, "仙宠榜")
    async def handle_pet_rank(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        rows = []
        for p in await self.db.all_players():
            pet_data = (p.get("ext") or {}).get("pet")
            if not pet_data or not pet_data.get("name"):
                continue
            rows.append((p, pet_data))
        if not rows:
            yield event.plain_result("天下尚无驯宠之人。")
            return
        rows.sort(key=lambda x: (-int(x[1].get("level", 1)), -int(x[1].get("exp", 0))))
        lines = ["--- 仙宠榜 · 等级前十 ---"]
        for i, (p, pet_data) in enumerate(rows[:10], 1):
            name = p.get("name") or p["uid"][:8] + "…"
            info = self.item_index.get(str(pet_data["name"])) or {}
            lines.append(
                f"{i}. {pet_data['name']}（{info.get('品级', '?')}）{pet_data.get('level', 1)} 级"
                f" — 主人 {name}｜战绩 {int((p.get('ext') or {}).get('pet_wins', 0))} 胜"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command(CMD_PET_ADV, "进阶仙宠")
    async def handle_pet_advance(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        mine, info = self._pet_info(doc)
        if not mine or not info:
            yield event.plain_result("道友尚无仙宠。")
            return
        grade = str(info.get("品级", "仙胎"))
        if grade not in pet.GRADE_CHAIN:
            yield event.plain_result("品级数据异常。")
            return
        if grade == pet.GRADE_CHAIN[-1]:
            yield event.plain_result(f"「{mine['name']}」已是 {grade} 之境，无可再进。")
            return
        cap = pet.GRADE_CAPS.get(grade, 0)
        if int(mine.get("level", 1)) < cap:
            yield event.plain_result(
                f"灵韵不足：进阶需「{mine['name']}」修至 {cap} 级（现 {mine.get('level', 1)}）。"
                f"发「{CMD_PET_FEED} 灵石数」喂养。"
            )
            return
        nxt_info = pet.next_form(info, self.pet_by_id)
        if not nxt_info:
            yield event.plain_result(f"「{mine['name']}」暂无可用的进阶形态。")
            return
        food, food_qty = pet.ADVANCE_FOOD.get(grade, ("", 0))
        cost = pet.advance_cost(grade)
        inv = await self.db.get_inventory(doc.uid)
        lack = []
        if food and inv.get(food, 0) < food_qty:
            lack.append(f"{food}(需{food_qty}有{inv.get(food, 0)})")
        if doc.stones < cost:
            lack.append(f"灵石(需{cost}有{doc.stones})")
        if lack:
            yield event.plain_result(
                f"进阶材料不足：{'、'.join(lack)}。口粮出自秘境灵物与坊市。"
            )
            return
        import random as _random
        talent = pet.roll_talent(_random.Random(f"talent:{doc.uid}:{nxt_info['name']}:{time.time()}"))
        d = doc.model_copy(update={"stones": doc.stones - cost})
        d.ext["pet"] = {
            "name": str(nxt_info["name"]), "level": int(mine.get("level", 1)),
            "exp": int(mine.get("exp", 0)), "talent": talent["name"],
        }
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if food:
                if not await self.db.remove_item(doc.uid, food, food_qty):
                    raise RuntimeError("INSUFFICIENT")
        st = self._stats(d)
        yield event.plain_result(
            f"天降灵韵！「{mine['name']}」进阶为「{nxt_info['name']}」（{nxt_info.get('品级')}，"
            f"等级上限 {pet.GRADE_CAPS.get(str(nxt_info.get('品级')))}）！\n"
            f"品级觉醒：宠物对战暴击率 {pet.GRADE_CRIT.get(str(nxt_info.get('品级'))):.0%}。\n"
            f"天赋觉醒：【{talent['name']}】（{talent['rarity']}）——{talent_desc(talent)}\n"
            f"当前属性：攻击 {st.atk} · 防御 {st.defense} · 血量 {st.hp}"
        )
