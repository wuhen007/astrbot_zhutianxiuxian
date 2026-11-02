"""诸天修仙 —— AstrBot 原生插件（M0：骨架 + 存储层 + 内容加载 + 建档/面板）。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from .core.player import PlayerDoc, create_player, next_realm_entry, realm_entry
from .core import adventure, alchemy, battle, boss, catalog, cultivate, dibing, equipment, items, linggen, endless, motou, npc, occupation, pet, quest, raid, secret, sect, shenjie, story_npc, universe, wenxian, world_deep, xiaoshijie, yuanshi, zhutian
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
CMD_MIRROR = "#诸天镜"
CMD_MIRROR_REFINE = "#淬炼诸天镜"
CMD_MIRROR_WORLDS = "#诸天世界"
CMD_MIRROR_PROJ = "#投影诸天"
CMD_MIRROR_CHOICE = "#选择"
CMD_MIRROR_EXIT = "#退出投影"
CMD_MIRROR_AVATAR = "#诸天化身"
CMD_MIRROR_LOAD = "#装载化身"
CMD_XT_USE = "#使用诸天镜"
CMD_UNI = "#大宇宙"
CMD_UNI_ASCEND = "#升格大宇宙"
CMD_UNI_LAW = "#完善宇宙法则"
CMD_UNI_AURA = "#炼化宇宙灵韵"
CMD_UNI_FORGE = "#铸造宇宙秘境"
CMD_UNI_LIST = "#宇宙秘境"
CMD_UNI_ENTER = "#进入宇宙秘境"
CMD_UNI_DERIVE = "#演绎宇宙秘境"
CMD_TOWER = "#挑战镇妖塔"
CMD_TOWER_ALL = "#一键挑战镇妖塔"
CMD_PET_SEND = "#派仙宠寻宝"
CMD_PET_COLLECT = "#结束仙宠寻宝"
CMD_RAID_LIST = "#洗劫列表"
CMD_RAID = "#洗劫"
CMD_RAID_SPY = "#探查"
CMD_GIFT = "#赠予花篮"
CMD_DB_FORGE = "#炼制帝兵"
CMD_DB_FUSE = "#融合帝兵"
CMD_DB_TRIB = "#雷劫洗礼帝兵"
CMD_DB_NURTURE = "#蕴养帝兵"
CMD_DB_RENAME = "#为帝兵更名"
CMD_DB_MY = "#我的帝兵"
CMD_CLOW_DECK = "#库洛牌组合"
CMD_MOON_TRIAL = "#月之审判"
CMD_DREAM_TRIAL = "#梦之试炼"
CMD_SAKURA_ADV = "#小樱进阶"
CMD_DECADE_DECK = "#编组骑士卡片"
CMD_FINAL_RIDE = "#最终攻击驾驭"
CMD_REDEEM = "#救赎"
CMD_WXL = "#问仙令"
CMD_WXL_CLUE = "#重金求取问仙线索"
CMD_WXL_EXPLORE = "#探索问仙线索"
CMD_WXL_ACT = "#激活问仙令"
CMD_WXL_DAILY = "#问仙令任务"
CMD_WXL_CLAIM = "#领取问仙令"
CMD_WXL_WEEKLY = "#领取每周任务"
CMD_STONE_MARKET = "#源石坊"
CMD_STONE_INSPECT = "#勘石"
CMD_STONE_BUY = "#购石"
CMD_STONE_EXCHANGE = "#源石兑换"
CMD_EVIL_SLAY = "#镇魂"
CMD_EVIL_DISPOSE = "#处置"
CMD_EVIL_MAGIC = "#修炼魔功"
CMD_EVIL_MOSHI = "#供奉魔石"
CMD_EVIL_BREAK = "#冲击魂印"
CMD_EVIL_REFINE = "#炼化遗蜕"
CMD_NPC = "#剧情人物"
CMD_NPC_ALIAS = "#剧情人物图鉴"
CMD_FIERCE_TALK = "#狠人交流"
CMD_FIERCE_ASK = "#狠人请教"
CMD_SU_TALK = "#苏灵交流"
CMD_SU_ASK = "#苏灵请教"
CMD_ESSENCE = "#凝聚精血"
CMD_PROTECT_LIU = "#请柳神护道"
CMD_PROTECT_SU = "#请苏灵护道"
CMD_PROTECT_HEN = "#请狠人护道"
CMD_PROTECT_MY = "#我的护道人"
CMD_PROTECT_OFF = "#解除护道"
CMD_HEI = "#黑皇"
CMD_HEI_TALK = "#黑皇交流"
CMD_HEI_TEACH = "#黑皇请教阵道"
CMD_HEI_ARRAYS = "#黑皇阵法"
CMD_HEI_ENGRAVE = "#请黑皇刻阵"
CMD_ARRAY_OFF = "#停用阵法"
CMD_ARRAY_ON = "#启用阵法"
CMD_TR_CREATE = "#创建讨伐队伍"
CMD_TR_JOIN = "#加入讨伐队伍"
CMD_TR_START = "#发起讨伐"
CMD_TR_HIT = "#讨伐出手"
CMD_TR_INFO = "#查看队伍信息"
CMD_TR_LIST = "#团本列表"
CMD_TR_DISMISS = "#解散队伍"
CMD_TR_CLAIM = "#结算团本奖励"
CMD_ENDLESS = "#无尽劫境"
CMD_ENDLESS_START = "#开启无尽劫境"
CMD_ENDLESS_MAP = "#劫途星图"
CMD_ENDLESS_ROUTE = "#星图定途"
CMD_ENDLESS_NEXT = "#无尽下一关"
CMD_ENDLESS_PICK = "#无尽选择"
CMD_ENDLESS_CHECKPOINT = "#劫后抉择"
CMD_ENDLESS_BUILD = "#无尽构筑"
CMD_ENDLESS_QUIT = "#无尽撤离"
CMD_ENDLESS_TIER = "#无尽难度"
CMD_ENDLESS_CELESTIAL = "#今日天象"
CMD_ENDLESS_RANK = "#无尽排名"
CMD_ENDLESS_SHOP = "#无尽商店"
CMD_ENDLESS_BUY = "#无尽购买"
CMD_ENDLESS_MERCHANT = "#劫境商人"
CMD_ENDLESS_MERCHANT_BUY = "#劫境购买"
CMD_ENDLESS_TITLES = "#称号"
CMD_ENDLESS_TITLES_ALIAS = "#我的称号"
CMD_ENDLESS_TITLE_EQUIP = "#佩戴称号"
CMD_ENDLESS_WEEKEND = "#周末免费"
CMD_ENDLESS_META = "#万劫道碑"
CMD_ENDLESS_META_UP = "#参悟道碑"
CMD_ENDLESS_META_RESET = "#重置万劫道碑"
CMD_ENDLESS_META_RESET_YES = "#确认重置万劫道碑"
CMD_ENDLESS_TREASURE = "#无尽至宝"
CMD_ENDLESS_TREASURE_UP = "#升级无尽至宝"
CMD_ENDLESS_TREASURE_EQUIP = "#装备无尽至宝"
CMD_ENDLESS_TREASURE_UNEQUIP = "#卸下无尽至宝"
CMD_ENDLESS_TREASURE_SLOT = "#拓展无尽至宝槽"
CMD_ENDLESS_REROLL = "#重置无尽能力"
CMD_ENDLESS_SWEEP = "#扫荡无尽劫境"
CMD_DARK_OPEN = "#开启黑暗动乱"
CMD_DARK_CLOSE = "#关闭黑暗动乱"
CMD_DARK_STATUS = "#禁区至尊状态"
CMD_DARK_FIGHT = "#平定黑暗动乱"
CMD_DARK_RANK = "#黑暗动乱帝战贡献榜"
CMD_SHENPO = "#炼神魄"
CMD_SHENPO_ALL = "#一键炼神魄"
CMD_OFFER = "#供奉神石"
CMD_CANWU = "#参悟神石"
CMD_STONE = "#敲开闪闪发光的石头"
CMD_SHENJIE = "#踏入神界"
CMD_SHENJIE_END = "#神界归来"
CMD_EVIL = "#我的邪道"
CMD_RECRUIT_ON = "#开启收徒"
CMD_RECRUIT_OFF = "#关闭收徒"
CMD_BAISHI = "#拜师"
CMD_SHITU_END = "#解除师徒关系"
CMD_MY_TUDI = "#我的弟子"
CMD_MY_SHIFU = "#我的师门"
CMD_SHIFU_LIST = "#查看师傅列表"
CMD_MARRY = "#结为道侣"
CMD_MARRY_YES = "我愿意"
CMD_MARRY_NO = "我拒绝"
CMD_DIVORCE = "#断绝姻缘"
CMD_QINMI = "#查询亲密度"
CMD_GIVE_STONES = "#补发灵石"
CMD_VIEW_PLAYER = "#查看玩家"
CMD_RESET_TASK = "#重置每日任务"
CMD_BAN = "#封禁修仙"
CMD_UNBAN = "#解封修仙"
CMD_SHITU_TRIAL = "#开始师徒试炼"
CMD_SHITU_SUBMIT = "#提交师徒任务"
CMD_SHITU_SHOP = "#师徒商店"
CMD_SHITU_EX = "#师徒兑换"
CMD_RECAST = "#神兵重铸"
CMD_SHUANGXIU = "#双修"
CMD_WORLD_CREATE = "#开辟小世界"
CMD_WORLD_UP = "#演化小世界"
CMD_WORLD_MY = "#我的小世界"
CMD_WORLD_AVATAR = "#将分身化入小世界"
CMD_WORLD_HARVEST = "#收获小世界资源"
CMD_WORLD_PLANT = "#小世界栽种"
CMD_WORLD_BATCH = "#一键种植"
CMD_WORLD_WATER = "#一键浇灌普通"
CMD_PLANT_GUIDE = "#种植指南"
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
        if doc.ext.get("banned"):
            return None, "道友已被打入天牢，静候管理员赦免。"
        return doc, None

    SMART_TEXT_LIMIT = 200

    def _is_panel(self, text: str) -> bool:
        """面板判定：超字数、或行数 ≥5、或以 --- 标题行开头 → 出图。"""
        if len(text) > self.SMART_TEXT_LIMIT:
            return True
        lines = [ln for ln in text.split("\n") if ln.strip()]
        return len(lines) >= 5 or text.lstrip().startswith("---")

    async def _smart(self, event: AstrMessageEvent, text: str, title: str = "诸天修仙"):
        """智能回复：长文本/多行面板自动转通用面板图，渲染失败回退原文。"""
        if not self._is_panel(text):
            yield event.plain_result(text)
            return
        if self.render_on:
            png = await render.render_panel(
                "text",
                {"title": title, "footer": "智能排版", "lines": text.split("\n")},
                self.panel_dir,
            )
            if png:
                yield event.image_result(str(png))
                return
        yield event.plain_result(text)

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
        # 本命帝兵是玩家私有数据（不在全局 item_index），按玩家注入 lookup 避免跨玩家同名污染
        w = dibing.system_of(doc)
        if w:
            card = dibing.item_card(w)
            name = card["name"]

            def lookup(n: str):
                if n == name:
                    return card
                return self.item_index.get(n)
        else:
            lookup = self.item_index.get
        st = equipment.aggregate(
            doc, self.content.table(doc.realm_table), lookup,
            doc.ext.get("enh"), set(doc.ext.get("imperial") or []),
        )
        # 魔头禁术：魔功 + 魂奴 三维加成（乘法叠加）
        ev = motou.state_of(doc)
        mult = 1.0 + motou.magic_bonus(ev) + motou.slave_bonus(ev, time.time())
        if abs(mult - 1.0) > 1e-9:
            st = equipment.Stats(
                atk=int(st.atk * mult), defense=int(st.defense * mult),
                hp=int(st.hp * mult), bao=st.bao, set_lines=st.set_lines,
            )
        return st

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
            {"title": "神界邪道", "lines": [
                (CMD_OFFER, "供奉神石（进度 /200，魔道值>0 被拒）"),
                (f"{CMD_CANWU} 次数", "参悟神石（8 石/次得限定丹药）"),
                (f"{CMD_STONE} 次数", "敲开闪闪发光的石头（赌石）"),
                (CMD_SHENJIE, "踏入神界（供奉圆满+220 万灵石+每日 1 次）"),
                (CMD_SHENJIE_END, "神界归来结算"),
                (CMD_EVIL, "我的邪道（魔道值/业力）"),
            ]},
            {"title": "小世界", "lines": [
                (f"{CMD_WORLD_CREATE} 世界名", "开辟小世界（成仙+世界石×1）"),
                (CMD_WORLD_UP, "演化升级（1-5 级，材料逐级）"),
                (CMD_WORLD_MY, "查看世界总览"),
                (CMD_WORLD_AVATAR, "分身化入（100 万修为开启挂机）"),
                (CMD_WORLD_HARVEST, "收获资源与成熟作物（96h 封顶×流速）"),
                (f"{CMD_WORLD_PLANT} 种子名", "栽种神药（#种植指南 查看）"),
                (f"{CMD_WORLD_BATCH} 种子名", "一键种植"),
                (CMD_WORLD_WATER, "一键浇灌（生长-30 分，6h 冷却）"),
            ]},
            {"title": "师徒道侣", "lines": [
                (f"{CMD_RECRUIT_ON} / {CMD_RECRUIT_OFF}", "开启/关闭收徒"),
                (f"{CMD_BAISHI} @师傅", "拜师（师傅须开收徒，解除后 3h CD）"),
                (CMD_SHITU_END, "解除师徒关系"),
                (f"{CMD_MY_TUDI} / {CMD_MY_SHIFU}", "我的弟子 / 我的师门"),
                (CMD_SHIFU_LIST, "查看收徒中的前辈"),
                (CMD_SHITU_TRIAL, "师徒试炼（每日 1 次，胜得积分 200+灵石）"),
                (CMD_SHITU_SUBMIT, "提交师徒任务（徒弟每日积分 50）"),
                (f"{CMD_SHITU_SHOP} / {CMD_SHITU_EX} 物品", "师徒商店与兑换"),
                ("结为道侣 @道友", "求婚（定情信物×1，对方 60 秒内我愿意）"),
                (CMD_SHUANGXIU, "双修（道侣修为+亲密度，1h CD）"),
                ("断绝姻缘 / #查询亲密度", "道侣解除与亲密度"),
            ]},
            {"title": "锻造补充", "lines": [
                (f"{CMD_RECAST} 原名 新名", "神兵重铸（重铸卡改名，穿戴同步）"),
            ]},
            {"title": "管理", "lines": [
                (f"{CMD_GIVE_STONES} @玩家 数量", "补发灵石（管理员）"),
                (f"{CMD_VIEW_PLAYER} @玩家", "查看玩家档案（管理员）"),
                (f"{CMD_RESET_TASK} @玩家", "重置每日任务（管理员）"),
                (f"{CMD_BAN} / {CMD_UNBAN} @玩家", "打入天牢 / 赦免（管理员）"),
            ]},
            {"title": "天机阁", "lines": [
                ("#天机阁", "天机阁商店（仙兽玉/白泽玉代币）"),
                ("#天机阁兑换 物品 数量", "兑换"),
                ("#天机符楼", "符楼商店（需邀请函，顶级灵石代币）"),
                ("#天机符楼兑换 物品 数量", "兑换"),
                ("双修彩蛋", "特定体质道侣双修可融合更高灵根（圣体道胎/终焉神魔体/混沌体）"),
            ]},
            {"title": "本命帝兵", "lines": [
                (f"{CMD_DB_FORGE} 仙金*帝兵名", "炼制本命帝兵（名称须含剑/鼎/枪/钟/塔等形态字）"),
                (CMD_DB_MY, "查看帝兵（品阶/潜力/融合/蕴养）"),
                (f"{CMD_DB_FUSE} 仙金名", "融合仙金提潜力（每种限一次，九金齐备解锁雷劫）"),
                (CMD_DB_TRIB, "雷劫洗礼进阶（需九金全融合）"),
                (f"{CMD_DB_NURTURE}*次数", "蕴养（修为血气各 2000 万/次，三维 +50 万）"),
                (f"{CMD_DB_RENAME} 新名", "更名（仍须含形态字）"),
            ]},
            {"title": "历练寻宝", "lines": [
                (CMD_TOWER, "挑战当前层（胜+5 层得灵石，败罚灵石）"),
                (CMD_TOWER_ALL, "连打到战败或 60 层（每层回满血）"),
                (CMD_PET_SEND, "派仙宠寻宝（800 万灵石，120 分钟）"),
                (CMD_PET_COLLECT, "召回收获（每 4 分钟 1 次，最多 8 次）"),
                (CMD_RAID_LIST, "洗劫地点一览"),
                (f"{CMD_RAID_SPY} 地点", "花 0.3×价格打探收获"),
                (f"{CMD_RAID} 地点", "洗劫（强化费+战斗，2h CD，魔道值+）"),
                (f"{CMD_GIFT} @道侣", "赠百合花篮（亲密度 +10）"),
            ]},
            {"title": "团本讨伐", "lines": [
                (f"{CMD_TR_CREATE} 名字", "创建讨伐队伍（5 人，24h 有效）"),
                (f"{CMD_TR_JOIN} 队伍码", "加入队伍"),
                (CMD_TR_START, "队长发起讨伐（按全队均攻定标）"),
                (CMD_TR_HIT, "出手（每日 3 次，20 秒间隔）"),
                (CMD_TR_INFO, "队伍信息 / Boss 血条 / 伤害榜"),
                (CMD_TR_LIST, "招募中的团本"),
                (CMD_TR_CLAIM, "结算明细（击杀时已自动发放）"),
                (CMD_TR_DISMISS, "解散队伍（队长）"),
            ]},
            {"title": "无尽劫境", "lines": [
                (f"{CMD_ENDLESS_START} [世界]", f"开启 10 层劫环（{endless.ENTRY_COST:,} 灵石，第 {endless.ENTRY_REALM} 境）"),
                (CMD_ENDLESS_MAP, "劫途星图：三途选一"),
                (f"{CMD_ENDLESS_ROUTE} 1-3", "定途"),
                (CMD_ENDLESS_NEXT, "推进当前层（战斗/机缘/休整）"),
                (f"{CMD_ENDLESS_PICK} 1-3", "道法三选一"),
                (f"{CMD_ENDLESS_CHECKPOINT} 1-3", "劫后问道（第 3/6/9 层）"),
                (CMD_ENDLESS_BUILD, "本局道法/神器/三维"),
                (CMD_ENDLESS_QUIT, "撤离，带出劫境道痕"),
                (CMD_ENDLESS_TIER, "难度 A1-A10（通关解锁）"),
                (CMD_ENDLESS_SHOP, "劫境道痕商店（每日限购）"),
                (f"{CMD_ENDLESS_BUY} 编号[*数量]", "购买（如 #无尽购买 叩仙丹*3）"),
                (CMD_ENDLESS_MERCHANT, "劫境商人（局内，每层 4 件折扣货）"),
                (f"{CMD_ENDLESS_MERCHANT_BUY} 1-4", "用未带出的道痕购买"),
                (CMD_ENDLESS_TITLES, "称号（#佩戴称号 名称）"),
                (CMD_ENDLESS_WEEKEND, "周末免费入场额度"),
                (CMD_ENDLESS_CELESTIAL, "今日天象"),
                (CMD_ENDLESS_RANK, "劫境排名"),
                (CMD_ENDLESS_META, "万劫道碑（永久强化）｜#参悟道碑 节点名"),
                (CMD_ENDLESS_TREASURE, "无尽至宝（通关解锁/升级/装备）"),
                (CMD_ENDLESS_SWEEP, "扫荡（按最高层结算道痕，每日一次）"),
                (CMD_ENDLESS_REROLL, "劫机重演（需道碑参悟，刷新三选一）"),
            ]},
            {"title": "剧情人物", "lines": [
                (CMD_NPC, "剧情人物图鉴（11 位 · 立绘/关系/线索）"),
                (f"{CMD_NPC} 名字", "人物档案（好感/关系/近事/机缘）"),
                (f"{CMD_FIERCE_TALK} / {CMD_SU_TALK}", "交流 +5~8 好感（每日 3 次）"),
                (CMD_FIERCE_ASK, "狠人请教（180 好感，授功法）"),
                (CMD_SU_ASK, "苏灵请教（240 好感，每日推演，10 次领悟终极）"),
                (CMD_HEI, "黑皇：交流 / #黑皇阵法 / #请黑皇刻阵 阵法名"),
                (CMD_PROTECT_MY, "护道之约（480 好感可立约，濒死自动出手）"),
                (CMD_ESSENCE, "凝聚精血（特殊体质每 7 天 1 份）"),
            ]},
            {"title": "魔头禁术（PvP）", "lines": [
                (CMD_EVIL, "邪道面板（魔道值/魔功/魂印/魂奴）"),
                (CMD_EVIL_MAGIC, "修炼魔功（魔道值换三维永久加成，10 层）"),
                (f"{CMD_EVIL_MOSHI} 数量", "供奉魔石（每颗魔道值 +20）"),
                (f"{CMD_EVIL_SLAY} @目标", "镇魂（魔道100+境界30+，24h CD，7 天保护期）"),
                (f"{CMD_EVIL_DISPOSE} 烙印/灭魂", "处置战果（烙印=对方魂印3天+你的魂奴 / 灭魂=遗蜕）"),
                (CMD_EVIL_REFINE, "炼化遗蜕（修为+魔道值）"),
                (CMD_EVIL_BREAK, "冲击魂印（50 万灵石，12h CD）"),
            ]},
            {"title": "源石坊赌石", "lines": [
                (f"{CMD_STONE_MARKET} [外园/地字号/天字号]", "当日 5 块原石（外园 5 万灵石起）"),
                (f"{CMD_STONE_INSPECT} 序号", "勘石看线索（1 万灵石）"),
                (f"{CMD_STONE_BUY} 序号 [档位]", "购石当场切开（凶源会反噬气血）"),
                (f"{CMD_STONE_EXCHANGE} 数量", "源石兑灵石（汇率 10）"),
            ]},
            {"title": "问仙令", "lines": [
                (CMD_WXL, "通行证面板（激活后：等级/经验/任务）"),
                (CMD_WXL_CLUE, "求取问仙线索（300 万灵石）"),
                (CMD_WXL_EXPLORE, "循迹线索（3 处）"),
                (CMD_WXL_ACT, "激活问仙令"),
                (CMD_WXL_DAILY, "领取已完成的每日任务（每项 500 经验）"),
                (f"{CMD_WXL_CLAIM} 等级", "领取升级奖励"),
                (CMD_WXL_WEEKLY, "领取每周任务（3000 经验）"),
            ]},
            {"title": "诸天世界深度", "lines": [
                (f"{CMD_CLOW_DECK} 风*翔*影", "库洛牌编组（无参查看 4 组合）"),
                (CMD_MOON_TRIAL, "月之审判（10 牌+境界，两次失败保底）"),
                (CMD_DREAM_TRIAL, "梦之试炼（52 牌+熟练度 100 三重梦境）"),
                (CMD_SAKURA_ADV, "小樱进阶（星之杖→梦之杖）"),
                (f"{CMD_DECADE_DECK} 空我*龙骑*Faiz", "骑士卡编组"),
                (CMD_FINAL_RIDE, "最终攻击驾驭（镜3阶+卡组+融合度60）"),
                (f"{CMD_REDEEM} / {CMD_REDEEM} @道友", "救赎（鹿目圆化身+希望碎片）"),
            ]},
            {"title": "诸天镜主线", "lines": [
                ("#使用诸天镜", "绑定诸天镜（天机阁 2 仙兽玉兑换）"),
                (CMD_MIRROR, "镜阶/镜能/材料/化身总览"),
                (CMD_MIRROR_REFINE, "淬炼升阶（1-7 阶，材料探索获取）"),
                (CMD_MIRROR_WORLDS, "十大投影世界与门槛"),
                (f"{CMD_MIRROR_PROJ} 世界名", "投影（1 亿修为血气 + 1 镜能，剧情抉择）"),
                ("#1 / #2 / #3 / #选择 序号", "投影剧情抉择（慧/勇/仁）"),
                ("#探索友枝町/#探索见泷原/#探索骑士世界 地点", "世界探索（镜能 -1，掉材料/卡牌/印记）"),
                (f"{CMD_MIRROR_AVATAR} / {CMD_MIRROR_LOAD} 名", "化身谱与装载（灵根替换+三维加成）"),
            ]},
            {"title": "大宇宙终局", "lines": [
                (CMD_UNI_ASCEND, "小世界 5 级+金仙+潜力151 → 升格大宇宙"),
                (f"{CMD_UNI} / #我的大宇宙", "宇宙面板（法则/灵韵/秘境）"),
                (f"{CMD_UNI_LAW}", "完善法则（承载真仙→帝光仙王）"),
                (f"{CMD_UNI_AURA} 物品*数量", "纳戒物品炼化灵韵"),
                (f"{CMD_UNI_FORGE} 名*简介*守关者", "铸造宇宙秘境（100 灵韵）"),
                (f"{CMD_UNI_DERIVE} 名", "演绎万物轮回生成秘境"),
                (f"{CMD_UNI_ENTER} 名", "挑战秘境（8h CD，胜得灵韵）"),
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
            async for _r in self._smart(event, "\n".join(lines)):
                yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        # 魔头禁术：魂印缠身 → 闭关效率 -30%
        brand_mult = motou.brand_penalty(motou.state_of(doc), time.time())
        if brand_mult < 1.0:
            eff_rate = max(1, int(eff_rate * brand_mult))
        ok, msg, d = cultivate.end_cultivate(
            doc, time.time(), eff_rate,
            int(self._val("CULTIVATE_MAX_MINUTES", 7200)),
        )
        if ok:
            self._wxl_track(d, "seclusion")  # 问仙令每日任务
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    # ---- 物品 / 坊市 ----

    # 稀有度 → 分组 [下界, 上界)/标签/颜色（修仙配色：凡→仙递进）
    _RARITY_TIERS = (
        (9, 99, "仙品 · 九阶以上", "#e88a8a"),
        (8, 9, "八阶 · 淬金", "#f0d78c"),
        (7, 8, "七阶 · 流紫", "#b48ce8"),
        (6, 7, "六阶 · 凝蓝", "#6fb8e8"),
        (4, 6, "四五行 · 凝碧", "#7ec97f"),
        (0, 4, "凡阶 · 一至三阶", "#9aa5b5"),
    )

    async def _bag_data(self, doc: PlayerDoc) -> dict:
        """纳戒数据（出图与文本回退同源）：按稀有度降序分组。"""
        inv = await self.db.get_inventory(doc.uid)
        rows = []
        for name, qty in inv.items():
            item = self.item_index.get(name, {})
            try:
                rar = int(float(item.get("稀有度") or 0))
            except (TypeError, ValueError):
                rar = 0
            rows.append({
                "name": name, "qty": int(qty),
                "cls": item.get("class", "?"),
                "typ": (item.get("type") or "")[:6],
                "rar": rar,
            })
        rows.sort(key=lambda r: (-r["rar"], -r["qty"], r["name"]))
        groups = []
        for lo, hi, label, color in self._RARITY_TIERS:
            picked = [r for r in rows if lo <= r["rar"] < hi]
            if picked:
                groups.append({
                    "label": label, "color": color,
                    "cells": [{k: r[k] for k in ("name", "qty", "cls", "typ")} for r in picked],
                })
        return {
            "kinds": len(rows),
            "total": sum(r["qty"] for r in rows),
            "groups": groups,
            "rows": rows,
        }

    async def _bag_text(self, doc: PlayerDoc) -> str:
        data = await self._bag_data(doc)
        if not data["rows"]:
            return "纳戒空空如也。坊市在等你：#商店"
        lines = [f"--- 道友的纳戒（共 {data['kinds']} 种 · {data['total']} 件）---"]
        for r in data["rows"][:40]:
            meta = f"{r['cls']}/{r['rar'] or '?'}阶" if r["rar"] else r["cls"]
            lines.append(f"· {r['name']} ×{r['qty']}（{meta}）")
        if len(data["rows"]) > 40:
            lines.append(f"…其余 {len(data['rows']) - 40} 种详见面板")
        return "\n".join(lines)

    @filter.command(CMD_BAG, "查看纳戒")
    async def handle_bag(self, event: AstrMessageEvent):
        async for r in self._bag_view(event):
            yield r

    @filter.command(CMD_BAG_ALIAS, "查看纳戒（短指令）")
    async def handle_bag_alias(self, event: AstrMessageEvent):
        async for r in self._bag_view(event):
            yield r

    async def _bag_view(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        data = await self._bag_data(doc)
        if not data["rows"]:
            yield event.plain_result("纳戒空空如也。坊市在等你：#商店")
            return
        if self.render_on:
            png = await render.render_panel(
                "bag",
                {"title": "诸天万界 · 纳戒", "sub": f"{data['kinds']} 种",
                 "footer": "稀有序 · 品阶配色", **data},
                self.panel_dir,
            )
            if png:
                yield event.image_result(str(png))
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        name = (item_name or "").strip()
        w = dibing.system_of(doc)
        is_own_dibing = bool(w and name == w.get("name"))
        item = dibing.item_card(w) if is_own_dibing else self.item_index.get(name)
        if not item:
            yield event.plain_result(f"物品索引中找不到「{item_name}」。")
            return
        ok, msg, old = equipment.wear(doc, item)
        if not ok:
            yield event.plain_result(msg)
            return
        async with self.db.transaction():
            if not is_own_dibing:
                if not await self.db.remove_item(doc.uid, item["name"], 1):
                    raise RuntimeError("INSUFFICIENT")
            if old and not (w and old == w.get("name")):
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
        w = dibing.system_of(doc)
        async with self.db.transaction():
            if not (w and old == w.get("name")):  # 本命帝兵卸下回 ext 私有档，不进纳戒
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
        self._wxl_track(doc, "raid")  # 问仙令每日任务
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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

    # ---- 神界（对齐原版 shenren.js） ----

    def _linggen_type(self, doc: PlayerDoc) -> str:
        lg = doc.ext.get("linggen")
        return str(lg.get("type", "")) if isinstance(lg, dict) else ""

    def _shenjie_gate(self, doc: PlayerDoc) -> tuple[bool, str]:
        return shenjie.offer_gate(int(doc.ext.get("modao", 0) or 0), self._linggen_type(doc))

    @filter.command(CMD_OFFER, "供奉神石")
    async def handle_offer(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        ok, why = self._shenjie_gate(doc)
        if not ok:
            yield event.plain_result(why)
            return
        inv = await self.db.get_inventory(doc.uid)
        owned = int(inv.get("神石", 0))
        if owned < 1:
            yield event.plain_result("你没有神石。")
            return
        progress = int(doc.ext.get("shenshi", 0) or 0)
        new_progress, used = shenjie.offer_shenshi(progress, owned)
        d = doc.model_copy(deep=True)
        d.ext["shenshi"] = new_progress
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.remove_item(doc.uid, "神石", used)
        note = f"供奉成功，当前供奉进度 {new_progress}/{shenjie.SHENSHI_NEED}。"
        if progress < shenjie.SHENSHI_NEED <= new_progress:
            note += "\n供奉圆满，神界之门为你虚掩——可「#踏入神界」（220 万灵石/次）。"
        yield event.plain_result(note)

    @filter.command(CMD_CANWU, "参悟神石")
    async def handle_canwu(self, event: AstrMessageEvent, times: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        ok, why = self._shenjie_gate(doc)
        if not ok:
            yield event.plain_result(why)
            return
        n = max(1, min(int("".join(ch for ch in (times or "") if ch.isdigit()) or 1), 99))
        cost = n * shenjie.CANWU_COST
        inv = await self.db.get_inventory(doc.uid)
        if int(inv.get("神石", 0)) < cost:
            yield event.plain_result(f"神石不足，需要 {cost} 个（{n} 次×8），当前 {int(inv.get('神石', 0))}。")
            return
        import random as _random
        pill_table = [e for e in (self.content.table("Timelimit/限定丹药") or []) if isinstance(e, dict) and e.get("name")]
        rewards = shenjie.canwu_rewards(pill_table, n, _random.Random(f"{doc.uid}:canwu:{time.time()}"))
        d = doc.model_copy(deep=True)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.remove_item(doc.uid, "神石", cost)
            await self.db.add_items(doc.uid, rewards)
        text = "，".join(f"{k}×{v}" for k, v in rewards.items())
        yield event.plain_result(f"参悟完成（消耗神石 {cost}）！获得：{text}")

    @filter.command(CMD_STONE, "敲石赌博")
    async def handle_stone(self, event: AstrMessageEvent, times: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        n = max(1, min(int("".join(ch for ch in (times or "") if ch.isdigit()) or 1), 99))
        inv = await self.db.get_inventory(doc.uid)
        if int(inv.get("闪闪发光的石头", 0)) < n:
            yield event.plain_result(f"闪闪发光的石头不足，需要 {n} 个，当前 {int(inv.get('闪闪发光的石头', 0))}。")
            return
        import random as _random
        pill_table = [e for e in (self.content.table("Timelimit/限定丹药") or []) if isinstance(e, dict) and e.get("name")]
        rewards = shenjie.canwu_rewards(pill_table, n, _random.Random(f"{doc.uid}:stone:{time.time()}"))
        d = doc.model_copy(deep=True)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.remove_item(doc.uid, "闪闪发光的石头", n)
            await self.db.add_items(doc.uid, rewards)
        text = "，".join(f"{k}×{v}" for k, v in rewards.items())
        yield event.plain_result(f"敲开石头，灵光乍现！获得：{text}")

    @filter.command(CMD_SHENJIE, "踏入神界")
    async def handle_shenjie(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if doc.state != "空闲":
            yield event.plain_result(f"道友正在「{doc.state}」中，无法分心。")
            return
        today = quest.date_key()
        used = doc.ext.get("shenjie_date") == today
        ok, why = shenjie.shenjie_entry_gate(
            int(doc.ext.get("shenshi", 0) or 0), doc.stones,
            int(doc.ext.get("modao", 0) or 0), self._linggen_type(doc), used)
        if not ok:
            yield event.plain_result(why)
            return
        d = doc.model_copy(deep=True)
        d.stones -= shenjie.SHENJIE_STONES
        d.state = "神界中"
        d.state_start = time.time()
        d.ext["shenjie_date"] = today
        await self.db.save_player(d.model_dump())
        yield event.plain_result(
            f"神界之门开启，你踏入其中历练 {shenjie.SHENJIE_MINUTES} 分钟。\n"
            f"归来后发「{CMD_SHENJIE_END}」结算。"
        )

    @filter.command(CMD_SHENJIE_END, "神界归来")
    async def handle_shenjie_end(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if doc.state != "神界中":
            yield event.plain_result("道友并未在神界历练。")
            return
        elapsed = max(0.0, (time.time() - doc.state_start) / 60)
        floored = int(elapsed // shenjie.SHENJIE_MINUTES) * shenjie.SHENJIE_MINUTES
        d = doc.model_copy(deep=True)
        d.state = "空闲"
        d.state_start = 0.0
        if floored < shenjie.SHENJIE_MINUTES:
            await self.db.save_player(d.model_dump())
            yield event.plain_result(f"神界历练不足 {shenjie.SHENJIE_MINUTES} 分钟，空手而归（可稍后再归）。")
            return
        import random as _random
        rewards = shenjie.shenjie_rewards()
        gain_stones = rewards.pop("__stones__")
        d.stones += gain_stones
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.add_items(doc.uid, rewards)
        text = "，".join(f"{k}×{v}" for k, v in rewards.items())
        yield event.plain_result(
            f"神界历练归来（{floored} 分钟）：灵石 +{gain_stones}，{text}！"
        )

    @filter.command(CMD_EVIL, "我的邪道")
    async def handle_evil(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = motou.state_of(doc)
        async for r in self._smart(event, motou.panel(s, time.time()), "邪道 · 魔头之路"):
            yield r

    # ---- 小世界（对齐原版 Garden/xiaoshijie.js 核心链） ----

    @filter.command(CMD_WORLD_CREATE, "开辟小世界")
    async def handle_world_create(self, event: AstrMessageEvent, world_name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = (world_name or "").strip()
        if not name:
            yield event.plain_result(f"格式：{CMD_WORLD_CREATE} 世界名（如：#开辟小世界 紫霄界）")
            return
        if doc.ext.get("xiaoshijie"):
            w = doc.ext["xiaoshijie"]
            yield event.plain_result(f"你已开辟【{w.get('name')}】，无法再开辟新的小世界。")
            return
        realm_id = max(0, doc.realm_index) + 1
        inv = await self.db.get_inventory(doc.uid)
        ok, msg, world = xiaoshijie.create_world(name, realm_id, inv)
        if not ok:
            yield event.plain_result(msg)
            return
        d = doc.model_copy(deep=True)
        d.ext["xiaoshijie"] = world
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            for item, amount in xiaoshijie.WORLD_LEVELS[1]["cost"].items():
                await self.db.remove_item(doc.uid, item, amount)
        yield event.plain_result(msg)

    @filter.command(CMD_WORLD_UP, "演化小世界")
    async def handle_world_up(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = doc.ext.get("xiaoshijie")
        if not w:
            yield event.plain_result(f"道友尚无小世界，先「{CMD_WORLD_CREATE} 世界名」。")
            return
        inv = await self.db.get_inventory(doc.uid)
        ok, msg, nw = xiaoshijie.upgrade_world(w, inv)
        if not ok:
            yield event.plain_result(msg)
            return
        cost = xiaoshijie.upgrade_cost(int(w.get("level", 1)))
        d = doc.model_copy(deep=True)
        d.ext["xiaoshijie"] = nw
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            for item, amount in cost.items():
                await self.db.remove_item(doc.uid, item, amount)
        yield event.plain_result(msg)

    @filter.command(CMD_WORLD_MY, "我的小世界")
    async def handle_world_my(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = doc.ext.get("xiaoshijie")
        if not w:
            yield event.plain_result(f"道友尚无小世界，先「{CMD_WORLD_CREATE} 世界名」（需成仙）。")
            return
        _, exp = self._ensure_occ(doc)
        yield event.plain_result(xiaoshijie.view(w, doc.exp))

    @filter.command(CMD_WORLD_AVATAR, "分身化入小世界")
    async def handle_world_avatar(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = doc.ext.get("xiaoshijie")
        if not w:
            yield event.plain_result(f"道友尚无小世界，先「{CMD_WORLD_CREATE} 世界名」。")
            return
        ok, msg, nw = xiaoshijie.bind_avatar(w, doc.exp)
        if not ok:
            yield event.plain_result(msg)
            return
        d = doc.model_copy(deep=True)
        d.exp -= xiaoshijie.AVATAR_COST
        d.ext["xiaoshijie"] = nw
        await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_WORLD_HARVEST, "收获小世界资源")
    async def handle_world_harvest(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = doc.ext.get("xiaoshijie")
        if not w:
            yield event.plain_result(f"道友尚无小世界。")
            return
        ok, msg, nw, out = xiaoshijie.harvest(w)
        if not ok:
            yield event.plain_result(msg)
            return
        stones = out.pop("__stones__", 0)
        d = doc.model_copy(deep=True)
        d.stones += stones
        d.ext["xiaoshijie"] = nw
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if out:
                await self.db.add_items(doc.uid, out)
        parts = [f"灵石 ×{stones}"] + [f"{k} ×{v}" for k, v in out.items()]
        yield event.plain_result(msg.replace("__stones__", "灵石") + f"\n合计：{'，'.join(parts)}")

    @filter.command(CMD_PLANT_GUIDE, "种植指南")
    async def handle_plant_guide(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        lines = ["--- 种植指南（种子 → 神药｜灵气需求）---"]
        for seed, (harvest, aura) in xiaoshijie.SEEDS.items():
            lines.append(f"· {seed} → {harvest}（需灵气 {aura}）")
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
    async def _world_plant(self, event: AstrMessageEvent, seed: str):
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = doc.ext.get("xiaoshijie")
        if not w:
            yield event.plain_result(f"道友尚无小世界。")
            return
        seed = (seed or "").strip()
        ok, msg, nw = xiaoshijie.plant(w, seed)
        if not ok:
            yield event.plain_result(msg)
            return
        d = doc.model_copy(deep=True)
        d.ext["xiaoshijie"] = nw
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.remove_item(doc.uid, seed, 1)
        yield event.plain_result(msg)

    @filter.command(CMD_WORLD_PLANT, "栽种神药")
    async def handle_world_plant(self, event: AstrMessageEvent, seed: str = ""):
        if not self._allowed(event):
            return
        seed = (seed or "").strip()
        if not seed:
            yield event.plain_result(f"格式：{CMD_WORLD_PLANT} 种子名（#种植指南 查看）")
            return
        async for r in self._world_plant(event, seed):
            yield r

    @filter.command(CMD_WORLD_BATCH, "一键种植")
    async def handle_world_batch(self, event: AstrMessageEvent, seed: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = doc.ext.get("xiaoshijie")
        if not w:
            yield event.plain_result(f"道友尚无小世界。")
            return
        seed = (seed or "").strip()
        inv = await self.db.get_inventory(doc.uid)
        planted = 0
        msgs: list[str] = []
        nw = w
        while True:
            ok0, msg0, nw0 = xiaoshijie.plant(nw, seed)
            if not ok0:
                msgs.append(msg0)
                break
            # 确认种子库存
            if int(inv.get(seed, 0)) < 1:
                msgs.append(f"{seed} 种子用尽（已种 {planted} 株）。")
                break
            nw = nw0
            inv = {**inv, seed: int(inv.get(seed, 0)) - 1}
            planted += 1
        if planted:
            d = doc.model_copy(deep=True)
            d.ext["xiaoshijie"] = nw
            async with self.db.transaction():
                await self.db.save_player(d.model_dump())
                await self.db.remove_item(doc.uid, seed, planted)
            yield event.plain_result(f"一键种植完成：{seed} ×{planted}。" + ("\n" + msgs[-1] if msgs else ""))
        else:
            yield event.plain_result(msgs[-1] if msgs else "未能种植。")

    @filter.command(CMD_WORLD_WATER, "一键浇灌")
    async def handle_world_water(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = doc.ext.get("xiaoshijie")
        if not w:
            yield event.plain_result(f"道友尚无小世界。")
            return
        ok, msg, nw = xiaoshijie.water(w)
        if ok:
            d = doc.model_copy(deep=True)
            d.ext["xiaoshijie"] = nw
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    # ---- 师徒 / 道侣 / 管理（对齐原版 shitu / Daolv / AdminSuper） ----

    @filter.command(CMD_RECRUIT_ON, "开启收徒")
    async def handle_recruit_on(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        d = doc.model_copy(deep=True)
        d.ext["recruit"] = True
        await self.db.save_player(d.model_dump())
        yield event.plain_result("已开启收徒，道友可「#拜师 @你」拜入你门下。")

    @filter.command(CMD_RECRUIT_OFF, "关闭收徒")
    async def handle_recruit_off(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        d = doc.model_copy(deep=True)
        d.ext["recruit"] = False
        await self.db.save_player(d.model_dump())
        yield event.plain_result("已关闭收徒。")

    @filter.command(CMD_BAISHI, "拜师")
    async def handle_baishi(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        target_uid = self._at_target(event)
        if not target_uid:
            yield event.plain_result(f"格式：{CMD_BAISHI} @师傅")
            return
        if target_uid == doc.uid:
            yield event.plain_result("不能拜自己为师。")
            return
        if doc.ext.get("shifu"):
            yield event.plain_result("你已有师承，先「#解除师徒关系」再拜新师。")
            return
        if now := time.time():
            if now - float(doc.ext.get("shitu_cd") or 0) < 3 * 3600:
                left = int(3 * 3600 - (now - float(doc.ext.get("shitu_cd") or 0)))
                yield event.plain_result(f"距离再次拜师还需 {left // 60} 分钟。")
                return
        raw = await self.db.get_player(target_uid)
        if not raw:
            yield event.plain_result("目标尚未踏入修行。")
            return
        master = PlayerDoc(**raw)
        if not master.ext.get("recruit"):
            yield event.plain_result(f"{master.name} 尚未开启收徒。")
            return
        dm = master.model_copy(deep=True)
        tudi = list(dm.ext.get("tudi") or [])
        if doc.uid in tudi:
            yield event.plain_result("你已在对方门下。")
            return
        tudi.append(doc.uid)
        dm.ext["tudi"] = tudi
        d = doc.model_copy(deep=True)
        d.ext["shifu"] = target_uid
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.save_player(dm.model_dump())
        yield event.plain_result(f"拜师成功！{doc.name} 位列 {master.name} 门下。")

    @filter.command(CMD_SHITU_END, "解除师徒关系")
    async def handle_shitu_end(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        shifu_uid = doc.ext.get("shifu")
        tudi = list(doc.ext.get("tudi") or [])
        if not shifu_uid and not tudi:
            yield event.plain_result("你并无师徒关系。")
            return
        d = doc.model_copy(deep=True)
        d.ext["shifu"] = None
        d.ext["shitu_cd"] = time.time()
        if tudi:
            d.ext["tudi"] = []
        await self.db.save_player(d.model_dump())
        # 双向清理
        other_uid = shifu_uid or (tudi[0] if tudi else None)
        if other_uid:
            raw = await self.db.get_player(other_uid)
            if raw:
                other = PlayerDoc(**raw)
                do = other.model_copy(deep=True)
                if shifu_uid == other.uid:
                    do.ext["tudi"] = [u for u in (do.ext.get("tudi") or []) if u != doc.uid]
                else:
                    do.ext["shifu"] = None
                await self.db.save_player(do.model_dump())
        yield event.plain_result("师徒关系已解除（3 小时内不可再拜师）。")

    @filter.command(CMD_MY_TUDI, "我的弟子")
    async def handle_my_tudi(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        tudi = list(doc.ext.get("tudi") or [])
        if not tudi:
            yield event.plain_result("你尚无弟子（#开启收徒 后可收徒）。")
            return
        lines = ["--- 我的弟子 ---"]
        for uid in tudi:
            raw = await self.db.get_player(uid)
            if raw:
                p = PlayerDoc(**raw)
                lines.append(f"· {p.name}（第 {max(0, p.realm_index) + 1} 境）")
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
    @filter.command(CMD_MY_SHIFU, "我的师门")
    async def handle_my_shifu(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        shifu_uid = doc.ext.get("shifu")
        if not shifu_uid:
            yield event.plain_result("你尚未拜师。")
            return
        raw = await self.db.get_player(shifu_uid)
        name = PlayerDoc(**raw).name if raw else "（已失联）"
        yield event.plain_result(f"师尊：{name}")

    @filter.command(CMD_SHIFU_LIST, "查看师傅列表")
    async def handle_shifu_list(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        uids = await self.db.all_player_uids()
        lines = ["--- 收徒中的前辈 ---"]
        for uid in uids:
            raw = await self.db.get_player(uid)
            if raw:
                p = PlayerDoc(**raw)
                if p.ext.get("recruit"):
                    lines.append(f"· {p.name}（第 {max(0, p.realm_index) + 1} 境）")
        yield event.plain_result("\n".join(lines) if len(lines) > 1 else "目前无人开启收徒。")

    # ---- 道侣 ----

    async def _marry_apply(self, event: AstrMessageEvent, target_uid: str):
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if target_uid == doc.uid:
            yield event.plain_result("精神分裂?")
            return
        if doc.ext.get("daolv"):
            yield event.plain_result("你已有道侣。")
            return
        raw = await self.db.get_player(target_uid)
        if not raw:
            yield event.plain_result("目标尚未踏入修行。")
            return
        target = PlayerDoc(**raw)
        if target.ext.get("daolv"):
            yield event.plain_result(f"{target.name} 已有道侣。")
            return
        inv = await self.db.get_inventory(doc.uid)
        if int(inv.get("定情信物", 0)) < 1:
            yield event.plain_result("你没有【定情信物】。")
            return
        self._pending_marriage = {"from": doc.uid, "to": target_uid, "ts": time.time()}
        yield event.plain_result(
            f"{doc.name} 向 {target.name} 送上定情信物，愿结为道侣！\n"
            f"{target.name} 请在 60 秒内回复「我愿意」或「我拒绝」。"
        )

    @filter.command(CMD_MARRY, "结为道侣")
    async def handle_marry(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        target_uid = self._at_target(event)
        if not target_uid:
            yield event.plain_result("格式：结为道侣 @道友")
            return
        async for r in self._marry_apply(event, target_uid):
            yield r

    @filter.command(CMD_MARRY_YES, "答应求婚")
    async def handle_marry_yes(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        pending = getattr(self, "_pending_marriage", None)
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if not pending or pending.get("to") != doc.uid or time.time() - pending.get("ts", 0) > 60:
            self._pending_marriage = None
            return
        raw = await self.db.get_player(pending["from"])
        if not raw:
            self._pending_marriage = None
            return
        lover = PlayerDoc(**raw)
        dl = lover.model_copy(deep=True)
        dd = doc.model_copy(deep=True)
        dl.ext["daolv"] = doc.uid
        dd.ext["daolv"] = lover.uid
        self._pending_marriage = None
        async with self.db.transaction():
            await self.db.save_player(dl.model_dump())
            await self.db.save_player(dd.model_dump())
            await self.db.remove_item(lover.uid, "定情信物", 1)
        yield event.plain_result(f"{doc.name} 应允了！二人结为道侣，共赴仙途。")

    @filter.command(CMD_MARRY_NO, "拒绝求婚")
    async def handle_marry_no(self, event: AstrMessageEvent):
        pending = getattr(self, "_pending_marriage", None)
        if not pending or pending.get("to") != event.get_sender_id():
            return
        self._pending_marriage = None
        yield event.plain_result("这段姻缘被婉拒了。")

    @filter.command(CMD_DIVORCE, "断绝姻缘")
    async def handle_divorce(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        lover_uid = doc.ext.get("daolv")
        if not lover_uid:
            yield event.plain_result("你并无道侣。")
            return
        d = doc.model_copy(deep=True)
        d.ext["daolv"] = None
        await self.db.save_player(d.model_dump())
        raw = await self.db.get_player(lover_uid)
        if raw:
            other = PlayerDoc(**raw)
            do = other.model_copy(deep=True)
            do.ext["daolv"] = None
            await self.db.save_player(do.model_dump())
            yield event.plain_result(f"与 {other.name} 的姻缘就此斩断。")
        else:
            yield event.plain_result("姻缘已断。")

    @filter.command(CMD_QINMI, "查询亲密度")
    async def handle_qinmi(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        qm = dict(doc.ext.get("qinmidu") or {})
        if not qm:
            yield event.plain_result("暂无亲密度记录（道侣同修将提升亲密度）。")
            return
        lines = ["--- 亲密度 ---"]
        for uid, n in sorted(qm.items(), key=lambda kv: -kv[1]):
            raw = await self.db.get_player(uid)
            name = PlayerDoc(**raw).name if raw else uid[:8]
            lines.append(f"· {name}：{n}")
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
    # ---- 管理（对齐原版 AdminSuper 精选） ----

    async def _target_doc(self, event: AstrMessageEvent) -> tuple[PlayerDoc | None, str | None]:
        target_uid = self._at_target(event)
        if not target_uid:
            return None, "格式：指令 @玩家"
        raw = await self.db.get_player(target_uid)
        if not raw:
            return None, "目标尚未踏入修行。"
        return PlayerDoc(**raw), None

    @filter.command(CMD_GIVE_STONES, "补发灵石")
    async def handle_give_stones(self, event: AstrMessageEvent, amount: int = 0):
        if not self._allowed(event):
            return
        if not event.is_admin:
            yield event.plain_result("此权柄唯管理员可执。")
            return
        target, terr = await self._target_doc(event)
        if terr:
            yield event.plain_result(terr)
            return
        amount = int(amount or 0)
        if amount <= 0:
            yield event.plain_result("格式：#补发灵石 @玩家 数量")
            return
        dt = target.model_copy(deep=True)
        dt.stones += amount
        await self.db.save_player(dt.model_dump())
        yield event.plain_result(f"已为 {target.name} 补发灵石 ×{amount}。")

    @filter.command(CMD_VIEW_PLAYER, "查看玩家档案")
    async def handle_view_player(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        if not event.is_admin:
            yield event.plain_result("此权柄唯管理员可执。")
            return
        target, terr = await self._target_doc(event)
        if terr:
            yield event.plain_result(terr)
            return
        st = self._stats(target)
        hp_cur, hp_max = self._hp_pair(target)
        yield event.plain_result(
            f"【{target.name}】uid {target.uid[:12]}…\n"
            f"境界：第 {max(0, target.realm_index) + 1} 境｜修为 {target.exp}｜灵石 {target.stones}\n"
            f"攻 {st.atk} 防 {st.defense} 血 {hp_cur}/{hp_max}｜职业 {target.ext.get('occupation') or '无'}\n"
            f"封禁：{'是' if target.ext.get('banned') else '否'}｜每日任务：{target.ext.get('date', '未接')}"
        )

    @filter.command(CMD_RESET_TASK, "重置每日任务")
    async def handle_reset_task(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        if not event.is_admin:
            yield event.plain_result("此权柄唯管理员可执。")
            return
        target, terr = await self._target_doc(event)
        if terr:
            yield event.plain_result(terr)
            return
        dt = target.model_copy(deep=True)
        dt.ext["date"] = ""
        dt.ext["renwu"] = 0
        await self.db.save_player(dt.model_dump())
        # 任务表也重置
        rec = await self.db.get_daily_task(target.uid)
        if rec:
            rec2 = dict(rec)
            rec2["date"] = ""
            rec2["renwu"] = 0
            await self.db.upsert_daily_task(rec2)
        yield event.plain_result(f"已重置 {target.name} 的每日任务（可重新 #获取每日任务）。")

    @filter.command(CMD_BAN, "封禁修仙")
    async def handle_ban(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        if not event.is_admin:
            yield event.plain_result("此权柄唯管理员可执。")
            return
        target, terr = await self._target_doc(event)
        if terr:
            yield event.plain_result(terr)
            return
        dt = target.model_copy(deep=True)
        dt.ext["banned"] = True
        await self.db.save_player(dt.model_dump())
        yield event.plain_result(f"{target.name} 已被打入天牢。")

    @filter.command(CMD_UNBAN, "解封修仙")
    async def handle_unban(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        if not event.is_admin:
            yield event.plain_result("此权柄唯管理员可执。")
            return
        target, terr = await self._target_doc(event)
        if terr:
            yield event.plain_result(terr)
            return
        dt = target.model_copy(deep=True)
        dt.ext["banned"] = False
        await self.db.save_player(dt.model_dump())
        yield event.plain_result(f"{target.name} 已被赦免，重获自由。")

    # ---- 师徒试炼 / 商店 / 神兵重铸 / 双修 ----

    SHITU_SHOP = {
        "定情信物": 200, "神石": 300, "世界石": 500, "秘境之匙": 100,
        "天命轮回丹": 800, "仙品辟谷丹": 400,
    }

    @filter.command(CMD_SHITU_TRIAL, "开始师徒试炼")
    async def handle_shitu_trial(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if not doc.ext.get("shifu") and not doc.ext.get("tudi"):
            yield event.plain_result("你还没拜师&收徒过！")
            return
        today = quest.date_key()
        if doc.ext.get("trial_date") == today:
            yield event.plain_result("今日师徒试炼已过，明日再来。")
            return
        hp_cur, hp_max = self._hp_pair(doc)
        if hp_cur < hp_max * 0.2:
            yield event.plain_result("你都伤成这样了，先回回血再打吧。")
            return
        st = self._stats(doc)
        name = doc.name or doc.uid[:8] + "…"
        import random as _random
        rng = _random.Random(f"{doc.uid}:trial:{today}")
        boss_hp = st.atk * 100 + 50_000_000
        shadow = battle.Unit("道祖虚影", int(st.atk * 1.1), st.defense, boss_hp, 0.05)
        me = battle.Unit(name, st.atk, st.defense, hp_cur, st.bao)
        won, log, hp_left, _ = battle.spar_full(me, shadow, rng, max_rounds=15)
        d = doc.model_copy(deep=True)
        d.ext["trial_date"] = today
        d.ext["hp"] = hp_left
        if won == 0:
            gain = 200
            d.stones += 500_000
            d.ext["shitu_points"] = int(d.ext.get("shitu_points", 0)) + gain
            await self.db.save_player(d.model_dump())
            yield event.plain_result(
                f"师徒试炼：你力挫道祖虚影！师徒积分 +{gain}，灵石 +500000。"
            )
        else:
            await self.db.save_player(d.model_dump())
            yield event.plain_result("师徒试炼败于道祖虚影之手，尚需磨砺（明日再战）。")

    @filter.command(CMD_SHITU_SUBMIT, "提交师徒任务")
    async def handle_shitu_submit(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if not doc.ext.get("shifu"):
            yield event.plain_result("只能由徒弟提交任务。")
            return
        today = quest.date_key()
        if doc.ext.get("submit_date") == today:
            yield event.plain_result("今日任务已提交，明日再来。")
            return
        d = doc.model_copy(deep=True)
        d.ext["submit_date"] = today
        d.ext["shitu_points"] = int(d.ext.get("shitu_points", 0)) + 50
        await self.db.save_player(d.model_dump())
        yield event.plain_result("师徒任务提交，师徒积分 +50。")

    @filter.command(CMD_SHITU_SHOP, "师徒商店")
    async def handle_shitu_shop(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        pts = int(doc.ext.get("shitu_points", 0))
        lines = [f"--- 师徒商店（我的积分 {pts}）---"]
        for name, cost in self.SHITU_SHOP.items():
            lines.append(f"· {name}：{cost} 积分")
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
    @filter.command(CMD_SHITU_EX, "师徒兑换")
    async def handle_shitu_ex(self, event: AstrMessageEvent, thing_name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        thing = (thing_name or "").strip()
        cost = self.SHITU_SHOP.get(thing)
        if not cost:
            yield event.plain_result(f"师徒商店还没有这样的东西：{thing}。发「{CMD_SHITU_SHOP}」查看。")
            return
        pts = int(doc.ext.get("shitu_points", 0))
        if pts < cost:
            yield event.plain_result(f"积分不足，还需 {cost - pts} 积分兑换{thing}。")
            return
        d = doc.model_copy(deep=True)
        d.ext["shitu_points"] = pts - cost
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.add_items(doc.uid, {thing: 1})
        yield event.plain_result(f"兑换成功！获得[{thing}]，剩余 {pts - cost} 积分。")

    @filter.command(CMD_RECAST, "神兵重铸")
    async def handle_recast(self, event: AstrMessageEvent, old_name: str = "", new_name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        old_name = (old_name or "").strip().rstrip("*")
        new_name = (new_name or "").strip()
        if not old_name or not new_name:
            yield event.plain_result(f"格式：{CMD_RECAST} 原装备名 新名字")
            return
        if len(new_name) > 12:
            yield event.plain_result("字符超出最大限制，请重新赋名。")
            return
        if new_name in self.item_index or new_name == old_name:
            yield event.plain_result("这个世间已经拥有这把武器了。")
            return
        inv = await self.db.get_inventory(doc.uid)
        if int(inv.get(old_name, 0)) < 1:
            yield event.plain_result(f"你没有这件装备（{old_name}）。")
            return
        if int(inv.get("神兵重铸卡", 0)) < 1:
            yield event.plain_result("你没有神兵重铸卡。")
            return
        d = doc.model_copy(deep=True)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.remove_item(doc.uid, "神兵重铸卡", 1)
            await self.db.remove_item(doc.uid, old_name, 1)
            await self.db.add_items(doc.uid, {new_name: 1})
            # 穿戴槽同步
            equip = dict(d.ext.get("equipment") or {})
            changed = False
            for slot, equipped in equip.items():
                if equipped == old_name:
                    equip[slot] = new_name
                    changed = True
            if changed:
                d.ext["equipment"] = equip
                await self.db.save_player(d.model_dump())
        yield event.plain_result("神光转瞬即逝，神兵已重塑真名，重回您的纳戒当中。")

    @filter.command(CMD_SHUANGXIU, "双修")
    async def handle_shuangxiu(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        lover_uid = doc.ext.get("daolv")
        if not lover_uid:
            yield event.plain_result("双修需道侣相伴（结为道侣 后再来）。")
            return
        if doc.ext.get("shuangxiu_off"):
            yield event.plain_result("你已闭关谢客（#允许双修 可重新开启）。")
            return
        now = time.time()
        if now - float(doc.ext.get("shuangxiu_ts") or 0) < 3600:
            left = int(3600 - (now - float(doc.ext["shuangxiu_ts"])))
            yield event.plain_result(f"双修初成需温养，{left // 60} 分钟后再来。")
            return
        raw = await self.db.get_player(lover_uid)
        if not raw:
            yield event.plain_result("道侣已失联。")
            return
        lover = PlayerDoc(**raw)
        gain = 2000 * (max(0, doc.realm_index) + 1)
        dl = lover.model_copy(deep=True)
        dd = doc.model_copy(deep=True)
        dd.exp += gain
        dl.exp += gain
        # 亲密度双向 +5
        qm_d = dict(dd.ext.get("qinmidu") or {})
        qm_d[lover.uid] = int(qm_d.get(lover.uid, 0)) + 5
        dd.ext["qinmidu"] = qm_d
        qm_l = dict(dl.ext.get("qinmidu") or {})
        qm_l[doc.uid] = int(qm_l.get(doc.uid, 0)) + 5
        dl.ext["qinmidu"] = qm_l
        dd.ext["shuangxiu_ts"] = now
        dl.ext["shuangxiu_ts"] = now
        fusion_note = ""
        # 双修灵根融合彩蛋（对齐原版 applyFusion：体质对+概率，双方替换为融合体质）
        FUSION_RULES = [
            ({"大成·荒古圣体", "先天道胎"}, 0.05, "先天圣体道胎",
             "【圣体道胎交融】荒古圣体与先天道胎相遇，引动万古异象！「先天圣体道胎」诞生！"),
            ({"命运神道体", "极道天魔"}, 0.01, "终焉神魔体",
             "【命运与天魔交融】时空长河倒卷，混沌重开！「终焉神魔体」诞生！"),
            ({"太阳之体", "太阴之体"}, 0.01, "混沌体",
             "【太阴太阳交融】阴阳二气交织，混沌初开！「混沌体」诞生！"),
        ]
        root_a = (dd.ext.get("linggen") or {}).get("name")
        root_b = (dl.ext.get("linggen") or {}).get("name")
        pair = {root_a, root_b}
        if len(pair) == 2:
            for names, chance, fused_name, flavor in FUSION_RULES:
                if pair == names and _random.random() < chance:
                    fused = next((e for e in self.linggen_table if e.get("name") == fused_name), None)
                    if fused:
                        snap = linggen.snapshot(fused)
                        dd.ext["linggen"] = snap
                        dl.ext["linggen"] = dict(snap)
                        fusion_note = f"\n{flavor}\n双方灵根蜕变为「{fused_name}」（修炼效率加成 +{float(fused.get('eff', 0)):g}）！"
                    break
        async with self.db.transaction():
            await self.db.save_player(dd.model_dump())
            await self.db.save_player(dl.model_dump())
        yield event.plain_result(
            f"与 {lover.name} 双修圆满：双方修为 +{gain}，亲密度 +5（当前 {qm_d[lover.uid]}）。"
            + fusion_note
        )

    @filter.command("#允许双修", "允许双修")
    async def handle_shuangxiu_on(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        d = doc.model_copy(deep=True)
        d.ext["shuangxiu_off"] = False
        await self.db.save_player(d.model_dump())
        yield event.plain_result("已重新开门迎客。")

    @filter.command("#拒绝双修", "拒绝双修")
    async def handle_shuangxiu_off(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        d = doc.model_copy(deep=True)
        d.ext["shuangxiu_off"] = True
        await self.db.save_player(d.model_dump())
        yield event.plain_result("已闭关谢客，双修请求将被婉拒。")

    # ---- 天机阁 / 天机符楼（对齐原版 tianjishop.js） ----

    async def _tianji_view(self, event: AstrMessageEvent, table: str, title: str, cmd: str):
        goods = [e for e in (self.content.table(table) or []) if isinstance(e, dict) and e.get("name")]
        if not goods:
            yield event.plain_result("天机阁空空如也。")
            return
        groups = [{"group": f"{g['name']}（{g.get('daibi')}×{g.get('出售价')}）",
                   "list": [{"title": f"{g.get('class')}｜{g.get('稀有度', '')}",
                             "desc": f"{g.get('desc', '')}｜兑换：{cmd} {g['name']}"}]}
                  for g in goods[:30]]
        data = {"title": title, "groups": groups}
        if self.render_on:
            png = await render.render_panel("catalog", data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        lines = [f"【{title}】"]
        for g in goods[:30]:
            lines.append(f"· {g['name']}（{g.get('daibi')}×{g.get('出售价')}）")
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
    @filter.command("#天机阁", "天机阁商店")
    async def handle_tianji_shop(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        async for r in self._tianji_view(event, "item/商店/天机阁", "诸天修仙 · 天机阁", "#天机阁兑换"):
            yield r

    async def _tianji_buy(self, event: AstrMessageEvent, table: str, thing_name: str, qty: int,
                          invite_need: bool):
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if invite_need:
            inv0 = await self.db.get_inventory(doc.uid)
            if int(inv0.get("天机符楼邀请函", 0)) < 1:
                yield event.plain_result(
                    "【天机符楼·禁制】\n「非持函者不得窥视楼内天机！」\n获取方式：天机阁兑换 天机符楼邀请函。")
                return
        goods = [e for e in (self.content.table(table) or []) if isinstance(e, dict) and e.get("name")]
        g = next((x for x in goods if x.get("name") == thing_name), None)
        if not g:
            yield event.plain_result(f"此处并无「{thing_name}」。")
            return
        currency = str(g.get("daibi", "灵石"))
        unit = int(g.get("出售价", 0) or 0)
        total = unit * qty
        inv = await self.db.get_inventory(doc.uid)
        if int(inv.get(currency, 0)) < total:
            yield event.plain_result(f"{currency}不足：需 {total}，当前 {int(inv.get(currency, 0))}。")
            return
        d = doc.model_copy(deep=True)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.remove_item(doc.uid, currency, total)
            await self.db.add_items(doc.uid, {thing_name: qty})
        yield event.plain_result(f"兑换成功！获得[{thing_name}]×{qty}（{currency}×{total}）。")

    @filter.command("#天机阁兑换", "天机阁兑换")
    async def handle_tianji_buy(self, event: AstrMessageEvent, thing_name: str = "", qty: int = 1):
        if not self._allowed(event):
            return
        thing = (thing_name or "").strip()
        if not thing:
            yield event.plain_result("格式：#天机阁兑换 物品 数量")
            return
        async for r in self._tianji_buy(event, "item/商店/天机阁", thing, max(1, int(qty or 1)), False):
            yield r

    @filter.command("#天机符楼", "天机符楼商店")
    async def handle_tianji_fu(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        inv = await self.db.get_inventory(doc.uid)
        if int(inv.get("天机符楼邀请函", 0)) < 1:
            yield event.plain_result(
                "【天机符楼·禁制】\n「非持函者不得窥视楼内天机！」\n获取方式：天机阁兑换 天机符楼邀请函。")
            return
        async for r in self._tianji_view(event, "item/商店/天机阁符楼", "诸天修仙 · 天机符楼", "#天机符楼兑换"):
            yield r

    @filter.command("#天机符楼兑换", "天机符楼兑换")
    async def handle_tianji_fu_buy(self, event: AstrMessageEvent, thing_name: str = "", qty: int = 1):
        if not self._allowed(event):
            return
        thing = (thing_name or "").strip()
        if not thing:
            yield event.plain_result("格式：#天机符楼兑换 物品 数量")
            return
        async for r in self._tianji_buy(event, "item/商店/天机阁符楼", thing, max(1, int(qty or 1)), True):
            yield r

    # ---- 诸天镜主线（对齐原版 zhutiantouying/ZhutianMirror） ----

    def _zt_save(self, doc: PlayerDoc, zt: dict) -> PlayerDoc:
        d = doc.model_copy(deep=True)
        d.ext["zhutian"] = zt
        return d

    @filter.command(CMD_XT_USE, "使用诸天镜（绑定）")
    async def handle_xt_bind(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        ok, msg, zt = zhutian.bind(doc)
        if ok:
            if not await self.db.remove_item(doc.uid, "诸天镜", 1):
                yield event.plain_result("纳戒中没有「诸天镜」（天机阁 2 仙兽玉可兑换）。")
                return
            await self.db.save_player(self._zt_save(doc, zt).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_MIRROR, "诸天镜面板")
    async def handle_mirror(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        zt = zhutian.system_of(doc)
        zhutian.daily_reset(zt)
        if not zt.get("bound"):
            yield event.plain_result(
                "尚未绑定诸天镜。天机阁可兑换「诸天镜」，然后发送 #使用诸天镜 绑定。"
            )
            return
        info = zhutian.MIRROR_TIERS[int(zt["tier"])]
        nxt, req = zhutian.missing_refine(zt)
        mats = zt["materials"]
        lines = [
            f"--- 诸天镜 · {info['name']} ---",
            f"镜能：{zt['energy']} / {info['energy']}（每日重置）",
            f"材料：镜尘 {mats.get('镜尘', 0)}｜世界残响 {mats.get('世界残响', 0)}"
            f"｜位面晶核 {mats.get('位面晶核', 0)}｜时空锚 {mats.get('时空锚', 0)}｜诸天镜心 {mats.get('诸天镜心', 0)}",
            f"世界印记（{len(zt['imprints'])}）：{'、'.join(zt['imprints']) or '（无）'}",
            f"化身：{'、'.join(zt['avatars']) or '（尚未收录）'}｜当前：{zt.get('current') or '本源'}",
            f"库洛牌 {len(zt.get('clow_cards') or [])} 张｜骑士卡 {len(zt.get('rider_cards') or [])} 张｜希望碎片 {zt.get('hopes', 0)}",
        ]
        if req:
            lines.append(f"下一阶（{nxt}）淬炼需：{'、'.join(f'{k}×{v}' for k, v in req.items())}")
        else:
            lines.append("已臻七阶·彼岸。")
        lines.append("投影：#投影诸天 世界名（#诸天世界 查列表）｜探索：#探索友枝町 地点 等")
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
    @filter.command(CMD_MIRROR_REFINE, "淬炼诸天镜")
    async def handle_mirror_refine(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        ok, msg, zt = zhutian.refine(doc)
        if ok:
            await self.db.save_player(self._zt_save(doc, zt).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_MIRROR_WORLDS, "诸天世界列表")
    async def handle_mirror_worlds(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        zt = zhutian.system_of(doc)
        tier = int(zt.get("tier") or 0) if zt.get("bound") else 0
        lines = [f"--- 诸天世界（镜阶 {tier or '未绑定'}）---"]
        for w, t in zhutian.WORLD_MIN_TIER.items():
            mark = "✅可投影" if tier >= t else f"需 {t} 阶"
            lines.append(f"· {w}（{mark}）")
        lines.append("投影：#投影诸天 世界名（修为 1 亿 + 血气 1 亿 + 镜能 1）")
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
    @filter.command(CMD_MIRROR_PROJ, "投影诸天")
    async def handle_mirror_proj(self, event: AstrMessageEvent, world: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if doc.ext.get("projection"):
            yield event.plain_result("已有进行中的投影（#1-#3 抉择 或 #退出投影）。")
            return
        ok, msg, zt, proj = zhutian.begin_projection(doc, world.strip(), time.time())
        if not ok:
            yield event.plain_result(msg)
            return
        d = self._zt_save(doc, zt)
        d.ext["projection"] = proj
        await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_MIRROR_CHOICE, "投影抉择")
    async def handle_mirror_choice(self, event: AstrMessageEvent, choice: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        proj = doc.ext.get("projection")
        if not proj:
            yield event.plain_result("当前没有进行中的投影。")
            return
        try:
            n = int(choice)
        except (TypeError, ValueError):
            n = 0
        if n < 1 or n > int(proj.get("max_choice", 3)):
            yield event.plain_result(f"请输入 1-{proj.get('max_choice', 3)} 作出抉择。")
            return
        import random as _random
        rng = _random.Random(f"{doc.uid}:proj:{time.time()}")
        tail, zt = zhutian.resolve_projection(doc, proj, n, rng)
        d = self._zt_save(doc, zt)
        d.ext.pop("projection", None)
        await self.db.save_player(d.model_dump())
        yield event.plain_result(tail)

    @filter.command("#1", "投影抉择1")
    async def handle_choice1(self, event: AstrMessageEvent):
        async for r in self.handle_mirror_choice(event, "1"):
            yield r

    @filter.command("#2", "投影抉择2")
    async def handle_choice2(self, event: AstrMessageEvent):
        async for r in self.handle_mirror_choice(event, "2"):
            yield r

    @filter.command("#3", "投影抉择3")
    async def handle_choice3(self, event: AstrMessageEvent):
        async for r in self.handle_mirror_choice(event, "3"):
            yield r

    @filter.command("#4", "投影抉择4")
    async def handle_choice4(self, event: AstrMessageEvent):
        async for r in self.handle_mirror_choice(event, "4"):
            yield r

    @filter.command(CMD_MIRROR_EXIT, "退出投影")
    async def handle_mirror_exit(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if not doc.ext.get("projection"):
            yield event.plain_result("当前没有进行中的投影。")
            return
        d = doc.model_copy(deep=True)
        d.ext.pop("projection", None)
        await self.db.save_player(d.model_dump())
        yield event.plain_result("神魂抽离镜光，投影中止（镜能不退）。")

    @filter.command("#探索友枝町", "探索魔卡世界")
    async def handle_xt_tomoeda(self, event: AstrMessageEvent, place: str = ""):
        async for r in self._xt_explore(event, "魔卡少女樱", place):
            yield r

    @filter.command("#探索见泷原", "探索魔圆世界")
    async def handle_xt_mitakihara(self, event: AstrMessageEvent, place: str = ""):
        async for r in self._xt_explore(event, "魔法少女小圆", place):
            yield r

    @filter.command("#探索骑士世界", "探索帝骑世界")
    async def handle_xt_decade(self, event: AstrMessageEvent, place: str = ""):
        async for r in self._xt_explore(event, "假面骑士帝骑", place):
            yield r

    async def _xt_explore(self, event: AstrMessageEvent, world: str, place: str):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if not place:
            spots = zhutian.LOCATIONS.get(world, {})
            cmd_name = {"魔卡少女樱": "#探索友枝町", "魔法少女小圆": "#探索见泷原",
                        "假面骑士帝骑": "#探索骑士世界"}[world]
            yield event.plain_result(f"格式：{cmd_name} 地点\n地点：{'、'.join(spots)}")
            return
        import random as _random
        rng = _random.Random(f"{doc.uid}:explore:{time.time()}")
        ok, msg, zt = zhutian.explore(doc, world, place.strip(), rng)
        if ok:
            # B2 联动：友枝町探索积累魔法熟练度；骑士世界积累融合度/探索度
            if world == "魔卡少女樱":
                s = world_deep.sakura_of(zt)
                s["prof"] = int(s["prof"]) + 2
                zt["sakura"] = s
            elif world == "假面骑士帝骑":
                dd = world_deep.decade_of(zt)
                dd["fusion"] = min(world_deep.FUSION_MAX, int(dd["fusion"]) + 8)
                dd["explore"] = min(100, int(dd["explore"]) + 8)
                zt["decade"] = dd
            await self.db.save_player(self._zt_save(doc, zt).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_MIRROR_AVATAR, "诸天化身谱")
    async def handle_mirror_avatar(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        zt = zhutian.system_of(doc)
        if not zt.get("bound"):
            yield event.plain_result("尚未绑定诸天镜。")
            return
        lines = ["--- 诸天化身谱 ---"]
        av: dict = zt.get("avatars") or {}
        if not av:
            lines.append("（尚未收录化身）投影世界并在抉择中行「仁」之事，有缘者自会现身。")
        for name, info in av.items():
            root = info.get("root") or {}
            cur = "（当前装载）" if zt.get("current") == name else ""
            lines.append(
                f"· {name}{cur}｜eff +{root.get('eff', 0):g}｜三维 +{root.get('atk', 0):.0%}"
            )
        lines.append(f"当前灵根：{zt.get('current') or '本源'}｜切换：#装载化身 化身名 / #装载化身 本源（1 镜能 + 15 分钟冷却）")
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
    @filter.command(CMD_MIRROR_LOAD, "装载化身")
    async def handle_mirror_load(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        ok, msg, zt, buff = zhutian.load_avatar(doc, name, time.time())
        if ok:
            d = self._zt_save(doc, zt)
            if buff:
                d.ext["avatar_buff"] = buff
            else:
                d.ext.pop("avatar_buff", None)
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    # ---- 大宇宙（小世界升格终局玩法，对齐原版 Garden/GrandUniverse） ----

    @filter.command(CMD_UNI, "大宇宙面板")
    async def handle_uni(self, event: AstrMessageEvent):
        async for r in self._uni_view(event):
            yield r

    @filter.command("#我的大宇宙", "大宇宙面板（别名）")
    async def handle_uni_alias(self, event: AstrMessageEvent):
        async for r in self._uni_view(event):
            yield r

    async def _uni_view(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        u = universe.system_of(doc)
        if not u:
            check = universe.can_ascend(doc)
            if check.get("ok"):
                yield event.plain_result(
                    "升格条件已全部满足！发送「#升格大宇宙」即可开辟大宇宙。"
                )
                return
            reason = check.get("reason", "")
            cur = check.get("current", 0)
            req = check.get("required", 0)
            if reason == "world":
                tip = "尚未开辟小世界（#开辟小世界）。"
            elif reason == "world-level":
                tip = f"小世界演化 {cur}/5 级（#演化小世界）。"
            elif reason == "authority":
                tip = f"境界不足：需金仙 {req} 境（当前 {cur} 境）。"
            elif reason == "potential":
                tip = f"仙道潜力不足：{cur:g}/{req}（凝聚精血类丹药提升）。"
            else:
                tip = ""
            yield event.plain_result(
                "尚未升格大宇宙。升格条件：\n· 小世界演化圆满（5 级）\n· 境界 ≥ 金仙\n· 仙道潜力 ≥ 151\n" + tip
            )
            return
        stage = universe.LAW_STAGES[int(u.get("law", 0))]
        lines = [
            f"--- 大宇宙 · {u.get('name')} ---",
            f"法则：{stage['name']}（承载上限 {stage['capacity']}）｜完善 {u.get('law_refined', 0)} 次",
            f"宇宙灵韵：{u.get('aura', 0)}｜对外开放：{'是' if u.get('open') else '否'}",
            f"秘境（{len(u.get('dungeons') or [])}/{universe.MAX_DUNGEONS}）："
            + ("、".join(d["name"] for d in u.get("dungeons", [])) or "（无）"),
        ]
        nxt = universe.LAW_STAGES[int(u.get("law", 0)) + 1] if int(u.get("law", 0)) + 1 < len(universe.LAW_STAGES) else None
        if nxt:
            lines.append(f"下一阶【{nxt['name']}】需：潜力 {nxt['potential']}｜修为血气各 {nxt['cultivation']:,}｜灵韵 {nxt['aura']}")
        lines.append("炼化：#炼化宇宙灵韵 物品*数量｜铸造：#铸造宇宙秘境 名*简介*守关者｜挑战：#进入宇宙秘境 名")
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
    @filter.command(CMD_UNI_ASCEND, "升格大宇宙")
    async def handle_uni_ascend(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        ok, msg, u = universe.ascend(doc, time.time())
        if ok:
            d = doc.model_copy(deep=True)
            d.ext["universe"] = u
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_UNI_LAW, "完善宇宙法则")
    async def handle_uni_law(self, event: AstrMessageEvent, grade: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        u = universe.system_of(doc)
        if not u:
            yield event.plain_result("尚未升格大宇宙（#升格大宇宙）。")
            return
        ok, msg, u, consume = universe.refine_law(doc, u)
        if not ok:
            yield event.plain_result(msg)
            return
        d = doc.model_copy(deep=True)
        d.ext["universe"] = u
        d.exp = max(0, d.exp - consume["exp"])
        d.ext["xueqi"] = max(0.0, float(d.ext.get("xueqi", 0) or 0) - consume["xueqi"])
        d.ext["potential"] = float(d.ext.get("potential", 0) or 0) - consume["potential"]
        await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_UNI_AURA, "炼化宇宙灵韵")
    async def handle_uni_aura(self, event: AstrMessageEvent, *, args: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        u = universe.system_of(doc)
        if not u:
            yield event.plain_result("尚未升格大宇宙（#升格大宇宙）。")
            return
        # 格式：物品名*数量 或 物品名 数量
        raw = (args or "").strip().replace("＊", "*")
        if "*" in raw:
            name, _, qty_s = raw.partition("*")
        else:
            parts = raw.rsplit(" ", 1)
            name, qty_s = (parts + ["1"])[:2] if parts[0] else ("", "1")
        try:
            qty = max(1, min(9999, int(qty_s.strip() or 1)))
        except ValueError:
            qty = 1
        name = name.strip()
        if not name:
            yield event.plain_result("格式：#炼化宇宙灵韵 物品名*数量")
            return
        item = self.item_index.get(name)
        if not item or item.get("class") not in universe.AURA_CATEGORIES:
            yield event.plain_result(f"「{name}」不可炼化（类别限：{'、'.join(sorted(universe.AURA_CATEGORIES))}）。")
            return
        have = dict(await self.db.get_inventory(doc.uid)).get(name, 0)
        if have < qty:
            yield event.plain_result(f"纳戒中「{name}」不足：需 {qty}，当前 {have}。")
            return
        gain = universe.refine_aura(item, qty)
        d = doc.model_copy(deep=True)
        d.ext["universe"] = {**u, "aura": int(u.get("aura", 0)) + gain}
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if not await self.db.remove_item(doc.uid, name, qty):
                raise RuntimeError("INSUFFICIENT")
        yield event.plain_result(f"炼化 {name} ×{qty} → 宇宙灵韵 +{gain}（当前 {d.ext['universe']['aura']}）。")

    @filter.command(CMD_UNI_FORGE, "铸造宇宙秘境")
    async def handle_uni_forge(self, event: AstrMessageEvent, *, args: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        u = universe.system_of(doc)
        if not u:
            yield event.plain_result("尚未升格大宇宙（#升格大宇宙）。")
            return
        parts = (args or "").split("*")
        if len(parts) != 3 or not all(p.strip() for p in parts):
            yield event.plain_result("格式：#铸造宇宙秘境 秘境名*简介*守关者名")
            return
        ok, msg, u = universe.forge_dungeon(u, parts[0].strip(), parts[1].strip(), parts[2].strip())
        if ok:
            d = doc.model_copy(deep=True)
            d.ext["universe"] = u
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_UNI_LIST, "宇宙秘境列表")
    async def handle_uni_list(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        u = universe.system_of(doc)
        ds = u.get("dungeons") or []
        if not ds:
            yield event.plain_result("大宇宙中尚无秘境（#铸造宇宙秘境 名*简介*守关者）。")
            return
        lines = [f"--- 宇宙秘境（{len(ds)}/{universe.MAX_DUNGEONS}）---"]
        for d in ds:
            lines.append(f"· {d['name']}｜守关者【{d['enemy']}】｜通关 {d.get('cleared', 0)} 次")
            if d.get("intro"):
                lines.append(f"  {d['intro']}")
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
    @filter.command(CMD_UNI_ENTER, "进入宇宙秘境")
    async def handle_uni_enter(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        u = universe.system_of(doc)
        if not u:
            yield event.plain_result("尚未升格大宇宙（#升格大宇宙）。")
            return
        st = self._stats(doc)
        me = {"atk": st.atk, "defense": st.defense, "hp": st.hp, "bao": st.bao}
        import random as _random
        rng = _random.Random(f"{doc.uid}:ud:{time.time()}")
        ok, msg, u, result = universe.enter_dungeon(doc, u, (name or "").strip(), time.time(), me, rng)
        if ok:
            d = doc.model_copy(deep=True)
            d.ext["universe"] = u
            if result:
                d.ext["udungeon_ts"] = time.time()
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_UNI_DERIVE, "演绎宇宙秘境")
    async def handle_uni_derive(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        u = universe.system_of(doc)
        if not u:
            yield event.plain_result("尚未升格大宇宙（#升格大宇宙）。")
            return
        if not name:
            yield event.plain_result("格式：#演绎宇宙秘境 秘境名")
            return
        import random as _random
        rng = _random.Random(f"{doc.uid}:udv:{time.time()}")
        ok, msg, u, consume = universe.derive_dungeon(u, name.strip(), rng)
        if ok:
            d = doc.model_copy(deep=True)
            d.ext["universe"] = u
            d.exp = max(0, d.exp - consume["exp"])
            d.ext["xueqi"] = max(0.0, float(d.ext.get("xueqi", 0) or 0) - consume["xueqi"])
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    # ---- A 档：镇妖塔 / 仙宠寻宝 / 洗劫 / 道侣赠礼 ----

    def _tower_view(self, doc: PlayerDoc, stats: equipment.Stats, rng, once: bool):
        """单次或连打镇妖塔。返回 (msg, floors, total_stones, final_doc)。"""
        total_stones = 0
        floors = 0
        d = doc
        for _ in range(1 if once else 60):
            st = {"atk": stats.atk, "defense": stats.defense, "hp": stats.hp, "bao": stats.bao}
            ok, msg, ext2, consume = adventure.tower_fight(d, st, rng)
            if not ok:
                return msg, 0, 0, d
            total_stones += consume.get("stones", 0)
            d = d.model_copy(deep=True)
            d.ext.update(ext2)
            if consume.get("stones", 0) < 0:  # 战败
                return msg, floors, total_stones, d
            floors += 5
            if once:
                return msg, floors, total_stones, d
        return f"一键挑战结束：连过 {floors} 层！灵石 +{total_stones:,}", floors, total_stones, d

    @filter.command(CMD_TOWER, "挑战镇妖塔")
    async def handle_tower(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        import random as _random
        rng = _random.Random(f"{doc.uid}:tower:{time.time()}")
        msg, floors, stones, d = self._tower_view(doc, self._stats(doc), rng, once=True)
        if stones:
            d.stones = max(0, d.stones + stones)
            d.ext["tower_ts"] = time.time()
            await self.db.save_player(d.model_dump())
        async for _r in self._smart(event, msg, "镇妖塔"):
            yield _r

    @filter.command(CMD_TOWER_ALL, "一键挑战镇妖塔")
    async def handle_tower_all(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        import random as _random
        rng = _random.Random(f"{doc.uid}:towerall:{time.time()}")
        msg, floors, stones, d = self._tower_view(doc, self._stats(doc), rng, once=False)
        d.stones = max(0, d.stones + stones)
        d.ext["tower_ts"] = time.time()
        await self.db.save_player(d.model_dump())
        async for _r in self._smart(event, msg, "镇妖塔 · 连战"):
            yield _r

    @filter.command(CMD_PET_SEND, "派仙宠寻宝")
    async def handle_pet_send(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        import random as _random
        ok, msg, st = adventure.pet_explore_start(doc, time.time(), _random.Random(f"{doc.uid}:ps:{time.time()}"))
        if ok:
            d = doc.model_copy(deep=True)
            d.ext["pet_explore"] = st
            d.stones -= adventure.PET_EXPLORE_COST
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_PET_COLLECT, "结束仙宠寻宝")
    async def handle_pet_collect(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        import random as _random
        pool = adventure.build_pet_pool(self.item_index)
        ok, msg, _, gains = adventure.pet_explore_collect(doc, pool, time.time(),
                                                          _random.Random(f"{doc.uid}:pc:{time.time()}"))
        if ok:
            d = doc.model_copy(deep=True)
            d.ext.pop("pet_explore", None)
            async with self.db.transaction():
                await self.db.save_player(d.model_dump())
                if gains:
                    await self.db.add_items(doc.uid, gains)
        yield event.plain_result(msg)

    @filter.command(CMD_RAID_LIST, "洗劫列表")
    async def handle_raid_list(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        shops = self.content.table("item/shop列表") or []
        lines = ["--- 洗劫地点（洗劫有风险，魔道 +25×档）---"]
        for s in shops:
            loot = "、".join(x["name"] for x in (s.get("one") or [])[:4])
            lines.append(f"· {s['name']}（{s['Grade']} 档｜强化费 {s['price'] * s['Grade']:,}）｜可掠：{loot}…")
        lines.append("#探查 地点（0.3×价格）｜#洗劫 地点（2h CD，战斗定胜负）")
        async for r in self._smart(event, "\n".join(lines), "洗劫地点"):
            yield r

    @filter.command(CMD_RAID_SPY, "探查洗劫点")
    async def handle_raid_spy(self, event: AstrMessageEvent, place: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        shops = {s["name"]: s for s in (self.content.table("item/shop列表") or [])}
        s = shops.get((place or "").strip())
        if not s:
            yield event.plain_result(f"未找到洗劫地点：{place}（#洗劫列表 查看）。")
            return
        cost = int(s["price"] * 0.3)
        if doc.stones < cost:
            yield event.plain_result(f"打探消息需要 {cost:,} 灵石，家底不足。")
            return
        d = doc.model_copy(deep=True)
        d.stones -= cost
        await self.db.save_player(d.model_dump())
        loot = s.get("one") or []
        preview = "、".join(f"{x['name']}×{x.get('数量', 1)}" for x in loot[:5])
        async for r in self._smart(
            event,
            f"你花 {cost:,} 灵石买通了 {s['name']} 的账房……\n"
            f"传闻库中藏着：{preview} 等。\n守卫实力约 {s['Grade']} 档（血 {adventure.raid_guard(s['Grade'])['hp']:,}）。\n"
            f"#洗劫 {s['name']} 干一票大的！",
            f"探查 · {s['name']}",
        ):
            yield r

    @filter.command(CMD_RAID, "洗劫")
    async def handle_raid(self, event: AstrMessageEvent, place: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if not place:
            yield event.plain_result("格式：#洗劫 地点名（#洗劫列表 查看）。")
            return
        # CD 检查（劫光令可清）
        last = float(doc.ext.get("raid_ts", 0.0))
        now = time.time()
        if now - last < adventure.RAID_CD:
            have = dict(await self.db.get_inventory(doc.uid)).get("劫光令", 0)
            if have > 0:
                d = doc.model_copy(deep=True)
                async with self.db.transaction():
                    await self.db.save_player(d.model_dump())
                    await self.db.remove_item(doc.uid, "劫光令", 1)
                doc = d
                yield event.plain_result("你祭出一枚劫光令，劫光一闪，天道禁制化为虚无（洗劫冷却重置）！")
            else:
                remain = int((adventure.RAID_CD - (now - last)) / 60) + 1
                yield event.plain_result(f"每 120 分钟洗劫一次，CD 中（余 {remain} 分钟）；劫光令可重置。")
                return
        shops = {s["name"]: s for s in (self.content.table("item/shop列表") or [])}
        s = shops.get(place.strip())
        if not s:
            yield event.plain_result(f"未找到洗劫地点：{place}。")
            return
        grade = int(s.get("Grade", 1))
        strengthen = int(s["price"] * grade)
        if doc.stones < strengthen:
            yield event.plain_result(f"洗劫前需花 {strengthen:,} 灵石强化防备，家底不足。")
            return
        st = self._stats(doc)
        import random as _random
        rng = _random.Random(f"{doc.uid}:raid:{time.time()}")
        me = {"atk": st.atk, "defense": st.defense, "hp": st.hp, "bao": st.bao}
        won, log = adventure.raid_fight(me, adventure.raid_guard(grade), rng)
        d = doc.model_copy(deep=True)
        d.stones = max(0, d.stones - strengthen)
        d.ext["raid_ts"] = now
        d.ext["modao"] = float(d.ext.get("modao", 0) or 0) + adventure.RAID_MODAO_PER_GRADE * grade
        if won:
            loot = s.get("one") or []
            picked = rng.sample(loot, k=min(3, len(loot))) if loot else []
            gains: dict[str, int] = {}
            for x in picked:
                gains[str(x["name"])] = int(x.get("数量", 1) or 1)
            stones_gain = int(s["price"] * grade * rng.uniform(0.5, 1.5))
            d.stones += stones_gain
            async with self.db.transaction():
                await self.db.save_player(d.model_dump())
                if gains:
                    await self.db.add_items(doc.uid, gains)
            loot_txt = "，".join(f"{k} ×{v}" for k, v in gains.items()) or "（空手但赢了面子）"
            async for r in self._smart(
                event,
                f"夜色掩护下你潜入 {s['name']}——守卫被你放倒！\n"
                + "\n".join(log[-4:]) + f"\n💰 掠得：{loot_txt}；灵石 +{stones_gain:,}\n"
                f"（强化费 −{strengthen:,}，魔道值 +{adventure.RAID_MODAO_PER_GRADE * grade}）",
                f"洗劫 · {s['name']}",
            ):
                yield r
        else:
            loss = int(s["price"] * grade * 0.3)
            d.stones = max(0, d.stones - loss)
            await self.db.save_player(d.model_dump())
            async for r in self._smart(
                event,
                f"夜袭 {s['name']} 失手——守卫把你打了出来！\n"
                + "\n".join(log[-4:]) + f"\n❌ 灵石 −{loss:,}（疗伤封口费），魔道值 +{adventure.RAID_MODAO_PER_GRADE * grade}",
                f"洗劫失败 · {s['name']}",
            ):
                yield r

    @filter.command(CMD_GIFT, "赠予花篮")
    async def handle_gift(self, event: AstrMessageEvent, *, args: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        lover_uid = self._at_target(event)
        if not lover_uid:
            yield event.plain_result("格式：#赠予花篮 @道侣")
            return
        lover_name = lover_uid[:8] + "…"
        if doc.ext.get("daolv") != lover_uid:
            yield event.plain_result("只可赠予道侣（结为道侣后才能赠花）。")
            return
        have = dict(await self.db.get_inventory(doc.uid)).get("百合花篮", 0)
        if have < 1:
            yield event.plain_result("纳戒中没有「百合花篮」。")
            return
        raw = await self.db.get_player(lover_uid)
        if not raw:
            yield event.plain_result("对方尚未踏入仙途。")
            return
        lover_doc = PlayerDoc(**raw)
        d = doc.model_copy(deep=True)
        d.ext["qinmidu"] = {**(d.ext.get("qinmidu") or {}), lover_uid: int((d.ext.get("qinmidu") or {}).get(lover_uid, 0)) + 10}
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.remove_item(doc.uid, "百合花篮", 1)
            dl = lover_doc.model_copy(deep=True)
            qm = dict(dl.ext.get("qinmidu") or {})
            qm[doc.uid] = int(qm.get(doc.uid, 0)) + 10
            dl.ext["qinmidu"] = qm
            await self.db.save_player(dl.model_dump())
        yield event.plain_result(f"你将一篮百合赠予 {lover_name}，花香满堂——双方亲密度 +10。")

    # ---- B1：本命帝兵炼制 ----

    def _db_sync(self, doc: PlayerDoc, w: dict | None) -> PlayerDoc:
        """帝兵档写回 ext；更名时同步穿戴槽（属性由 _stats 的私有 lookup 提供）。"""
        d = doc.model_copy(deep=True)
        old = (d.ext.get("dibing") or {}).get("name")
        if w:
            d.ext["dibing"] = w
            if old and old != w["name"]:
                eq = d.ext.get("equipment") or {}
                for slot, nm in list(eq.items()):
                    if nm == old:
                        eq[slot] = w["name"]
                d.ext["equipment"] = eq
        return d

    @filter.command(CMD_DB_MY, "我的帝兵")
    async def handle_db_my(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = dibing.system_of(doc)
        if not w:
            yield event.plain_result(
                "尚未炼制本命帝兵。\n格式：#炼制帝兵 仙金名*帝兵名（名称需含剑/鼎/枪/钟/塔/镜/印/刀等形态字）\n"
                "可用仙金：仙泪绿金、凰血赤金、龙纹黑金、永恒蓝金、神痕紫金、道劫黄金、羽化青金、混沌石精、大罗银精"
            )
            return
        async for r in self._smart(event, dibing.summary(w), "本命帝兵"):
            yield r

    @filter.command(CMD_DB_FORGE, "炼制帝兵")
    async def handle_db_forge(self, event: AstrMessageEvent, *, args: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        if dibing.system_of(doc):
            yield event.plain_result("你已有本命帝兵（#我的帝兵），器随其主，不可再炼。")
            return
        raw = (args or "").strip().replace("*", " ")
        parts = raw.split(None, 1)
        if len(parts) < 2:
            yield event.plain_result("格式：#炼制帝兵 仙金名*帝兵名（如 仙泪绿金*混沌剑）")
            return
        gold, name = parts[0].strip(), parts[1].strip()
        ok, msg, w = dibing.forge(gold, name)
        if not ok:
            yield event.plain_result(msg)
            return
        have = dict(await self.db.get_inventory(doc.uid)).get(gold, 0)
        if have < 1:
            yield event.plain_result(f"纳戒中没有「{gold}」（#哪里有 {gold} 可查获取渠道）。")
            return
        d = self._db_sync(doc, w)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if not await self.db.remove_item(doc.uid, gold, 1):
                raise RuntimeError("INSUFFICIENT")
        async for r in self._smart(event, msg, "帝兵出世"):
            yield r

    @filter.command(CMD_DB_FUSE, "融合帝兵")
    async def handle_db_fuse(self, event: AstrMessageEvent, gold: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = dibing.system_of(doc)
        if not w:
            yield event.plain_result("尚未炼制本命帝兵（#炼制帝兵）。")
            return
        gold = (gold or "").strip().replace("*", "").strip()
        ok, msg, w2 = dibing.fuse(w, gold)
        if not ok:
            yield event.plain_result(msg)
            return
        have = dict(await self.db.get_inventory(doc.uid)).get(gold, 0)
        if have < 1:
            yield event.plain_result(f"纳戒中没有「{gold}」。")
            return
        d = self._db_sync(doc, w2)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if not await self.db.remove_item(doc.uid, gold, 1):
                raise RuntimeError("INSUFFICIENT")
        yield event.plain_result(msg)

    @filter.command(CMD_DB_TRIB, "雷劫洗礼帝兵")
    async def handle_db_trib(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = dibing.system_of(doc)
        if not w:
            yield event.plain_result("尚未炼制本命帝兵（#炼制帝兵）。")
            return
        s = story_npc.state_of(doc)
        cheat = bool(s.get("trib_pending"))
        need = dibing.TRIBULATION_COST // 2 if cheat else dibing.TRIBULATION_COST
        ok, msg, w2 = dibing.tribulation(
            w, doc.exp, float(doc.ext.get("xueqi", 0) or 0), cost=need
        )
        if not ok:
            yield event.plain_result(msg)
            return
        if cheat:
            story_npc.consume_tribulation(s)
            msg += f"\n【欺天阵纹】阵纹遮蔽天机，雷劫消耗减半（各 {need:,}）。"
        d = self._db_sync(doc, w2)
        d = story_npc.save(d, s)
        d.exp -= need
        d.ext["xueqi"] = max(0.0, float(d.ext.get("xueqi", 0) or 0) - need)
        await self.db.save_player(d.model_dump())
        async for r in self._smart(event, msg, "雷劫洗礼"):
            yield r

    @filter.command(CMD_DB_NURTURE, "蕴养帝兵")
    async def handle_db_nurture(self, event: AstrMessageEvent, *, args: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = dibing.system_of(doc)
        if not w:
            yield event.plain_result("尚未炼制本命帝兵（#炼制帝兵）。")
            return
        times = 1
        raw = (args or "").strip().lstrip("*").strip()
        if raw.isdigit():
            times = int(raw)
        ok, msg, w2, consume = dibing.nurture(w, times, doc.exp, float(doc.ext.get("xueqi", 0) or 0))
        if not ok:
            yield event.plain_result(msg)
            return
        d = self._db_sync(doc, w2)
        d.exp -= consume["exp"]
        d.ext["xueqi"] = max(0.0, float(d.ext.get("xueqi", 0) or 0) - consume["xueqi"])
        await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_DB_RENAME, "为帝兵更名")
    async def handle_db_rename(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = dibing.system_of(doc)
        if not w:
            yield event.plain_result("尚未炼制本命帝兵（#炼制帝兵）。")
            return
        ok, msg, w2 = dibing.rename(w, (name or "").strip())
        if not ok:
            yield event.plain_result(msg)
            return
        d = self._db_sync(doc, w2)
        await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    # ---- B2：诸天世界深度（库洛牌/月之审判/梦之试炼/帝骑/救赎） ----

    def _zt_load(self, doc: PlayerDoc) -> tuple[dict, str | None]:
        zt = zhutian.system_of(doc)
        if not zt.get("bound"):
            return zt, "尚未绑定诸天镜（#使用诸天镜）。"
        return zt, None

    @filter.command(CMD_CLOW_DECK, "库洛牌编组")
    async def handle_clow_deck(self, event: AstrMessageEvent, *, args: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        zt, err2 = self._zt_load(doc)
        if err2:
            yield event.plain_result(err2)
            return
        raw = (args or "").strip()
        if not raw:
            owned = zt.get("clow_cards") or []
            combos = "\n".join(f"· {k}：{'、'.join(v)}" for k, v in world_deep.CARD_COMBOS.items())
            sel = world_deep.sakura_of(zt)
            async for r in self._smart(
                event,
                f"--- 库洛牌组合 ---\n{combos}\n\n"
                f"已封印 {len(owned)} 张：{'、'.join(owned) or '（无）'}\n"
                f"当前卡组：{'、'.join(sel['deck']) or '（未编组）'}｜组合：{sel['combo'] or '无'}\n"
                f"编组：#库洛牌组合 风*翔*影",
                "库洛牌组合",
            ):
                yield r
            return
        cards = [c.strip() for c in raw.replace("、", "*").replace(" ", "*").split("*") if c.strip()]
        s = world_deep.sakura_of(zt)
        ok, msg, s2 = world_deep.set_clow_deck(zt, cards)
        if ok:
            zt["sakura"] = s2
            await self.db.save_player(self._zt_save(doc, zt).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_MOON_TRIAL, "月之审判")
    async def handle_moon_trial(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        zt, err2 = self._zt_load(doc)
        if err2:
            yield event.plain_result(err2)
            return
        import random as _random
        rng = _random.Random(f"{doc.uid}:moon:{time.time()}")
        ok, msg, s = world_deep.moon_trial(zt, doc.realm_index, rng)
        if ok:
            zt["sakura"] = s
            d = self._zt_save(doc, zt)
            if int(s["moon_tries"]) > 0 and not s["moon_pass"]:
                d.exp = int(d.exp * 0.9)  # 失败罚修为 10%
            await self.db.save_player(d.model_dump())
        async for r in self._smart(event, msg, "月之审判"):
            yield r

    @filter.command(CMD_DREAM_TRIAL, "梦之试炼")
    async def handle_dream_trial(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        zt, err2 = self._zt_load(doc)
        if err2:
            yield event.plain_result(err2)
            return
        ok, msg, s = world_deep.dream_trial(zt, doc.realm_index)
        if ok:
            zt["sakura"] = s
            await self.db.save_player(self._zt_save(doc, zt).model_dump())
        async for r in self._smart(event, msg, "梦之试炼"):
            yield r

    @filter.command(CMD_SAKURA_ADV, "小樱进阶")
    async def handle_sakura_adv(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        zt, err2 = self._zt_load(doc)
        if err2:
            yield event.plain_result(err2)
            return
        ok, msg, s = world_deep.advance_sakura(zt, doc.realm_index)
        if ok:
            zt["sakura"] = s
            await self.db.save_player(self._zt_save(doc, zt).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_DECADE_DECK, "编组骑士卡片")
    async def handle_decade_deck(self, event: AstrMessageEvent, *, args: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        zt, err2 = self._zt_load(doc)
        if err2:
            yield event.plain_result(err2)
            return
        raw = (args or "").strip().replace("、", "*").replace(" ", "*")
        cards = [c.strip() for c in raw.split("*") if c.strip()]
        ok, msg, d2 = world_deep.set_decade_deck(zt, cards)
        if ok:
            zt["decade"] = d2
            await self.db.save_player(self._zt_save(doc, zt).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_FINAL_RIDE, "最终攻击驾驭")
    async def handle_final_ride(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        zt, err2 = self._zt_load(doc)
        if err2:
            yield event.plain_result(err2)
            return
        ok, msg, d2 = world_deep.final_ride(zt, int(zt.get("tier", 0)))
        if ok:
            zt["decade"] = d2
            await self.db.save_player(self._zt_save(doc, zt).model_dump())
        async for r in self._smart(event, msg, "最终攻击驾驭"):
            yield r

    @filter.command(CMD_REDEEM, "救赎")
    async def handle_redeem(self, event: AstrMessageEvent, *, args: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        zt, err2 = self._zt_load(doc)
        if err2:
            yield event.plain_result(err2)
            return
        is_self = not (args or "").strip().lstrip("@").strip()
        ok, msg, zt2 = world_deep.redeem(zt, str(zt.get("current") or ""), is_self)
        if ok:
            await self.db.save_player(self._zt_save(doc, zt2).model_dump())
        yield event.plain_result(msg)

    # ---- B3：问仙令通行证 ----

    def _wxl_track(self, doc: PlayerDoc, kind: str) -> None:
        """任务进度埋桩（写回 doc.ext，调用方负责落盘）。"""
        w = wenxian.system_of(doc)
        if not w.get("active"):
            return
        wenxian.track(w, kind)
        doc.ext["wenxian"] = w

    @filter.command(CMD_WXL, "问仙令面板")
    async def handle_wxl(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = wenxian.system_of(doc)
        async for r in self._smart(event, wenxian.panel(w, time.time()), "问仙令"):
            yield r

    @filter.command(CMD_WXL_CLUE, "求取问仙线索")
    async def handle_wxl_clue(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = wenxian.system_of(doc)
        ok, msg, w2 = wenxian.buy_clue(w, doc.stones)
        if ok:
            d = doc.model_copy(deep=True)
            d.stones -= wenxian.CLUE_COST
            d.ext["wenxian"] = w2
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_WXL_EXPLORE, "探索问仙线索")
    async def handle_wxl_explore(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = wenxian.system_of(doc)
        ok, msg, w2 = wenxian.explore_clue(w)
        if ok:
            d = doc.model_copy(deep=True)
            d.ext["wenxian"] = w2
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_WXL_ACT, "激活问仙令")
    async def handle_wxl_act(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = wenxian.system_of(doc)
        ok, msg, w2 = wenxian.activate(w, doc.realm_index)
        if ok:
            d = doc.model_copy(deep=True)
            d.ext["wenxian"] = w2
            await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_WXL_DAILY, "领取问仙令每日任务")
    async def handle_wxl_daily(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = wenxian.system_of(doc)
        if not w.get("active"):
            yield event.plain_result("问仙令未激活（#问仙令 查看流程）。")
            return
        now = time.time()
        msgs: list[str] = []
        total = 0
        for key in wenxian.DAILY_GOALS:
            ok, m, w = wenxian.claim_daily(w, key, now)
            if ok:
                msgs.append(m)
                total += 1
        if not total:
            yield event.plain_result(msgs[0] if msgs else "暂无已完成的每日任务（进度见 #问仙令）。")
            return
        d = doc.model_copy(deep=True)
        d.ext["wenxian"] = w
        await self.db.save_player(d.model_dump())
        async for r in self._smart(event, "\n".join(msgs), "问仙令 · 每日"):
            yield r

    @filter.command(CMD_WXL_CLAIM, "领取问仙令等级奖励")
    async def handle_wxl_claim(self, event: AstrMessageEvent, level: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = wenxian.system_of(doc)
        try:
            lv = int(level)
        except (TypeError, ValueError):
            lv = 0
        if lv <= 0:
            yield event.plain_result("格式：#领取问仙令 等级（如 #领取问仙令 3）")
            return
        ok, msg, w2, r = wenxian.claim_level(w, lv)
        if not ok:
            yield event.plain_result(msg)
            return
        d = doc.model_copy(deep=True)
        d.ext["wenxian"] = w2
        d.exp += r["exp_gain"]
        d.stones += r["stones"]
        d.ext["xueqi"] = float(d.ext.get("xueqi", 0) or 0) + r["xueqi"]
        if r["potential"]:
            d.ext["potential"] = float(d.ext.get("potential", 0) or 0) + r["potential"]
        await self.db.save_player(d.model_dump())
        async for rr in self._smart(event, msg, "问仙令 · 领奖"):
            yield rr

    @filter.command(CMD_WXL_WEEKLY, "领取每周任务")
    async def handle_wxl_weekly(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        w = wenxian.system_of(doc)
        ok, msg, w2 = wenxian.claim_weekly(w, time.time())
        if ok:
            d = doc.model_copy(deep=True)
            d.ext["wenxian"] = w2
            await self.db.save_player(d.model_dump())
        async for r in self._smart(event, msg, "问仙令 · 周任务"):
            yield r

    # ---- B4：源石坊赌石 ----

    @filter.command(CMD_STONE_MARKET, "源石坊")
    async def handle_stone_market(self, event: AstrMessageEvent, garden: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        g = (garden or "外园").strip()
        if g not in yuanshi.GARDENS:
            yield event.plain_result(f"可选档位：{'、'.join(yuanshi.GARDENS)}（默认外园）。")
            return
        now = time.time()
        y = yuanshi.system_of(doc)
        stones = yuanshi.make_market(doc.uid, g, now)
        async for r in self._smart(event, yuanshi.market_text(g, stones, y, now), f"源石坊 · {g}"):
            yield r

    @filter.command(CMD_STONE_INSPECT, "勘石")
    async def handle_stone_inspect(self, event: AstrMessageEvent, no: str = "", garden: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        g = (garden or "外园").strip()
        if g not in yuanshi.GARDENS:
            g = "外园"
        try:
            n = int(no)
        except (TypeError, ValueError):
            yield event.plain_result("格式：#勘石 序号（1-5）")
            return
        if doc.stones < yuanshi.INSPECT_COST:
            yield event.plain_result(f"勘石需 {yuanshi.INSPECT_COST:,} 灵石。")
            return
        stones = yuanshi.make_market(doc.uid, g, time.time())
        ok, msg = yuanshi.inspect(stones, n)
        if not ok:
            yield event.plain_result(msg)
            return
        d = doc.model_copy(deep=True)
        d.stones -= yuanshi.INSPECT_COST
        await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_STONE_BUY, "购石切石")
    async def handle_stone_buy(self, event: AstrMessageEvent, no: str = "", garden: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        g = (garden or "外园").strip()
        if g not in yuanshi.GARDENS:
            g = "外园"
        try:
            n = int(no)
        except (TypeError, ValueError):
            yield event.plain_result("格式：#购石 序号 [档位]（如 #购石 2 地字号）")
            return
        now = time.time()
        y = yuanshi.system_of(doc)
        stones = yuanshi.make_market(doc.uid, g, now)
        hp_cur, max_hp = self._hp_pair(doc)
        import random as _random
        rng = _random.Random(f"{doc.uid}:cut:{now}")
        ok, msg, y2, consume = yuanshi.buy_and_cut(doc, y, g, stones, n, doc.stones, hp_cur, max_hp, now, rng)
        if not ok:
            yield event.plain_result(msg)
            return
        d = doc.model_copy(deep=True)
        d.ext["yuanshi"] = y2
        cost = consume["cost"]
        if cost["currency"] == "灵石":
            d.stones = max(0, d.stones - int(cost["amount"]))
        if consume["hp_pct"]:
            d.ext["hp"] = max(1, int(hp_cur * (1 - consume["hp_pct"])))
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if consume["gains"]:
                await self.db.add_items(doc.uid, consume["gains"])
        async for r in self._smart(event, msg, f"切石 · {g}"):
            yield r

    @filter.command(CMD_STONE_EXCHANGE, "源石兑换")
    async def handle_stone_exchange(self, event: AstrMessageEvent, n: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        try:
            num = int(n)
        except (TypeError, ValueError):
            yield event.plain_result("格式：#源石兑换 数量（源石→灵石，汇率 10）")
            return
        y = yuanshi.system_of(doc)
        ok, msg, y2 = yuanshi.exchange(num, y)
        if not ok:
            yield event.plain_result(msg)
            return
        d = doc.model_copy(deep=True)
        d.ext["yuanshi"] = y2
        d.stones += num * 10
        await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    # ---- B5：魔头禁术 ----

    def _evil_save(self, doc: PlayerDoc, s: dict) -> PlayerDoc:
        d = doc.model_copy(deep=True)
        s = dict(s)
        d.ext["evil"] = s
        d.ext["modao"] = float(s.get("modao", 0))
        return d

    @filter.command(CMD_EVIL_MAGIC, "修炼魔功")
    async def handle_evil_magic(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = motou.state_of(doc)
        ok, msg, s2 = motou.train_magic(s)
        if ok:
            await self.db.save_player(self._evil_save(doc, s2).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_EVIL_MOSHI, "供奉魔石")
    async def handle_evil_moshi(self, event: AstrMessageEvent, n: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        try:
            qty = max(1, int(n))
        except (TypeError, ValueError):
            qty = 1
        have = dict(await self.db.get_inventory(doc.uid)).get("魔石", 0)
        if have < qty:
            yield event.plain_result(f"纳戒中魔石不足（有 {have}）。")
            return
        s = motou.state_of(doc)
        ok, msg, s2 = motou.offer_moshi(s, qty)
        d = self._evil_save(doc, s2)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if not await self.db.remove_item(doc.uid, "魔石", qty):
                raise RuntimeError("INSUFFICIENT")
        yield event.plain_result(msg)

    @filter.command(CMD_EVIL_SLAY, "镇魂")
    async def handle_evil_slay(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        target_uid = self._at_target(event)
        if not target_uid:
            yield event.plain_result("格式：#镇魂 @目标")
            return
        raw = await self.db.get_player(target_uid)
        if not raw:
            yield event.plain_result("目标尚未踏入修行。")
            return
        tgt = PlayerDoc(**raw)
        now = time.time()
        s = motou.state_of(doc)
        ts = motou.state_of(tgt)
        hp_cur, _ = self._hp_pair(doc)
        t_hp_cur, _ = self._hp_pair(tgt)
        ok, why = motou.can_slay(s, doc.realm_index, hp_cur, ts, tgt.realm_index, t_hp_cur, now)
        if not ok:
            yield event.plain_result(why)
            return
        # 战斗（镜像对拼，复用切磋引擎）
        import random as _random
        rng = _random.Random(f"{doc.uid}:slay:{now}")
        st_a, st_t = self._stats(doc), self._stats(tgt)
        me = battle.Unit(doc.name, st_a.atk, st_a.defense, hp_cur, st_a.bao)
        foe = battle.Unit(tgt.name, st_t.atk, st_t.defense, t_hp_cur, st_t.bao)
        result, log, hp_left, _ = battle.spar_full(me, foe, rng)
        won = result == 0
        s2 = motou.record_result(s, tgt.name, won, now)
        d = self._evil_save(doc, s2)
        d.ext["hp"] = max(1, hp_left)
        await self.db.save_player(d.model_dump())
        head = "禁术得手！" if won else "镇魂反噬！"
        tail = ("你压制了对方的真灵——#处置 烙印 / #处置 灭魂（10 分钟内）。" if won
                else "对方真灵顽强反扑，你落败退走（魔道值已消耗）。")
        async for r in self._smart(event, f"{head}\n" + "\n".join(log[-5:]) + f"\n{tail}", "镇魂"):
            yield r

    @filter.command(CMD_EVIL_DISPOSE, "处置战果")
    async def handle_evil_dispose(self, event: AstrMessageEvent, kind: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        kind = (kind or "").strip()
        s = motou.state_of(doc)
        p = s.get("pending")
        if not p:
            yield event.plain_result("没有待处置的镇魂战果（先 #镇魂 @目标 取胜）。")
            return
        tname = p.get("target")
        raw = None
        for uid in await self.db.all_player_uids():
            r = await self.db.get_player(uid)
            if r and r.get("name") == tname:
                raw = r
                break
        if not raw:
            yield event.plain_result(f"目标「{tname}」的档案已不存在。")
            return
        tgt = PlayerDoc(**raw)
        ts = motou.state_of(tgt)
        ok, msg, s2, tpatch = motou.dispose(s, kind, ts, time.time())
        if not ok:
            yield event.plain_result(msg)
            return
        d = self._evil_save(doc, s2)
        dt = tgt.model_copy(deep=True)
        te = dict(dt.ext.get("evil") or {})
        te.update(tpatch)
        dt.ext["evil"] = te
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.save_player(dt.model_dump())
        async for r in self._smart(event, msg, "禁术处置"):
            yield r

    @filter.command(CMD_EVIL_BREAK, "冲击魂印")
    async def handle_evil_break(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = motou.state_of(doc)
        ok, msg, s2 = motou.break_brand(doc, s, time.time(), doc.stones)
        if not ok:
            yield event.plain_result(msg)
            return
        d = self._evil_save(doc, s2)
        d.stones -= 500_000
        await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_EVIL_REFINE, "炼化遗蜕")
    async def handle_evil_refine(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = motou.state_of(doc)
        ok, msg, s2, consume = motou.refine_remains(s, doc.realm_index)
        if not ok:
            yield event.plain_result(msg)
            return
        d = self._evil_save(doc, s2)
        d.exp += consume["exp"]
        await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    # ---- B6：剧情 NPC（狠人大帝/苏灵）+ 凝聚精血 ----

    def _npc_save(self, doc: PlayerDoc, n: dict) -> PlayerDoc:
        d = doc.model_copy(deep=True)
        d.ext["npc"] = n
        return d

    @filter.command(CMD_FIERCE_TALK, "狠人交流")
    async def handle_fierce_talk(self, event: AstrMessageEvent):
        async for r in self._npc_talk(event, "ruthless"):
            yield r

    @filter.command("#狠人状态", "狠人状态")
    async def handle_fierce_state(self, event: AstrMessageEvent):
        async for r in self._npc_view(event):
            yield r

    @filter.command(CMD_SU_TALK, "苏灵交流")
    async def handle_su_talk(self, event: AstrMessageEvent):
        async for r in self._npc_talk(event, "suling"):
            yield r

    @filter.command("#苏灵状态", "苏灵状态")
    async def handle_su_state(self, event: AstrMessageEvent):
        async for r in self._npc_view(event):
            yield r

    async def _npc_view(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        n = npc.state_of(doc)
        async for r in self._smart(event, npc.panel(n, time.time()), "剧情人物"):
            yield r

    async def _npc_talk(self, event: AstrMessageEvent, who: str):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        n = npc.state_of(doc)
        ok, msg, n2 = npc.talk(n, who, time.time())
        if ok:
            await self.db.save_player(self._npc_save(doc, n2).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_FIERCE_ASK, "狠人请教")
    async def handle_fierce_ask(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        n = npc.state_of(doc)
        owned = list(doc.ext.get("gongfa") or [])
        ok, msg, n2, gongfa = npc.teach_ruthless(n, owned)
        if ok:
            d = self._npc_save(doc, n2)
            async with self.db.transaction():
                await self.db.save_player(d.model_dump())
                if gongfa:
                    await self.db.add_items(doc.uid, {gongfa: 1})
        async for r in self._smart(event, msg, "狠人请教"):
            yield r

    @filter.command(CMD_SU_ASK, "苏灵请教")
    async def handle_su_ask(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        n = npc.state_of(doc)
        ok, msg, n2, gain = npc.teach_suling(n, time.time())
        if not ok:
            yield event.plain_result(msg)
            return
        d = self._npc_save(doc, n2)
        d.exp += int(gain.get("exp", 0))
        if gain.get("potential"):
            d.ext["potential"] = float(d.ext.get("potential", 0) or 0) + float(gain["potential"])
        await self.db.save_player(d.model_dump())
        async for r in self._smart(event, msg, "苏灵请教"):
            yield r

    @filter.command(CMD_ESSENCE, "凝聚精血")
    async def handle_essence(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        n = npc.state_of(doc)
        ok, msg, n2 = npc.essence(doc, n, time.time())
        if not ok:
            yield event.plain_result(msg)
            return
        d = self._npc_save(doc, n2)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            await self.db.add_items(doc.uid, {npc.ESSENCE_ITEM: 1})
        yield event.plain_result(msg)

    # ---- B7：剧情人物全集（图鉴 / 邂逅 / 护道之约 / 黑皇阵道） ----

    def _story_roster(self) -> list[dict]:
        return self.content.table("item/剧情人物列表") or []

    def _story_gallery(self, doc: PlayerDoc) -> tuple[list[dict], int, int]:
        roster = self._story_roster()
        groups = story_npc.gallery_rows(doc, roster)
        total = unlocked = 0
        for g in groups:
            for c in g["chars"]:
                total += 1
                if c["unlocked"]:
                    unlocked += 1
                c["portrait_uri"] = (
                    render.asset_data_uri(f"character/{c['portrait']}") if c.get("portrait") else ""
                )
        return groups, total, unlocked

    @filter.command(CMD_NPC, "剧情人物图鉴")
    async def handle_story(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        raw = (name or "").strip()
        if raw:
            if raw in ("狠人", "狠人大帝"):
                raw = "狠人大帝"
            text = story_npc.detail_text(doc, self._story_roster(), raw)
            async for r in self._smart(event, text, f"剧情人物·{raw}"):
                yield r
            return
        groups, total, unlocked = self._story_gallery(doc)
        if self.render_on and total:
            pct = round(unlocked / total * 100)
            png = await render.render_panel(
                "story",
                {"title": "剧情人物图鉴", "footer": "诸天人物志",
                 "groups": groups, "total": total, "unlocked": unlocked, "pct": pct},
                self.panel_dir,
            )
            if png:
                yield event.image_result(str(png))
                return
        async for r in self._smart(event, story_npc.gallery_text(doc, self._story_roster()),
                                   "剧情人物图鉴"):
            yield r

    @filter.command(CMD_NPC_ALIAS, "剧情人物图鉴")
    async def handle_story_alias(self, event: AstrMessageEvent):
        async for r in self.handle_story(event):
            yield r

    # ---- 护道之约 ----

    async def _protect_assign(self, event: AstrMessageEvent, name: str):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = story_npc.state_of(doc)
        ok, msg, s2 = story_npc.assign_protector(doc, s, name)
        if ok:
            await self.db.save_player(story_npc.save(doc, s2).model_dump())
        async for r in self._smart(event, msg, "护道之约"):
            yield r

    @filter.command(CMD_PROTECT_LIU, "请柳神护道")
    async def handle_protect_liu(self, event: AstrMessageEvent):
        async for r in self._protect_assign(event, "柳神"):
            yield r

    @filter.command(CMD_PROTECT_SU, "请苏灵护道")
    async def handle_protect_su(self, event: AstrMessageEvent):
        async for r in self._protect_assign(event, "苏灵"):
            yield r

    @filter.command(CMD_PROTECT_HEN, "请狠人护道")
    async def handle_protect_hen(self, event: AstrMessageEvent):
        async for r in self._protect_assign(event, "狠人大帝"):
            yield r

    @filter.command(CMD_PROTECT_MY, "我的护道人")
    async def handle_protect_my(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = story_npc.state_of(doc)
        lines = ["--- 护道之约 ---", story_npc.protect_status(s, time.time()), ""]
        for n in ("柳神", "苏灵", "狠人大帝"):
            f = story_npc.favor_of(doc, n)
            mark = "✅" if f >= story_npc.PROTECTOR_FAVOR else f"{f}/{story_npc.PROTECTOR_FAVOR}"
            lines.append(f"{n}：{mark} 好感｜{story_npc.relation_of(n, f)}")
        lines.append("※ 480 好感可立约，秘境濒死自动出手（24 小时一次）")
        async for r in self._smart(event, "\n".join(lines), "护道之约"):
            yield r

    @filter.command(CMD_PROTECT_OFF, "解除护道")
    async def handle_protect_off(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = story_npc.state_of(doc)
        old, s2 = story_npc.clear_protector(s)
        if old == "无":
            yield event.plain_result("你本就没有护道人。")
            return
        await self.db.save_player(story_npc.save(doc, s2).model_dump())
        yield event.plain_result(f"你与「{old}」的护道之约已解。山高水长，各自珍重。")

    # ---- 黑皇阵道 ----

    @filter.command(CMD_HEI, "黑皇")
    async def handle_hei(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = story_npc.state_of(doc)
        async for r in self._smart(event, story_npc.hei_panel(s), "剧情人物·黑皇"):
            yield r

    @filter.command("#黑皇状态", "黑皇状态")
    async def handle_hei_state(self, event: AstrMessageEvent):
        async for r in self.handle_hei(event):
            yield r

    @filter.command(CMD_HEI_TALK, "黑皇交流")
    async def handle_hei_talk(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = story_npc.state_of(doc)
        ok, msg, s2 = story_npc.hei_talk(s, time.time())
        if ok:
            await self.db.save_player(story_npc.save(doc, s2).model_dump())
        async for r in self._smart(event, msg, "黑皇交流"):
            yield r

    @filter.command(CMD_HEI_TEACH, "黑皇请教阵道")
    async def handle_hei_teach(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = story_npc.state_of(doc)
        ok, msg, s2 = story_npc.hei_teach(s)
        if ok:
            await self.db.save_player(story_npc.save(doc, s2).model_dump())
        async for r in self._smart(event, msg, "黑皇阵道"):
            yield r

    @filter.command(CMD_HEI_ARRAYS, "黑皇阵法")
    async def handle_hei_arrays(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = story_npc.state_of(doc)
        async for r in self._smart(event, story_npc.formations_text(s, doc.stones), "黑皇阵法"):
            yield r

    @filter.command(CMD_HEI_ENGRAVE, "请黑皇刻阵")
    async def handle_hei_engrave(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = story_npc.state_of(doc)
        fname = (name or "").strip()
        if not fname:
            async for r in self._smart(event, story_npc.formations_text(s, doc.stones), "黑皇阵法"):
                yield r
            return
        ok, msg, f = story_npc.engrave_check(s, fname, time.time(), doc.stones)
        if not ok or f is None:
            yield event.plain_result(msg)
            return
        if f["kind"] == "exp" and doc.ext.get("occupation") != "阵法师":
            yield event.plain_result("「聚灵道阵」须以阵法师之身承受（#转职 阵法师）。")
            return
        mats = f.get("mats") or {}
        inv = await self.db.get_inventory(doc.uid)
        missing = [f"{k}×{v}（有 {int(inv.get(k, 0))}）" for k, v in mats.items()
                   if int(inv.get(k, 0)) < int(v)]
        if missing:
            yield event.plain_result("材料不足：" + "、".join(missing))
            return
        effect, s2 = story_npc.apply_engrave(s, fname, time.time())
        d = story_npc.save(doc, s2)
        d.stones -= int(f["cost"])
        note = ""
        if effect.get("job_exp"):
            lv, ex = self._ensure_occ(d)
            nlv, nex = occupation.add_exp(lv, ex, int(effect["job_exp"]), self.occ_exp_table)
            d.ext["occupation_level"] = nlv
            d.ext["occupation_exp"] = nex
            note = f"\n职业等级 {lv} → {nlv}（经验 +{int(effect['job_exp'])}）"
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            for k, v in mats.items():
                await self.db.remove_item(doc.uid, k, int(v))
        detail = {"seal": "阵纹已布下，下一场秘境战斗生效",
                  "kill": "杀阵已成，接下来 5 场秘境战斗生效",
                  "escape": "传送阵已就位，秘境战败时自动脱身",
                  "tribulation": "欺天阵纹已布下，下次帝兵雷劫消耗减半"}.get(f["kind"], "阵成")
        yield event.plain_result(
            f"黑皇爪影翻飞，【{fname}】阵纹一气呵成！\n{detail}。\n"
            f"耗灵石 {int(f['cost']):,}" + (f"、{('、'.join(f'{k}×{v}' for k, v in mats.items()))}" if mats else "")
            + note
        )

    @filter.command(CMD_ARRAY_OFF, "停用阵法")
    async def handle_array_off(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = story_npc.state_of(doc)
        s["arrays_off"] = True
        await self.db.save_player(story_npc.save(doc, s).model_dump())
        yield event.plain_result("阵纹暂敛，秘境战斗不再自动触发（#启用阵法 恢复）。")

    @filter.command(CMD_ARRAY_ON, "启用阵法")
    async def handle_array_on(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        s = story_npc.state_of(doc)
        s["arrays_off"] = False
        await self.db.save_player(story_npc.save(doc, s).model_dump())
        yield event.plain_result("阵纹重新亮起，秘境战斗将自动催动。")

    # ---- B7：团本讨伐（组队共享血条 + 伤害账本分奖） ----

    def _raid_cd_left(self, doc: PlayerDoc) -> float:
        return max(0.0, float(doc.ext.get("raid_cd", 0) or 0) - time.time())

    def _raid_block_text(self, left: float) -> str:
        hours = int(left // 3600)
        mins = int(left % 3600 // 60)
        return f"刚刚经历过一场团本讨伐，需休整 {hours} 小时 {mins} 分。"

    async def _raid_expire(self, team: dict | None) -> dict | None:
        """招募/讨伐超过 24h 自动解散。"""
        if not team or team.get("status") not in ("recruiting", "fighting"):
            return team
        if time.time() - float(team.get("created_at", 0) or 0) <= raid.RAID_TTL:
            return team
        await self.db.close_raid(team["code"], "closed", time.time())
        return None

    async def _raid_data(self, team: dict, members: list[dict], now: float) -> dict:
        hp = max(0, int(team.get("hp", 0) or 0))
        hp_max = max(1, int(team.get("hp_max", 1) or 1))
        pct = round(hp * 100 / hp_max, 1)
        cfg = raid.boss_of(team.get("boss")) or {}
        victory = str(team.get("status")) == "victory"
        ledger = [(m["uid"], m["name"], int(m.get("dmg", 0) or 0)) for m in members]
        shares = raid.split_rewards(
            int(team.get("reward", 0) or 0), ledger, team.get("killer_uid") or None
        ) if victory else []
        smap = {s["uid"]: s for s in shares}
        rows = []
        for m in members:
            share = smap.get(m["uid"]) or {}
            rows.append({
                "name": m.get("name") or m["uid"][:8],
                "dmg": f"{int(m.get('dmg', 0) or 0):,}",
                "hits": raid.hits_today(m, now),
                "leader": m["uid"] == team.get("leader_uid"),
                "killer": m["uid"] == team.get("killer_uid"),
                "stones": f"{int(share.get('stones', 0) or 0):,}",
            })
        if str(team.get("status")) == "recruiting":
            hint = f"队友加入：#加入讨伐队伍 {team['code']}｜队长：#发起讨伐"
        elif str(team.get("status")) == "fighting":
            hint = "#讨伐出手（今日 3 次，20 秒间隔）"
        elif victory:
            hint = "奖励已按伤害占比自动发放（击杀者 +10%）"
        else:
            hint = "队伍已解散"
        return {
            "title": f"团本讨伐 · {team.get('boss')}",
            "footer": f"队伍码 {team.get('code')}",
            "code": team.get("code"), "boss": team.get("boss"),
            "title_tag": cfg.get("title", ""),
            "status": raid.STATUS_LABEL.get(str(team.get("status")), str(team.get("status"))),
            "hp": f"{hp:,}", "hp_max": f"{hp_max:,}", "pct": pct,
            "reward": f"{int(team.get('reward', 0) or 0):,}",
            "members": rows, "victory": victory, "started": str(team.get("status")) != "recruiting",
            "loot": (f"{cfg['loot']}×{int(cfg.get('loot_qty', 1))}" if cfg.get("loot") else ""),
            "hint": hint,
        }

    async def _raid_send(self, event: AstrMessageEvent, team: dict, members: list[dict]):
        now = time.time()
        data = await self._raid_data(team, members, now)
        if self.render_on:
            png = await render.render_panel("raid", data, self.panel_dir)
            if png:
                yield event.image_result(str(png))
                return
        async for r in self._smart(event, raid.status_text(team, members, now), "团本讨伐"):
            yield r

    @filter.command(CMD_TR_CREATE, "创建讨伐队伍")
    async def handle_team_create(self, event: AstrMessageEvent, boss_name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        name = (boss_name or "").strip()
        if not name:
            lines = ["--- 创建讨伐队伍 ---"]
            for bname, cfg in raid.BOSSES.items():
                gate = f"，需【{cfg['gate']}】" if cfg.get("gate") else ""
                lines.append(f"· {bname}（第 {cfg['realm']} 境{gate}）：{cfg['desc']}")
            lines.append(f"格式：{CMD_TR_CREATE} 名字｜队长可邀 4 人（共 5 人）")
            async for r in self._smart(event, "\n".join(lines), "创建讨伐队伍"):
                yield r
            return
        cd = self._raid_cd_left(doc)
        if cd > 0:
            yield event.plain_result(self._raid_block_text(cd))
            return
        active = await self._raid_expire(await self.db.active_raid_of(doc.uid))
        ok, msg, cfg = raid.can_create(doc, name, bool(active))
        if not ok or cfg is None:
            yield event.plain_result(msg)
            return
        inv = await self.db.get_inventory(doc.uid)
        gate = cfg.get("gate") or ""
        if gate and int(inv.get(gate, 0)) < 1:
            yield event.plain_result(f"创建【{name}】的队伍需要【{gate}】×1。")
            return
        import random as _random
        rng = _random.Random(f"{doc.uid}:{time.time()}")
        code = ""
        for _ in range(20):
            code = raid.make_code(rng)
            if not await self.db.get_raid(code):
                break
        now = time.time()
        async with self.db.transaction():
            await self.db.create_raid(code, name, doc.uid, doc.name or doc.uid[:8], now)
            if gate:
                await self.db.remove_item(doc.uid, gate, 1)
        yield event.plain_result(
            f"【{name}】讨伐队伍已立！\n"
            f"队伍码：{code}（{raid.MAX_MEMBERS} 人上限）\n"
            f"队友加入：{CMD_TR_JOIN} {code}\n"
            f"队长开战：{CMD_TR_START}｜查看：{CMD_TR_INFO}"
            + (f"\n（已消耗【{gate}】×1）" if gate else "")
        )

    @filter.command(CMD_TR_JOIN, "加入讨伐队伍")
    async def handle_team_join(self, event: AstrMessageEvent, code: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        c = (code or "").strip()
        if not (len(c) == 6 and c.isdigit()):
            yield event.plain_result(f"格式：{CMD_TR_JOIN} 六位队伍码（{CMD_TR_LIST} 查看招募中队伍）")
            return
        cd = self._raid_cd_left(doc)
        if cd > 0:
            yield event.plain_result(self._raid_block_text(cd))
            return
        team = await self._raid_expire(await self.db.get_raid(c))
        if not team:
            yield event.plain_result("没有这个队伍码（或队伍已解散/逾期）。")
            return
        if await self.db.raid_member(c, doc.uid):
            yield event.plain_result("你已在这支队伍里。")
            return
        count = await self.db.raid_member_count(c)
        active = await self._raid_expire(await self.db.active_raid_of(doc.uid))
        ok, msg = raid.can_join(doc, team, count, bool(active))
        if not ok:
            yield event.plain_result(msg)
            return
        cfg = raid.boss_of(team["boss"])
        if cfg and not raid.realm_ok(doc, cfg):
            yield event.plain_result(f"【{team['boss']}】需第 {cfg['realm']} 境，道友境界未至。")
            return
        joined = await self.db.join_raid(c, doc.uid, doc.name or doc.uid[:8], time.time())
        if not joined:
            yield event.plain_result("加入失败：队伍状态已变化，请重试。")
            return
        yield event.plain_result(
            f"已加入【{team['boss']}】讨伐队（{count + 1}/{raid.MAX_MEMBERS}）。\n"
            f"等待队长 {CMD_TR_START}，开战后发 {CMD_TR_HIT} 出手。"
        )

    @filter.command(CMD_TR_START, "发起讨伐")
    async def handle_team_start(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        team = await self._raid_expire(await self.db.active_raid_of(doc.uid))
        if not team:
            yield event.plain_result("你不在任何招募中的队伍里。")
            return
        members = await self.db.raid_members(team["code"])
        ok, msg = raid.can_start(team, len(members), team["leader_uid"] == doc.uid)
        if not ok:
            yield event.plain_result(msg)
            return
        atks: list[int] = []
        for m in members:
            raw = await self.db.get_player(m["uid"])
            if raw:
                atks.append(self._stats(PlayerDoc(**raw)).atk)
        avg = sum(atks) // max(1, len(atks))
        cfg = raid.boss_of(team["boss"]) or {"tier": 1.0}
        stats = raid.boss_stats(avg, len(members), float(cfg.get("tier", 1.0)))
        if not await self.db.start_raid(team["code"], stats):
            yield event.plain_result("队伍状态已变化，发起失败。")
            return
        team = await self.db.get_raid(team["code"]) or team
        yield event.plain_result(
            f"【{team['boss']}】现身！全队 {len(members)} 人，均攻 {avg:,} 定标。\n"
            f"Boss 气血：{stats['hp']:,}｜奖池：{stats['reward']:,} 灵石\n"
            f"队员发 {CMD_TR_HIT} 出手（今日 3 次，20 秒间隔），击杀后自动分奖。"
        )

    @filter.command(CMD_TR_HIT, "讨伐出手")
    async def handle_team_hit(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        team = await self._raid_expire(await self.db.active_raid_of(doc.uid))
        if not team:
            yield event.plain_result("你不在进行中的讨伐队伍里。")
            return
        member = await self.db.raid_member(team["code"], doc.uid)
        if not member:
            yield event.plain_result("你不在这支队伍里。")
            return
        now = time.time()
        ok, msg = raid.can_hit(team, member, now)
        if not ok:
            yield event.plain_result(msg)
            return
        hp_cur, hp_max = self._hp_pair(doc)
        if hp_cur <= hp_max * 0.1:
            yield event.plain_result("气血将尽，先「#疗伤」再出手。")
            return
        st = self._stats(doc)
        sname, satk, sdef, shp = raid.shadow_of(team)
        import random as _random
        rng = _random.Random(f"{doc.uid}:raid:{team['code']}:{now}")
        me = battle.Unit(doc.name or doc.uid[:8] + "…", st.atk, st.defense, hp_cur, st.bao)
        shadow = battle.Unit(sname, satk, sdef, shp, 0.05)
        won, _log, hp_left, _ = battle.spar_full(me, shadow, rng, max_rounds=20)
        won_bool = won == 0
        dmg = raid.hit_damage(won_bool, st.atk, int(team["defense"]), int(team["hp_max"]), rng)
        doc.ext["hp"] = hp_left if won_bool else 0
        await self.db.save_player(doc.model_dump())
        left = await self.db.damage_raid(
            team["code"], doc.uid, dmg, raid.time_key(now), now
        )
        hits = raid.hits_today(member, now) + 1
        verdict = (
            f"你击碎{sname}，一击贯穿岩躯，造成 {dmg:,} 伤害！"
            if won_bool else
            f"你被{sname}击退，仍在其身上留下 {dmg:,} 伤害的血痕。"
        )
        lines = [
            verdict,
            f"Boss 剩余气血：{max(0, left):,} / {int(team['hp_max']):,}",
            f"今日出手：{hits}/{raid.HITS_PER_MEMBER}",
        ]
        if not won_bool:
            lines.append("你重伤倒地（气血归零），先「#疗伤」。")
        if left <= 0:
            members = await self.db.raid_members(team["code"])
            shares = await self._raid_settle(team, members, doc.uid)
            lines.append(f"\n【全队公告】{team['boss']} 被讨伐！奖池 {int(team['reward']):,} 灵石已按伤害分奖：")
            for s in shares:
                lines.append(f"· {s['name']}：{s['stones']:,} 灵石（伤害 {s['dmg']:,}｜{s['share']}%）")
            cfg = raid.boss_of(team["boss"]) or {}
            if cfg.get("loot"):
                lines.append(f"每人另得【{cfg['loot']}】×{int(cfg.get('loot_qty', 1))}。")
        async for r in self._smart(event, "\n".join(lines), "团本讨伐"):
            yield r

    async def _raid_settle(self, team: dict, members: list[dict], killer_uid: str) -> list[dict]:
        ledger = [(m["uid"], m["name"], int(m.get("dmg", 0) or 0)) for m in members]
        shares = raid.split_rewards(
            int(team.get("reward", 0) or 0), ledger, killer_uid
        )
        cfg = raid.boss_of(team["boss"]) or {}
        now = time.time()
        async with self.db.transaction():
            for s in shares:
                raw = await self.db.get_player(s["uid"])
                if raw:
                    p = PlayerDoc(**raw)
                    p.stones += int(s["stones"])
                    p.ext["raid_cd"] = now + raid.CLEAR_CD
                    await self.db.save_player(p.model_dump())
                if cfg.get("loot"):
                    await self.db.add_items(
                        s["uid"], {cfg["loot"]: int(cfg.get("loot_qty", 1))}
                    )
            await self.db.mark_raid_settled(team["code"])
        return shares

    @filter.command(CMD_TR_INFO, "查看队伍信息")
    async def handle_team_info(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        team = await self._raid_expire(await self.db.active_raid_of(doc.uid))
        if not team:
            team = await self.db.last_raid_of(doc.uid)
        if not team or team.get("status") == "closed":
            yield event.plain_result(f"你不在任何队伍中。{CMD_TR_LIST} 查看招募中的团本。")
            return
        members = await self.db.raid_members(team["code"])
        async for r in self._raid_send(event, team, members):
            yield r

    @filter.command(CMD_TR_LIST, "团本列表")
    async def handle_team_list(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        raw_teams = await self.db.list_raids("recruiting", 20)
        teams = []
        for t in raw_teams:
            alive = await self._raid_expire(t)
            if alive:
                teams.append(alive)
            if len(teams) >= 10:
                break
        if not teams:
            yield event.plain_result(
                f"暂无招募中的团本。发「{CMD_TR_CREATE} 若陀龙王」开一支。"
            )
            return
        lines = ["--- 招募中的团本 ---"]
        for t in teams:
            n = await self.db.raid_member_count(t["code"])
            lines.append(
                f"· {t['boss']}｜队伍码 {t['code']}｜队长 {t['leader_name']}｜{n}/{raid.MAX_MEMBERS}"
            )
        lines.append(f"加入：{CMD_TR_JOIN} 队伍码")
        async for r in self._smart(event, "\n".join(lines), "团本列表"):
            yield r

    @filter.command(CMD_TR_DISMISS, "解散队伍")
    async def handle_team_dismiss(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        team = await self.db.active_raid_of(doc.uid)
        if not team:
            yield event.plain_result("你不在任何队伍中。")
            return
        if team["leader_uid"] != doc.uid:
            yield event.plain_result("只有队长可以解散队伍。")
            return
        await self.db.close_raid(team["code"], "closed", time.time())
        yield event.plain_result(f"【{team['boss']}】讨伐队已解散（队伍码 {team['code']}）。")

    @filter.command(CMD_TR_CLAIM, "结算团本奖励")
    async def handle_team_claim(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        team = await self.db.last_raid_of(doc.uid)
        if not team or team.get("status") != "victory":
            yield event.plain_result("你还没有已讨伐成功的团本。")
            return
        members = await self.db.raid_members(team["code"])
        cfg = raid.boss_of(team["boss"]) or {}
        shares = raid.split_rewards(
            int(team.get("reward", 0) or 0),
            [(m["uid"], m["name"], int(m.get("dmg", 0) or 0)) for m in members],
            team.get("killer_uid") or None,
        )
        lines = [f"--- {team['boss']} · 奖励结算 ---",
                 f"队伍码：{team['code']}｜奖池：{int(team.get('reward', 0)):,} 灵石"]
        for s in shares:
            lines.append(
                f"· {s['name']}：{s['stones']:,} 灵石（伤害 {s['dmg']:,}｜{s['share']}%）"
            )
        if cfg.get("loot"):
            lines.append(f"每位参战者另得【{cfg['loot']}】×{int(cfg.get('loot_qty', 1))}")
        lines.append("奖励已于击杀时自动发放，无需重复领取。")
        async for r in self._smart(event, "\n".join(lines), "团本结算"):
            yield r

    # ---- B8-1：无尽劫境（单人劫环核心） ----

    def _endless_content(self) -> dict:
        return self.content.table("无尽劫境") or {}

    def _endless_base(self, doc: PlayerDoc) -> dict:
        st = self._stats(doc)
        return {"atk": st.atk, "def": st.defense, "hp": st.hp, "bao": st.bao}

    def _endless_panel_data(self, st: dict, base: dict, content: dict, now: float) -> dict:
        stats = endless.run_stats(st, base, content, endless.celestial_of(now))
        world = endless.world_of(content, str(st.get("world") or ""))
        tier = endless.tier_of(int(st.get("tier", 1) or 1))
        idx = endless.index(content)
        sel = int(st.get("pending_node", 0) or 0)
        nodes = []
        for i, n in enumerate(st.get("starmap") or [], 1):
            nodes.append({
                "no": i, "name": n.get("name") or "",
                "type": endless.NODE_LABEL.get(str(n.get("type")), str(n.get("type"))),
                "desc": n.get("desc") or "", "selected": i == sel,
            })
        choices = []
        for i, aid in enumerate(st.get("choices") or [], 1):
            ab = idx["abilities"].get(aid) or {}
            cur = int((st.get("abilities") or {}).get(aid, 0) or 0)
            max_lv = int(ab.get("maxLevel", 3) or 3)
            choices.append({
                "no": i, "name": ab.get("name", aid), "rarity": ab.get("rarity", ""),
                "lv": (f"Lv.{cur}→{min(max_lv, cur + 1)}" if cur else "新悟"),
                "desc": ab.get("description", ""),
            })
        checkpoints = [
            {"no": i, "name": c.get("name", ""), "sub": c.get("sub", ""),
             "desc": c.get("desc", "")}
            for i, c in enumerate(st.get("checkpoint") or [], 1)
        ]
        abilities = []
        for aid, lv in sorted((st.get("abilities") or {}).items(),
                              key=lambda kv: -int(kv[1])):
            ab = idx["abilities"].get(aid) or {}
            abilities.append({
                "name": ab.get("name", aid), "lv": int(lv),
                "max": int(ab.get("maxLevel", 3) or 3), "rarity": ab.get("rarity", ""),
            })
        boons = [(idx["boons"].get(b) or {}).get("name", b) for b in (st.get("boons") or [])]
        phase = {"ready": "星图待定", "choice": "道法三选一",
                 "checkpoint": "劫后问道"}.get(str(st.get("phase")), str(st.get("phase")))
        if str(st.get("phase")) == "ready":
            hint = "#星图定途 1-3 → #无尽下一关｜撤离：#无尽撤离"
        elif str(st.get("phase")) == "choice":
            hint = "#无尽选择 1-3"
        elif str(st.get("phase")) == "checkpoint":
            hint = "#劫后抉择 1-3"
        else:
            hint = "#无尽构筑"
        hp_max = max(1, int(stats["hp"]))
        hp = max(0, min(int(st.get("hp", 0) or 0), hp_max))
        return {
            "title": f"无尽劫境 · {world.get('name')}",
            "footer": f"{tier['code']}·{tier['name']}",
            "tier": f"{tier['code']}·{tier['name']}",
            "layer": int(st.get("layer", 0) or 0), "phase": phase,
            "hp": f"{hp:,}", "hp_max": f"{hp_max:,}",
            "pct": round(hp * 100 / hp_max, 1),
            "atk": f"{stats['atk']:,}", "def": f"{stats['def']:,}",
            "bao": f"{stats['bao']:.0%}",
            "marks": f"{int(st.get('marks', 0) or 0):,}",
            "total": f"{int(st.get('marks_total', 0) or 0):,}",
            "rule": world.get("rule", ""),
            "nodes": nodes, "choices": choices, "checkpoints": checkpoints,
            "abilities": abilities, "boons": boons, "hint": hint,
        }

    async def _endless_send(self, event: AstrMessageEvent, doc: PlayerDoc, st: dict):
        base = self._endless_base(doc)
        content = self._endless_content()
        now = time.time()
        if self.render_on:
            png = await render.render_panel(
                "endless", self._endless_panel_data(st, base, content, now), self.panel_dir
            )
            if png:
                yield event.image_result(str(png))
                return
        async for r in self._smart(
            event, endless.status_text(st, base, content, now), "无尽劫境"
        ):
            yield r

    @filter.command(CMD_ENDLESS, "无尽劫境")
    async def handle_endless(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if st.get("active"):
            async for r in self._endless_send(event, doc, st):
                yield r
            return
        content = self._endless_content()
        worlds = "、".join(w.get("name", "") for w in (content.get("worlds") or []))
        lines = [
            "--- 无尽劫境 ---",
            f"入场：{endless.ENTRY_COST:,} 灵石｜第 {endless.ENTRY_REALM} 境",
            f"难度：{endless.TIERS[min(len(endless.TIERS) - 1, int(st.get('tier', 1)) - 1)]['code']}"
            f"·{endless.TIERS[min(len(endless.TIERS) - 1, int(st.get('tier', 1)) - 1)]['name']}"
            f"｜已解锁至 {endless.TIERS[endless.unlocked_tier(st) - 1]['code']}",
            f"世界：{worlds}",
            f"累计道痕：{int(st.get('marks_total', 0) or 0):,}｜最高 A{st.get('best_tier', 1)} 第 {st.get('best_layer', 0)} 层",
            "流程：#开启无尽劫境 [世界] → #劫途星图 → #星图定途 N → #无尽下一关",
            "　　　每 3 层 #劫后抉择，每层后 #无尽选择，随时 #无尽撤离",
            "其他：#无尽构筑 / #无尽难度 A2 / #今日天象 / #无尽排名",
            "商店：#无尽商店｜局内商人：#劫境商人｜称号：#称号｜周末：#周末免费",
        ]
        async for r in self._smart(event, "\n".join(lines), "无尽劫境"):
            yield r

    @filter.command(CMD_ENDLESS_START, "开启无尽劫境")
    async def handle_endless_start(self, event: AstrMessageEvent, world: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if st.get("active"):
            yield event.plain_result("你已在一场劫境之中（#无尽构筑 / #无尽撤离）。")
            return
        ok, msg = endless.check_entry(doc)
        if not ok:
            yield event.plain_result(msg)
            return
        now = time.time()
        free = endless.weekend_available(st, now)
        cost = 0 if free else endless.ENTRY_COST
        if doc.stones < cost:
            yield event.plain_result(
                f"开启劫境需 {cost:,} 灵石（当前 {doc.stones:,}）。"
            )
            return
        base = self._endless_base(doc)
        ok, msg, st2 = endless.start_run(
            st, doc, base, self._endless_content(), (world or "").strip(), now
        )
        if not ok:
            yield event.plain_result(msg)
            return
        if free:
            st2["weekend_week"] = endless.week_key(now)
            msg += "\n（周末免费额度：本次免入场灵石）"
        d = endless.save(doc, st2)
        d.stones -= cost
        await self.db.save_player(d.model_dump())
        async for r in self._smart(event, msg, "无尽劫境"):
            yield r

    @filter.command(CMD_ENDLESS_MAP, "劫途星图")
    async def handle_endless_map(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if not st.get("active"):
            yield event.plain_result(f"尚未开启劫境（{CMD_ENDLESS_START}）。")
            return
        if st.get("phase") != "ready":
            yield event.plain_result("先处理当前的道法/劫后抉择。")
            return
        async for r in self._endless_send(event, doc, st):
            yield r

    @filter.command(CMD_ENDLESS_ROUTE, "星图定途")
    async def handle_endless_route(self, event: AstrMessageEvent, idx: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if not st.get("active"):
            yield event.plain_result(f"尚未开启劫境（{CMD_ENDLESS_START}）。")
            return
        raw = (idx or "").strip()
        if not raw.isdigit():
            yield event.plain_result(f"格式：{CMD_ENDLESS_ROUTE} 1-3（先看 {CMD_ENDLESS_MAP}）")
            return
        ok, msg, st2 = endless.select_node(st, int(raw))
        if not ok:
            yield event.plain_result(msg)
            return
        await self.db.save_player(endless.save(doc, st2).model_dump())
        yield event.plain_result(msg + f"\n前进：{CMD_ENDLESS_NEXT}")

    @filter.command(CMD_ENDLESS_NEXT, "无尽下一关")
    async def handle_endless_next(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if not st.get("active"):
            yield event.plain_result(f"尚未开启劫境（{CMD_ENDLESS_START}）。")
            return
        if st.get("phase") != "ready":
            hint = ("#无尽选择 1-3" if st.get("phase") == "choice" else "#劫后抉择 1-3")
            yield event.plain_result(f"先处理当前阶段：{hint}")
            return
        import random as _random
        now = time.time()
        rng = _random.Random(f"{doc.uid}:endless:{st.get('layer')}:{now}")
        st2, res = endless.resolve_node(st, self._endless_base(doc),
                                        self._endless_content(), now, rng)
        d = endless.save(doc, st2)
        unlock_name = None
        if res.get("clear"):
            tres, unlock_name = endless.grant_treasure(endless.treasury_of(doc), st2)
            d = endless.save_treasury(d, tres)
        await self.db.save_player(d.model_dump())
        lines = [str(res.get("msg") or "")]
        if unlock_name:
            lines.append(f"✦ 解锁无尽至宝【{unlock_name}】（{CMD_ENDLESS_TREASURE} 装备/升级）")
        if res.get("log"):
            lines.append(str(res["log"][-1]))
        idx = endless.index(self._endless_content())
        if res.get("choices"):
            lines.append("【道法三选一】")
            for i, aid in enumerate(res["choices"], 1):
                ab = idx["abilities"].get(aid) or {}
                lines.append(f"{i}. {ab.get('name')}（{ab.get('rarity')}）{ab.get('description', '')}")
            lines.append(f"选择：{CMD_ENDLESS_PICK} 1-{len(res['choices'])}")
        if res.get("checkpoint"):
            lines.append("【劫后问道】")
            for i, c in enumerate(endless.CHECKPOINT_CHOICES, 1):
                lines.append(f"{i}. {c['name']}——{c['desc']}")
            lines.append(f"选择：{CMD_ENDLESS_CHECKPOINT} 1-3")
        if res.get("clear"):
            lines.append(f"下一档：#无尽难度 A{min(10, int(st2.get('tier', 1)) + 1)}")
        async for r in self._smart(event, "\n".join(x for x in lines if x), "无尽劫境"):
            yield r

    @filter.command(CMD_ENDLESS_PICK, "无尽选择")
    async def handle_endless_pick(self, event: AstrMessageEvent, idx: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if not st.get("active") or st.get("phase") != "choice":
            yield event.plain_result("现在没有待选的道法。")
            return
        raw = (idx or "").strip()
        if not raw.isdigit():
            yield event.plain_result(f"格式：{CMD_ENDLESS_PICK} 1-3")
            return
        ok, msg, st2 = endless.pick_ability(st, int(raw), self._endless_content())
        if not ok:
            yield event.plain_result(msg)
            return
        await self.db.save_player(endless.save(doc, st2).model_dump())
        yield event.plain_result(msg + f"\n继续：{CMD_ENDLESS_MAP}")

    @filter.command(CMD_ENDLESS_CHECKPOINT, "劫后抉择")
    async def handle_endless_checkpoint(self, event: AstrMessageEvent, idx: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if not st.get("active") or st.get("phase") != "checkpoint":
            yield event.plain_result("现在不是劫后抉择的时候。")
            return
        raw = (idx or "").strip()
        if not raw.isdigit():
            yield event.plain_result(f"格式：{CMD_ENDLESS_CHECKPOINT} 1-3")
            return
        import random as _random
        ok, msg, st2 = endless.apply_checkpoint(
            st, int(raw), self._endless_content(), self._endless_base(doc),
            _random.Random(f"{doc.uid}:cp:{st.get('layer')}:{time.time()}"), time.time(),
        )
        if not ok:
            yield event.plain_result(msg)
            return
        await self.db.save_player(endless.save(doc, st2).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_ENDLESS_BUILD, "无尽构筑")
    async def handle_endless_build(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if not st.get("active"):
            yield event.plain_result(f"当前没有进行中的劫境（{CMD_ENDLESS_START}）。")
            return
        text = endless.build_text(st, self._endless_base(doc),
                                  self._endless_content(), time.time())
        async for r in self._smart(event, text, "无尽构筑"):
            yield r

    @filter.command(CMD_ENDLESS_QUIT, "无尽撤离")
    async def handle_endless_quit(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if not st.get("active"):
            yield event.plain_result("你不在劫境之中。")
            return
        msg, st2 = endless.withdraw(st, time.time())
        await self.db.save_player(endless.save(doc, st2).model_dump())
        async for r in self._smart(event, msg, "无尽撤离"):
            yield r

    @filter.command(CMD_ENDLESS_TIER, "无尽难度")
    async def handle_endless_tier(self, event: AstrMessageEvent, tier: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        raw = (tier or "").strip().upper().replace("A", "")
        if not raw:
            lines = ["--- 无尽难度 ---"]
            unlocked = endless.unlocked_tier(st)
            for t in endless.TIERS:
                mark = "✅" if t["tier"] <= unlocked else "🔒"
                lines.append(
                    f"{mark} {t['code']}·{t['name']}｜敌血 ×{t['hp']:.2f}"
                    f"｜敌攻 ×{t['atk']:.2f}｜道痕 ×{t['reward']:.2f}"
                )
            lines.append(f"当前：A{st.get('tier', 1)}｜切换：#无尽难度 A2")
            async for r in self._smart(event, "\n".join(lines), "无尽难度"):
                yield r
            return
        if not raw.isdigit():
            yield event.plain_result(f"格式：{CMD_ENDLESS_TIER} A1-A10")
            return
        ok, msg, st2 = endless.set_tier(st, int(raw))
        if not ok:
            yield event.plain_result(msg)
            return
        await self.db.save_player(endless.save(doc, st2).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_ENDLESS_CELESTIAL, "今日天象")
    async def handle_endless_celestial(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        c = endless.celestial_of(time.time())
        st = endless.state_of(doc)
        lines = [
            "--- 今日天象 ---",
            f"【{c['name']}】{c.get('desc', '')}",
            "影响："
            + ("能力加成 ×%.2f｜" % float(c["ability"]) if c.get("ability") else "")
            + ("道痕收益 ×%.2f" % float(c["token"]) if c.get("token") else "道痕收益 ×1.00"),
            f"当前难度：A{st.get('tier', 1)}｜每日 0 点轮换（上海时区）",
        ]
        async for r in self._smart(event, "\n".join(lines), "今日天象"):
            yield r

    @filter.command(CMD_ENDLESS_RANK, "无尽排名")
    async def handle_endless_rank(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        rows = endless.rank_rows(await self.db.all_players(), 10)
        if not rows:
            yield event.plain_result("还没有人踏入劫境。")
            return
        lines = ["--- 无尽劫境 · 排名 ---"]
        for i, r in enumerate(rows, 1):
            lines.append(
                f"{i}. {r['name']}｜A{r['tier']} 第 {r['layer']} 层｜道痕 {r['marks']:,}"
            )
        async for r in self._smart(event, "\n".join(lines), "无尽排名"):
            yield r

    # ---- B8-2：无尽商店 / 劫境商人 / 称号 / 周末免费 ----

    def _endless_shop(self) -> dict:
        return self.content.table("无尽商店") or {}

    @filter.command(CMD_ENDLESS_SHOP, "无尽商店")
    async def handle_endless_shop(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        text = endless.shop_text(
            st, self._endless_shop(), endless.celestial_of(time.time()), time.time()
        )
        async for r in self._smart(event, text, "无尽商店"):
            yield r

    @filter.command(CMD_ENDLESS_BUY, "无尽购买")
    async def handle_endless_buy(self, event: AstrMessageEvent, item: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        raw = (item or "").strip()
        if not raw:
            yield event.plain_result(f"格式：{CMD_ENDLESS_BUY} 编号或名称[*数量]")
            return
        ident, _, qtxt = raw.partition("*")
        qty = int(qtxt) if qtxt.strip().isdigit() else 1
        st = endless.state_of(doc)
        now = time.time()
        ok, msg, st2, items = endless.buy_shop(
            st, ident.strip(), qty, now, self._endless_shop(), endless.celestial_of(now)
        )
        if not ok:
            yield event.plain_result(msg)
            return
        d = endless.save(doc, st2)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if items:
                await self.db.add_items(doc.uid, items)
        async for r in self._smart(event, msg, "无尽购买"):
            yield r

    @filter.command(CMD_ENDLESS_MERCHANT, "劫境商人")
    async def handle_endless_merchant(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if not st.get("active"):
            yield event.plain_result("劫境商人在劫境之内才会现身（#开启无尽劫境）。")
            return
        import random as _random
        now = time.time()
        st2 = endless.refresh_merchant(
            st, self._endless_shop(), endless.celestial_of(now),
            _random.Random(f"{doc.uid}:merchant:{st.get('layer')}"),
        )
        await self.db.save_player(endless.save(doc, st2).model_dump())
        async for r in self._smart(event, endless.merchant_text(st2), "劫境商人"):
            yield r

    @filter.command(CMD_ENDLESS_MERCHANT_BUY, "劫境购买")
    async def handle_endless_merchant_buy(self, event: AstrMessageEvent, idx: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if not st.get("active"):
            yield event.plain_result("你不在劫境之中。")
            return
        raw = (idx or "").strip()
        if not raw.isdigit():
            yield event.plain_result(f"格式：{CMD_ENDLESS_MERCHANT_BUY} 1-4")
            return
        ok, msg, st2, items = endless.buy_merchant(
            st, int(raw), endless.celestial_of(time.time())
        )
        if not ok:
            yield event.plain_result(msg)
            return
        d = endless.save(doc, st2)
        async with self.db.transaction():
            await self.db.save_player(d.model_dump())
            if items:
                await self.db.add_items(doc.uid, items)
        yield event.plain_result(msg)

    @filter.command(CMD_ENDLESS_TITLES, "称号")
    async def handle_endless_titles(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        async for r in self._smart(event, endless.titles_text(endless.state_of(doc)), "称号"):
            yield r

    @filter.command(CMD_ENDLESS_TITLES_ALIAS, "我的称号")
    async def handle_endless_titles_alias(self, event: AstrMessageEvent):
        async for r in self.handle_endless_titles(event):
            yield r

    @filter.command(CMD_ENDLESS_TITLE_EQUIP, "佩戴称号")
    async def handle_endless_title_equip(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        raw = (name or "").strip()
        if not raw:
            yield event.plain_result(f"格式：{CMD_ENDLESS_TITLE_EQUIP} 称号名（{CMD_ENDLESS_TITLES} 查看）")
            return
        st = endless.state_of(doc)
        ok, msg, st2 = endless.equip_title(st, raw)
        if not ok:
            yield event.plain_result(msg)
            return
        await self.db.save_player(endless.save(doc, st2).model_dump())
        async for r in self._smart(event, msg, "佩戴称号"):
            yield r

    @filter.command(CMD_ENDLESS_WEEKEND, "周末免费")
    async def handle_endless_weekend(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        async for r in self._smart(
            event, endless.weekend_text(st, time.time()), "周末免费"
        ):
            yield r

    # ---- B8-3：万劫道碑 / 无尽至宝 / 能力重演 / 扫荡 ----

    @filter.command(CMD_ENDLESS_META, "万劫道碑")
    async def handle_endless_meta(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        text = endless.meta_text(endless.meta_state_of(doc), endless.state_of(doc))
        async for r in self._smart(event, text, "万劫道碑"):
            yield r

    @filter.command(CMD_ENDLESS_META_UP, "参悟道碑")
    async def handle_endless_meta_up(self, event: AstrMessageEvent, node: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        raw = (node or "").strip()
        if not raw:
            text = endless.meta_text(endless.meta_state_of(doc), endless.state_of(doc))
            async for r in self._smart(event, text, "万劫道碑"):
                yield r
            return
        st = endless.state_of(doc)
        ok, msg, meta2, st2 = endless.upgrade_meta(endless.meta_state_of(doc), st, raw)
        if not ok:
            yield event.plain_result(msg)
            return
        d = endless.save_meta(doc, meta2)
        d = endless.save(d, st2)
        if st2.get("active"):
            d.ext["endless"]["meta"] = endless.meta_effects(meta2)
        await self.db.save_player(d.model_dump())
        async for r in self._smart(event, msg, "参悟道碑"):
            yield r

    @filter.command(CMD_ENDLESS_META_RESET, "重置万劫道碑")
    async def handle_endless_meta_reset(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if st.get("active"):
            yield event.plain_result("劫境进行中不可重置道碑，先「#无尽撤离」。")
            return
        meta = endless.meta_state_of(doc)
        if not int(meta.get("spent", 0) or 0):
            yield event.plain_result("万劫道碑尚未投入道痕。")
            return
        refund = int(int(meta["spent"]) * 0.8)
        yield event.plain_result(
            f"重置万劫道碑将清空全部节点与流派，返还 80% 道痕（{refund:,}）。\n"
            f"确认请发送「{CMD_ENDLESS_META_RESET_YES}」。"
        )

    @filter.command(CMD_ENDLESS_META_RESET_YES, "确认重置万劫道碑")
    async def handle_endless_meta_reset_yes(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if st.get("active"):
            yield event.plain_result("劫境进行中不可重置道碑，先「#无尽撤离」。")
            return
        ok, msg, meta2, st2 = endless.reset_meta(endless.meta_state_of(doc), st)
        if not ok:
            yield event.plain_result(msg)
            return
        d = endless.save_meta(doc, meta2)
        d = endless.save(d, st2)
        await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_ENDLESS_REROLL, "重置无尽能力")
    async def handle_endless_reroll(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        if not st.get("active") or st.get("phase") != "choice":
            yield event.plain_result("现在没有待选的道法。")
            return
        import random as _random
        ok, msg, st2 = endless.reroll_choices(
            st, self._endless_content(), _random.Random(f"{doc.uid}:reroll:{time.time()}")
        )
        if not ok:
            yield event.plain_result(msg)
            return
        await self.db.save_player(endless.save(doc, st2).model_dump())
        idx = endless.index(self._endless_content())
        lines = [msg]
        for i, aid in enumerate(st2.get("choices") or [], 1):
            ab = idx["abilities"].get(aid) or {}
            lines.append(f"{i}. {ab.get('name')}（{ab.get('rarity')}）{ab.get('description', '')}")
        lines.append(f"选择：{CMD_ENDLESS_PICK} 1-{len(st2.get('choices') or [])}")
        async for r in self._smart(event, "\n".join(lines), "劫机重演"):
            yield r

    @filter.command(CMD_ENDLESS_TREASURE, "无尽至宝")
    async def handle_endless_treasure(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        text = endless.treasury_text(endless.treasury_of(doc), endless.state_of(doc))
        async for r in self._smart(event, text, "无尽至宝"):
            yield r

    @filter.command(CMD_ENDLESS_TREASURE_UP, "升级无尽至宝")
    async def handle_endless_treasure_up(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        raw = (name or "").strip()
        if not raw:
            yield event.plain_result(f"格式：{CMD_ENDLESS_TREASURE_UP} 至宝名")
            return
        ok, msg, tres, st2 = endless.upgrade_treasure(
            endless.treasury_of(doc), endless.state_of(doc), raw
        )
        if not ok:
            yield event.plain_result(msg)
            return
        if st2.get("active"):
            st2["treasures"] = endless.equipped_treasures(tres)
        d = endless.save_treasury(doc, tres)
        d = endless.save(d, st2)
        await self.db.save_player(d.model_dump())
        async for r in self._smart(event, msg, "升级至宝"):
            yield r

    @filter.command(CMD_ENDLESS_TREASURE_EQUIP, "装备无尽至宝")
    async def handle_endless_treasure_equip(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        raw = (name or "").strip()
        if not raw:
            yield event.plain_result(f"格式：{CMD_ENDLESS_TREASURE_EQUIP} 至宝名")
            return
        ok, msg, tres = endless.equip_treasure(endless.treasury_of(doc), raw)
        if not ok:
            yield event.plain_result(msg)
            return
        await self.db.save_player(endless.save_treasury(doc, tres).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_ENDLESS_TREASURE_UNEQUIP, "卸下无尽至宝")
    async def handle_endless_treasure_unequip(self, event: AstrMessageEvent, name: str = ""):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        raw = (name or "").strip()
        if not raw:
            yield event.plain_result(f"格式：{CMD_ENDLESS_TREASURE_UNEQUIP} 至宝名")
            return
        ok, msg, tres = endless.unequip_treasure(endless.treasury_of(doc), raw)
        if not ok:
            yield event.plain_result(msg)
            return
        await self.db.save_player(endless.save_treasury(doc, tres).model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_ENDLESS_TREASURE_SLOT, "拓展无尽至宝槽")
    async def handle_endless_treasure_slot(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        ok, msg, tres, st2 = endless.expand_slots(
            endless.treasury_of(doc), endless.state_of(doc)
        )
        if not ok:
            yield event.plain_result(msg)
            return
        d = endless.save_treasury(doc, tres)
        d = endless.save(d, st2)
        await self.db.save_player(d.model_dump())
        yield event.plain_result(msg)

    @filter.command(CMD_ENDLESS_SWEEP, "扫荡无尽劫境")
    async def handle_endless_sweep(self, event: AstrMessageEvent):
        if not self._allowed(event):
            return
        doc, err = await self._require_player(event)
        if err:
            yield event.plain_result(err)
            return
        st = endless.state_of(doc)
        ok, msg, st2 = endless.sweep(st, time.time(), endless.celestial_of(time.time()))
        if not ok:
            yield event.plain_result(msg)
            return
        await self.db.save_player(endless.save(doc, st2).model_dump())
        yield event.plain_result(msg)

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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        # 黑皇阵纹：只在真正进入战斗时催动（逐场消耗）
        s = story_npc.state_of(doc)
        used_arrays: list[str] = []

        def _buff():
            mods, used = story_npc.battle_mods(s)
            used_arrays.extend(used)
            return mods

        me = battle.Unit(doc.name or doc.uid[:8] + "…", st.atk, st.defense, hp_cur, st.bao)

        def _protect(place: str, floor: int, enemy: str):
            got = story_npc.try_protect(s, time.time())
            if got:
                return got
            esc = story_npc.consume_escape(s)
            if esc:
                return esc, (f"【{esc}】阵纹骤然亮起，虚空裂开一道门。\n"
                              f"你在{enemy}的攻势落下前被挪出秘境，收获未失，气血尽复。")
            return None

        sess, me, flavor, fled = secret.explore(
            sess, base, me, self.drop_pool, rng, sect_mode=bool(sess.sect_name),
            buff=_buff, protect=_protect,
        )
        if used_arrays:
            flavor = "【阵法·" + "、".join(used_arrays) + "】阵纹复苏，笼罩战场！\n" + flavor
        d = doc.model_copy()
        d.ext["hp"] = me.hp
        d.ext["story"] = s
        d.ext["explore"] = {
            "place": sess.place, "floor": sess.floor, "stones": sess.stones,
            "items": sess.items, "log": sess.log[-30:], "factor": sess.factor,
            "sect_name": sess.sect_name, "boss_kills": sess.boss_kills,
        }
        if not sess.sect_name:  # 每日任务 3：秘境探索计数（宗门秘境不计，对齐原版"沉迷不计入"）
            await self.db.add_daily_secret(doc.uid)
        # 剧情人物邂逅（战败/传送脱身不触发）
        enc = None if fled else story_npc.meet(s, sess.place, sess.floor, time.time(), rng)
        drop_items: dict[str, int] = {}
        if enc:
            flavor = flavor + "\n" + str(enc.get("text") or "")
            if enc.get("exp_pct"):
                gain = int(d.exp * float(enc["exp_pct"]))
                d.exp += gain
                flavor += f"\n修为 +{gain:,}"
            if enc.get("item"):
                drop_items[str(enc["item"])] = 1
                flavor += f"\n（获得【{enc['item']}】×1）"
        if fled:
            if "传送阵" in flavor:
                reason = "传送脱身"
            elif "护道之约" in flavor:
                reason = "护道脱险"
            else:
                reason = "血战脱身"
            d.state = "空闲"
            text = await self._settle_explore(d, sess, reason=reason)
            if drop_items:
                await self.db.add_items(doc.uid, drop_items)
            yield event.plain_result(f"{flavor}\n{text}")
            return
        d.state = "秘境中"
        if drop_items:
            async with self.db.transaction():
                await self.db.save_player(d.model_dump())
                await self.db.add_items(doc.uid, drop_items)
        else:
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
            self._wxl_track(d, "alchemy")  # 问仙令每日任务
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
        async for _r in self._smart(event, "\n".join(lines)):
            yield _r
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
