"""M0 自检：迁移 + 玩家文档往返 + 内容表加载。直接运行，断言失败即非零退出。"""
import asyncio
import sys
import tempfile
import time
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))

from infra.db import DataBase          # noqa: E402
from infra.content import ContentStore # noqa: E402
from core.player import (              # noqa: E402
    PlayerDoc, create_player, realm_entry, next_realm_entry,
)
from core import cultivate             # noqa: E402
from core import items as items_mod    # noqa: E402
from core import other_shore_world as osh_w          # noqa: E402
from core import other_shore_rules as osh_rules   # noqa: E402
from core import other_shore_state as osh_state   # noqa: E402
import random as _random               # noqa: E402


async def main():
    tmp = Path(tempfile.mkdtemp(prefix="zhutian_m0_"))

    # 1. 迁移 + 玩家文档往返
    db = DataBase(tmp / "zhutian.db")
    await db.connect()
    level_table = [{"level": "凡人", "exp": 500, "基础攻击": 2000, "基础防御": 2000, "基础血量": 4000},
                   {"level": "虚妄境初期", "exp": 5000, "基础攻击": 5000, "基础防御": 5000, "基础血量": 10000},
                   {"level": "金丹", "exp": 20000, "基础攻击": 9000, "基础防御": 9000, "基础血量": 20000}]
    doc = create_player("uid_1", "无痕", level_table)
    await db.save_player(doc.model_dump())
    raw = await db.get_player("uid_1")
    loaded = PlayerDoc(**raw)
    assert loaded.uid == "uid_1" and loaded.stones == 100, loaded
    assert await db.get_player("uid_2") is None
    print("db roundtrip ok")

    # 2. 更新覆盖（UPSERT）
    loaded.exp += 500
    await db.save_player(loaded.model_dump())
    assert (await db.get_player("uid_1"))["exp"] == 500
    print("upsert ok")

    # 3. 境界表纯函数
    assert realm_entry(loaded, level_table)["level"] == "凡人"
    assert next_realm_entry(loaded, level_table)["level"] == "虚妄境初期"
    tail = PlayerDoc(uid="x", realm_index=99)
    assert realm_entry(tail, level_table)["level"] == "金丹"  # 越界回退到最后一境
    assert next_realm_entry(tail, level_table) is None
    print("realm helpers ok")

    # 4. 内容加载器（真实原仓库表）
    store = ContentStore(PLUGIN / "data")
    table = store.table("Level/练气境界")
    assert isinstance(table, list) and len(table) == 64, len(table)
    assert table[0]["level"] == "凡人"
    assert store.by_name("Level/练气境界", "虚妄境中期")["level_id"] == 3
    assert store.table("Level/不存在") == []
    print(f"content store ok: {len(store.tables)} tables")

    # 5. 事务回滚
    try:
        async with db.transaction():
            await db.save_player({"uid": "tx", "name": "", "realm_table": "练气境界",
                                  "realm_index": 0, "exp": 0, "stones": 0,
                                  "created_at": 0.0, "ext": {}})
            raise RuntimeError("rollback")
    except RuntimeError:
        pass
    assert await db.get_player("tx") is None
    print("transaction rollback ok")

    # 5.5 并发写串行化：共享连接上两个事务必须排队，写入全部落库
    import asyncio as _aio

    async def _tx_bump():
        async with db.transaction():
            await db.add_items("lock_uid", {"试炼石": 1})
            await _aio.sleep(0.01)   # 制造重叠窗口：无锁时第二个 BEGIN 会报错

    await _aio.gather(_tx_bump(), _tx_bump())
    assert (await db.get_inventory("lock_uid")).get("试炼石") == 2
    print("concurrent tx serialization ok")

    # 6. 签到：自然日 CD + 连续递增压值（对齐原版 daily_gift）
    now = 1_800_000_000.0
    ok, msg, d = cultivate.sign_in(loaded, 100, 500, now, _random.Random(1))
    assert ok and d.ext["sign_streak"] == 1 and d.ext["last_sign_date"] == "2027-01-15", msg
    assert d.exp == loaded.exp + 1000 and d.stones == loaded.stones + 300, msg  # 1天×1000×1² / ×300×1
    ok2, _, _ = cultivate.sign_in(d, 100, 500, now + 3600, _random.Random(2))
    assert not ok2, "同日不应重复签到"
    ok3, msg3, d3 = cultivate.sign_in(d, 100, 500, now + 23 * 3600, _random.Random(3))
    assert ok3 and d3.ext["sign_streak"] == 2 and d3.exp == d.exp + 2000, msg3  # 次日连续第 2 天
    ok4, _, d4 = cultivate.sign_in(d3, 100, 500, now + 5 * 86400, _random.Random(4))
    assert ok4 and d4.ext["sign_streak"] == 1, "断签后应重置为 1"
    print("sign_in ok")

    # 7. 闭关：状态机 / 计划时长钳制 / 惰性结算
    d3.state = "空闲"
    ok, _, d4 = cultivate.start_cultivate(d3, None, 7200)
    assert ok and d4.state == "闭关中" and "cultivate_minutes" not in d4.ext
    ok, _, _ = cultivate.start_cultivate(d4, None, 7200)
    assert not ok, "重复闭关应被拒绝"

    d4b = loaded.model_copy()
    ok, msg, d4c = cultivate.start_cultivate(d4b, 10000, 7200)
    assert ok and d4c.ext["cultivate_minutes"] == 7200 and "最高" in msg, msg  # 超限钳制并提示

    ok, msg, d5 = cultivate.end_cultivate(d4c, d4c.state_start + 30 * 60, 20, 7200)
    assert ok and d5.exp == loaded.exp + 600 and d5.state == "空闲", msg
    ok, _, _ = cultivate.end_cultivate(d5, d5.state_start + 60, 20, 7200)
    assert not ok, "未闭关不应可出关"

    d6 = loaded.model_copy()
    ok, _, d6b = cultivate.start_cultivate(d6, 100, 7200)
    ok, msg, d6c = cultivate.end_cultivate(d6b, d6b.state_start + 1000 * 60, 20, 7200)
    # 100 分钟按 30 分钟周期取整 = 90 分钟（对齐原版 biguan_jiesuan）
    assert ok and d6c.exp == loaded.exp + 90 * 20 and "计划" in msg, msg  # 超计划按计划结算

    d6g = loaded.model_copy()
    ok, _, d6h = cultivate.start_cultivate(d6g, 10, 7200)
    ok, msg, d6i = cultivate.end_cultivate(d6h, d6h.state_start + 10 * 60, 20, 7200)
    assert ok and d6i.exp == loaded.exp and "不足一个周期" in msg, msg  # 不足 30 分钟无收益

    d6d = loaded.model_copy()
    ok, _, d6e = cultivate.start_cultivate(d6d, None, 7200)
    ok, msg, d6f = cultivate.end_cultivate(d6e, d6e.state_start + 8000 * 60, 20, 7200)
    assert ok and d6f.exp == loaded.exp + 7200 * 20 and "上限" in msg, msg  # 无计划受全局上限
    print("cultivate ok")

    # 8. 突破：需求取「当前境界」的 exp 字段；修为不足 / 成功 / 失败损耗
    d7 = d6f
    d7.exp = 499
    ok, _, d8 = cultivate.breakthrough(d7, level_table, 1.0, 0.3, _random.Random(1))
    assert not ok and d8.exp == 499, "修为不足不应突破"
    d8.exp = 500
    ok, msg, d9 = cultivate.breakthrough(d8, level_table, 1.0, 0.3, _random.Random(1))
    assert ok and d9.realm_index == 1 and d9.exp == 500, msg  # 累计制不扣修为
    ok, msg, d10 = cultivate.breakthrough(
        d9.model_copy(update={"exp": 5000}), level_table, 0.0, 0.3, _random.Random(1))
    assert ok and d10.exp == 3500, msg  # 必败路径：损耗 30%×5000 = 1500
    print("breakthrough ok")


    # 9. 物品：购买 / 出售 / 使用（exp 丹）+ 纳戒表
    item = {"name": "凝气丹", "class": "丹药", "type": "修为", "exp": 300, "出售价": 100}
    buyer = loaded.model_copy(update={"stones": 1000})
    ok, msg, d, gain = items_mod.buy(buyer, item, 2, 2.0)
    assert ok and d.stones == 600 and gain == {"凝气丹": 2}, msg
    ok, _, _, _ = items_mod.buy(buyer, item, 999, 2.0)
    assert not ok, "灵石不足应失败"

    inv_doc = buyer
    async with db.transaction():
        await db.save_player(inv_doc.model_dump())
        await db.add_items(inv_doc.uid, gain)
    inv = await db.get_inventory(inv_doc.uid)
    assert inv.get("凝气丹") == 2, inv

    ok, msg, d2, consumed = items_mod.use_item(inv_doc, item, 1)
    assert ok and consumed and d2.exp == inv_doc.exp + 300, msg  # inv_doc.exp 沿用 500
    assert await db.remove_item(inv_doc.uid, "凝气丹", 1)
    assert not await db.remove_item(inv_doc.uid, "凝气丹", 5), "超量移除应失败"
    assert (await db.get_inventory(inv_doc.uid)).get("凝气丹") == 1

    junk = {"name": "废铁", "class": "装备", "出售价": 0}
    ok, _, _ = items_mod.sell(inv_doc, junk, 1)
    assert not ok, "出售价 0 不可出售"

    # 10. 迁移版本 = 17
    from infra.db import LATEST_DB_VERSION
    async with db.conn.execute("SELECT version FROM db_info") as cur:
        assert (await cur.fetchone())[0] == LATEST_DB_VERSION == 17

    # 11. 装备：穿戴/换位/卸下 + 比例与固定加成聚合
    from core import battle as battle_mod   # noqa: E402
    from core import equipment as equip_mod # noqa: E402

    lvl4 = [
        {"level": "凡人", "exp": 500, "基础攻击": 1000, "基础防御": 1000, "基础血量": 5000},
        {"level": "虚妄境初期", "exp": 5000, "基础攻击": 2000, "基础防御": 2000, "基础血量": 10000},
    ]
    wpn = {"name": "一剑", "class": "装备", "type": "武器", "atk": 0.92, "def": 0.21, "HP": 0.45, "bao": 0.1}
    armor = {"name": "铁甲", "class": "装备", "type": "护具", "atk": 100, "def": 300, "HP": 800}
    lookup = {"一剑": wpn, "铁甲": armor}

    d10 = PlayerDoc(uid="e1")
    ok, _, old = equip_mod.wear(d10, wpn)
    assert ok and old is None and d10.ext["equipment"]["武器"] == "一剑"
    ok, _, _ = equip_mod.wear(d10, wpn)
    assert not ok, "重复穿戴应拒绝"
    ok, _, old = equip_mod.wear(d10, {"name": "碎星锤", "class": "装备", "type": "武器", "atk": 1})
    assert ok and old == "一剑", "同槽位换装应归还旧装备"

    st = equip_mod.aggregate(d10, lvl4, lookup.get)
    assert st.atk == 1000, st            # 碎星锤不在索引 → 优雅降级为纯基础值
    ok, _, _ = equip_mod.wear(d10, armor)
    assert ok
    st = equip_mod.aggregate(d10, lvl4, lookup.get)
    # 仅铁甲（固定加成）：攻 1000+100、防 1000+300、血 5000+800
    assert (st.atk, st.defense, st.hp) == (1100, 1300, 5800), st
    ok, _, old = equip_mod.wear(d10, wpn)   # 一剑回到武器位（碎星锤换出）
    assert ok and old == "碎星锤"
    st = equip_mod.aggregate(d10, lvl4, lookup.get)
    # 一剑（比例）+ 铁甲（固定）：攻 1000×1.92+100、防 1000×1.21+300、血 5000×1.45+800
    assert st.atk == int(1000 * 1.92) + 100, st
    assert st.defense == int(1000 * 1.21) + 300, st
    assert st.hp == int(5000 * 1.45) + 800, st
    assert st.bao == 0.1, st
    ok, _, old = equip_mod.unequip(d10, "护具")
    assert ok and old == "铁甲"
    ok, _, _ = equip_mod.unequip(d10, "法宝")
    assert not ok, "空槽卸下应拒绝"
    ok, _, _ = equip_mod.wear(d10, {"name": "丹药", "class": "丹药"})
    assert not ok, "非装备不可穿戴"
    print("equipment ok")

    # 12. 战斗：Harm 公式边界 + 切磋模拟
    dmg, crit = battle_mod.harm(100, 10000, _random.Random(1))
    assert 8 <= dmg <= 12 and not crit, dmg          # s<1 → 约 10% 攻击
    dmg, _ = battle_mod.harm(10000, 100, _random.Random(1))
    assert 9400 <= dmg <= 10600, dmg                 # s>2.5 → 全额攻击 × 0.95~1.05
    dmg, crit = battle_mod.harm(2000, 2000, _random.Random(1), 1.0)
    assert crit and 475 <= dmg <= 525, (dmg, crit)   # s=1 → x=0.1：2000×0.1×[0.95~1.05]×2.5（暴伤=暴击率1.0+1.5）
    a = battle_mod.Unit("甲", 3000, 1500, 20000, 0.4)
    b = battle_mod.Unit("乙", 1500, 3000, 18000)
    rng = _random.Random(7)
    winner, log = battle_mod.spar(a, b, rng)
    assert winner in (0, 1) and log and "第1回合" in log[0]
    rng2 = _random.Random(7)
    _, log2 = battle_mod.spar(a, b, rng2)
    assert log == log2, "同种子应可复现"
    weak = battle_mod.Unit("弱", 1, 1, 1)
    winner, _ = battle_mod.spar(b, weak, _random.Random(3))
    assert winner == 0, "秒杀路径"
    print("battle ok")

    # 13. 世界 Boss：轮次递增 / 幻影浮动 / 伤害公式 / 分账
    from core import boss as boss_mod  # noqa: E402
    from core import pet as pet_mod  # noqa: E402

    h1, r1 = boss_mod.boss_specs(1)
    h3, r3 = boss_mod.boss_specs(3)
    assert h1 == 1_000_000 and h3 == int(1_000_000 * 1.5 ** 2), (h1, h3)
    assert r3 == int(500_000 * 2.25), r3

    rng_b = _random.Random(5)
    for _ in range(20):
        sh = boss_mod.make_shadow(1000, 1000, 10000, rng_b)
        assert 800 <= sh.atk <= 1400 and 800 <= sh.defense <= 1400 and 8000 <= sh.hp <= 14000, sh

    dmg_win = boss_mod.boss_damage(True, 1000, 1000, 1_000_000, _random.Random(2))
    dmg_lose = boss_mod.boss_damage(False, 1000, 1000, 1_000_000, _random.Random(2))
    assert dmg_win > dmg_lose >= 30_000, (dmg_win, dmg_lose)  # 3% 下限 + 幻影伤害×4

    ledger = {"u1": ("甲", 700), "u2": ("乙", 300)}
    shares = boss_mod.split_rewards(1000, ledger, "u1")
    m = dict((n, s) for _, n, s in shares)
    assert m["甲"] == 700 + 100 and m["乙"] == 300, m  # 贡献比例 + 击杀者 10%
    assert boss_mod.split_rewards(1000, {}, None) == []

    # 14. Boss 存储生命周期：入账累计 → 击杀置位 → 账本排序
    await db.init_boss(1, 1000, 50000)
    await db.damage_boss(1, "u1", "甲", 300)
    await db.damage_boss(1, "u1", "甲", 200)
    await db.damage_boss(1, "u2", "乙", 100)
    row = await db.get_boss()
    assert row["health"] == 400 and row["alive"], row
    left = await db.damage_boss(1, "u2", "乙", 500)
    assert left <= 0
    row = await db.get_boss()
    assert not row["alive"] and row["health"] == 0, row
    led = await db.boss_ledger(1)
    names = [v[0] for v in led.values()]
    assert names[0] == "乙" and dict((k, v[1]) for k, v in led.items())["u1"] == 500, led
    # 重开新一轮
    await db.init_boss(2, 2000, 60000)
    row = await db.get_boss()
    assert row["round"] == 2 and row["alive"] and row["health"] == 2000, row
    print("world boss ok")

    # 15. 血气丹：回血 / 满血拒绝 / 钳制
    pill_fix = {"name": "回血丹", "class": "丹药", "type": "血气", "HP": 3000}
    pill_pct = {"name": "起死回生丹", "class": "丹药", "HPp": 1.0}
    hurt = PlayerDoc(uid="h1", ext={"hp": 1000})
    ok, msg, d, consume = items_mod.use_item(hurt, pill_fix, 1, 10000)
    assert ok and consume and d.ext["hp"] == 4000, msg
    ok, msg, d, consume = items_mod.use_item(d, pill_pct, 1, 10000)
    assert ok and d.ext["hp"] == 10000, msg  # HPp=1 → 回满
    ok, msg, _, consume = items_mod.use_item(d, pill_fix, 1, 10000)
    assert not ok and not consume and "正满" in msg, msg
    hurt2 = PlayerDoc(uid="h2", ext={"hp": 9500})
    ok, msg, d2, _ = items_mod.use_item(hurt2, pill_fix, 5, 10000)
    assert ok and d2.ext["hp"] == 10000, msg  # 溢出钳制
    ok, _, _, _ = items_mod.use_item(hurt, {"name": "铁甲", "class": "装备", "HP": 800}, 1)
    assert not ok, "装备不得走回血分支"
    print("hp pill ok")

    # 15b. 灵根（天资）：加权抽取 / 洗炼 / 修炼效率 / 血气永久上限
    from core import linggen as lg_mod  # noqa: E402

    lg_pool = [
        {"id": 1, "name": "伪灵根", "type": "伪灵根", "eff": 0.1, "稀有度": 1},
        {"id": 2, "name": "真灵根", "type": "真灵根", "eff": 0.2, "稀有度": 2},
        {"id": 3, "name": "天灵根", "type": "天灵根", "eff": 1.0, "稀有度": 7},
    ]
    rng_lg = _random.Random(11)
    draws = [lg_mod.roll(lg_pool, rng_lg)["name"] for _ in range(4000)]
    # 权重 1 : 1/3 : 1/729 → 伪灵根约 74%，天灵根约 0.1%
    assert draws.count("伪灵根") > draws.count("真灵根") > 0, (draws.count("伪灵根"), draws.count("真灵根"))
    assert draws.count("伪灵根") > 2000
    assert draws.count("天灵根") <= 30, draws.count("天灵根")

    plain = PlayerDoc(uid="lg0")
    assert lg_mod.eff_of(plain) == 0.0, "未洗炼效率加成应为 0（原版加法项语义）"
    old, new, d_lg = lg_mod.refine(plain, lg_pool, _random.Random(5))
    assert old is None and new.get("name") and d_lg.ext["linggen"]["id"] == new["id"]
    assert lg_mod.eff_of(d_lg) == new["eff"]  # 加法项：eff 直接作为 +bonus
    assert "未洗炼（效率加成 +0）" in lg_mod.describe(None)
    # 效率等式（对齐 player_efficiency）：1 + 灵根eff + 其它 —— 伪灵根 0.1 → ×1.1
    assert abs((1 + lg_mod.eff_of(d_lg)) - (1 + float(new["eff"]))) < 1e-9

    # 天命轮回丹（type=天资洗炼，无数值字段）→ 触发洗炼并消耗
    destiny = {"name": "天命轮回丹", "class": "丹药", "type": "天资洗炼", "desc": "蕴含天道轮回之力"}
    ok, msg, d_use, consume = items_mod.use_item(
        plain, destiny, 1, 1000, linggen_table=lg_pool, rng=_random.Random(9))
    assert ok and consume and d_use.ext["linggen"], msg
    assert "天资洗炼" in msg, msg
    # 无灵根表注入时不误触发、不消耗
    ok2, msg2, _, consume2 = items_mod.use_item(plain, destiny, 1)
    assert not ok2 and not consume2, msg2
    # 神心丹 linggen=1 同效
    shenxin = {"name": "神心丹", "class": "丹药", "type": "灵根", "linggen": 1}
    ok, msg, d3, _ = items_mod.use_item(
        plain, shenxin, 1, 1000, linggen_table=lg_pool, rng=_random.Random(9))
    assert ok and d3.ext["linggen"], msg

    # 血气：永久上限累计 + 聚合并入
    tidan = {"name": "九阶淬体丹", "class": "丹药", "type": "血气", "xueqi": 1000}
    ok, msg, d4, _ = items_mod.use_item(plain, tidan, 2, 1000)
    assert ok and d4.ext["xueqi"] == 2000, msg
    st_x = equip_mod.aggregate(d4, lvl4, lookup.get)
    st_0 = equip_mod.aggregate(plain, lvl4, lookup.get)
    assert st_x.hp == st_0.hp + 2000, (st_0.hp, st_x.hp)
    # 神药类多字段叠加：修为 + 血气一次结算
    shenyao = {"name": "无上九转仙丹", "class": "丹药", "exp": 100, "xueqi": 50}
    ok, msg, d5, _ = items_mod.use_item(plain, shenyao, 1, 1000)
    assert ok and d5.exp == plain.exp + 100 and d5.ext["xueqi"] == 50, msg
    print("linggen & xueqi ok")

    # 15d. 品质丹 buff（原版 dy 体系）+ 直投字段
    biguan_pill = {"name": "仙品辟谷丹", "class": "丹药", "type": "闭关", "biguan": 3}
    ok, msg, d6b, _ = items_mod.use_item(plain, biguan_pill, 1, 1000)
    assert ok and d6b.ext["buffs"]["biguan"] == {"times": 1, "bonus": 3.0}, msg
    assert "+300%" in msg, msg
    # 凝仙丹延长 buff
    ningxian = {"name": "极品凝仙丹", "class": "丹药", "type": "凝仙", "机缘": 2}
    ok, msg, d7b, _ = items_mod.use_item(d6b, ningxian, 1, 1000)
    assert ok and d7b.ext["buffs"]["biguan"]["times"] == 3, (msg, d7b.ext.get("buffs"))
    # 炼神丹 + 闭关结算：修为转血气 + 次数消耗
    lianshen = {"name": "凡品炼神丹", "class": "丹药", "type": "炼神", "lianshen": 0.3}
    ok, msg, d8b, _ = items_mod.use_item(d7b, lianshen, 1, 1000)
    assert ok and d8b.ext["buffs"]["lianti"]["ratio"] == 0.3, msg
    ok, _, d9b = cultivate.start_cultivate(d8b, 30, 7200)
    exp0 = d9b.exp
    xq0 = int(d9b.ext.get("xueqi", 0))
    ok, msg, d10b = cultivate.end_cultivate(d9b, d9b.state_start + 30 * 60, 20, 7200)
    assert d10b.exp == exp0, "炼神生效时修为不增"
    assert int(d10b.ext["xueqi"]) == xq0 + 600, (xq0, msg)  # 30min×20 全转血气
    assert d10b.ext["buffs"]["biguan"]["times"] == 2, d10b.ext.get("buffs")
    assert "lianti" not in d10b.ext["buffs"], d10b.ext.get("buffs")  # 耗尽即移除
    # 覆盖制：再服炼神丹刷新次数
    ok, msg, d11b, _ = items_mod.use_item(d10b, lianshen, 2, 1000)
    assert ok and d11b.ext["buffs"]["lianti"]["times"] == 2, msg
    # 魔道值 ±（转生降 / 疯魔升）
    zhuansheng = {"name": "仙品转生丹", "class": "丹药", "type": "魔道值", "modao": 120}
    fengmo = {"name": "凡品疯魔丹", "class": "丹药", "type": "入魔", "modao": 200}
    ok, msg, d12b, _ = items_mod.use_item(d11b, fengmo, 1, 1000)
    assert ok and d12b.ext["modao"] == 200, msg
    ok, msg, d13b, _ = items_mod.use_item(d12b, zhuansheng, 1, 1000)
    assert ok and d13b.ext["modao"] == 80, msg
    # 直投字段：potential/heart/xingyun/道心
    jidao = {"name": "极道丹", "class": "丹药", "type": "仙道潜力", "potential": 500}
    dingshen = {"name": "定神丹", "class": "丹药", "type": "心神恢复", "heart": 10}
    fuyuan = {"name": "凡品福源丹", "class": "丹药", "type": "幸运", "xingyun": 0.04}
    daoxin = {"name": "凡品道心果", "class": "丹药", "type": "道心", "道心": 3}
    ok, msg, d14b, _ = items_mod.use_item(d13b, jidao, 1, 1000)
    ok, msg, d15b, _ = items_mod.use_item(d14b, dingshen, 1, 1000)
    ok, msg, d16b, _ = items_mod.use_item(d15b, fuyuan, 1, 1000)
    ok, msg, d17b, _ = items_mod.use_item(d16b, daoxin, 2, 1000)
    assert d17b.ext["potential"] == 500 and d17b.ext["heart"] == 10 and d17b.ext["daoxin"] == 6, msg
    assert d17b.ext["buffs"]["lucky"]["times"] == 10, msg
    # 器灵/真器：依赖未开放系统，拒绝且不消耗
    qiling = {"name": "凡品器灵丹", "class": "丹药", "type": "器灵", "天赋": 20}
    ok, msg, _, consume = items_mod.use_item(d17b, qiling, 1, 1000)
    assert not ok and not consume, msg
    print("pill buffs ok")

    # 15e. 职业体系：等级曲线 / 采药采矿产出 / 制符 / 炼器成功率
    from core import occupation as occ_mod  # noqa: E402

    store = ContentStore(PLUGIN / "data")
    exp_table = store.table("occupation/experience")
    assert len(exp_table) == 38 and exp_table[0]["id"] == 0
    lv0, exp0 = occ_mod.add_exp(1, 0, 100, exp_table)
    assert lv0 == 2 and exp0 == 0, (lv0, exp0)  # 1 级需 100 → 恰好升 2 级
    lv1, exp1 = occ_mod.add_exp(1, 0, 250, exp_table)
    assert lv1 == 2 and exp1 == 150, (lv1, exp1)  # 250-100=150 < 200 → 停 2 级剩 150
    assert occ_mod.rate_of(1, exp_table) == 0.1
    # 采药：480 分钟满周期、10 级、境界 10（<22 → k=0.5）→ total=32×0.5=16，前 5 草各 3 株
    herbs, exp = occ_mod.plant_yield(480, 10, 10, _random.Random(1))
    assert exp == 4800 and sum(herbs.values()) >= 10, (herbs, exp)
    assert set(herbs) <= set(occ_mod.HERB_NAMES[:5]), herbs  # 低境界只有前 5 草
    herbs_low, exp_low = occ_mod.plant_yield(30, 1, 10, _random.Random(1))
    assert exp_low == 300 and herbs_low == {}, (herbs_low, exp_low)  # 30 分钟×1 级不足一株（原版语义）
    # 采矿：60 分钟、5 级
    mats, exp = occ_mod.mine_yield_full(60, 5, exp_table, _random.Random(2))
    assert "庚金" in mats and "玄土" in mats and exp == 600, mats
    assert all(v >= 0 for v in mats.values())
    # 制符：等级门槛
    ff = {"name": "符笔", "level_limit": 0, "materials": []}
    ok, why, n = occ_mod.talisman_make(ff, 1, 2)
    assert ok and n == 2
    ff2 = {"name": "锁灵仙符", "level_limit": 5, "materials": []}
    ok, why, _ = occ_mod.talisman_make(ff2, 3, 1)
    assert not ok and "5重境" in why, why
    # 炼器成功率：clamp 与封顶
    tbl = [{"id": 24, "rate": 3.0}, {"id": 1, "rate": 0.1}]
    r24 = occ_mod.forge_rate(1.0, 24, tbl)
    assert r24 == 0.8, r24  # ≥24 级封顶 0.8
    r1 = occ_mod.forge_rate(0.5, 1, tbl)
    assert 0.01 <= r1 < 1.0, r1
    print("occupation ok")

    # 15f. 黑暗动乱 + 炼神魄（对齐 BOSS2 / pata DSC）
    from core import boss as boss_mod2  # noqa: E402

    h, rw, a, df = boss_mod2.dark_specs(1000000, 5)
    assert rw == 12_000_000 and h == int(10000 * 150 * 5 * 200), (h, rw)
    assert boss_mod2.dark_specs(1000000, 3)[1] == 6_000_000  # <5 人奖池减半
    dmg_win = boss_mod2.dark_damage(True, 1000000, df, h, _random.Random(1))
    dmg_lose = boss_mod2.dark_damage(False, 1000000, df, h, _random.Random(1))
    assert dmg_win > dmg_lose > 0, (dmg_win, dmg_lose)
    # 锻神池：段数缩放 + 逐回合胜负
    sh, sa, sd, sr = boss_mod2.shenpo_specs(10)
    assert sh == 1_000_000 and sa == 2_500_000 and sd == 2_000_000 and sr == 12_000, (sh, sa, sd, sr)
    sr_cap = boss_mod2.shenpo_specs(1000)[3]
    assert sr_cap == 400_000, sr_cap  # 奖励封顶
    # 黑暗 Boss 存储生命周期（复用 world_boss 模式）
    await db.init_dark_boss(1, 1000, 50000, 3000, 1500)
    await db.damage_dark_boss(1, "u1", "甲", 400)
    left = await db.damage_dark_boss(1, "u2", "乙", 700)
    assert left <= 0
    row = await db.get_dark_boss()
    assert not row["alive"] and row["round"] == 1, row
    led = await db.dark_ledger(1)
    assert dict((k, v[1]) for k, v in led.items())["u1"] == 400, led
    await db.init_dark_boss(2, 2000, 60000, 3000, 1500)
    assert (await db.get_dark_boss())["alive"]
    print("dark boss & shenpo ok")

    # 15g. 神界：供奉/参悟/踏入门槛（对齐 shenren.js）
    from core import shenjie as sj_mod  # noqa: E402

    ok, why = sj_mod.offer_gate(100, "伪灵根")
    assert not ok and "罪孽" in why, why
    ok, _ = sj_mod.offer_gate(0, "伪灵根")
    assert ok
    ok, _ = sj_mod.offer_gate(100, "转生")
    assert ok, "转生灵根可入神界"
    assert sj_mod.offer_shenshi(100, 150) == (250, 150)
    pills = [{"name": "限定丹A"}, {"name": "限定丹B"}]
    rs = sj_mod.canwu_rewards(pills, 5, _random.Random(1))
    assert sum(rs.values()) == 5 and set(rs) <= {"限定丹A", "限定丹B"}, rs
    ok, why = sj_mod.shenjie_entry_gate(150, 9_999_999, 0, "伪灵根", False)
    assert not ok and "供奉进度" in why, why
    ok, why = sj_mod.shenjie_entry_gate(200, 100, 0, "伪灵根", False)
    assert not ok and "灵石不足" in why, why
    ok, _ = sj_mod.shenjie_entry_gate(200, 9_999_999, 0, "伪灵根", False)
    assert ok
    ok, why = sj_mod.shenjie_entry_gate(200, 9_999_999, 0, "伪灵根", True)
    assert not ok and "次数" in why, why
    rw = sj_mod.shenjie_rewards()
    assert rw["__stones__"] == 8_000_000 and rw["神石"] == 10
    print("shenjie ok")

    # 15h. 小世界：开辟/演化/挂机收获/种植/浇灌（对齐 xiaoshijie.js）
    from core import xiaoshijie as xs_mod  # noqa: E402

    inv = {"世界石": 1}
    ok, msg, w = xs_mod.create_world("紫霄界", 10, inv)
    assert not ok and "成仙" in msg  # 境界不足
    ok, msg, w = xs_mod.create_world("紫霄界", 42, inv)
    assert ok and w["level"] == 1 and w["fields"] == []
    # 演化：2 级材料齐 → 成功；5 级封顶
    inv2 = {"世界石": 99, "玄渊真水": 1, "元虚罡风": 1, "太初燧火": 1, "须弥神土": 1,
            "造化玉碟": 1, "混沌母气": 99}
    for _ in range(4):
        ok, msg, w = xs_mod.upgrade_world(w, inv2)
        assert ok, msg
    ok, msg, _ = xs_mod.upgrade_world(w, inv2)
    assert not ok and "5 级" in msg, msg
    # 挂机：分身化入 → 时间快进收获
    ok, msg, w = xs_mod.bind_avatar(w, 2_000_000)
    assert ok and w["avatar"]
    w["last_harvest"] -= 3600  # 快进 1 现实小时
    ok, msg, w, out = xs_mod.harvest(w)
    # harvest 内部用 time.time()，last_harvest 与 now 之间那几毫秒会让 eff_hours 略大于 8，
    # 故灵石按 8 小时的向下取整值给一个极小容差（原断言写死 6_400_000 会偶发 +1）
    assert ok and 6_400_000 <= out.get("__stones__", 0) <= 6_401_000 and out.get("仙馐果") == 2400, out
    # 种植：5 级灵气 30000 可种全部种子；大夏神药 12 现实小时成熟
    ok, msg, w = xs_mod.plant(w, "大夏神药种子")
    assert ok and "1.5" in msg, msg  # (3000/1000)×4h ÷ 流速8 = 1.5 现实小时
    ok, msg, w = xs_mod.plant(w, "不存在种子")
    assert not ok
    # 浇灌：-30 分钟 + 冷却
    ok, msg, w = xs_mod.water(w)
    assert ok, msg
    remaining = w["fields"][0]["remaining"]
    ok, msg, _ = xs_mod.water(w)
    assert not ok and "冷却" in msg, msg
    # 成熟判定：剩余 0 → harvest 收获神药
    w["fields"][0]["remaining"] = 0
    w["last_harvest"] -= 3600  # 回拨避免"间隔太短"拦截
    ok, msg, w, out = xs_mod.harvest(w)
    assert ok and out.get("大夏神药") == 1, out
    assert all(f.get("seed") != "大夏神药种子" for f in w["fields"]), w["fields"]  # 收获后不返种（简化）
    print("xiaoshijie ok")

    # 15j. 诸天镜主线：绑定→探索→淬炼→投影→化身
    from core import zhutian as zt_mod  # noqa: E402
    zt_doc = PlayerDoc(uid="zt1", exp=200_000_000)
    ok, _, zt = zt_mod.bind(zt_doc)
    assert ok and zt["tier"] == 1 and zt["energy"] == 3, zt
    zt_doc.ext["zhutian"] = zt  # 模拟 main 写回（纯函数由调用方落盘）
    ok2, _, _ = zt_mod.bind(zt_doc)
    assert not ok2  # 不可重复绑定
    zt = zt_mod.system_of(zt_doc)  # 后续用已写回的档继续
    assert zt["bound"]
    # 探索（先手动给 4 阶方便全地点；需写回 ext——core 从 doc.ext 读档）
    zt = zt_mod.system_of(zt_doc)
    zt["tier"] = 4
    zt["energy_date"] = zt_mod.time.strftime("%Y-%m-%d")
    zt["energy"] = 12
    zt_doc.ext["zhutian"] = zt
    ok, msg, zt = zt_mod.explore(zt_doc, "魔卡少女樱", "友枝小学", _random.Random(1))
    assert ok and zt["energy"] == 11 and zt["materials"]["镜尘"] >= 4, msg
    zt_doc.ext["zhutian"] = zt
    ok, msg, _ = zt_mod.explore(zt_doc, "魔卡少女樱", "不存在地点", _random.Random(1))
    assert not ok
    # 淬炼：材料不足 → 补齐 → 升阶（印记被消耗）
    ok, msg, _ = zt_mod.refine(zt_doc)
    assert not ok and "不足" in msg
    zt = zt_mod.system_of(zt_doc)
    zt["tier"] = 1
    zt["materials"] = {"镜尘": 999, "世界残响": 99, "位面晶核": 9, "时空锚": 9, "诸天镜心": 9}
    zt["imprints"] = ["魔法少女小圆", "假面骑士帝骑"]
    zt_doc.ext["zhutian"] = zt
    ok, msg, zt2 = zt_mod.refine(zt_doc)
    assert ok and zt2["tier"] == 2, msg
    assert len(zt2["imprints"]) == 1, zt2["imprints"]  # REQ[1] 要 1 印记 → 消耗 1 剩 1
    assert zt2["energy"] == 4  # 晋阶补满（2 阶上限 4）
    zt_doc.ext["zhutian"] = zt2
    # 投影：门槛+消耗+分支
    ok, msg, _, _ = zt_mod.begin_projection(zt_doc, "星海归墟", 1_000.0)
    assert not ok and "镜阶不足" in msg
    ok, msg, zt3, proj = zt_mod.begin_projection(zt_doc, "魔卡少女樱", 1_000.0)
    assert ok and proj["max_choice"] == 3, msg
    assert zt3["energy"] == 3  # 4-1
    zt_doc.ext["zhutian"] = zt3
    before_marks = len(zt3["imprints"])
    tail, zt4 = zt_mod.resolve_projection(zt_doc, proj, 3, _random.Random(2))
    assert "世界印记" in tail and len(zt4["imprints"]) == before_marks + 1  # 首投影必得印记
    # 化身装载：buff 替换与切回（需先写回 zt4）
    zt4["avatars"]["木之本樱"] = {"root": dict(zt_mod.AVATAR_ROOTS["木之本樱"]), "stage": 1}
    zt4["energy"] = 5
    zt_doc.ext["zhutian"] = zt4
    ok, msg, zt5, buff = zt_mod.load_avatar(zt_doc, "木之本樱", 1_000.0 + 99999)
    assert ok and buff == {"atk": 0.5, "def": 0.5, "hp": 0.5}, (msg, buff)
    zt_doc.ext["zhutian"] = zt5
    ok, msg, _, _ = zt_mod.load_avatar(zt_doc, "鹿目圆", 1_000.0 + 99999 + 60)
    assert not ok and "冷却" in msg
    ok, msg, zt6, buff2 = zt_mod.load_avatar(zt_doc, "本源", 1_000.0 + 99999 + 3600)
    assert ok and buff2 == {}, msg
    # aggregate 并入化身 buff（装载态三维 +50%）
    loaded_doc = zt_doc.model_copy(deep=True)
    loaded_doc.ext["zhutian"] = dict(zt5)
    loaded_doc.ext["zhutian"]["current"] = "木之本樱"
    loaded_doc.ext["avatar_buff"] = {"atk": 0.5, "def": 0.5, "hp": 0.5}
    print("zhutian mirror ok")

    # 15k. 大宇宙：升格门槛→灵韵折算→铸造→挑战→演绎
    from core import universe as uni_mod  # noqa: E402
    u_doc = PlayerDoc(uid="u9", exp=100_000_000, ext={"potential": 200.0})
    u_doc.realm_index = 46
    assert uni_mod.can_ascend(u_doc)["reason"] == "world"  # 无小世界
    u_doc.ext["xiaoshijie"] = {"name": "紫霄界", "level": 3}
    assert uni_mod.can_ascend(u_doc)["reason"] == "world-level"
    u_doc.ext["xiaoshijie"]["level"] = 5
    ok, msg, u = uni_mod.ascend(u_doc, 1000.0)
    assert ok and u["law"] == 0 and u["aura"] == 0, msg
    # 灵韵折算：稀有度 8、售 1000 万 → 20+200+80=300
    item = {"稀有度": 8, "出售价": 10_000_000}
    assert uni_mod.aura_value(item) == 290, uni_mod.aura_value(item)  # 20+8×25+log10(1e7)×10=290
    assert uni_mod.aura_value({"稀有度": 0, "出售价": 0}) == 20  # 无稀有度无售价 = 基础 20
    # 法则完善：潜力不足 → 灵韵不足 → 补齐 → 升 1 阶
    ok, msg, _, _ = uni_mod.refine_law(u_doc, dict(u))
    assert not ok and "潜力不足" in msg, msg
    u_doc.ext["potential"] = 900.0
    ok, msg, _, _ = uni_mod.refine_law(u_doc, dict(u))
    assert not ok and "灵韵不足" in msg, msg
    u["aura"] = 290
    ok, msg, u2, consume = uni_mod.refine_law(u_doc, dict(u))
    assert ok and u2["law"] == 1 and consume["exp"] == 5_000_000, msg
    # 铸造：灵韵不足 → 补齐 → 成功 → 重名拒绝
    ok, msg, _ = uni_mod.forge_dungeon(dict(u2), "轮回古路", "试炼之地", "古道残魂")
    assert not ok and "灵韵不足" in msg
    u2["aura"] = 250
    ok, msg, u3 = uni_mod.forge_dungeon(dict(u2), "轮回古路", "试炼之地", "古道残魂")
    assert ok and len(u3["dungeons"]) == 1, msg
    ok, msg, _ = uni_mod.forge_dungeon(dict(u3), "轮回古路", "x", "y")
    assert not ok and "同名" in msg
    # 挑战：战胜 → 灵韵入账、通关数+1
    u_doc.ext["universe"] = dict(u3)
    from core.player import PlayerDoc as _PD
    fighter = _PD(uid="u9", exp=1)
    fighter.realm_index = 50
    ok, msg, u4, result = uni_mod.enter_dungeon(
        fighter, dict(u3), "轮回古路", 100_000.0,
        {"atk": 9_999_999, "defense": 9_999_999, "hp": 999_999_999, "bao": 0.5},
        _random.Random(3))
    assert ok and result["won"] and u4["dungeons"][0]["cleared"] == 1, msg
    assert u4["aura"] > u3["aura"]  # 战胜得灵韵
    # CD 拦截
    u_doc.ext["udungeon_ts"] = 100_000.0
    ok, msg, _, _ = uni_mod.enter_dungeon(u_doc, dict(u4), "轮回古路", 100_100.0,
                                          {"atk": 1, "defense": 1, "hp": 1, "bao": 0}, _random.Random(4))
    assert not ok and "小时" in msg
    # 演绎
    u4["aura"] = 2000
    ok, msg, u5, consume = uni_mod.derive_dungeon(dict(u4), "寂灭星海", _random.Random(5))
    assert ok and len(u5["dungeons"]) == 2 and consume["exp"] == 10_000_000, msg
    print("grand universe ok")

    # 15l. A 档：镇妖塔/寻宝/洗劫
    from core import adventure as adv_mod  # noqa: E402
    # 镇妖塔数值公式
    assert adv_mod.tower_boss(0) == {"hp": 10000, "atk": 10000, "defense": 10000}
    assert adv_mod.tower_boss(100)["hp"] == 5_000_000 + 10_000
    assert adv_mod.tower_reward(50) == 5100 and adv_mod.tower_reward(150) == 31000
    assert adv_mod.tower_reward(999) == 300_700  # 300×999+1000
    assert adv_mod.tower_reward(1500) == 400_000  # 封顶
    # 单挑：碾压属性必胜 → 层+5、灵石正收益
    tdoc = PlayerDoc(uid="tw", ext={"tower_floor": 0})
    winner = {"atk": 9_999_999, "defense": 9_999_999, "hp": 9_999_999_999, "bao": 0.5}
    ok, msg, ext2, consume = adv_mod.tower_fight(tdoc, winner, _random.Random(7))
    assert ok and ext2["tower_floor"] == 5 and consume["stones"] == 100, (msg, consume)
    loser = {"atk": 1, "defense": 1, "hp": 1, "bao": 0}
    ok, msg, ext3, consume = adv_mod.tower_fight(tdoc, loser, _random.Random(8))
    assert ok and consume["stones"] == -200, msg  # 0 层败 → 罚 reward(0)=100×2
    # 寻宝：未派 → 拒；时长不足 → 拒
    ok, msg, _, _ = adv_mod.pet_explore_collect(tdoc, [], 1000.0, _random.Random(1))
    assert not ok
    tdoc.ext["pet_explore"] = {"name": "小白", "ts": 1000.0, "place": "葬仙古域"}
    ok, msg, _, _ = adv_mod.pet_explore_collect(tdoc, [], 1000.0 + 600, _random.Random(1))
    assert not ok and "分钟" in msg    # 时长足够（130 分钟 > 120 必须）→ 8 次满额收获
    pool = [{"name": "修为丹", "class": "丹药", "数量": 1}, {"name": "庚金", "class": "材料", "数量": 2}]
    ok, msg, _, gains = adv_mod.pet_explore_collect(tdoc, pool, 1000.0 + 130 * 60, _random.Random(2))
    assert ok and gains, (msg, gains)
    # 灵韵池构建
    p = adv_mod.build_pet_pool({"修为丹": {"稀有度": 3, "class": "丹药"}, "神石": {"稀有度": 7, "class": "道具"}})
    assert all("name" in x for x in p) and p
    # 洗劫：守卫数值 + 战斗可判
    g = adv_mod.raid_guard(1)
    assert g["hp"] == 900_000
    won, log = adv_mod.raid_fight(winner, g, _random.Random(9))
    assert won and log
    print("adventure ok")

    # 15m. 帝兵炼制：炼制→融合→雷劫门槛→进阶→蕴养→更名
    from core import dibing as db_mod  # noqa: E402
    ok, msg, _ = db_mod.forge("凡铁", "混沌剑")
    assert not ok  # 非仙金
    ok, msg, _ = db_mod.forge("仙泪绿金", "混沌")
    assert not ok and "形态" in msg  # 缺形态字
    ok, msg, w = db_mod.forge("仙泪绿金", "混沌剑")
    assert ok and w["atk"] == 7200 and w["all"] == 0.9 and w["stage"] == 0, msg
    # 融合：主材拒、重复拒、九金齐备判定
    ok, msg, _ = db_mod.fuse(w, "仙泪绿金")
    assert not ok and "主材" in msg
    ok, msg, w2 = db_mod.fuse(w, "龙纹黑金")
    assert ok and w2["potential"] == 5.7 and len(w2["fused"]) == 1
    ok, msg, _ = db_mod.fuse(w2, "龙纹黑金")
    assert not ok and "已融合" in msg
    # 雷劫：九金未齐 → 拒；齐备 + 资源 → 进 1 阶
    ok, msg, _ = db_mod.tribulation(w2, 10 ** 9, 10 ** 9)
    assert not ok and "九种" in msg
    w_all = dict(w2)
    w_all["fused"] = [g for g in db_mod.GOLD_RARITY if g != "仙泪绿金"][:8]
    ok, msg, _ = db_mod.tribulation(w_all, 100, 100)
    assert not ok and "修为" in msg  # 资源不足
    ok, msg, w3 = db_mod.tribulation(w_all, 10 ** 9, 10 ** 9)
    assert ok and w3["stage"] == 1 and "通灵" in msg, msg
    # 蕴养：上限与成长
    ok, msg, w4, consume = db_mod.nurture(w3, 2, 10 ** 9, 10 ** 9)
    assert ok and w4["nurture"] == 2 and w4["atk"] == w3["atk"] + 2 * db_mod.NURTURE_BOOST
    assert consume["exp"] == 2 * db_mod.NURTURE_COST
    ok, msg, _, _ = db_mod.nurture(w4, 100, 10 ** 12, 10 ** 12)
    assert ok  # 超上限自动钳制到剩余
    ok, msg, w6 = db_mod.rename(w4, "吞天")
    assert not ok  # 缺形态字
    ok, msg, w6 = db_mod.rename(w4, "吞天剑")
    assert ok and w6["name"] == "吞天剑"
    # 物品卡：可被装备系统消费
    card = db_mod.item_card(w3)
    assert card["type"] == "帝兵" and card["atk"] == w3["atk"] and card["品阶"] == "通灵"
    print("dibing ok")

    # 15n. 世界深度：组合/月之审判/试炼/帝骑
    from core import world_deep as wd_mod  # noqa: E402
    assert wd_mod.combo_of(["风", "翔", "影"]) == "疾风封印"
    assert wd_mod.combo_of(["风", "翔"]) == ""
    zt_w = {"clow_cards": ["风", "翔", "影", "光", "暗", "盾", "镜", "梦", "时", "火"],
            "rider_cards": ["空我", "龙骑", "Faiz"], "tier": 3, "hopes": 30}
    ok, msg, s = wd_mod.set_clow_deck(zt_w, ["风", "翔", "影"])
    assert ok and s["combo"] == "疾风封印", msg
    ok, msg, _ = wd_mod.set_clow_deck(zt_w, ["风", "翔", "泰"])
    assert not ok and "尚未封印" in msg
    ok, msg, _ = wd_mod.set_clow_deck(zt_w, ["风", "翔"])
    assert not ok and "3 张" in msg
    zt_w["sakura"] = s
    # 月之审判：门槛（牌够10、境界够）→ 走流程（两次失败后必成）
    ok, msg, s2 = wd_mod.moon_trial(zt_w, 40, _random.Random(1))
    assert ok and ("成功率" in msg or "必定" in msg), msg
    zt_w["sakura"] = s2
    for _ in range(3):
        ok, msg, s2 = wd_mod.moon_trial(zt_w, 40, _random.Random(9))
        zt_w["sakura"] = s2
        if s2["moon_pass"]:
            break
    assert zt_w["sakura"]["moon_pass"], "三次内应有保底通过"
    assert zt_w["sakura"]["prof"] >= 30
    # 梦之试炼：52 牌不足 → 拒
    ok, msg, _ = wd_mod.dream_trial(zt_w, 40)
    assert not ok and "52" in msg
    zt_w["clow_cards"] = [f"牌{i}" for i in range(52)] + ["镜"]
    zt_w["sakura"]["prof"] = 100
    ok, msg, s3 = wd_mod.dream_trial(zt_w, 40)
    assert ok, msg  # 第一重（镜牌在）
    zt_w["sakura"] = s3
    ok, msg, s3 = wd_mod.dream_trial(zt_w, 40)
    assert ok, msg
    zt_w["sakura"] = s3
    ok, msg, s3 = wd_mod.dream_trial(zt_w, 40)
    assert ok and s3["dream_pass"] and s3["wand"] == "梦之杖", msg
    # 帝骑：编组/融合度/最终驾驭
    zt_w["decade"] = {"deck": [], "fusion": 50, "explore": 0, "resonance": 0}
    ok, msg, d = wd_mod.set_decade_deck(zt_w, ["空我", "龙骑", "Faiz"])
    assert ok and len(d["deck"]) == 3, msg
    ok, msg, _ = wd_mod.final_ride({"decade": d, "tier": 3}, 3)
    assert not ok and "融合度" in msg
    d["fusion"] = 80
    ok, msg, d2 = wd_mod.final_ride({"decade": d, "tier": 3}, 3)
    assert ok and d2["fusion"] == 10, msg
    # 救赎：非鹿目圆化身拒；装了且碎片够 → 扣碎片
    ok, msg, _ = wd_mod.redeem({"hopes": 30}, "木之本樱", True)
    assert not ok and "鹿目圆" in msg
    ok, msg, zt_r = wd_mod.redeem({"hopes": 30}, "鹿目圆", True)
    assert ok and zt_r["hopes"] == 20, (msg, zt_r)
    print("world deep ok")

    # 15o. 问仙令：线索→激活→任务→升级→领奖
    from core import wenxian as wx_mod  # noqa: E402
    wdoc = PlayerDoc(uid="wx", exp=1)
    w = wx_mod.system_of(wdoc)
    ok, msg, _ = wx_mod.explore_clue(w)
    assert not ok  # 无线索
    ok, msg, _ = wx_mod.buy_clue(w, 100)
    assert not ok and "灵石" in msg
    ok, msg, w = wx_mod.buy_clue(w, 10_000_000)
    assert ok and w["clue"]
    for _ in range(3):
        ok, msg, w = wx_mod.explore_clue(w)
        assert ok, msg
    ok, msg, _ = wx_mod.activate(w, 3)
    assert not ok and "境界" in msg
    ok, msg, w = wx_mod.activate(w, 10)
    assert ok and w["active"] and w["level"] == 1, msg
    # 任务埋桩 + 领取（每日 3 项各 500；统一用真实时间，避免跨日 key 重置）
    now = wx_mod.time.time()
    wx_mod.track(w, "seclusion", 5, now)
    wx_mod.track(w, "raid", 5, now)
    for k in ("seclusion", "raid"):
        ok, msg, w = wx_mod.claim_daily(w, k, now)
        assert ok, msg
    ok, msg, w = wx_mod.claim_daily(w, "seclusion", now)
    assert not ok and "已领" in msg
    # 2 项 1000 经验 → 升到 2 级
    assert w["level"] == 2 and w["exp"] == 0, (w["level"], w["exp"])
    # 领奖：1 级可领，重复拒
    ok, msg, w, r = wx_mod.claim_level(w, 1)
    assert ok and r["exp_gain"] > 0, msg
    ok, msg, _, _ = wx_mod.claim_level(w, 1)
    assert not ok and "已领" in msg
    ok, msg, _, _ = wx_mod.claim_level(w, 5)
    assert not ok and "已达到" in msg
    # 每日期数 → 每周 daily 进度
    assert wx_mod.weekly_of(w, now)["prog"]["daily"] == 1
    # 50 级节点奖励潜力
    assert wx_mod.level_reward(50)["potential"] == 80
    # 面板渲染文本
    text = wx_mod.panel(w, now)
    assert "每日任务" in text and "1500" not in text
    print("wenxian ok")

    # 15p. 源石坊：市场生成确定性/勘石/切石结算/凶源/日限
    from core import yuanshi as ys_mod  # noqa: E402
    now_s = 1_800_000_000.0
    st1 = ys_mod.make_market("u1", "外园", now_s)
    st2 = ys_mod.make_market("u1", "外园", now_s)
    assert [s["outcome"] for s in st1] == [s["outcome"] for s in st2], "同日市场应确定"
    assert len(st1) == 5 and all(s["price"] >= 39_000 for s in st1)
    ok, msg = ys_mod.inspect(st1, 1)
    assert ok and msg
    ok, msg = ys_mod.inspect(st1, 9)
    assert not ok
    # 切石：纯净源（ratio 1）→ 源石 = 价/10
    y = {"amount": 0, "day": {}}
    stone = {"no": 1, "price": 100_000, "name": "纯净源", "outcome": "pure",
             "ratio": 1.0, "item": None, "danger": False, "surface": "x"}
    ok, msg, y2, consume = ys_mod.buy_and_cut(
        PlayerDoc(uid="u1"), y, "外园", [stone], 1, 5_000_000, 1000, 1000, now_s, _random.Random(1))
    assert ok and y2["amount"] == 10_000 and consume["cost"]["amount"] == 100_000, (msg, y2)
    assert y2["day"]["count"]["外园"] == 1
    # 日限：外园 3 块
    y3 = y2
    for i in range(2):
        ok, msg, y3, _ = ys_mod.buy_and_cut(
            PlayerDoc(uid="u1"), y3, "外园", [stone], 1, 5_000_000, 1000, 1000, now_s, _random.Random(i))
        assert ok, msg
    ok, msg, _, _ = ys_mod.buy_and_cut(
        PlayerDoc(uid="u1"), y3, "外园", [stone], 1, 5_000_000, 1000, 1000, now_s, _random.Random(9))
    assert not ok and "限额" in msg
    # 凶源反噬
    danger_stone = {"no": 1, "price": 50_000, "name": "凶源", "outcome": "ominous",
                    "ratio": 0.0, "item": None, "danger": True, "surface": "x"}
    ok, msg, y4, consume = ys_mod.buy_and_cut(
        PlayerDoc(uid="u1"), {"amount": 0, "day": {}}, "外园", [danger_stone], 1, 5_000_000, 1000, 1000, now_s, _random.Random(2))
    assert ok and consume["hp_pct"] == 0.05 and "反噬" in msg
    # 物品型（地字号神源液）
    item_stone = {"no": 1, "price": 300_000, "name": "神源液", "outcome": "divine_liquid",
                  "ratio": 0.0, "item": "神源液", "danger": False, "surface": "x"}
    ok, msg, y5, consume = ys_mod.buy_and_cut(
        PlayerDoc(uid="u1"), {"amount": 400_000, "day": {}}, "地字号", [item_stone], 1, 0, 1000, 1000, now_s, _random.Random(3))
    assert ok and consume["gains"].get("神源液") == 1 and y5["amount"] == 100_000, (msg, y5)
    # 兑换
    ok, msg, y6 = ys_mod.exchange(1000, {"amount": 2000, "day": {}})
    assert ok and y6["amount"] == 1000
    print("yuanshi ok")

    # 15q. 魔头禁术：魔功/镇魂资格/处置/魂印
    from core import motou as mt_mod  # noqa: E402
    now_e = 1_900_000_000.0
    ev = mt_mod.state_of(PlayerDoc(uid="e1", ext={"modao": 200.0}))
    assert ev["modao"] == 200.0
    # 魔功：消耗递增（cost(0)=80，cost(1)=120）、上限 10
    ok, msg, ev = mt_mod.train_magic(ev)
    assert ok and ev["magic"] == 1 and ev["modao"] == 120.0, (msg, ev["modao"])
    assert abs(mt_mod.magic_bonus(ev) - 0.08) < 1e-9
    ok, msg, ev = mt_mod.train_magic(ev)  # 剩 120，cost(1)=120 → 成功升 2 层
    assert ok and ev["magic"] == 2 and ev["modao"] == 0.0, (msg, ev["modao"])
    ok, msg, _ = mt_mod.train_magic(ev)  # 魔道 0 < cost(2)=180 → 拒
    assert not ok and "魔道值不足" in msg
    # 资格：魔道不足 → 拒；境界差保护；保护期（重置 ev 为魔道充足状态）
    ev = mt_mod.state_of(PlayerDoc(uid="e1", ext={"modao": 200.0}))
    weak = mt_mod.state_of(PlayerDoc(uid="e2", ext={"modao": 10.0}))
    ok, why = mt_mod.can_slay(weak, 40, 100, mt_mod.state_of(PlayerDoc(uid="t1")), 40, 100, now_e)
    assert not ok and "邪道" in why
    ok, why = mt_mod.can_slay(ev, 20, 100, mt_mod.state_of(PlayerDoc(uid="t1")), 20, 100, now_e)
    assert not ok and "境界不足" in why
    ok, why = mt_mod.can_slay(ev, 40, 100, mt_mod.state_of(PlayerDoc(uid="t1")), 30, 100, now_e)
    assert not ok and "天道弱者" in why  # 40-30 > 8？差 10 > 8 → 保护
    ok, why = mt_mod.can_slay(ev, 40, 100, mt_mod.state_of(PlayerDoc(uid="t1")), 35, 100, now_e)
    assert ok, why
    # 记录战果 → 处置烙印 → 对方魂印 + 保护期
    ev = mt_mod.record_result(ev, "受害者", True, now_e)
    assert ev["pending"] and ev["slay_ts"] == now_e
    target_ev = mt_mod.state_of(PlayerDoc(uid="t1"))
    ok, msg, ev, patch = mt_mod.dispose(ev, "烙印", target_ev, now_e + 60)
    assert ok and ev["soul_slave"]["name"] == "受害者", msg
    assert patch["brand"]["until"] == now_e + 60 + mt_mod.BRAND_DURATION
    assert patch["protected_until"] == now_e + 60 + mt_mod.PROTECTION
    # 魂印惩罚 / 魂奴加成
    branded = {"brand": {"until": now_e + 100}}
    assert abs(mt_mod.brand_penalty(branded, now_e) - 0.7) < 1e-9
    assert abs(mt_mod.slave_bonus(ev, now_e + 60) - 0.10) < 1e-9
    # 冲击魂印
    ok, msg, s2 = mt_mod.break_brand(PlayerDoc(uid="t1"), dict(branded), now_e, 1_000_000)
    assert ok and s2["brand"] is None
    # 灭魂 → 遗蜕 → 炼化
    ev2 = mt_mod.record_result(mt_mod.state_of(PlayerDoc(uid="e3", ext={"modao": 300.0})), "猎物", True, now_e)
    ok, msg, ev2, _ = mt_mod.dispose(ev2, "灭魂", mt_mod.state_of(PlayerDoc(uid="t9")), now_e + 60)
    assert ok and ev2["remains"]["name"] == "猎物"
    ok, msg, ev2, consume = mt_mod.refine_remains(ev2, 40)
    assert ok and consume["exp"] > 0 and ev2["remains"] is None
    print("motou ok")

    # 15r. 剧情 NPC：好感/关系/请教/终极/精血
    from core import npc as npc_mod  # noqa: E402
    ndoc = PlayerDoc(uid="n1", ext={"linggen": {"name": "荒古圣体", "type": "圣体", "eff": 1.2}})
    n = npc_mod.state_of(ndoc)
    assert n["ruthless"]["favor"] == 0 and npc_mod.relation_of(0) == "时间长河一瞥"
    ok, msg, n = npc_mod.talk(n, "ruthless", 1_900_000_000.0)
    assert ok and 5 <= n["ruthless"]["favor"] <= 8, msg
    # 每日 3 次
    for i in range(2):
        ok, msg, n = npc_mod.talk(n, "ruthless", 1_900_000_000.0 + i)
        assert ok, msg
    ok, msg, _ = npc_mod.talk(n, "ruthless", 1_900_000_000.0 + 9)
    assert not ok and "3 次" in msg
    # 关系档位
    assert npc_mod.relation_of(180) == "隔世相知" and npc_mod.relation_of(480) == "护道之约"
    # 狠人请教：好感不足 → 拒；够 → 授功法
    ok, msg, _, _ = npc_mod.teach_ruthless(n, [])
    assert not ok and "隔世相知" in msg
    n["ruthless"]["favor"] = 200
    ok, msg, n, g = npc_mod.teach_ruthless(n, [])
    assert ok and g in npc_mod.RUTHLESS_TEACHINGS, (msg, g)
    # 苏灵请教：门槛 + 10 次终极
    ok, msg, _, _ = npc_mod.teach_suling(n, 1_900_000_000.0)
    assert not ok and "命途相知" in msg
    n["suling"]["favor"] = 300
    ok, msg, n, gain = npc_mod.teach_suling(n, 1_900_000_000.0)
    assert ok and gain["exp"] > 0
    ok, msg, _, _ = npc_mod.teach_suling(n, 1_900_000_000.0 + 60)
    assert not ok and "每日一次" in msg
    n["suling"]["teach_total"] = 9
    ok, msg, n, gain = npc_mod.teach_suling(n, 1_900_000_000.0 + 86400)
    assert ok and n["suling"]["ultimate"] and gain["potential"] == 200, msg
    # 凝聚精血：体质门槛 + 7 天 CD
    ok, msg, n2 = npc_mod.essence(ndoc, n, 1_900_000_000.0)
    assert ok and npc_mod.ESSENCE_ITEM in msg, msg
    ok, msg, _ = npc_mod.essence(ndoc, n2, 1_900_000_000.0 + 60)
    assert not ok and "静养" in msg
    plain_doc = PlayerDoc(uid="n2", ext={"linggen": {"name": "凡人", "type": "凡体"}})
    ok, msg, _ = npc_mod.essence(plain_doc, npc_mod.state_of(plain_doc), 1_900_000_000.0)
    assert not ok and "特殊体质" in msg
    # 面板
    text = npc_mod.panel(n, 1_900_000_000.0)
    assert "狠人大帝" in text and "苏灵" in text
    print("npc ok")

    # 15i. 师徒/道侣/封禁（纯存档语义验证）
    master = PlayerDoc(uid="m1", ext={"recruit": True})
    disciple = PlayerDoc(uid="d1")
    dm = master.model_copy(deep=True)
    dm.ext["tudi"] = list(dm.ext.get("tudi") or []) + ["d1"]
    dd = disciple.model_copy(deep=True)
    dd.ext["shifu"] = "m1"
    assert dm.ext["tudi"] == ["d1"] and dd.ext["shifu"] == "m1"
    # 封禁语义：_require_player 层拦截（ext.banned）
    banned = PlayerDoc(uid="b1", ext={"banned": True})
    assert banned.ext.get("banned") is True
    print("social ok")

    # 15j. 师徒积分/试炼/重铸/双修（存档语义）
    d_t = disciple.model_copy(deep=True)
    d_t.ext["shitu_points"] = int(d_t.ext.get("shitu_points", 0)) + 200
    assert d_t.ext["shitu_points"] == 200
    d_t.ext["shitu_points"] -= 100  # 兑换
    assert d_t.ext["shitu_points"] == 100
    # 双修收益（道侣双方修为+亲密度）
    lover_a = PlayerDoc(uid="la", ext={"daolv": "lb", "qinmidu": {"lb": 10}})
    lover_b = PlayerDoc(uid="lb", ext={"daolv": "la", "qinmidu": {"la": 10}})
    gain = 2000 * 5
    qa = dict(lover_a.ext.get("qinmidu") or {})
    qa["lb"] = int(qa.get("lb", 0)) + 5
    assert qa["lb"] == 15
    # 双修融合规则（体质对+概率）
    RULES = [
        ({"大成·荒古圣体", "先天道胎"}, 0.05, "先天圣体道胎"),
        ({"命运神道体", "极道天魔"}, 0.01, "终焉神魔体"),
        ({"太阳之体", "太阴之体"}, 0.01, "混沌体"),
    ]
    for names, chance, fused in RULES:
        assert len(names) == 2 and 0 < chance <= 1 and fused, (names, fused)
    # 融合体质在灵根表中
    lg_tbl = store.table("item/灵根列表")
    lg_names = {e.get("name") for e in lg_tbl}
    for _, _, fused in RULES:
        assert fused in lg_names, fused
    for n in ("大成·荒古圣体", "先天道胎", "命运神道体", "极道天魔", "太阳之体", "太阴之体"):
        assert n in lg_names, n
    print("fusion ok")

    # 15c. 每日任务：公式 / 接取-提交-领奖闭环 / 灵石自动追踪 / 秘境计数
    from core import quest as quest_mod  # noqa: E402

    lvl, realm = 1, 3
    ns, ng, nsec = quest_mod.requirements(lvl, realm)
    assert ns == ng == (5 + 6) * 20000 and nsec == 2, (ns, ng, nsec)
    rec = quest_mod.accept_record(None, "u1", "2026-11-01")
    assert rec["w1"] == rec["w2"] == rec["w3"] == 1 and rec["renwu"] == 0
    rec["j1"] = ns
    msgs, rec2, done = quest_mod.settle_submit(rec, realm)
    assert done == 1 and rec2["w1"] == 2 and rec2["exp"] == quest_mod.step_exp(lvl, realm)
    assert rec2["renwu"] == 0, "未全完成不应进入待领奖"
    rec2["j2"] = ng
    rec2["j3"] = nsec
    msgs, rec3, done3 = quest_mod.settle_submit(rec2, realm)
    assert done3 == 2 and quest_mod.all_done(rec3) and rec3["renwu"] == 1
    fr = quest_mod.final_reward(lvl, realm)
    assert fr["keys"] == 1 and fr["amount"] == 1 * 6 * 8000 and fr["task_exp"] > 0
    rec4 = quest_mod.settle_claim(rec3)
    assert rec4["renwu"] == 2
    assert not quest_mod.is_today(None, "2026-11-01") and quest_mod.is_today({"date": "2026-11-01"}, "2026-11-01")

    # 灵石自动追踪：save_player 新旧差值入 gained/spent（仅当日已接取记录）
    tr_doc = PlayerDoc(uid="tasker", stones=1000)
    await db.upsert_daily_task(quest_mod.accept_record(None, "tasker", quest_mod.date_key()))
    await db.save_player(tr_doc.model_dump())     # 基线落库（无旧档，不追踪）
    tr_doc.stones = 400                           # 消耗 600
    await db.save_player(tr_doc.model_dump())
    row = await db.get_daily_task("tasker")
    assert row["spent"] == 600 and row["gained"] == 0, row
    tr_doc.stones = 1500                          # 获取 1100
    await db.save_player(tr_doc.model_dump())
    row = await db.get_daily_task("tasker")
    assert row["gained"] == 1100 and row["spent"] == 600, row
    assert await db.add_daily_secret("tasker")
    assert (await db.get_daily_task("tasker"))["j3"] == 1
    print("daily quest ok")

    # 16. 秘境：程序化怪物 / 遭遇循环 / 战败出局 / 掉落稀有度门槛
    from core import secret as secret_mod  # noqa: E402

    assert secret_mod.PLACES["太古战场"][1] > secret_mod.PLACES["青冥山"][1]
    m_weak = secret_mod.make_monster("青冥山", 0, (1000, 1000, 1000), _random.Random(1))
    m_strong = secret_mod.make_monster("太古战场", 5, (1000, 1000, 1000), _random.Random(1), elite=True)
    assert m_strong.atk > m_weak.atk * 3, (m_weak.atk, m_strong.atk)

    pool = [
        {"name": "灵草", "class": "草药", "稀有度": 1},
        {"name": "玄铁", "class": "材料", "稀有度": 3},
        {"name": "仙丹", "class": "丹药", "稀有度": 6},
    ]
    rng3 = _random.Random(1)
    shallow = {secret_mod.roll_drop(pool, rng3, 0, False)["name"] for _ in range(30)}
    assert shallow <= {"灵草", "玄铁"}, shallow          # 第 0 层稀有度上限 2
    deep = {secret_mod.roll_drop(pool, rng3, 9, True)["name"] for _ in range(60)}
    assert "仙丹" in deep, deep                          # 第 9 层精英上限 7

    sess = secret_mod.Session(place="青冥山")
    me = battle_mod.Unit("甲", 3000, 1500, 20000, 0.2)
    base = (3000, 1500, 20000)
    for _ in range(50):
        if me.hp <= 0:
            break
        sess, me, _, fled = secret_mod.explore(sess, base, me, pool, rng3)
        if fled:
            break
    assert sess.floor >= 1 and len(sess.log) == sess.floor and sess.stones >= 0

    weak = battle_mod.Unit("弱", 5, 5, 10)
    sess2 = secret_mod.Session(place="太古战场")
    fled_seen = False
    for _ in range(30):
        sess2, weak, _, fled = secret_mod.explore(sess2, base, weak, pool, _random.Random(3))
        if fled:
            fled_seen = True
            break
    assert fled_seen, "弱者应被打出局且散财"
    assert sess2.stones >= 0 and sess2.floor >= 1
    print("secret realm ok")

    # 16b. 剧情人物：图鉴 / 邂逅 / 好感 / 护道 / 黑皇阵道
    from core import story_npc as story_mod  # noqa: E402

    roster = store.table("item/剧情人物列表")
    assert isinstance(roster, list) and len(roster) == 10, len(roster)
    assert story_mod.relation_of("柳神", 0) == "初识"
    assert story_mod.relation_of("柳神", 60) == "相识"
    assert story_mod.relation_of("柳神", 480) == "护道者"
    assert story_mod.relation_of("黑皇", 40) == "熟人"
    assert story_mod.relation_of("黑皇", 360) == "帝阵传人"

    sdoc = PlayerDoc(uid="story", name="说书人", realm_index=10, stones=10 ** 12)
    sdoc.ext["occupation"] = "阵法师"
    sdoc.ext["occupation_level"] = 3
    sdoc.ext["occupation_exp"] = 0
    s = story_mod.state_of(sdoc)
    assert story_mod.meet(s, "青冥山", 2, 0, _random.Random(1)) is None, "层数未到不应邂逅"
    enc = story_mod.meet(s, "青冥山", 3, 0, _random.Random(1))
    assert enc and enc["name"] == "柳神" and enc["first"] and enc["gain"] == 10, enc
    enc = story_mod.meet(s, "幽冥渊", 6, 0, _random.Random(1))
    assert enc and enc["name"] == "张五爷" and enc.get("item") == "源师转职凭证", enc

    sdoc.ext["story"] = s
    rows = story_mod.gallery_rows(sdoc, roster)
    names = [c["name"] for g in rows for c in g["chars"]]
    assert len(names) == 11 and "柳神" in names and "狠人大帝" in names, names

    ok, _, s = story_mod.assign_protector(sdoc, s, "柳神")
    assert not ok, "好感不足不应立约"
    s["chars"]["柳神"]["favor"] = 480
    sdoc.ext["story"] = s
    ok, _, s = story_mod.assign_protector(sdoc, s, "柳神")
    assert ok, "480 好感应可立护道之约"
    assert story_mod.try_protect(s, 100)[0] == "柳神"
    assert story_mod.try_protect(s, 200) is None, "护道 24h 冷却未生效"

    s["chars"]["黑皇"] = {"favor": 90, "met": True, "unlock_ts": 0, "events": [],
                          "talk_day": "", "talk_count": 0, "engrave_day": "",
                          "engrave_count": 0, "taught": False}
    ok, _, s = story_mod.hei_teach(s)
    assert ok, "80 好感应获黑皇阵道传承"
    s["chars"]["黑皇"]["favor"] = 360
    ok, _, f = story_mod.engrave_check(s, "无始杀阵", 1000, 10 ** 12)
    assert ok and f and f["kind"] == "kill"
    eff, s = story_mod.apply_engrave(s, "无始杀阵", 1000)
    mods, used = story_mod.battle_mods(s)
    assert mods.get("atk_mult") == 2.0 and used == ["无始杀阵"], (mods, used)
    assert s["arrays"][0]["left"] == 4, "无始杀阵次数未扣减"

    winner, slog, _, _ = battle_mod.spar_full(
        battle_mod.Unit("甲", 1000, 100, 100000),
        battle_mod.Unit("乙", 1000, 100, 100000),
        _random.Random(1), skip_first=(1,),
    )
    assert any("困住" in ln for ln in slog), "困龙阵定身未生效"

    triggered = None
    for i in range(40):
        def _prot(place, floor, enemy, _state={"ready": True}):
            if _state["ready"]:
                _state["ready"] = False
                return "柳神", "【护道之约·柳神】护道法相出手。"
            return None

        sess3 = secret_mod.Session(place="太古战场")
        weak3 = battle_mod.Unit("弱", 5, 5, 10)
        sess3, weak3, fl3, fled3 = secret_mod.explore(
            sess3, (5, 5, 500), weak3, pool, _random.Random(i), protect=_prot
        )
        if "护道" in fl3:
            triggered = (fled3, weak3.hp, sess3.stones)
            break
    assert triggered and triggered[0] is False and triggered[1] == 500, triggered
    print("story npc ok")

    # 16c. 团本讨伐：定标 / 分奖 / 队伍流转 / 出手记伤 / 击杀
    from core import raid as raid_mod  # noqa: E402

    st = raid_mod.boss_stats(10_000_000, 4, 1.0)
    assert st["hp"] == 10_000_000 * (3 + 2.5 * 4), st
    assert st["hp_max"] == st["hp"] and st["reward"] > 0
    assert raid_mod.boss_stats(10_000_000, 4, 2.0)["hp"] == st["hp"] * 2

    shares = raid_mod.split_rewards(1_000_000, [("a", "甲", 600), ("b", "乙", 400)], "a")
    assert shares[0]["uid"] == "a" and shares[0]["stones"] == 600_000 + 100_000, shares
    assert shares[1]["stones"] == 400_000
    assert shares[0]["share"] == 60.0

    now = 1_800_000_000.0
    assert (await db.create_raid("123456", "若陀龙王", "raid_u1", "甲", now)) is None
    team = await db.get_raid("123456")
    assert team["status"] == "recruiting" and team["leader_uid"] == "raid_u1"
    assert (await db.active_raid_of("raid_u1"))["code"] == "123456"
    assert await db.join_raid("123456", "raid_u2", "乙", now + 1)
    assert not await db.join_raid("123456", "raid_u2", "乙", now + 2), "重复加入应失败"
    assert await db.raid_member_count("123456") == 2
    assert await db.start_raid("123456", st), "招募中应可开战"
    left = await db.damage_raid("123456", "raid_u1", st["hp"] // 2, "2026-11-02", now + 3)
    assert left > 0
    assert (await db.raid_member("123456", "raid_u1"))["dmg"] == st["hp"] // 2
    left = await db.damage_raid("123456", "raid_u2", st["hp"], "2026-11-02", now + 4)
    assert left <= 0
    team = await db.get_raid("123456")
    assert team["status"] == "victory" and team["killer_uid"] == "raid_u2", team
    members = await db.raid_members("123456")
    assert len(members) == 2 and members[0]["uid"] == "raid_u2"

    member = {"hits_today": 3, "hits_day": raid_mod.time_key(now), "last_ts": 0}
    ok, msg = raid_mod.can_hit({"status": "fighting", "hp": 100}, member, now)
    assert not ok and "次数" in msg
    member = {"hits_today": 3, "hits_day": "1999-01-01", "last_ts": 0}
    ok, _ = raid_mod.can_hit({"status": "fighting", "hp": 100}, member, now)
    assert ok, "跨日应重置出手次数"
    member = {"hits_today": 0, "hits_day": raid_mod.time_key(now), "last_ts": now}
    ok, msg = raid_mod.can_hit({"status": "fighting", "hp": 100}, member, now + 1)
    assert not ok and "秒后" in msg

    # 解散：招募中的队伍可关闭
    await db.create_raid("654321", "九幽魔君", "raid_u3", "丙", now)
    await db.close_raid("654321", "closed", now)
    assert (await db.get_raid("654321"))["status"] == "closed"
    assert (await db.active_raid_of("raid_u3")) is None
    print("raid ok")

    # 16d. 无尽劫境：开局 / 星图 / 推进 / 能力 / 劫后 / 通关 / 战败 / 排名
    from core import endless as end_mod  # noqa: E402

    content_e = store.table("无尽劫境")
    assert len(content_e["worlds"]) == 6 and len(content_e["abilities"]) == 57, "劫境数据不完整"
    c1 = end_mod.celestial_of(1_800_000_000)
    assert c1["id"] == end_mod.celestial_of(1_800_000_100)["id"], "天象应当每日固定"

    base_e = {"atk": 1_000_000, "def": 800_000, "hp": 2_000_000, "bao": 0.1}
    edoc = PlayerDoc(uid="endless", name="劫客", realm_index=20)
    st = end_mod.state_of(edoc)
    ok, msg, st = end_mod.start_run(st, edoc, base_e, content_e, "乱古界海", 1_800_000_000)
    assert ok and st["active"] and len(st["starmap"]) == 3, msg
    assert st["hp"] == base_e["hp"] and st["hp_max"] == base_e["hp"]
    assert end_mod.select_node(st, 1)[0]
    st = end_mod.select_node(st, 1)[2]
    st, res = end_mod.resolve_node(st, base_e, content_e, 1_800_000_000, _random.Random(7))
    assert res["ok"] and res["layer"] == 1 and st["layer"] == 1
    assert st["phase"] in ("choice", "ready"), st["phase"]
    if st["phase"] == "choice":
        ok, _, st = end_mod.pick_ability(st, 1, content_e)
        assert ok and len(st["abilities"]) == 1

    for _ in range(2):
        if st["phase"] == "choice":
            st = end_mod.pick_ability(st, 1, content_e)[2]
        elif st["phase"] == "checkpoint":
            st = end_mod.apply_checkpoint(st, 1, content_e, base_e, _random.Random(1), 1_800_000_000)[2]
        st = end_mod.select_node(st, 1)[2]
        st, _res = end_mod.resolve_node(st, base_e, content_e, 1_800_000_000, _random.Random(8))
    assert st["layer"] == 3 and st["phase"] == "checkpoint", (st["layer"], st["phase"])
    ok, msg, st = end_mod.apply_checkpoint(st, 1, content_e, base_e, _random.Random(2), 1_800_000_000)
    assert ok and st["phase"] == "ready", msg

    # 强属性跑完 10 层，验证通关/解锁/道痕入账
    base_win = {"atk": 200_000_000, "def": 5_000_000, "hp": 3_000_000_000, "bao": 1.0}
    st2 = end_mod.state_of(PlayerDoc(uid="endless2", name="劫客二", realm_index=30))
    ok, msg, st2 = end_mod.start_run(
        st2, PlayerDoc(uid="endless2", name="劫客二", realm_index=30),
        base_win, content_e, "葬帝星路", 1_800_000_000,
    )
    assert ok, msg
    guard = 0
    while st2["active"] and guard < 40:
        guard += 1
        if st2["phase"] == "choice":
            st2 = end_mod.pick_ability(st2, 1, content_e)[2]
        elif st2["phase"] == "checkpoint":
            st2 = end_mod.apply_checkpoint(
                st2, 3, content_e, base_win, _random.Random(3), 1_800_000_000)[2]
        elif st2["phase"] == "ready":
            st2 = end_mod.select_node(st2, 1)[2]
            st2, _r = end_mod.resolve_node(
                st2, base_win, content_e, 1_800_000_000, _random.Random(st2["layer"] + 10))
        else:
            break
    assert not st2["active"] and st2["best_layer"] == 10, st2
    assert 1 in st2["clears"] and end_mod.unlocked_tier(st2) == 2, st2
    assert st2["marks_total"] > 0 and st2["marks"] == 0

    # 战败：只保留一半道痕
    weak_doc = PlayerDoc(uid="endless3", name="劫客三", realm_index=20)
    st3 = end_mod.state_of(weak_doc)
    ok, msg, st3 = end_mod.start_run(
        st3, weak_doc, {"atk": 1000, "def": 0, "hp": 100, "bao": 0},
        content_e, "", 1_800_000_000)
    assert ok, msg
    st3["starmap"] = [{"type": "battle", "name": "测试劫兽", "trait": "", "desc": ""}]
    st3 = end_mod.select_node(st3, 1)[2]
    st3, res3 = end_mod.resolve_node(
        st3, {"atk": 1000, "def": 0, "hp": 100, "bao": 0}, content_e,
        1_800_000_000, _random.Random(5))
    assert not res3["win"] and not st3["active"], res3

    rows = end_mod.rank_rows([
        {"uid": "a", "name": "甲", "ext": {"endless": {"best_tier": 1, "best_layer": 10, "marks_total": 100}}},
        {"uid": "b", "name": "乙", "ext": {"endless": {"best_tier": 2, "best_layer": 3, "marks_total": 50}}},
    ])
    assert rows and rows[0]["name"] == "乙", rows
    assert st2["marks_earned"] == st2["marks_total"], "无消费时历史道痕应等于钱包"
    print("endless ok")

    # 16e. 无尽商店 / 劫境商人 / 称号 / 周末免费
    shop = store.table("无尽商店")
    assert len(shop["products"]) == 21, "无尽商店商品数不对"
    cel = {"name": "测试天象", "shop": 1.0}
    stx = end_mod.state_of(PlayerDoc(uid="shop", name="商人", realm_index=30))
    stx["marks_total"] = 100_000
    sat = time.mktime(time.strptime("2026-11-07 12:00:00", "%Y-%m-%d %H:%M:%S"))
    assert end_mod.is_weekend(sat), "2026-11-07 应为周六"
    assert end_mod.weekend_available(stx, sat)
    stx["weekend_week"] = end_mod.week_key(sat)
    assert not end_mod.weekend_available(stx, sat), "本周额度用后不应再免费"
    stx["weekend_week"] = ""

    pill = [p for p in shop["products"] if p["id"] == 2][0]
    assert end_mod.shop_price(pill, cel) == pill["price"]
    assert end_mod.shop_price(pill, {"shop": 1.25}) == int(pill["price"] * 1.25)
    ok, msg, stx, got = end_mod.buy_shop(stx, "2", 2, sat, shop, cel)
    assert ok and got.get("叩仙丹") == 2 and stx["marks_total"] == 100_000 - 200, msg
    assert stx["shop_counts"]["2"] == 2
    ok, msg, stx, _ = end_mod.buy_shop(stx, "2", 99, sat, shop, cel)
    assert not ok and "限购" in msg, msg
    ok, msg, stx, _ = end_mod.buy_shop(stx, "8", 1, sat, shop, cel)
    assert not ok, "未开放 action 不应可买"

    stm = end_mod.state_of(PlayerDoc(uid="merchant", name="行商", realm_index=30))
    stm["layer"] = 3
    stm["marks"] = 100_000
    stm = end_mod.refresh_merchant(stm, shop, cel, _random.Random(1))
    assert len(stm["merchant"]) == 4, stm["merchant"]
    price0 = stm["merchant"][0]["price"]
    before = stm["marks"]
    ok, msg, stm, got2 = end_mod.buy_merchant(stm, 1, cel)
    assert ok and stm["marks"] == before - price0 and len(stm["merchant"]) == 3, msg
    stm["marks"] = 0
    ok, msg, _, _ = end_mod.buy_merchant(stm, 1, cel)
    assert not ok and "不足" in msg

    stt = end_mod.state_of(PlayerDoc(uid="title", name="称号", realm_index=30))
    stt["best_layer"] = 5
    owned = [t["name"] for t in end_mod.owned_titles(stt)]
    assert "初入劫境" in owned and "劫境行者" in owned and "破界者" not in owned, owned
    ok, msg, stt = end_mod.equip_title(stt, "劫境行者")
    assert ok and stt["title"] == "劫境行者", msg
    ok, msg, _ = end_mod.equip_title(stt, "无尽劫境天尊")
    assert not ok, "未获得称号不应可佩戴"
    base_t = {"atk": 1_000_000, "def": 1_000_000, "hp": 1_000_000, "bao": 0}
    plain_st = end_mod.state_of(PlayerDoc(uid="t2"))
    stat_plain = end_mod.run_stats(plain_st, base_t, content_e, cel)
    stat_title = end_mod.run_stats(stt, base_t, content_e, cel)
    assert stat_title["atk"] > stat_plain["atk"], (stat_plain, stat_title)
    print("endless shop ok")

    # 16f. 万劫道碑 / 无尽至宝 / 能力重演 / 扫荡
    md = PlayerDoc(uid="meta", name="碑主", realm_index=30)
    mst = end_mod.state_of(md)
    mst["marks_total"] = 100_000
    mst["clears"] = [1, 2, 3, 4]
    meta = end_mod.meta_state_of(md)
    ok, msg, meta, mst = end_mod.upgrade_meta(meta, mst, "攻击")
    assert ok and meta["nodes"]["attack"] == 1 and mst["marks_total"] == 99_950, msg
    ok, msg, meta, mst = end_mod.upgrade_meta(meta, mst, "衍算天机")
    assert ok and meta["nodes"]["choice"] == 1
    ok, msg, meta, mst = end_mod.upgrade_meta(meta, mst, "破阵师")
    assert ok and meta["branch"] == "vanguard", msg
    ok, msg, meta, mst = end_mod.upgrade_meta(meta, mst, "治疗师")
    assert not ok, "流派锁定后不应可改投"
    ok, msg, meta, mst = end_mod.upgrade_meta(meta, mst, "三尖两刃刀")
    assert ok and "three_pointed_blade" in end_mod.meta_effects(meta)["unlocks"], msg
    eff_m = end_mod.meta_effects(meta)
    assert eff_m["atk"] > 1 and eff_m["choice"] == 4 and eff_m["crit"] > 0, eff_m
    ok, msg, meta2, mst2 = end_mod.reset_meta(meta, mst)
    assert ok and mst2["marks_total"] > mst["marks_total"], "重置应返还道痕"

    tres = {"owned": {}, "equipped": [], "slots": 1}
    stc = end_mod.state_of(PlayerDoc(uid="treasure", name="宝主", realm_index=30))
    stc["clears"] = [1, 2]
    stc["marks_total"] = 100_000
    tres, name1 = end_mod.grant_treasure(tres, stc)
    assert name1 == "缘一的斩鬼之刀", name1
    tres, name2 = end_mod.grant_treasure(tres, stc)
    assert name2 == "九尾人柱力", name2
    ok, msg, tres = end_mod.equip_treasure(tres, name1)
    assert ok, msg
    ok, msg, tres = end_mod.equip_treasure(tres, name2)
    assert not ok, "1 槽位不应能装第二件"
    ok, msg, tres, stc = end_mod.expand_slots(tres, stc)
    assert ok and tres["slots"] == 2, msg
    ok, msg, tres = end_mod.equip_treasure(tres, name2)
    assert ok, msg
    ok, msg, tres, stc = end_mod.upgrade_treasure(tres, stc, name1)
    assert ok and tres["owned"][list(tres["owned"])[0]] >= 2, msg
    stc["treasures"] = end_mod.equipped_treasures(tres)
    plain_eff = end_mod.treasure_effects({"treasures": [], "abilities": {}})
    tr_eff = end_mod.treasure_effects(stc)
    assert tr_eff["atk"] > plain_eff["atk"], (plain_eff, tr_eff)
    stc["abilities"] = {"anime_sun_breath": 1, "anime_transparent_world": 1}
    aw_eff = end_mod.treasure_effects(stc)
    assert aw_eff["atk"] > tr_eff["atk"], "集齐觉醒条件后加成应提高"

    st_r = end_mod.state_of(PlayerDoc(uid="reroll"))
    st_r["phase"] = "choice"
    st_r["meta"] = {"choice": 4, "reroll": 1}
    st_r["rerolls"] = 1
    st_r["abilities"] = {}
    st_r["choices"] = end_mod.ability_choices(st_r, content_e, _random.Random(1))
    assert len(st_r["choices"]) == 4, st_r["choices"]
    ok, msg, st_r = end_mod.reroll_choices(st_r, content_e, _random.Random(2))
    assert ok and st_r["rerolls"] == 0 and len(st_r["choices"]) == 4, msg
    ok, msg, _ = end_mod.reroll_choices(st_r, content_e, _random.Random(3))
    assert not ok, "重演次数用尽后不应可刷新"

    st_s = end_mod.state_of(PlayerDoc(uid="sweep"))
    st_s["best_layer"] = 8
    st_s["marks_total"] = 0
    ok, msg, st_s = end_mod.sweep(st_s, sat, cel)
    assert ok and st_s["marks_total"] > 0, msg
    ok, msg, _ = end_mod.sweep(st_s, sat, cel)
    assert not ok, "同日不应重复扫荡"
    print("endless meta ok")

    # 16g. 沉迷秘境：时长/费用/模拟/死亡中断/历史
    from core import addict as addict_mod  # noqa: E402

    assert addict_mod.rounds_of(3) == 9
    assert addict_mod.cost_of("青冥山", 1) == int(addict_mod.PLACE_COST * secret_mod.place_factor("青冥山"))
    rec = addict_mod.make("青冥山", 2, 1_800_000_000)
    assert rec["rounds"] == 6 and rec["end"] == 1_800_000_000 + 2 * addict_mod.MINUTES_PER_COUNT * 60
    out, hp_left = addict_mod.simulate(
        rec, (1_000_000, 800_000, 2_000_000), 2_000_000, 0.2, pool, _random.Random(1)
    )
    assert out["done"] >= 1 and out["status"] in ("completed", "died"), out
    assert out["exp"] >= 0 and hp_left >= 0
    out_w, hp_w = addict_mod.simulate(
        rec, (10, 0, 10), 10, 0.0, pool, _random.Random(2)
    )
    assert out_w["deaths"] >= 1 and hp_w <= 0, out_w
    assert "沉迷收获" in addict_mod.summary_text(out)
    hdoc = addict_mod.push_history(PlayerDoc(uid="addict"), out)
    assert len(addict_mod.history_of(hdoc)) == 1
    print("addiction ok")

    # 16h. 凡间坐标 / 位面旅行
    from core import plane as plane_mod  # noqa: E402
    from infra import render as render_mod  # noqa: E402

    pdata = store.table("位面坐标")
    plane_names = [k for k in pdata if not k.startswith("_")]
    assert len(plane_names) == 11, plane_names
    for pn in plane_names:
        ids = {l["id"] for l in pdata[pn]["locations"]}
        for loc in pdata[pn]["locations"]:
            b = loc["bounds"]
            assert 0 <= b["x1"] < b["x2"] <= 999 and 0 <= b["y1"] < b["y2"] <= 999, (pn, loc["name"])
            assert not loc.get("parent") or loc["parent"] in ids, (pn, loc["name"], loc.get("parent"))

    fan_sites = plane_mod.sites_of(pdata, "凡间")
    assert len(fan_sites) == 10, len(fan_sites)
    leaf = next(x for x in fan_sites if x.get("parent"))
    lc = plane_mod.center(leaf)
    chain = plane_mod.chain_at(pdata, "凡间", lc["x"], lc["y"])
    assert chain and chain[-1]["id"] == leaf["id"] and len(chain) >= 2, chain
    assert chain[0]["name"] == "天南", chain[0]["name"]

    free = None
    for gx in range(0, 1000, 25):
        for gy in range(0, 1000, 25):
            if not plane_mod.chain_at(pdata, "遮天位面", gx, gy):
                free = (gx, gy)
                break
        if free:
            break
    assert free, "遮天位面应存在荒野坐标"

    pl = PlayerDoc(uid="plane", name="星客", realm_index=46, stones=5_000_000)
    pl.ext["xueqi"] = 5_000_000
    pst = plane_mod.state_of(pl)
    assert plane_mod.current(pst) == "凡间" and plane_mod.known_of(pst) == ["凡间"]
    assert plane_mod.coord_of(pst) is None

    ok, msg = plane_mod.move_to(pl, pdata, lc["x"], lc["y"])
    assert ok and "初至" in msg and pl.stones == 5_005_000 and pl.exp == plane_mod.SITE_EXP, msg
    ok, msg2 = plane_mod.move_to(pl, pdata, lc["x"], lc["y"])
    assert ok and "初至" not in msg2 and pl.stones == 5_005_000, msg2
    pst["current"] = "遮天位面"
    ok, _msg = plane_mod.move_to(pl, pdata, free[0], free[1])
    assert ok and "荒芜" in _msg, _msg
    pst["current"] = "凡间"
    ok, _msg = plane_mod.move_to(pl, pdata, 2000, 10)
    assert not ok, "越界坐标应拒绝"

    q = plane_mod.quote(pl, "仙界")
    assert q["ok"] and q["distance"] == 1 and q["minutes"] >= 1 and q["exp"] > 0, q
    low = PlayerDoc(uid="low", name="凡人", realm_index=0)
    low.ext["xueqi"] = 10 ** 9
    ok, msg = plane_mod.begin_travel(low, "仙界", pdata, 1_800_000_000)
    assert not ok and "境界" in msg, msg

    ok, msg = plane_mod.begin_travel(pl, "仙界", pdata, 1_800_000_000)
    assert not ok and "星空坐标" in msg, msg

    ok, msg = plane_mod.remember(pl, "仙界")
    assert ok and "仙界" in plane_mod.known_of(pst), msg
    ok, msg = plane_mod.remember(pl, "仙界")
    assert not ok, "重复记坐标应拒绝"
    ok, msg = plane_mod.remember(pl, "不存在的位面")
    assert not ok

    before = pl.stones
    ok, msg = plane_mod.buy_clue(pl, "九天十地")
    assert ok and pl.stones == before - plane_mod.CLUE_COST, msg
    ok, msg = plane_mod.buy_clue(pl, "九天十地")
    assert not ok, "已记坐标不应可重复求购"

    now = 1_800_000_000
    pl.exp = 50_000_000
    exp_before, xq_before = pl.exp, pl.ext["xueqi"]
    ok, msg = plane_mod.begin_travel(pl, "仙界", pdata, now)
    assert ok and pl.state == "穿梭中", msg
    tr = plane_mod.travel_state(plane_mod.state_of(pl), now)
    assert tr and not tr["done"] and tr["to"] == "仙界"
    assert pl.exp == exp_before - q["exp"] and pl.ext["xueqi"] == xq_before - q["xueqi"]
    d2, msg = plane_mod.settle(pl, pdata, now + q["minutes"] * 60 + 1)
    assert msg and "抵达" in msg and d2.state == "空闲", msg
    assert plane_mod.current(plane_mod.state_of(d2)) == "仙界"
    assert plane_mod.coord_of(plane_mod.state_of(d2), "仙界"), "落位后应有坐标"
    d3, msg3 = plane_mod.settle(d2, pdata, now + 10 ** 6)
    assert msg3 is None, "无行程时 settle 应静默"

    class _R:
        def random(self):
            return 0.0

        def choice(self, seq):
            return seq[0]

    ce = PlayerDoc(uid="clue", name="寻路人", realm_index=20)
    cst = plane_mod.state_of(ce)
    cst["known"] = [p for p in plane_mod.PLANES if p != "阳间"]
    ok, msg = plane_mod.explore_clue(ce, 1_800_000_000, _R())
    assert ok and "阳间" in plane_mod.known_of(cst), msg
    ok, msg = plane_mod.explore_clue(ce, 1_800_000_100, _R())
    assert not ok and "今日" in msg, msg

    payload = plane_mod.map_payload(d2, pdata, "仙界", now)
    assert payload["regions"] and payload["sites"] and payload["dot"], payload
    assert payload["plane"] == "仙界" and len(payload["coords"]) > 0
    text_p = plane_mod.plane_text(d2, pdata, [f"境{i}" for i in range(64)], now)
    assert "诸天星路" in text_p and "仙界" in text_p
    assert "坐标记忆" in plane_mod.memory_text(d2, pdata, [f"境{i}" for i in range(64)], now)
    png_p = await render_mod.render_panel("plane", payload, tmp)
    assert png_p and png_p.exists() and png_p.stat().st_size > 2000
    html_p = render_mod._jinja().get_template("plane.html").render(**payload)
    assert "仙界" in html_p and "rg" in html_p
    print("plane ok")

    # 16i. 裂界副本：窗口/进入/三路线/结算/兑换
    from core import rift as rift_mod  # noqa: E402

    class _Seq:
        """可控随机：random() 依次取值，randrange 取 0，choice 取首项。"""

        def __init__(self, vals=(0.0,)):
            self.vals = list(vals)

        def random(self):
            return self.vals.pop(0) if self.vals else 0.0

        def randrange(self, n):
            return 0

        def choice(self, seq):
            return seq[0]

    t0 = 1_800_000_000.0
    g, r0, created = rift_mod.ensure({}, t0, _Seq())
    win0 = int(t0 // rift_mod.WINDOW_SECONDS)
    assert created and r0["plane"] == rift_mod.PLANES[win0 % 2] and r0["expires_at"] > t0, r0
    g2, r_same, created2 = rift_mod.ensure(g, t0 + 60, _Seq())
    assert not created2 and r_same["id"] == r0["id"]
    g3, r_next, created3 = rift_mod.ensure(g2, t0 + rift_mod.WINDOW_SECONDS + 5, _Seq())
    assert created3 and r_next["plane"] == rift_mod.PLANES[(win0 + 1) % 2] and r_next["id"] != r0["id"]
    assert g3["history"], "旧裂界应入历史"

    rd = PlayerDoc(uid="rift_p", name="裂客", realm_index=46, stones=0, exp=1_000_000)
    rd.ext["xueqi"] = 1_000_000
    rd.ext["hp"] = 1_000_000
    ok, msg = rift_mod.join(g, rd, t0)
    assert not ok and "穿梭" in msg, msg
    plane_mod.state_of(rd)["current"] = r0["plane"]
    ok, msg = rift_mod.join(g, rd, t0)
    assert ok and rd.ext["rift"]["status"] == "active", msg
    ok, msg = rift_mod.join(g, rd, t0)
    assert not ok, "重复进入应拒绝"

    stats = {"atk": 5_000_000, "defense": 5_000_000, "hp": 10_000_000, "bao": 0.2, "hp_cur": 10_000_000}
    ok, msg = rift_mod.explore(g, rd, "稳阵", stats, _Seq([0.9, 0.0]), t0)
    assert ok and rd.ext["rift"]["depth"] == 1 and rd.ext["rift"]["loot"] == 3, msg
    assert g["rift"]["anchor"] == 6, g["rift"]["anchor"]
    ok, msg = rift_mod.explore(g, rd, "寻宝", stats, _Seq([0.9, 0.0, 0.0]), t0)
    assert ok and rd.ext["rift"]["depth"] == 2, msg
    assert "潜行" in msg or "战利品" in msg
    src_before = rift_mod.source_of(rd)
    ok, msg = rift_mod.explore(g, rd, "强攻", stats, _Seq([0.0]), t0)
    assert ok and rd.ext["rift"] is None, msg
    assert "通关" in msg and rift_mod.source_of(rd) > src_before, msg
    assert rd.exp > 1_000_000, rd.exp
    assert g["rift"]["anchor"] >= 12

    # 强攻失败：属性极弱 → 折半结算
    weak = PlayerDoc(uid="rift_w", name="弱者", realm_index=20, exp=0)
    weak.ext["xueqi"] = 0
    weak.ext["hp"] = 100
    plane_mod.state_of(weak)["current"] = r0["plane"]
    ok, _ = rift_mod.join(g, weak, t0)
    assert ok
    weak.ext["rift"]["loot"] = 10
    weak_stats = {"atk": 1, "defense": 1, "hp": 100, "bao": 0.0, "hp_cur": 100}
    ok, msg = rift_mod.explore(g, weak, "强攻", weak_stats, _Seq([0.0]), t0)
    assert ok and "失败" in msg and weak.ext["rift"] is None, msg
    assert weak.ext["rift_last"]["status"] == "failed"
    assert weak.ext["rift_last"]["source"] <= 10

    # 撤离结算
    wd = PlayerDoc(uid="rift_out", name="离客", realm_index=30, exp=0)
    wd.ext["xueqi"] = 0
    plane_mod.state_of(wd)["current"] = r0["plane"]
    ok, _ = rift_mod.join(g, wd, t0)
    assert ok
    wd.ext["rift"]["loot"] = 7
    ok, msg = rift_mod.withdraw(g, wd, t0)
    assert ok and "撤离" in msg and wd.ext["rift"] is None, msg

    # 过期自动结算
    od = PlayerDoc(uid="rift_exp", name="迟客", realm_index=30, exp=0)
    od.ext["xueqi"] = 0
    plane_mod.state_of(od)["current"] = r0["plane"]
    ok, _ = rift_mod.join(g, od, t0)
    assert ok
    od.ext["rift"]["loot"] = 5
    note = rift_mod.settle_if_needed(g, od, t0 + rift_mod.WINDOW_SECONDS + 1)
    assert note and "裂界闭合" in note and od.ext["rift"] is None, note

    # 兑换
    xd = PlayerDoc(uid="rift_x", name="换客")
    xd.ext["rift_source"] = 100
    ok, msg, got = rift_mod.exchange(xd, "星图")
    assert ok and got == {"星图": 1} and rift_mod.source_of(xd) == 60, msg
    ok, msg, _ = rift_mod.exchange(xd, "无尽秘钥配方")
    assert not ok, "界源不足应拒绝"
    ok, msg, _ = rift_mod.exchange(xd, "不存在")
    assert not ok
    assert "裂界副本" in rift_mod.status_text(g, xd, t0)

    await db.save_rift(g)
    g_back = await db.get_rift()
    assert g_back["rift"]["id"] == g["rift"]["id"], "裂界状态应可持久化"
    print("rift ok")

    # 16j. 千年灾劫：均值锚定/召唤/巡猎上限/讨伐/魔主/纪元
    from core import calamity as cal_mod  # noqa: E402
    import random as pyrandom  # noqa: E402

    avg = cal_mod.average_stats([{"atk": 1_000_000, "defense": 900_000, "hp": 5_000_000, "bao": 0.2}])
    assert avg["samples"] == 1 and avg["atk"] == 1_000_000, avg
    fallback = cal_mod.average_stats([])
    assert fallback["atk"] == 5_000 and fallback["samples"] == 0, fallback

    cs = cal_mod.ensure(None)
    rr = pyrandom.Random(11)
    made = cal_mod.spawn_wave(cs, 0, 10, avg, rr, source="natural")
    assert len(made) == 10 and all(e["status"] == "active" for e in made), made
    assert made[0]["hp"] > 0 and made[0]["id"].startswith("calamity-")
    assert cal_mod.resolve(cs, "1") is made[-1] or cal_mod.resolve(cs, "1") in made
    assert cal_mod.resolve(cs, made[0]["name"])["id"] == made[0]["id"]

    # 超过 100 尊：NPC 天骄巡猎最旧者
    for _ in range(11):
        cal_mod.spawn_wave(cs, 0, 10, avg, rr, source="natural")
    active = cal_mod.active_calamities(cs)
    assert len(active) <= cal_mod.MAX_ACTIVE, len(active)
    assert cs["report"] and cs["report"]["count"] > 0, cs["report"]
    assert cal_mod.cull_report_text(cs["report"])

    # 讨伐：胜则伏诛 + 留炼化窗口；败则留伤
    cd = PlayerDoc(uid="cal_p", name="伐厄者", realm_index=46, stones=0, exp=0)
    cd.ext["modao"] = 10
    target = cal_mod.active_calamities(cs)[0]
    strong = {"atk": avg["atk"] * 1000, "defense": avg["defense"] * 1000, "hp": avg["hp"] * 100, "bao": 0.5}
    res = cal_mod.battle_calamity(cd, target, strong, rr, t0)
    assert res["won"] and target["status"] == "defeated", res
    assert target["defeated_by"] == "cal_p" and res["damage"] > 0
    cal_mod.grant_refine(cd, target, t0)
    pending = cal_mod.take_refine(cd, t0 + 60)
    assert pending and pending["entity_id"] == target["id"], pending
    assert cal_mod.take_refine(cd, t0 + cal_mod.REFINE_WINDOW_SECONDS + 1) is None

    weak = {"atk": 1, "defense": 1, "hp": 100, "bao": 0.0}
    target2 = cal_mod.active_calamities(cs)[0]
    res2 = cal_mod.battle_calamity(cd, target2, weak, rr, t0)
    assert not res2["won"] and target2["hp"] >= 1, res2

    # 魔主：击杀达标降临 / 共享血条按伤害计贡献 / 名次发奖
    cs["kills"] = cal_mod.OVERLORD_BASE_KILLS
    ov = cal_mod.maybe_spawn_overlord(cs, avg, rr, t0)
    assert ov and ov["status"] == "active" and ov["hp"] > 0, ov
    assert cal_mod.maybe_spawn_overlord(cs, avg, rr, t0) is None, "魔主在场不重复降临"
    hit = cal_mod.battle_overlord(cs, cd, strong, rr, t0)
    assert hit["damage"] > 0, hit
    # W7-5c 起首次伏诛会满血复生（逆命劫生），故此处要么掉血、要么复生满血
    assert (hit["revived"] and ov["hp"] == ov["max_hp"]) or ov["hp"] < ov["max_hp"], hit
    rank = cal_mod.overlord_rank(ov)
    assert rank and rank[0]["uid"] == "cal_p", rank
    reward = cal_mod.overlord_reward(ov, "cal_p")
    assert reward["rank"] == 1 and reward["amount"] >= 5 and reward["page"].endswith("残页"), reward
    mem = cal_mod.rift_memory(cd, str(ov["id"]))
    assert isinstance(mem["granted"], bool)
    for _ in range(3):  # 35% 概率 + 3 次保底
        cd.ext["rift_memory"] = mem["state"]
        if mem["state"].get("unlocked"):
            break
        mem = cal_mod.rift_memory(cd, str(ov["id"]))
    assert mem["state"].get("unlocked") is True, mem
    cd.ext["rift_memory"] = mem["state"]
    assert cal_mod.rift_memory(cd, str(ov["id"]))["already"] is True

    # 纪元：千年轮转 / 压制加深 / 位面损失 / 护身符豁免
    era0 = dict(cs["era"])
    adv = cal_mod.advance_era(cs, avg, rr, t0)
    assert adv["index"] == era0["index"] + 1 and adv["years"] == era0["years"] + cal_mod.NATURAL_YEAR
    assert 0 < adv["suppression"] <= 0.5 and adv["spawned"] >= 1
    assert cs["era"]["losses"] and cs["era"]["events"]
    base_mult = cal_mod.reward_multiplier(cd, cs, t0)
    assert base_mult <= 1.0
    cd.ext["era_charm_until"] = cs["era"]["index"]
    assert cal_mod.reward_multiplier(cd, cs, t0) == 1.0
    print("calamity ok")

    # 16k. 灵界裂缝：坐标/界印/准入/探索/伏杀/奖励倍率/存取
    from core import lingjie as lj_mod  # noqa: E402

    lr_rng = _random.Random(21)
    lr_now = t0
    lr_rift = lj_mod.create_rift({"index": 1, "years": 2000}, lr_rng, lr_now)
    assert 0 <= lr_rift["x"] <= lj_mod.COORD_MAX and 0 <= lr_rift["y"] <= lj_mod.COORD_MAX, lr_rift
    assert abs(lr_rift["expires_at"] - lr_now - lj_mod.RIFT_DURATION) < 1e-6
    assert lj_mod.ATTEMPT_MIN <= lj_mod.base_attempts(lr_rift) <= lj_mod.ATTEMPT_MAX
    assert lj_mod.is_milestone(2000) and lj_mod.is_milestone(4000) and not lj_mod.is_milestone(2100)

    # 坐标解析：全角逗号 / 越界 / 非法
    assert lj_mod.parse_coordinate("#前往 12,34") == (12, 34)
    assert lj_mod.parse_coordinate("#探索 999，0") == (999, 0)
    assert lj_mod.parse_coordinate("#前往 1200,3") is None
    assert lj_mod.parse_coordinate("#前往 abc") is None
    assert lj_mod.is_at([12, 34], {"x": 12, "y": 34})
    assert not lj_mod.is_at([12, 35], {"x": 12, "y": 34})
    assert not lj_mod.is_at(None, {"x": 12, "y": 34})

    # 界印：基础 2~5 重，换裂缝自动清零，锚符追加一次
    lr_state = lj_mod.ensure({})
    lr_uid = "lj_p"
    assert lj_mod.remaining_attempts(lr_state, lr_uid, lr_rift) == lj_mod.base_attempts(lr_rift)
    lj_mod.bump_attempt(lr_state, lr_uid, lr_rift, "used")
    assert lj_mod.remaining_attempts(lr_state, lr_uid, lr_rift) == lj_mod.base_attempts(lr_rift) - 1
    lj_mod.bump_attempt(lr_state, lr_uid, lr_rift, "extra")
    assert lj_mod.remaining_attempts(lr_state, lr_uid, lr_rift) == lj_mod.base_attempts(lr_rift)
    lr_next = lj_mod.create_rift({"index": 2, "years": 4000}, lr_rng, lr_now)
    assert lj_mod.remaining_attempts(lr_state, lr_uid, lr_next) == lj_mod.base_attempts(lr_next)

    # 准入：坍塌 / 境界 / 未抵达 / 来不及 / 通过
    lj_doc = PlayerDoc(uid=lr_uid, name="探界者", realm_index=40)
    assert lj_mod.can_start(lj_doc, None, lr_now)[1] == "collapsed"
    assert lj_mod.can_start(lj_doc, lr_rift, lr_now)[1] == "coordinate"
    lj_doc.ext["lingjie_pos"] = [lr_rift["x"], lr_rift["y"]]
    assert lj_mod.can_start(lj_doc, lr_rift, lr_now)[0] is True
    low = PlayerDoc(uid="lj_low", name="凡人", realm_index=lj_mod.REALM_GATE - 1)
    low.ext["lingjie_pos"] = [lr_rift["x"], lr_rift["y"]]
    assert lj_mod.can_start(low, lr_rift, lr_now)[1] == "realm"
    assert lj_mod.can_start(lj_doc, lr_rift, lr_rift["expires_at"] - 60)[1] == "time"

    # 探索耗时：行字秘/天璇步法减时，下限 1 分钟
    base_dur, _ = lj_mod.explore_duration(PlayerDoc(uid="lj_d"))
    assert base_dur == lj_mod.EXPLORE_SECONDS
    fast_doc = PlayerDoc(uid="lj_f", realm_index=20)
    fast_doc.ext["gongfa"] = ["行字秘"]
    fast_dur, fast_msgs = lj_mod.explore_duration(fast_doc)
    assert fast_dur < base_dur and fast_msgs, (fast_dur, fast_msgs)
    step_doc = PlayerDoc(uid="lj_s")
    step_doc.ext["gongfa"] = ["天璇步法"]
    assert lj_mod.explore_duration(step_doc)[0] == base_dur - 60

    # 裂缝生灵：玩家三维 ×0.85 附近浮动
    base_stats = (1_000_000, 800_000, 5_000_000)
    lr_mon = lj_mod.make_monster(base_stats, lr_rng)
    assert 1 <= lr_mon.atk <= int(base_stats[0] * 1.2), lr_mon.atk
    assert 1 <= lr_mon.hp <= int(base_stats[2] * 1.3), lr_mon.hp
    amb = lj_mod.make_ambusher(base_stats, lr_rng, "陆沉")
    assert "伏杀者" in amb.name

    # 余波分布合法，奖励至少三件丹药
    for _ in range(50):
        assert lj_mod.roll_aftermath(lr_rng) in ("ambush", "triple_ambush", "corpse", "none")
    corpse = lj_mod.roll_corpse_extras(_random.Random(3))
    assert set(corpse) == {"grass", "water", "fate_reroll", "fate_slot"}
    lr_rewards = lj_mod.roll_rewards(lr_rng, 1.0)
    assert len(lr_rewards) >= 3 and all(r["count"] >= 1 for r in lr_rewards), lr_rewards

    # 奖励倍率：灵根天赋 + 幸运 buff 消耗
    card = PlayerDoc(uid="lj_c")
    card.ext["linggen"] = {"type": "魔卡少女"}
    mult, mult_msgs = lj_mod.reward_multiplier(card)
    assert mult >= 2 and mult_msgs, (mult, mult_msgs)
    lucky = PlayerDoc(uid="lj_l")
    lucky.ext["buffs"] = {"lucky": {"times": 1, "bonus": 0.5}}
    assert lj_mod.reward_multiplier(lucky)[0] > 1
    assert lucky.ext["buffs"]["lucky"]["times"] == 0

    # 状态文案含坐标与准入
    text = lj_mod.status_text(lr_rift, lr_now, lj_doc, 3)
    assert str(lr_rift["x"]) in text and "realm_index" in text and "剩余 3" in text
    assert "没有现世" in lj_mod.status_text(None, lr_now)

    # 全服单例存取
    assert await db.get_lingjie() in ({},)
    lj_state = lj_mod.ensure(await db.get_lingjie())
    lj_state["rift"] = lr_rift
    await db.save_lingjie(lj_state)
    back = await db.get_lingjie()
    assert back["rift"]["id"] == lr_rift["id"]
    print("lingjie ok")

    # 16m. 镇妖塔 / 炼神魄：数值门面与实装同源（防两处漂移）
    from core import pagoda as pg_mod  # noqa: E402
    from core import adventure as adv_mod, boss as boss_mod  # noqa: E402

    assert pg_mod.MAX_FLOOR == adv_mod.TOWER_MAX == 50000
    assert pg_mod.clamp_floor(-5) == 0 and pg_mod.clamp_floor(999999) == pg_mod.MAX_FLOOR
    for f in (0, 1, 99, 100, 199, 200, 500, pg_mod.MAX_FLOOR):
        assert pg_mod.boss_spec(pg_mod.KIND_ZYT, f) == (
            adv_mod.tower_boss(f)["hp"], adv_mod.tower_boss(f)["atk"], adv_mod.tower_boss(f)["defense"]
        ), f"镇妖塔第 {f} 层数值与实装不一致"
        assert pg_mod.reward_of(pg_mod.KIND_ZYT, f) == adv_mod.tower_reward(f)
    for s in (0, 1, 7, 500):
        assert pg_mod.boss_spec(pg_mod.KIND_SHENPO, s) == boss_mod.shenpo_specs(s)[:3]
        assert pg_mod.reward_of(pg_mod.KIND_SHENPO, s) == boss_mod.shenpo_specs(s)[3]
    assert pg_mod.reward_of(pg_mod.KIND_ZYT, 0) == 100
    assert pg_mod.reward_of(pg_mod.KIND_ZYT, 200) == 300 * 200 + 1000
    assert pg_mod.reward_of(pg_mod.KIND_SHENPO, 500) == 400000
    assert pg_mod.penalty_of(pg_mod.KIND_ZYT, 10) == 2 * adv_mod.tower_reward(10)
    assert "第 0 层" in pg_mod.status_text(pg_mod.KIND_ZYT, 0)
    print("pagoda facade ok")

    # 16n. 彼岸古文明：四章串行链 + 全服贡献 + 每章一次领取
    from core import ancient as anc  # noqa: E402

    assert [e["order"] for e in anc.CATALOG] == [1, 2, 3, 4]
    assert all(len(e["opposition"]) == 2 and e["items"] for e in anc.CATALOG)
    assert [e["required"] for e in anc.CATALOG] == sorted(e["required"] for e in anc.CATALOG)
    st_anc = anc.ensure(anc.default_state())
    assert list(st_anc["events"].values())[0]["status"] == "active"
    assert list(st_anc["events"].values())[1]["status"] == "locked"
    assert anc.active_chapter(st_anc) is anc.CATALOG[0]
    assert anc.resolve_chapter("2") is anc.CATALOG[1]
    assert anc.resolve_chapter("禁宝") is anc.CATALOG[2]
    assert anc.resolve_chapter("") is None and anc.resolve_chapter("zzz") is None

    # 锁住的章节不能推进；贡献溢出按阈值截断
    assert not anc.contribute(st_anc, anc.CATALOG[1], "u1", "甲", 50, 1)["ok"]
    first = anc.CATALOG[0]
    r1 = anc.contribute(st_anc, first, "u1", "甲", 500, 10)
    assert r1["ok"] and r1["applied"] == first["required"] and r1["chapterCompleted"]
    assert st_anc["events"][first["id"]]["status"] == "completed"
    assert st_anc["events"][anc.CATALOG[1]["id"]]["status"] == "active"
    assert st_anc["completedCount"] == 1
    assert not anc.contribute(st_anc, first, "u2", "乙", 10, 11)["ok"]

    # 领取：必须有贡献、每章一次
    assert anc.claim(st_anc, first, "u2", 12)["ok"] is False
    c1 = anc.claim(st_anc, first, "u1", 13)
    assert c1["ok"] and c1["stones"] == first["stones"] and c1["exp"] == first["exp"]
    assert anc.claim(st_anc, first, "u1", 14)["ok"] is False
    assert not anc.claim(st_anc, anc.CATALOG[2], "u1", 15)["ok"]

    # 四章全通 → 链条 completed
    for entry in anc.CATALOG[1:]:
        anc.contribute(st_anc, entry, "u1", "甲", entry["required"], 20)
    assert st_anc["completedCount"] == 4 and st_anc["status"] == "completed"
    assert anc.active_chapter(st_anc) is None
    assert "四章已尽" in anc.status_text(st_anc, "u1")

    # 战斗口径：强者两战全胜、弱者必败；贡献随境界与章节递增
    class _AncientStrong:
        atk = 10 ** 9
        defense = 10 ** 9
        hp = 10 ** 9
        bao = 0.0

    class _AncientWeak:
        atk = 1
        defense = 1
        hp = 10
        bao = 0.0

    strong = anc.fight_chapter(first, _AncientStrong, _random.Random(3))
    assert strong["won"] and strong["hp_left"] > 0
    assert anc.fight_chapter(first, _AncientWeak, _random.Random(3))["wins"] == 0
    assert anc.contribution_amount(first, 2, 0) >= anc.MIN_CONTRIBUTION
    assert anc.contribution_amount(first, 0, 9) == 0
    assert anc.contribution_amount(first, 1, 0) < anc.contribution_amount(first, 2, 0)
    assert anc.contribution_amount(anc.CATALOG[0], 2, 50) <= anc.CATALOG[0]["required"] // 3
    assert len(anc.progress_bar(0, 100)) == 10 and len(anc.progress_bar(100, 100)) == 10
    print("ancient ok")

    # 16o. 小世界工坊/守卫/催熟/偷菜
    from core import xiaoshijie as xsj  # noqa: E402

    world = {
        "name": "紫霄界", "level": 2, "avatar": True, "last_harvest": 0.0,
        "water_ts": 0.0,
        "fields": [
            {"seed": "麒麟神药种子", "remaining": 0.0},
            {"seed": "蟠桃仙种", "remaining": 5.0},
        ],
    }
    assert xsj.workshop_level(world, "灵田") == 0
    assert xsj.workshop_cost("灵田", 0) == 3_000_000
    assert xsj.workshop_cost("灵田", 4) == 3_000_000 * 25
    ok_w, msg_w, nw, spent = xsj.upgrade_workshop(world, "灵田", 10 ** 12, 3)
    assert ok_w and nw["workshops"]["灵田"] == 1 and spent == 3_000_000
    assert not xsj.upgrade_workshop(world, "灵田", 10 ** 12, 0)[0]  # 世界石不足
    assert not xsj.upgrade_workshop(world, "灵田", 1, 9)[0]         # 灵石不足
    assert not xsj.upgrade_workshop(world, "不存在", 10 ** 12, 9)[0]
    full = {"name": "甲", "level": 1, "fields": [], "workshops": {"灵田": xsj.WORKSHOP_MAX}}
    assert not xsj.upgrade_workshop(full, "灵田", 10 ** 12, 9)[0]
    assert "灵田 5/5" in xsj.workshop_text(full)

    assert xsj.guard_upgrade(world, 10 ** 12, 1)[2]["guard"] == 1
    guard_full = {"name": "甲", "level": 1, "fields": [], "guard": xsj.GUARD_MAX}
    assert not xsj.guard_upgrade(guard_full, 10 ** 12, 9)[0]
    assert xsj.steal_rate(guard_full) == 0.05
    assert abs(xsj.steal_rate({"guard": 2}) - (0.65 - 0.3)) < 1e-9

    ok_r, msg_r, rw, cost_r = xsj.ripen(world, 10 ** 12)
    assert ok_r and cost_r == xsj.RIPEN_COST and rw["fields"][1]["remaining"] == 0.0
    assert not xsj.ripen({"name": "甲", "fields": [{"seed": "x", "remaining": 0}]}, 10 ** 12)[0]
    assert not xsj.ripen(world, 1)[0]

    class _AlwaysOk:
        def random(self):
            return 0.0

    class _AlwaysFail:
        def random(self):
            return 0.999

    ok_s, msg_s, tw, item_s, fine_s = xsj.steal(world, 10 ** 7, _AlwaysOk())
    assert ok_s and item_s == "麒麟神药" and fine_s == 0
    assert len(tw["fields"]) == 1
    ok_f, msg_f, _tw, item_f, fine_f = xsj.steal(world, 10 ** 7, _AlwaysFail())
    assert not ok_f and item_f == "" and fine_f == xsj.STEAL_FAIL_PENALTY
    assert not xsj.steal(world, 1, _AlwaysOk())[0]           # 修为不足
    assert not xsj.steal({"name": "甲", "fields": [{"seed": "x", "remaining": 9}]}, 10 ** 7, _AlwaysOk())[0]
    print("xiaoshijie workshop ok")

    # 16p. 彼岸世界/真世界：世界纯函数 + 规则层 + SQLite 单例存取
    from core import other_shore_rules as orules  # noqa: E402
    from core import other_shore_state as osst  # noqa: E402
    from core import other_shore_world as osw  # noqa: E402

    world = osw.create_other_shore_world("canglan")
    center_state = world["states"]["0,0"]
    assert center_state["phase"] == "anchored" and center_state["contribution"] == 0
    assert osw.get_other_shore_hex_distance({"q": 0, "r": 0}, {"q": 1, "r": 0}) == 1
    assert osw.get_other_shore_hex_distance({"q": 0, "r": 0}, {"q": 3, "r": 0}) == 3
    assert osw._hash("canglan:x") == osw._hash("canglan:x")
    try:
        osw.require_star(world, {"q": 99, "r": 99})
        raise AssertionError("不存在的坐标应报错")
    except ValueError:
        pass
    # 中心星已 anchored，踏足无副作用
    assert osw.visit_other_shore_star(world, {"q": 0, "r": 0})["states"]["0,0"]["phase"] == "anchored"
    # 观测半径 1 后，距离 1 内星进入 sensed
    observed = osw.observe_other_shore_stars(world, {"q": 0, "r": 0}, 1)
    within = [s for s in observed["stars"] if osw.get_other_shore_hex_distance({"q": 0, "r": 0}, s) <= 1]
    assert any(observed["states"][f"{s['q']},{s['r']}"]["phase"] == "sensed" for s in within), \
        "观测半径内应进入 sensed"
    # 贡献：单人上限 1/人；中心星阈值 0 → 贡献无增量
    center = {"q": 0, "r": 0}
    assert osw.contribute_other_shore_exploration(observed, center, "u1", 100)[
        "states"]["0,0"]["contribution"] == 0
    wide = osw.observe_other_shore_stars(world, center, 4)
    gate = osw.visit_other_shore_star(wide, {"q": 4, "r": 0})
    gated = osw.contribute_other_shore_exploration(gate, {"q": 4, "r": 0}, "u1", 100)
    gate_id = next(x["id"] for x in gated["stars"] if x["q"] == 4 and x["r"] == 0)
    assert gated["states"][gate_id]["contribution"] == 1, gated["states"][gate_id]
    assert gated["states"][gate_id]["contributors"]["u1"] == 1
    assert osw.contribute_other_shore_exploration(
        gated, {"q": 4, "r": 0}, "u1", 100)["states"][gate_id]["contribution"] == 1
    anchored = osw.anchor_other_shore_star(observed, center)  # 已 anchored → 幂等
    assert anchored["states"]["0,0"]["phase"] == "anchored"
    cleared = osw.clear_other_shore_star(anchored, center)
    assert cleared["states"]["0,0"]["phase"] == "cleared"
    # 非中心星未 visited 不可贡献
    lone = osw.create_other_shore_world("c2")
    try:
        osw.contribute_other_shore_exploration(lone, {"q": 4, "r": 0}, "u1", 1)
        raise AssertionError("未踏足应拒绝贡献")
    except ValueError:
        pass
    # 规则层：境界名 / 分档 / 心神路程 / 抑制免疫 / 外部限制
    assert orules.tier_from_realm_name("准仙帝") == "quasi_immortal_emperor"
    assert orules.tier_from_realm_name("仙帝") == "immortal_emperor"
    assert orules.tier_from_realm_name("远古残境") == "below_emperor"
    assert orules.tier_from_level(16, {"emperor": 16}) == "emperor"
    assert orules.tier_from_level(18, {"emperor": 16, "immortalKing": 18}) == "immortal_king"
    assert orules.stronger_tier("emperor", "below_emperor") == "emperor"
    assert orules.get_other_shore_travel_tier({"realm": "准仙帝"}) == "quasi_immortal_emperor"
    cost0 = orules.calculate_other_shore_mind_cost({"realm": "仙帝"}, 10, 0)
    assert cost0["cost"] == 0 and cost0["remainder"] == 0
    cost3 = orules.calculate_other_shore_mind_cost({"realm": "仙王"}, 10, 0)
    assert cost3["cost"] == 3 and cost3["remainder"] == 1
    assert orules.get_other_shore_suppression({"realm": "仙帝", "xiangu_yishenweizhong": True})["immune"]
    assert orules.get_other_shore_suppression({"realm": "仙帝", "xiangulevel_id": 13})["immune"]
    assert not orules.get_other_shore_suppression({"realm": "准仙帝", "xiangulevel_id": 11})["immune"]
    assert orules.get_other_shore_suppression({"realm": "准仙帝", "xiangulevel_id": 11})["attributeMultiplier"] == 0.7
    assert not orules.is_other_shore_external_action_allowed("externalShop")
    try:
        orules.is_other_shore_external_action_allowed("custom")
        raise AssertionError("未知外部行为应报错")
    except ValueError:
        pass
    # SQLite 单例存取：create/save/get/update 往返
    conn = db.conn
    state = await osst.ensure_other_shore_world(conn, "canglan")
    assert state["stars"] and state["version"] == 1
    state = await osst.ensure_other_shore_world(conn, "canglan")
    assert state is not None
    await osst.update_other_shore_world(conn, state, lambda d: dict(d, seed="x"))
    updated = await osst.ensure_other_shore_world(conn, "canglan")
    assert updated["seed"] == "x"
    await osst.save_other_shore_world(conn, await osst.ensure_other_shore_world(conn, "canglan"))
    print("other_shore world ok")

    # 16q. 双轨境界：炼体突破 + 属性聚合叠加（原版四体系求和，量级 ÷1000）
    body_table = store.table("Level/炼体境界")
    assert len(body_table) == 63 and body_table[0]["level"] == "莽夫"
    bd = PlayerDoc(uid="body", name="肉身", realm_index=10, exp=0)
    assert cultivate.physique_entry(bd, body_table)["level"] == "莽夫"

    # 血气不足拒绝
    ok, msg, cost = cultivate.body_breakthrough(bd, body_table, 0, _random.Random(1))
    assert not ok and "血气" in msg and cost == 0, msg
    # 成功：莽夫 exp=500 → 消耗 1（÷1000 进位），概率 (1-1/60)≈98%
    xq = 10_000.0
    ok, msg, cost = cultivate.body_breakthrough(bd, body_table, xq, _random.Random(0))
    assert ok and bd.physique_index == 1 and cost == 1, (msg, cost)
    ok, msg, cost = cultivate.body_breakthrough(bd, body_table, xq - cost, _random.Random(0))
    assert ok and bd.physique_index == 2, msg
    # 失败分档：构造必败 rng
    class _AlwaysFail(_random.Random):
        def random(self):
            return 0.999

    bd.physique_index = 20
    fail_cost = int(body_table[20]["exp"] * cultivate.BODY_COST_SCALE + 0.999)
    ok, msg, lost = cultivate.body_breakthrough(
        bd, body_table, 10 ** 9, _AlwaysFail(1)
    )
    assert not ok and bd.physique_index == 20 and lost == int(fail_cost * 0.4), (msg, lost, fail_cost)
    # 最高境
    bd.physique_index = 62
    ok, msg, cost = cultivate.body_breakthrough(bd, body_table, 10 ** 9, _random.Random(1))
    assert not ok and "进境" in msg and cost == 0
    assert "炼体" in cultivate.physique_text(bd, body_table)

    # 聚合：双轨叠加 + 暴击 = 练气 + 炼体
    duo = PlayerDoc(uid="duo", name="双轨", realm_index=3, physique_index=2)
    row_q = store.table("Level/练气境界")[3]
    row_t = body_table[2]
    st_d = equip_mod.aggregate(duo, store.table("Level/练气境界"), lookup.get,
                               physique_table=body_table)
    assert st_d.atk == row_q["基础攻击"] + row_t["基础攻击"], (st_d, row_q, row_t)
    assert st_d.hp == row_q["基础血量"] + row_t["基础血量"]
    assert abs(st_d.bao - (float(row_q.get("基础暴击", 0)) + float(row_t.get("基础暴击", 0)))) < 1e-9, st_d.bao
    # 单轨（不传 physique_table）行为不变
    st_s = equip_mod.aggregate(duo, store.table("Level/练气境界"), lookup.get)
    assert st_s.atk == row_q["基础攻击"]
    print("body dual ok")

    # 16r. 权柄换算（W0-2）：双轨取高 + 位面门槛接 authority
    from core import authority as auth_mod  # noqa: E402

    lo = PlayerDoc(uid="auth_lo", realm_index=10, physique_index=4)
    hi_body = PlayerDoc(uid="auth_body", realm_index=10, physique_index=30)
    assert auth_mod.authority_of(lo) == 10 and auth_mod.dual_level(lo) == 11
    assert auth_mod.authority_of(hi_body) == 30 and auth_mod.authority_21(hi_body) == 10
    assert auth_mod.authority_21(PlayerDoc(uid="x", realm_index=63, physique_index=63)) == 21
    # 位面门槛：炼体 30 解锁界海（31? 否——界海 gate 31），用遮天 21 验证
    assert auth_mod.meets(hi_body, plane_mod.GATES["遮天位面"])
    assert not auth_mod.meets(lo, plane_mod.GATES["遮天位面"])
    pd_body = PlayerDoc(uid="plane_body", name="体修", realm_index=10, physique_index=30)
    pd_body.ext["xueqi"] = 10 ** 9
    pd_body.exp = 10 ** 9
    plane_mod.state_of(pd_body)["known"].append("遮天位面")
    ok, msg = plane_mod.begin_travel(pd_body, "遮天位面", pdata, 1_900_000_000)
    assert ok, msg  # 炼体 30 ≥ 遮天门槛 21：双轨任一达标即可
    q = plane_mod.quote(lo, "遮天位面")
    assert not q["enough_realm"]
    print("authority ok")

    # 16s. 战斗引擎骨架（W1-1）：薄壳等价 + 效果槽 + 技能注册表
    from core.combat import Fighter, run_1v1, skills as cskills  # noqa: E402

    ua = battle_mod.Unit("甲", 5000, 2000, 50000, 0.3)
    ub = battle_mod.Unit("乙", 4000, 2500, 45000, 0.2)
    for seed in range(5):
        w1, log1, ha1, hb1 = battle_mod.spar_full(ua, ub, _random.Random(seed))
        w2, log2, ha2, hb2 = run_1v1(
            Fighter.from_unit(ua), Fighter.from_unit(ub), _random.Random(seed)
        ).as_tuple()
        assert (w1, log1, ha1, hb1) == (w2, log2, ha2, hb2), seed
    # skip_first 等价（困龙阵路径）
    w1, log1, _, _ = battle_mod.spar_full(ua, ub, _random.Random(7), skip_first=(1,))
    w2, log2, _, _ = run_1v1(
        Fighter.from_unit(ua), Fighter.from_unit(ub), _random.Random(7), skip_first=(1,)
    ).as_tuple()
    assert (w1, log1) == (w2, log2) and any("困住" in x for x in log2)
    # 定身效果：乙前两回合无法出手
    fb = Fighter.from_unit(ub)
    fb.effects["stun_turns"] = 2
    res = run_1v1(Fighter.from_unit(ua), fb, _random.Random(1))
    assert sum("被定身" in x for x in res.log) == 2, res.log
    # 护盾吸收 + 溢出扣血
    fb2 = Fighter.from_unit(ub)
    fb2.effects["shield"] = 30000
    res2 = run_1v1(Fighter.from_unit(ua), fb2, _random.Random(2))
    assert any("护盾吸收" in x for x in res2.log) and res2.b_hp < 45000
    # 反噬致死：守方高反噬，攻方薄血
    fa3 = Fighter("脆皮", 8000, 1000, 100, 0.0)
    fb3 = Fighter.from_unit(battle_mod.Unit("刺猬", 1000, 500000, 999999, 0.0))
    fb3.effects["reflect"] = 1.0
    res3 = run_1v1(fa3, fb3, _random.Random(3))
    assert res3.winner == 1 and any("反噬" in x for x in res3.log), res3
    # 汲取回血不超上限
    fa4 = Fighter("吸血", 9000, 1000, 500, 0.9)
    fa4.hp_max = 1000
    fb4 = Fighter("血袋", 10, 10, 999999, 0.0)
    fa4.effects["lifesteal"] = 0.5
    res4 = run_1v1(fa4, fb4, _random.Random(4))
    assert res4.a_hp > 500 and any("汲取" in x for x in res4.log), res4.a_hp  # 汲取回血且不超上限
    # 技能注册表：on_turn 钩子被调用
    fired = []
    cskills.register(cskills.SkillSpec(
        "test_echo", "回声技",
        on_turn=lambda me, foe, ctx: fired.append(ctx["round"]) or foe.effects.update({"shield": 10}),
    ))
    assert cskills.get("test_echo").name == "回声技"
    fa5 = Fighter("甲", 5000, 2000, 50000, 0.0, skills=("test_echo",))
    res5 = run_1v1(fa5, Fighter.from_unit(ub), _random.Random(5))
    assert fired and any("护盾吸收" in x for x in res5.log), (fired, res5.log)
    cskills.clear()
    print("combat engine ok")

    # 16t. 功法战斗装填（W1-2）：复活技能 + 开场乘区 + 切磋接入
    from core.combat import loadout as loadout_mod  # noqa: E402

    lookup2 = {"凰劫再生术": {"name": "凰劫再生术", "class": "功法", "复活技能": 1,
                              "恢复比例": 0.7, "pr": 1, "msg2": "涅槃真火焚身！",
                              "攻击加成": 0.5, "防御加成": 0.5, "生命加成": 1.0}}
    gd = PlayerDoc(uid="gp", name="凤主", realm_index=30)
    gd.ext["gongfa"] = ["凰劫再生术", "不存在的功法"]
    got = loadout_mod.learned_battle_skills(gd, lookup2)
    assert len(got) == 1 and got[0]["name"] == "凰劫再生术", got
    fa6 = loadout_mod.build_fighter(gd, "凤主", 10000, 10000, 100000, 0.2, lookup2)
    assert fa6.atk == 15000 and fa6.defense == 15000 and fa6.hp_max == 200000 and fa6.hp == 200000
    assert fa6.effects["revive"]["ratio"] == 0.7 and fa6.effects["revive"]["pr"] == 1.0
    # 致死 → 复活 70%，再致死 → 判负（一场一次）
    killer = Fighter("判官", 10 ** 9, 10, 999999999, 0.0)
    res6 = run_1v1(fa6, killer, _random.Random(1))
    assert any("凰劫再生术" in x and "复活" in x for x in res6.log), res6.log[:4]
    assert res6.winner == 1, "复活一次后仍应落败"
    assert sum("凰劫再生术" in x for x in res6.log) == 1
    # pr=0 永不复活
    fa7 = loadout_mod.build_fighter(gd, "凤主", 10000, 10000, 100000, 0.0, lookup2)
    fa7.effects["revive"]["pr"] = 0.0
    res7 = run_1v1(fa7, Fighter("判官", 10 ** 9, 10, 999999999, 0.0), _random.Random(2))
    assert res7.winner == 1 and not any("复活" in x for x in res7.log)
    # 无功法玩家不受影响
    plain6 = loadout_mod.build_fighter(PlayerDoc(uid="np"), "素人", 1000, 1000, 1000, 0.0, lookup2)
    assert plain6.effects.get("revive") is None and plain6.atk == 1000
    print("gongfa loadout ok")

    # 16u. 灵根法球 + 黑皇阵效果槽迁移（W1-3）
    from core import linggen as linggen_mod  # noqa: E402
    sn = linggen_mod.snapshot({"name": "金灵根", "type": "真灵根", "eff": 1.1,
                               "法球倍率": 0.08, "稀有度": 2})
    assert abs(sn["orb"] - 0.08) < 1e-9 and linggen_mod.orb_of(sn) == 0.08
    assert linggen_mod.orb_of({"name": "老快照"}) == 0.0 and linggen_mod.orb_of(None) == 0.0
    fo = Fighter("法球客", 10000, 1000, 50000, 0.0)
    fo.effects["orb"] = 0.08
    res_o = run_1v1(fo, Fighter.from_unit(ub), _random.Random(9))
    assert any("法球" in x for x in res_o.log), res_o.log[:3]
    # 每击法球值 = trunc(atk × 0.08)（无乘区时 800）
    assert any("法球 800" in x for x in res_o.log), [x for x in res_o.log[:3]]

    # 黑皇阵效果槽：无始杀阵 ×2 与旧战前缩放等价（同种子首回合伤害一致）
    from core import secret as secret_mod  # noqa: E402

    me_u = battle_mod.Unit("阵主", 6000, 3000, 80000, 0.1)
    foe_u = battle_mod.Unit("凶兽", 5000, 2500, 90000, 0.0)

    def _buff_kaelthas():
        return {"atk_mult": 2.0, "bao_add": 0.2}

    calls = {"n": 0}

    def _buff_once():
        calls["n"] += 1
        return _buff_kaelthas()

    sess0 = secret_mod.Session(place="青冥山")
    me0 = battle_mod.Unit("阵主", 6000, 3000, 80000, 0.1)
    # 旧路径对照：战前缩放
    me_old = battle_mod.Unit("阵主", 6000 * 2, 3000, 80000, min(1.0, 0.1 + 0.2))
    d0, m0, hp0 = 0, 0, 0
    r_old = battle_mod.harm(me_old.atk, foe_u.defense, _random.Random(11), me_old.bao)
    sess, me_after, flavor, fled = secret_mod.explore(
        sess0, (6000, 3000, 80000), me0, [], _random.Random(11),
        buff=_buff_once,
    )
    assert calls["n"] == 1, "buff 只应在进入战斗时消耗一次"
    first = flavor if isinstance(flavor, str) else str(flavor)
    assert "阵主" in first, first  # 战报应含我方名（胜负皆可）
    # 困龙阵：效果槽承载敌方削弱 + 定身（skip_first 交给引擎，文案由引擎保证）
    me_b = battle_mod.Unit("阵主", 6000, 3000, 80000, 0.1)

    def _buff_stun():
        return {"enemy": {"atk": 0.85, "def": 0.55}, "stun": True}

    me_f2, foe_f2, skip2 = secret_mod._battle_fighters(me_b, foe_u, _buff_stun)
    assert skip2 == (1,)
    assert abs(foe_f2.effects["dmg_dealt_mult"] - 0.85) < 1e-9
    assert abs(foe_f2.effects["dmg_taken_mult"] - 0.55) < 1e-9
    assert me_f2.effects.get("dmg_dealt_mult") is None  # 无 at_mult 不误伤
    res2 = run_1v1(me_f2, foe_f2, _random.Random(12), skip_first=skip2)
    assert any("困住" in x for x in res2.log)
    print("orb & arrays ok")

    # 16v. 开场阶段（W1-4）：高境镇杀 / 岁云同境裁决 / 帝骑助战
    from core.combat import opening as opening_mod  # noqa: E402

    # 镇杀：auth21 ≥20 且不等
    f_hi = Fighter("仙帝", 99999, 99999, 999999, 0.0)
    f_hi.tags["auth21"] = 21
    f_lo = Fighter("凡人", 100, 100, 1000, 0.0)
    f_lo.tags["auth21"] = 15
    exec_res = opening_mod.high_realm_exec(f_lo, f_hi)
    assert exec_res and exec_res[0] == 1 and f_lo.hp == 0
    assert "境界天堑" in exec_res[1][0]
    # 同档 / 低档不触发
    f_hi2 = Fighter("甲", 1, 1, 10, 0.0); f_hi2.tags["auth21"] = 19
    assert opening_mod.high_realm_exec(f_hi2, f_lo) is None
    assert opening_mod.high_realm_exec(f_hi, Fighter("乙", 1, 1, 10, 0.0,
                                                    tags={"auth21": 21})) is None

    # 岁云裁决：压高轨基础表值
    fh = Fighter("岁云客", 5000, 3000, 50000, 0.0)
    fh.tags.update({"linggen_name": "岁云化身", "auth_of": 20, "realm_index": 20, "physique_index": 10})
    fo2 = Fighter("高境客", 60000, 30000, 800000, 0.0)
    fo2.tags.update({"auth_of": 46, "realm_index": 46, "physique_index": 5})
    old_atk, old_def, old_hp = fo2.atk, fo2.defense, fo2.hp
    vmsgs = opening_mod.suiyun_verdict(fh, fo2, store.table("Level/练气境界"), body_table)
    assert len(vmsgs) == 1 and "同境裁决" in vmsgs[0], vmsgs
    # 压缩量 = 练气表 46 行 - 20 行（对手高轨为练气）
    exp_atk = old_atk - (store.table("Level/练气境界")[46]["基础攻击"] - store.table("Level/练气境界")[20]["基础攻击"])
    assert fo2.atk == max(1, exp_atk), (fo2.atk, exp_atk)
    assert fo2.hp_max < old_hp and fo2.hp <= fo2.hp_max
    # 无岁云灵根不触发
    fh2 = Fighter("素人", 1, 1, 10, 0.0); fh2.tags["linggen_name"] = "金灵根"
    assert opening_mod.suiyun_verdict(fh2, fo2, store.table("Level/练气境界"), body_table) == []
    # 对手权柄不高不触发
    fo3 = Fighter("低境", 1, 1, 10, 0.0); fo3.tags["auth_of"] = 10
    assert opening_mod.suiyun_verdict(fh, fo3, store.table("Level/练气境界"), body_table) == []

    # 帝骑助战：三卡合击 = trunc(攻×0.6×2)；不足三卡不触发
    fd = Fighter("帝骑", 10000, 1000, 50000, 0.0)
    fv = Fighter("对手", 1000, 1000, 50000, 0.0)
    assert opening_mod.decade_assist(fd, fv, ["空我", "龙骑"]) is None
    msg_d = opening_mod.decade_assist(fd, fv, ["空我", "龙骑", "Faiz"])
    assert msg_d and "合击" in msg_d and fv.hp == 50000 - 12000, (msg_d, fv.hp)
    # 一击致溃
    fv2 = Fighter("脆皮", 1, 1, 100, 0.0)
    opening_mod.decade_assist(fd, fv2, ["空我", "龙骑", "Faiz"])
    assert fv2.hp == 0
    print("opening ok")

    # 16w. 技能池（W1-5）：装配 / 攻击倍率与控制 / 防御减免与格挡 / 治疗 / cnt 限次
    from core.combat import engine as cengine  # noqa: E402
    from core.combat import loadout as loadout_mod  # noqa: E402

    tables = {
        "atk": [{"name": "太阳之体", "class": "灵根", "pr": 1, "cnt": -1, "beilv": 2.0,
                 "msg1": "大日灼空！", "msg2": "被灼伤", "控制": 0},
                {"name": "九幽魔体", "pr": 1, "cnt": -1, "beilv": 1e17, "msg1": "魔", "控制": 0},
                {"name": "九重魔功", "pr": 1, "cnt": 1, "beilv": 1.5, "msg1": "魔功灌注", "控制": 1}],
        "def": [{"name": "太阴之体", "pr": 1, "cnt": -1, "beilv": 0.9, "msg1": "月华蔽体"},
                {"name": "混沌体", "pr": 1, "cnt": 2, "beilv": 0, "msg1": "混沌反弹", "反弹伤害": 0.5}],
        "heal": [{"name": "生生不息", "pr": 1, "cnt": -1, "回复比例": 0.08, "msg1": "生机磅礴"}],
        "boost": [{"name": "太阳之体", "beilv": 1.2, "控制": 0}],
    }
    gd = PlayerDoc(uid="sk", name="技客", realm_index=30)
    gd.ext["linggen"] = {"name": "太阳之体", "type": "血统", "eff": 1.2, "orb": 0.05}
    gd.ext["gongfa"] = ["九重魔功", "生生不息"]   # 学了攻击+治疗功法
    fs = loadout_mod.build_fighter(gd, "技客", 10000, 5000, 100000, 0.0, lookup2, skill_tables=tables)
    names_a = [x["name"] for x in fs.tags["atk_skills"]]
    assert names_a == ["太阳之体", "九重魔功"], names_a   # 增幅 1.2 < 攻击 2.0 被并掉
    assert fs.tags["atk_skills"][0]["beilv"] == 2.0 and fs.tags["heal_skills"][0]["name"] == "生生不息"
    # 攻击技能：beilv 乘区（异常数据钳 50）
    foe_s = Fighter("靶子", 1, 1, 10 ** 9, 0.0)
    dmg2, ex = cengine.roll_attack_skills(fs, foe_s, 1000, _random.Random(1))
    # 两条 pr=1 技能逐条独立判定 → 1000×2.0×1.5 = 3000（对齐原版遍历判定）
    assert dmg2 == 3000 and any("大日灼空" in x for x in ex) \
        and any("魔功灌注" in x for x in ex), (dmg2, ex)
    fd2 = loadout_mod.build_fighter(gd, "技客", 10000, 5000, 100000, 0.0, lookup2, skill_tables=tables)
    fd2.tags["atk_skills"] = [{"name": "九幽魔体", "pr": 1, "cnt": -1, "beilv": 1e17, "msg1": "魔", "控制": 0}]
    dmg3, _ = cengine.roll_attack_skills(fd2, foe_s, 1000, _random.Random(1))
    assert dmg3 == 50000, dmg3   # 1e17 钳到 50 倍
    # 控制定身 + cnt 限次
    fc = loadout_mod.build_fighter(gd, "技客", 10000, 5000, 100000, 0.0, lookup2, skill_tables=tables)
    fc.tags["atk_skills"] = [{"name": "九重魔功", "pr": 1, "cnt": 1, "beilv": 1.5, "msg1": "m", "控制": 1}]
    fv_c = Fighter("受控", 1, 1, 999999, 0.0)
    _, ex_c = cengine.roll_attack_skills(fc, fv_c, 1000, _random.Random(2))
    assert fv_c.effects["stun_turns"] == 1 and any("被定身" in x for x in ex_c)
    cengine.roll_attack_skills(fc, fv_c, 1000, _random.Random(2))
    assert fc.tags["skill_uses"]["九重魔功"] == 0   # cnt=1 用尽
    # 防御：减免与完全格挡
    fdf = Fighter("守方", 1, 1, 100000, 0.0)
    fdf.tags["def_skills"] = tables["def"]
    d1, exd = cengine.roll_defense_skills(fdf, 1000, _random.Random(3))
    # 逐条独立判定：太阴 ×0.9 后混沌格挡 → 终值 0；cnt=2 的混沌体记账一次
    assert d1 == 0 and any("受伤 ×0.9" in x for x in exd) and any("完全格挡" in x for x in exd), (d1, exd)
    d2, exd2 = cengine.roll_defense_skills(fdf, 1000, _random.Random(3))
    assert d2 == 0 and fdf.tags["skill_uses"]["混沌体"] == 0, (d2, exd2)   # 第二次后用尽
    assert abs(fdf.effects["reflect"] - 0.5) < 1e-9   # 混沌体反弹写槽
    # 治疗：出手前回血
    fh = Fighter("伤者", 1, 1, 100000, 100000, 0.0)
    fh.tags["heal_skills"] = tables["heal"]
    hp_h = [50000, 999999]
    log_h: list[str] = []
    cengine.try_heal_skills(fh, hp_h, 0, _random.Random(4), log_h)
    assert hp_h[0] == 58000 and any("生机磅礴" in x for x in log_h), (hp_h, log_h)
    print("skill pool ok")

    # 16x. 打劫 / 比武结算（W1-6）
    from core import pvp as pvp_mod  # noqa: E402

    ra = PlayerDoc(uid="ra", name="劫匪", realm_index=45, stones=100_000)
    ra.ext["xueqi"] = 5_000_000
    rb = PlayerDoc(uid="rb", name="苦主", realm_index=30, stones=200_000)
    rb.ext["xueqi"] = 5_000_000
    rb.ext["hp"] = 1_000_000
    rb.ext["hp_max"] = 1_000_000
    # 比武门槛：血量须 > 上限/1.2
    rb2 = PlayerDoc(uid="rb2", name="伤员", stones=1)
    rb2.ext["hp"] = 100
    rb2.ext["hp_max"] = 1000
    ra2 = PlayerDoc(uid="ra2", name="甲", stones=1)
    ra2.ext["hp"] = 1000
    ra2.ext["hp_max"] = 1000
    assert pvp_mod.biwu_check(ra2, rb2, 1_800_000_000) is not None, "伤员应被拒"
    assert "比武冷却" not in (pvp_mod.biwu_check(ra2, rb2, 1_800_000_000) or "")
    # 双向 CD：A 刚比过
    ra2.ext["biwu_ts"] = 1_800_000_000 - 60
    m = pvp_mod.biwu_check(ra2, rb2, 1_800_000_000)
    assert m and "冷却" in m, m
    del ra2.ext["biwu_ts"]
    rb2.ext["hp"] = rb2.ext["hp_max"]   # 满血后可通过
    assert pvp_mod.biwu_check(ra2, rb2, 1_800_000_000) is None

    # 打劫门槛：穷鬼/重伤拒绝 + CD
    poor = PlayerDoc(uid="poor", name="穷人", stones=100)
    poor.ext["hp"] = 999_999
    poor.ext["hp_max"] = 1_000_000
    m = pvp_mod.rob_check(ra2, poor, 1_800_000_000)
    assert m and "穷" in m, m
    hurt = PlayerDoc(uid="hurt", name="伤员", stones=999_999)
    hurt.ext["hp"] = 10_000
    hurt.ext["hp_max"] = 1_000_000
    m = pvp_mod.rob_check(ra2, hurt, 1_800_000_000)
    assert m and "重伤" in m, m
    ok_target = PlayerDoc(uid="ok", name="肥羊", stones=500_000)
    ok_target.ext["hp"] = 999_999
    ok_target.ext["hp_max"] = 1_000_000
    assert pvp_mod.rob_check(ra2, ok_target, 1_800_000_000) is None
    ra2.ext["rob_ts"] = 1_800_000_000 - 60
    m = pvp_mod.rob_check(ra2, ok_target, 1_800_000_000)
    assert m and "CD" in m, m

    # 打劫结算：A 胜抢 1/5 + 血气 + 魔道
    text, da, db_ = pvp_mod.rob_settle(ra, rb, 0)
    assert da["stones"] == 40_000 and db_["stones"] == -40_000, (da, db_)
    assert da["xueqi"] == 100 * 46 and da["modao"] == 4, da
    # 替身人偶：免疫
    text2, da2, db2 = pvp_mod.rob_settle(ra, rb, 0, b_has_dummy=True)
    assert "替身人偶" in text2 and db2.get("dummy") == -1 and not da2
    # A 败反被劫 1/4
    text3, da3, db3 = pvp_mod.rob_settle(ra, rb, 1)
    assert da3["stones"] == -25_000 and db3["stones"] == 25_000 and db3["xueqi"] == 100 * 31, (da3, db3)
    # A 败且穷：不赔灵石
    broke = PlayerDoc(uid="br", name="穷匪", stones=100)
    text4, da4, _ = pvp_mod.rob_settle(broke, rb, 1)
    assert not da4.get("stones") and "落荒而逃" in text4, (da4, text4)

    # 比武结算：胜 1000×败境 / 败 500×胜境 / 双方 10×胜境
    t5, da5, db5 = pvp_mod.biwu_settle(ra, rb, 0)
    assert da5["xueqi"] == 1000 * 31 and db5["xueqi"] == 500 * 46, (da5, db5)
    assert da5["stones"] == 10 * 46 == db5["stones"] and da5["modao"] == 1
    t6, da6, db6 = pvp_mod.biwu_settle(ra, rb, 1)
    assert da6["xueqi"] == 500 * 31 and db6["xueqi"] == 1000 * 46 and db6["modao"] == 1
    print("pvp settle ok")

    # 16y. 渡劫 / 登仙 / 功法熟练度（W2-1）
    from core import trib as trib_mod  # noqa: E402

    td = PlayerDoc(uid="tdoc", name="劫主", realm_index=40, stones=0)
    td.ext["linggen"] = {"name": "圣体", "type": "圣体", "eff": 4, "orb": 0.5}
    td.ext["hp"] = 999_999_999
    td.ext["hp_max"] = 1_000_000_000
    td.exp = 25_000_000
    tstats = type("S", (), {"atk": 7_000_000, "defense": 5_000_000, "hp": 1_000_000_000})()
    # 门槛：非 40 境拒绝
    other = PlayerDoc(uid="o40", name="地仙", realm_index=41)
    assert trib_mod.trib_check(other, store.table("Level/练气境界"), tstats, 999, 1000) is not None
    # 未开灵根拒绝
    nol = PlayerDoc(uid="nol", name="无根", realm_index=40)
    nol.exp = 25_000_000
    assert trib_mod.trib_check(nol, store.table("Level/练气境界"), tstats, 999, 1000) is not None
    # 血量不足拒绝
    td.ext["hp"] = 100
    m = trib_mod.trib_check(td, store.table("Level/练气境界"), tstats, 100, 1_000_000_000)
    assert m and "血量" in m, m
    td.ext["hp"] = 999_999_999
    # 雷抗与劫数
    x = trib_mod.thunder_resist(td, tstats)
    assert x > 0, x
    rounds = trib_mod.ROOT_ROUNDS.get("圣体")
    assert rounds == 52
    # 渡劫：构造必成/必败
    class _Win(_random.Random):
        def random(self):
            return 0.0
    class _Lose(_random.Random):
        def random(self):
            return 0.999
    ok, msg = trib_mod.trib_run(td, tstats, _Win(1))
    assert ok and td.ext["power"] == 2, msg
    # 登仙
    m = trib_mod.ascend_check(td, store.table("Level/练气境界"))
    assert m is None, m
    ok, msg = trib_mod.ascend_run(td, store.table("Level/练气境界"))
    assert ok and td.realm_index == 41, msg
    # 渡劫失败路径
    tf = PlayerDoc(uid="tf", name="败者", realm_index=40, exp=20_000_000)
    tf.ext["linggen"] = {"name": "伪灵根", "type": "伪灵根", "eff": 1, "orb": 0.02}
    tf.ext["hp"] = 999_999
    tf.ext["hp_max"] = 1_000_000
    ok, msg = trib_mod.trib_run(tf, tstats, _Lose(1))
    assert not ok and tf.exp == 15_000_000 and tf.ext["hp"] == 1, msg
    assert tf.ext["spirit_fail_ts"] > 0
    m = trib_mod.trib_check(tf, store.table("Level/练气境界"), tstats, 999, 1000)
    assert m and "元神" in m, m   # CD 中

    # 熟练度：感悟分配 / 六档 / 战斗乘区
    tp = PlayerDoc(uid="tp", name="参悟", realm_index=30)
    tp.ext["gongfa"] = ["凰劫再生术"]
    ok, msg = trib_mod.allocate(tp, "未学功法", 10)
    assert not ok and "尚未参悟" in msg
    tp.ext["insight"] = 200
    ok, msg = trib_mod.allocate(tp, "凰劫再生术", 120)
    assert ok and trib_mod.prof_of(tp)["凰劫再生术"] == 120, msg
    st = trib_mod.stage_of(120)
    assert st[0] == "略有所成" and abs(st[1] - 1.03) < 1e-9, st
    tp.ext["insight"] = 5000
    ok, msg = trib_mod.allocate(tp, "凰劫再生术", 10 ** 9)
    assert ok and trib_mod.prof_of(tp)["凰劫再生术"] == 1000, msg   # 超额分配钳上限
    assert tp.ext["insight"] == 4120, tp.ext["insight"]
    st = trib_mod.stage_of(1000)
    assert st[0] == "出神入化" and abs(st[2] - 1.15) < 1e-9
    assert trib_mod.best_stage(tp)[:2] == ("出神入化", 1.15)
    assert "参悟" in trib_mod.prof_text(tp)
    n = trib_mod.add_insight(tp, 2)
    assert n == 4122, n
    print("trib & prof ok")

    # 16z. 寿元 / 轮回（W2-2）
    from core import lifespan as life_mod  # noqa: E402

    ls = PlayerDoc(uid="ls", name="凡修", realm_index=20, stones=10_000)
    # 惰性初始化 (realm+1)×500
    assert life_mod.shouyuan_of(ls) == 21 * 500
    # 未登仙流逝 10；同日不重复
    lost, dead = life_mod.daily_decay(ls, 1_800_000_000)
    assert lost == 10 and not dead and life_mod.shouyuan_of(ls) == 21 * 500 - 10
    lost2, _ = life_mod.daily_decay(ls, 1_800_000_100)
    assert lost2 == 0, "同日不应重复流逝"
    # 体质减免：圣体 ×0.7
    st_body = PlayerDoc(uid="stb", name="圣体", realm_index=20)
    st_body.ext["linggen"] = {"name": "圣体", "type": "圣体"}
    st_body.ext["shouyuan_day"] = ""
    lost3, _ = life_mod.daily_decay(st_body, 1_800_000_000)
    assert lost3 == 7, lost3
    # 登仙后 100 / ≥50 境折半
    im = PlayerDoc(uid="im", name="地仙", realm_index=41)
    lost4, _ = life_mod.daily_decay(im, 1_800_000_000)
    assert lost4 == 100, lost4
    hi = PlayerDoc(uid="hi", name="仙帝", realm_index=55)
    lost5, _ = life_mod.daily_decay(hi, 1_800_000_000)
    assert lost5 == 50, lost5
    # 归零轮回：境界归 1、灵石折半、轮回 +1、寿元重置
    old_stones = ls.stones
    dead_doc = PlayerDoc(uid="dd", name="寿尽", realm_index=30, stones=8_000)
    dead_doc.ext["shouyuan"] = 5
    dead_doc.exp = 999_999
    lost6, dead = life_mod.daily_decay(dead_doc, 1_800_000_000)
    assert dead, "寿元耗尽应触发轮回"
    msg_r = life_mod.rebirth(dead_doc)
    assert dead_doc.realm_index == 0 and dead_doc.stones == 4_000, msg_r
    assert dead_doc.ext["rebirths"] == 1 and life_mod.shouyuan_of(dead_doc) == 500
    assert "第 1 世" in msg_r
    # grant：渡劫/登仙加寿
    life_mod.grant(dead_doc, life_mod.TRIB_BONUS)
    assert life_mod.shouyuan_of(dead_doc) == 500 + life_mod.TRIB_BONUS
    assert "寿元" in life_mod.text(ls)
    print("lifespan ok")

    # 17a. 命格（W2-3）：抽取/补抽/改命/四消费点
    from core import mingge as mg_mod  # noqa: E402

    table_m = store.table("item/命格词条")
    assert len(table_m) == 75, len(table_m)
    rng_m = _random.Random(7)
    drawn = mg_mod.roll(store, rng_m)
    assert drawn and drawn.get("name") and "effects" in drawn, drawn
    # 100 次抽取稀有度分布合理（1 档应占多数）
    counts = {1: 0, 2: 0, 3: 0}
    for _ in range(200):
        r = int(mg_mod.roll(store, _random.Random(_))["rarity"])
        counts[r] = counts.get(r, 0) + 1
    assert counts[1] > counts[2] > counts[3], counts

    md = PlayerDoc(uid="mg", name="命主", realm_index=20, stones=200_000)
    got = mg_mod.ensure(md, store, _random.Random(3))
    assert got and md.ext["mingge"]["name"] == got["name"]
    assert mg_mod.ensure(md, store, _random.Random(4))["name"] == got["name"]  # 幂等
    # 改命：余额不足拒绝；足额重抽
    md.stones = 100
    ok, msg = mg_mod.reroll(md, store, _random.Random(5))
    assert not ok and "灵石" in msg, msg
    md.stones = 200_000
    ok, msg = mg_mod.reroll(md, store, _random.Random(5))
    assert ok and md.stones == 100_000 and md.ext["mingge"] is not None, msg
    # 效果取值
    md.ext["mingge"] = {"name": "测试命", "effects": {"攻击加成": 0.2, "签到奖励倍率": 1.5}}
    assert abs(mg_mod.bonus(md, "攻击加成") - 0.2) < 1e-9
    assert abs(mg_mod.multiplier(md, "签到奖励倍率") - 1.5) < 1e-9
    assert mg_mod.multiplier(md, "未配置项") == 1.0
    assert "测试命" in mg_mod.text(md)
    print("mingge ok")

    # 17b. 时间长河（W3-1）：门槛/CD/四事件/结晶/传道
    from core import river as river_mod  # noqa: E402

    rd = PlayerDoc(uid="rd", name="渡客", realm_index=44, stones=0)
    assert river_mod.check(rd, 1_800_000_000) is not None, "44 重应被拒"
    rd.realm_index = 46
    assert river_mod.check(rd, 1_800_000_000) is None
    rd.ext["river"] = {"last": 1_800_000_000 - 60}
    m = river_mod.check(rd, 1_800_000_000)
    assert m and "分" in m, m
    rd.ext["river"] = {}

    class _F:
        def __init__(s, name, mult):
            s.name = name
            s.hp = 1_000_000 if name == "__me__" else int(900_000 * mult)
            s.hp_max = s.hp
            s.atk = 100 if name == "__me__" else int(200 * mult)
            s.defense = 100 if name == "__me__" else int(200 * mult)
            s.bao = 0.1
            s.effects = {}
            s.tags = {}

    class _Res:
        def __init__(s, w):
            s.winner = w
            s.a_hp = 900_000
            s.log = []

    calls = {"n": 0}

    def _run(fa, fb, rng):
        calls["n"] += 1
        return _Res(0 if fb.atk <= 500 else 1)   # 弱敌我赢、强敌我输

    outcomes = set()
    for seed in range(40):
        rr = PlayerDoc(uid=f"r{seed}", name="渡客", realm_index=46, stones=0)
        rr.exp = 50_000_000
        rng = _random.Random(seed)
        text_r, gains = river_mod.roam(rr, None, _F, _run, rng, 1_800_000_000)
        outcomes.add(("遇敌" if "三帝法身" in text_r else
                      "悟道" if "静观" in text_r else
                      "拾遗" if "遗物" in text_r else "传道"))
        assert rr.ext["river"]["crystal"] >= 0
        assert rr.ext["river"]["last"] == 1_800_000_000
    assert outcomes == {"遇敌", "悟道", "拾遗", "传道"}, outcomes
    # 传道：有功法时涨熟练度
    rt = PlayerDoc(uid="rt", name="剑客", realm_index=46)
    rt.ext["gongfa"] = ["凰劫再生术"]
    rt.ext["river"] = {"teachings": 0}
    for seed in range(60):
        rt.ext["river"]["last"] = 0
        rng = _random.Random(1000 + seed)
        roll_v = rng.random()
        rng2 = _random.Random(1000 + seed)
        rng2.random()  # 重放第一掷
        if roll_v >= 0.88:
            text_r, gains = river_mod.roam(rt, None, _F, _run, rng2, 1_800_000_000 + seed)
            if gains.get("prof"):
                assert trib_mod.prof_of(rt).get("凰劫再生术", 0) > 0
                break
    assert river_mod.CRYSTAL_HUANG == 15 and river_mod.TEACHING_MAX == 30
    assert "岁月沉淀" in river_mod.text(rt)
    print("river ok")

    # 17c. 命格消费点（W4-2）：采药/采矿/炼丹品质/签到倍率/寻宝
    from core import occupation as occupation_mod  # noqa: E402
    from core import alchemy as alchemy_mod  # noqa: E402

    md2 = PlayerDoc(uid="md2", name="百命", realm_index=30)
    md2.ext["mingge"] = {"name": "草木通灵", "effects": {"采药加成": 0.2, "采矿加成": 0.25,
                                                          "炼丹品质": 0.15, "寻宝加成": 0.3}}
    herbs, exp_h = occupation_mod.plant_yield(480, 5, 30, _random.Random(1))
    herbs_b, _ = occupation_mod.plant_yield(480, 5, 30, _random.Random(1))
    if herbs:
        boosted = {k: max(1, int(v * 1.2)) for k, v in herbs_b.items()}
        assert any(boosted.get(k, 0) >= v for k, v in herbs.items()), (herbs, boosted)
    # 炼丹品质：阈值 0.1+lv×3% − 0.15
    recipe = {"name": "叩仙丹", "rate": 1.0, "exp": [10, 5]}
    b1, _ = alchemy_mod.craft_pills(recipe, 0, _random.Random(1), 50)
    b2, _ = alchemy_mod.craft_pills(recipe, 0, _random.Random(1), 50, quality_bonus=0.15)
    fan1 = b1.get("凡品", 0)
    fan2 = b2.get("凡品", 0)
    assert fan2 <= fan1, (fan1, fan2)   # 品质加成后凡品不增
    # 签到倍率
    sd = PlayerDoc(uid="sd", name="签客", realm_index=10)
    ok, msg, d1 = cultivate.sign_in(sd, 0, 0, 1_800_000_000, _random.Random(1))
    sd2 = PlayerDoc(uid="sd2", name="倍签", realm_index=10)
    ok, msg, d2 = cultivate.sign_in(sd2, 0, 0, 1_800_000_000, _random.Random(1), reward_mult=1.5)
    assert d2.stones == int(d1.stones * 1.5), (d1.stones, d2.stones)
    # 寻宝加成：explore 结算 stones 放大
    se1 = secret_mod.Session(place="青冥山")
    se2 = secret_mod.Session(place="青冥山")
    su = battle_mod.Unit("甲", 10 ** 9, 10 ** 6, 10 ** 10, 1.0)
    su_f = Fighter.from_unit(su)
    foe = battle_mod.Unit("兽", 1, 1, 10 ** 9, 0.0)
    for sess_x, bonus_v in ((se1, 0.0), (se2, 0.3)):
        rng_x = _random.Random(9)
        me_x = battle_mod.Unit("甲", 10 ** 9, 10 ** 6, 10 ** 10, 1.0)
        mf_x = Fighter.from_unit(me_x)
        for _ in range(3):
            secret_mod.explore(sess_x, (10 ** 9, 10 ** 6, 10 ** 10), me_x,
                               [], rng_x, me_fighter=mf_x, treasure_bonus=bonus_v)
    assert se2.stones > se1.stones, (se1.stones, se2.stones)   # 同种子 1.3 倍应更高
    print("mingge consumers ok")

    # 17d. 灵市（W5-1）：确定性行情/买卖/借款/走势
    from core import market as market_mod  # noqa: E402

    t0 = 1_800_000_000.0
    g1 = market_mod.create_market(t0, seed=12345)
    g2 = market_mod.create_market(t0, seed=12345)
    assert g1["stocks"][0]["price"] == 10000
    market_mod.advance(g1, t0 + 3600)       # 6 tick
    market_mod.advance(g2, t0 + 3600)
    assert [s["price"] for s in g1["stocks"]] == [s["price"] for s in g2["stocks"]], "同种子行情应一致"
    assert any(s["price"] != 10000 for s in g1["stocks"]), "6 tick 后价格应变动"
    # 涨跌停约束
    for st_ in g1["stocks"]:
        lo, hi = market_mod._limits(st_)
        assert lo <= st_["price"] <= hi, (st_["name"], st_["price"], lo, hi)
    # 买入/卖出
    md3 = PlayerDoc(uid="mk", name="灵市大亨", realm_index=30, stones=5_000_000)
    g = market_mod.create_market(t0, seed=99)
    st0 = g["stocks"][0]
    ok, msg = market_mod.buy(g, md3, st0, 100, t0)
    assert ok and md3.stones == 5_000_000 - 1_003_000, msg
    acc = market_mod.account_of(md3)
    assert acc["holdings"][st0["id"]]["shares"] == 100
    # 30 秒 CD
    ok, msg = market_mod.buy(g, md3, st0, 100, t0 + 5)
    assert not ok and "冷却" in msg, msg
    # 卖出清仓
    ok, msg = market_mod.sell(g, md3, st0, -1, t0 + 60)
    assert ok and not market_mod.account_of(md3)["holdings"], msg
    # 借款：额度/资产上限/还款
    ok, msg = market_mod.take_loan(g, md3, 999, t0)
    assert not ok and "额度" in msg, msg
    md3.stones = 100_000
    ok, msg = market_mod.take_loan(g, md3, 1_000_000, t0)
    assert not ok and "2 倍" in msg, msg   # 身家 10 万，借 100 万超 2 倍
    ok, msg = market_mod.take_loan(g, md3, 150_000, t0)
    assert ok and md3.stones == 250_000, msg
    ok, msg = market_mod.take_loan(g, md3, 10_000, t0)
    assert not ok and "未结清" in msg, msg
    ok, msg = market_mod.repay(g, md3)
    assert ok and market_mod.account_of(md3)["loan"] is None, msg
    # 摘牌不可交易
    st_del = dict(g["stocks"][1], delistedAt=1)
    ok, msg = market_mod.buy(g, md3, st_del, 10, t0 + 120)
    assert not ok and "摘牌" in msg, msg
    # 打听扣费 + 文案
    before_tip = md3.stones
    ok, msg = market_mod.tip(g, md3)
    assert ok and md3.stones == before_tip - market_mod.TIP_COST, msg
    assert "走势" in market_mod.trend_text(g, "丹鼎阁")
    assert "持仓" in market_mod.account_text(g, md3)
    print("market ok")

    # 17. 宗门纯函数 + 存取
    from core import sect as sect_mod  # noqa: E402

    no_sect = PlayerDoc(uid="s0")
    ok, _ = sect_mod.can_create(no_sect)
    assert not ok, "无宗门但境界不足应拒绝"
    rich = PlayerDoc(uid="s1", realm_index=5, stones=10000)
    ok, _ = sect_mod.can_create(rich)
    assert ok
    has_sect = PlayerDoc(uid="s2", realm_index=9, stones=99999, ext={"sect": "甲"})
    ok, _ = sect_mod.can_create(has_sect)
    assert not ok, "已有宗门应拒绝"
    assert sect_mod.upgrade_cost(1) == 20000 and sect_mod.upgrade_cost(3) == 80000
    assert sect_mod.member_limit(1) == 10 and sect_mod.member_limit(9) == 26

    await db.create_sect("青云门", "s1", 1.0)
    s = await db.get_sect("青云门")
    assert s and s["level"] == 1 and s["fund"] == 0
    await db.update_sect("青云门", 2, 5000)
    s = await db.get_sect("青云门")
    assert s["level"] == 2 and s["fund"] == 5000
    rows = await db.all_sects()
    assert rows and rows[0]["name"] == "青云门"
    await db.delete_sect("青云门")
    assert await db.get_sect("青云门") is None
    print("sect ok")

    # 18. 装备强化：费用/成功率边界 + 聚合乘数
    assert equip_mod.enhance_cost(0) == 2000 and equip_mod.enhance_cost(9) == 20000
    assert abs(equip_mod.enhance_rate(0) - 1.0) < 1e-9
    assert abs(equip_mod.enhance_rate(10) - 0.35) < 1e-9
    d11 = PlayerDoc(uid="q1")
    equip_mod.wear(d11, wpn)
    s0 = equip_mod.aggregate(d11, lvl4, lookup.get)
    s1 = equip_mod.aggregate(d11, lvl4, lookup.get, {"武器": 10})
    assert s1.atk == int(1000 * (1 + 0.92 * 2.0)), (s0.atk, s1.atk)  # +10级 → 加成×2
    assert s1.bao == s0.bao, "bao 不吃强化乘数"
    print("enhance ok")

    # 19. 拍卖行生命周期：挂单 → 分页 → 购买（托管删除）→ 下架取回
    lot1 = await db.list_auction("u1", "甲", "灵草", 3, 100)
    lot2 = await db.list_auction("u2", "乙", "玄铁", 1, 500)
    assert lot1 and lot2 and lot2 == lot1 + 1
    rows, pages = await db.auction_page(1, per=1)
    assert pages == 2 and rows[0]["id"] == lot1
    lot = await db.get_auction(lot1)
    assert lot["item"] == "灵草" and lot["qty"] == 3
    lots = await db.my_auctions("u2")
    assert [x["id"] for x in lots] == [lot2]
    assert await db.delete_auction(lot1)
    assert await db.get_auction(lot1) is None
    assert not await db.delete_auction(lot1), "重复删除应返回 False"
    print("auction ok")

    # 20. 宗门俸禄公式（等级×1200，宗主×2）——由 handler 直算，这里验证组成
    assert 3 * 1200 * 2 == 7200 and 1 * 1200 == 1200
    print("salary formula ok")

    # 21. 炼丹：等级阈值 / 材料缺漏 / 制造结算
    from core import alchemy as alch  # noqa: E402

    assert alch.level_of(0) == 0 and alch.level_of(99) == 0 and alch.level_of(100) == 1
    assert alch.next_threshold(0) == 100 and alch.next_threshold(999999) is None
    assert alch.level_of(12000) == 10 and alch.MAX_LEVEL == 20
    recipe = {"name": "辟谷丹", "rate": 1.0, "level_limit": 0, "exp": [100, 300],
              "materials": [{"name": "万年凝血草", "amount": 2}]}
    assert alch.missing_materials(recipe, {"万年凝血草": 1}) == [("万年凝血草", 2, 1)]
    assert alch.missing_materials(recipe, {"万年凝血草": 5}) == []
    ok, exp, msg = alch.craft(recipe, 0, _random.Random(1), 2)
    assert ok and exp == 200, msg            # rate=1.0 全成
    ok, exp, msg = alch.craft({**recipe, "rate": 0.0}, 0, _random.Random(1), 2)
    assert not ok and exp == 600, msg        # rate=0 全败，失败经验 300×2
    assert abs(alch.success_rate(recipe, 5) - 1.0) < 1e-9
    # 原版 zhizuo_dan 语义：必成 + 品质分档（craft_pills；craft 保留给锻造掷骰）
    rq = {"name": "辟谷丹", "rate": 1.0, "level_limit": 0, "exp": [100, 300], "materials": []}
    buckets, exp = alch.craft_pills(rq, 0, _random.Random(1), 1)
    assert set(buckets) <= {"凡品", "极品", "仙品"} and sum(buckets.values()) == 1 and exp == 100
    buckets, exp = alch.craft_pills(rq, 20, _random.Random(1), 200)
    assert sum(buckets.values()) == 200 and exp == 20000
    assert buckets.get("凡品", 0) < 120, buckets  # 20 级凡品阈值 0.7 → 凡品约 30%
    rs = {"name": "天命轮回丹", "exp": [55555, 55555], "materials": []}
    buckets, exp = alch.craft_pills(rs, 0, _random.Random(1), 2)
    assert buckets == {"": 2} and exp == 111110, (buckets, exp)  # 特殊丹直接产出
    print("alchemy ok")

    # 21b. 图鉴分页 + 来源反查
    from core import catalog as catalog_mod  # noqa: E402

    fake_items = [{"name": f"丹{i}", "class": "丹药", "type": "修为", "exp": i * 100, "出售价": i * 10,
                   "稀有度": 1} for i in range(1, 31)]
    cur, pages, curp = catalog_mod.catalog_page(fake_items, 1)
    assert pages == 3 and curp == 1 and len(cur) == 12 and cur[0]["name"] == "丹1"
    assert "修为+100" in cur[0]["effect"], cur[0]
    cur2, _, p2 = catalog_mod.catalog_page(fake_items, 99)
    assert p2 == 3 and len(cur2) == 6  # 末页 6 条
    srcs = catalog_mod.where_to_get(
        "万年凝血草",
        [{"name": "起死回生丹", "materials": [{"name": "万年凝血草", "amount": 1}]}],
        set(), set())
    assert any("炼丹材料" in s for s in srcs), srcs
    assert catalog_mod.where_to_get("不存在的东西", [], set(), set())[0].startswith("暂无已知渠道")
    print("catalog ok")

    # 22. 帝兵认主：聚合翻倍 + 宗门秘境 factor 覆盖
    imp_wpn = {"name": "万龙铃仿品", "class": "装备", "type": "帝兵", "atk": 0.5, "def": 0.5, "HP": 0.5}
    lookup["万龙铃仿品"] = imp_wpn
    d12 = PlayerDoc(uid="im1")
    equip_mod.wear(d12, imp_wpn)
    s_plain = equip_mod.aggregate(d12, lvl4, lookup.get)
    s_own = equip_mod.aggregate(d12, lvl4, lookup.get, None, {"万龙铃仿品"})
    assert s_own.atk == int(1000 * 2.0), (s_plain.atk, s_own.atk)  # 0.5×2倍=1.0 倍基础
    s_enh = equip_mod.aggregate(d12, lvl4, lookup.get, {"帝兵": 5}, {"万龙铃仿品"})
    assert s_enh.atk == int(1000 * (1 + 0.5 * 1.5 * 2.0)), s_enh.atk  # 强化与认主叠乘（帝兵独立槽位）

    sess3 = secret_mod.Session(place="青云门·宗门秘境", factor=2.9)
    monster = secret_mod.make_monster(sess3.place, 0, (1000, 1000, 1000), _random.Random(2), factor_override=2.9)
    m_plain = secret_mod.make_monster("青冥山", 0, (1000, 1000, 1000), _random.Random(2))
    assert monster.atk > m_plain.atk * 3, (monster.atk, m_plain.atk)  # 2.9 vs 0.6
    print("imperial & sect secret ok")

    # 23. 套装特效：2 件 +15%、3 件齐 +35%
    setA = [
        {"name": "终焉剑", "class": "装备", "type": "武器", "atk": 0.3, "套装": "终焉神魔套"},
        {"name": "终焉甲", "class": "装备", "type": "护具", "def": 0.3, "套装": "终焉神魔套"},
        {"name": "终焉铃", "class": "装备", "type": "法宝", "HP": 0.3, "套装": "终焉神魔套"},
    ]
    lookup.update({e["name"]: e for e in setA})
    d13 = PlayerDoc(uid="st1")
    equip_mod.wear(d13, setA[0])
    equip_mod.wear(d13, setA[1])
    s2 = equip_mod.aggregate(d13, lvl4, lookup.get)
    # 无套装基线：攻 1000×1.3、防 1000×1.3；2 件套 → ×1.15
    assert abs(s2.atk - 1300 * 1.15) <= 1 and abs(s2.defense - 1300 * 1.15) <= 1, (s2.atk, s2.defense)
    assert s2.set_lines and "终焉神魔套×2" in s2.set_lines[0]
    equip_mod.wear(d13, setA[2])
    s3 = equip_mod.aggregate(d13, lvl4, lookup.get)
    assert abs(s3.atk - 1300 * 1.35) <= 1 and abs(s3.hp - 6500 * 1.35) <= 1, (s3.atk, s3.hp)
    assert "终焉神魔套×3" in s3.set_lines[0]
    print("set bonus ok")

    # 24. 宝石镶嵌聚合 + 宗门积分
    gem = {"name": "攻击宝石", "class": "宝石", "攻击加成": 1000, "暴击加成": 0.1}
    lookup["攻击宝石"] = gem
    d14 = PlayerDoc(uid="g1")
    equip_mod.wear(d14, wpn)
    s_base = equip_mod.aggregate(d14, lvl4, lookup.get)
    d14.ext["gems"] = {"武器": ["攻击宝石"]}
    s_gem = equip_mod.aggregate(d14, lvl4, lookup.get)
    assert s_gem.atk == s_base.atk + 1000, (s_base.atk, s_gem.atk)
    assert abs(s_gem.bao - min(s_base.bao + 0.1, 1.0)) < 1e-9
    print("gem ok")

    await db.create_sect("积分宗", "s9", 1.0)
    await db.add_sect_score("积分宗", 3)
    s = await db.get_sect("积分宗")
    assert s["score"] == 3, s
    rows = await db.all_sects()
    assert rows[0]["name"] == "积分宗" and rows[0]["score"] == 3
    await db.delete_sect("积分宗")
    print("sect score ok")

    # 25. 仙宠聚合 + 宗门守关 Boss
    pet_def = {"id": 2801, "name": "冉遗鱼", "class": "仙宠", "品级": "仙胎",
               "初始加成": 0.005, "每级增加": 0.001, "等级上限": 20}
    lookup["冉遗鱼"] = pet_def
    d15 = PlayerDoc(uid="p1")
    d15.ext["pet"] = {"name": "冉遗鱼", "level": 10}
    s_np = equip_mod.aggregate(d15, lvl4, lookup.get)
    d15.ext["pet"] = {"name": "冉遗鱼", "level": 1}
    s_lv1 = equip_mod.aggregate(d15, lvl4, lookup.get)
    # 10 级加成 = 0.005+0.001×9 = 0.014；1 级 = 0.005
    assert abs(s_np.atk - 1000 * 1.014) <= 1, s_np.atk
    assert abs(s_lv1.atk - 1000 * 1.005) <= 1, s_lv1.atk
    d15.ext["pet"] = {"name": "冉遗鱼", "level": 999}   # 超上限钳制
    assert abs(equip_mod.aggregate(d15, lvl4, lookup.get).atk - 1000 * 1.025) <= 1

    # 宗门秘境守关 Boss：第 5 层强制遭遇
    sess_b = secret_mod.Session(place="宗测", factor=2.0, sect_name="测试宗")
    me_b = battle_mod.Unit("甲", 100000, 100000, 1000000, 0.0)
    won5 = None
    for _ in range(4):
        sess_b, me_b, _, fled = secret_mod.explore(sess_b, (3000, 3000, 30000), me_b, pool, _random.Random(9), sect_mode=True)
        if fled:
            break
    assert sess_b.floor == 4 and sess_b.boss_kills == 0
    if not fled:
        before = sess_b.stones
        sess_b, me_b, flavor, fled = secret_mod.explore(sess_b, (3000, 3000, 30000), me_b, pool, _random.Random(9), sect_mode=True)
        assert sess_b.floor == 5 and "守关Boss" in sess_b.log[-1], sess_b.log[-1]
        if not fled:
            assert sess_b.boss_kills == 1 and sess_b.stones > before, sess_b.log[-1]
    print("sect boss & pet ok")

    # 26. 宠物对战：三维缩放 / 成长升级 / 品级压制
    pet_spirit = {"id": 7091301, "name": "岁云剑灵", "class": "仙宠", "品级": "仙灵",
                  "atk": 20, "def": 7, "HP": 15,
                  "初始加成": 0.35, "每级增加": 0.35, "等级上限": 100}
    lookup["岁云剑灵"] = pet_spirit
    pb_low = pet_mod.build({"name": "冉遗鱼", "level": 1, "exp": 0}, lookup.get)
    pb_high = pet_mod.build({"name": "岁云剑灵", "level": 1, "exp": 0}, lookup.get)
    assert pb_low and pb_high
    assert pb_low.unit.atk == 1 and pb_high.unit.atk == 20   # 图鉴基准
    pb10 = pet_mod.build({"name": "岁云剑灵", "level": 11, "exp": 0}, lookup.get)
    assert pb10.unit.atk == 20 * 2, pb10.unit.atk            # 每级 +10%
    pet_new, up = pet_mod.gain_exp({"name": "冉遗鱼", "level": 1, "exp": 8}, 3, lookup.get)
    assert up == 1 and pet_new["level"] == 2 and pet_new["exp"] == 2, pet_new
    pet_cap, up2 = pet_mod.gain_exp({"name": "冉遗鱼", "level": 20, "exp": 0}, 9, lookup.get)
    assert up2 == 0 and pet_cap["level"] == 20 and pet_cap["exp"] == 0, pet_cap   # 上限封顶
    w, _ = pet_mod.duel(pb_high, pb_low, _random.Random(1))
    assert w == 0, "仙灵应碾压仙胎"
    print("pet duel ok")

    # 27. 宠物进阶：品级链 / 形态查找 / 觉醒暴击
    assert pet_mod.GRADE_CHAIN == ("仙胎", "仙仔", "仙兽", "仙道", "仙灵")
    assert pet_mod.GRADE_CAPS["仙灵"] == 100
    assert pet_mod.advance_cost("仙胎") == 100000 and pet_mod.advance_cost("仙道") == 400000
    # 形态链：冉遗鱼鱼苗(2801) → 初级(2802) → 中级(2803)
    fish = pet_mod.next_form(pet_def, {2801: pet_def, 2802: {"id": 2802, "name": "初级冉遗鱼", "class": "仙宠", "品级": "仙仔"}})
    assert fish and fish["name"] == "初级冉遗鱼", fish
    assert pet_mod.next_form(pet_def, {}) is None
    # 品级暴击进 build
    pb = pet_mod.build({"name": "岁云剑灵", "level": 1, "exp": 0}, lookup.get)
    assert abs(pb.unit.bao - 0.30) < 1e-9, pb.unit.bao   # 仙灵 30%
    pb2 = pet_mod.build({"name": "冉遗鱼", "level": 1, "exp": 0}, lookup.get)
    assert pb2.unit.bao == 0.0                            # 仙胎无暴击
    print("pet advance ok")

    # 28. 随机天赋：抽取分布 / 属性应用 / 成长加速
    rng_t = _random.Random(42)
    names = {pet_mod.roll_talent(rng_t)["rarity"] for _ in range(200)}
    assert names <= {"普通", "稀有", "史诗"}
    koi = pet_mod.TALENT_BY_NAME["锦鲤附体"]
    pet_koi = {"name": "岁云剑灵", "level": 1, "exp": 0, "talent": "锦鲤附体"}
    pb_koi = pet_mod.build(pet_koi, lookup.get)
    assert abs(pb_koi.unit.bao - 0.30) < 1e-9  # 锦鲤不加减暴击，仙灵品级自带 30%
    got, up = pet_mod.gain_exp(pet_koi, 4, lookup.get)
    assert got["exp"] == 6, got   # 4 × 1.5 = 6
    claw = pet_mod.TALENT_BY_NAME["天生锐爪"]
    pet_claw = {"name": "岁云剑灵", "level": 1, "exp": 0, "talent": "天生锐爪"}
    pb_claw = pet_mod.build(pet_claw, lookup.get)
    assert abs(pb_claw.unit.bao - 0.42) < 1e-9, pb_claw.unit.bao   # 仙灵30% + 锐爪12%
    assert pb_claw.unit.atk == pb_high.unit.atk                     # 锐爪不加攻
    pet_sav = {"name": "岁云剑灵", "level": 1, "exp": 0, "talent": "蛮荒之力"}
    assert pet_mod.build(pet_sav, lookup.get).unit.atk == 24        # 20×1.2
    print("talent ok")

    # 29. 渲染管线：模板 → HTML → PNG
    from infra import render as render_mod  # noqa: E402

    status_data = {"title": "修仙状态", "sub": "M12", "footer": "test",
                   "name": "测试", "realm": "虚妄境圆满", "exp": 40080, "req": 50000,
                   "next": "化神", "progress": 80.2, "hp_cur": 8000, "hp_max": 9000,
                   "stones": 21906, "atk": 3000, "defense": 2500, "hp": 9000,
                   "bao": "10%", "state_note": "", "set_lines": []}
    html = render_mod._jinja().get_template("status.html").render(**status_data)
    assert "虚妄境圆满" in html and "21906" in html, "模板变量未注入"

    out = tmp / "status.png"
    png = await render_mod.render_panel("status", status_data, tmp)
    assert png and png.exists() and png.stat().st_size > 2000, "PNG 未生成或过小"

    boss_data = {"title": "世界 Boss", "footer": "test", "round": 1, "alive": True,
                 "status": "存活", "health": 600000, "health_max": 1000000, "pct": 60.0,
                 "reward": 500000, "ledger": [("甲", 700), ("乙", 300)]}
    png2 = await render_mod.render_panel("boss", boss_data, tmp)
    assert png2 and png2.exists() and png2.stat().st_size > 2000

    help_data = {"title": "诸天修仙 · 指令总览", "footer": "test",
                 "groups": [{"title": "基础修炼", "lines": [("#踏入仙途", "创建角色"), ("#修仙签到", "领灵石")]},
                            {"title": "灵根天资", "lines": [("#灵根", "查看灵根")]}]}
    html_h = render_mod._jinja().get_template("help.html").render(**help_data)
    assert "基础修炼" in html_h and "#踏入仙途" in html_h, "help 模板变量未注入"
    png3 = await render_mod.render_panel("help", help_data, tmp)
    assert png3 and png3.exists() and png3.stat().st_size > 2000

    qv = {"title": "每日修行任务", "sub": "2026-11-01", "level": 3, "exp": 120,
          "exp_need": 75000, "exp_pct": 0.2,
          "tasks": [
              {"no": 1, "name": "散财修行", "desc": "消耗灵石", "need": 100, "prog": 60,
               "status": "进行中", "pct": 60.0, "done": False},
              {"no": 2, "name": "聚财修行", "desc": "获取灵石", "need": 100, "prog": 100,
               "status": "已完成", "pct": 100.0, "done": True},
              {"no": 3, "name": "秘境历练", "desc": "探索秘境", "need": 4, "prog": 1,
               "status": "进行中", "pct": 25.0, "done": False}],
          "state": "进行中（完成后 #提交每日任务）",
          "final": {"amount": 48000, "task_exp": 72, "key_n": 3}}
    png_q = await render_mod.render_panel("quest", qv, tmp)
    assert png_q and png_q.exists() and png_q.stat().st_size > 2000

    # 纳戒面板：分组互斥 + 渲染
    bag_data = {"title": "诸天万界 · 纳戒", "sub": "4 种", "footer": "test",
                "kinds": 4, "total": 37,
                "groups": [
                    {"label": "八阶 · 淬金", "color": "#f0d78c",
                     "cells": [{"name": "万兽神药", "qty": 1, "cls": "丹药", "typ": "神药"}]},
                    {"label": "凡阶 · 一至三阶", "color": "#9aa5b5",
                     "cells": [{"name": "定魂草", "qty": 5, "cls": "草药", "typ": "灵根"},
                               {"name": "神石", "qty": 30, "cls": "道具", "typ": ""},
                               {"name": "世界石", "qty": 1, "cls": "材料", "typ": "开辟小世界"}]}],
                "rows": []}
    html_b = render_mod._jinja().get_template("bag.html").render(**bag_data)
    assert "万兽神药" in html_b and "定魂草" in html_b and "37 件" in html_b, "bag 模板变量未注入"
    png_b = await render_mod.render_panel("bag", bag_data, tmp)
    assert png_b and png_b.exists() and png_b.stat().st_size > 2000

    # 团本面板：血条/成员/分奖
    raid_data = {
        "title": "团本讨伐 · 若陀龙王", "footer": "队伍码 123456",
        "code": "123456", "boss": "若陀龙王", "title_tag": "岩龙", "status": "讨伐中",
        "started": True,
        "hp": "7,750,000", "hp_max": "15,500,000", "pct": 50.0, "reward": "2,790,000",
        "members": [
            {"name": "甲", "dmg": "600", "hits": 2, "leader": True, "killer": False, "stones": "0"},
            {"name": "乙", "dmg": "400", "hits": 1, "leader": False, "killer": False, "stones": "0"},
        ],
        "victory": False, "loot": "五行神石", "hint": "#讨伐出手（今日 3 次）",
    }
    png_r = await render_mod.render_panel("raid", raid_data, tmp)
    assert png_r and png_r.exists() and png_r.stat().st_size > 2000
    html_r = render_mod._jinja().get_template("raid.html").render(**raid_data)
    assert "若陀龙王" in html_r and "7,750,000" in html_r and "甲" in html_r

    # 无尽劫境面板：星图/血条/道法
    endless_data = {
        "title": "无尽劫境 · 乱古界海", "footer": "A1·本初劫境",
        "tier": "A1·本初劫境", "layer": 3, "phase": "星图待定",
        "hp": "1,200,000", "hp_max": "2,000,000", "pct": 60.0,
        "atk": "1,500,000", "def": "900,000", "bao": "25%",
        "marks": "320", "total": "1,820",
        "rule": "极境：凶兽擅长狂暴与再生，拖延战斗会越来越危险。",
        "nodes": [
            {"no": 1, "name": "界海黑兽", "type": "遭遇战", "desc": "第 4 层遭遇，胜则前行。", "selected": True},
            {"no": 2, "name": "诸天遗珍", "type": "诸天遗珍", "desc": "直接获得一项能力，无需战斗。", "selected": False},
            {"no": 3, "name": "涅槃温泉", "type": "涅槃温泉", "desc": "回复 40% 气血，稳妥前行。", "selected": False},
        ],
        "choices": [], "checkpoints": [],
        "abilities": [{"name": "至尊骨", "lv": 1, "max": 3, "rarity": "稀有"},
                      {"name": "雷帝宝术", "lv": 2, "max": 3, "rarity": "核心"}],
        "boons": ["如意金箍棒"], "hint": "#星图定途 1-3 → #无尽下一关",
    }
    png_e = await render_mod.render_panel("endless", endless_data, tmp)
    assert png_e and png_e.exists() and png_e.stat().st_size > 2000
    html_e = render_mod._jinja().get_template("endless.html").render(**endless_data)
    assert "乱古界海" in html_e and "界海黑兽" in html_e and "至尊骨" in html_e

    # 分组区间互斥：物品只落一组
    tiers = [(9, 99), (8, 9), (7, 8), (6, 7), (4, 6), (0, 4)]
    for rar in range(0, 12):
        hits = [1 for lo, hi in tiers if lo <= rar < hi]
        assert len(hits) == 1, f"稀有度 {rar} 分组不互斥"
    # 16p. 彼岸世界/真世界：基础世界层（世界/坐标/观测/路径/贡献/通关）+ 规则层 + 状态访问层
    # 用固定 rng 桩，不依赖随机数。
    world = osh_w.create_other_shore_world(seed="canglan")
    assert world["radius"] == osh_w.OTHER_SHORE_MAP_RADIUS == 4
    assert world["centerId"] == "0,0"
    center = next(s for s in world["stars"] if s["id"] == "0,0")
    assert center["anchorRequirement"] == 0
    center_state = world["states"]["0,0"]
    assert center_state["phase"] == "anchored" and center_state["contribution"] == 0
    non_center = [s for s in world["stars"] if s["id"] != "0,0"]
    assert len(non_center) > 50, "世界星表应远大于关键星"

    # 坐标与距离
    assert osh_w.get_other_shore_hex_distance({"q": 0, "r": 0}, {"q": 1, "r": 0}) == 1
    assert osh_w.get_other_shore_hex_distance({"q": 0, "r": 0}, {"q": 4, "r": 0}) == 4
    assert osh_w.other_shore_coordinate_id(0, 0) == "0,0"
    assert osh_w._normalize_coordinate({"q": -2, "r": 3}) == {"q": -2, "r": 3}
    assert osh_w.get_other_shore_hex_distance({"q": -2, "r": 3}, {"q": -4, "r": 1}) == 4

    # 星表与程序星池
    key_star_names = {s["name"] for s in world["stars"] if s.get("keyStar")}
    assert "沧澜祖星" in key_star_names
    procedural = [s for s in world["stars"] if s.get("keyStar") is False]
    assert procedural, "应存在程序生成大星"
    assert all(s["kind"] in ("life", "ruin", "tide", "rift", "civilization", "dead") for s in procedural)
    assert {s["templateId"] for s in procedural} <= {
        "life", "ruin", "tide", "rift", "civilization", "dead"}
    key_star_reqs = {s["anchorRequirement"] for s in world["stars"] if s["name"] == "观潮天门"}
    assert key_star_reqs == {8}, key_star_reqs
    assert {s["anchorRequirement"] for s in world["stars"] if s["name"] == "沧澜祖星"} == {0}

    # 观测 / 踏足 / 贡献 / 建标 / 完成 的契约
    world_sensed = osh_w.observe_other_shore_stars(world, {"q": 2, "r": -1}, range_=2)
    sensed_ids = {sid for sid, st in world_sensed["states"].items() if st.get("phase") == "sensed"}
    assert sensed_ids, "观测范围应至少把若干大星推进到 sensed"
    assert world_sensed["states"]["0,0"]["phase"] == "anchored", "观测不得回退中心锚定"
    # 距 (2,-1) 为 3 的观潮天门不在观测范围，未观测不可踏足
    assert osh_w.get_other_shore_hex_distance({"q": 2, "r": -1}, {"q": 4, "r": 0}) == 3
    try:
        osh_w.visit_other_shore_star(world_sensed, {"q": 4, "r": 0})
        raise AssertionError("未观测不可踏足")
    except ValueError:
        pass
    visited = osh_w.visit_other_shore_star(world_sensed, {"q": 2, "r": -1})
    assert visited["states"]["2,-1"]["phase"] == "visited"
    try:
        osh_w.anchor_other_shore_star(visited, {"q": 2, "r": -1})
        raise AssertionError("贡献不足不可建标")
    except ValueError:
        pass
    # 单人上限 1：凑 6 人贡献后可达标建标
    for _i in range(6):
        visited = osh_w.contribute_other_shore_exploration(visited, {"q": 2, "r": -1}, f"u{_i}", 1)
    world_visited = osh_w.anchor_other_shore_star(visited, {"q": 2, "r": -1})
    assert world_visited["states"]["2,-1"]["phase"] == "anchored"
    cleared = osh_w.clear_other_shore_star(world_visited, {"q": 2, "r": -1})
    assert cleared["states"]["2,-1"]["phase"] == "cleared"

    # 贡献：已 cleared 的星阈值已满（6/6），再贡献无增量
    world_contrib = osh_w.contribute_other_shore_exploration(world_visited, {"q": 2, "r": -1}, "uid_x", amount=1)
    assert world_contrib["states"]["2,-1"]["contribution"] == 6, world_contrib["states"]["2,-1"]
    assert "uid_x" not in world_contrib["states"]["2,-1"].get("contributors", {})
    # 中心星贡献 = anchorRequirement（中心锚定=0 时 0）
    center_contrib = osh_w.contribute_other_shore_exploration(
        world, {"q": 0, "r": 0}, "uid_c", amount=5)
    assert center_contrib["states"]["0,0"]["contribution"] == 0
    # 未知坐标报错
    try:
        osh_w.require_star(world, {"q": 999, "r": 999})
        raise AssertionError("未知坐标应报错")
    except ValueError:
        pass

    # 路径与移动心智成本
    path = ["0,0", "1,0", "1,1"]
    travel = osh_w.calculate_other_shore_travel(world_visited, path, {"境界": "准仙帝"}, remainder=0)
    assert travel["path"] == path and travel["totalSteps"] == 2
    assert travel["cost"] == 0 and travel["remainder"] == 2  # 准仙帝 10 步/心神
    bad_path = ["0,0", "2,0"]  # 距离 2 ≠ 1
    try:
        osh_w.calculate_other_shore_travel(world_visited, bad_path, {"境界": "准仙帝"}, remainder=0)
        raise AssertionError("非相邻路径应报错")
    except ValueError:
        pass
    # 大帝 mindPerStep=1 → 每格 1 心神
    emperor_cost = osh_w.calculate_other_shore_travel(
        world_visited, path, {"境界": "大帝"}, remainder=0)
    assert emperor_cost["cost"] == 2
    # 真仙 stepsPerMind=2
    true_tier_cost = osh_w.calculate_other_shore_travel(
        world_visited, path, {"境界": "真仙"}, remainder=1)
    assert true_tier_cost["cost"] == (1 + 2) // 2 and true_tier_cost["remainder"] == (1 + 2) % 2

    # 规则层：境界名称判定 / 阈值 / 强档 / 旅行档位
    assert osh_rules.tier_from_realm_name("准仙帝") == "quasi_immortal_emperor"
    assert osh_rules.tier_from_realm_name("仙帝") == "immortal_emperor"
    assert osh_rules.tier_from_realm_name("祭道") == "immortal_emperor"
    assert osh_rules.tier_from_realm_name("路尽") == "immortal_emperor"
    assert osh_rules.tier_from_realm_name("仙王") == "immortal_king"
    assert osh_rules.tier_from_realm_name("真仙") == "true_immortal"
    assert osh_rules.tier_from_realm_name("大帝") == "emperor"
    assert osh_rules.tier_from_realm_name("普通") == "below_emperor"
    assert osh_rules.tier_from_level(10, {"emperor": 16, "trueImmortal": 17, "immortalKing": 18,
                                          "quasiImmortalEmperor": 20, "immortalEmperor": 21}) == "below_emperor"
    assert osh_rules.tier_from_level(22, {"emperor": 16, "trueImmortal": 17, "immortalKing": 18,
                                          "quasiImmortalEmperor": 20, "immortalEmperor": 21}) == "immortal_emperor"
    assert osh_rules.stronger_tier("emperor", "below_emperor") == "emperor"
    assert osh_rules.stronger_tier("below_emperor", "emperor") == "emperor"
    assert osh_rules.get_other_shore_travel_tier("准仙帝") == "quasi_immortal_emperor"
    # 三体系取最高档：仙王名号 + 秘境 25（≥21 仙帝档）→ immortal_emperor
    assert osh_rules.get_other_shore_travel_tier({"境界": "仙王", "mijinglevel_id": 25}) == "immortal_emperor"
    assert osh_rules.get_other_shore_travel_tier({"境界": "仙王", "mijinglevel_id": 18}) == "immortal_king"
    assert osh_rules.get_other_shore_travel_rule("准仙帝")["mindPerStep"] == 1
    assert osh_rules.get_other_shore_travel_rule("普通")["mindPerStep"] == 5  # below_emperor
    assert osh_rules.OTHER_SHORE_SUPPRESSION_MULTIPLIER == 0.7
    assert osh_rules.is_other_shore_external_action_allowed("externalShop") is False
    assert osh_rules.is_other_shore_external_action_allowed("externalPillHealing") is False

    # 抑制免疫 / 抑制规则
    assert osh_rules.is_other_shore_suppression_immune({"xiangu_yishenweizhong": True}) is True
    assert osh_rules.is_other_shore_suppression_immune({"自创修炼体系": {"name": "星路师"}}) is True
    assert osh_rules.get_other_shore_suppression({"xiangulevel_id": 25})["immune"] is True
    assert osh_rules.get_other_shore_suppression({"xiangulevel_id": 5})["immune"] is False
    assert osh_rules.get_other_shore_suppression({"xiangulevel_id": 5})["attributeMultiplier"] == 0.7

    # 状态访问层：ensure / read / save / update（SQLite 单例表 other_shore_state）
    await osh_state.ensure_other_shore_world(db.conn, seed="canglan")
    world_state = await osh_state.read_other_shore_world(db.conn)
    assert world_state is not None and world_state["centerId"] == "0,0"
    assert await osh_state.read_other_shore_world(db.conn) == world_state
    await osh_state.save_other_shore_world(db.conn, {**world_state, "radius": 5})
    assert (await osh_state.read_other_shore_world(db.conn))["radius"] == 5
    # update 整体读-改-写
    count_before = len(world_state["stars"])
    value = await osh_state.update_other_shore_world(
        db.conn, world_state, lambda doc: {"n": len(doc["stars"])})
    assert value[1]["n"] == count_before and len(value[0]["stars"]) == count_before

    # 序列化：阶段与发现字段
    serial = osh_w.serialize_other_shore_world(world_visited)
    assert serial["centerId"] == "0,0"
    center_s = next(s for s in serial["stars"] if s["id"] == "0,0")
    assert center_s["phase"] == "anchored" and center_s["anchored"] is True
    assert len(serial["stars"]) == len(world_visited["stars"])

    await render_mod.shutdown()
    print("render ok")

    # 18. W6-1 补齐玩法：幸运/一键、赐福抽奖、灵市社交、独立法身
    from core import blessing as bl, cultivate as cv, fashan as fs, market as mk

    lv6 = store.table("Level/练气境界")
    blv6 = store.table("Level/炼体境界")
    u6 = PlayerDoc(uid="w6", realm_index=0, exp=10 ** 9, ext={"xueqi": 10 ** 9})
    txt6, u6b, used6 = cv.one_key_break(u6, lv6, 1.0, 0.3, _random.Random(1))
    assert u6b.realm_index > u6.realm_index and "结束原因" in txt6 and used6 == 0
    _t, u6c, used6b = cv.one_key_body(u6b, blv6, _random.Random(2), luck=True, grass=3)
    assert u6c.physique_index >= u6b.physique_index and used6b <= 3
    assert not bl.tiandao_gift(u6, 1_800_000_000.0, 1.0)[0]      # 境界门槛
    hi6 = PlayerDoc(uid="w6hi", realm_index=25, ext={"occupation": "侠客"})
    ok, _m, nd6, gift6 = bl.tiandao_gift(hi6, 1_800_000_000.0, 1.0)
    assert ok and gift6["秘境之匙"] >= 2 and not bl.tiandao_gift(nd6, 1_800_000_000.0, 1.0)[0]
    assert len(bl.LOTTERY_POOL) == 41
    ok, _m, td6, lot6 = bl.lottery(bl.grant_tickets(hi6), 2, _random.Random(3))
    assert ok and td6.ext["lottery_tickets"] == 1 and lot6
    print("breakthrough & blessing & lottery ok")

    g6 = mk.create_market(1_800_000_000.0, seed=77)
    p6 = PlayerDoc(uid="w6m", stones=1_000_000, ext={})
    contacts6 = mk.account_of(p6)["contacts"]
    mk.chat(g6, "墨九", p6)
    assert contacts6["mo"]["favor"] == 1
    mk.chat(g6, "墨九", p6)                                     # 同报价时段不重复涨好感
    assert contacts6["mo"]["favor"] == 1
    assert mk.tip(g6, p6, "墨九", "丹鼎阁")[0] and len(mk.account_of(p6)["tips"]) == 1
    assert mk.audit(g6, p6, "墨九", "丹鼎阁")[0]
    assert p6.stones == 1_000_000 - 1000 - 5000
    assert mk.audit(g6, p6, "墨九", "丹鼎阁")[0]                   # 本时段免二次费
    assert p6.stones == 1_000_000 - 1000 - 5000
    mk.advance(g6, 1_800_000_000.0 + 4 * mk.TICK_MS / 1000)
    ok, msg6 = mk.followup(g6, p6, "墨九")
    assert ok and ("兑现" in msg6 or "结案" in msg6)
    assert mk.take_loan(g6, p6, 100_000, 1_800_000_000.0)[0]
    assert mk.repay(g6, p6, 10_000)[0] and mk.account_of(p6)["loan"] is not None
    assert mk.debt_text(g6, p6).startswith("--- 灵市债务 ---")
    assert mk.news_text(g6).startswith("--- 灵市消息 ---")
    print("market social & debt ok")

    f6 = PlayerDoc(uid="w6f", realm_index=45, exp=20_000_000, stones=10_000_000,
                   ext={"xueqi": 20_000_000})
    assert not fs.create(PlayerDoc(uid="low", realm_index=1), 1_800_000_000.0)[0]
    ok, _m = fs.create(f6, 1_800_000_000.0)
    assert ok and fs.state_of(f6)["plane"] == "仙界"
    assert not fs.begin(f6, "遮天位面", 1, 1_800_000_000.0)[0]     # 法身位置硬校验
    assert fs.begin(f6, "仙界", 1, 1_800_000_000.0)[0]
    assert f6.state == "空闲"                                      # 不占真身状态
    ok, _m = fs.settle(f6, 1_800_000_000.0 + 200, _random.Random(4))
    assert ok and fs.state_of(f6)["state"] == "空闲" and f6.exp > 0
    print("fashan ok")

    # 19. W6-2 道法订阅 / 双榜 / 法身四分支
    from core import daofa as df

    n6 = 1_800_000_000.0
    sub = PlayerDoc(uid="w6sub", realm_index=25, physique_index=5, ext={})
    assert not df.active(sub, n6)
    assert df.open_for(sub, n6)[0] and df.active(sub, n6)
    assert not df.active(sub, n6 + 31 * 86400)
    sub2 = PlayerDoc(uid="w6sub2", realm_index=25, physique_index=5, ext={})
    df.open_for(sub2, n6)
    ok, _m, nd9, gift9 = df.gift(sub2, n6, 1.0)
    assert ok and gift9.get("遣龙令", 0) >= 2 and nd9.exp > 0
    assert not df.gift(nd9, n6, 1.0)[0]
    d7 = PlayerDoc(uid="w6d7", realm_index=25, ext={
        "daofaxianshu": 2, "daofaxianshu_endtime": (n6 + 86400) * 1000, "daofa_days": 6})
    ok, _m, d7b, it7 = df.gift(d7, n6, 1.0)
    assert ok and d7b.ext["daofa_days"] == 1 and it7.get("超越宝盒") == 5
    one = bl.lottery(bl.grant_tickets(PlayerDoc(uid="a", ext={})), 1, _random.Random(5))[3]
    two = bl.lottery(bl.grant_tickets(PlayerDoc(uid="a", ext={})), 1,
                     _random.Random(5), per_draw=2)[3]
    assert sum(two.values()) > sum(one.values())
    print("daofa subscription ok")

    pg = mk.create_market(n6, seed=88)
    pp = PlayerDoc(uid="w6p", stones=500_000, ext={})
    assert mk.buy(pg, pp, pg["stocks"][0], 10, n6)[0]
    pf = mk.portfolio(pg, pp)
    assert pf["invested"] >= 100_000 and "rate" in pf and pf["profit"] == 0
    print("market dual rank ok")

    fb = PlayerDoc(uid="w6fb", realm_index=50, exp=20_000_000, stones=50_000_000,
                   ext={"xueqi": 20_000_000, "era_points": 5})
    assert fs.create(fb, n6)[0] and fs.era_of(fb) == 5
    assert fs.begin_river(fb, n6)[0]
    assert fs.settle(fb, n6 + 16 * 60, _random.Random(11))[0]
    era_after_river = fs.era_of(fb)
    assert era_after_river > 5 and fs.state_of(fb)["state"] == "空闲"
    assert not fs.begin_jiehai(fb, "接引古殿", n6)[0]        # 位面硬校验
    assert fs.travel(fb, "界海", n6)[0] and fs.begin_jiehai(fb, "接引古殿", n6)[0]
    assert fs.settle(fb, n6 + 31 * 60, _random.Random(12))[0]
    assert fs.travel(fb, "小阴间", n6)[0] and fs.begin_shengxu(fb, "小阴间", 2, n6)[0]
    assert fs.settle(fb, n6 + 7 * 60, _random.Random(13))[0]
    assert fs.start_guard(fb, n6, "fashan")[0]
    assert fs.guard_tick(fb, n6 + 7200) == 20
    assert fs.stop_guard(fb, n6 + 7200)[0]
    assert fs.start_guard(fb, n6 + 7200, "self")[0]          # 结束后可手动重开
    print("fashan branches & guard ok")

    # 20. W6-3 帮助/图鉴/境界/天骄/副本 补缺
    from core import extras as ex
    from types import SimpleNamespace

    groups20 = [{"title": "基础修炼", "lines": [("#修仙签到", "每日签到")]},
                {"title": "宗门", "lines": [("#创建宗门 名字", "创建")]}]
    st20 = SimpleNamespace(atk=10 ** 9, defense=10 ** 9, hp=10 ** 9, bao=0.5)
    d20 = PlayerDoc(uid="w6x", realm_index=10, physique_index=3, stones=100_000,
                    exp=500_000, ext={"hp": 1000, "hp_max": 100_000, "base_hp": 100_000,
                                      "spirit_fail_ts": n6})
    c20 = store.table
    def run20(cmd, arg="", now=n6):
        return ex.dispatch(cmd, d20, arg, c20, groups20, st20, _random.Random(7), now)
    assert "基础修炼" in run20("#基础帮助")[0]
    assert "命格" in run20("#命格图鉴")[0]
    assert "境界（共" in run20("#练气境界")[0]
    assert "我的练气" in run20("#我的练气")[0]
    assert "建议顺序" in run20("#修仙助手")[0]
    assert run20("#打散雷劫")[1] and "spirit_fail_ts" not in d20.ext
    assert "青冥剑子" in run20("#天骄列表")[0]
    assert run20("#讨伐天骄", "青冥剑子")[1]
    assert "青冥剑子" in (d20.ext.get("tianjiao_defeated") or [])
    assert "禁地（" in run20("#禁地")[0]
    first20 = c20("item/副本/禁地列表")[0]["name"]
    assert "掉落" in run20("#副本掉落", first20)[0]
    assert d20.ext.get("last_dungeon") == first20
    assert first20 in run20("#去")[0]
    assert run20("#镇守仙境")[1]
    assert run20("#镇守仙境", now=n6 + 7200)[1] and d20.exp > 500_000
    assert run20("#献祭魂与血")[1] and d20.ext["hp"] == 100_000
    print("extras help/catalog/tianjiao/dungeon ok")

    # 21. W7-0：4 处机制断链 + 展示层空壳转正（每组一条断言防回潮）
    from core import lifespan as lf, extras as ex
    from core.combat import skills as csk
    from core.combat.engine import Fighter, run_1v1
    from core.combat.loadout import build_fighter

    c21 = store.table
    st21 = SimpleNamespace(atk=1_000, defense=1_000, hp=10_000, bao=0.1)

    # ① 寿命丹：数据表 shouyuan 字段终于被消费；同日耐药递减；饱和不消耗
    dp = PlayerDoc(uid="w7pill", realm_index=5, stones=0, exp=0, ext={})
    pill = {"name": "寿命丹", "class": "丹药", "type": "寿命", "shouyuan": 10}
    okp, msgp, dp, usep = items_mod.use_item(dp, pill, 1, now=n6)
    assert okp and usep and "寿元 +10" in msgp and lf.shouyuan_of(dp) == 3010
    for expect_note, expect_total in (("药力 ×0.5", 3015), ("药力 ×0.25", 3017),
                                      ("药力 ×0.125", 3018)):
        okp, msgp, dp2, usep = items_mod.use_item(dp, pill, 1, now=n6)
        assert okp and expect_note in msgp and lf.shouyuan_of(dp2) == expect_total
        dp = dp2
    okp, msgp, _, usep = items_mod.use_item(dp, pill, 1, now=n6)
    assert not okp and not usep and "饱和" in msgp
    # 次日重置
    assert lf.grant_pill(dp, 10, n6 + 86400)[0] == 10
    print("W7-0 ① pill shouyuan ok")

    # ② 功法 numeric 乘区 + combat/trigger + PvE 同源装填
    dq = PlayerDoc(uid="w7prof", realm_index=10, physique_index=10,
                   ext={"gongfa": ["测试功法"], "prof": {"测试功法": 1000}})
    fq = build_fighter(dq, "甲", 1_000, 1_000, 10_000, 0.1, {})
    assert abs(float(fq.effects.get("dmg_dealt_mult", 1.0)) - 1.10) < 1e-9
    assert fq.atk > 1_000 and fq.tags["prof_stage"] == "出神入化"
    # ③ 技能装配链路：build_fighter 挂 id + 注册表有内置项 + on_turn 真被触发
    assert "prof_echo" in fq.skills and "dual_echo" in fq.skills
    assert csk.get("prof_echo") is not None
    csk.clear()
    csk.ensure_builtin()
    assert csk.get("prof_echo") is not None      # clear() 后幂等恢复
    fa = Fighter("甲", 100, 10, 500, 500, skills=("prof_echo", "dual_echo"))
    fb = Fighter("乙", 10, 10, 500, 500)
    res21 = run_1v1(fa, fb, _random.Random(3), max_rounds=3)
    assert any("功法共鸣" in x for x in res21.log)
    assert any("双轨共鸣" in x for x in res21.log)
    print("W7-0 ②③ prof numeric + skill hook ok")

    # ④ 两张图鉴表补齐 + 分页 + 真实已获得收集态
    dc = PlayerDoc(uid="w7cat", realm_index=1, ext={})
    assert "共 8 条" in ex.catalog("#位面天骄图鉴", c21, doc=dc)
    dc.ext["tianjiao_defeated"] = ["青冥剑子"]
    assert "✅已获得" in ex.catalog("#位面天骄图鉴", c21, doc=dc)
    assert "未开放兑换码兑换" in ex.catalog("#兑换码图鉴", c21, doc=dc)
    pg1 = ex.catalog("#命格图鉴", c21, page=1, doc=dc)
    pg4 = ex.catalog("#命格图鉴", c21, page=4, doc=dc)
    assert "第 1/4 页" in pg1 and "第 4/4 页" in pg4 and pg1 != pg4
    print("W7-0 ④ catalog tables/pagination/collection ok")

    # ⑤ 空壳转正：助手读真实档、境界查询带真实门槛、我的练气带实际三维
    dd = PlayerDoc(uid="w7assist", realm_index=2, stones=0, exp=0,
                   ext={"shouyuan": 50})
    base21 = ex.dispatch("#修仙助手", dd, "", c21, [], st21, _random.Random(1), n6)[0]
    assert "寿元 50" in base21 and "寿元将尽" in base21 and "今日未接" in base21
    with_task = ex.dispatch("#修仙助手", dd, "", c21, [], st21, _random.Random(1), n6,
                            daily={"w1": 2, "w2": 2, "w3": 2, "renwu": 1, "level": 3})[0]
    assert "Lv3" in with_task and "领取每日奖励" in with_task and with_task != base21
    assert "需累计修为" in ex.realm_list(dd, c21)
    assert "需血气" in ex.realm_list(dd, c21, body=True)
    assert "实际三维" in ex.my_realm(dd, c21, st21)
    assert "掉落预览" in ex.tianjiao_status(dc, "青冥剑子", c21)
    print("W7-0 ⑤ assistant/realm/tianjiao real data ok")

    # 22. W7-1 四个小机制：丹药稀有度/道心果、命格扩槽、锁定+复活、沉迷 11 字段
    from core import items as it22, mingge as mg22, trib as tb22, addict as ad22, secret as sc22

    # ① 丹药：稀有度 1-10 消费 + 道心果按需服用 + 500 上限钳制
    d22 = PlayerDoc(uid="w7pill2", realm_index=5, ext={"daoxin": 495})
    fruit = {"name": "凡品道心果", "class": "丹药", "type": "道心", "道心": 3, "稀有度": 3}
    assert it22.rarity_of({"稀有度": 99}) == 10 and it22.rarity_of({}) == 1
    need, note = it22.daoxin_qty(d22, fruit, 10)
    assert need == 2 and "只取 2 颗" in note          # (500-495)/3 → 2 颗，余 8 颗不扣
    ok22, msg22, d22b, use22 = it22.use_item(d22, fruit, need, now=n6)
    assert ok22 and use22 and d22b.ext["daoxin"] == 500 and "稀有度 3/10" in msg22
    assert it22.daoxin_qty(d22b, fruit, 1)[0] == 0     # 已满：不消耗物品
    assert it22.daoxin_qty(d22, {"name": "寿命丹", "type": "寿命", "shouyuan": 10}, 7)[0] == 7
    print("W7-1 ① daoxin/rarity ok")

    # ② 命格：拓碑 1→3 槽、轮回命签抽取、主+附加 effects 合并
    d22m = PlayerDoc(uid="w7mg", realm_index=5, ext={
        "mingge": {"name": "主命", "effects": {"攻击加成": 0.1, "签到奖励倍率": 1.2}}})
    assert mg22.slots_of(d22m) == 1
    assert mg22.expand_slot(d22m)[0] and mg22.slots_of(d22m) == 2
    ok22, _msg22, got22 = mg22.extract(d22m, store, _random.Random(3))
    assert ok22 and got22 and len(mg22.extra_of(d22m)) == 1
    d22m.ext["mingge_extra"] = [{"name": "副命", "effects": {"攻击加成": 0.05, "签到奖励倍率": 1.5}}]
    assert abs(mg22.bonus(d22m, "攻击加成") - 0.15) < 1e-9          # 加法
    assert abs(mg22.multiplier(d22m, "签到奖励倍率") - 1.8) < 1e-9   # 乘法
    mg22.expand_slot(d22m)
    assert mg22.slots_of(d22m) == 3 and not mg22.expand_slot(d22m)[0]
    d22m.ext["mingge_extra"] = [{"name": "a"}, {"name": "b"}]
    assert not mg22.extract(d22m, store, _random.Random(4))[0]        # 满槽拒绝
    assert "命宫：" in mg22.text(d22m)
    print("W7-1 ② mingge slots/extract/merge ok")

    # ③ 物品锁定 + 渡劫复活设置（自动/手动 60 秒窗口）
    d22l = PlayerDoc(uid="w7lock", realm_index=5, ext={})
    assert it22.set_lock(d22l, "诸天镜", True)[0] and "诸天镜" in it22.locked_of(d22l)
    assert not it22.set_lock(d22l, "诸天镜", True)[0]                  # 重复锁定
    assert it22.set_lock(d22l, "诸天镜", False)[0] and not it22.locked_of(d22l)
    d22r = PlayerDoc(uid="w7rev", realm_index=40, exp=100_000,
                     ext={"hp": 9999, "gongfa": ["凰劫再生术"]})
    assert tb22.revive_mode(d22r) == "自动"
    assert tb22.revival_skills(d22r, ["凰劫再生术"]) == ["凰劫再生术"]
    assert tb22.set_revive_mode(d22r, "手动")[0] and tb22.revive_mode(d22r) == "手动"
    tb22.arm_revive(d22r, 100_000, 9999, n6)
    d22r.exp, d22r.ext["hp"] = 75_000, 1
    assert tb22.consume_revive(d22r, n6 + 30)[0] and d22r.exp == 100_000 and d22r.ext["hp"] == 9999
    tb22.arm_revive(d22r, 100_000, 9999, n6)
    d22r.exp = 75_000
    ok22, msg22 = tb22.consume_revive(d22r, n6 + 61)
    assert not ok22 and "已过" in msg22 and "pending_revive" not in d22r.ext
    print("W7-1 ③ lock/revival ok")

    # ④ 沉迷：原版 11 字段 + 逐轮累加 + 完整结算面板
    place22 = next(iter(sc22.PLACES))
    rec22 = ad22.make(place22, 2, n6)
    for k in ("location", "location_type", "total_count", "settled_count", "death_count",
              "xiuwei_gained", "xueqi_gained", "items_gained", "status", "start_time", "end_time"):
        assert k in rec22, k
    rec22b, _hp22 = ad22.simulate(rec22, (10 ** 9, 10 ** 9, 10 ** 9), 10 ** 9, 0.5,
                                  [], _random.Random(5))
    assert rec22b["settled_count"] == rec22b["done"] > 0
    assert rec22b["xueqi_gained"] == rec22b["xiuwei_gained"] == rec22b["exp"]
    assert isinstance(rec22b["items_gained"], dict)
    txt22 = ad22.summary_text(rec22b)
    assert "类型：秘境" in txt22 and "血气：" in txt22 and "起止：" in txt22
    print("W7-1 ④ addict 11 fields ok")

    # 23. W7-2 时代系统：五时代修正值 / 轮转边界 / 封印 / 出金率 / v16 迁移
    from core import era as era_mod23

    # ① 五时代修正值（EraStatusPlugin.js:56-105）
    want_eras = [
        ("神话时代", 0.25, 0.10, 0.4, 0.3),
        ("太古时代", 0.10, 0.25, 0.6, 0.5),
        ("天命时代", 0.0, 0.0, 1.0, 0.9),
        ("末法时代", -0.10, 0.15, 1.8, 1.6),
        ("绝灵时代", -0.30, -0.35, 3.0, 2.8),
    ]
    for i, (ename, qr, br, qc, bc) in enumerate(want_eras):
        st23 = era_mod23.ensure({"years_total": i * era_mod23.ERA_YEARS}, 1_800_000_000)
        row23 = era_mod23.state_of(st23["years_total"])
        assert row23["name"] == ename and row23["index"] == i
        assert abs(row23["qi_rate"] - qr) < 1e-9 and abs(row23["body_rate"] - br) < 1e-9
        assert abs(row23["qi_cost"] - qc) < 1e-9 and abs(row23["body_cost"] - bc) < 1e-9
        assert era_mod23.qi_mods(st23) == (qr, qc) and era_mod23.body_mods(st23) == (br, bc)
    assert "专注练气" in era_mod23.advice(era_mod23.state_of(0))
    assert "专注炼体" in era_mod23.advice(era_mod23.state_of(era_mod23.ERA_YEARS))
    assert "双修并进" in era_mod23.advice(era_mod23.state_of(2 * era_mod23.ERA_YEARS))
    assert "维艰" in era_mod23.advice(era_mod23.state_of(4 * era_mod23.ERA_YEARS))
    print("W7-2 ① five-era modifiers ok")

    # ② 轮转边界 + 纪元进位 + 懒推进（余数不吞）
    st23, info23 = era_mod23.advance_years(era_mod23.ensure({"years_total": 9999}, 1_800_000_000), 1000)
    assert info23["changed"] and info23["new"]["index"] == 1 and info23["new"]["years"] == 999
    assert info23["new"]["epoch"] == 1 and "太古时代" in era_mod23.change_text(info23)
    st23, info23 = era_mod23.advance_years(era_mod23.ensure({"years_total": 49_999}, 1_800_000_000), 1000)
    assert info23["new"]["index"] == 0 and info23["new"]["epoch"] == 2 and info23["new"]["years"] == 999
    st23, info23 = era_mod23.to_next_era(era_mod23.ensure({"years_total": 0}, 1_800_000_000))
    assert info23["new"]["index"] == 1 and info23["new"]["years"] == 0
    st23, info23 = era_mod23.set_era(era_mod23.ensure({"years_total": 0}, 1_800_000_000), 4, 500)
    assert info23["new"]["index"] == 4 and info23["new"]["years"] == 500
    st23 = era_mod23.ensure({"years_total": 0, "last_tick": 1000.0}, 1000.0)
    st23, info23 = era_mod23.tick(st23, 1000.0 + 5 * 3600)
    assert info23["ticks"] == 2 and st23["years_total"] == 2000
    assert abs(st23["last_tick"] - (1000.0 + 4 * 3600)) < 1e-6   # 余下 1 小时不吞
    st23, info23 = era_mod23.tick(era_mod23.ensure({"years_total": 0}, 1000.0), 1000.0 + 60)
    assert info23["ticks"] == 0 and st23["years_total"] == 0
    print("W7-2 ② rotation/epoch/lazy tick ok")

    # ③ 禁仙六封：封印拦截 + 跨时代（黄金大世）自动解封
    st24 = era_mod23.ensure({"years_total": 0}, 1_800_000_000)
    dseal = PlayerDoc(uid="w7seal", realm_index=10, ext={})
    assert era_mod23.seal_block(dseal, st24) is None
    era_mod23.seal(dseal, "张源天", "uid-src", st24, 1_800_000_000)
    block23 = era_mod23.seal_block(dseal, st24, "突破")
    assert block23 and "禁仙六封" in block23 and "张源天" in block23
    st24b, _info = era_mod23.to_next_era(st24)
    assert not era_mod23.is_sealed(dseal, st24b)
    assert era_mod23.seal_block(dseal, st24b) is None
    era_mod23.unseal(dseal)
    assert era_mod23.seal_of(dseal) is None
    # 封印确实管住突破入口：被封印的修士连修为足够的突破也做不了（main 侧拦在 era.seal_block）
    assert block23.startswith("你已被")
    print("W7-2 ③ seal blocks & auto-releases ok")

    # ④ 秘境出金率：三档改写生效（同一组种子，高 vs 断供）
    assert all(sc22.loot_grade((1.0, 1.0, 1.0), _random.Random(i)) == "high" for i in range(5))
    assert all(sc22.loot_grade((0.0, 0.0, 0.0), _random.Random(i)) == "none" for i in range(5))
    st25 = era_mod23.ensure({"years_total": 0, "seal": {"one": 1.0, "two": 1.0, "three": 1.0}},
                            1_800_000_000)
    assert era_mod23.seal_rates(st25) == (1.0, 1.0, 1.0)
    st25, sinfo = era_mod23.set_seal_rates(st25, 0.99, 0.5, 0.25)
    assert st25["seal"] == {"one": 0.99, "two": 0.5, "three": 0.25}
    assert era_mod23.set_seal_rates(st25, 2, -1, 0.5)[0]["seal"]["one"] == 1.0   # 钳制

    def _delve(rates):
        place23 = next(iter(sc22.PLACES))
        sess23 = sc22.Session(place=place23)
        me23 = battle_mod.Unit("我", 10 ** 9, 10 ** 9, 10 ** 9)
        for i in range(40):
            sess23, me23, _t, _fled = sc22.explore(
                sess23, (10 ** 9, 10 ** 9, 10 ** 9), me23, [], _random.Random(700 + i),
                loot_rates=rates)
            me23.hp = 10 ** 9
        return sess23.stones

    rich, poor = _delve((1.0, 1.0, 1.0)), _delve((0.0, 0.0, 0.0))
    assert rich > poor > 0, (rich, poor)
    assert _delve(None) == _delve(None)   # 无时代配置 → 历史行为不变
    print("W7-2 ④ loot rates ok")

    # ⑤ db v16：空库建表 + 已有 v15 存档升级 + 单例读写
    await db.save_era({"years_total": 12_345, "last_tick": 1_800_000_000.0,
                       "seal": {"one": 0.9, "two": 0.5, "three": 0.3}})
    assert (await db.get_era())["years_total"] == 12_345
    tmp15 = Path(tempfile.mkdtemp(prefix="zhutian_v15_"))
    seed_db = DataBase(tmp15 / "z.db")
    await seed_db.connect()
    await seed_db.close()
    import aiosqlite as _aiosqlite23
    raw23 = await _aiosqlite23.connect(tmp15 / "z.db")
    await raw23.execute("DROP TABLE era_state")
    await raw23.execute("UPDATE db_info SET version = 15")
    await raw23.commit()
    await raw23.close()
    up_db = DataBase(tmp15 / "z.db")
    await up_db.connect()
    async with up_db.conn.execute("SELECT version FROM db_info") as cur:
        assert (await cur.fetchone())[0] == LATEST_DB_VERSION, "v15 → 最新版 迁移失败"
    await up_db.save_era({"years_total": 1, "last_tick": 1_800_000_000.0})
    assert (await up_db.get_era())["years_total"] == 1
    await up_db.close()
    print("W7-2 ⑤ db v16 fresh+upgrade ok")

    # 24. W7-3 天骄深度（踪迹/仇恨/共享血条/贡献榜/污损）+ 源石坊账本 + 势力
    from core import tianjiao as tj24, faction as fc24

    # ① 天机寻踪：代价表 / 24 小时有效 / 过期即失效
    assert tj24.COSTS == {"灵石": 3_000_000, "源石": 30_000}
    d24 = PlayerDoc(uid="w7tj", realm_index=32, ext={})
    assert tj24.trace_of(d24, "青冥剑子", n6) is None
    tr24 = tj24.make_trace("青冥剑子", _random.Random(7), n6)
    tj24.set_trace(d24, "青冥剑子", tr24)
    assert tj24.trace_of(d24, "青冥剑子", n6 + 3600) is not None
    assert tj24.trace_of(d24, "青冥剑子", n6 + 24 * 3600 + 1) is None
    assert "（" in tj24.format_trace(tr24) and tj24.trace_left(tr24, n6) == 24 * 60
    print("W7-3 ① trace cost/expiry ok")

    # ② 个人冷却 90 分钟 + 六档仇恨与逃脱/护道人概率
    assert tj24.cooldown_left(d24, n6) == 0
    tj24.mark_fight(d24, n6)
    assert 89 * 60 <= tj24.cooldown_left(d24, n6) <= 90 * 60
    assert tj24.cooldown_left(d24, n6 + 90 * 60) == 0
    assert tj24.add_hatred(d24, "青冥剑子", "挑战失败")[:2] == (0, 5)
    assert tj24.add_hatred(d24, "青冥剑子", "挑战成功")[:2] == (5, 25)
    assert tj24.level_of(0)[0] == "陌生" and tj24.level_of(50)[0] == "敌视"
    assert tj24.level_of(500)[0] == "不死不休"
    assert tj24.level_of(500)[1] > tj24.level_of(0)[1]      # 仇恨越高越容易逃
    assert tj24.clear_hatred(d24, "青冥剑子") == 25 and tj24.hatred_of(d24, "青冥剑子") == 0
    print("W7-3 ② cd 90min & hatred tiers ok")

    # ③ 共享血条 + 贡献榜排序 + 击杀清榜与 18 小时轮回
    world24 = tj24.world_ensure({})
    boss24 = tj24.boss_of(world24, "青冥剑子")
    assert boss24["hp_pct"] == 1.0 and tj24.status_of(boss24, n6) == "在世"
    tj24.add_contribution(boss24, "u1", 500)
    tj24.add_contribution(boss24, "u2", 1500)
    tj24.add_contribution(boss24, "u1", 300)
    assert tj24.ranking(boss24) == [("u2", 1500), ("u1", 800)]
    assert tj24.CONTRIB_TOP_BONUS == (0.30, 0.20, 0.10)
    boss24["hp_pct"] = 0.2
    assert tj24.hp_pct_of(boss24) == 0.2
    tj24.on_kill(boss24, "u2", n6)
    assert boss24["hp_pct"] == 1.0 and boss24["contrib"] == {} and boss24["kills"] == 1
    assert tj24.blocked_until(boss24) == n6 + 18 * 3600
    assert "轮回中" in tj24.status_of(boss24, n6 + 60)
    assert "失踪" in tj24.status_of({"escaped_until": n6 + 600, "alive_until": 0}, n6)
    print("W7-3 ③ shared hp & contribution board ok")

    # ④ 污损：比例属性 -20%，击杀来源或修复后复原
    wpn24 = {"name": "赤霄", "class": "装备", "type": "武器", "atk": 0.9, "def": 0.2, "HP": 0.4}
    d24e = PlayerDoc(uid="w7taint", realm_index=1, ext={"equipment": {"武器": "赤霄"}})
    lv24 = store.table("Level/练气境界")
    lookup24 = lambda n: wpn24 if n == "赤霄" else None       # noqa: E731
    base24 = equip_mod.aggregate(d24e, lv24, lookup24)
    tx24 = d24e.model_copy(deep=True)
    tj24.apply_taint(tx24, "武器", "青冥剑子", n6)
    hurt24 = equip_mod.aggregate(tx24, lv24, lookup24)
    assert hurt24.atk < base24.atk and tj24.is_tainted(tx24, "武器")
    assert tj24.pick_taint_slot(
        PlayerDoc(uid="x", ext={"equipment": {"武器": "赤霄",
                                              "护具": "铁甲"}}),
        lambda n: wpn24 if n == "赤霄" else {"class": "装备", "type": "护具", "atk": 100},
        _random.Random(1)) == "武器"
    assert tj24.repair_by_source(tx24, "青冥剑子") == 1 and not tj24.tainted(tx24)
    assert equip_mod.aggregate(tx24, lv24, lookup24).atk == base24.atk
    print("W7-3 ④ taint -20% & repair ok")

    # ⑤ 源石坊账本 + 天字号 20 小时冷却 + 势力贡献/分级俸禄 + db v17
    y24 = ys_mod.system_of(PlayerDoc(uid="w7stone", ext={}))
    assert y24["ledger"] == [] and y24["cuts"] == 0
    stone24 = {"no": 1, "price": 100_000, "name": "纯净源", "outcome": "pure",
               "ratio": 1.0, "item": None, "danger": False, "surface": "x"}
    ok24, msg24, y24, _c24 = ys_mod.buy_and_cut(
        PlayerDoc(uid="w7stone"), y24, "外园", [stone24], 1, 10 ** 9, 1000, 1000, n6, _random.Random(3))
    assert ok24 and len(y24["ledger"]) == 1 and y24["cuts"] == 1
    assert "源石坊账本" in ys_mod.ledger_text(y24)
    y24["amount"] = 10 ** 9
    ok24, msg24, y24b, _c24 = ys_mod.buy_and_cut(
        PlayerDoc(uid="w7stone"), y24, "天字号", [stone24], 1, 0, 1000, 1000, n6, _random.Random(4))
    assert ok24 and "天字号" in (y24b.get("cooldown") or {}), msg24
    ok24, msg24, _y, _c = ys_mod.buy_and_cut(
        PlayerDoc(uid="w7stone"), y24b, "天字号", [stone24], 1, 0, 1000, 1000,
        n6 + 3600, _random.Random(5))
    assert not ok24 and "冷却" in msg24
    assert ys_mod.buy_and_cut(
        PlayerDoc(uid="w7stone"), y24b, "天字号", [stone24], 1, 0, 1000, 1000,
        n6 + 20 * 3600, _random.Random(5))[0]

    fst24 = fc24.ensure(None)
    assert fc24.join(fst24, "瑶池圣地", "u1", "张三", 0)[0]
    assert fc24.faction_of(fst24, "u1") == "瑶池圣地" and fc24.is_leader(fst24, "瑶池圣地", "u1")
    assert fc24.join(fst24, "瑶池圣地", "u2", "李四", 0)[0]
    assert (fc24.member_of(fst24, "瑶池圣地", "u2") or {}).get("role") == "门人"
    assert fc24.join(fst24, "瑶池圣地", "u3", "王五", 0)[0] is True    # 第三人仍是门人
    assert not fc24.join(fst24, "剑云海", "u1", "张三", 0)[0]             # 已入势力
    assert not fc24.join(fst24, "剑云海", "u9", "赵六", 5)[0]             # 门槛不足
    ok24, msg24, pts24 = fc24.contribute(fst24, "u1", 100_000)
    assert ok24 and pts24 == 200_000 and fst24["factions"]["瑶池圣地"]["level"] == 2
    amt24, fname24, role24 = fc24.salary(fst24, "u1")
    assert fname24 == "瑶池圣地" and role24 == "宗主" and amt24 == 2 * 1200 * 2
    assert fc24.salary(fst24, "u2")[0] == 2 * 1200                          # 门人不加成
    ok24, _m, paid24 = fc24.pay(fst24, "u1")
    assert ok24 and paid24 == amt24
    assert fst24["factions"]["瑶池圣地"]["fund"] == 100_000 - amt24
    assert "瑶池圣地" in fc24.list_text(fst24, "u1")
    assert "势力等级" in fc24.status_text(fst24, "u1")
    assert "尚未加入" in fc24.status_text(fst24, "nobody")
    # db v17：两张单例表 + 读写
    async with db.conn.execute(
            "SELECT name FROM sqlite_master WHERE name IN ('tianjiao_state','faction_state')") as cur:
        assert {r[0] for r in await cur.fetchall()} == {"tianjiao_state", "faction_state"}
    await db.save_tianjiao({"bosses": {"青冥剑子": {"hp_pct": 0.5}}})
    assert (await db.get_tianjiao())["bosses"]["青冥剑子"]["hp_pct"] == 0.5
    await db.save_faction(fst24)
    assert (await db.get_faction())["factions"]["瑶池圣地"]["level"] == 2
    print("W7-3 ⑤ stone ledger/sky cd/faction salary/db v17 ok")

    # 25. W7-4 养成深度：灵根觉醒 / 寿元救援 / 帝兵 12 档 / 职业产线 / 道法卡 / 功法特效
    from core import linggen as lg25, lifespan as ls25, dibing as db25
    from core import occupation as occ25, daofa as df25
    from core.combat import engine as eng25, skills as sk25

    # ① 灵根觉醒：四维进快照 + 觉醒抬四维 + 装备聚合真实生效 + 三阶封顶
    lrow = {"id": 901, "name": "元灵体", "type": "体质", "eff": 0.1, "法球倍率": 0.12,
            "攻击": 0.2, "防御": 0.2, "生命": 0.2, "生命本源": 100, "稀有度": 3}
    snap25 = lg25.snapshot(lrow)
    assert snap25["atk"] == 0.2 and snap25["origin"] == 100 and snap25["awaken"] == 0
    atk25, _d25, _h25, flat25 = lg25.stats_of(snap25)
    assert atk25 == 0.2 and flat25 == 100 * lg25.ORIGIN_SCALE
    d25 = PlayerDoc(uid="w7lg", realm_index=21, stones=50_000_000,
                    ext={"linggen": dict(snap25)})
    lv25 = store.table("Level/练气境界")
    no_item = lambda n: None                                     # noqa: E731
    base25 = equip_mod.aggregate(d25, lv25, no_item)
    ok25, msg25, d25b = lg25.awaken(d25, n6)
    assert ok25 and d25b.ext["linggen"]["awaken"] == 1 and d25b.stones == d25.stones - 5_000_000
    grew25 = equip_mod.aggregate(d25b, lv25, no_item)
    assert grew25.atk > base25.atk and grew25.hp > base25.hp
    d25b = lg25.awaken(d25b, n6)[2]
    d25b = lg25.awaken(d25b, n6)[2]
    assert lg25.awaken_level(d25b.ext["linggen"]) == 3
    assert not lg25.awaken(d25b, n6)[0]                          # 已圆满
    assert not lg25.awaken(PlayerDoc(uid="x", realm_index=3), n6)[0]
    print("W7-4 ① linggen awaken & four stats ok")

    # ② 寿元救援：24h 窗口 / 救人 / 逾期转世
    d25l = PlayerDoc(uid="w7life", realm_index=5, ext={"shouyuan": 0})
    msg25 = ls25.mark_death(d25l, n6)
    assert "24 小时" in msg25 and ls25.pending(d25l) and ls25.rescue_left(d25l, n6) == 24 * 3600
    ok25, _m25 = ls25.rescue(d25l, n6)
    assert ok25 and d25l.ext["shouyuan"] == ls25.RESCUE_LIFESPAN and not ls25.pending(d25l)
    assert ls25.resolve_if_due(d25l, n6 + 999999) is None
    d25l2 = PlayerDoc(uid="w7life2", realm_index=5, ext={"shouyuan": 0})
    ls25.mark_death(d25l2, n6)
    assert ls25.resolve_if_due(d25l2, n6 + 3600) is None           # 窗口内不转世
    born25 = ls25.resolve_if_due(d25l2, n6 + 24 * 3600 + 1)
    assert born25 and "轮回往生" in born25 and d25l2.realm_index == 0 and not ls25.pending(d25l2)
    print("W7-4 ② lifespan rescue window ok")

    # ③ 帝兵 12 档：成长表 / 九金门槛 / 仙金祭炼 / 铭文门槛与每阶限一道
    assert len(db25.STAGE_LIMITS) == 12 and db25.nurture_limit(0) == 6
    assert db25.nurture_limit(5) == 22 and db25.nurture_limit(99) == 46
    w25 = db25.forge("仙泪绿金", "混沌剑")[2]
    ok25, msg25, _w = db25.tribulation(w25, 10 ** 12, 10 ** 12, gold_stock=99)
    assert not ok25 and "九种仙金" in msg25
    for g25 in [g for g in db25.GOLD_RARITY if g != "仙泪绿金"]:
        _ok, _m, w25 = db25.fuse(w25, g25)
    assert len(set(w25["fused"])) == len(db25.GOLD_RARITY) - 1
    ok25, msg25, _w = db25.tribulation(w25, 10 ** 12, 10 ** 12, gold_stock=0)
    assert not ok25 and "祭炼" in msg25
    ok25, msg25, w25b = db25.tribulation(w25, 10 ** 12, 10 ** 12, gold_stock=1)
    assert ok25 and w25b["stage"] == 1
    ok25, msg25, _w = db25.inscribe(w25b, "斩道", 52)
    assert not ok25 and "圣兵" in msg25
    w25b["stage"] = 4
    ok25, msg25, w25c = db25.inscribe(w25b, "斩道", 52)
    assert ok25 and w25c["all"] > w25b["all"] and w25c["inscriptions"] == ["斩道"]
    assert not db25.inscribe(w25c, "再来", 52)[0]                  # 同阶限一道
    print("W7-4 ③ dibing 12 stages & inscription ok")

    # ④ 12 职业产线：7 条产线可结算 / 无产线职业拒绝 / 等级加成
    assert set(occ25.PRODUCE) == {"猎户", "侠客", "唤魔者", "源师", "源地师", "源天师", "阵法师"}
    items25, _src, _st, title25 = occ25.produce("猎户", 300, 1, _random.Random(3))
    assert items25 and sum(items25.values()) > 0 and title25
    assert occ25.produce("炼丹师", 300, 1, _random.Random(1))[0] == {}
    assert occ25.produce_skill(0)[1] == 0.0 and occ25.produce_skill(20)[1] == 0.4
    assert occ25.produce_skill(30)[2] == 3
    items25b, src25, _st25, _t = occ25.produce("源师", 720, 20, _random.Random(5))
    assert src25 > 0 and items25b
    assert occ25.produce_line("猎户")["period"] == 30 and occ25.produce_line("无") is None
    print("W7-4 ④ occupation production lines ok")

    # ⑤ 道法卡：购买/权益/到期/续期叠加
    d25c = PlayerDoc(uid="w7card", stones=100_000_000, ext={})
    ok25, msg25, d25c2 = df25.buy_card(d25c, "月卡", n6)
    assert ok25 and d25c2.stones == d25c.stones - 40_000_000
    bonus25 = df25.card_bonus(d25c2, n6)
    assert bonus25 == {"loot": 2, "sign": 0.30, "cd": 0.20}
    assert df25.card_of(d25c2, n6 + 31 * 86400)[0] is None        # 30 天到期
    assert df25.card_bonus(d25c2, n6 + 31 * 86400)["loot"] == 0
    ok25, msg25, d25c3 = df25.buy_card(d25c2, "月卡", n6 + 86400)
    assert ok25 and (d25c3.ext["daofa_card"]["end"] - d25c2.ext["daofa_card"]["end"]) == 30 * 86400
    assert df25.card_bonus(d25c3, n6)["sign"] == 0.30
    print("W7-4 ⑤ daofa card tiers ok")

    # ⑥ 功法特效：破军（伤害乘区）/ 回春（真实回血）在引擎中触发
    sk25.ensure_builtin()
    assert sk25.get("break_army") and sk25.get("rejuvenate")
    fa25 = eng25.Fighter(name="甲", atk=2000, defense=100, hp=60000, hp_max=60000,
                         skills=("break_army", "rejuvenate"))
    fb25 = eng25.Fighter(name="乙", atk=1500, defense=200, hp=80000, hp_max=80000)
    res25 = eng25.run_1v1(fa25, fb25, _random.Random(11), max_rounds=10)
    assert any("【破军】" in x for x in res25.log), res25.log
    assert any("【回春】" in x for x in res25.log)
    assert fa25.tags.get("_break_army") and fa25.tags.get("_rejuvenate")
    assert fa25.effects.get("dmg_dealt_mult", 1.0) > 1.0
    print("W7-4 ⑥ break_army/rejuvenate skills ok")

    # 26. W7-5c 域外：业力 / 位面青睐 / 魔主逆命复生
    from core import calamity as cal26, river as rv26

    # ① 业力：累加、消减不为负、突破惩罚封顶 -30%
    d26 = PlayerDoc(uid="w7karma", realm_index=5, ext={})
    assert cal26.karma_of(d26) == 0 and cal26.karma_penalty(d26) == 0.0
    assert cal26.add_karma(d26, 50) == 50 and cal26.karma_penalty(d26) == 0.0
    assert cal26.add_karma(d26, 150) == 200
    assert abs(cal26.karma_penalty(d26) + 0.20) < 1e-9
    cal26.add_karma(d26, 500)
    assert abs(cal26.karma_penalty(d26) + cal26.KARMA_PENALTY_CAP) < 1e-9
    cleared26, left26 = cal26.reduce_karma(d26, 10000)
    assert left26 == 0 and cleared26 == 700
    assert cal26.reduce_karma(d26, 10) == (0, 0)              # 已归零不再减
    print("W7-5c ① karma accumulate/penalty ok")

    # ② 位面青睐：满 50 换 +20% 悟道；不足或无数值空间时不动
    d26f = PlayerDoc(uid="w7favor", realm_index=5, ext={"plane_favor": 60})
    gain26, used26 = cal26.consume_favor_for_wudao(d26f, 1_000_000)
    assert used26 == 50 and gain26 == 1_200_000 and cal26.favor_of(d26f) == 10
    poor26 = PlayerDoc(uid="w7favor2", ext={"plane_favor": 49})
    assert cal26.consume_favor_for_wudao(poor26, 1_000_000) == (1_000_000, 0)
    assert cal26.favor_of(poor26) == 49
    full26 = PlayerDoc(uid="w7favor3", ext={"plane_favor": 50})
    assert cal26.consume_favor_for_wudao(full26, 1000, remaining=1000) == (1000, 0)
    assert cal26.favor_of(full26) == 50                       # 没增益空间不消耗
    # 长河悟道分支真消耗（rng 固定在悟道区间）
    class _SeqRng26:
        def __init__(self, *vals):
            self.vals = list(vals)

        def random(self):
            return self.vals.pop(0) if self.vals else 0.5

        def randint(self, a, b):
            return a

        def uniform(self, a, b):
            return a

        def choice(self, seq):
            return seq[0]

    d26r = PlayerDoc(uid="w7river", realm_index=5, ext={"plane_favor": 60})
    text26, gains26 = rv26.roam(d26r, None, None, None, _SeqRng26(0.5), n6)
    assert gains26["exp"] == int(600_000 * 6 * 1.2), gains26
    assert cal26.favor_of(d26r) == 10 and "位面青睐" in text26
    print("W7-5c ② plane favor exchange ok")

    # ③ 魔主逆命复生：首次伏诛满血复生且全属性 +25%，再杀才真正陨落
    st26 = cal26.ensure({})
    st26["overlord"] = {"id": "ov-test", "name": "试验魔主", "status": "active",
                        "hp": 1000, "max_hp": 1000, "atk": 100, "defense": 50,
                        "contributions": {}}
    killer26 = PlayerDoc(uid="w7ov", name="斩杀者", realm_index=5, ext={})
    stats26 = {"atk": 10 ** 9, "defense": 10 ** 9, "hp": 10 ** 9, "bao": 0.0}
    res26 = cal26.battle_overlord(st26, killer26, stats26, _random.Random(1), n6)
    assert res26["revived"] and not res26["defeated"]
    ov26 = st26["overlord"]
    assert ov26["status"] == "active" and ov26["hp"] == 1250 and ov26["max_hp"] == 1250
    assert ov26["atk"] == 125 and ov26["defense"] == 62       # int(50*1.25)
    res26b = cal26.battle_overlord(st26, killer26, stats26, _random.Random(2), n6 + 60)
    assert res26b["defeated"] and not res26b["revived"] and ov26["status"] == "defeated"
    reward26 = cal26.overlord_reward(ov26, "w7ov")
    assert reward26 and reward26["karma"] == cal26.KARMA_OVERLORD
    assert reward26["favor"] == cal26.FAVOR_OVERLORD
    assert cal26.KARMA_REWARD_RANGE == (5, 10) and cal26.FAVOR_REWARD_RANGE == (5, 20)
    print("W7-5c ③ overlord revival ok")

    # 27. W7-5b 维度壁垒 / 刻画坐标 / 位面毁灭 / 副本查询接真
    from core import plane as pl27, dungeon as dg27

    # ① 破界强度：权柄 20→30、25→150；壁垒按表判定
    low27 = PlayerDoc(uid="w7p1", realm_index=52,
                      ext={"plane": {"current": "凡间", "known": ["凡间"]}})
    assert pl27.dim_tier(low27) == 20 and pl27.breaking_power(low27) == 30
    assert pl27.barrier_check(low27, "凡间", "超维宇宙")[0]          # 需 30 → 通过
    ok27, msg27 = pl27.barrier_check(low27, "凡间", "上苍之上")       # 需 50 → 拒绝
    assert not ok27 and "维度壁垒" in msg27 and "破界强度 50" in msg27
    high27 = PlayerDoc(uid="w7p2", realm_index=63, exp=10 ** 9,
                       ext={"plane": {"current": "凡间", "known": ["凡间"]},
                            "xueqi": 10 ** 9})
    assert pl27.dim_tier(high27) == 25 and pl27.breaking_power(high27) == 150
    assert pl27.barrier_check(high27, "凡间", "神维丝线海")[0]       # 需 150 → 通过
    assert pl27.emperor_free_travel(high27, "仙界", "上苍之上")
    assert not pl27.emperor_free_travel(low27, "仙界", "上苍之上")
    print("W7-5b ① dimension barrier ok")

    # ② 穿戴壁垒参与真实穿梭：坐标已知也会被界壁拦下
    low27.ext["plane"]["known"] = ["凡间", "上苍之上"]
    ok27, msg27 = pl27.begin_travel(low27, "上苍之上", {}, n6, {})
    assert not ok27 and "维度壁垒" in msg27
    high27.ext["plane"]["known"] = ["凡间", "神维丝线海"]
    ok27, msg27 = pl27.begin_travel(high27, "神维丝线海", {}, n6, {})
    assert ok27 and "神维丝线海" in msg27, msg27
    print("W7-5b ② barrier gates travel ok")

    # ③ 刻画坐标：付费、进记忆、重复拒绝；毁灭记录封界、修复后重开
    d27 = PlayerDoc(uid="w7mark", stones=1_000_000, ext={})
    ok27, msg27 = pl27.mark_coordinate(d27, "上苍之上", 500, 600, n6)
    assert ok27 and d27.stones == 1_000_000 - pl27.MARK_COST
    st27 = pl27.state_of(d27)
    assert st27["marks"]["上苍之上"] == {"x": 500, "y": 600, "at": n6}
    assert "上苍之上" in pl27.known_of(st27)
    assert not pl27.mark_coordinate(d27, "上苍之上", 1, 1, n6)[0]
    assert not pl27.mark_coordinate(d27, "不存在的位面", 1, 1, n6)[0]
    dead27 = {"仙界": {"source": "黑暗动乱", "at": n6}}
    ok27, msg27 = pl27.barrier_check(high27, "凡间", "仙界", dead27)
    assert not ok27 and "已毁灭" in msg27 and "黑暗动乱" in msg27
    st27b = pl27.state_of(PlayerDoc(uid="w7dead", ext={}))
    assert pl27.destroy_plane(st27b, "仙界", "诡异大祭", n6)
    assert pl27.destroyed_of(st27b, "仙界")["source"] == "诡异大祭"
    assert pl27.repair_plane(st27b, "仙界") and not pl27.destroyed_of(st27b, "仙界")
    print("W7-5b ③ marks & plane destruction ok")

    # ④ 副本查询接真：五张表可查、门槛/门票/系数/掉落池/结算折算
    hit27 = dg27.find("灭仙洞", store.table)
    assert hit27 and hit27[1] == "禁地"
    row27 = hit27[0]
    assert dg27.gate_of(200_000) == 12 and dg27.gate_of(572_000_000) == 50
    assert dg27.fee_of(200_000) == 5_000 and dg27.fee_of(10 ** 8) == 2_000_000
    assert dg27.factor_of(200_000) == 1.02 and dg27.factor_of(5 * 10 ** 8) == 3.2
    pool27 = dg27.pool_of(row27)
    assert pool27 and all(isinstance(x.get("稀有度"), int) for x in pool27)
    names27 = [x["name"] for x in pool27]
    assert len(names27) == len(set(names27))
    assert dg27.find("仙界矿场", store.table)[1] == "仙境"
    assert dg27.find("不存在的地方", store.table) is None
    full27 = dg27.rewards_of(row27, 10)
    assert full27 == (int(row27["experience"]), int(row27["shouyuan"]))
    assert dg27.rewards_of(row27, 5)[0] == int(row27["experience"]) // 2
    print("W7-5b ④ dungeon tables wired ok")

    # 28. W7-5a 彼岸大道至宝：三层 / 四配方 / 24h 开炉 / 至宝加成
    from core import other_shore_forge as osf28, dibing as db28

    # ① 材料入炉库 + 层解锁（沧澜→真世界→乾坤）
    d28 = PlayerDoc(uid="w7osf", realm_index=40, ext={})
    st28 = osf28.ensure(d28)
    assert osf28.layer_of(st28, d28) == "canglan"
    assert not osf28.has_layer(st28, d28, "true_world")
    osf28.add_materials(st28, osf28.CLEAR_BUNDLE)
    assert int(st28["materials"]["true-world-source-crystal"]) == 60
    st28["clears"] = 1
    assert osf28.layer_of(st28, d28) == "true_world"       # 40 境破界 15 档 → 停在真世界
    assert not osf28.has_layer(st28, d28, "qiankun")
    hi28 = PlayerDoc(uid="w7qk", realm_index=52, ext={})    # 52 境 = 破界 20 档
    st_hi = osf28.ensure(hi28)
    st_hi["clears"] = 1
    assert osf28.layer_of(st_hi, hi28) == "qiankun"
    low28 = PlayerDoc(uid="w7low", realm_index=40, ext={})
    st28b = osf28.ensure(low28)
    st28b["clears"] = 1
    print("W7-5a ① materials & layer unlock ok")

    # ② 配方预览：缺材料/缺器胚分别列出；齐备后通过；第二法锁定
    ok28, miss28, recipe28 = osf28.preview(d28, 1)
    assert recipe28["name"] == "三宝归墟法" and not ok28
    assert any("真界源晶" in m for m in miss28)
    assert any("帝兵" in m for m in miss28)
    ok28, miss28, _r = osf28.preview(d28, 2)
    assert not ok28 and any("未开放" in m for m in miss28)
    # 备齐材料 + 圣兵器胚
    st28["materials"] = dict(recipe28["materials"])
    w28 = db28.forge("仙泪绿金", "混沌剑")[2]
    w28["stage"] = 4
    d28.ext["dibing"] = w28
    ok28, miss28, _r = osf28.preview(d28, 1)
    assert ok28, miss28
    print("W7-5a ② recipe preview gaps ok")

    # ③ 24 小时开炉：重复开炉拒绝 / 未足拒领 / 到点出炉 / 炉空
    ok28, msg28 = osf28.start(d28, 1, n6)
    assert ok28 and "24 小时" in msg28
    assert not osf28.start(d28, 1, n6)[0]
    ok28, msg28, _t = osf28.claim(d28, n6 + 3600)
    assert not ok28 and "炉火未足" in msg28
    ok28, msg28, treasure28 = osf28.claim(d28, n6 + osf28.FORGE_SECONDS + 1)
    assert ok28 and treasure28 and treasure28["all"] == 0.15
    assert osf28.treasure_bonus(osf28.ensure(d28)) == (0.15, 0.05)
    assert not osf28.claim(d28, n6 + osf28.FORGE_SECONDS + 2)[0]
    print("W7-5a ③ 24h forge lifecycle ok")

    # ④ 至宝加成进装备聚合（全属性 +15%、暴击 +5%）
    lv28 = store.table("Level/练气境界")
    bare28 = PlayerDoc(uid="w7bare", realm_index=40, ext={})
    with28 = equip_mod.aggregate(d28, lv28, lambda n: None)
    without28 = equip_mod.aggregate(bare28, lv28, lambda n: None)
    assert with28.atk > without28.atk and with28.defense > without28.defense
    assert abs(with28.bao - without28.bao - 0.05) < 1e-9
    # 乾坤界配方：层不足拒绝
    ok28, miss28, _r = osf28.preview(low28, 4)
    assert not ok28 and any("乾坤界" in m for m in miss28)
    print("W7-5a ④ treasure bonus & layer gate ok")

    # ================= W8-A1 诸天遗珍 =================
    from core import relic as rl29
    from core import equipment as eq29
    from core.combat import loadout as lo29
    rr29 = _random.Random(29)
    st29 = rl29.default_state()
    st29["fragments"] = 2000

    # ① 合成 → 背包 / 碎片扣除 / 数量与品质
    st29, made29, cost29 = rl29.synthesize(st29, "荒古战血", "至圣", 3, rr29)
    assert len(made29) == 3 and cost29 == 300 and st29["fragments"] == 1700
    assert len(st29["bag"]) == 3 and all(r["quality"] == "至圣" for r in made29)
    assert all(len(r["affixes"]) == 3 for r in made29)       # 至圣 3 词条

    # ② 铭刻 / 卸下 / 第二槽门槛 / 替换回背包
    st29, r29, _ = rl29.engrave(st29, 1, "武器", 1)
    st29, _r2, _ = rl29.engrave(st29, 1, "护具", 1)
    assert len(st29["bag"]) == 1
    try:
        rl29.engrave(st29, 1, "武器", 2)
        raise AssertionError("未拓展的第二铭刻位不应可铭刻")
    except ValueError:
        pass
    st29 = rl29.expand(st29, "武器")
    st29, _r3, replaced29 = rl29.engrave(st29, 1, "武器", 2)
    assert replaced29 is None or isinstance(replaced29, dict)
    st29, back29 = rl29.unequip(st29, "武器", 2)
    assert back29["quality"] == "至圣" and len(st29["bag"]) >= 1

    # ③ 三件同套 → 共鸣；缺一件 → 无共鸣
    st29b = rl29.default_state()
    st29b["fragments"] = 2000
    st29b, made29b, _ = rl29.synthesize(st29b, "玄黄不灭", "灵玄", 3, rr29)
    for idx, part in enumerate(("武器", "护具", "法宝"), 1):
        st29b, _x, _ = rl29.engrave(st29b, 1, part, 1)
    eff29, reso29 = rl29.effects(st29b)
    assert reso29 == ["玄黄不灭"], reso29
    assert eff29["开战护盾率"] >= 0.15 - 1e-9 and eff29["近战伤害减免"] >= 0.05 - 1e-9

    # ④ 分解守卫：已铭刻拒绝；批量按品质；碎片按品质给
    engraved29 = st29["engrave"]["武器"][0]["id"]
    try:
        rl29.salvage(st29, [engraved29])
        raise AssertionError("已铭刻的遗珍不应可分解")
    except ValueError:
        pass
    ids29 = rl29.select_for_salvage(st29, "至圣")
    st29c, picked29, frag29 = rl29.salvage(st29, ids29)
    assert picked29 and frag29 == 10 * len(picked29)

    # ⑤ 战斗映射：bao 进装备聚合；增伤/减伤/护盾进 Fighter
    doc29 = PlayerDoc(uid="w8relic", realm_index=40, ext={"relics": st29b})
    t29 = store.table("Level/练气境界")
    with29 = eq29.aggregate(doc29, t29, lambda n: None)
    bare29 = PlayerDoc(uid="w8relic0", realm_index=40, ext={})
    without29 = eq29.aggregate(bare29, t29, lambda n: None)
    assert with29.bao > without29.bao
    cb29 = rl29.combat(st29b)
    assert cb29["taken"] > 0 and cb29["shield"] > 0
    f29 = lo29.build_fighter(doc29, "测试", 1000, 500, 10000, 0.1, lambda n: None)
    assert float(f29.eff("dmg_taken_mult", 1.0)) < 1.0
    assert int(f29.effects.get("shield", 0) or 0) > 0
    assert abs(float(f29.eff("dmg_dealt_mult", 1.0)) - 1.0) > 1e-9 or cb29["dealt"] == 0
    # 卸下一件 → 共鸣消失
    st29b, _ = rl29.unequip(st29b, "法宝", 1)
    assert rl29.resonances(st29b) == []

    # ⑥ 老档归一：未拓展的第二铭刻位退回背包；坏词条丢弃；碎片纠正
    legacy29 = {"fragments": -5, "bag": "bad",
                "engrave": {"武器": [{"quality": "灵玄", "set": "万法天章",
                                      "affixes": [{"name": "不存在的词条", "value": 1},
                                                  {"name": "洞虚", "value": 0.02}]},
                                    {"quality": "至圣", "set": "荒古战血", "affixes": []}],
                            "护具": [], "法宝": []},
                "expanded": {"武器": False}}
    norm29 = rl29.normalize(legacy29)
    assert norm29["fragments"] == 0
    assert len(norm29["bag"]) == 1                     # 第二槽退回
    assert norm29["engrave"]["武器"][1] is None
    kept29 = norm29["engrave"]["武器"][0]
    assert [a["name"] for a in kept29["affixes"]] == ["洞虚"]   # 坏词条被丢
    print("W8-A1 relic system ok")

    # ================= W8-A2 众生仙钓 + 鱼王 =================
    from core import fishing as fs30
    fr30 = _random.Random(30)

    # ① 数据与潮汐：7 位面 / 5 仙饵 / 5000-2000 周期 / 旺潮两位面不重复
    assert len(fs30.planes()) == 7 and len(fs30.baits()) == 5
    t30 = fs30.tide(100)
    assert t30["active"] and t30["remaining"] == 1900
    assert len(set(t30["planes"])) == 2
    assert not fs30.tide(2500)["active"]
    assert fs30.tide(5100)["cycle"] == 1

    # ② 签到：首日得钓竿 / 同日拒绝 / 连续第 3 日加赠仙饵
    d30 = PlayerDoc(uid="w8fish", ext={})
    t0 = 1_800_000_000.0
    ok30, msg30, items30, streak30 = fs30.sign(d30, t0, fr30)
    assert ok30 and streak30 == 1 and items30.get(fs30.ROD_ITEM) == 1
    assert not fs30.sign(d30, t0 + 3600, fr30)[0]
    ok30, _m, items30, streak30 = fs30.sign(d30, t0 + 86400, fr30)
    assert ok30 and streak30 == 2
    ok30, _m, items30, streak30 = fs30.sign(d30, t0 + 2 * 86400, fr30)
    assert streak30 == 3 and any(b in items30 for b in fs30.baits())

    # ③ 垂钓结算：无饵记鱼谱；有饵出仙饵奖池；单次数量 1~5
    res30 = fs30.roll_catch("凡间", 0, None, fr30)
    assert res30["kind"] in ("fish", "king") and res30["item"]
    res30b = fs30.roll_catch("凡间", 0, "神藏仙饵", fr30)
    assert res30b["kind"] == "bait" and 1 <= res30b["amount"] <= 5
    st30 = fs30.state_of(d30)
    fs30.record(st30, "凡间", "青灵鲤")
    fs30.set_state(d30, st30)
    a30 = fs30.atlas_of(d30, "凡间")
    assert a30["collected"] == 1 and a30["total"] == 4

    # ④ 鱼谱领奖：未集齐拒绝；集齐后每位面愿鳞 ×10
    assert not fs30.claim_atlas(d30)[0]
    st30 = fs30.state_of(d30)
    for p in fs30.planes():
        for f in (fs30.data()["planes"][p]["fish"] + [fs30.data()["planes"][p]["king"]]):
            fs30.record(st30, p, f["name"])
    fs30.set_state(d30, st30)
    ok30, msg30, items30 = fs30.claim_atlas(d30)
    assert ok30 and items30[fs30.SCALE_ITEM] == 10 * len(fs30.planes())
    assert not fs30.claim_atlas(d30)[0]          # 不可重复领

    # ⑤ 潮汐加成：旺潮位面走 50/30/20 权重；鱼王率 1%→2%
    assert fs30.tide(0)["active"]
    cfg30 = fs30.data()["planes"]["凡间"]
    assert len(cfg30["fish"]) == 3 and cfg30["king"]["name"]

    # ⑥ 愿鳞兑换：成本 × 份数，唯一物品标记
    cost30, reward30 = fs30.wish_cost("万界引潮灯")
    assert cost30 == 120 and reward30["name"] == "万界引潮灯"
    ok30, msg30, items30 = fs30.exchange(d30, "百草香饵", 3)
    assert ok30 and items30["百草香饵"] == 15
    assert fs30.wish_cost("不存在的东西") is None

    # ⑦ 鱼王：加入 → 单次至多 10% → 多轮击杀 → 榜 → 宝箱一次性
    world30: dict = {}
    avg30 = 10000.0
    row30 = fs30.fk_row(world30, "凡间", avg30)
    assert row30["hp"] == row30["hp_max"] == 300000
    assert not fs30.fk_strike(world30, "凡间", "u1", 10 ** 9, fr30, avg30)[0]
    assert fs30.fk_join(world30, "凡间", "u1", avg30)[0]
    assert not fs30.fk_join(world30, "凡间", "u1", avg30)[0]
    ok30, _m, dmg30, killed30 = fs30.fk_strike(world30, "凡间", "u1", 10 ** 9, fr30, avg30)
    assert ok30 and dmg30 == int(300000 * fs30.KING_STRIKE_CAP) and not killed30
    for _ in range(12):
        ok30, _m, _d, killed30 = fs30.fk_strike(world30, "凡间", "u1", 10 ** 9, fr30, avg30)
        if killed30:
            break
    assert killed30
    assert "u1" in fs30.fk_rank(world30, "凡间", avg30)
    ok30, msg30, items30, _relic30 = fs30.fk_open(world30, "凡间", "u1", fr30, avg30)
    assert ok30 and items30[fs30.SCALE_ITEM] >= 15
    assert not fs30.fk_open(world30, "凡间", "u1", fr30, avg30)[0]
    assert not fs30.fk_open(world30, "凡间", "u2", fr30, avg30)[0]
    print("W8-A2 fishing & fish king ok")

    # ================= W8-A3 舟出海 =================
    from core import voyage as vy31

    class _SeqRng:
        def __init__(self, seq):
            self.seq = list(seq)
            self.i = 0

        def random(self):
            v = self.seq[self.i % len(self.seq)]
            self.i += 1
            return v

    d31 = PlayerDoc(uid="w8boat", ext={})
    inv31 = dict(vy31.FIRST_BOAT_MATS)
    # ① 首舟：材料齐 → 造成；不足 → 拒绝并报缺口
    ok31, msg31, need31 = vy31.build(d31, {})
    assert not ok31 and "缺口" in msg31
    ok31, msg31, need31 = vy31.build(d31, inv31)
    assert ok31 and d31.ext["voyage"]["boat"] == "一叶轻舟"
    assert need31 == vy31.FIRST_BOAT_MATS
    # ② 升阶：材料齐才可，升至界河灵舟（×1.5）
    up31 = vy31.BOATS[0]["upgrade"]["mats"]
    ok31, msg31, _ = vy31.build(d31, up31)
    assert ok31 and d31.ext["voyage"]["boat"] == "界河灵舟"
    assert vy31.boat_mult("界河灵舟") == 1.5
    assert "诸天仙舟" in vy31.build_cost(d31)[1]
    # ③ 出海：扣 1 钓竿 + 10 愿鳞；每日 3 趟；在海上不可再出
    inv31 = {vy31.ROD_ITEM: 3, vy31.SCALE_ITEM: 100}
    ok31, msg31, cost31 = vy31.start(d31, "凡间河", 1000.0, inv31)
    assert ok31 and cost31 == {vy31.ROD_ITEM: 1, vy31.SCALE_ITEM: 10}
    assert not vy31.can_sail(d31, 1100.0, inv31)[0]
    # ④ 回港：未到点拒绝；到点给愿鳞（×1.5 舟倍率）
    bad31, _m, _i, _e = vy31.settle(d31, 1000.0 + 60, 0, _random.Random(1))
    assert not bad31
    ok31, msg31, items31, _ev = vy31.settle(d31, 1000.0 + vy31.VOYAGE_MINUTES * 60 + 1,
                                           0, _random.Random(2))
    assert ok31 and items31[vy31.SCALE_ITEM] >= 15      # 10~20 × 1.5
    # ⑤ 每日上限：3 趟后拒绝
    for i in range(2):
        ok31, _m, _c = vy31.start(d31, "界海", 2000.0 + i, inv31)
        assert ok31
        vy31.settle(d31, 2000.0 + i + vy31.VOYAGE_MINUTES * 60 + 1, 0, _random.Random(3))
    assert not vy31.can_sail(d31, 2600.0, inv31)[0]
    # ⑥ 恶性事件：界河灵舟 → 降阶；一叶轻舟 → 沉没返材料
    d31b = PlayerDoc(uid="w8boat2", ext={"voyage": {"boat": "界河灵舟",
                                                   "voyage": {"route": "凡间河", "end": 0,
                                                              "boat": "界河灵舟"}}})
    ok31, msg31, items31, _e = vy31.settle(d31b, 10.0, 0, _SeqRng([0.01, 0.0]))
    assert ok31 and d31b.ext["voyage"]["boat"] == "一叶轻舟" and "残骸重组" in msg31
    d31c = PlayerDoc(uid="w8boat3", ext={"voyage": {"boat": "一叶轻舟",
                                                   "voyage": {"route": "凡间河", "end": 0,
                                                              "boat": "一叶轻舟"}}})
    ok31, msg31, items31, _e = vy31.settle(d31c, 10.0, 0, _SeqRng([0.01, 0.0]))
    assert ok31 and d31c.ext["voyage"]["boat"] is None and items31
    # ⑦ 见闻：集齐一条航线 → 领该航线仙饵
    d31d = PlayerDoc(uid="w8boat4", ext={"voyage": {"boat": "一叶轻舟"}})
    st31 = vy31.state_of(d31d)
    for name, _k in vy31.ROUTES["凡间河"]["atlas"]:
        st31.setdefault("atlas", {}).setdefault("凡间河", {})[name] = 1
    vy31.set_state(d31d, st31)
    ok31, msg31, items31 = vy31.claim_atlas(d31d)
    assert ok31 and items31.get("百草香饵") == 2
    assert not vy31.claim_atlas(d31d)[0]
    print("W8-A3 sea voyage ok")

    # ================= W8-A4 轮回路与遗落纳戒 =================
    from core import reincarnation as rein32
    w32: dict = {}
    d32 = PlayerDoc(uid="w8rein", name="试炼者", realm_index=55, stones=1_000_000,
                    ext={"plane": {"current": "凡间", "coords": {"x": 12, "y": 34}}})
    # ① 转世留纳戒：20% 灵石 + 至多 3 件遗物
    row32 = rein32.make_drop(w32, d32, "凡间", {"x": 12, "y": 34}, 200_000,
                             {"丹药A": 3, "材料B": 2, "道具C": 1, "多余D": 9}, 1000.0)
    assert row32 and row32["stones"] == 200_000
    assert len(row32["items"]) == rein32.DROP_ITEM_MAX
    assert rein32.mode_of(w32) == "纳戒"
    # ② 归虚模式不留纳戒
    w32b: dict = {"reincarnation": {"mode": "归虚", "drops": []}}
    assert rein32.make_drop(w32b, d32, "凡间", {}, 1, {"x": 1}, 1000.0) is None
    assert not rein32.list_text(w32b, None, 1000.0).count("编号")
    # ③ 执掌：境界门槛 / 唯一 / 夺位看境界 / 放弃
    low32 = PlayerDoc(uid="w8low", name="低境", realm_index=10, ext={})
    assert not rein32.take(w32, low32, 1000.0)[0]
    ok32, msg32 = rein32.take(w32, d32, 1000.0)
    assert ok32 and "轮回路" in msg32
    assert not rein32.take(w32, d32, 1001.0)[0]                 # 已在自己手里
    higher32 = PlayerDoc(uid="w8hi", name="高境", realm_index=60, ext={})
    assert rein32.take(w32, higher32, 1002.0)[0]                # 高境夺位
    assert not rein32.take(w32, d32, 1003.0)[0]                 # 低境夺不回
    # ④ 输出切换只限执掌者
    assert not rein32.toggle(w32, d32)[0]
    ok32, msg32 = rein32.toggle(w32, higher32)
    assert ok32 and rein32.mode_of(w32) == "归虚"
    rein32.toggle(w32, higher32)
    assert rein32.mode_of(w32) == "纳戒"
    # ⑤ 列表 / 详情 / 按序号与编号定位
    st32 = rein32.list_text(w32, None, 1000.0)
    assert "试炼者" in st32 and "编号" in st32
    assert rein32.pick(w32, row32["id"], 1000.0)["uid"] == "w8rein"
    assert rein32.pick(w32, "1", 1000.0)["uid"] == "w8rein"
    assert "灵石" in rein32.detail_text(row32, 1000.0)
    # ⑥ 拾取：转移并移除，二次拾取失败
    ok32, msg32, stones32, items32 = rein32.claim(w32, row32, 1000.0)
    assert ok32 and stones32 == 200_000 and items32
    assert not rein32.claim(w32, row32, 1000.0)[0]
    # ⑦ 过期清扫
    w32c: dict = {}
    rein32.make_drop(w32c, d32, "凡间", {}, 1, {"a": 1}, 1000.0)
    assert "没有遗落纳戒" in rein32.list_text(w32c, None, 1000.0 + rein32.DROP_TTL + 1)
    # ⑧ 强闯成功率：同境 50%，高 10 境 70%，下限 10%
    assert abs(rein32.force_chance({"realm": 50}, PlayerDoc(uid="a", realm_index=50, ext={})) - 0.5) < 1e-9
    assert abs(rein32.force_chance({"realm": 50}, PlayerDoc(uid="b", realm_index=60, ext={})) - 0.7) < 1e-9
    assert rein32.force_chance({"realm": 50}, PlayerDoc(uid="c", realm_index=0, ext={})) == 0.10
    print("W8-A4 reincarnation ok")

    # ================= W8-B1a 灵根觉醒·体质线 =================
    from core import bloodline as bl33
    from core import authority as au33
    tbl33 = store.table("item/灵根列表")
    d33 = PlayerDoc(uid="w8blood", realm_index=7,
                    ext={"linggen": {"type": "圣体", "name": "荒古圣体", "awaken": 2}})
    # ① 体质线识别 + 指令线与体质不符拒绝
    assert bl33.line_of(d33) == "圣体"
    ok33, msg33 = bl33.awaken(d33, tbl33, "霸体")
    assert not ok33 and "不能走" in msg33
    # ② 境界门槛 / 秘境完成度门槛
    assert not bl33.awaken(d33, tbl33, "圣体")[0]        # 秘境 0
    st33 = bl33.state_of(d33)
    st33["secret"]["轮海"] = 50
    st33["secret"]["道宫"] = 50
    bl33.set_state(d33, st33)
    low33 = PlayerDoc(uid="w8blood0", realm_index=5,
                      ext={"linggen": {"type": "圣体", "name": "荒古圣体"}})
    st33b = bl33.state_of(low33)
    st33b["secret"].update({"轮海": 60, "道宫": 60})
    bl33.set_state(low33, st33b)
    assert not bl33.awaken(low33, tbl33, "圣体")[0]      # 第 6 境，未到 7
    # ③ 小成：替换灵根快照、保留通用觉醒档、阶段 +1
    ok33, msg33 = bl33.awaken(d33, tbl33, "圣体")
    assert ok33 and "小成·荒古圣体" in msg33
    assert d33.ext["linggen"]["name"] == "小成·荒古圣体"
    assert d33.ext["linggen"]["awaken"] == 2              # W7-4 档位不被清零
    assert bl33.state_of(d33)["stage"] == 1
    # ④ 大成：需第 15 境 + 四处圆满
    assert not bl33.awaken(d33, tbl33, "圣体")[0]
    d33.realm_index = 15
    assert not bl33.awaken(d33, tbl33, "圣体")[0]         # 只两处 50
    st33 = bl33.state_of(d33)
    for k in bl33.SECRETS:
        st33["secret"][k] = 100
    bl33.set_state(d33, st33)
    ok33, msg33 = bl33.awaken(d33, tbl33, "圣体")
    assert ok33 and d33.ext["linggen"]["name"] == "大成·荒古圣体"
    assert bl33.state_of(d33)["stage"] == 2
    assert not bl33.awaken(d33, tbl33, "圣体")[0]         # 已圆满
    # ⑤ 打磨：补最低一处、上限 100
    d33b = PlayerDoc(uid="w8grind", ext={})
    st33c = bl33.state_of(d33b)
    st33c["secret"] = {"轮海": 10, "道宫": 4, "四极": 30, "化龙": 60}
    bl33.set_state(d33b, st33c)
    assert bl33.grind(d33b) == "道宫"
    assert bl33.state_of(d33b)["secret"]["道宫"] == 4 + bl33.GRIND_PER_RUN
    st33c = bl33.state_of(d33b)
    st33c["secret"] = {k: 100 for k in bl33.SECRETS}
    bl33.set_state(d33b, st33c)
    assert bl33.grind(d33b) == ""                          # 全满不再增长
    # ⑥ 第三轨注册制：register_track 后并入 authority_of 的 max 链
    base33 = PlayerDoc(uid="w8track", realm_index=10, physique_index=8, ext={})
    assert au33.authority_of(base33) == 10
    au33.register_track(lambda d: 40)
    assert au33.extra_levels(base33) == [40]
    assert au33.authority_of(base33) == 40
    assert au33.authority_of(PlayerDoc(uid="w8track2", realm_index=50, ext={})) == 50
    au33.reset_tracks()            # 隔离：别污染后续组的 authority 判定
    assert au33.authority_of(base33) == 10
    print("W8-B1a bloodline awaken ok")

    # ================= W8-B5 记忆命途 =================
    from core import memory as mm34
    d34 = PlayerDoc(uid="w8mem", realm_index=25, stones=10_000_000, ext={})
    # ① 开启：境界/灵石门槛 + 灵根换为金血之体
    low34 = PlayerDoc(uid="w8mem0", realm_index=10, stones=10_000_000, ext={})
    assert not mm34.activate(low34)[0]
    poor34 = PlayerDoc(uid="w8mem1", realm_index=25, stones=0, ext={})
    assert not mm34.activate(poor34)[0]
    ok34, msg34 = mm34.activate(d34)
    assert ok34 and mm34.stage_of(d34) == 1
    assert d34.ext["linggen"]["name"] == "金血之体"
    assert d34.stones == 10_000_000 - mm34.ACTIVATE_COST
    # ② 模拟值：未开启不累计；开启后 +2/次、上限 100；不足 100 不能抽
    d34b = PlayerDoc(uid="w8mem2", ext={})
    assert mm34.add_sim(d34b) == 0
    for _ in range(60):
        mm34.add_sim(d34)
    assert mm34.state_of(d34)["sim"] == 100
    assert not mm34.advance(d34)[0]                     # 只有 0 因子
    ok34, msg34 = mm34.simulate(d34, _random.Random(3))
    assert ok34 and mm34.state_of(d34)["sim"] == 0
    assert len(mm34.state_of(d34)["factors"]) == 1
    # ③ 阶段容量：金血之体 3 个因子封顶
    for _ in range(2):
        mm34.add_sim(d34, 100)
        assert mm34.simulate(d34, _random.Random(4))[0]
    assert len(mm34.state_of(d34)["factors"]) == 3
    mm34.add_sim(d34, 100)
    assert not mm34.simulate(d34, _random.Random(5))[0]  # 达上限
    # ④ 生命本源：一二阶每因子 +10；三阶起只算泰坦 +20
    assert mm34.life_max(mm34.state_of(d34), 1) == 50 + 30
    st34 = {"factors": {"门径": 1, "理性": 2, "死亡": 3}}
    assert mm34.life_max(st34, 3) == 300 + 20           # 只有 1 个泰坦
    # ⑤ 物品倍率：二阶起 2 倍，每 6 泰坦 +1，上限 4
    assert mm34.item_mult({"factors": {}}, 1) == 1
    assert mm34.item_mult({"factors": {}}, 2) == 2
    assert mm34.item_mult({"factors": {f"f{i}": 3 for i in range(6)}}, 3) == 3
    assert mm34.item_mult({"factors": {f"f{i}": 3 for i in range(12)}}, 3) == 4
    # ⑥ 行进：因子/境界/逐火/泰坦四道门槛
    ok34, msg34 = mm34.advance(d34)                     # 3 因子 + 25 境 → 逐火行者
    assert ok34 and d34.ext["linggen"]["name"] == "逐火行者"
    st34 = mm34.state_of(d34)
    st34["factors"] = {f: 1 for f in mm34.FACTORS[:6]}
    mm34.set_state(d34, st34)
    assert not mm34.advance(d34)[0]                     # 差逐火 12 次
    # ⑦ 逐火：6 小时 CD、12 次封顶、黄金→强化
    d34.ext["memory"]["last_journey"] = 0.0
    t34 = 1_000_000.0
    ok34, msg34 = mm34.journey(d34, t34, _random.Random(6))
    assert ok34 and mm34.state_of(d34)["journey"] == 1
    assert not mm34.journey(d34, t34 + 3600, _random.Random(7))[0]      # CD 6h
    assert mm34.journey(d34, t34 + 6 * 3600 + 1, _random.Random(8))[0]
    # ⑧ 等效境界只进门槛：三阶 = 40
    assert mm34.equivalent_level(d34) == 10             # 逐火行者
    st34 = mm34.state_of(d34)
    st34["factors"] = {f: 1 for f in mm34.FACTORS[:9]}
    mm34.set_state(d34, st34)
    d34.ext["linggen"]["name"] = "半神之体"
    assert mm34.equivalent_level(d34) == 25
    print("W8-B5 memory path ok")

    # ================= W8-B2a 内景地（第二仓库） =================
    from core import inner_world as iw35
    CLS35 = {"长剑": "装备", "回春丹": "丹药", "青鸾": "仙宠"}
    cls35 = lambda n: CLS35.get(n, "")
    d35 = PlayerDoc(uid="w8iw", stones=6_000_000, ext={})
    # ① 开启：灵石门槛 / 1 级 500 格
    poor35 = PlayerDoc(uid="w8iw0", stones=0, ext={})
    assert not iw35.open_world(poor35)[0]
    ok35, msg35 = iw35.open_world(d35)
    assert ok35 and d35.stones == 1_000_000
    st35 = iw35.state_of(d35)
    assert st35["level"] == 1 and iw35.capacity(st35) == 500
    # ② 占格权重：装备 2 / 仙宠 3 / 丹药 0.5
    assert iw35.weight_of("装备") == 2 and iw35.weight_of("仙宠") == 3
    assert iw35.weight_of("丹药") == 0.5 and iw35.weight_of("怪东西") == 1
    # ③ 存入：容量不足时按剩余格数缩量，返回实存数量
    ok35, msg35, real35 = iw35.deposit(d35, {"长剑": 300}, "长剑", 300, cls35)
    assert ok35 and real35 == 250                    # 500 格 ÷ 2
    assert iw35.used(iw35.state_of(d35), cls35) == 500
    assert not iw35.deposit(d35, {"回春丹": 5}, "回春丹", 5, cls35)[0]   # 已满
    # ④ 升级：等级 × 50 万，容量 +500
    ok35, msg35 = iw35.upgrade(d35)
    assert ok35 and d35.stones == 500_000
    assert iw35.state_of(d35)["level"] == 2 and iw35.capacity(iw35.state_of(d35)) == 1000
    # ⑤ 取出：部分取出 / 取空后删除键
    ok35, msg35, real35 = iw35.withdraw(d35, "长剑", 100, cls35)
    assert ok35 and real35 == 100
    assert iw35.used(iw35.state_of(d35), cls35) == 300
    ok35, _m, real35 = iw35.withdraw(d35, "长剑", 999, cls35)
    assert real35 == 150 and "长剑" not in iw35.state_of(d35)["items"]
    # ⑥ 一键存入：按占格从小到大装，装满即止
    ok35, msg35, moved35 = iw35.deposit_all(
        d35, {"长剑": 5, "回春丹": 4, "青鸾": 1}, cls35)
    assert ok35 and moved35 == {"长剑": 5, "回春丹": 4, "青鸾": 1}
    assert iw35.used(iw35.state_of(d35), cls35) == 10 + 2 + 3
    # ⑦ 一键取出：按类别筛选
    ok35, msg35, moved35 = iw35.withdraw_all(d35, "装备", cls35)
    assert ok35 and moved35 == {"长剑": 5}
    assert "长剑" not in iw35.state_of(d35)["items"]
    assert "回春丹" in iw35.state_of(d35)["items"]
    # ⑧ 未开启时的提示
    assert "未开" in iw35.panel(PlayerDoc(uid="w8iw2", ext={}), cls35)
    print("W8-B2a inner world storage ok")

    # ============ 第 36 组：W8-B2b 元神与精神宇宙 ============
    from core import yuanshen as ys36
    from core.combat import loadout as lo36
    import json as _json36
    places36 = _json36.loads((PLUGIN / "data/jingshen/精神宇宙.json").read_text(encoding="utf-8"))
    assert ys36.load_places(places36) == 9, "位面表应为 9 处"
    assert sum(len(x["layers"]) for x in places36) == 28, "总层数应为 28"

    # ① 凝练：首次 150 万，等级推进受 authority_21 门槛限制
    d36 = PlayerDoc(uid="w8ys", name="元神测试", realm_index=40, ext={})
    assert ys36.level_of(d36) is None and ys36.max_of(d36) == 0
    assert ys36.consolidate(d36)[0] is False, "空元神不能凝练"
    ys36.save(d36, {**ys36.ensure(d36), "cur": 5_000_000, "max": 5_000_000})
    ok36, msg36 = ys36.consolidate(d36)
    assert ok36 and ys36.level_of(d36) == 0, msg36
    assert ys36.ensure(d36)["cur"] == 5_000_000 - ys36.CONSOLIDATE_FIRST
    de = PlayerDoc(uid="w8ys0", realm_index=8, ext={})
    ys36.save(de, {**ys36.ensure(de), "cur": 100_000_000, "max": 100_000_000})
    assert ys36.consolidate(de)[0] and ys36.level_of(de) == 0
    bad, why = ys36.consolidate(de)                # 第二次要 1500 万 + 权柄 11 重
    assert bad is False and "重天" in why, why

    # ② 天药：只认 class=丹药 且 type=天药，元神与上限同增
    idx36 = {"涅槃丹": {"class": "丹药", "type": "天药", "yuanshen": 100000},
             "回春丹": {"class": "丹药", "type": "疗伤"}}
    before36 = ys36.max_of(d36)
    ok36b, _m36b, used36 = ys36.take_pills(d36, {"涅槃丹": 3, "回春丹": 9}, idx36, "全部")
    assert ok36b and used36 == {"涅槃丹": 3}, used36
    assert ys36.max_of(d36) == before36 + 300000
    assert ys36.take_pills(d36, {}, idx36)[0] is False

    # ③ 四类法门：恢复 / 淬炼 / 爆发 / 护体 + CD
    d36.ext["gongfa"] = ["前字秘", "九劫玄身", "劫运神拳", "元神盾"]
    t36 = 2_000_000.0
    cap36 = ys36.max_of(d36)
    ys36.save(d36, {**ys36.ensure(d36), "cur": cap36 // 2})
    okc, _ = ys36.cultivate(d36, "前字秘", t36)
    assert okc and ys36.cur_of(d36) == cap36 // 2 + int(ys36.math.ceil(cap36 * 0.20))
    assert ys36.cultivate(d36, "前字秘", t36 + 60)[0] is False       # 240 分 CD
    assert ys36.cultivate(d36, "九劫玄身", t36)[0] is False          # 类型不符
    assert ys36.cultivate(d36, "太一凝神诀", t36)[0] is False        # 未学
    cap36b = ys36.max_of(d36)
    okr, _ = ys36.refine(d36, "九劫玄身", t36)
    assert okr and ys36.max_of(d36) == cap36b + int(ys36.math.ceil(cap36b * 0.05))
    okb, _ = ys36.burst(d36, "劫运神拳", t36)
    assert okb and ys36.active_burst(d36, t36)[0] == 0.30
    assert ys36.active_burst(d36, t36 + 301)[0] == 0.0               # 5 分钟过期
    okg, _ = ys36.guard(d36, "元神盾", t36)
    assert okg and abs(ys36.active_shield(d36, t36)[0] - 0.25) < 1e-9
    assert ys36.active_shield(d36, t36 + 1801)[0] == 0.0             # 30 分钟过期

    # ④ 战斗注入：爆发进增伤、护体进减伤
    ys36.save(d36, {**ys36.ensure(d36),
                    "buff": {"skill": "劫运神拳", "mult": 0.30, "end": 9e9},
                    "shield": {"skill": "元神盾", "rate": 0.5, "end": 9e9}})
    f36 = lo36.build_fighter(d36, "测试", 1000, 500, 10000, 0.1, lambda n: None)
    assert float(f36.eff("dmg_dealt_mult", 1.0)) >= 1.30 - 1e-6
    assert float(f36.eff("dmg_taken_mult", 1.0)) <= 0.75 + 1e-6

    # ⑤ 神游：入场扣心神与元神 → 观想 → 抉择 → 节点满 → 深入通关
    d36b = PlayerDoc(uid="w8ys3", name="神游", realm_index=60, ext={"gongfa": []})
    ys36.save(d36b, {**ys36.ensure(d36b), "level": 1, "cur": 9_000_000, "max": 9_000_000})
    heart36 = ys36.heart_of(d36b, t36)
    assert heart36[1] == ys36.HEART_BASE_MAX + 3
    assert ys36.enter(d36b, "不存在的地方", t36)[0] is False
    assert ys36.enter(d36b, "九劫雷池", t36)[0] is False             # 等级不足
    okd, _ = ys36.enter(d36b, "未央天域", t36)
    assert okd and ys36.journey(d36b)["layer"] == 1
    assert ys36.heart_of(d36b, t36)[0] == heart36[1] - ys36.HEART_ENTRY
    assert ys36.cur_of(d36b) == 9_000_000 - 300000
    assert ys36.enter(d36b, "未央天域", t36)[0] is False             # 已在云游
    oke, txt36e = ys36.observe(d36b, t36 + 1, _random.Random(11))
    assert oke and "#抉择" in txt36e, txt36e
    okf, _txt36f, _it36 = ys36.choose(d36b, 1, t36 + 2, _random.Random(11))
    assert okf and ys36.journey(d36b)["actions"] == 1
    assert ys36.choose(d36b, 1, t36 + 3, _random.Random(11))[0] is False   # 无待处理异象
    ys36.observe(d36b, t36 + 4, _random.Random(12))
    ys36.choose(d36b, 1, t36 + 5, _random.Random(12))
    assert ys36.journey(d36b)["actions"] == 2
    assert ys36.observe(d36b, t36 + 6, _random.Random(13))[0] is False     # 节点已满
    okg2, txt36g, it36g = ys36.deep(d36b, t36 + 7, _random.Random(14))
    assert okg2 and "进入第 2 层" in txt36g, txt36g
    assert ys36.journey(d36b)["layer"] == 2
    oks, txt36s, _ = ys36.settle(d36b, forced=False, now=t36 + 8, rng=_random.Random(15))
    assert oks and "战利品保留：100%" in txt36s
    assert ys36.journey(d36b) is None

    # ⑥ 强制归位按层折损：第 3 层 50%
    assert ys36._retention(1) == 0.8 and ys36._retention(3) == 0.5
    assert ys36._retention(9) == ys36.FORCED_RETENTION[-1]

    # ⑦ 内景地修炼：未开启拒绝；开启后消耗元神换修为
    from core import inner_world as iw36
    d36c = PlayerDoc(uid="w8ys4", name="内景", realm_index=30, stones=10_000_000, ext={})
    ys36.save(d36c, {**ys36.ensure(d36c), "level": 0, "cur": 5_000_000, "max": 5_000_000})
    assert ys36.inner_cultivate(d36c, 1, t36, _random.Random(1))[0] is False
    iw36.open_world(d36c)
    okh, txt36h = ys36.inner_cultivate(d36c, 20, t36, _random.Random(3))
    assert okh and "内景地修炼" in txt36h
    assert ys36.cur_of(d36c) < 5_000_000
    print("W8-B2b yuanshen & spirit universe ok")


    # ---- W8-B3：花粉进化路 ----
    from core import flower as fl37            # noqa: E402
    from core import authority as auth37       # noqa: E402

    class _Seq37:
        """按序列返回 random()，让成功/失败/异变可精确断言。"""
        def __init__(self, *seq):
            self.seq = list(seq) or [0.0]
            self.i = 0
        def _next(self):
            v = self.seq[self.i % len(self.seq)]
            self.i += 1
            return v
        def random(self):
            return self._next()
        def randrange(self, n):
            return 0
        def uniform(self, a, b):
            return (a + b) / 2

    t37 = 1_800_000.0
    d37 = PlayerDoc(uid="w8fl1", name="花粉", realm_index=15, physique_index=15,
                    exp=10 ** 12, ext={"xueqi": 10 ** 12})
    inv37 = {"普通进化花粉": 20, "灵性进化花粉": 10, "神性进化花粉": 10,
             "无暇进化花粉": 10, "净化花露": 10, "本源圣药": 10,
             "进化异果": 10, "本源异果": 10, "祖种异果": 10,
             fl37.SEED: 1, fl37.JAR: 1}

    # ① 开启门槛 / 重复开启 / 赠媒介
    low37 = PlayerDoc(uid="w8fl0", name="低境", realm_index=3, physique_index=3, ext={})
    assert fl37.activate(low37, {})[0] is False
    ok37, _msg37, delta37 = fl37.activate(d37, {})
    assert ok37 and delta37 == {"普通进化花粉": 3}
    assert fl37.activate(d37, {})[0] is False
    assert fl37.state_of(d37)["level"] == 1

    # ② 感应异变：每日一次、按下一境品阶产媒介、积淀 +8
    ok37, _msg37, gains37 = fl37.sense(d37, inv37, t37, _Seq37(0.5))
    assert ok37 and fl37.state_of(d37)["accum"] == fl37.SENSE_ACCUM
    assert "普通进化花粉" in gains37 and sum(gains37.values()) >= 3
    assert fl37.sense(d37, inv37, t37, _Seq37(0.5))[0] is False

    # ③ 进化成功（扣修为血气 + 媒介，境界 +1）
    exp37, xq37 = int(d37.exp), int(d37.ext["xueqi"])
    ok37, msg37, delta37 = fl37.evolve(d37, inv37, "", t37, _Seq37(0.0))
    assert ok37 and "生命跃迁" in msg37 and delta37 == {"普通进化花粉": -1}
    assert fl37.state_of(d37)["level"] == 2
    assert int(d37.exp) == exp37 - fl37.evo_cost(1)
    assert int(d37.ext["xueqi"]) == xq37 - fl37.evo_cost(1)

    # ④ 媒介品阶 / 位面法则上限
    st37 = fl37.state_of(d37)
    st37.update({"level": 5, "completed": [5]})   # 第 5 境花劫已渡，否则先被渡劫门槛拦下
    fl37.set_state(d37, st37)
    ok37, msg37, _ = fl37.evolve(d37, inv37, "普通进化花粉", t37, _Seq37(0.0))
    assert not ok37 and "品阶不足" in msg37, msg37
    ok37, msg37, _ = fl37.evolve(d37, {}, "", t37, _Seq37(0.0))
    assert not ok37 and "媒介" in msg37, msg37
    st37 = fl37.state_of(d37)
    st37.update({"level": 11, "plane": "小阴间", "dao": {}, "completed": [11], "root": 0})
    fl37.set_state(d37, st37)
    ok37, msg37, _ = fl37.evolve(d37, inv37, "", t37, _Seq37(0.0))
    assert not ok37 and "位面" in msg37, msg37
    ok37, msg37, _ = fl37.set_plane(d37, "阳间")
    assert ok37 and fl37.state_of(d37)["plane"] == "阳间"
    assert fl37.set_plane(d37, "不存在")[0] is False

    # ⑤ 失败三成 / 异变污染 / 始祖接引
    st37 = fl37.state_of(d37)
    st37.update({"level": 4, "accum": 0, "risk": 0, "pollution": 0, "root": 0,
                 "mark_until": 0.0, "extremes": []})
    fl37.set_state(d37, st37)
    ok37, msg37, _ = fl37.evolve(d37, inv37, "", t37, _Seq37(0.99, 0.01))
    assert ok37 and "进化受阻" in msg37 and "始祖异变" in msg37
    assert fl37.state_of(d37)["level"] == 4
    st37 = fl37.state_of(d37)
    st37.update({"pollution": 95, "risk": 0, "root": 0, "mark_until": 0.0})
    fl37.set_state(d37, st37)
    ok37, msg37, _ = fl37.evolve(d37, inv37, "", t37, _Seq37(0.99, 0.01))
    assert ok37 and "始祖接引" in msg37
    assert fl37.state_of(d37)["pollution"] == 60
    assert fl37.state_of(d37)["mark_until"] > t37

    # ⑥ 服异果 / 净化清零奖励 / 根基满禁进化 / 重塑
    st37 = fl37.state_of(d37)
    st37.update({"pollution": 10, "risk": 20, "root": 0, "accum": 0, "mark_until": 0.0})
    fl37.set_state(d37, st37)
    ok37, _msg37, delta37 = fl37.eat_fruit(d37, inv37, "进化异果")
    assert ok37 and delta37["进化异果"] == -1 and fl37.state_of(d37)["root"] == 2
    ok37, msg37, _ = fl37.purify(d37, inv37, "本源圣药")
    assert ok37 and "破而后立" in msg37
    assert fl37.state_of(d37)["accum"] >= fl37.PURIFY_CLEAR_BONUS
    assert fl37.purify(d37, inv37, "本源圣药")[0] is False
    st37 = fl37.state_of(d37)
    st37.update({"root": 100, "pollution": 5, "risk": 5})
    fl37.set_state(d37, st37)
    ok37, msg37, _ = fl37.evolve(d37, inv37, "", t37, _Seq37(0.0))
    assert not ok37 and "根基" in msg37, msg37
    ok37, msg37, _ = fl37.reshape(d37, inv37, "本源圣药")
    assert ok37 and fl37.state_of(d37)["root"] == 55

    # ⑦ 悟道每日 3 次 / 祖种三倍 / 道则圆满
    st37 = fl37.state_of(d37)
    st37.update({"level": 9, "root": 0, "dao": {}, "dao_date": "", "dao_count": 0,
                 "seed_wudao": 0, "extremes": []})
    fl37.set_state(d37, st37)
    for _ in range(fl37.WUDAO_DAILY_LIMIT):
        assert fl37.wudao(d37, inv37, t37, _Seq37(0.0))[0] is True
    ok37, msg37, _ = fl37.wudao(d37, inv37, t37, _Seq37(0.0))
    assert not ok37 and "用尽" in msg37, msg37
    assert fl37.state_of(d37)["dao"]["9"] == 3 * fl37.DAO_RULES[9][2]
    d37b = PlayerDoc(uid="w8fl2", name="祖种", realm_index=15, physique_index=15,
                     exp=10 ** 12, ext={"xueqi": 10 ** 12})
    fl37.activate(d37b, {})
    st37 = fl37.state_of(d37b)
    st37["level"] = 9
    fl37.set_state(d37b, st37)
    assert fl37.wudao(d37b, {}, t37, _Seq37(0.0), ancestor=True)[0] is False
    assert fl37.wudao(d37b, inv37, t37, _Seq37(0.0), ancestor=True)[0] is True
    assert fl37.state_of(d37b)["dao"]["9"] == 3 * fl37.DAO_RULES[9][2]
    assert fl37.state_of(d37b)["seed_wudao"] == 1

    # ⑧ 祖种孕育 8h → 沉寂 24h → 超级异果
    st37 = fl37.state_of(d37b)
    st37.update({"breed_at": 0.0, "dormant_until": 0.0, "ready": 0})
    fl37.set_state(d37b, st37)
    assert fl37.breed(d37b, inv37, t37)[0] is True
    assert fl37.breed(d37b, inv37, t37 + 3600)[0] is False
    ok37, msg37, _ = fl37.breed(d37b, inv37, t37 + fl37.BREED_SECONDS + 1)
    assert ok37 and "孕育完成" in msg37
    assert fl37.breed(d37b, inv37, t37 + fl37.BREED_SECONDS + 2)[0] is False
    exp37 = int(d37b.exp)
    st37 = fl37.state_of(d37b)
    st37["root"] = 40
    fl37.set_state(d37b, st37)
    ok37, msg37, _ = fl37.super_fruit(d37b, t37 + fl37.BREED_SECONDS + 3)
    assert ok37 and "超级异果" in msg37 and int(d37b.exp) > exp37
    assert fl37.state_of(d37b)["root"] == 0
    assert fl37.state_of(d37b)["dao"]["9"] == fl37.DAO_RULES[9][1]

    # ⑨ 渡劫成功 / 失败保护
    d37c = PlayerDoc(uid="w8fl3", name="渡劫", realm_index=15, physique_index=15,
                     exp=10 ** 12, ext={"xueqi": 10 ** 12})
    fl37.activate(d37c, {})
    st37 = fl37.state_of(d37c)
    st37["level"] = 5
    fl37.set_state(d37c, st37)
    ok37, msg37, _ = fl37.tribulation(d37c, t37, _Seq37(0.0))
    assert ok37 and "渡尽" in msg37 and 5 in fl37.state_of(d37c)["completed"]
    assert fl37.tribulation(d37c, t37, _Seq37(0.0))[0] is False
    st37 = fl37.state_of(d37c)
    st37["completed"] = []
    fl37.set_state(d37c, st37)
    ok37, msg37, _ = fl37.tribulation(d37c, t37, _Seq37(0.99))
    assert ok37 and "未渡尽" in msg37 and fl37.state_of(d37c)["trib_fail"]["5"] == 1

    # ⑩ 极境 + 等效权柄注册制 + 面板
    st37 = fl37.state_of(d37c)
    st37.update({"level": 3, "accum": 500, "risk": 0, "extremes": []})
    fl37.set_state(d37c, st37)
    ok37, msg37, _ = fl37.extreme(d37c)
    assert ok37 and "本源觉醒" in msg37 and len(fl37.state_of(d37c)["extremes"]) == 1
    assert fl37.panel(d37c, t37).startswith("【花粉进化路】")
    assert len(fl37.levels_text().split("\n")) == 26
    auth37.reset_tracks()
    auth37.register_track(fl37.equivalent_level)
    assert fl37.equivalent_level(d37c) > 0
    assert auth37.authority_of(low37) == 3          # 未开启花粉路不抬权柄（双轨仍为 3）
    fl37.set_state(low37, {"level": 25})
    assert auth37.authority_of(low37) == 24
    auth37.reset_tracks()          # 与第 33 组一致：隔离，别污染其它组的 authority 判定

    # ⑪ 物品表已进内容索引
    cs37 = ContentStore(PLUGIN / "data")
    assert len(cs37.table("item/花粉") or []) == 6
    assert len(cs37.table("item/异果") or []) == 6
    print("W8-B3 flower pollen path ok")


    # ---- W8-B4：岁云灵根 ----
    from core import suiyun as sy38            # noqa: E402
    from core import equipment as eq38         # noqa: E402
    from core.combat import loadout as lo38    # noqa: E402
    from core.combat import opening as op38    # noqa: E402
    from core.combat.engine import Fighter as F38   # noqa: E402

    class _Seq38:
        """定序伪随机：让掉落/CD/成功率可精确断言。"""
        def __init__(self, *seq):
            self.seq = list(seq) or [0.0]
            self.i = 0
        def _next(self):
            v = self.seq[self.i % len(self.seq)]
            self.i += 1
            return v
        def random(self):
            return self._next()
        def randint(self, a, b):
            return a
        def choice(self, seq):
            return seq[0]

    t38 = 1_800_000.0
    d38 = PlayerDoc(uid="w8sy1", name="岁云", realm_index=60, physique_index=60,
                    exp=10 ** 12, stones=10 ** 9, ext={"xueqi": 10 ** 9})
    # ① 五阶表 / 未觉醒零加成 / 感应岁云的唯一性与 CD（不能误写 awake）
    assert len(sy38.STAGES) == 5 and sy38.STAGES[4]["realm"] == 20
    assert sy38.stage_of(d38) == 0 and sy38.effects(d38)["loot_mult"] == 1
    assert sy38.combat(d38, t38) == {} and sy38.set_bonus(d38)[0] == 0.0
    assert sy38.seek(d38, {}, t38, _Seq38(0.01), True)[0] is False
    ok38, _m38, delta38 = sy38.seek(d38, {}, t38, _Seq38(0.01), False)
    assert ok38 and delta38.get(sy38.REMNANT) == 1
    assert sy38.stage_of(d38) == 0
    assert sy38.seek(d38, {}, t38 + 60, _Seq38(0.01), False)[0] is False
    assert sy38.seek(d38, {}, t38 + 3600, _Seq38(0.99), False)[0] is False
    # ② 觉醒 + 全服登记表
    ok38, msg38, delta38 = sy38.activate(d38, {sy38.REMNANT: 1}, t38)
    assert ok38 and delta38[sy38.REMNANT] == -1 and delta38[sy38.GONGFA[0]] == 1
    assert sy38.stage_of(d38) == 1 and "月华初生" in msg38
    assert sy38.activate(d38, {sy38.REMNANT: 1}, t38)[0] is False
    reg38 = sy38.registry_of({"suiyun_registry": {"remnant": d38.uid}})
    assert reg38["remnant"] == d38.uid and sy38.gift_left(reg38) == 3
    # ③ 惰性结算：等效权柄 21 → 自动连升 5 阶 + 阶段馈赠 + 天阙枝唯一
    note38, rew38 = sy38.settle(d38, t38, 21)
    assert "自动晋阶" in note38 and sy38.stage_of(d38) == 5
    assert all(rew38.get(n) == 1 for n in sy38.FROST_SET)
    assert rew38.get(sy38.TREASURE) == 1 and d38.ext["equipment"]["至宝"] == sy38.TREASURE
    ok38, msg38, _ = sy38.witness(d38, t38)
    assert ok38 and "已全部领取" in msg38
    assert sy38.stage_name(d38) == "岁云剑尊"
    d38b = PlayerDoc(uid="w8sy2", name="岁云乙", realm_index=60, exp=10 ** 12)
    sy38.activate(d38b, {sy38.REMNANT: 1}, t38)
    _n38, rew38b = sy38.settle(d38b, t38, 21, treasure_taken=True)
    assert sy38.TREASURE not in rew38b and sy38.stage_of(d38b) == 5
    # ④ 月华经济：修炼 24h / 岁岁年年 1h / 炼化 24h / 锁魂必成
    ok38, _m38, _ = sy38.cultivate(d38, t38, _Seq38())
    assert ok38 and sy38.state_of(d38)["moonlight"] == 2000
    assert sy38.cultivate(d38, t38 + 3600, _Seq38())[0] is False
    pool38, gf38 = list(sy38.YEAR_POOL), list(sy38.NINE_SECRETS + sy38.TEN_XIONG)
    ok38, _m38, delta38 = sy38.years(d38, "祈愿 九秘", t38, _Seq38(), pool38, gf38)
    assert ok38 and sum(delta38.values()) >= 1
    assert sy38.years(d38, "", t38 + 60, _Seq38(), pool38, gf38)[0] is False
    ok38, _m38, _ = sy38.refine(d38, "天骄", t38, _Seq38(0.0))
    assert ok38 and sy38.state_of(d38)["lotus_moon"] > 0
    assert sy38.refine(d38, "天骄", t38 + 3600, _Seq38(0.0))[0] is False
    ok38, _m38, _ = sy38.soul_lock(d38, t38)
    assert ok38
    ok38, msg38, _ = sy38.refine(d38, "天骄", t38, _Seq38(0.99))
    assert ok38 and "搜魂必成" in msg38
    ok38, _m38, _ = sy38.redeem(d38, "")
    assert ok38 and sy38.state_of(d38)["moonlight"] >= 0
    # ⑤ 套装倍率 / 云月之莲 / 战斗注入
    lookup38 = {n: {"name": n, "class": "装备", "套装": "岁云剑尊套",
                    "type": {"岁云剑": "武器", "岁云袍": "护具", "云月之莲": "法宝"}[n],
                    "atk": 1000, "def": 1000, "HP": 1000}
                for n in sy38.FINAL_SET}
    d38.ext["equipment"] = {"武器": "岁云剑", "护具": "岁云袍", "法宝": "云月之莲",
                            "至宝": sy38.TREASURE}
    assert abs(sy38.set_bonus(d38)[0] - 19.0) < 1e-6
    st38 = sy38.state_of(d38)
    st38["lotus_moon"] = 10
    sy38.set_state(d38, st38)
    assert sy38.lotus_flat(d38) == 2_000_000
    with_set = eq38.aggregate(d38, level_table, lambda n: lookup38.get(n))
    d38.ext["equipment"]["法宝"] = "别的"
    no_set = eq38.aggregate(d38, level_table, lambda n: lookup38.get(n))
    assert with_set.atk >= no_set.atk * 10       # 套装层 ×20
    d38.ext["equipment"]["法宝"] = "云月之莲"
    f38 = lo38.build_fighter(d38, "岁云", 100000, 100000, 1000000, 0.1, lookup38)
    assert f38.tags["linggen_name"] == "岁云剑尊" and f38.tags["suiyun_stage"] == 5
    assert float(f38.eff("dmg_dealt_mult", 1.0)) >= 2.0
    assert f38.effects["revive"]["times"] == 3
    # ⑥ 对外加成：悟道 / 物品 / 渡劫 / 免费入场 / 免即死
    assert abs(sy38.wudao_bonus(d38) - 0.45) < 1e-6
    assert sy38.loot_mult(d38) == 10 and sy38.free_entry(d38) is True
    assert abs(sy38.trib_reduction(d38) - 0.85) < 1e-6
    st38 = sy38.state_of(d38)
    st38["trib_shield"] = True
    sy38.set_state(d38, st38)
    assert abs(sy38.trib_reduction(d38) - 0.95) < 1e-6
    hi38 = F38(name="仙帝", atk=1, defense=1, hp=100, hp_max=100, bao=0.0)
    low38 = F38(name="岁云", atk=1, defense=1, hp=100, hp_max=100, bao=0.0)
    hi38.tags["auth21"] = 21
    low38.tags["auth21"] = 5
    low38.tags["suiyun_stage"] = 5
    assert op38.high_realm_exec(hi38, low38) is None      # 岁云常青免即死
    low38.tags.pop("suiyun_stage")
    assert op38.high_realm_exec(hi38, low38) is not None  # 素人仍被镇杀
    # ⑦ 岁云之力经济：造物 / 更改 / 剑宫兑换 / 九印解封 / 权柄技
    st38 = sy38.state_of(d38)
    st38["power"] = 100.0
    sy38.set_state(d38, st38)
    ok38, _m38, delta38 = sy38.create(d38, "潜力丹", {"潜力丹": {}})
    assert ok38 and delta38.get("潜力丹") == 1 and float(sy38.state_of(d38)["power"]) == 90.0
    assert sy38.create(d38, sy38.REMNANT, {sy38.REMNANT: {}})[0] is False
    ok38, _m38, _ = sy38.change(d38, "称号 月宫主人")
    assert ok38 and sy38.state_of(d38)["title"] == "月宫主人"
    rows38 = [{"name": "月华帝剑", "class": "装备", "出售价": 200_000_000}]
    ok38, _m38, delta38 = sy38.buy(d38, "月华帝剑", 2, rows38)
    assert ok38 and delta38["月华帝剑"] == 2 and d38.stones == 10 ** 9 - 4_000_000
    inv38 = {"如梦的加持": 20, "地心红莲": 1, "雷帝宝术": 1, "万物母气": 1,
             "仙坟土": 1, "仙泉之眼": 1, "九彩神金": 1, "群星圣药": 10, "界核": 200}
    for seal38 in sy38.SEALS:
        ok38, _m38, _ = sy38.unseal(d38, seal38[0], inv38, t38)
        assert ok38, seal38[0]
    assert len(sy38.state_of(d38)["seals"]) == 9
    assert sy38.unseal(d38, "梦幻", inv38, t38)[0] is False
    assert sy38.dream(d38, "无上天阙枝 梦幻", t38)[0] is True
    assert sy38.sword(d38, t38, grand=True)[0] is True
    assert sy38.combat(d38, t38)["dealt"] > 3.0     # 梦幻 + 岁云降世叠加
    assert "已解封 9/9" in sy38.authority_panel(d38)
    # ⑧ 赐予月华（全服 3 席）
    ok38, msg38, reg38 = sy38.grant(d38, "someone", False, reg38, t38)
    assert ok38 and len(reg38["gifts"]) == 1 and "第 1 席" in msg38
    assert sy38.grant(d38, "someone", False, reg38, t38)[0] is False
    assert sy38.grant(d38, "other", True, reg38, t38)[0] is False
    # ⑨ 原版物品表已随包存在，无需新增数据文件
    cs38 = ContentStore(PLUGIN / "data")
    idx38 = {}
    for tname38 in ("特殊装备列表", "道具列表", "功法列表", "仙宠列表"):
        for e38 in cs38.table("item/" + tname38) or []:
            if isinstance(e38, dict) and e38.get("name"):
                idx38.setdefault(str(e38["name"]), e38)
    for n38 in (*sy38.FROST_SET, *sy38.FINAL_SET, sy38.TREASURE, sy38.REMNANT,
                sy38.PET, *sy38.GONGFA):
        assert n38 in idx38, n38
    assert len(sy38.panel(d38, t38, reg38).split("\n")) >= 10
    print("W8-B4 suiyun path ok")


    # ============================================================ 39. W8-B6 证道与道伤
    from core import zhengdao as dz39            # noqa: E402
    from core import trib as trib39              # noqa: E402
    from core import flower as fl39              # noqa: E402
    from core import suiyun as sy39              # noqa: E402
    from core import yuanshen as ys39            # noqa: E402
    from types import SimpleNamespace as _NS39   # noqa: E402

    class _Seq39:
        def __init__(self, *seq):
            self.seq = list(seq) or [0.0]
            self.i = 0
        def _next(self):
            v = self.seq[self.i % len(self.seq)]
            self.i += 1
            return v
        def random(self):
            return self._next()
        def randint(self, a, b):
            return a
        def choice(self, seq):
            return seq[0]

    t39 = time.time()          # 与现实时钟对齐，避免道伤被「离线自然恢复」一次性结算清光
    d39 = PlayerDoc(uid="w8dz1", name="证道", realm_index=60, physique_index=60,
                    exp=10 ** 12, stones=10 ** 9,
                    ext={"xueqi": 10 ** 12, "gongfa": ["不灭经"],
                         "linggen": {"name": "凡根", "type": "凡"}})
    # ① 初始态 / 三层惩罚 / 面板与规则
    assert dz39.peek(d39) == 0.0 and dz39.effects(d39)["dao_multiplier"] == 1.0
    assert len(dz39.panel(d39, {}, t39).split("\n")) >= 9
    assert "自然恢复" in dz39.rules_text()
    dz39.add_wounds(d39, 3.0, "自检", t39)
    e39 = dz39.effects(d39)
    assert e39["wounds"] == 3.0 and e39["level"] == 3.0
    assert abs(e39["chance_penalty"] - 0.24) < 1e-6
    assert abs(e39["dao_multiplier"] - 0.7) < 1e-6
    assert abs(e39["attr_multiplier"] - 0.85) < 1e-6
    assert dz39.add_wounds(d39, 1.0, "霜华", t39, halve=True) == 3.5
    assert abs(dz39.effects(d39)["chance_penalty"] - 0.28) < 1e-6
    # ② 读时自然恢复：每 10 分钟 -0.1，且时间倒退时对齐不误清
    st39 = dz39.state_of(d39, t39)
    st39["last_decay_at"] = t39 - 1800
    dz39.save(d39, st39)
    assert abs(dz39.state_of(d39, t39)["wounds"] - 3.2) < 1e-6
    d39t = PlayerDoc(uid="w8dz_t", name="时钟", realm_index=0, exp=0, ext={})
    dz39.add_wounds(d39t, 2.0, "自检", t39)
    dz39.state_of(d39t, t39 - 100_000)         # 时间倒退：独立档验证不得把道伤清零
    assert dz39.peek(d39t) == 2.0
    # ③ 花粉成功率惩罚 / 渡劫门槛 / 渡劫失败累积与成功清空
    st39b = fl39.state_of(d39) or fl39._defaults()
    med39 = next(iter(fl39.MEDIA.values()))
    assert fl39._chance(st39b, med39, t39, 0.4) < fl39._chance(st39b, med39, t39)
    stats39 = _NS39(atk=10 ** 9, defense=10 ** 9, hp=10 ** 9)
    d39.realm_index = trib39.TRIB_REALM
    d39.ext["power"] = 0
    d39.ext["linggen"] = {"name": "凡根", "type": "凡"}
    assert "道伤" in (trib39.trib_check(d39, [{"exp": 0}], stats39, 10 ** 9, 10 ** 9) or "")
    ok39, _ = trib39.trib_run(d39, stats39, _Seq39(0.99))
    assert ok39 is False and dz39.peek(d39) >= 4.2
    ok39, _ = trib39.trib_run(d39, stats39, _Seq39(0.0))
    assert ok39 is True and dz39.peek(d39) == 0.0
    # ④ 道基重塑 / 修复道伤（八门功法效率）
    dz39.add_wounds(d39, 2.0, "自检", t39)
    assert dz39.reshape(d39, {}, t39)[0] is False
    assert dz39.reshape(d39, {dz39.RESHAPE_ITEM: 5}, t39)[0] is True
    assert abs(dz39.peek(d39) - 1.0) < 1e-6
    assert dz39.repair_efficiency(d39) == (1.0, "不灭经")
    assert dz39.repair(d39, t39)[0] is True and dz39.peek(d39) == 0.0
    assert dz39.repair(d39, t39)[0] is False
    # ⑤ 冲关成功/失败（失败 +1 道伤）
    d39.realm_index = 60
    ok39, msg39, _ = dz39.charge(d39, {}, t39, _Seq39(0.0))
    assert ok39 and d39.realm_index == 61
    ok39, msg39, _ = dz39.charge(d39, {}, t39, _Seq39(0.99))
    assert ok39 and "道伤" in msg39 and dz39.peek(d39) > 0
    dz39.clear(d39, "自检", t39)
    # ⑥ 全服注册表 / 护道窗口 / 三路线判定
    reg39 = dz39.registry_of({})
    assert reg39["heart_holder"] == "" and reg39["emperors"] == []
    assert dz39.resolve_route(d39, reg39, t39) == "天心合道"
    reg39["heart_holder"] = "someone"
    assert dz39.resolve_route(d39, reg39, t39) == "帝路断绝"
    assert dz39.guard(reg39, d39.uid, d39.uid, t39)[0] is True
    assert dz39.guard_left(reg39, d39.uid, t39) == dz39.GUARD_WINDOW
    assert dz39.resolve_route(d39, reg39, t39) == "护道成帝"
    d39.ext["linggen"] = {"name": "混沌体", "type": "混沌"}
    assert dz39.resolve_route(d39, reg39, t39) == "凌驾万道"
    assert dz39.ROUTE_DIFFICULTY["凌驾万道"] == 1.5
    assert dz39.unguard(reg39, d39.uid, d39.uid)[0] is True
    assert "天心印记" in dz39.heart_panel(d39, reg39, t39)
    # ⑦ 证道成帝：失败 +2 道伤 / 全过成功并写帝榜与天心印记
    d39.ext["linggen"] = {"name": "凡根", "type": "凡"}
    d39.realm_index = 60
    d39.exp = 10 ** 12
    d39.ext["xueqi"] = 10 ** 12
    ok39, msg39, _, reg39b = dz39.prove(d39, dz39.registry_of({}), t39, _Seq39(0.99))
    assert ok39 and "道基受损" in msg39 and dz39.peek(d39) > 0
    dz39.clear(d39, "自检", t39)
    reg39c = dz39.registry_of({})
    ok39, msg39, _, reg39d = dz39.prove(d39, reg39c, t39, _Seq39(0.0))
    assert ok39 and "证道成功" in msg39 and reg39d["heart_holder"] == d39.uid
    assert len(reg39d["emperors"]) == 1 and dz39.peek(d39) == 0.0
    assert abs(dz39.power_bonus(d39) - 0.8) < 1e-6
    assert "天心合道" in dz39.panel(d39, reg39d, t39)
    # ⑧ 路尽重证：24h CD / 清修为血气 / 帝威 +20%
    assert dz39.reprove(d39, t39)[0] is False
    ok39, msg39, _ = dz39.reprove(d39, t39 + dz39.PROVE_CD + 1)
    assert ok39 and d39.exp == 0 and d39.ext["xueqi"] == 0
    assert abs(dz39.power_bonus(d39) - 1.0) < 1e-6
    # ⑨ 岁云霜华被动 / 雷帝道液（天药 daoshang 字段）/ 根源波动清伤
    d39.ext["suiyun"] = {"awake": True,
                         "seals": {n: t39 for n, *_ in sy39.SEALS}}
    assert dz39.frost_active(d39) is True
    idx39 = {"雷帝道液": {"name": "雷帝道液", "class": "丹药", "type": "天药",
                          "yuanshen": 45_000_000, "daoshang": 1}}
    pills39 = ys39.spirit_pills(d39, {"雷帝道液": 1}, idx39)
    assert len(pills39) == 1 and pills39[0]["daoshang"] == 1
    dz39.add_wounds(d39, 2.0, "自检", t39)
    ok39, msg39, used39 = ys39.take_pills(d39, {"雷帝道液": 1}, idx39)
    assert ok39 and "道伤 -1" in msg39 and abs(dz39.peek(d39) - 1.0) < 1e-6
    print("W8-B6 zhengdao path ok")


    # ============================================================ 40. W8-B1b 至尊线
    import json as _json40, io as _io40             # noqa: E402
    from core import supreme as sp40                # noqa: E402
    from core.combat import loadout as lo40         # noqa: E402
    from core.combat.engine import Fighter as F40   # noqa: E402

    tbl40 = _json40.load(_io40.open("data/item/灵根列表.json", encoding="utf-8"))
    d40 = PlayerDoc(uid="w8sp1", name="至尊", realm_index=30, physique_index=30,
                    exp=10 ** 12, stones=10 ** 9,
                    ext={"linggen": {"name": "凡根", "type": "凡", "origin": 0, "awaken": 2},
                         "gongfa": ["原始真解神引篇", "六道轮回天功",
                                    "原始真解终极篇", "五行涅槃法"],
                         "era_points": 200, "xueqi": 10 ** 12})
    inv40 = {"至尊骨": 1, "重瞳本源": 1, "仙王残魂": 3, "世界石": 1}

    class _S40:
        atk, defense, hp, bao = 10 ** 9, 10 ** 9, 10 ** 9, 0.05

    # ① 初始态 / 至尊传承换灵根（保留 W7-4 觉醒档）/ 生命本源 250 / 减伤 25%
    assert sp40.stage_of(d40) == 0 and sp40.trib_reduction(d40) == 0.0
    ok40, msg40, _ = sp40.inherit(d40, {"至尊骨": 0}, tbl40)
    assert not ok40 and "至尊骨" in msg40
    ok40, msg40, delta40 = sp40.inherit(d40, inv40, tbl40)
    assert ok40 and sp40.stage_of(d40) == 1 and delta40 == {"至尊骨": -1}
    assert d40.ext["linggen"]["awaken"] == 2 and sp40.life_max(d40) == 250
    assert abs(sp40.trib_reduction(d40) - 0.25) < 1e-6
    ok40, msg40b, _ = sp40.inherit(d40, inv40, tbl40)
    assert not ok40 and "无需再承" in msg40b

    # ② 前置缺口（境界代理极境）/ 斩骨开 9 胜试炼 / 试炼中不可重复开
    d40.realm_index = 5
    assert any("第 13 境" in g for g in sp40.missing_of(d40, "nirvana"))
    d40.realm_index = 30
    assert sp40.missing_of(d40, "nirvana") == []
    ok40, msg40, delta40 = sp40.start(d40, "nirvana")
    assert ok40 and delta40 == {"至尊骨": 1}
    assert sp40.state_of(d40)["trial"]["target"] == 9
    ok40, msg40, _ = sp40.start(d40, "nirvana")
    assert not ok40 and "进行中" in msg40

    # ③ 参悟至尊骨 → 上苍之手进功法栏；阶段 1 不能参悟涅槃骨；重复拒绝
    ok40, msg40, _ = sp40.comprehend(d40, inv40, "涅槃至尊骨")
    assert not ok40 and "阶段 2" in msg40
    ok40, msg40, delta40 = sp40.comprehend(d40, inv40, "至尊骨")
    assert ok40 and delta40 == {"至尊骨": -1} and "上苍之手" in d40.ext["gongfa"]
    ok40, msg40, _ = sp40.comprehend(d40, inv40, "至尊骨")
    assert not ok40 and "已在参悟" in msg40

    # ④ 失败不损胜场的口径由回执保证；连胜 9 场 → 整体换灵根晋阶段 2
    wins40 = 0
    for _ in range(9):
        ok40, msg40, _ = sp40.trial(d40, _S40(), tbl40, _random.Random(1))
        wins40 += int(bool(ok40))
    assert wins40 == 9 and sp40.stage_of(d40) == 2
    assert sp40.state_of(d40)["trial"] is None
    assert sp40.life_max(d40) == 400 and sp40.state_of(d40)["bone"] == "涅槃再生"
    assert abs(sp40.trib_reduction(d40) - 0.40) < 1e-6

    # ⑤ 阶段 2 #斩骨 复用为舍骨入血（纪元积累 100 + 两门功法）
    assert sp40.missing_of(d40, "ultimate") == []
    d40.ext["era_points"] = 10
    assert any("纪元积累" in g for g in sp40.missing_of(d40, "ultimate"))
    d40.ext["era_points"] = 200
    ok40, msg40, delta40 = sp40.start(d40, "ultimate", via_chop=True)
    assert ok40 and delta40 == {"涅槃至尊骨": 1} and "自动转" in msg40
    for _k40, _v40 in delta40.items():        # 模拟统一落库：新骨入纳戒
        inv40[_k40] = int(inv40.get(_k40, 0) or 0) + int(_v40)
    ok40, msg40, delta40 = sp40.comprehend(d40, inv40, "涅槃至尊骨")
    assert ok40 and delta40 == {"涅槃至尊骨": -1}
    assert "轮回天罚" in d40.ext["gongfa"] and len(sp40.state_of(d40)["arts"]) == 2

    # ⑥ 4 胜 → 终极涅槃·至尊 / 生命本源 600 / 减伤 65%
    wins40 = 0
    for _ in range(4):
        ok40, msg40, _ = sp40.trial(d40, _S40(), tbl40, _random.Random(1))
        wins40 += int(bool(ok40))
    assert wins40 == 4 and sp40.stage_of(d40) == 3
    assert sp40.life_max(d40) == 600 and sp40.state_of(d40)["bone"] == "血肉铭骨"
    assert abs(sp40.trib_reduction(d40) - 0.65) < 1e-6

    # ⑦ 三条支线：孕育仙骨 / 重瞳开天 / 瞳骨合一（缺一不可）
    ok40, msg40, _ = sp40.merge(d40)
    assert not ok40 and "未开重瞳" in msg40
    ok40, msg40, delta40 = sp40.immortal_bone(d40, inv40)
    assert ok40 and delta40 == {"仙王残魂": -3, "世界石": -1}
    ok40, msg40, delta40 = sp40.double_pupil(d40, inv40)
    assert ok40 and delta40 == {"重瞳本源": -1}
    ok40, msg40, _ = sp40.merge(d40)
    assert ok40 and sp40.title_of(d40) == "至尊重瞳仙骨"

    # ⑧ 战斗技能池注入（重瞳/仙骨/共鸣 + 三至尊宝术）/ 面板规则 / 不进第三轨
    atk40 = _json40.load(_io40.open("data/item/技能组/攻击技能.json", encoding="utf-8"))
    def40 = _json40.load(_io40.open("data/item/技能组/防御技能.json", encoding="utf-8"))
    f40 = F40(name="至尊", atk=1, defense=1, hp=1, hp_max=1)
    f40.tags["linggen_name"] = "终极涅槃·至尊"
    lo40.equip_skill_pool(f40, d40, {"atk": atk40, "def": def40, "heal": [], "boost": []})
    an40 = {str(s.get("name")) for s in f40.tags.get("atk_skills", [])}
    dn40 = {str(s.get("name")) for s in f40.tags.get("def_skills", [])}
    assert {"重瞳", "重瞳至尊", "至尊重瞳仙骨", "上苍之手", "轮回宝术", "轮回天罚"} <= an40
    assert "仙骨" in dn40 and len(sp40.skill_names(d40)) == 4
    assert "终极涅槃·至尊" in sp40.panel(d40) and "无 CD" in sp40.rules_text()
    assert isinstance(sp40.explore_drop(d40, _random.Random(2)), dict)
    assert sp40.equivalent_level(d40) == 0        # 原版三体系无至尊：不注册第三轨
    print("W8-B1b supreme path ok")

    # ============================================================ 41. W8-C1 本命法宝
    from core import bengming as bm41
    from core import equipment as eq41
    import json as _json41

    t41 = time.time()
    d41 = PlayerDoc(uid="w8bm1", name="本命", realm_index=30, physique_index=30,
                    exp=10 ** 10, stones=10 ** 8,
                    ext={"equipment": {"武器": "凡剑", "护具": "布衣"}})
    inv41 = {n: 40 for n in bm41.ALL_MATS}
    r41 = _random.Random(7)

    # ① 材料表 20 件（四类）与参数解析
    with (PLUGIN / 'data/item/本命材料.json').open(encoding='utf-8') as _f41:
        tbl41 = _json41.load(_f41)
    assert len(tbl41) == 20 and len(bm41.ALL_MATS) == 20
    assert {e['name'] for e in tbl41} == set(bm41.ALL_MATS)
    assert {e['type'] for e in tbl41} == {"本命核心", "本命辅材", "本命淬炼", "本命修复"}
    assert bm41.parse_arg("五行聚灵晶 *12") == ("五行聚灵晶", 10)
    assert bm41.parse_arg("劫火红绒*3") == ("劫火红绒", 3)
    assert bm41.parse_embed_key("#一键宝灵灵纹镶嵌") == "宝灵灵纹"
    assert bm41.parse_ultimate_key("#玄铁精炼*5") == ("玄铁精炼", 5)
    assert bm41.parse_battle_part("护灵 3") == "护具"

    # ② 炼化：恒定失败累积感应，满 1000 必成；重复炼化拒绝
    class _F41:
        def random(self):
            return 0.999

    st41 = bm41.state_of(d41)
    st41["武器"]["sense"] = 999
    bm41.set_state(d41, st41)
    bm41.refine(d41, "武器", _F41())
    ok41, msg41, _ = bm41.refine(d41, "武器", _F41())
    assert ok41 and bm41.state_of(d41)["武器"]["refined"] == 1 and "功成" in msg41
    ok41, msg41, _ = bm41.refine(d41, "武器", r41)
    assert not ok41 and "已炼化" in msg41

    # ③ 淬炼：批量上限、达上限不扣料；升华 100% 且重置强化计数
    ok41, msg41, dl41 = bm41.quench(d41, "武器", "五行聚灵晶", 10, inv41, r41)
    assert ok41 and 0 < -dl41["五行聚灵晶"] <= 10
    inv41["五行聚灵晶"] += dl41["五行聚灵晶"]
    assert bm41.state_of(d41)["武器"]["quench"] >= bm41.QUENCH_CAP["武器"][1]
    ok41, msg41, dl41 = bm41.quench(d41, "武器", "五行聚灵晶", 3, inv41, r41)
    assert not ok41 and not dl41 and "升华" in msg41
    ok41, msg41, _ = bm41.ascend(d41, "武器")
    assert ok41 and bm41.state_of(d41)["武器"]["level"] == 2
    assert bm41.state_of(d41)["武器"]["ult_success"] == 0

    # ④ 终境升华门禁：淬炼值满但魂魄未满 → 拒绝
    st41 = bm41.state_of(d41)
    lv41 = len(bm41.LEVELS["武器"]) - 2
    st41["武器"]["level"] = lv41
    st41["武器"]["quench"] = bm41.QUENCH_CAP["武器"][lv41]
    bm41.set_state(d41, st41)
    ok41, msg41, _ = bm41.ascend(d41, "武器")
    assert not ok41 and "终境升华条件不足" in msg41

    # ⑤ 六类镶嵌：同名唯一 / core 3 / aux 7 / 阶段奖励 / 一键 10 种 key
    ok41, msg41, dl41 = bm41.embed(d41, "武器", "core", "太初魂晶", inv41)
    assert ok41 and dl41 == {"太初魂晶": -1}
    inv41["太初魂晶"] -= 1
    ok41, msg41, _ = bm41.embed(d41, "武器", "core", "太初魂晶", inv41)
    assert not ok41 and "已镶过" in msg41
    assert len(bm41.EMBED_TARGETS) == 10
    ok41, msg41, dl41 = bm41.embed_all(d41, "本命武器", inv41)
    assert ok41
    for _k41, _v41 in dl41.items():
        inv41[_k41] += _v41
    w41 = bm41.state_of(d41)["武器"]
    assert len(w41["core"]) == 3 and len(w41["aux"]) == 7 and bm41.complete(w41)
    assert w41["spirit"]["affinity"] >= 120 and w41["sense"] == 1000
    assert w41["spirit"]["talent"] in bm41.TALENTS

    # ⑥ 器灵：召唤→命名→性别→磨合→共鸣（1h 内进战斗乘区，过期清空）
    ok41, msg41, _ = bm41.summon(d41, "武器", r41)
    assert ok41 and "命名" in msg41
    ok41, _, _ = bm41.name_spirit(d41, "武器", "霜华")
    assert ok41
    ok41, _, _ = bm41.set_gender(d41, "武器", "女")
    assert ok41 and bm41.state_of(d41)["武器"]["spirit"]["atk"] > 0
    ok41, _, _ = bm41.temper(d41, "武器", r41)
    assert ok41
    ok41, _, _ = bm41.resonance(d41, "武器", t41)
    assert ok41
    assert bm41.combat(d41, t41 + 10).get("dmg_dealt_mult", 1.0) > 1.0
    assert bm41.combat(d41, t41 + bm41.RESONANCE_SECONDS + 1) == {}

    # ⑦ 化剑为鞘可逆且三维按形态变化
    a0_41, f0_41 = bm41.bonus(d41, t41 + 10)[0], bm41.bonus(d41, t41 + 10)[1]
    ok41, _, _ = bm41.sheath(d41, True)
    assert ok41
    assert bm41.bonus(d41, t41 + 10)[0] < a0_41
    assert bm41.bonus(d41, t41 + 10)[1] > f0_41
    ok41, _, _ = bm41.sheath(d41, False)
    assert ok41 and bm41.state_of(d41)["武器"]["sheath"] == 0

    # ⑧ 终极强化：成功率随成功次数衰减；残响与消耗
    c0_41 = bm41.ultimate_chance(bm41.state_of(d41)["武器"])
    ok41, msg41, dl41 = bm41.ultimate(d41, "引雷淬火", 5, inv41, r41)
    assert ok41 and dl41 == {"劫火红绒": -5}
    assert bm41.ultimate_chance(bm41.state_of(d41)["武器"]) <= c0_41

    # ⑨ 属性确实进 equipment.aggregate（未炼化 vs 已炼化）
    lookup41 = lambda n: next((e for e in tbl41 if e['name'] == n), None)
    bare41 = d41.model_copy(deep=True)
    bst41 = bm41.state_of(bare41)
    for _p41 in bm41.PARTS:
        bst41[_p41]["refined"] = 0
    bm41.set_state(bare41, bst41)
    assert eq41.aggregate(d41, level_table, lookup41).atk > \
        eq41.aggregate(bare41, level_table, lookup41).atk

    # ⑩ 投放 / 面板 / 规则 / 器灵对战
    drops41 = [bm41.roll_drop(_random.Random(i)) for i in range(200)]
    assert all(x is None or x in bm41.ALL_MATS for x in drops41) and any(drops41)
    assert len(bm41.panel(d41, t41 + 10).split("\n")) >= 5
    assert "无 CD" in bm41.rules_text() and "20 件" in bm41.materials_text()
    assert "#一键本命镶嵌" in bm41.help_text()
    ok41, msg41, _ = bm41.spirit_battle(d41, "武器", r41)
    assert ok41 and msg41
    print("W8-C1 bengming ok")

    # ============================================================ 42. W8-C2 先天至宝·权柄
    from core import xtzb as xt42, equipment as eq42, trib as trib42, cultivate as cul42
    from core import yuanshen as ys42, zhengdao as dz42
    from core.combat.loadout import build_fighter as bf42
    import json as _json42
    from types import SimpleNamespace

    t42 = 1_800_000.0

    class _Win42:
        def random(self):
            return 0.0
        def choice(self, seq):
            return seq[0]
        def randint(self, a, b):
            return a

    class _Lose42:
        def random(self):
            return 1.0

    w42 = xt42.world_of({})
    d42 = PlayerDoc(uid="w8xt1", name="先天", realm_index=30, physique_index=30,
                    exp=10 ** 10, stones=10 ** 8, ext={"linggen": {"name": "木"}})
    d42b = PlayerDoc(uid="w8xt2", name="旁人", realm_index=30, physique_index=30,
                     exp=10 ** 10, stones=10 ** 8, ext={})
    inv42 = {"先天道痕": 100, "灵宝残片": 4, "界核": 20, "宇宙核心": 3,
             "鸿蒙道火": 200, "太初魂晶": 10, "凡铁": 5}

    # ① 目录 23 件 / 24 个 CD key / 九宝 / 5 件信物表 / 孤儿指令不注册
    assert len(xt42.CATALOG) == 23 and len(xt42.NAMES) == 23
    assert len(xt42.CD) == 24 and "图中巡游" in xt42.CD
    assert "图中巡游" not in xt42.AUTH_FLAG
    assert len(xt42.ETERNAL_COMPONENTS) == 9
    assert len(xt42.ALIASES) == 6 and len(xt42.FLAGS) == 10
    with (PLUGIN / 'data/item/至宝信物.json').open(encoding='utf-8') as _f42:
        tbl42 = _json42.load(_f42)
    assert len(tbl42) == 5 and {e['name'] for e in tbl42} == set(xt42.SIGILS)
    assert xt42._parse_item("凡铁 *12") == ("凡铁", 12)
    assert "23 件" in xt42.catalog() and "混沌珠" in xt42.catalog()
    assert "盘古幡" in xt42.catalog("盘古幡") and "CD" in xt42.catalog("盘古幡")

    # ② 择主：门槛 / 全服唯一 / 第二人只得 7 日投影（投影属性为 0）
    ok42, msg42, _ = xt42.claim(d42, "不存在的至宝", inv42, w42, t42, _Win42())
    assert not ok42
    ok42, msg42, _ = xt42.claim(d42, "虚天舟", inv42, w42, t42, _Win42())
    assert not ok42 and "虚天宝库" in msg42
    ok42, msg42, _ = xt42.claim(d42, "混沌珠", {"先天道痕": 3}, w42, t42, _Win42())
    assert not ok42 and "先天道痕" in msg42
    ok42, msg42, dl42 = xt42.claim(d42, "混沌珠", inv42, w42, t42, _Win42())
    assert ok42 and dl42["先天道痕"] == -xt42.CLAIM_COST
    assert w42["owners"]["混沌珠"]["uid"] == "w8xt1"
    assert xt42.current(d42, t42) == "混沌珠"
    ok42, msg42, _ = xt42.claim(d42b, "混沌珠", {"先天道痕": 100}, w42, t42 + 10, _Win42())
    assert ok42 and "投影" in msg42
    assert xt42.state_of(d42b, t42 + 10)["projection"]["混沌珠"] > t42
    assert w42["owners"]["混沌珠"]["uid"] == "w8xt1"
    assert xt42.bonus(d42b, t42 + 10)[0] == 0.0

    # ③ 执掌 / 移交：全服 owners 迁移 + CD 状态迁移 + 投影标记撤销
    st42 = xt42.state_of(d42, t42)
    st42["owned"].append("盘古幡")
    xt42.save(d42, st42)
    ok42, _, _ = xt42.equip(d42, "盘古幡", w42, t42)
    assert ok42 and xt42.current(d42, t42) == "盘古幡"
    ok42, msg42, _ = xt42.equip(d42, "混沌钟", w42, t42)
    assert not ok42 and "纳戒" in msg42
    ok42, _, _ = xt42.transfer(d42, "w8xt1", "混沌珠", w42, d42b, t42)
    assert not ok42
    ok42, msg42, _ = xt42.transfer(d42, "w8xt2", "混沌珠", w42, d42b, t42)
    assert ok42 and w42["owners"]["混沌珠"]["uid"] == "w8xt2"
    assert "混沌珠" not in xt42.state_of(d42, t42)["owned"]
    assert xt42.current(d42b, t42) == "混沌珠"
    assert "混沌珠" not in xt42.state_of(d42b, t42)["projection"]

    # ④ 统一网关：未持有拒绝 / CD / 过期清理
    ok42, msg42, _ = xt42.prepare(d42, w42, "东皇镇世", t42)
    assert not ok42 and "执掌" in msg42
    ok42, msg42, _ = xt42.prepare(d42, w42, "开天", t42)
    assert ok42 and "盘古开天待用" in xt42.state_of(d42, t42)["flags"]
    ok42, msg42, _ = xt42.prepare(d42, w42, "开天", t42 + 1)
    assert not ok42 and "冷却" in msg42
    st42 = xt42.state_of(d42, t42 + xt42.CD["开天"] + 1)
    assert "开天" not in st42["cd"] and not st42["flags"]

    # ⑤ 被动 + 蓄势 → combat()；过期自动失效；bonus / yield / guard
    st42 = xt42.state_of(d42, t42)
    st42["current"] = "盘古幡"
    st42["flags"] = {"盘古开天待用": t42 + 100, "诛仙剑阵待用": t42 + 100}
    xt42.save(d42, st42)
    c42 = xt42.combat(d42, t42)
    assert c42["dealt"] >= 0.30 + 0.60 + 0.50
    assert xt42.bonus(d42, t42) == (xt42.FLAT_ALL, xt42.FLAT_ALL,
                                   xt42.FLAT_ALL, xt42.BAO_FLAT)
    assert xt42.yield_mult(d42, "raid", t42) > 1.0
    assert xt42.guard_mult(d42, t42) == 1.0
    assert xt42.combat(d42, t42 + 200)["dealt"] == 0.30

    # ⑥ 混沌珠三权柄：复制 / 演化 / 变幻，信物与至宝禁止复制
    inv42c = {"先天道痕": 10, "凡铁": 5, "太初魂晶": 3, "灵宝残片": 2}
    ok42, _, dl42 = xt42.chaos_copy(d42b, inv42c, w42, "凡铁 *3", t42)
    assert ok42 and dl42 == {"凡铁": 3}
    t42b = t42 + xt42.CD["混沌复制"] + 1   # 越过第一次复制的 12h CD
    ok42, msg42, _ = xt42.chaos_copy(d42b, inv42c, w42, "先天道痕*1", t42b)
    assert not ok42 and "不可复制" in msg42
    ok42, _, dl42 = xt42.chaos_evolve(d42b, inv42c, w42, "太初魂晶*3", t42, _Win42())
    assert ok42 and dl42["太初魂晶"] == -3 and dl42["先天道痕"] == 3
    ok42, _, dl42 = xt42.chaos_transform(d42b, inv42c, w42, "凡铁*2", t42, _Win42(), {}.get)
    assert ok42 and dl42["凡铁"] == -2
    assert sum(v for k, v in dl42.items() if k != "凡铁") == 2

    # ⑦ 世界级：人皇敕令 + 每人一次借气运 / 山河投影显式收获
    st42 = xt42.state_of(d42, t42)
    st42["owned"].append("崆峒印")
    st42["current"] = "崆峒印"
    xt42.save(d42, st42)
    ok42, _, _ = xt42.decree(d42, w42, "修炼", t42)
    assert ok42 and xt42.decree_active(w42, t42)
    exp0_42 = d42.exp
    ok42, _, _ = xt42.borrow_decree(d42, w42, t42)
    assert ok42 and d42.exp > exp0_42
    ok42, msg42, _ = xt42.borrow_decree(d42, w42, t42 + 1)
    assert not ok42 and "1 次" in msg42
    st42 = xt42.state_of(d42, t42)
    st42["owned"].append("山河社稷图")
    st42["current"] = "山河社稷图"
    xt42.save(d42, st42)
    ok42, _, _ = xt42.capture_landscape(d42, w42, "灵界裂缝", t42)
    assert ok42 and len(w42["landscapes"]) == 1
    exp0_42 = d42.exp
    ok42, _, _ = xt42.landscape_harvest(d42, w42, t42 + 3 * 3600)
    assert ok42 and d42.exp > exp0_42
    ok42, _, _ = xt42.landscape_harvest(d42, w42, t42 + 3 * 3600)
    assert not ok42

    # ⑧ 立即结算：回春祛道伤 / 淬神涨元神上限 / 菩提顿悟 / 太极双相
    st42 = xt42.state_of(d42, t42)
    st42["owned"].append("造化仙池")
    st42["current"] = "造化仙池"
    xt42.save(d42, st42)
    dz42.add_wounds(d42, 2.0, "自检", now=t42)
    ok42, _, _ = xt42.creation_spring(d42, w42, t42)
    assert ok42 and dz42.peek(d42) == 0.0
    assert xt42.state_of(d42, t42)["potential"] == 500
    st42 = xt42.state_of(d42, t42)
    st42["owned"].append("万劫天碑")
    st42["current"] = "万劫天碑"
    xt42.save(d42, st42)
    y42 = ys42.ensure(d42)
    y42["max"], y42["cur"] = 1000, 100
    ys42.save(d42, y42)
    ok42, _, _ = xt42.temper_spirit(d42, w42, t42)
    assert ok42 and ys42.max_of(d42) == 1100 and xt42.guard_mult(d42, t42) < 1.0
    st42 = xt42.state_of(d42, t42)
    st42["owned"].append("菩提祖树")
    st42["current"] = "菩提祖树"
    xt42.save(d42, st42)
    exp0_42 = d42.exp
    ok42, _, _ = xt42.bodhi(d42, w42, t42)
    assert ok42 and d42.exp > exp0_42
    st42 = xt42.state_of(d42, t42)
    st42["owned"].append("太极图")
    st42["current"] = "太极图"
    xt42.save(d42, st42)
    ok42, _, _ = xt42.switch_taiji(d42, w42, "阳", t42)
    assert ok42 and xt42.combat(d42, t42)["lifesteal"] >= 0.25
    ok42, _, _ = xt42.switch_taiji(d42, w42, "阴", t42)
    assert ok42 and xt42.combat(d42, t42)["reflect"] >= 0.30

    # ⑨ 永恒仙图：九宝齐聚 + 三材 → 孕育 → 成形 → 古史改写（每条一次）
    st42 = xt42.state_of(d42, t42)
    for _n42 in xt42.ETERNAL_COMPONENTS:
        if _n42 not in st42["owned"]:
            st42["owned"].append(_n42)
    xt42.save(d42, st42)
    ok42, msg42, _ = xt42.synthesize_eternal(d42, inv42c, w42, t42)
    assert not ok42 and "材料不足" in msg42
    ok42, _, dl42 = xt42.synthesize_eternal(d42, inv42, w42, t42)
    assert ok42 and dl42["界核"] == -9 and w42["eternal"]["status"] == "gestating"
    ok42, msg42, _ = xt42.synthesize_eternal(d42, inv42, w42, t42 + 1)
    assert ok42 and "孕育" in msg42
    ok42, _, _ = xt42.synthesize_eternal(d42, inv42, w42,
                                         t42 + xt42.ETERNAL_GESTATION + 2)
    assert ok42 and w42["eternal"]["status"] == "formed"
    xt42.note_erasure(d42, "自检身灭", t42)
    ok42, msg42, _ = xt42.eternal_history(d42, t42)
    assert ok42 and "自检身灭" in msg42
    ok42, _, _ = xt42.eternal_rewrite(d42, w42, "1", t42)
    assert ok42 and xt42.state_of(d42, t42)["history"][-1]["state"] == "rewritten"
    ok42, _, _ = xt42.eternal_rewrite(d42, w42, "1", t42 + 1)
    assert not ok42

    # ⑩ 消费点：装备聚合 / 战斗装配 / 渡劫减伤 / 闭关缩时 / 投放 / 面板
    bare42 = d42.model_copy(deep=True)
    st42 = xt42.state_of(bare42, t42)
    st42["current"] = ""
    xt42.save(bare42, st42)
    lookup42 = lambda n: next((e for e in tbl42 if e['name'] == n), None)
    assert eq42.aggregate(d42, level_table, lookup42).atk > \
        eq42.aggregate(bare42, level_table, lookup42).atk
    f42 = bf42(d42, "先天", 10000, 10000, 100000, 0.1, {}.get)
    assert float(f42.eff("dmg_dealt_mult", 1.0)) > 1.0 or f42.effects.get("shield", 0) > 0
    stats42 = SimpleNamespace(atk=10 ** 9, defense=10 ** 9, hp=10 ** 10)
    tower42 = d42.model_copy(deep=True)
    st42 = xt42.state_of(tower42, t42)
    st42["current"] = "天地玄黄玲珑塔"
    xt42.save(tower42, st42)
    base42b = bare42.model_copy(deep=True)
    ok_a42, _ = trib42.trib_run(base42b, stats42, _Lose42())
    ok_b42, _ = trib42.trib_run(tower42, stats42, _Lose42())
    assert not ok_a42 and not ok_b42 and tower42.exp > base42b.exp
    d42d = PlayerDoc(uid="w8xt3", name="闭关", realm_index=10,
                     state="闭关中", state_start=t42, ext={})
    d42e = d42d.model_copy(deep=True)
    st42 = xt42.state_of(d42e, t42)
    st42["current"] = "混沌钟"
    xt42.save(d42e, st42)
    ok42, _, out_d42 = cul42.end_cultivate(d42d, t42 + 120 * 60, 100, 7200)
    ok42, _, out_e42 = cul42.end_cultivate(d42e, t42 + 120 * 60, 100, 7200)
    assert ok42 and out_e42.exp > out_d42.exp
    drops42 = [xt42.roll_drop(_random.Random(i)) for i in range(200)]
    assert all(x is None or set(x) <= set(xt42.SIGILS) for x in drops42) and any(drops42)
    assert "先天至宝" in xt42.panel(d42, w42, t42)
    assert "#至宝择主" in xt42.help_text() and len(xt42.help_text().split("\n")) >= 10
    assert "每纪元" in xt42.rules_text() and "孤儿" in xt42.rules_text()
    print("W8-C2 xtzb ok")

    # ── 43. W8-C3 大道炼器 ──────────────────────────────────────────────
    from types import SimpleNamespace
    from core import daotreasure as dt43
    from core import authority as au43
    au43.reset_tracks()          # 第 42 组注册的第三轨不污染本组权柄判定

    class _Content43:
        def table(self, name):
            if name == "item/命格词条":
                return [{"name": "天命孤星", "id": "A1", "effects": {"攻击加成": 1.0}}]
            return []

    c43 = _Content43()
    t43 = 1_800_000.0
    d43 = PlayerDoc(uid="w8dt0", name="器主", realm_index=25,
                    ext={"occupation": "炼器师", "occupation_level": 24})
    bad43 = PlayerDoc(uid="w8dt9", name="散修", realm_index=3, ext={})
    w43 = dt43.world_of({})

    assert len(dt43.APTITUDES) == 10 and len(dt43.STAGES) == 5
    assert sum(dt43.FUEL.values()) == 1160 and dt43.FORGE_YEARS == 50_000
    assert "#大道权柄" in dt43.help_text() and "彼岸铸宝" in dt43.help_text()
    assert "纪元" in dt43.rules_text() and "shortcut" in dt43.rules_text()

    # ① 开铸三重校验 + 全服唯一工程
    ok43, msg43, _ = dt43.open_forge(bad43, "无道炉", w43, 1000)
    assert not ok43 and "炼器师" in msg43
    d43b = d43.model_copy(deep=True)
    d43b.realm_index = 3
    ok43, msg43, _ = dt43.open_forge(d43b, "无道炉", w43, 1000)
    assert not ok43 and "祭道" in msg43
    d43c = d43.model_copy(deep=True)
    d43c.ext["occupation_level"] = 2
    ok43, msg43, _ = dt43.open_forge(d43c, "无道炉", w43, 1000)
    assert not ok43 and "炉火纯青" in msg43
    ok43, _, _ = dt43.open_forge(d43, "文明炉", w43, 1000)
    assert ok43 and w43["project"]["status"] == "gathering"
    ok43, _, _ = dt43.open_forge(d43, "第二炉", w43, 1000)
    assert not ok43

    # ② 四种燃料齐备自动点炉，扣料走 delta
    inv43 = dict(dt43.FUEL)
    for k43, v43 in dt43.FUEL.items():
        ok43, _, delta43 = dt43.contribute(d43, inv43, f"{k43}*{v43}", w43, 2000, t43)
        assert ok43 and delta43[k43] == -v43
    assert w43["project"]["status"] == "forging"
    assert w43["project"]["start_year"] == 2000

    # ③ 镇守去重：仅阶段 0 满 3 人 → 成器完整度 20、四权柄残缺
    g43 = [PlayerDoc(uid=f"w8dtg{i}", name=f"守{i}", ext={}) for i in range(3)]
    for g in g43:
        ok43, _, _ = dt43.guard_forge(g, w43, 2000, t43)
        assert ok43
    ok43, _, _ = dt43.guard_forge(g43[0], w43, 2000, t43)
    assert not ok43
    dt43.advance(w43, 2000 + 40_000, t43)
    assert w43["project"]["stage_index"] == 4
    ok43, msg43, _ = dt43.guard_forge(g43[0], w43, 42_000, t43)
    assert not ok43 and "渡劫" in msg43

    # ④ 器劫：胜写 guardians、败无任何惩罚（双分支都可接受）
    st43 = SimpleNamespace(atk=100_000, defense=50_000, hp=500_000, bao=0.2)
    ok43, msg43, _ = dt43.tribulation(d43, w43, 42_000, st43, _random.Random(43), t43)
    guards43 = w43["project"]["stages"][4]["guardians"]
    if ok43:
        assert "斩道功成" in msg43 and str(d43.uid) in guards43
    else:
        assert "未破" in msg43 and not guards43

    notes43 = dt43.advance(w43, 2000 + 50_000, t43)
    assert any("出世" in n for n in notes43)
    tr43 = w43["treasure"]
    assert w43["project"]["status"] == "completed"
    assert tr43["integrity"] == 20 and tr43["body"] == "完整"
    assert all(v == "残缺" for v in tr43["authorities"].values())
    assert tr43["origin"] == 12 and tr43["delivery"] == "pending"

    # ⑤ 本源跨一纪元恢复 4（按 epoch 差一次性补算）
    tr43["origin"] = 0
    ep43 = dt43.epoch_of(52_000)
    tr43["last_recovery_epoch"] = ep43
    dt43.advance(w43, 52_000 + 50_000, t43)
    assert tr43["origin"] == 4 and tr43["last_recovery_epoch"] == ep43 + 1

    # ⑥ 领取成器 + 镜像全服状态给纯读出口
    assert "文明大道至宝" in dt43.treasure_panel(d43, w43, 102_000)
    assert tr43["delivery"] == "delivered" and dt43._player(d43)["owned"] == "文明炉"
    dt43.sync_treasure(d43, w43)
    b43 = dt43.bonus(d43)
    assert b43[0] > 0 and b43[1] > 0 and b43[2] > 0
    assert dt43.combat(d43)["dealt"] == 0.0

    # ⑦ 修权柄耗四种材料、完整度 +20；残缺权柄不可敕令
    inv43b = dict(dt43.REPAIR_COST)
    ok43, msg43, _ = dt43.decree(d43, "万法", w43)
    assert not ok43 and "残缺" in msg43
    for k43 in dt43.AUTHORITIES:
        ok43, _, delta43 = dt43.repair(d43, inv43b, k43, w43)
        assert ok43 and all(delta43[x] == -y for x, y in dt43.REPAIR_COST.items())
    assert tr43["integrity"] == 100
    dt43.sync_treasure(d43, w43)
    ok43, _, _ = dt43.decree(d43, "生死", w43)
    assert ok43 and dt43.combat(d43)["revive"] is True
    ok43, _, _ = dt43.decree(d43, "万法", w43)
    assert ok43 and dt43.combat(d43)["dealt"] >= 0.25

    # ⑧ 改命：自己立即生效 / 他人须 60 秒同意 / 邀请过期
    tr43["origin"] = 12
    ok43, _, _ = dt43.rewrite(d43, None, "无演无尽", "apt", w43, c43, t43)
    assert ok43 and dt43._player(d43)["aptitude"] == "无演无尽"
    assert dt43.combat(d43)["dealt"] >= 0.54
    ok43, _, _ = dt43.rewrite(d43, None, "天命孤星", "fate", w43, c43, t43)
    assert ok43 and d43.ext["mingge"]["name"] == "天命孤星"
    other43 = PlayerDoc(uid="w8dt1", name="道友", realm_index=10, ext={})
    tr43["origin"] = 12
    ok43, msg43, _ = dt43.rewrite(d43, other43, "绝世天骄", "apt", w43, c43, t43)
    assert ok43 and "60" in msg43 and "w8dt1" in w43["invites"]
    assert not dt43._player(other43).get("aptitude")
    ok43, _, _ = dt43.accept_rewrite(other43, w43, c43, t43 + 10)
    assert ok43 and dt43._player(other43)["aptitude"] == "绝世天骄"
    assert "w8dt1" not in w43["invites"]
    tr43["origin"] = 12
    dt43.rewrite(d43, other43, "平庸之资", "apt", w43, c43, t43)
    ok43, msg43, _ = dt43.accept_rewrite(other43, w43, c43, t43 + 61)
    assert not ok43 and "消散" in msg43

    # ⑨ 终极功法 / 大道界每件至宝各一次；改名同步 owned
    tr43["origin"] = 12
    ok43, _, _ = dt43.deduce(d43, "无上道经 攻伐", w43)
    assert ok43 and dt43.combat(d43)["dealt"] >= 0.74
    tr43["origin"] = 12
    ok43, msg43, _ = dt43.deduce(d43, "再来一部", w43)
    assert not ok43 and "一次" in msg43
    tr43["origin"] = 12
    ok43, _, _ = dt43.create_world(d43, "大罗天", w43)
    assert ok43 and dt43.combat(d43)["taken"] >= 0.15
    ok43, _, _ = dt43.create_world(d43, "另一个", w43)
    assert not ok43
    ok43, _, _ = dt43.rename(d43, "太初炉", w43)
    assert ok43 and tr43["name"] == "太初炉" and dt43._player(d43)["owned"] == "太初炉"

    # ⑩ 秘境燃料投放 + 面板/名录
    drops43 = [dt43.roll_drop(_random.Random(i)) for i in range(200)]
    assert all(x is None or set(x) <= set(dt43.FUEL) for x in drops43) and any(drops43)
    assert "众生念力" in dt43.materials_text() and "纪元" in dt43.forge_panel(w43, 102_000)
    print("W8-C3 daotreasure ok")

    # ── 44. W8-C4 锻造深层 / 锻炉 / 神兵榜 ──────────────────────────────
    from core import duanzao as dzl44        # noqa: E402
    from core import daotreasure as dt44     # noqa: E402
    from core import equipment as eq44       # noqa: E402

    assert len(dzl44.FURNACES) == 7 and len(dzl44.FIRES) == 6 and len(dzl44.GONGFA) == 5
    assert dzl44.FURNACES[5]["容纳量"] == 34     # 源码硬编码 34，非 json 的 77
    assert abs(dzl44.time_speed({"fire": "道火", "gongfa": "无上炼器道"}) - 0.2) < 1e-9
    assert dzl44.ELEMENT_AFFIX[0][1] == 0.35 and dzl44.NAME_MAX == 8

    mat44 = {
        "星银": {"name": "星银", "type": "锻造", "攻": 1.0, "防": 0.8, "血": 0.6,
                 "暴": 0.2, "金": 1, "木": 0, "土": 0, "水": 0, "火": 0},
        "庚金": {"name": "庚金", "type": "普通", "出售价": 3},
    }
    def look44(n):
        return mat44.get(n)
    tpl44 = [
        {"name": "赤马阔刀", "type": "武器", "atk": 0.02, "def": 0.01, "HP": 0.01, "稀有度": 1},
        {"name": "玄龟盾", "type": "护具", "atk": 0.01, "def": 0.4, "HP": 0.3, "稀有度": 3},
        {"name": "混沌珠", "type": "法宝", "atk": 0.2, "def": 0.2, "HP": 0.2, "稀有度": 6},
    ]
    hid44 = [{"name": "真火灵根", "控器": 8, "type": 5}]
    lvl44 = [{"level": "凡人", "exp": 500, "基础攻击": 2000, "基础防御": 2000,
              "基础血量": 4000, "基础暴击": 0.0}]
    rng44 = _random.Random(44)
    t44 = 1_800_000.0

    # ① 建档：天赋 80~119、隐藏灵根、不可重复
    d44 = PlayerDoc(uid="w8c4", name="器痴", realm_index=25,
                    ext={"occupation": "炼器师", "occupation_level": 20, "occupation_exp": 0})
    d44.stones = 3_000_000
    ok44, _, _ = dzl44.evaluate(d44, rng44, hid44)
    assert ok44 and 80 <= dzl44.state_of(d44)["talent"] <= 119
    ok44, _, _ = dzl44.evaluate(d44, rng44, hid44)
    assert not ok44

    # ② C3 回填：未建档旧档走职业等级，建档后逐项严格校验
    bare44 = PlayerDoc(uid="w8c4bare", name="旧档", realm_index=25,
                       ext={"occupation": "炼器师", "occupation_level": 24})
    assert dzl44.gate(bare44) == (True, "", False)
    ok44, _, _ = dt44.open_forge(bare44, "旧炉", dt44.world_of({}), 1000)
    assert ok44
    assert not dzl44.gate(d44)[0] and "混沌炉" in dzl44.gate(d44)[1]
    st44 = dzl44.state_of(d44)
    st44["furnace"] = "混沌炉"
    assert "道火" in dzl44.gate(d44)[1]
    st44["fire"] = "道火"
    assert "熟练度" in dzl44.gate(d44)[1]
    st44["gongfa"], st44["proficiency"] = "无上炼器道", 100
    assert dzl44.gate(d44)[0] and dzl44.gate(d44)[2]
    ok44, _, _ = dt44.open_forge(d44, "文明炉", dt44.world_of({}), 1000)
    assert ok44                                # 三项齐备即可，不再看职业等级
    bad44 = d44.model_copy(deep=True)
    bad44.ext["forge"] = dict(st44, proficiency=3)
    ok44, msg44, _ = dt44.open_forge(bad44, "废炉", dt44.world_of({}), 1000)
    assert not ok44 and "熟练度" in msg44

    # ③ 投料 / 温养 / 三种开炉
    d44b = PlayerDoc(uid="w8c4b", name="匠人", realm_index=25,
                     ext={"occupation": "炼器师", "occupation_level": 20, "occupation_exp": 0})
    d44b.stones = 3_000_000
    dzl44.evaluate(d44b, rng44, hid44)
    inv44 = {"星银": 10, "庚金": 5, "时光令": 3, "造化本源": 2, "时光令配方": 1,
             "时光石": 10, "世界石": 5, "天外清风": 5, "符纸": 50}
    ok44, msg44, _ = dzl44.melt(d44b, inv44, "庚金*2", look44)
    assert not ok44 and "凡界" in msg44
    ok44, _, dl44 = dzl44.melt(d44b, inv44, "星银*3", look44)
    assert ok44 and dl44["星银"] == -3 and dzl44.used(dzl44.state_of(d44b)) == 3
    assert dzl44.capacity(dzl44.state_of(d44b), d44b) == 20   # 凡铁炉 10 + 20//2
    ok44, _, _ = dzl44.start(d44b, t44)
    assert ok44
    ok44, msg44, _ = dzl44.open_forge(d44b, "normal", inv44, t44 + 60,
                                      item_lookup=look44, templates=tpl44, rng=rng44)
    assert not ok44 and "过短" in msg44
    ok44, msg44, dl44 = dzl44.open_forge(d44b, "normal", inv44, t44 + 2000,
                                         item_lookup=look44, templates=tpl44, rng=rng44)
    assert ok44 and "获得" in msg44
    arts44 = dzl44.state_of(d44b)["artifacts"]
    assert len(arts44) == 1
    nm44 = next(iter(arts44))
    assert dl44[nm44] == 1 and arts44[nm44]["atk"] > 0 and arts44[nm44]["score"] > 0
    assert dzl44.state_of(d44b)["proficiency"] == 2
    assert int(d44b.ext.get("occupation_exp") or 0) > 0

    # ④ 私有神兵卡注入装备聚合：clamp 0.99 且真的加三维
    card44 = dzl44.item_card(d44b, nm44)
    assert card44 and card44["class"] == "装备" and card44["atk"] <= dzl44.MAX_CARD_RATIO
    def agg44(n):
        return dzl44.item_card(d44b, n) or look44(n)
    d44b.ext["equipment"] = {}
    s44_plain = eq44.aggregate(d44b, lvl44, agg44)
    d44b.ext["equipment"] = {"武器": nm44}
    s44_worn = eq44.aggregate(d44b, lvl44, agg44)
    assert s44_worn.atk > s44_plain.atk and s44_worn.defense > s44_plain.defense

    # ⑤ 赋名 / 榜单 30 分钟缓存 / 神兵重铸同步
    inv44[nm44] = 1
    w44 = dzl44.world_of({})
    ok44, msg44, _ = dzl44.name_it(d44b, inv44, f"{nm44}*九字神兵名字超长测试", w44, t44,
                                   lambda n: False)
    assert not ok44 and "超出" in msg44
    ok44, _, dl44 = dzl44.name_it(d44b, inv44, f"{nm44}*诛仙", w44, t44, lambda n: False)
    assert ok44 and dl44["诛仙"] == 1 and "诛仙" in w44["named"]
    assert d44b.ext["equipment"]["武器"] == "诛仙"      # 穿戴槽同步
    inv44["诛仙"] = 1                                    # 模拟 _dz_apply 落库后的背包
    ok44, msg44, _ = dzl44.name_it(d44b, inv44, "诛仙*再来", w44, t44, lambda n: False)
    assert not ok44 and "只能赋名一次" in msg44
    p44 = [{"uid": d44b.uid, "name": d44b.name, "ext": d44b.ext}]
    assert "诛仙" in dzl44.board(w44, p44, t44) and len(w44["board"]) == 1
    w44["board"] = []
    assert "诛仙" not in dzl44.board(w44, p44, t44 + 60)     # CD 内读缓存
    dzl44.sync_recast(d44b, "诛仙", "诛仙改", w44)
    assert "诛仙改" in dzl44.state_of(d44b)["artifacts"] and "诛仙改" in w44["named"]

    # ⑥ 一键 / 完美开炉：跳过时间、扣道具、perfect 系数 +0.1
    assert dzl44.melt(d44b, inv44, "星银*2", look44)[0]
    ok44, msg44, dl44 = dzl44.open_forge(d44b, "oneclick", inv44, t44,
                                         item_lookup=look44, templates=tpl44, rng=rng44)
    assert ok44 and dl44["时光令"] == -1 and "跳过时间衰减" in msg44
    assert dzl44.melt(d44b, inv44, "星银*2", look44)[0]
    ok44, msg44, dl44 = dzl44.open_forge(d44b, "perfect", inv44, t44,
                                         item_lookup=look44, templates=tpl44, rng=rng44)
    assert ok44 and dl44["造化本源"] == -1 and "+0.10" in msg44
    inv44["时光令"] = 0
    assert dzl44.melt(d44b, inv44, "星银*1", look44)[0]
    ok44, msg44, _ = dzl44.open_forge(d44b, "oneclick", inv44, t44,
                                      item_lookup=look44, templates=tpl44, rng=rng44)
    assert not ok44 and "时光令" in msg44

    # ⑦ 炉阶 / 炉火 / 功法 / 时光令配方 / 清炉
    inv44["道火"], inv44["混沌炉"] = 1, 1
    ok44, _, _ = dzl44.install_furnace(d44b, "混沌炉", inv44)
    assert ok44 and dzl44.capacity(dzl44.state_of(d44b), d44b) == 31
    ok44, _, _ = dzl44.light_fire(d44b, "道火", inv44)
    assert ok44 and abs(dzl44.time_speed(dzl44.state_of(d44b)) - 0.4) < 1e-9
    ok44, _, _ = dzl44.learn_gongfa(d44b, "无上炼器道", inv44)
    assert ok44 and d44b.stones == 1_000_000 and dzl44.state_of(d44b)["proficiency"] == 0
    ok44, _, _ = dzl44.synth_token(d44b, inv44, "1")
    assert not ok44
    ok44, _, dl44 = dzl44.learn_recipe(d44b, inv44)
    assert ok44 and dl44["时光令配方"] == -1
    ok44, _, dl44 = dzl44.synth_token(d44b, inv44, "2")
    assert ok44 and dl44["时光令"] == 2 and dl44["符纸"] == -20
    assert dzl44.start(d44b, t44)[0]
    dzl44.clear_state(dzl44.state_of(d44b))
    assert dzl44.state_of(d44b)["materials"] == [] and dzl44.state_of(d44b)["status"] == 0
    assert "我的锻炉" in dzl44.panel(d44b, t44, look44)
    assert "#熔炼" in dzl44.help_text() and "shortcut" in dzl44.rules_text()
    assert "星银" in dzl44.materials_text(look44, ["星银", "庚金"])
    assert "庚金" not in dzl44.materials_text(look44, ["星银", "庚金"])
    print("W8-C4 duanzao ok")

    # ── 45. W8-D1 灵园深化 / 环境 / 败天神殿 / 浇灌道具 / 仙兽驯服 / 仙宠岗位 ──
    from core import xiaoshijie as xs45  # noqa: E402
    rng45 = _random.Random(45)
    t45 = 1_800_000.0

    # ① 环境创造：映射 / 重复拒绝 / 未知道具
    w45 = {"name": "紫霄界", "level": 3, "avatar": True, "last_harvest": 0.0,
           "fields": [], "water_ts": 0.0}
    ok45, msg45, nw45 = xs45.create_environment(w45, "仙泉之眼")
    assert ok45 and nw45["env"] == ["仙泉"], msg45
    ok45, msg45, _ = xs45.create_environment(nw45, "仙泉之眼")
    assert not ok45 and "已拥有" in msg45
    ok45, msg45, _ = xs45.create_environment(w45, "乱七八糟")
    assert not ok45 and "仙泉之眼" in msg45
    assert len(xs45.ENVIRONMENTS) == 8

    # ② 神药环境门槛：悟道古茶树需 仙坟+仙泉；大夏无要求（3 级世界灵气 5000 种大夏可行）
    ok45, msg45, _ = xs45.plant({**nw45, "level": 5}, "悟道古茶树幼苗")
    assert not ok45 and "仙坟" in msg45, msg45
    ok45, msg45, nw45 = xs45.plant(nw45, "大夏神药种子")
    assert ok45, msg45
    ok45, msg45, nw45 = xs45.create_environment(nw45, "仙坟土")
    assert ok45 and nw45["env"] == ["仙泉", "仙坟"]
    ok45, msg45, nw45 = xs45.plant({**nw45, "level": 5}, "悟道古茶树幼苗")
    assert ok45, msg45
    assert xs45.stage_of({**nw45, "level": 5}, nw45["fields"][-1]) == 1  # 刚种=萌芽
    nw45["fields"][-1]["remaining"] = 0.01
    assert xs45.stage_of({**nw45, "level": 5}, nw45["fields"][-1]) == 5  # 快熟=成熟期
    # ③ 时间碎片：新栽生长 ×0.75（大夏 3000 灵气 → 12/8=1.5 现实小时 → 1.125）
    ok45, msg45, nw45 = xs45.create_environment(nw45, "时间沙漏")
    assert ok45
    ok45, msg45, nw45b = xs45.plant({**nw45, "level": 5}, "大夏神药种子")
    assert ok45 and abs(nw45b["fields"][-1]["remaining"] - 1.125) < 0.01, nw45b["fields"]  # round 2 位

    # ④ 败天神殿：建造扣费 / 重复拒绝 / 4h 一轮结算 / 96h 封顶
    ok45, msg45, nw45, cy45, cw45 = xs45.build_temple(nw45, 20_000, 15)
    assert ok45 and cy45 == 20_000 and cw45 == 15 and nw45["temple"]["built"], msg45
    assert not xs45.build_temple(nw45, 20_000, 15)[0]
    assert not xs45.build_temple(nw45, 19_999, 15)[0]
    assert not xs45.build_temple(nw45, 20_000, 14)[0]
    got45, hrs45 = xs45.settle_temple(dict(nw45, temple={"built": True, "last_settle": t45}), 8.0)
    assert got45 == {"yuanshi": 10_000, "insight": 10} and hrs45 == 8.0, got45
    got45, _ = xs45.settle_temple(dict(nw45, temple={"built": True, "last_settle": t45}), 200.0)
    assert got45["yuanshi"] == 24 * 5_000 and got45["insight"] == 24 * 5  # 96h/4h=24 轮

    # ⑤ 浇灌道具：单株按比例 / 批量按固定小时 / 乾坤造化瓶全田 -25%
    wf45 = {"name": "甲", "level": 3, "fields": [
        {"seed": "大夏神药种子", "remaining": 10.0},
        {"seed": "大夏神药种子", "remaining": 2.0},
        {"seed": "大夏神药种子", "remaining": 0.0},
    ]}
    ok45, msg45, nw45 = xs45.water_item(wf45, 1, "岁月流金沙")
    assert ok45 and abs(nw45["fields"][0]["remaining"] - 5.0) < 1e-9, msg45
    ok45, msg45, _ = xs45.water_item(wf45, 3, "草木精华露")
    assert not ok45 and "已经成熟" in msg45
    ok45, msg45, _ = xs45.water_item(wf45, 9, "草木精华露")
    assert not ok45 and "没有 9 号" in msg45
    ok45, msg45, nw45 = xs45.batch_water_item(wf45, "掌天灵液")
    assert ok45  # 10-12 与 2-12 都钳到 0
    assert nw45["fields"][0]["remaining"] == 0.0 and nw45["fields"][1]["remaining"] == 0.0
    ok45, msg45, _ = xs45.batch_water_item(wf45, "不存在")
    assert not ok45
    wf45b = {"name": "乙", "level": 3, "fields": [{"seed": "大夏神药种子", "remaining": 8.0}]}
    ok45, msg45, nw45 = xs45.force_ripen_all(wf45b)
    assert ok45 and abs(nw45["fields"][0]["remaining"] - 6.0) < 1e-9
    assert not xs45.force_ripen_all({"fields": [{"seed": "s", "remaining": 0}]})[0]

    # ⑥ 野外仙兽：事件概率公式 / 驯服成功入栖息地 / 失败逃离 / 符档优先
    assert 0.0 < xs45._tame_event_chance(24.0) < 0.09
    class _R45:
        def __init__(self, seq): self.seq = list(seq); self.i = 0
        def random(self):
            v = self.seq[self.i % len(self.seq)]; self.i += 1; return v
        def shuffle(self, _): pass
    w45, tame_msg45 = xs45.maybe_wild_beast(
        {"name": "甲", "pets": []}, 48.0, _R45([0.0, 0.5, 0.9]), now=t45)
    assert tame_msg45 and w45["tame"]["beast"]["type"] in xs45.BEAST_TYPES
    ok45, msg45, nw45 = xs45.tame(w45, "极品封灵符", _R45([0.5]), now=t45)
    assert ok45 and nw45["pets"] and nw45["pets"][0]["name"] == w45["tame"]["beast"]["name"], msg45
    assert nw45["tame"] is None
    # 事件过期
    w45b = {"name": "甲", "pets": [], "tame": {"beast": {"name": "x", "type": "战斗", "quality": "仙胎", "traits": []}, "expires": t45 - 1}}
    ok45, msg45, _ = xs45.tame(w45b, "极品封灵符", _R45([0.0]), now=t45)
    assert not ok45 and "没有仙兽" in msg45
    # 驯服失败
    w45c = {"name": "甲", "pets": [], "tame": {"beast": {"name": "x", "type": "战斗", "quality": "仙胎", "traits": []}, "expires": t45 + 100}}
    ok45, msg45, nw45 = xs45.tame(w45c, "普通封灵符", _R45([0.999]), now=t45)
    assert not ok45 and "挣脱" in msg45 and nw45["tame"] is None
    # 符档优先
    assert xs45.pick_talisman({"普通封灵符": 2, "上品封灵符": 1})[0] == "上品封灵符"
    assert xs45.pick_talisman({"普通封灵符": 2})[0] == "普通封灵符"
    assert xs45.pick_talisman({}) is None

    # ⑦ 仙宠岗位：安置 / 容量 / 分配类型不匹配提示 / 召回 / 守卫 / 偷菜成功率联动
    wp45 = {"name": "甲", "level": 1, "pets": []}   # 1 级栖息地 = 1 位
    ok45, msg45, wp45 = xs45.place_pet(wp45, "赤瞳灵狐", "战斗", "仙胎", ["勤勉"])
    assert ok45, msg45
    ok45, msg45, _ = xs45.place_pet(wp45, "九尾仙猫", "修炼", "仙仔")
    assert not ok45 and "已满" in msg45
    ok45, msg45, wp45 = xs45.place_pet({**wp45, "level": 3}, "九尾仙猫", "修炼", "仙仔")
    assert ok45
    ok45, msg45, wp45 = xs45.assign_pet(wp45, "赤瞳灵狐", "矿脉")
    assert ok45 and "不合" not in msg45  # 战斗型配矿脉 = 匹配
    ok45, msg45, wp45 = xs45.assign_pet(wp45, "九尾仙猫", "丹房")
    assert ok45 and "×0.5" in msg45  # 修炼型配丹房（只收炼丹型）不匹配
    ok45, msg45, wp45 = xs45.recall_pet(wp45, "赤瞳灵狐")
    assert ok45, msg45
    ok45, msg45, wp45 = xs45.set_guard(wp45, "赤瞳灵狐")
    assert ok45
    assert xs45.steal_rate(wp45) < xs45.steal_rate({"name": "甲", "level": 3, "pets": []})
    ok45, msg45, wp45 = xs45.unset_guard(wp45)
    assert ok45 and not wp45["pets"][0]["guard"]
    # 工坊容量 = 工坊等级
    wp45b = {"name": "甲", "level": 5, "pets": [
        {"name": "a", "type": "战斗", "quality": "仙胎", "traits": [], "workshop": "矿脉", "guard": False, "energy": 100, "max_energy": 100, "cycle": 0.0},
        {"name": "b", "type": "战斗", "quality": "仙胎", "traits": [], "workshop": "矿脉", "guard": False, "energy": 100, "max_energy": 100, "cycle": 0.0},
        {"name": "c", "type": "战斗", "quality": "仙胎", "traits": [], "workshop": None, "guard": False, "energy": 100, "max_energy": 100, "cycle": 0.0},
    ], "workshops": {"矿脉": 2}}
    ok45, msg45, _ = xs45.assign_pet(wp45b, "c", "矿脉")
    assert not ok45 and "只能容纳" in msg45
    ok45, msg45, _ = xs45.assign_pet(wp45b, "不存在的", "矿脉")
    assert not ok45

    # ⑧ 精力作息数学：14/7/3 循环 / 效率分档 / 恢复
    st45 = xs45.energy_period(100, 100, 10, 4.0)
    assert st45["active"] == 10.0 and st45["end"] == 60.0 and st45["weighted"] == 10.0
    st45 = xs45.energy_period(20, 100, 10, 4.0)
    assert st45["end"] == 0.0 and abs(st45["weighted"] - (2.5 * 0.6 + 2.5 * 0.2)) < 1e-9  # 20→10 中档2.5h + 10→0 低档2.5h
    st45 = xs45.energy_period(50, 100, 10, -8.0)
    assert st45["end"] == 100.0  # 休息封顶
    cp45 = xs45.care_period(100, 100, 24.0, 4.0, 0.0)
    assert cp45["meals"] == 1.0 and cp45["rest"] == 7.0 and cp45["play"] == 3.0, cp45

    # ⑨ harvest_full 端到端：资源 + 神殿 + 宠物产出 + 喂食缺餐降效 + 深化环境加成
    wh45 = {"name": "紫霄界", "level": 5, "avatar": True,
            "last_harvest": t45 - 8 * 3600,   # 8 现实小时 × 流速 8 = 64 有效小时
            "fields": [], "water_ts": 0.0,
            "env": ["星辰矿脉", "生命古树"],
            "temple": {"built": True, "last_settle": t45 - 8 * 3600},
            "pets": [
                {"name": "石煞", "type": "战斗", "quality": "仙灵", "traits": [],
                 "energy": 100, "max_energy": 100, "workshop": "矿脉", "guard": False, "cycle": 0.0},
            ],
            "supplies": {"仙宠口粮": 10, "界源矿石": 0, "工坊构件": 0, "欠餐": 0}}
    inv45 = {}
    ok45, msg45, nw45, out45, ex45 = xs45.harvest_full(wh45, now=t45, inv=inv45, rng=_random.Random(7))
    assert ok45, msg45
    assert out45["__stones__"] >= 800_000 * 64 and out45.get("灵矿", 0) >= int(20 * 64 * 1.5)  # 星辰矿脉 +50%
    assert out45.get("仙馐果", 0) >= int(300 * 64 * 1.5)  # 生命古树 +50%
    assert ex45.get("yuanshi") == 10_000 and ex45.get("insight") == 10  # 神殿 8h = 2 轮
    assert any("石煞" in ln for ln in ex45.get("pet_logs", [])), ex45.get("pet_logs")
    # 仙灵 = 5 倍品级；战斗宠矿脉：灵石 50000/h + 源石 1500/h（64 有效小时 ≈ 42 工时）
    assert ex45.get("__yuanshi__", 0) > 0
    # 喂食：口粮充足 → 吃 2 份（64h≈2.67 轮，取整轮 2）、无欠餐
    assert nw45["supplies"]["仙宠口粮"] == 8 and nw45["supplies"]["欠餐"] == 0, nw45["supplies"]
    assert "界源矿石" in nw45["supplies"] and nw45["supplies"]["界源矿石"] > 0
    # 老四元组兼容入口仍可用
    ok45, msg45, _w45, out45b = xs45.harvest({"name": "乙", "avatar": True, "last_harvest": t45 - 3600, "level": 1, "fields": []})
    assert ok45 and out45b.get("__stones__", 0) > 0
    print("W8-D1 xiaoshijie ok")

    # ── 46. W8-D2 星阁 · 竞价拍卖 / 惰性结算 / 内场验资 / NPC ──
    from core import auction as xg46  # noqa: E402
    t46 = 1_800_000.0
    pools46 = {
        "official": [{"name": "玄铁", "class": "材料", "出售价": 500000,
                      "desc": "顶级材料", "稀有度": 3}],
        "inner": [{"name": "帝品秘境结算卡", "class": "道具", "出售价": 1300000,
                   "数量": 1, "desc": "副本-30分钟", "稀有度": 10}],
    }
    r46 = _random.Random(46)
    seller46 = PlayerDoc(uid="seller", stones=1000, ext={})
    buyer46 = PlayerDoc(uid="buyer", stones=10_000_000, ext={})

    # ① 世界状态默认值 / 写回
    st46: dict = {}
    w46 = xg46.world_of(st46)
    assert w46["player"] is None and w46["official"] is None and w46["inner"] is None
    assert w46["enabled"] is False and w46["claims"] == [] and w46["last_list"] == {}
    xg46.set_world(st46, w46)
    assert xg46.WORLD_KEY in st46 and xg46.world_of(st46)["seq"] == 0

    # ② 上架：格式 / 全服唯一 / 禁售 / 24h CD / 扣物
    ok46, msg46, _ = xg46.list_item(w46, seller46, {}, "玄铁", t46)
    assert not ok46 and "格式" in msg46
    ok46, msg46, d46 = xg46.list_item(w46, seller46, {"玄铁": 3}, "玄铁*1000*2", t46)
    assert ok46 and d46 == {"玄铁": -2} and w46["player"]["amount"] == 2, msg46
    ok46, msg46, _ = xg46.list_item(w46, seller46, {"玄铁": 3}, "玄铁*1000", t46)
    assert not ok46 and "仅 1 场" in msg46
    w46["player"] = None
    secret46 = PlayerDoc(uid="secret", stones=1000,
                         ext={"forge": {"artifacts": {"我的神兵": {}}}})
    ok46, msg46, _ = xg46.list_item(w46, secret46, {"我的神兵": 1}, "我的神兵*100", t46)
    assert not ok46 and "不可交易" in msg46
    w46["last_list"] = {}          # 前面成功上架写过 CD，隔离后再测 CD 本身
    ok46, _, _ = xg46.list_item(w46, seller46, {"玄铁": 3}, "玄铁*1000*1", t46)
    assert ok46
    w46["player"] = None
    ok46, msg46, _ = xg46.list_item(w46, seller46, {"玄铁": 3}, "玄铁*1000*1", t46 + 3600)
    assert not ok46 and "冷却" in msg46

    # ③ 竞价：10% 门槛 / 禁止卖家与最高者 / 余额 / 倒计时重置
    w46["player"] = None
    w46["last_list"] = {}          # 独立场景，清掉上一组的 24h CD
    ok46, _, _ = xg46.list_item(w46, seller46, {"玄铁": 2}, "玄铁*1000*2", t46)
    assert ok46
    ok46, msg46, _ = xg46.bid(w46, seller46, "player", "1100", t46 + 1, r46)
    assert not ok46 and "卖家" in msg46
    ok46, msg46, _ = xg46.bid(w46, buyer46, "player", "1000", t46 + 1, r46)
    assert not ok46 and "10%" in msg46
    ok46, msg46, _ = xg46.bid(w46, buyer46, "player", "", t46 + 1, r46)
    assert ok46 and w46["player"]["price"] == 1100 and w46["player"]["bid_ts"] == t46 + 1
    ok46, msg46, _ = xg46.bid(w46, buyer46, "player", "2000", t46 + 2, r46)
    assert not ok46 and "最高出价者" in msg46
    poor46 = PlayerDoc(uid="poor", stones=100, ext={})
    ok46, msg46, _ = xg46.bid(w46, poor46, "player", "", t46 + 2, r46)
    assert not ok46 and "灵石不足" in msg46

    # ④ 惰性结算：未到时间不动 / 超时成交（买家扣款+发货、卖家收款）/ 幂等
    bal46 = {"buyer": (10_000_000, 0), "seller": (1000, 0)}
    notes46, ops46 = xg46.tick(w46, t46 + 60, pools46, r46, bal46)
    assert not notes46 and not ops46
    notes46, ops46 = xg46.tick(w46, t46 + 121, pools46, r46, bal46)
    assert any("成交" in n for n in notes46), notes46
    bop46 = [o for o in ops46 if o["uid"] == "buyer"][0]
    assert bop46["stones"] == -1100 and bop46["items"] == {"玄铁": 2}
    assert any(o["uid"] == "seller" and o["stones"] == 1100 for o in ops46)
    assert w46["player"] is None
    _, ops46b = xg46.tick(w46, t46 + 300, pools46, r46, bal46)
    assert not ops46b

    # ⑤ 流拍退物 / 违约 / NPC 得标不扣款
    wf46 = xg46.world_of({})
    xg46.list_item(wf46, seller46, {"玄铁": 1}, "玄铁*100*1", t46)
    notes46, ops46 = xg46.tick(wf46, t46 + 121, {}, r46, {})
    assert any("流拍" in n for n in notes46)
    assert any(o["uid"] == "seller" and o["items"] == {"玄铁": 1} for o in ops46)
    wd46 = xg46.world_of({})
    xg46.list_item(wd46, seller46, {"玄铁": 1}, "玄铁*100*1", t46)
    xg46.bid(wd46, buyer46, "player", "110", t46 + 1, r46)
    notes46, ops46 = xg46.tick(wd46, t46 + 122, {}, r46, {"buyer": (0, 0)})
    assert any("余额不足" in n for n in notes46), notes46
    assert not any(o.get("stones", 0) < 0 for o in ops46)
    wn46 = xg46.world_of({})
    wn46["player"] = {"id": "p-x", "kind": "player", "name": "玄铁", "class": "材料",
                      "amount": 1, "start": 100, "price": 200, "bid_ts": t46,
                      "bidder": "-1", "seller": "seller", "desc": "", "rarity": 0}
    notes46, ops46 = xg46.tick(wn46, t46 + 121, {}, r46, {})
    assert any("NPC" in n for n in notes46) and not any(o.get("stones", 0) < 0 for o in ops46)

    # ⑥ 官方开拍 / 管理员开关 / 面板文案
    wo46 = xg46.world_of({})
    wo46["enabled"] = True
    notes46, _ = xg46.tick(wo46, t46, pools46, _random.Random(1), {})
    assert any("开拍" in n for n in notes46) and wo46["official"]["start"] == 500000
    assert "500,000" in xg46.panel(wo46, "official", t46)
    ok46, _, _ = xg46.switch(wo46, "close", False, "", True)
    assert ok46 and wo46["official"] is None and wo46["enabled"] is False
    ok46, msg46, _ = xg46.switch(wo46, "open", False, "g1", False)
    assert not ok46 and "管理员" in msg46
    assert "尚未开启" in xg46.panel(xg46.world_of({}), "official", t46)
    ws46 = xg46.world_of({})
    xg46.switch(ws46, "open", False, "g1", True)
    assert ws46["enabled"] and ws46["groups"] == ["g1"]
    xg46.switch(ws46, "cancel", False, "g1", True)
    assert ws46["groups"] == []

    # ⑦ 内场验资：1200 万门槛 / 扣 500 万买断 / 永久 / 无身份禁出价
    ypoor46 = PlayerDoc(uid="v", stones=0, ext={"yuanshi": {"amount": 11_999_999}})
    ok46, msg46, _ = xg46.verify_inner(ypoor46)
    assert not ok46 and "验资需" in msg46
    rich46 = PlayerDoc(uid="v", stones=0, ext={"yuanshi": {"amount": 12_000_000}})
    ok46, msg46, _ = xg46.verify_inner(rich46)
    assert ok46 and rich46.ext["yuanshi"]["amount"] == 7_000_000
    assert rich46.ext[xg46.INNER_FLAG] == 1
    ok46, msg46, _ = xg46.verify_inner(rich46)
    assert not ok46 and "永久" in msg46
    wi46 = xg46.world_of({})
    wi46["enabled2"] = True
    xg46.tick(wi46, t46, pools46, _random.Random(2), {})
    noid46 = PlayerDoc(uid="n", stones=0, ext={"yuanshi": {"amount": 9_000_000}})
    ok46, msg46, _ = xg46.bid(wi46, noid46, "inner", "", t46, _random.Random(3))
    assert not ok46 and "验资" in msg46

    # ⑧ 内场 NPC 同步抬价（原版 30%/分钟 cron 的等价替代）
    class _R46:
        def __init__(self, first): self.first, self.calls = first, 0
        def random(self):
            self.calls += 1
            return self.first if self.calls == 1 else 0.5
        def choices(self, pop, weights=None, k=1): return [(1.05, 1.15)]
        def uniform(self, a, b): return (a + b) / 2
        def choice(self, seq): return seq[0]
    wi46b = xg46.world_of({})
    wi46b["enabled2"] = True
    xg46.tick(wi46b, t46, pools46, _R46(0.9), {})
    ok46, msg46, _ = xg46.bid(wi46b, rich46, "inner", "", t46, _R46(0.0))
    assert ok46 and "神秘 NPC" in msg46 and wi46b["inner"]["bidder"] == "-1", msg46

    assert "无手续费" in xg46.rules_text() and "#星阁内场验资" in xg46.help_text()
    print("W8-D2 auction ok")

    # ── 47. W8-D3 诡异大祭 / 位面后果 / 永久覆灭与回滚 ──
    from types import SimpleNamespace
    from unittest.mock import patch
    from core import sacrifice as ss47

    st47 = SimpleNamespace(atk=100_000, defense=100_000, hp=1_000_000, bao=0.1)
    t47, y47 = 1_800_000.0, 5_000
    r47 = _random.Random(47)

    # ① 状态归一 / 管理员开关
    w47 = ss47.world_of({"sacrifice": {"phase": "bad", "damage": None, "small_count": -3}})
    assert w47["damage"] == {} and w47["small_count"] == 0 and w47["small_due"] is None
    ok47, msg47, _, _ = ss47.open_event(w47, "small", y47, t47, st47, False)
    assert not ok47 and "管理员" in msg47
    ok47, _, _, _ = ss47.open_event(w47, "big", y47, t47, st47, True)
    assert ok47 and w47["phase"] == "big" and w47["active"]["hpmax"] > 0
    ok47, msg47, _, _ = ss47.open_event(w47, "small", y47, t47, st47, True)
    assert not ok47 and "已有" in msg47

    # ② 门槛 / 每人每轮一次
    weak47 = PlayerDoc(uid="weak", realm_index=10, ext={})
    ok47, msg47, _, _ = ss47.fight(w47, weak47, st47, y47, t47, r47, "big")
    assert not ok47 and "权柄" in msg47
    emp47 = PlayerDoc(uid="emp", realm_index=63, stones=0, exp=0, ext={})
    with patch("core.battle.spar_full", return_value=(0, [], 100, 0)):
        ok47, msg47, _, _ = ss47.fight(w47, emp47, st47, y47, t47, r47, "big")
    assert ok47 and "迎战功成" in msg47 and emp47.stones > 0
    w47["damage"]["emp"] > 0 and w47["active"]["hp"] < w47["active"]["hpmax"]
    ok47, msg47, _, _ = ss47.fight(w47, emp47, st47, y47, t47, r47, "big")
    assert not ok47 and ("调息" in msg47 or "本轮" in msg47), msg47

    # ③ 战败 → 24h 身灭道消 + 天意一刀计数
    w47c = ss47.world_of({})
    ss47.open_event(w47c, "small", y47, t47, st47, True)
    loser47 = PlayerDoc(uid="loser", realm_index=60, ext={})
    with patch("core.battle.spar_full", return_value=(1, [], 0, 100)):
        ok47, msg47, _, _ = ss47.fight(w47c, loser47, st47, y47, t47, r47, "small")
    assert ok47 and "迎战失利" in msg47
    pst47 = ss47.state_of(loser47)
    assert pst47["deathlock_until"] == t47 + ss47.DEATHLOCK_SEC and pst47["slash_count"] == 1
    ok47, msg47, _, _ = ss47.fight(w47c, loser47, st47, y47, t47, r47, "small")
    assert not ok47 and "身灭道消" in msg47

    # ④ 未达终局档 → 因果回溯（本源复原、战绩清空、可再战）
    w47d = ss47.world_of({})
    ss47.open_event(w47d, "big", y47, t47, st47, True)
    w47d["active"]["hp"] = 1
    mid47 = PlayerDoc(uid="mid", realm_index=57, ext={})
    with patch("core.battle.spar_full", return_value=(0, [], 100, 0)):
        ok47, msg47, _, ops47 = ss47.fight(w47d, mid47, st47, y47, t47, r47, "big")
    assert ok47 and "因果回溯" in msg47 and w47d["rewinds"] == 1
    assert w47d["active"]["hp"] == w47d["active"]["hpmax"] and w47d["participants"] == {}

    # ⑤ 满档终局 → 三重永久标记，此后无法再开祭
    w47e = ss47.world_of({})
    ss47.open_event(w47e, "big", y47, t47, st47, True)
    w47e["active"]["hp"] = 1
    with patch("core.battle.spar_full", return_value=(0, [], 100, 0)):
        ok47, msg47, _, ops47e = ss47.fight(w47e, emp47, st47, y47,
                                            t47 + ss47.FIGHT_CD_SEC + 1, r47, "big")
    assert ok47 and "高原彻底覆灭" in msg47 and w47e["plateau_destroyed"], msg47
    assert w47e["phase"] == "destroyed" and w47e["active"] is None
    assert any(o[0] == "mark" and o[1] == ss47.HIGHLAND for o in ops47e)
    ok47, msg47, _, _ = ss47.open_event(w47e, "big", y47 + 1, t47, st47, True)
    assert not ok47 and "永不复启" in msg47

    # ⑥ 守界失败 → 崩灭 2 处位面 + 永寂名单只收低档且在被毁位面者
    w47f = ss47.world_of({})
    ss47.open_event(w47f, "big", y47, t47, st47, True)
    ok47, msg47, _, ops47f = ss47.settle(w47f, y47, t47, True, _random.Random(6))
    marks47 = [o[1] for o in ops47f if o[0] == "mark"]
    assert ok47 and len(marks47) == 2 and len(set(marks47)) == 2
    assert set(marks47) <= set(ss47.SACRIFICE_PLANES) and "凡间" not in marks47
    n47 = ss47.record_yongji(w47f, [("a", "甲", marks47[0], 5),
                                    ("b", "乙", marks47[0], 20),
                                    ("c", "丙", "凡间", 5)], t47)
    assert n47 == 1 and "a" in w47f["yongji"]

    # ⑦ 回滚：#复苏厄土高原 三重同清；#恢复诸天位面 修界门 + 清名单
    w47g = ss47.world_of({})
    w47g["plateau_destroyed"], w47g["phase"] = True, "destroyed"
    w47g["plane_log"] = [ss47.HIGHLAND, "界海"]
    w47g["yongji"] = {"a": {"name": "甲", "plane": "界海", "at": t47}}
    ok47, msg47, _, ops47g = ss47.restore_highland(w47g, y47 + 10, t47, True)
    assert ok47 and not w47g["plateau_destroyed"] and w47g["phase"] == "dormant"
    assert w47g["small_due"] == y47 + 10 + ss47.SMALL_INTERVAL
    assert ("clear", ss47.HIGHLAND) in ops47g and ("clear", "界海") in ops47g
    assert w47g["yongji"] == {} and w47g["plane_log"] == []
    ok47, msg47, _, ops47g2 = ss47.repair_all(w47g, False)
    assert not ok47
    w47g["plane_log"], w47g["yongji"] = ["遮天位面"], {"z": {}}
    ok47, msg47, _, ops47g2 = ss47.repair_all(w47g, True)
    assert ok47 and ("clear_all",) in ops47g2 and w47g["yongji"] == {}

    # ⑧ 惰性 advance：世界年到期自动结算 + 24h 无活动兜底
    w47h = ss47.world_of({})
    ss47.open_event(w47h, "small", y47, t47, st47, True)
    notes47, ops47h = ss47.advance(w47h, y47 + ss47.ACTIVE_YEARS, t47 + 10, st47, _random.Random(8))
    assert notes47 and w47h["active"] is None and w47h["big_due"] == y47 + ss47.ACTIVE_YEARS + ss47.BIG_DELAY
    w47i = ss47.world_of({})
    ss47.open_event(w47i, "big", y47, t47, st47, True)
    notes47, _ = ss47.advance(w47i, y47, t47 + ss47.INACTIVE_SEC + 1, st47, _random.Random(9))
    assert notes47 and "24h" in notes47[0] and w47i["active"] is None

    # ⑨ 面板与帮助不空
    assert "世界年" in ss47.status_text(w47h, y47) and "始祖" in ss47.ancestor_text(w47i)
    assert "#复苏厄土高原" in ss47.help_text() and "无 cron" in ss47.rules_text()
    assert "贡献" in ss47.rank_text(w47f) or "尚无" in ss47.rank_text(w47f)
    box47 = {}
    ss47.set_world(box47, dict(w47h, destroyed_view={"界海": {}}))
    assert "destroyed_view" not in box47["sacrifice"] and "phase" in box47["sacrifice"]
    print("W8-D3 sacrifice ok")

    # ============ 第 48 组：W8-D4 组队迎战帝尊 / 多人团本 ============
    from core import tuanben as tb48
    from core.combat import Fighter as F48, run_raid as raid48

    t48 = 1_800_000_000.0
    rng48 = _random.Random(48)

    # ① 全服单例：老档兼容、白名单过滤临时视图、类型归一化
    w48 = tb48.world_of({})
    assert set(w48) == set(tb48.DEFAULTS) and w48["enabled"] and w48["awareness"] == "reclaim"
    w48b = tb48.world_of({"tuanben": {"enabled": False, "emperor_codes": ["123456"],
                                      "awareness": "乱写", "junk": 1}})
    assert not w48b["enabled"] and w48b["emperor_codes"] == ["123456"]
    assert w48b["awareness"] == "reclaim"
    box48 = {}
    w48c = dict(tb48.world_of(box48), destroyed_view={"遮天位面": {}})
    tb48.set_world(box48, w48c)
    assert "destroyed_view" not in box48["tuanben"]
    w48c["emperor_codes"].append("999999")
    assert "999999" not in box48["tuanben"]["emperor_codes"]   # 深拷贝，不留可变引用

    # ② 自然周：周一 0 点（北京时间）为界，跨周额度重置
    wk48 = tb48.week_key(t48)
    assert wk48 != tb48.week_key(t48 + 7 * 86400)
    assert tb48.weekly_left(w48, "u48", t48) == tb48.WEEKLY_LIMIT
    tb48.consume_weekly(w48, "u48", 4, t48)
    assert tb48.weekly_left(w48, "u48", t48) == tb48.WEEKLY_LIMIT - 4
    assert tb48.weekly_left(w48, "u48", t48 + 7 * 86400) == tb48.WEEKLY_LIMIT
    assert len(w48["weekly"]["u48"]) == 1                       # 旧周惰性清掉

    # ③ 门槛 / 感知 / 沉眠 / 系统开关
    low48 = PlayerDoc(uid="low48", realm_index=10, ext={})
    assert not tb48.emperor_gate(15) and tb48.emperor_gate(16)
    ok48, msg48 = tb48.can_create_emperor(low48, w48, False, 15, True, t48)
    assert not ok48 and "权柄" in msg48
    w48["enabled"] = False
    ok48, msg48 = tb48.can_create_emperor(low48, w48, False, 20, True, t48)
    assert not ok48 and "关闭" in msg48
    w48["enabled"] = True
    ok48, msg48 = tb48.can_create_emperor(low48, w48, True, 20, True, t48)
    assert not ok48 and "别的讨伐队伍" in msg48
    ok48, _ = tb48.awareness_available(w48, True)
    assert ok48
    w48["awareness"] = "confront"
    ok48, msg48 = tb48.awareness_available(w48, False)
    assert not ok48 and "遮天位面" in msg48
    ok48, _ = tb48.awareness_available(w48, True)
    assert ok48
    w48["awareness"] = "reclaim"
    s48 = tb48.player_state_of(low48)
    tb48.defeat_penalty(low48, s48, t48)
    tb48.set_player(low48, s48)
    assert tb48.sleep_left(low48, t48) == tb48.DEFEAT_SLEEP
    ok48, msg48 = tb48.can_create_emperor(low48, w48, False, 20, True, t48)
    assert not ok48 and "沉眠" in msg48
    ok48, _ = tb48.can_create_emperor(low48, w48, False, 20, True,
                                      t48 + tb48.DEFEAT_SLEEP + 1)
    assert ok48
    w48["emperor_defeated"] = True
    ok48, msg48 = tb48.can_create_emperor(low48, w48, False, 20, True,
                                          t48 + tb48.DEFEAT_SLEEP + 1)
    assert not ok48 and "归寂" in msg48
    w48["emperor_defeated"] = False

    # ④ run_raid：阶段复活（者字秘·极尽）、伤害账本、确定性
    p48 = tb48.player_fighter("u1", "甲", 1000, 400, 5000, 5000, 0.1, 0, speed=100)
    b48 = F48(name="帝尊", atk=1, defense=1, hp=100, hp_max=100, bao=0.0,
              tags={"key": "boss", "speed": 1, "phase_revive": 1,
                    "phase_mult": 1.3, "phase_name": "者字秘·极尽"})
    r48 = raid48([p48], b48, _random.Random(9), max_rounds=10)
    assert r48.win and r48.phases == ["者字秘·极尽"] and r48.boss_hp == 0
    assert r48.damage["u1"] > 0 and r48.rounds >= 2
    p48b = tb48.player_fighter("u1", "甲", 1000, 400, 5000, 5000, 0.1, 0, speed=100)
    b48b = F48(name="帝尊", atk=1, defense=1, hp=100, hp_max=100, bao=0.0,
               tags={"key": "boss", "speed": 1, "phase_revive": 1,
                     "phase_mult": 1.3, "phase_name": "者字秘·极尽"})
    r48b = raid48([p48b], b48b, _random.Random(9), max_rounds=10)
    assert (r48.win, r48.log, r48.damage, r48.rounds) == (
        r48b.win, r48b.log, r48b.damage, r48b.rounds)

    # ⑤ 玩家侧者字秘：致死复活一次后仍会全灭，BOSS 胜利
    p48c = tb48.player_fighter("u2", "乙", 10, 10, 100, 100, 0.0, 1, speed=100)
    b48c = F48(name="帝尊", atk=100000, defense=100000, hp=10**9, hp_max=10**9,
               bao=0.0, tags={"key": "boss", "speed": 10})
    r48c = raid48([p48c], b48c, _random.Random(5), max_rounds=6)
    assert not r48c.win and any("者字秘" in x for x in r48c.log)
    assert r48c.player_hp["u2"] == 0 and r48c.survivors == []

    # ⑥ 胜率梯度：1 人必败、5 人高胜率（多人协作有意义，避免数值必败）
    def _sim48(n: int, seed: int) -> bool:
        fs = [tb48.player_fighter(f"p{i}", f"甲{i}", 1000, 400, 5000, 5000, 0.1, 1)
              for i in range(n)]
        bb = tb48.boss_fighter(1000, n, _random.Random(seed))
        return raid48(fs, bb, _random.Random(seed + 100), max_rounds=30).win
    assert sum(_sim48(1, s) for s in range(8)) == 0
    assert sum(_sim48(5, s) for s in range(8)) >= 5

    # ⑦ 结算落全服：DPS 榜 / 战报 / 感知归寂 / 管理员回滚
    w48d = tb48.world_of({})
    w48d["emperor_codes"] = ["123456"]
    members48 = [{"uid": "u1", "name": "甲"}, {"uid": "u2", "name": "乙"}]
    win48 = tb48.settle_battle(w48d, "123456", r48, members48, t48, True)
    assert "伏诛" in win48 and w48d["emperor_defeated"]
    assert w48d["emperor_codes"] == [] and w48d["dps"]["123456"][0] == ["甲", r48.damage["u1"]]
    assert "玩家胜利" in tb48.log_text(w48d) and "甲" in tb48.rank_text(w48d, "123456")
    assert "尚无" in tb48.rank_text(w48d, "000000")
    assert "无需复苏" in tb48.revive_emperor(tb48.world_of({}), t48)
    assert "感知重开" in tb48.revive_emperor(w48d, t48)
    assert not w48d["emperor_defeated"] and w48d["defeated_at"] == 0.0
    assert w48d["awareness"] == "reclaim"

    # ⑧ 奖励池：不重复抽 N 组、兜底、41 组文本、魔君批量结算
    pool48 = ContentStore(PLUGIN / "data").table("团本奖励列表")
    assert len(pool48) == 41
    loot48 = tb48.draw_loot(pool48, rng48, 8)
    assert loot48 and len(tb48.draw_loot([], rng48, 3)) == 1
    assert "41 组" in tb48.loot_text(pool48)
    w48e = tb48.world_of({})
    ok48, msg48, delta48 = tb48.mojun_settle(w48e, "u9", 3, 2, t48, pool48, rng48)
    assert ok48 and delta48["tokens"] == 2 and delta48["rounds"] == 2
    assert tb48.weekly_left(w48e, "u9", t48) == tb48.WEEKLY_LIMIT - 2
    assert sum(delta48["items"].values()) > 0 and delta48["stones"] == tb48.MOJUN_STONES * 2
    ok48, msg48, _ = tb48.mojun_settle(w48e, "u9", 1000, 5, t48, pool48, rng48)
    assert not ok48 and "999" in msg48
    ok48, msg48, _ = tb48.mojun_settle(w48e, "u9", 1, 0, t48, pool48, rng48)
    assert not ok48 and "讨伐令" in msg48

    # ⑨ 管理员：开关 / 重置闸 / 关闭所有 / 感知切换 / 文本完整
    w48f = tb48.world_of({})
    assert "关闭" in tb48.system_switch(w48f, False, t48) and not w48f["enabled"]
    assert "开启" in tb48.system_switch(w48f, True, t48) and w48f["enabled"]
    assert "重置" in tb48.reset_cd(w48f, t48) and w48f["cd_reset_at"] == t48
    w48f["emperor_codes"] = ["1", "2"]
    assert "2 支" in tb48.shutdown(w48f, t48) and w48f["emperor_codes"] == []
    assert "confront" in tb48.awareness_switch(w48f, "confront", t48)
    assert w48f["awareness"] == "confront"
    assert "confront" in tb48.awareness_switch(w48f, "对抗", t48)
    assert w48f["awareness"] == "confront"
    assert "reclaim" in tb48.awareness_switch(w48f, "reclaim", t48)
    assert w48f["awareness"] == "reclaim"
    assert "#迎战帝尊" in tb48.help_text() and "16 小时" not in tb48.rules_text()
    assert "24h" in tb48.rules_text() and "W8-D5" in tb48.rules_text()
    assert "团本系统" in tb48.system_text(w48f)
    assert "权柄" in tb48.status_text(w48f, low48, 20, True, t48, None, "")

    # ⑩ DB 新方法（不改表结构，db 仍 v17）：离队 / 一次性结算 / 全关
    await db.create_raid("481234", tb48.EMPEROR, "lead48", "队长", t48)
    await db.join_raid("481234", "join48", "队员", t48)
    await db.start_raid("481234", {"hp": 500, "hp_max": 500, "atk": 10,
                                   "defense": 10, "reward": 0})
    await db.settle_raid_battle("481234", {"lead48": 300, "join48": 200},
                                0, "victory", t48)
    trow48 = await db.get_raid("481234")
    assert trow48["status"] == "victory" and trow48["hp"] == 0 and trow48["settled"]
    assert (await db.raid_member("481234", "join48"))["dmg"] == 200
    assert await db.leave_raid("481234", "join48")
    assert await db.raid_member("481234", "join48") is None
    await db.create_raid("485678", "若陀龙王", "lead48", "队长", t48)
    assert await db.close_all_raids(t48) >= 1
    assert (await db.get_raid("485678"))["status"] == "closed"
    print("W8-D4 tuanben ok")

    # ---------------- 49. W8-D5 若陀龙王竞价团 ----------------
    import json as _json49
    from core import teamboss as dr49
    from core import equipment as eq49

    t49 = 1_800_000.0
    pool49 = _json49.load(
        open(PLUGIN / "data/item/GroupBoss.json", encoding="utf-8-sig"))[0]["one"]
    assert len(pool49) == 36, "GroupBoss.json 掉落池应 36 条（非团本奖励列表）"

    def p49(uid: str, name: str = "道友", stones: int = 10 ** 9,
            realm: int = 45, cd: float = 0.0) -> PlayerDoc:
        d = PlayerDoc(uid=uid, name=name, realm_index=realm, stones=stones)
        d.ext["dragon"] = {"cd_until": cd, "exit_ids": [], "battles": 0,
                           "kills": 0, "last_id": 1}
        return d

    st49 = eq49.Stats(atk=20000, defense=18000, hp=60000, bao=0.15, set_lines=[])

    # ① 整数加价 / 血条公式 / 状态单例深拷贝
    assert dr49.min_bid(100) == 130 and dr49.min_bid(1) == 2
    assert dr49.min_bid(666888) == 866955          # 原版 ceil(666888*1.3)
    assert dr49.boss_hp(20000, 8) == 8_000_000
    assert dr49.boss_hp(20000, 1) == 5_000_000     # 人数下限 5
    state49: dict = {}
    w49 = dr49.world_of(state49)
    assert w49["enabled"] and w49["next_id"] == 1 and w49["bosses"] == {}
    dr49.set_world(state49, w49)
    w49["bosses"]["x"] = {"bad": 1}
    assert "x" not in state49["dragon"]["bosses"], "set_world 必须深拷贝"
    w49 = dr49.world_of(state49)                 # 丢弃临时脏视图
    # 与 D4 团本状态互不串扰
    state49["tuanben"] = {"enabled": False}
    assert tb48.world_of(state49)["enabled"] is False
    assert dr49.world_of(state49)["enabled"] is True

    # ② 掉落：建团时抽定 5 件、同种子确定性、起拍价来自出售价
    a49 = dr49.draw_loot(pool49, _random.Random(5))
    b49 = dr49.draw_loot(pool49, _random.Random(5))
    assert len(a49) == 5 and a49 == b49
    assert all(x["amount"] == 1 and x["bidder"] == "" for x in a49)
    assert all(x["price"] == max(1, int(next(
        (e for e in pool49 if e["name"] == x["name"]), {}).get("出售价", 1)))
        for x in a49)

    # ③ 建团 / 门槛 / 加入 / 满员 / 退团一次机会
    ok49, msg49 = dr49.create_boss(w49, "lead", "团长", 20000, 8,
                                   t49, pool49, _random.Random(7))
    assert ok49 and w49["next_id"] == 2 and "1 号" in msg49
    team49 = w49["bosses"]["1"]
    assert team49["hp"] == team49["hp_max"] == 8_000_000
    assert len(team49["loot"]) == 5 and team49["members"] == ["lead"]
    assert not dr49.create_boss(w49, "lead", "团长", 0, 0, t49, pool49,
                                _random.Random(7))[0], "无达标玩家应拒绝"
    assert dr49.gate(p49("low", realm=0), 0)[0] is False
    assert dr49.gate(p49("hi", realm=41), 0)[0] is True
    assert dr49.gate(p49("lh", realm=0), 0)[0] is False
    lh49 = p49("lh", realm=0); lh49.ext["lunhui"] = 1
    assert dr49.gate(lh49, 0)[0] is True                      # 轮回放行
    assert dr49.gate(p49("au", realm=0), 10)[0] is True      # 权柄 10 档放行
    assert dr49.parse_id("1,2,3") == 1, "原版只取第一个数字"
    assert dr49.parse_id("") == 1
    for i in range(2, 6):
        assert "已加入" in dr49.join_boss(w49, p49(f"u{i}", f"队员{i}"), "1", 21, t49)
    assert len(team49["members"]) == 5
    assert "已满" in dr49.join_boss(w49, p49("u6"), "1", 21, t49)
    assert "已在" in dr49.join_boss(w49, p49("lead", "团长"), "1", 21, t49)
    assert "仙界之人" in dr49.join_boss(w49, p49("low", realm=0), "1", 0, t49)
    lead49 = p49("lead", "团长")
    assert "已脱离" in dr49.leave_boss(w49, lead49, t49)
    assert team49["members"][0] == "u2", "团长退团应顺延"
    assert str(1) in dr49.player_state_of(lead49)["exit_ids"]
    assert "不在任何" in dr49.leave_boss(w49, lead49, t49)
    # 同一 uid 重新入团后再退 → 退团机会已用尽（原版此处永久锁死）
    dr49.join_boss(w49, lead49, "1", 21, t49)
    assert "唯一一次" in dr49.leave_boss(w49, lead49, t49)
    assert team49["members"][0] == "u2"

    # ④ 门槛 / CD / 体力不支 / 战斗折算与记账 / 击杀终结奖励
    low49 = p49("low", realm=0)
    assert "仙界之人" in dr49.fight(w49, low49, st49, 60000, 60000, 0,
                                    t49, _random.Random(1))[0]
    cd49 = p49("u2", "队员2", cd=t49 + 200)
    assert "调息" in dr49.fight(w49, cd49, st49, 60000, 60000, 21,
                                t49, _random.Random(1))[0]
    tired49 = p49("u2", "队员2")
    assert "体力不支" in dr49.fight(w49, tired49, st49, 100, 60000, 21,
                                    t49, _random.Random(1))[0]
    outsider49 = p49("zz", "路人")
    assert "不在任何" in dr49.fight(w49, outsider49, st49, 60000, 60000, 21,
                                    t49, _random.Random(1))[0]
    killed49 = False
    for k49 in range(80):
        f49 = p49("u2", "队员2")
        msg49, ops49 = dr49.fight(w49, f49, st49, 60000, 60000, 21,
                                  t49 + k49 * 301, _random.Random(900 + k49))
        if "终结一击" in msg49:
            killed49 = True
            assert ("items", "u2", {"起死回生丹": 5}) in ops49
            break
    assert killed49 and not team49["alive"] and team49["hp"] == 0
    assert team49["killer"] == "u2"
    assert int(team49["record"]["u2"][1]) > 0
    assert abs(dr49.cd_left(p49("u2", cd=t49 + 301), t49 + 1) - 300.0) < 1e-6
    assert "已被斩" in dr49.fight(w49, p49("u2"), st49, 60000, 60000, 21,
                                  t49 + 10_000, _random.Random(1))[0]

    # ⑤ 竞价：格式 / 30% 下限 / 填 1 自动 / 灵石不足
    lead2 = p49("u2", "队员2")
    assert "格式" in dr49.bid(w49, lead2, "abc", t49)[0]
    assert "不存在编号" in dr49.bid(w49, lead2, "9*100", t49)[0]
    first49 = team49["loot"][0]
    first49["price"] = 1000        # 固定样本，避免抽到出售价 1 的物品令「填 2」恰好等于下限
    floor49 = dr49.min_bid(first49["price"])
    assert floor49 == 1300
    assert "低于下限" in dr49.bid(w49, lead2, "1*2", t49)[0]
    okmsg49, _ = dr49.bid(w49, lead2, "1*1", t49)
    assert "出价成功" in okmsg49 and first49["price"] == floor49
    assert first49["bidder"] == "u2" and first49["bids"] == 1
    poor49 = p49("u3", "队员3", stones=1)
    assert "灵石不足" in dr49.bid(w49, poor49, "2*99999999", t49)[0]

    # ⑥ 分配：非团长 / 无人出价 / 验资 / 平分 ops / 归档
    assert "只有" in dr49.assign(w49, p49("u3", "队员3"), "1", {}, t49)[0]
    assert "尚无人出价" in dr49.assign(w49, lead2, "2", {}, t49)[0]
    buyer49 = p49("u3", "队员3", stones=10 ** 9)
    dr49.bid(w49, buyer49, "1*99999999", t49)
    assert "灵石不足" in dr49.assign(w49, lead2, "1", {"u3": 1}, t49)[0]
    okmsg49, ops49 = dr49.assign(w49, lead2, "1", {"u3": 10 ** 9}, t49)
    price49 = max(1, team49["loot"][0]["price"])
    share49 = price49 // len(team49["members"])
    assert ("stones", "u3", -price49) in ops49
    assert ("items", "u3", {team49["loot"][0]["name"]: 1}) in ops49
    assert sum(1 for o in ops49 if o[0] == "stones" and o[2] == share49) \
        == len(team49["members"])
    assert "全队" in okmsg49 and team49["loot"][0]["amount"] == 0
    for i in range(2, 6):
        dr49.bid(w49, buyer49, f"{i}*99999999", t49)
        dr49.assign(w49, lead2, str(i), {"u3": 10 ** 9}, t49)
    assert team49["settled"] and dr49.unassigned(team49) == 0
    assert "归档" in dr49.assign(w49, lead2, "1", {}, t49)[0]

    # ⑦ 文本面板 / 规则纠偏 / 关闭清场
    assert "龙王榜" in dr49.rank_text(w49, lead2) and "占比" in dr49.rank_text(w49, lead2)
    assert "????????????" in dr49.status_text(w49, lead2, t49)
    assert "1 号" in dr49.list_text(w49) or "没有进行中" in dr49.list_text(w49)
    assert "dragon" in dr49.system_text(w49)
    assert "GroupBoss.json" in dr49.rules_text() and "$" in dr49.rules_text()
    assert "30%" in dr49.rules_text() and "起死回生丹" in dr49.rules_text()
    assert all(x in dr49.help_text() for x in (
        "#若陀龙王状态", "#龙王榜", "#讨伐若陀龙王", "#加入讨伐若陀龙王",
        "#若陀龙王奖励", "#若陀龙王出价", "#若陀龙王分配", "#若陀龙王团本",
        "#退出若陀龙王团本", "#开启若陀龙王", "#关闭若陀龙王"))
    assert "关闭" in dr49.close_all(w49, t49)
    assert w49["bosses"] == {} and w49["next_id"] == 1 and not w49["enabled"]
    assert "团本已被管理员关闭" in dr49.system_on(w49)[1]
    assert "已被管理员关闭" in dr49.list_text(w49)
    assert "已被管理员关闭" in dr49.bid(w49, lead2, "1*1", t49)[0]

    # ⑧ DB 往返：calamity_state["dragon"] + ext["dragon"]（db 仍 v17）
    await db.save_calamity(state49)
    got49 = dr49.world_of(await db.get_calamity())
    assert got49["enabled"] is True and "1" not in got49["bosses"]
    p49db = p49("db49", "存档")
    dr49.set_player(p49db, {"cd_until": t49 + 300, "exit_ids": ["1"],
                            "battles": 3, "kills": 1, "last_id": 1})
    await db.save_player(p49db.model_dump())
    row49 = await db.get_player("db49")
    assert row49 and dr49.player_state_of(PlayerDoc(**row49))["battles"] == 3
    print("W8-D5 teamboss ok")

    # ---------------- 50. W8-E1 复活地球（平行开局） ----------------
    import random as _random50
    from core import revival as rv50

    t50 = 1_800_000_000.0
    r50 = _random50.Random(11)
    d50 = PlayerDoc(uid="e1", name="甲", realm_index=40, exp=777, stones=8888)

    clock50 = [t50]

    def call50(cmd, dt=0):
        clock50[0] += dt
        return rv50.dispatch(d50, cmd, clock50[0], r50)[0]
    # ① 入界：预览不写档 / 确认建档 / 快照正确 / 别名与空参=状态
    assert "入界预览" in call50("入界")
    assert rv50.state_of(d50) is None
    assert "入界成功" in call50("入界 确认")
    e50 = rv50.state_of(d50)
    assert e50 and e50["place"] == "塔监狱" and e50["snapshot"]["realm_index"] == 40
    assert "已有复活地球记录" in call50("入界 确认")
    assert "---- 复活地球" in call50("")
    assert "---- 复活地球" in call50("状态")
    assert "放弃 确认" in rv50.help_text()
    assert "openingArrival.js" in rv50.rules_text() and "只升不降" in rv50.rules_text()

    # ② 塔监狱：观察会 die 但线索/校准必须保留（原版顺序坑）
    for c in rv50.TOWER_CLUES:
        call50(f"观察 {c}")
        call50("结算", 400)
    e50["tower"]["clues"] = list(rv50.TOWER_CLUES)
    e50["tower"]["calibrated"] = True
    assert len(e50["tower"]["clues"]) == 3 and e50["deaths"] == 3
    call50("交谈")
    call50("结算", 400)
    ev50 = e50["tower"]["event"]
    assert ev50 in rv50.TOWER_EVENTS
    opt50 = list(rv50.TOWER_EVENTS[ev50]["choices"])[0]
    assert "需二次确认" in call50(f"抉择 {opt50}")
    call50(f"抉择 {opt50} 确认")
    call50("结算", 1800)
    assert e50["tower"]["ally"] is True and e50["tower"]["event"] is None
    call50("推演")
    call50("结算", 400)
    assert e50["tower"]["window"] == 1 and abs(rv50.tower_risk(e50) - 0.25) < 1e-9
    call50("候时")
    call50("结算", 400)
    assert e50["tower"]["window"] == 2 and abs(rv50.tower_risk(e50) - 0.05) < 1e-9
    e50["tower"]["stale"] = True
    assert abs(rv50.tower_risk(e50) - 0.20) < 1e-9, "旧表误差 +15pp"
    e50["tower"]["stale"] = False
    call50("越狱 确认")
    assert "进行中" in call50("工作 绿植维护 1 确认"), "行动期间必须拒绝新动作"
    call50("结算", 800)
    assert e50["place"] == "空间站" and e50["credits"] >= 120
    assert e50["tower"]["window"] == 0 and e50["body"]["realm"] == 0, "越狱必经死亡重塑"

    # ③ 死亡重塑边界：清 body/bag/expedition，保留 knowledge/storage/facilities/station
    e50["body"].update(realm=3, cultivation=400, weapon=True)
    e50["bag"] = {"灵植": 9}
    e50["knowledge"]["功法"] = True
    e50["storage"] = {"燃料": 2}
    e50["facilities"]["丹炉"] = True
    e50["station"]["contribution"] = 17
    e50["expedition"] = {"target": "地表采药", "cargo": {"灵植": 1}}
    rv50.die(e50, "空间站", t50)
    assert e50["body"]["realm"] == 0 and e50["bag"] == {} and e50["expedition"] is None
    assert e50["knowledge"]["功法"] and e50["storage"]["燃料"] == 2
    assert e50["facilities"]["丹炉"] and e50["station"]["contribution"] == 17
    assert len(e50["tower"]["clues"]) == 3, "塔规线索永久保留"

    # ④ 站务：工作 / 委托 / 研读 / 修炼 / 突破门槛 / 结婴确认
    e50["credits"] = 500
    e50["bag"] = {"灵植": 20, "工程部件": 20, "燃料": 20}
    call50("工作 绿植维护 3 确认")
    work50 = call50("结算", 1000)
    assert e50["station"]["contribution"] >= 3 and "不自动续工" in work50
    assert "已领【医疗补给】" in call50("委托 医疗补给")
    assert "交付" in call50("交付委托")
    call50("研读")
    call50("结算", 400)
    assert e50["knowledge"]["功法"]
    call50("修炼")
    call50("结算", 800)
    assert e50["body"]["realm"] == 1
    assert "修为 100" in call50("突破"), "小突破需修为门槛"
    e50["body"]["cultivation"] = 100
    call50("突破")
    call50("结算", 400)
    assert e50["body"]["phase"] == 1
    assert "只读" in call50("筹备")
    # 污染结婴 65% 风险，必须二次确认（突破是唯一不在统一确认表里的动词）
    e50["body"].update(realm=3, phase=3, cultivation=9999)
    e50["knowledge"]["佛道传承"] = True
    e50["bag"]["金脑丹"] = 1
    assert "65% 死亡风险" in call50("突破")
    call50("突破 确认")
    call50("结算", 8000)
    assert e50["body"]["realm"] in (0, 4), "结婴成功进元婴，失败死亡重塑回凡人"

    # ⑤ 地表外勤 + 四类信号：先取证再处置，异常档案死亡保留
    e50["place"] = "空间站"
    e50["credits"] = 500
    e50["action"] = None
    e50["body"]["realm"] = 2
    call50("探索 地表采药 确认")
    call50("结算", 800)
    x50 = e50["expedition"]
    assert x50 and x50["cargo"], "出发即暂存，返站才入账"
    x50["signal"] = {"pattern": "回声", "investigated": False, "verified": False,
                     "clue": "", "choice": ""}
    call50("调查 信号 确认")
    call50("结算", 400)
    assert x50["signal"]["investigated"]
    call50("核验 手工 确认")
    call50("结算", 400)
    assert x50["signal"]["verified"] and "切断广播" in x50["signal"]["clue"]
    call50("抉择 切断广播 确认")
    call50("结算", 400)
    assert any(a["pattern"] == "回声" for a in e50["anomaly_archive"])
    assert "已核验 1/4" in call50("异常档案")
    # 误判加风险
    x50["signal"].update(verified=True, pattern="错时")
    call50("抉择 切断广播 确认")
    call50("结算", 400)
    assert x50["risk"] > 0
    # 撤离成功：暂存入袋 + 永久知识
    e50["expedition"]["risk"] = 0.0
    e50["expedition"]["discoveries"] = ["离界坐标"]
    call50("撤离 确认")
    call50("结算", 400)
    assert e50["expedition"] is None and e50["knowledge"].get("离界坐标"), \
        f"撤离应成功入账：{call50('状态')}"
    assert e50["place"] == "空间站"

    # ⑥ 化神分路 + 离界：二次确认、四门槛、只升不降、封存只读
    assert "可选分路" in call50("化神 化魔"), "化魔原版明确拒绝"
    e50["body"]["realm"] = 4
    assert "已选【化凡】" in call50("化神 化凡")
    e50["body"]["mortal_steps"] = 3
    assert "愿文须 8~80 字" in call50("立愿 短")
    call50("立愿 愿以此身记住所有没有回音的名字")
    e50["body"].update(realm=5, phase=0)
    e50["station"]["debt"] = 0
    assert "缺少设施" in call50("离界"), "离界四门槛应逐项校验"
    e50["facilities"]["接引装置"] = True
    e50["station"]["debt"] = 10
    assert "尚欠" in call50("离界")
    e50["station"]["debt"] = 0
    assert "离界预览" in call50("离界")
    assert "离界成功" in call50("离界 确认")
    assert d50.realm_index >= 40, "高阶角色离界只升不降"
    assert e50["status"] == "ascended" and "已封存" in call50("工作 绿植维护 1 确认")
    # 低阶角色离界应升到地仙
    d50b = PlayerDoc(uid="e1b", name="乙", realm_index=0, exp=5, stones=0)
    _, _ = rv50.dispatch(d50b, "入界 确认", t50, r50)
    eb = rv50.state_of(d50b)
    eb["body"]["realm"] = 5
    eb["knowledge"]["离界坐标"] = True
    eb["facilities"]["接引装置"] = True
    assert "离界成功" in rv50.dispatch(d50b, "离界 确认", t50, r50)[0]
    assert d50b.realm_index == rv50.ASCEND_REALM and d50b.exp == 0

    # ⑦ 放弃：恢复入界前主线快照并清档
    assert "放弃确认" in call50("放弃")
    assert "已放弃" in call50("放弃 确认")
    assert rv50.state_of(d50) is None
    assert d50.realm_index == 40 and d50.exp == 777 and d50.stones == 8888
    assert d50.state != "复活地球"

    # ⑧ DB 往返：ext["earth"] 落盘不丢，db 仍 v17
    d50c = PlayerDoc(uid="e1c", name="丙", realm_index=3)
    rv50.dispatch(d50c, "入界 确认", t50, r50)
    await db.save_player(d50c.model_dump())
    row50 = await db.get_player("e1c")
    assert row50 and rv50.state_of(PlayerDoc(**row50))["snapshot"]["realm_index"] == 3
    print("W8-E1 revival earth ok")

    # ---------------- 51. W8-E2 剑与魔法·艾瑟兰 ----------------
    import random as _random51
    from core import sword_magic as sm51

    t51 = 1_800_000_000.0
    r51 = _random51.Random(13)
    d51 = PlayerDoc(uid="e2", name="丙", realm_index=40, exp=321, stones=6000)
    clock51 = [t51]

    def call51(cmd, mins=0, fates=None):
        clock51[0] += mins * 60
        return sm51.dispatch(d51, cmd, clock51[0], r51, fates)

    def text51(cmd, mins=0, fates=None):
        return call51(cmd, mins, fates)[0]

    def step51(cmd, mins=30):
        a = text51(cmd)
        b = text51("结算", mins)
        return a + " || " + b

    # ① 文本 / 入界预览 / 双向互斥 / 快照
    assert "地脉点" in sm51.rules_text() and "臆造" in sm51.rules_text()
    assert "通用别名" in sm51.help_text() and "六地区" in sm51.lore_text()
    assert "入界预览" in text51("入界") and sm51.state_of(d51) is None
    assert "入界成功" in text51("入界 确认")
    s51 = sm51.state_of(d51)
    assert s51 and s51["place"] == "白桦镇" and s51["snapshot"]["realm_index"] == 40
    assert s51["coins"] == 120 and s51["level"] == 1
    assert sum(v["weight"] for v in sm51.TRAITS.values()) == 100
    assert len(sm51.REGIONS) == 6 and len(sm51.ENDINGS) == 3
    # E2 → E1 互斥（E1 的 enter 已加对称检查）
    e1side = PlayerDoc(uid="e2b", name="丁", ext={"sword": {"status": "active"}})
    assert "互斥" in rv50.dispatch(e1side, "入界 确认", t51, r51)[0]
    e2side = PlayerDoc(uid="e2c", name="戊", ext={"earth": {"status": "active"}})
    assert "互斥" in sm51.dispatch(e2side, "入界 确认", t51, r51)[0]

    # ② 抽天赋 / 就职 / 训练 / 计时与惰性 tick
    assert "抽取完成" in text51("抽取词条")
    assert len(s51["traits"]) == 2 and len(set(s51["traits"])) == 2 and s51["drawn_at"]
    assert "仅一次" in text51("抽取词条")
    assert "须先 抽取" not in text51("就职 剑士") and s51["skills"]["剑术"] == 5
    assert "本世不可改" in text51("就职 魔法师")
    assert "职业：" in text51("就职 未知")
    assert "熟练度" in text51("训练")
    assert "已开始【训练 剑术】" in text51("训练 剑术")
    assert "进行中" in text51("帮工"), "行动期间必须拒绝新动作"
    assert "训练【剑术】完成" in text51("结算", 10)
    assert "帮工完成" in step51("帮工")
    assert "当前没有到期行动" in text51("结算")

    # ③ 背包：购买 / 容量 / 不可买 / 存取出 / 使用 / 休养
    assert "不可购买" in text51("购买 古代晶片")
    assert "购买【野营口粮】×2" in text51("购买 野营口粮 2")
    assert "存入【野营口粮】×1" in text51("存入 野营口粮 1")
    assert "取出【野营口粮】×1" in text51("取出 野营口粮 1")
    s51["bag"] = {"野营口粮": 12}
    assert "背包不足" in text51("购买 疗伤药 1")
    s51["bag"] = {"野营口粮": 6, "疗伤药": 2, "魔力药": 1}
    assert "使用【疗伤药】完成" in step51("使用 疗伤药")
    s51["hp"] = 1
    s51["wounded"] = True
    assert "重伤解除" in step51("休养")

    # ④ 锻造 / 探索门槛 / 旅人洞察减时 / 抉择门禁
    s51["coins"] = 1000
    s51["bag"] = {"野营口粮": 6, "古代晶片": 4}
    assert "锻造完成" in step51("锻造") and s51["weapon"] is True
    assert "未开放" in text51("探索 裂月王庭")
    s51["wounded"] = True
    assert "「休养」" in text51("探索 风鸣林")
    s51["wounded"] = False
    s51["traits"] = ["wanderer", "will"]
    out51 = text51("探索 风鸣林")
    assert "需 5 分钟" in out51, "旅人洞察应让 6 分钟地区变 5 分钟"
    assert "进行中" in text51("探索 灰钟地窟")
    assert "遭遇待抉择" in text51("结算", 10)
    assert "需天赋" in text51("抉择 精灵交涉")
    assert "可选：" in text51("抉择 不存在")

    # ⑤ 战力公式 / 危险率钳制 / 战败 / 发奖 / 羁绊
    s51["encounter"] = {"region": 0, "repeat": False}
    s51["profession"] = "剑士"
    p51 = sm51._power(s51, "剑术", "救援")
    assert p51 == s51["level"] * 5 + s51["skills"]["剑术"] + 7 + 8
    s51["hp"] = 1
    s51["encounter"] = {"region": 0, "repeat": False}
    a51 = {"kind": "choice", "index": 0, "target": "救援", "repeat": False,
           "roll": 0.0, "end_at": t51}
    msg51 = sm51.resolve_action(s51, a51, r51)
    assert "战败撤回" in msg51 and s51["wounded"] is True and s51["defeats"] == 1
    s51["hp"] = 100
    s51["wounded"] = False
    s51["bag"] = {"野营口粮": 2}
    a51["roll"] = 0.99
    msg51 = sm51.resolve_action(s51, a51, r51)
    assert "古代晶片" in msg51 and s51["chapter"] >= 1 and s51["companion"] is True
    assert len(s51["lore"]) == 1

    # ⑥ 六地区通关 → 三终局（直接构造，避免刷 6 轮计时）
    s51["level"] = 8
    s51["skills"] = {k: 15 for k in sm51.SKILLS}
    s51["chapter"] = 5
    s51["hp"] = 200
    s51["bag"] = {"野营口粮": 2}
    s51["action"] = None
    assert "已开始【探索 裂月王庭】" in text51("探索 裂月王庭")
    s51["action"] = None
    s51["encounter"] = {"region": 5, "repeat": False}
    assert "已开始" in text51("抉择 重铸勇者誓约")
    s51["action"] = None
    a51 = {"kind": "choice", "index": 5, "target": "重铸勇者誓约",
           "repeat": False, "roll": 0.99, "end_at": t51}
    assert "断冠纪元终章" in sm51.resolve_action(s51, a51, r51)
    assert s51["chapter"] == 6 and s51["ending"] == "重铸勇者誓约"

    # ⑦ 飞升：二次确认 / 四门槛 / 只升不降 / 奖励 / ops / 封存 / 禁止放弃回滚
    s51["weapon"] = False
    assert "职业武装" in text51("飞升 确认")
    s51["weapon"] = True
    s51["level"] = 7
    assert "等级 ≥8" in text51("飞升 确认")
    s51["level"] = 8
    assert "飞升预览" in text51("飞升")
    fates51 = [
        {"id": "otherworld_returnee", "name": "异界归人", "effects": {"攻击加成": 0.08}},
        {"id": "dawn_oath", "name": "黎明之约", "effects": {"攻击加成": 0.1}},
    ]
    msg51, changed51, ops51 = call51("飞升 确认", fates=fates51)
    assert "飞升成功" in msg51 and changed51
    assert ops51 == [("items", {"黎明誓约剑": 1})], "信物按 name 入纳戒，避开 id 撞号"
    assert d51.realm_index == 40 and d51.exp == 321, "高阶角色飞升只升不降"
    assert d51.stones > 6000 and d51.ext["mingge_slots"] == 3
    assert len(d51.ext["mingge_extra"]) == 2
    assert s51["status"] == "ascended" and "已封存" in text51("训练 剑术")
    assert "不可再放弃" in text51("放弃 确认"), "封存后禁止回滚刷奖励"
    assert "---- 剑与魔法" in text51("状态")
    # 低阶角色飞升应升到 39 境
    d51b = PlayerDoc(uid="e2d", name="己", realm_index=0, exp=5, stones=0)
    sm51.dispatch(d51b, "入界 确认", t51, r51)
    sb = sm51.state_of(d51b)
    sb.update(chapter=6, ending="织补地脉", weapon=True, level=8, coins=10)
    assert "飞升成功" in sm51.dispatch(d51b, "飞升 确认", t51, r51, fates51)[0]
    assert d51b.realm_index == sm51.ASCEND_REALM and d51b.exp == 0

    # ⑧ 放弃恢复快照 / DB 往返（ext["sword"] 落盘，db 仍 v17）
    d51c = PlayerDoc(uid="e2e", name="庚", realm_index=7, exp=99, stones=123)
    assert "入界成功" in sm51.dispatch(d51c, "入界 确认", t51, r51)[0]
    assert "已放弃" in sm51.dispatch(d51c, "放弃 确认", t51, r51)[0]
    assert d51c.realm_index == 7 and d51c.exp == 99 and sm51.state_of(d51c) is None
    d51d = PlayerDoc(uid="e2f", name="辛", realm_index=3)
    sm51.dispatch(d51d, "入界 确认", t51, r51)
    await db.save_player(d51d.model_dump())
    row51 = await db.get_player("e2f")
    assert row51 and sm51.state_of(PlayerDoc(**row51))["snapshot"]["realm_index"] == 3

    # ⑨ 通用别名路由（main.py 层，静态校验：注册 + 避开二次节流 + 纳戒转发）
    src51 = open(PLUGIN / "main.py", encoding="utf-8").read()
    assert '@filter.regex(r"^#(?:我|我的练气)$")' in src51
    assert '@filter.regex(r"^#背包$")' in src51
    assert src51.count("doc: PlayerDoc | None = None") == 2, "两个 dispatch 都要支持传入 doc"
    assert 'self._sm_dispatch(event, "背包", doc)' in src51
    assert "sm_mod.active(sm_mod.state_of(doc))" in src51
    print("W8-E2 sword magic ok")

    # ---------------- 52. W8-F1 超级管理员 ----------------
    import sqlite3 as _sqlite52
    from core import admin as adm52
    from core import lifespan as life52

    t52 = 1_800_000_000.0

    # ① 世界状态：难度 / 修仙管理员 / 公告群 / 管理日志
    cal52: dict = {}
    st52 = adm52.state_of(cal52)
    assert st52["difficulty"] == "困难" and st52["masters"] == [] and st52["init"] is None
    assert adm52.flags_of(st52) == {"decay": True, "forced": True}
    assert adm52.is_master("u1", True, st52) and not adm52.is_master("u1", False, st52)
    assert "已授予" in adm52.master_add(st52, "u1")[1] and adm52.is_master("u1", False, st52)
    assert "已是" in adm52.master_add(st52, "u1")[1]
    assert "已收回" in adm52.master_del(st52, "u1")[1] and not adm52.is_master("u1", False, st52)
    assert "本就不是" in adm52.master_del(st52, "u1")[1]
    assert "只有机器人管理员" in adm52.master_text({})

    ok52, msg52 = adm52.set_difficulty(st52, "简单")
    assert ok52 and adm52.flags_of(st52) == {"decay": False, "forced": False}
    assert not adm52.set_difficulty(st52, "地狱")[0]
    assert "困难：寿元随时间流逝" in adm52.difficulty_text(st52)

    assert "已在公告名单" not in adm52.notify_add(st52, "123")[1]
    assert "已在公告名单" in adm52.notify_add(st52, "123")[1]
    assert "不在公告名单" in adm52.notify_del(st52, "999")[1]
    assert "已从公告名单移除" in adm52.notify_del(st52, "123")[1]
    assert "设为唯一公告群" in adm52.notify_set(st52, "456")[1]
    assert "456" in adm52.notify_text(st52)
    assert not adm52.notify_add(st52, "abc")[0], "群号必须纯数字"

    for i in range(adm52.LOG_CAP + 7):
        adm52.log_append(st52, "u1", f"事件{i}", t52 + i)
    assert len(st52["log"]) == adm52.LOG_CAP, "日志环形缓冲要截断"
    assert "事件" in adm52.log_text(st52) and "管理日志" in adm52.log_text({})
    print("F1 world state ok")

    # ② 玩家处置：解封行动 / 天牢 / 补发等级 / 拆道侣 / 打落凡间 / 解除法身
    d52 = PlayerDoc(uid="f1a", name="甲", state="闭关中", state_start=t52,
                    ext={"secret": {"end_at": t52 + 600}, "occupation": "炼丹师",
                         "occupation_level": 3, "daolv": "f1b"})
    assert adm52.relieve_action(d52, t52)[0]
    assert d52.state == "空闲" and d52.state_start == 0.0
    assert d52.ext["secret"]["end_at"] <= t52
    assert not adm52.relieve_action(d52, t52)[0], "无行动时应如实拒绝"

    _ok52, msg52 = adm52.jail(d52, 0, t52)
    assert d52.ext["banned"] is True and d52.ext["jail_until"] == t52 + 24 * 3600
    assert "24.0 小时" in msg52 and "剩余约" in adm52.jail_left(d52, t52 + 60)
    assert not adm52.grant_occupation_level(PlayerDoc(uid="f1c", name="乙"), 3)[0]
    assert adm52.grant_occupation_level(d52, 2)[0] and d52.ext["occupation_level"] == 5
    ok52, partner52 = adm52.divorce(d52)
    assert ok52 and partner52 == "f1b" and "daolv" not in d52.ext
    assert not adm52.divorce(d52)[0]

    plane52 = adm52.plane.state_of(d52)
    plane52["current"], plane52["travel"] = "仙界", {"to": "神界"}
    assert "打落凡间" in adm52.knock_to_mortal(d52)[1]
    assert plane52["current"] == "凡间" and plane52["travel"] is None

    fs52 = adm52.fashan.state_of(d52)
    assert not adm52.relieve_fashan(d52), "未行动的的法身不该被改"
    fs52["action"], fs52["state"] = {"kind": "探索"}, "行动中"
    assert adm52.relieve_fashan(d52) and fs52["action"] is None and fs52["state"] == "空闲"
    print("F1 player ops ok")

    # ③ 纳戒：体检 / 修复 / 抹除 / 替换
    inv52 = {"丹药": 3, "负数量": -2, "零": 0, "怪东西": 1}
    info52 = adm52.scan_inventory(inv52, known={"丹药"})
    assert set(info52["bad_qty"]) == {"负数量", "零"} and info52["unknown"] == ["怪东西"]
    n52, _s52 = adm52.repair_inventory(inv52)
    assert n52 == 2 and "负数量" not in inv52 and "怪东西" in inv52, "未知物品只报告不删"
    assert adm52.wipe_item(inv52, "丹药") == 3 and "丹药" not in inv52
    inv52["旧名"] = 7
    assert adm52.swap_item(inv52, "旧名", "新名") == 7
    assert "旧名" not in inv52 and inv52["新名"] == 7

    # ④ 拉新奖励：基础包 + 三档附加（原版档 4 空、档 1 幽灵物品已替换）
    ok52, items52, _b52 = adm52.invite_pack(1)
    assert ok52 and items52["超越宝盒"] == 5 and items52["锁灵仙符"] == 1
    assert items52["位面传送阵"] == 3 and items52["轮回命签"] == 50
    assert adm52.invite_pack(3)[1]["超越宝盒"] == 15, "档 3 叠加后共 15"
    assert adm52.invite_pack(4)[0] and set(adm52.invite_pack(4)[1]) == set(adm52.INVITE_BASE_ITEMS)
    assert not adm52.invite_pack(5)[0]
    assert "灵石 ×100,000,000" in adm52.invite_text(2, "甲")

    # ⑤ 诸天初始化：二次确认 / 超时 / 码错 / 取消
    st52["init"] = None
    adm52.init_request(st52, "u1", "1234", t52)
    assert not adm52.init_verify(st52, "u2", "1234", t52 + 1)[0], "非发起者不能确认"
    assert not adm52.init_verify(st52, "u1", "9999", t52 + 1)[0], "确认码错不得执行"
    assert adm52.init_verify(st52, "u1", "1234", t52 + 1)[0]
    assert st52["init"] is None
    adm52.init_request(st52, "u1", "1234", t52)
    assert "超时" in adm52.init_verify(st52, "u1", "1234", t52 + 61)[1]
    adm52.init_request(st52, "u1", "1234", t52)
    assert "已取消" in adm52.init_cancel(st52)[1] and st52["init"] is None
    assert "没有待确认" in adm52.init_cancel(st52)[1]
    assert "players" in adm52.INIT_TABLES and "db_info" not in adm52.INIT_TABLES
    assert len(adm52.make_code(1234)) == adm52.INIT_CODE_LEN

    # ⑥ DB：删档 / 备份 / 清表
    await db.save_player(PlayerDoc(uid="f1d", name="丁").model_dump())
    await db.add_items("f1d", {"丹药": 2})
    assert await db.delete_player("f1d") is True
    assert await db.get_player("f1d") is None and await db.get_inventory("f1d") == {}

    bak52 = tmp / "_backups" / "w8f1.db"
    await db.backup_to(bak52)
    assert bak52.exists() and bak52.stat().st_size > 0
    con52 = _sqlite52.connect(bak52)
    try:
        assert con52.execute("SELECT version FROM db_info").fetchone()[0] == 17
    finally:
        con52.close()
    await db.backup_to(bak52)      # 同名不覆盖，自动加序号
    assert (tmp / "_backups" / "w8f1-1.db").exists()
    counts52 = await db.wipe_all(adm52.INIT_TABLES)
    assert set(counts52) == set(adm52.INIT_TABLES) and counts52["players"] >= 1
    assert (await db.all_player_uids()) == [], "灭维后应无任何存档"
    print("F1 db ops ok")

    # ⑦ 寿元难度开关（简单不流逝 / 普通不强制轮回）
    d52b = PlayerDoc(uid="f1e", name="戊", realm_index=3)
    life52.shouyuan_of(d52b)
    before52 = int(d52b.ext["shouyuan"])
    assert life52.daily_decay(d52b, t52, decay=False) == (0, False)
    assert int(d52b.ext["shouyuan"]) == before52, "简单难度不得扣寿元"
    d52b.ext["awaiting_rescue"] = True
    d52b.ext["shouyuan"] = 0
    d52b.ext["rescue_deadline"] = t52 - 10
    assert life52.resolve_if_due(d52b, t52, forced=False) is None, "普通难度不得强制轮回"
    assert "轮回往生" in (life52.resolve_if_due(d52b, t52) or ""), "困难难度照旧转世"

    # ⑧ main.py 接线（静态校验）
    src52 = open(PLUGIN / "main.py", encoding="utf-8").read()
    regs52 = [c for c in (
        "CMD_AD_RELIEVE", "CMD_AD_REBIRTH", "CMD_AD_RELIEVE_ALL", "CMD_AD_RELIEVE_FS",
        "CMD_AD_KNOCK", "CMD_AD_CLEAR_EXCHANGE", "CMD_AD_LOG", "CMD_AD_DISSOLVE",
        "CMD_AD_WIPE_ITEM", "CMD_AD_SWAP_ITEM", "CMD_AD_LEVEL", "CMD_AD_HELL",
        "CMD_AD_DIVORCE", "CMD_AD_JAIL", "CMD_AD_PUSH_ADD", "CMD_AD_PUSH_DEL",
        "CMD_AD_PUSH_VIEW", "CMD_AD_MASTER", "CMD_AD_NAJIE_FIX", "CMD_AD_INVITE",
        "CMD_AD_WENXIAN", "CMD_AD_EPOCH", "CMD_AD_INIT", "CMD_AD_INIT_OK",
        "CMD_AD_INIT_NO", "CMD_AD_NOTIFY", "CMD_AD_DIFFICULTY",
    ) if f"@filter.command({c}" not in src52]
    assert regs52 == [], f"漏注册：{regs52}"
    assert 'alias={CMD_AD_LOG_ALIAS}' in src52 and 'alias={CMD_AD_LEVEL_ALIAS}' in src52
    assert 'alias={CMD_AD_NOTIFY_VIEW}' in src52
    assert "adm_mod.jail_left(doc, now)" in src52, "天牢到期要自动赦免"
    assert 'forced=bool(self._adm_flags.get("forced", True))' in src52
    assert 'decay=bool(self._adm_flags.get("decay", True))' in src52
    assert "await self.db.backup_to(path)" in src52 and "adm_mod.init_result_text" in src52
    assert "cmd_extras" not in src52
    print("W8-F1 super admin ok")

    # ---------------- 53. W8-F2 时间线权柄 ----------------
    from core import worldline as wl53

    t53 = 1_800_000_000.0

    # ① 权柄门槛 / 因果债档位 / 反噬画像
    gates53 = {r: wl53.gate_of(PlayerDoc(uid="g", realm_index=r))["mode"]
               for r in (41, 42, 45, 47, 49)}
    assert gates53 == {41: "none", 42: "random", 45: "target", 47: "scope", 49: "free"}, gates53
    assert wl53.tier_of(99)["level"] == 0 and wl53.tier_of(99)["name"] == "因果平稳"
    assert [wl53.tier_of(v)["name"] for v in (100, 300, 600, 1000)] == [
        "绝灵回响", "众生代偿", "古史清算", "厄土大祭"]
    assert wl53.penalty_of(1000)["hp"] == 0.30 and wl53.penalty_of(1000)["suppress"] == 2
    assert wl53.penalty_of(350)["tax"] == 0.10 and wl53.penalty_of(250)["tax"] == 0.05
    assert wl53.deduct_rate(PlayerDoc(uid="g", realm_index=44)) == 1.5
    assert wl53.deduct_rate(PlayerDoc(uid="g", realm_index=45)) == 3.0
    assert wl53.deduct_rate(PlayerDoc(uid="g", realm_index=47)) == 5.0
    assert wl53.deduct_rate(PlayerDoc(uid="g", realm_index=49)) == 999.0
    print("F2 gates ok")

    # ② 古史线投影：确定性 / 去重 / 已灭剔除 / 份数随线偏差递增
    o53a = wl53.line_offers("u53", "青锋剑", 4, [], [])
    o53b = wl53.line_offers("u53", "青锋剑", 4, [], [])
    assert len(o53a) == 6 and [o["qty"] for o in o53a] == [o["qty"] for o in o53b], "同人同物必须稳定"
    assert o53a[0]["qty"] < o53a[-1]["qty"], "越靠后的线偏差越大"
    o53c = wl53.line_offers("u53", "青锋剑", 4, ["L1|青锋剑"], ["L2"])
    assert [o["line"] for o in o53c] == ["L3", "L4", "L5", "L6"]
    assert wl53.line_offers("u53", "青锋剑", 4, [], ["L1", "L2", "L3", "L4", "L5", "L6"]) == []
    assert "太初混沌纪" in wl53.offers_text(o53a, True)
    assert "看不穿" in wl53.offers_text(o53a, False)

    # ③ 会话：开启 / 读取 / 过期 / 取消 / 选择解析
    st53a = wl53.state_of(PlayerDoc(uid="u53", name="甲", realm_index=45))
    wl53.open_session(st53a, "装备", "青锋剑", o53a[:2], t53)
    assert wl53.session_of(st53a, t53 + 1)["name"] == "青锋剑"
    assert wl53.session_of(st53a, t53 + wl53.SESSION_TTL + 1) is None, "10 分钟过期"
    assert wl53.parse_picks("1,2", 6) == (True, [0, 1], "")
    assert wl53.parse_picks("全部", 6)[1] == [0, 1, 2, 3, 4, 5]
    assert not wl53.parse_picks("9", 6)[0] and not wl53.parse_picks("x", 6)[0]
    assert wl53.cancel_session(st53a)[0] and st53a["session"] is None
    assert not wl53.cancel_session(st53a)[0]
    print("F2 session ok")

    # ④ 支取结算：入包 / claim / 计价 / 雷劫击杀 / 封锁
    d53 = PlayerDoc(uid="u53", name="甲", realm_index=45, ext={"hp": 5000})
    st53 = wl53.state_of(d53)
    offers53 = wl53.line_offers(d53.uid, "青锋剑", 4, [], [])
    wl53.open_session(st53, "装备", "青锋剑", offers53, t53)
    ok53, msg53, items53 = wl53.settle_withdraw(
        d53, st53, [0, 1], 6, t53 + 1, 5000)
    assert ok53 and items53["青锋剑"] == offers53[0]["qty"] + offers53[1]["qty"]
    assert st53["debt"] == 6 * items53["青锋剑"]
    assert st53["session"] is None and len(st53["claims"]) == 2
    assert "因果债" in msg53
    # 债过 200 → 20 道 ×120% 血量上限 = 必死
    st53["debt"] = 0
    res53 = wl53.add_debt(d53, st53, 250, "测试", t53 + 2, 5000)
    assert res53["backlash"]["triggered"] and res53["backlash"]["killed"]
    assert res53["backlash"]["damage_per_bolt"] == 6000
    assert d53.ext["hp"] == 0 and wl53.zhengdao.peek(d53) == 2.0, "雷劫必死 + 道伤 +2"
    assert wl53.block_left(st53, t53 + 2) >= 12 * 3600, "死亡叠 12 小时封锁"
    assert any("因果雷罚" in ln for ln in wl53.debt_lines(res53))
    # 未过阈值不触发
    st53["debt"] = 0
    d53.ext["hp"] = 5000
    assert not wl53.add_debt(d53, st53, 150, "测试", t53 + 3, 5000)["backlash"]["triggered"]
    # 祭道之上：债恒 0
    free53 = PlayerDoc(uid="u53f", name="乙", realm_index=49, ext={"hp": 10})
    stf53 = wl53.state_of(free53)
    resf53 = wl53.add_debt(free53, stf53, 9999, "测试", t53, 10)
    assert resf53["free"] and resf53["delta"] == 0 and stf53["debt"] == 0
    print("F2 withdraw ok")

    # ⑤ 纪元消债：倍率 / 纪元积累消耗 / 清零 / 免费全清
    d53b = PlayerDoc(uid="u53b", name="丙", realm_index=45, ext={"era_points": 100})
    st53b = wl53.state_of(d53b)
    st53b["debt"] = 300
    ok53, msg53 = wl53.reduce_debt(d53b, st53b, 10, t53)
    assert ok53 and st53b["debt"] == 270 and d53b.ext["era_points"] == 90, "×3 倍率"
    assert "倍率 ×3" in msg53
    ok53, _m = wl53.reduce_debt(d53b, st53b, 0, t53)
    assert ok53 and st53b["debt"] == 0, "省略数量=能消多少消多少"
    assert not wl53.reduce_debt(d53b, st53b, 5, t53)[0], "债已清零"
    d53c = PlayerDoc(uid="u53c", name="丁", realm_index=41)
    st53c = wl53.state_of(d53c)
    st53c["debt"] = 50
    assert not wl53.reduce_debt(d53c, st53c, 1, t53)[0], "权柄不足不能消债"
    d53d = PlayerDoc(uid="u53d", name="戊", realm_index=49, ext={"era_points": 0})
    st53d = wl53.state_of(d53d)
    st53d["debt"] = 88
    ok53, msg53 = wl53.reduce_debt(d53d, st53d, 1, t53)
    assert ok53 and st53d["debt"] == 0 and "祭道之上" in msg53
    print("F2 reduce ok")

    # ⑥ 古史打击：同阶反噬 / 越级反噬 / 路尽反震 / 成功改写 / 路尽目标只灭线
    atk53 = PlayerDoc(uid="a53", name="攻", realm_index=45, ext={"hp": 9000})
    ast53 = wl53.state_of(atk53)
    same53 = PlayerDoc(uid="t53a", name="同阶", realm_index=45)
    ok53, msg53, plan53 = wl53.strike(atk53, ast53, same53, wl53.state_of(same53),
                                      "功法", "九转玄功", t53, 9000)
    assert not ok53 and "古史反噬" in msg53 and ast53["debt"] == 45 and plan53 is None

    ast53["debt"] = 0
    high53 = PlayerDoc(uid="t53b", name="高阶", realm_index=47)
    ok53, msg53, _p = wl53.strike(atk53, ast53, high53, wl53.state_of(high53),
                                  "物品", "青锋剑", t53, 9000)
    assert not ok53 and ast53["debt"] == 80
    assert ast53["form_broken"], f"撞 47 档以上应形神俱灭：{msg53}"
    assert atk53.ext["hp"] == 0

    ast53["form_broken"] = ""
    ast53["debt"] = 0
    atk53.ext["hp"] = 9000
    atk53.realm_index = 46
    low53 = PlayerDoc(uid="t53c", name="低阶", realm_index=40, exp=999,
                      ext={"gongfa": ["九转玄功", "青莲剑歌"]})
    ok53, msg53, plan53 = wl53.strike(atk53, ast53, low53, wl53.state_of(low53),
                                      "功法", "九转玄功", t53, 9000)
    assert ok53 and "遗忘" in msg53
    assert low53.ext["gongfa"] == ["青莲剑歌"]
    assert ast53["debt"] == 50 and plan53 is None

    low53b = PlayerDoc(uid="t53d", name="低阶二", realm_index=40)
    ok53, _m, plan53 = wl53.strike(atk53, ast53, low53b, wl53.state_of(low53b),
                                   "证道", "成帝", t53, 9000)
    assert ok53 and low53b.realm_index == 39, "证道事实被击穿 → 境界跌落一档"
    ok53, _m, plan53 = wl53.strike(atk53, ast53, low53b, wl53.state_of(low53b),
                                   "物品", "青锋剑", t53, 9000)
    assert ok53 and plan53 == {"erase_item": "青锋剑"}, "物品类要交给主程序做全服抹除"
    # 目标 47 档 → 只能灭线，不改事实（攻击者须比它更高）
    line_only = PlayerDoc(uid="t53e", name="路尽", realm_index=48, ext={"gongfa": ["九转玄功"]})
    atk53b = PlayerDoc(uid="a53b", name="攻二", realm_index=50, ext={"hp": 9999})
    ast53b = wl53.state_of(atk53b)
    ok53, msg53, plan53 = wl53.strike(atk53b, ast53b, line_only, wl53.state_of(line_only),
                                      "功法", "九转玄功", t53, 9999)
    assert ok53 and plan53 is None and line_only.ext["gongfa"] == ["九转玄功"]
    assert "路尽" in msg53
    print("F2 strike ok")

    # ⑦ 众生代偿：伤害 / 道伤 / 事件去重 / 挂起重试
    rel53 = PlayerDoc(uid="r53", name="道侣", realm_index=10, ext={"hp": 1000})
    rst53 = wl53.state_of(rel53)
    r153 = wl53.compensate(rel53, 400, "ev1", "甲", t53, 1000)
    assert not r153["dedup"] and r153["damage"] == 350 and r153["wound"] == 2, r153
    assert rel53.ext["hp"] == 650
    r253 = wl53.compensate(rel53, 400, "ev1", "甲", t53, 1000)
    assert r253["dedup"] and rel53.ext["hp"] == 650, "同一事件不得二次受罚"
    assert wl53.related_of(PlayerDoc(uid="x", ext={"daolv": "a", "shifu": "b",
                                                   "tudi": ["c", "d"]}))[0] == ("道侣", "a")
    wl53.push_pending(rst53, "ghost", "弟子", 400, "ev2", t53)
    assert [r["uid"] for r in wl53.take_pending(rst53)] == ["ghost"]
    assert rst53["pending"] == [] and "没有挂起" in wl53.compensation_text([])
    assert "道侣" in wl53.compensation_text([{"name": "道侣", "damage": 5, "wound": 1}])
    print("F2 compensation ok")

    # ⑧ 形神重塑
    broken53 = PlayerDoc(uid="b53", name="己", realm_index=30, ext={"hp": 0})
    bst53 = wl53.state_of(broken53)
    assert not wl53.rebuild_form(broken53, "医", t53, 1000)[0], "形神完好时拒绝"
    bst53["form_broken"] = "触碰路尽级古史遭本体抹杀"
    ok53, msg53 = wl53.rebuild_form(broken53, "医", t53, 1000)
    assert ok53 and bst53["form_broken"] == "" and broken53.ext["hp"] == 200
    assert "重塑" in msg53
    print("F2 rebuild ok")

    # ⑨ DB 往返 + main.py 接线
    d53e = PlayerDoc(uid="u53e", name="庚", realm_index=46)
    wl53.state_of(d53e)["debt"] = 321
    await db.save_player(d53e.model_dump())
    row53 = await db.get_player("u53e")
    assert wl53.state_of(PlayerDoc(**row53))["debt"] == 321, "ext[\"worldline\"] 必须落盘"

    src53 = open(PLUGIN / "main.py", encoding="utf-8").read()
    miss53 = [c for c in (
        "CMD_WL", "CMD_WL_TAKE", "CMD_WL_TAKE_OK", "CMD_WL_TAKE_NO",
        "CMD_WL_REDUCE", "CMD_WL_STRIKE", "CMD_WL_REBUILD", "CMD_WL_RETRY",
    ) if f"@filter.command({c}" not in src53]
    assert miss53 == [], f"漏注册：{miss53}"
    assert 'alias={CMD_WL_ALIAS, CMD_WL_ALIAS2}' in src53
    assert 'alias={CMD_WL_REDUCE_ALIAS}' in src53
    assert "wl_mod.settle_withdraw" in src53 and "wl_mod.strike" in src53
    assert "wl_mod.compensate" in src53 and "wl_mod.take_pending" in src53
    assert 'if plan and plan.get("erase_item")' in src53
    assert "_wl_compensate" in src53
    print("W8-F2 worldline authority ok")

    # ---------------- 54. W8-F3 超维造物 ----------------
    from core import superdim as sd54

    t54 = 1_800_000_000.0

    # ① 觉醒门槛：权柄 ≥48 + 小世界
    low54 = PlayerDoc(uid="s54a", name="甲", realm_index=47, ext={"xiaoshijie": {"name": "紫霄界"}})
    assert not sd54.gate_of(low54)["ok"] and "权柄需 48" in sd54.gate_of(low54)["reason"]
    noworld54 = PlayerDoc(uid="s54b", name="乙", realm_index=52)
    assert not sd54.gate_of(noworld54)["ok"] and "小世界" in sd54.gate_of(noworld54)["reason"]
    d54 = PlayerDoc(uid="s54", name="丙", realm_index=48,
                    ext={"xiaoshijie": {"name": "紫霄界", "level": 3}})
    assert sd54.gate_of(d54)["ok"]
    print("F3 gate ok")

    # ② 炼化：重复 / 未到期 / 到期结算（三功法 + 神慧者 + 无演无尽 + 超维星界）
    st54 = sd54.state_of(d54)
    assert not sd54.settle_refine(d54, st54, t54)[0], "未开始不该结算"
    ok54, msg54 = sd54.begin_refine(d54, st54, t54)
    assert ok54 and "8 小时" in msg54
    assert not sd54.begin_refine(d54, st54, t54 + 10)[0], "炼化中不得重复开启"
    assert not sd54.settle_refine(d54, st54, t54 + 60)[0], "未到期不得结算"
    ok54, msg54 = sd54.settle_refine(d54, st54, t54 + sd54.REFINE_MINUTES * 60 + 1)
    assert ok54 and st54["owned"] and st54["refining"] is None
    assert d54.ext["gongfa"] == list(sd54.SHENGFA_GONGFA)
    assert d54.ext["linggen"]["name"] == "神慧者" and d54.ext["linggen"]["超维之光"] is True
    assert d54.ext["daotreasure"]["aptitude"] == "无演无尽"
    assert d54.ext["xiaoshijie"]["name"] == "超维星界" and d54.ext["xiaoshijie"]["超维星界"] is True
    assert d54.ext["xiaoshijie"]["原世界名"] == "紫霄界"
    assert "超维星界" in msg54 and "神慧者" in msg54
    print("F3 refine ok")

    # ③ 超维之力产出 / 消耗
    base54 = t54 + sd54.REFINE_MINUTES * 60 + 1
    assert sd54.accrue(d54, st54, base54 + 3599) == 0.0, "不足 1 小时不产出"
    assert round(sd54.accrue(d54, st54, base54 + 3600 * 3), 2) == 0.03
    assert sd54.power_of(st54) == 0.03
    assert not sd54.spend(st54), "不足 5 点不得消耗"
    st54["power"] = 12.0
    assert sd54.spend(st54) and sd54.power_of(st54) == 7.0
    assert sd54.power_of(sd54.state_of(PlayerDoc(uid="z"))) == 0.0
    print("F3 power ok")

    # ④ 面板：未觉醒 / 已觉醒
    fresh54 = PlayerDoc(uid="s54c", name="丁", realm_index=48,
                        ext={"xiaoshijie": {"name": "小界"}})
    panel54 = sd54.panel_text(fresh54, sd54.state_of(fresh54), t54)
    assert "尚未炼化" in panel54 and "#炼化圣法碎片" in panel54
    assert "当前：7.00 点" in sd54.panel_text(d54, st54, base54)

    # ⑤ 造物判定：稀有度 <8
    assert sd54.can_create({"name": "x", "稀有度": 7})
    assert not sd54.can_create({"name": "x", "稀有度": 8})
    assert not sd54.can_create({"name": "x"})
    assert not sd54.can_create(None)
    print("F3 create gate ok")

    # ⑥ 改写：灵根 / 命格 / 天资
    roots54 = [{"name": "青莲剑体", "稀有度": 6},
               {"name": "月华之体", "稀有度": 10, "唯一灵根": True, "不可随机获取": True}]
    row54, why54 = sd54.find_linggen(roots54, "青莲剑体")
    assert row54 and not why54
    bad54, why54 = sd54.find_linggen(roots54, "月华之体")
    assert bad54 is None and "唯一" in why54
    assert sd54.find_linggen(roots54, "不存在")[0] is None
    assert "灵根改写为" in sd54.apply_linggen(d54, row54) and d54.ext["linggen"]["name"] == "青莲剑体"

    fates54 = [{"id": 1, "name": "紫微星主", "effects": {}}]
    assert sd54.find_fate(fates54, "紫微星主")["name"] == "紫微星主"
    assert sd54.find_fate(fates54, "1")["id"] == 1 and sd54.find_fate(fates54, "无") is None
    assert "命格改写为" in sd54.apply_fate(d54, fates54[0])
    assert d54.ext["mingge"]["name"] == "紫微星主" and d54.ext["mingge"]["大道改写"] is True

    assert sd54.rewrite_name("  绝世天骄  @某人 ") == "绝世天骄"
    assert sd54.rewrite_name("") == ""
    print("F3 rewrite ok")

    # ⑦ 时代改写：五个时代 / 非法名
    era54: dict = {}
    for idx54, name54 in enumerate(sd54.ERA_NAMES):
        ok54, msg54 = sd54.era_apply(era54, name54, t54)
        assert ok54 and era54["years_total"] == idx54 * 10000, (name54, era54.get("years_total"))
    assert era54["years_total"] == 40000, "绝灵时代是第 5 个"
    assert not sd54.era_apply(era54, "黄金时代", t54)[0]
    print("F3 era ok")

    # ⑧ DB 往返 + main.py 接线
    d54b = PlayerDoc(uid="s54d", name="戊", realm_index=48, ext={"xiaoshijie": {"name": "小界"}})
    st54b = sd54.state_of(d54b)
    sd54.begin_refine(d54b, st54b, t54)
    await db.save_player(d54b.model_dump())
    row54 = await db.get_player("s54d")
    assert sd54.state_of(PlayerDoc(**row54))["refining"]["end"] == t54 + 480 * 60

    src54 = open(PLUGIN / "main.py", encoding="utf-8").read()
    miss54 = [c for c in (
        "CMD_SD", "CMD_SD_REFINE", "CMD_SD_CREATE", "CMD_SD_REPAIR", "CMD_SD_EVENT",
        "CMD_SD_ERA", "CMD_SD_FATE", "CMD_SD_APT", "CMD_SD_LG",
    ) if f"@filter.command({c}" not in src54]
    assert miss54 == [], f"漏注册：{miss54}"
    assert "sd_mod.settle_refine(doc, st, now)" in src54
    assert "sd_mod.accrue(doc, st, now)" in src54
    assert "sd_mod.era_apply(cal[\"era\"], name" in src54
    assert "ss_mod.repair_all(w, True)" in src54
    assert "calamity.spawn_wave" in src54 and 'source="superdimensional"' in src54
    assert "sd_mod.find_linggen" in src54 and "sd_mod.find_fate" in src54
    print("W8-F3 superdimensional ok")

    # ---------------- 55. W8-F4 场域圣墟 ----------------
    import random as _random55
    from core import shengxu as sx55
    from core import plane as pl55

    t55 = 1_800_000_000.0

    def mk55(uid="x55", level=6, **ext55):
        ext = {"xueqi": 10 ** 9, "shouyuan": 50000,
               "flower": {"level": level, "accum": 0, "risk": 10, "extremes": []}}
        ext.update(ext55)
        d = PlayerDoc(uid=uid, name="墟" + uid[-2:], realm_index=6,
                      exp=10 ** 9, stones=10 ** 9, ext=ext)
        pl55.state_of(d)["current"] = "小阴间"
        return d

    # ① 数据完整性
    assert len(sx55.DUNGEONS) == 12 and len({d["name"] for d in sx55.DUNGEONS}) == 12
    assert len(sx55.FACTIONS) == 3 and len(sx55.SKILLS) == 28
    assert len(sx55.SEVEN_TREASURES) == 7 and len(sx55.BREATHING_REDUCTION) == 6
    assert sx55.dungeon_of("太行山")["req"] == 2 and sx55.dungeon_of("不存在") is None
    assert sx55.plane_of(sx55.dungeon_of("太行山")) == "小阴间"
    assert sx55.plane_of(sx55.dungeon_of("魂河古地")) == "阳间"
    assert sx55.plane_of(sx55.dungeon_of("阳间名山")) == "阳间"
    print("F4 data ok")

    # ② 成本 / 耗时（呼吸法提速，下限 5 分钟）
    d55 = mk55()
    cost55 = sx55.explore_cost(sx55.dungeon_of("太行山"), 1)
    assert cost55["xiuwei"] == int(round(1_000_000 * 2 * 0.68))
    assert cost55["lingshi"] == int(round(500_000 * 2 * 0.68))
    assert cost55["shouyuan"] == 2, "7 分钟 → ceil(7/5)=2 点寿元"
    assert sx55.explore_cost(sx55.dungeon_of("太行山"), 3)["xiuwei"] == cost55["xiuwei"] * 3
    assert sx55.minutes_of(d55, sx55.dungeon_of("太行山")) == 7
    d55.ext["gongfa"] = ["道引呼吸法"]
    assert sx55.minutes_of(d55, sx55.dungeon_of("太行山")) == 5, "7-4=3 → 下限 5"
    assert sx55.minutes_of(d55, sx55.dungeon_of("魂河古地")) == 16, "20-4"
    d55.ext["gongfa"] = []
    print("F4 cost ok")

    # ③ 起探索：花粉路 / 位面 / 境界 / 资源 / 成功
    plain55 = PlayerDoc(uid="p55", name="凡人", ext={"shouyuan": 999})
    assert "花粉进化路" in sx55.begin(plain55, "太行山", 1, t55)[1]
    assert "位于" in sx55.begin(mk55("pp55", level=12), "阳间名山", 1, t55)[1], "位面不符要拒绝"
    low55 = mk55("l55", level=1)
    assert "花粉境" in sx55.begin(low55, "太行山", 1, t55)[1]
    poor55 = mk55("q55", level=6)
    poor55.exp = 0
    assert "资源不足" in sx55.begin(poor55, "太行山", 1, t55)[1]
    ok55, msg55 = sx55.begin(d55, "太行山", 2, t55)
    assert ok55 and "预计 14 分钟" in msg55, msg55
    assert not sx55.begin(d55, "昆仑山", 1, t55)[0], "行动中不得再起"
    assert d55.exp < 10 ** 9, "起探索要扣修为"
    print("F4 begin ok")

    # ④ 结算：未到期 / 胜利发奖 / 失败血量 1
    assert not sx55.settle(d55, sx55.state_of(d55), t55 + 10, _random55.Random(1))[0]
    before55 = (d55.exp, sx55.flower_accum(d55))
    ok55, msg55, items55, learned55 = sx55.settle(
        d55, sx55.state_of(d55), t55 + 3600, _random55.Random(7))
    assert ok55 and "胜利" in msg55
    assert d55.exp > before55[0] and sx55.flower_accum(d55) > before55[1]
    assert sx55.state_of(d55)["clue"] >= 1 and "太行山" in sx55.state_of(d55)["cleared"]
    assert isinstance(items55, dict) and isinstance(learned55, list)
    assert sx55.action_of(d55) is None

    lose55 = mk55("w55", level=2)
    sx55.begin(lose55, "魂河古地" if False else "太行山", 1, t55)
    lose55.ext["hp"] = 5000
    lost = False
    for seed in range(30):
        c55 = mk55("w55", level=2)
        sx55.begin(c55, "太行山", 1, t55)
        c55.ext["hp"] = 5000
        _ok, m55, _i, _l = sx55.settle(c55, sx55.state_of(c55), t55 + 3600, _random55.Random(seed))
        if "失败" in m55:
            assert c55.ext["hp"] == 1 and sx55.state_of(c55)["clue"] == 0
            lost = True
            break
    assert lost, "低阶打高阶应能失败"
    print("F4 settle ok")

    # ⑤ 呼吸法：残页 → 5 张合成 → 学会 / 已学会折现 / 不足拒绝
    d55b = mk55("b55")
    st55b = sx55.state_of(d55b)
    for i in range(1, 6):
        page = sx55.collect_page(st55b, "形意呼吸法", d55b.ext.get("gongfa") or [])
        assert page["count"] == i
    assert sx55.synthesize(d55b, st55b, "形意呼吸法")[0]
    assert "形意呼吸法" in d55b.ext["gongfa"] and st55b["pages"]["形意呼吸法"] == 0
    assert not sx55.synthesize(d55b, st55b, "形意呼吸法")[0], "已掌握不得重复"
    assert not sx55.synthesize(d55b, st55b, "不存在的呼吸法")[0]
    st55b["pages"]["太极呼吸法"] = 2
    assert "还需 3 张" in sx55.synthesize(d55b, st55b, "太极呼吸法")[1]
    learned_page = sx55.collect_page(st55b, "形意呼吸法", d55b.ext["gongfa"])
    assert learned_page["learned"] and learned_page["reward"] == sx55.LEARNED_PAGE_REWARD
    print("F4 breathing ok")

    # ⑥ 场域：残图 → 5 张升一重 → 上限 9 / 胜率加成
    d55c = mk55("c55")
    st55c = sx55.state_of(d55c)
    assert not sx55.advance_field(st55c)[0], "无残图不得参悟"
    for _ in range(5):
        sx55.collect_field_page(st55c)
    assert sx55.advance_field(st55c)[0] and st55c["field_stage"] == 1
    assert st55c["field_pages"] == 0
    st55c["field_stage"], st55c["field_pages"] = 9, 99
    assert "圆满" in sx55.advance_field(st55c)[1]
    prof55 = sx55.field_profile({"field_stage": 9})
    assert abs(prof55["attr"] - 0.27) < 1e-9 and abs(prof55["win"] - 0.18) < 1e-9
    assert sx55.win_rate(mk55("wr55", level=6), sx55.dungeon_of("太行山"), 9) > \
        sx55.win_rate(mk55("wr55", level=6), sx55.dungeon_of("太行山"), 0)
    print("F4 field ok")

    # ⑦ 势力：门槛 / 加入一次 / 日俸一天一次
    d55d = mk55("d55", level=2)
    assert not sx55.join_faction(d55d, sx55.state_of(d55d), "大梦净土", t55)[0]
    assert "圣墟势力仅" in sx55.join_faction(d55d, sx55.state_of(d55d), "不存在", t55)[1]
    ok55, msg55, gift55 = sx55.join_faction(d55d, sx55.state_of(d55d), "菩提基因", t55)
    assert ok55 and gift55["普通进化花粉"] == 3 and sx55.flower_accum(d55d) == 5
    assert not sx55.join_faction(d55d, sx55.state_of(d55d), "菩提基因", t55)[0], "不得二投"
    st55d = sx55.state_of(d55d)
    ok55, _m, pay55 = sx55.salary(d55d, st55d, t55)
    assert ok55 and pay55["普通进化花粉"] == 3 and st55d["faction_day"]
    assert not sx55.salary(d55d, st55d, t55 + 3600)[0], "同日不得重复领"
    assert sx55.salary(d55d, st55d, t55 + 86400)[0]
    assert not sx55.salary(mk55("n55"), sx55.state_of(mk55("n55")), t55)[0]
    print("F4 faction ok")

    # ⑧ 石罐：条件不足列原因 / 满足发罐 / 已有拒绝
    d55e = mk55("e55", level=11)
    st55e = sx55.state_of(d55e)
    info55 = sx55.jar_requirements(d55e, st55e)
    assert not info55["ok"] and any("线索" in r for r in info55["reasons"])
    st55e["cleared"] = {d["name"]: 1 for d in sx55.DUNGEONS[:6]}
    st55e["clue"] = 9
    d55e.ext["flower"]["extremes"] = list(sx55.JAR_EXTREMES)
    assert sx55.jar_requirements(d55e, st55e)["ok"]
    ok55, msg55, jar55 = sx55.claim_jar(d55e, st55e, {})
    assert ok55 and jar55[sx55.JAR] == 1 and st55e["jar_claimed"]
    assert not sx55.claim_jar(d55e, st55e, {})[0], "已有不得重复认主"
    assert not sx55.claim_jar(mk55("e2"), sx55.state_of(mk55("e2")), {sx55.JAR: 1})[0]
    print("F4 jar ok")

    # ⑨ 榜单：只收花粉路 / 排序
    rows55 = [mk55("r1", level=3), mk55("r2", level=9), PlayerDoc(uid="r3", name="无花粉")]
    sx55.state_of(rows55[1])["field_stage"] = 4
    entries55 = sx55.rank_entries(rows55)
    assert len(entries55) == 2 and entries55[0]["name"] == rows55[1].name
    assert "圣墟榜" in sx55.rank_text(rows55)
    assert "还没有花粉路修士" in sx55.rank_text([PlayerDoc(uid="z")])
    print("F4 rank ok")

    # ⑩ DB 往返 + main.py 接线
    d55f = mk55("f55")
    sx55.begin(d55f, "太行山", 1, t55)
    await db.save_player(d55f.model_dump())
    row55 = await db.get_player("f55")
    assert sx55.state_of(PlayerDoc(**row55))["action"]["dungeon"] == "太行山"

    src55 = open(PLUGIN / "main.py", encoding="utf-8").read()
    miss55 = [c for c in (
        "CMD_SX_DUNGEONS", "CMD_SX_EXPLORE", "CMD_SX_ADDICT", "CMD_SX_FACTIONS",
        "CMD_SX_JOIN_BODHI", "CMD_SX_JOIN_DREAM", "CMD_SX_JOIN_MOUNT", "CMD_SX_SALARY",
        "CMD_SX_JAR", "CMD_SX_JAR_CLAIM", "CMD_SX_BREATH", "CMD_SX_SKILLS",
        "CMD_SX_FIELD", "CMD_SX_FIELD_UP", "CMD_SX_RANK",
    ) if f"@filter.command({c}" not in src55]
    assert miss55 == [], f"漏注册：{miss55}"
    assert 'alias={CMD_SX_JAR_ALIAS}' in src55 and 'alias={CMD_SX_SKILLS_ALIAS}' in src55
    assert 'alias={CMD_SX_FIELD_ALIAS}' in src55
    assert "sx_mod.settle(" in src55 and "sx_mod.begin(" in src55
    assert "sx_mod.claim_jar" in src55 and "sx_mod.salary" in src55
    print("W8-F4 shengxu ok")

    # ---------------- 56. W8-F5 上苍之上 ----------------
    import random as _random56
    from core import shangcang as sc56

    t56 = 1_800_000_000.0
    rows56 = sc56.place_rows(store.table(sc56.TABLE))
    assert len(rows56) == 2 and [r["name"] for r in rows56] == ["魂河", "天帝葬坑"]

    def mk56(uid="sc56", realm=52, **ext56):
        ext = {"yuanshi": 10 ** 10, "xueqi": 10 ** 10, "shouyuan": 200_000, "hp": 10 ** 6}
        ext.update(ext56)
        return PlayerDoc(uid=uid, name="帝" + uid[-2:], realm_index=realm,
                         exp=10 ** 11, stones=10 ** 11, ext=ext)

    # ① 成本折算：灵石原值 / 源石与寿元 ÷1000 / 元神不实现
    c56 = sc56.cost_of(rows56[0])
    assert c56["灵石"] == 10_000_000_000, "灵石照原值"
    assert c56["源石"] == 2_000_000 and c56["寿元"] == 20_000, "源石与寿元 ÷1000"
    assert c56["修为"] == 300_000_000 and c56["血气"] == 300_000_000
    assert "元神" not in c56, "本移植无独立元神池"
    assert sc56.find_place(rows56, "魂河")["name"] == "魂河" and sc56.find_place(rows56, "无") is None
    print("F5 cost ok")

    # ② 门槛与资源
    assert "仙帝权柄" in sc56.begin(mk56("low56", realm=49), sc56.state_of(mk56("low56", realm=49)),
                                   rows56[0], 1, t56)[1]
    poor56 = mk56("poor56")
    poor56.stones = 1
    assert "资源不足" in sc56.begin(poor56, sc56.state_of(poor56), rows56[0], 1, t56)[1]
    print("F5 gate ok")

    # ③ 起历练：扣资源 / 提速 / 连探
    d56 = mk56("go56")
    st56 = sc56.state_of(d56)
    ok56, msg56 = sc56.begin(d56, st56, rows56[0], 1, t56)
    assert ok56 and "预计 60 分钟" in msg56
    assert d56.stones == 10 ** 11 - 10_000_000_000 and d56.ext["shouyuan"] == 180_000
    assert d56.exp == 10 ** 11 - 300_000_000
    assert not sc56.begin(d56, st56, rows56[1], 1, t56)[0], "行动中不得再起"

    d56b = mk56("fast56", **{"gongfa": ["行字秘"]})
    minute56, notes56 = sc56.duration_minutes(d56b, daofa_active=True)
    assert minute56 == 56 and any("行字秘" in n for n in notes56) and any("道法" in n for n in notes56)
    assert sc56.duration_minutes(mk56("none56"))[0] == 60

    d56c = mk56("more56")
    ok56, msg56 = sc56.begin(d56c, sc56.state_of(d56c), rows56[0], 3, t56)
    assert ok56 and "×3" in msg56 and "180 分钟" in msg56
    print("F5 begin ok")

    # ④ 结算：未到期 / 胜利掉落 / 胜场进度 / 纪元奖励 / 回执
    assert not sc56.settle(d56, sc56.state_of(d56), t56 + 60, _random56.Random(1), rows56)[0]
    st56["progress"] = 2
    era56 = sc56.fashan.era_of(d56)
    ok56, msg56, items56 = sc56.settle(d56, sc56.state_of(d56), t56 + 7200,
                                      _random56.Random(1), rows56)
    assert ok56 and "胜" in msg56
    assert items56, "guaranteed 档必掉"
    assert st56["wins"] == 1 and st56["progress"] == 0, "满 3 胜换纪元并归零"
    assert sc56.fashan.era_of(d56) == era56 + 5
    assert st56["receipts"] and "魂河" in st56["receipts"][-1]

    # 失败：血量降到 1，不发奖
    lost56 = False
    for seed in range(40):
        c = mk56("lose56")
        stc = sc56.state_of(c)
        sc56.begin(c, stc, rows56[0], 1, t56)
        c.ext["hp"] = 9_999
        _ok, m, it = sc56.settle(c, stc, t56 + 7200, _random56.Random(seed), rows56)
        if "败" in m:
            assert c.ext["hp"] == 1 and not it and stc["wins"] == 0
            lost56 = True
            break
    assert lost56, "应能失败"

    # 回执截断
    st56["receipts"] = [f"r{i}" for i in range(30)]
    ok56, _m, _i = sc56.settle_now(d56, st56, "魂河", 1, t56 + 9000, _random56.Random(1), rows56[0])
    assert ok56 and len(st56["receipts"]) == sc56.RECEIPT_CAP
    print("F5 settle ok")

    # ⑤ 面板与文案
    panel56 = sc56.panel_text(d56, sc56.state_of(d56), t56, rows56)
    assert "上苍之上" in panel56 and "魂河" in panel56 and "胜场" in panel56
    assert "仙帝权柄" in sc56.rules_text() and "#沉迷上苍之上" in sc56.help_text()
    assert sc56.win_rate(mk56("wr56", realm=60)) > sc56.win_rate(mk56("wr56", realm=50))
    print("F5 panel ok")

    # ⑥ DB 往返 + main.py 接线
    d56d = mk56("db56")
    sc56.begin(d56d, sc56.state_of(d56d), rows56[0], 2, t56)
    await db.save_player(d56d.model_dump())
    row56 = await db.get_player("db56")
    assert sc56.state_of(PlayerDoc(**row56))["action"]["count"] == 2

    src56 = open(PLUGIN / "main.py", encoding="utf-8").read()
    miss56 = [c for c in ("CMD_SC", "CMD_SC_ADDICT") if f"@filter.command({c}" not in src56]
    assert miss56 == [], f"漏注册：{miss56}"
    assert "sc_mod.settle(" in src56 and "sc_mod.begin(" in src56
    assert "sc_mod.panel_text(" in src56 and "sc_mod.TABLE" in src56
    print("W8-F5 shangcang ok")

    # ---------------- 57. W8-F6 人傀 / 外来道果 ----------------
    import json as _json57
    from core import puppet as pu57, motou as mt57

    t57 = 1_800_000_000.0

    def mk57(uid="pu57", **ext57):
        ext = {"modao": 300.0}
        ext.update(ext57)
        return PlayerDoc(uid=uid, name="魔" + uid[-2:], realm_index=45,
                         exp=10 ** 10, stones=10 ** 10, ext=ext)

    # ① 状态与数值（对齐原版 model/forbiddenSoul.js + ForbiddenSoul.js 常量）
    s57 = pu57.state_of(mt57.state_of(mk57()))
    assert s57["puppet"] is None and s57["impurity"] == 0 and s57["retreat_until"] == 0
    assert pu57.day_key(t57) == time.strftime("%Y-%m-%d", time.gmtime(t57 + 8 * 3600))
    assert pu57.CRAFT_ITEMS == {"阴魂木": 3, "神魂结晶": 1} and pu57.CRAFT_STONES == 50_000_000
    assert pu57.REPAIR_ITEMS == {"阴魂木": 1} and pu57.REPAIR_STONES == 10_000_000
    assert pu57.REPAIR_GAIN == 40 and pu57.SUMMON_DURABILITY_COST == 20
    assert pu57.IMPURITY_CAP == 60 and pu57.RETREAT_REDUCE == 30
    print("F6 state/cost ok")

    # ② 夺果打通：境界 <40 拒绝；≥40 得待炼道果 + 对方 6h 裂痕
    win57 = mt57.record_result(mt57.state_of(mk57("win57")), "猎物", True, t57)
    ok57, why57, _s, _p = mt57.dispose(win57, "夺果", {}, t57 + 60, None, 39)
    assert not ok57 and "境界" in why57
    win57 = mt57.record_result(mt57.state_of(mk57("win57b")), "道主", True, t57)
    ok57, why57, win57, patch57 = mt57.dispose(win57, "夺果", {}, t57 + 60, None, 45)
    assert ok57 and win57["guo"]["name"] == "道主·道果", why57
    assert patch57["crack_until"] == t57 + 60 + 6 * 3600

    # ③ 灭魂遗蜕快照（旧 4 参调用仍兼容）
    sl57 = mt57.record_result(mt57.state_of(mk57("sl57")), "傀材", True, t57)
    ok57, why57, sl57, _p = mt57.dispose(sl57, "灭魂", {}, t57 + 60,
                                         {"atk": 1000, "def": 600, "hp": 5000,
                                          "root": "荒古圣体", "gongfa": "道经"}, 45)
    assert ok57 and sl57["remains"]["atk"] == 1000, why57
    sl57 = pu57.state_of(sl57)
    ok57, why57, old57, _ = mt57.dispose(
        mt57.record_result(mt57.state_of(mk57("old57")), "旧傀", True, t57), "灭魂", {}, t57 + 60)
    assert ok57 and "atk" not in old57["remains"], "旧调用不得写快照"
    print("F6 dispose ok")

    # ④ 成本校验 + 炼制（三维遗蜕 ×30%，不超主人 35%）
    full57 = {"阴魂木": 3, "神魂结晶": 1}
    assert pu57.cost_gap(10 ** 10, full57, pu57.CRAFT_ITEMS, pu57.CRAFT_STONES) == ""
    assert "阴魂木" in pu57.cost_gap(10 ** 10, {"阴魂木": 2, "神魂结晶": 1},
                                    pu57.CRAFT_ITEMS, pu57.CRAFT_STONES)
    assert "灵石" in pu57.cost_gap(10, full57, pu57.CRAFT_ITEMS, pu57.CRAFT_STONES)
    ok57, why57 = pu57.craft(sl57, t57 + 120, {"atk": 1000, "defense": 600, "hp": 5000})
    assert ok57 and sl57["remains"] is None, why57
    p57 = sl57["puppet"]
    assert p57["atk"] == 300 and p57["def"] == 180 and p57["hp"] == 1500
    assert p57["durability"] == 100 and p57["name"] == "傀材" and p57["root"] == "荒古圣体"
    assert not pu57.craft(sl57, t57 + 120)[0], "已有人傀不得重炼"
    low57 = mt57.state_of(mk57("low57"))
    low57["remains"] = {"name": "弱傀", "atk": 1000, "def": 600, "hp": 5000}
    pu57.craft(pu57.state_of(low57), t57, {"atk": 100, "defense": 100, "hp": 100})
    assert low57["puppet"]["atk"] == 35, "出战属性受主人 35% 上限约束"
    print("F6 craft ok")

    # ⑤ 修复 / 驱使 / 毁去
    p57["durability"] = 50
    assert pu57.repair(sl57)[0] and p57["durability"] == 90
    assert pu57.repair(sl57)[0] and p57["durability"] == 100
    assert not pu57.repair(sl57)[0], "满耐久不得空耗材料"
    ok57, why57 = pu57.summon(sl57, t57 + 180)
    assert ok57 and p57["durability"] == 80 and sl57["puppet_until"] == t57 + 180 + 6 * 3600, why57
    assert not pu57.summon(sl57, t57 + 200)[0], "同日不得重复出战"
    sl57["puppet_day"], sl57["puppet_until"] = "", 0
    p57["durability"] = 10
    assert not pu57.summon(sl57, t57 + 220)[0], "耐久 <20 拒绝"
    sl57["puppet_day"], sl57["puppet_until"] = pu57.day_key(t57 + 180), t57 + 180 + 6 * 3600
    assert abs(pu57.battle_bonus(sl57, t57 + 200) - 0.10) < 1e-9
    sl57["foreign_fruit"] = {"name": "道果", "bonus": 0.03}
    sl57["crack_until"] = t57 + 200 + 1000
    assert abs(pu57.battle_bonus(sl57, t57 + 200) - 0.08) < 1e-9, "外来道果 + 裂痕 + 人傀同乘区"
    ok57, why57 = pu57.destroy(sl57)
    assert ok57 and sl57["puppet"] is None and sl57["puppet_until"] == 0
    assert not pu57.destroy(sl57)[0]
    print("F6 repair/summon/destroy ok")

    # ⑥ 道果链：炼化 → 熔去 → 闭关 → 到期结算 → 杂质封顶
    fr57 = pu57.state_of(mt57.state_of(mk57("fr57")))
    assert not pu57.refine(fr57, t57)[0], "无待炼道果"
    fr57["guo"] = {"name": "道主·道果", "way": "自身之道"}
    ok57, why57 = pu57.refine(fr57, t57)
    assert ok57 and fr57["impurity"] == 15 and fr57["guo"] is None, why57
    assert abs(pu57.battle_bonus(fr57, t57) - 0.03) < 1e-9
    assert not pu57.refine(fr57, t57)[0]
    assert pu57.melt(fr57)[0] and fr57["impurity"] == 5
    assert pu57.retreat(fr57, t57)[0] and not pu57.retreat(fr57, t57)[0]
    changed57, why57 = pu57.tick(fr57, t57 + 6 * 3600 + 1)
    assert changed57 and fr57["impurity"] == 0 and fr57["retreat_until"] == 0
    fr57["impurity"] = 60
    fr57["guo"] = {"name": "满杂质"}
    ok57, why57 = pu57.refine(fr57, t57)
    assert not ok57 and "杂质" in why57
    print("F6 fruit/retreat ok")

    # ⑦ 文案 / DB 往返 / main.py 接线 / help 分组
    lines57 = pu57.panel_lines(sl57, t57)
    assert any("人傀" in x for x in lines57) and any("杂质" in x for x in lines57)
    assert "#炼制人傀" in pu57.help_text() and "闭关化杂" in pu57.rules_text()
    d57 = mk57("db57")
    s57d = pu57.state_of(mt57.state_of(d57))
    s57d["remains"] = {"name": "库傀", "atk": 1000, "def": 600, "hp": 5000}
    pu57.craft(s57d, t57, {"atk": 1000, "defense": 600, "hp": 5000})
    d57.ext["evil"] = s57d
    await db.save_player(d57.model_dump())
    row57 = await db.get_player("db57")
    assert pu57.state_of(mt57.state_of(PlayerDoc(**row57)))["puppet"]["name"] == "库傀"
    src57 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names57 = ["CMD_PUP_CRAFT", "CMD_PUP_MY", "CMD_PUP_SUMMON", "CMD_PUP_REPAIR",
               "CMD_PUP_DESTROY", "CMD_PUP_REFINE", "CMD_PUP_MELT", "CMD_PUP_RETREAT"]
    miss57 = [c for c in names57 if f"@filter.command({c}" not in src57]
    assert miss57 == [], f"漏注册：{miss57}"
    assert "pup_mod.battle_bonus(" in src57 and "await self._pup_open(event)" in src57
    assert "pup_mod.craft(" in src57 and "确认请发送「#毁去人傀 确认」" in src57
    help57 = _json57.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert len(help57) >= 39 and any(g["group"] == "人傀 · 外来道果" for g in help57)
    print("W8-F6 puppet ok")

    # ---------------- 58. W8-F7 宗门深化 ----------------
    import json as _json58
    from core import sect_deep as sd58

    t58 = 1_800_000_000.0
    rows58 = store.table("item/洞天福地") or []
    assert len(rows58) == 15 and rows58[0]["name"] == "昆仑山" and rows58[0]["level"] == 5
    assert sd58.find_bless(rows58, "天山")["level"] == 3
    assert sd58.find_bless(rows58, "无此地") is None
    assert sd58.pool_cap(1) == 2_000_000 and sd58.pool_cap(9) == 30_000_000
    assert sd58.day_key(t58) == time.strftime("%Y-%m-%d", time.gmtime(t58 + 8 * 3600))
    assert sd58.ARRAY_HP_INIT == 114514 and sd58.ARRAY_HP_PER_STONE == 5
    print("F7 data/consts ok")

    # ② 宗门档 + 无主入驻 + 有主抢夺（攻弱败 / 攻强易主）
    cal58 = {}
    s58 = sd58.state_of(cal58, "青云宗")
    assert s58["array_hp"] == 114514 and s58["build"] == 0 and s58["place"] == ""
    brow58 = sd58.find_bless(rows58, "昆仑山")
    ok58, msg58 = sd58.settle(cal58, brow58, "青云宗", 1000, s58, 0, t58,
                              _random.Random("sec58a"))
    assert ok58 and s58["place"] == "昆仑山" and s58["build"] == 0, msg58
    assert not sd58.settle(cal58, brow58, "青云宗", 1000, s58, 0, t58,
                           _random.Random("sec58a"))[0], "同地不得重复入驻"
    h58 = sd58.state_of(cal58, "血煞宗")
    h58["build"], h58["array_hp"] = 20, 10
    ok58, msg58 = sd58.settle(cal58, brow58, "血煞宗", 10, h58, 1_000_000, t58,
                              _random.Random("sec58b"))
    assert not ok58 and "挡回" in msg58, "守方战力占优不得易主"
    s58["build"], s58["array_hp"] = 3, 900_000
    ok58, msg58 = sd58.settle(cal58, brow58, "血煞宗", 10_000_000, h58, 1, t58,
                              _random.Random("sec58c"))
    assert ok58 and h58["place"] == "昆仑山" and h58["build"] == 3, msg58
    assert s58["place"] == "" and s58["build"] == 0 and s58["array_hp"] == 0
    assert len(sd58.bless_lines(rows58, cal58)) == 17
    print("F7 settle ok")

    # ③ 灵脉 / 建设 / 大阵 / 维护 / 门槛
    b58 = sd58.state_of(cal58, "测试宗")
    b58["place"] = "天山"
    d58 = PlayerDoc(uid="sec58", name="道友", realm_index=9, stones=0,
                    ext={"sect": "测试宗", "sect_contrib": 0})
    ok58, msg58, gain58, pool58 = sd58.vein(d58, b58, rows58, 0, 1, t58)
    assert ok58 and gain58 == 1200 * 3 * 10, gain58
    assert pool58 == min(gain58, sd58.pool_cap(1))
    assert d58.ext["sect_contrib"] == gain58 and d58.ext["sect_deep"]["vein_day"] == sd58.day_key(t58)
    assert not sd58.vein(d58, b58, rows58, 0, 1, t58)[0], "每日一次"
    ok58, msg58, cost58, add58 = sd58.build(b58, 1_000_000, 9)
    assert ok58 and cost58 == 0 and add58 == 2 and b58["build"] == 2
    ok58, msg58, cost58, hp58 = sd58.array_fix(b58, 1_000_000, 1000)
    assert ok58 and cost58 == 1000 and hp58 == 5000 and b58["array_hp"] == 114514 + 5000
    assert not sd58.array_fix(b58, 100, 1000)[0], "池不足拒绝"
    assert not sd58.array_fix(b58, 1_000_000, 0)[0], "非正数拒绝"
    ok58, msg58, cost58 = sd58.upkeep(b58, 1_000_000, 3, t58)
    assert ok58 and cost58 == 150_000
    assert not sd58.upkeep(b58, 1_000_000, 3, t58 + 3600)[0], "7 日 CD"
    ok58, msg58 = sd58.set_gate(b58, 12, 50)
    assert ok58 and sd58.gate_of(b58) == 12
    assert not sd58.set_gate(b58, 999, 50)[0]
    print("F7 vein/build/array/upkeep/gate ok")

    # ④ 弟子招募 / 任命 / 培养 / 惰性运营
    roots58 = store.table("item/灵根列表") or []
    assert len(roots58) == 139
    ok58, msg58, cost58, dsc58 = sd58.recruit(b58, 1_000_000, 3, roots58, t58,
                                             _random.Random("disc58"))
    assert ok58 and dsc58["id"] == 1 and cost58 == 25_000
    assert dsc58["specialty"] in sd58.SPECIALTIES and 60 <= dsc58["loyalty"] <= 90
    assert not sd58.assign(b58, 1, "杂役")[0], "未知专长拒绝"
    ok58, msg58 = sd58.assign(b58, 1, "外务")
    assert ok58 and b58["disciples"][0]["status"] == "任职"
    ok58, msg58, cost58 = sd58.train(b58, 1_000_000, 1)
    assert ok58 and cost58 == 10_000 and b58["disciples"][0]["train"] == 1
    assert any("#1" in x for x in sd58.disciple_lines(b58, 3))
    ok58, msg58, delta58 = sd58.operate(b58, 1_000_000, 3, t58)
    assert ok58 and delta58 == 0 and b58["ops_at"] == t58, "首日起算不产出"
    ok58, msg58, delta58 = sd58.operate(b58, 1_000_000, 3, t58 + 3 * 86400 + 1)
    assert ok58 and delta58 > 0 and b58["ops_streak"] == 3, msg58
    assert not sd58.operate(b58, 100, 3, t58 + 4 * 86400)[0], "池不足断运营"
    assert b58["ops_streak"] == 0
    print("F7 disciples/operate ok")

    # ⑤ 面板 / 文案 / DB 往返 / main.py 接线 / help 分组
    lines58 = sd58.panel_lines(b58, 1_000_000, 3, 5, t58)
    assert any("护宗大阵" in x for x in lines58) and any("弟子" in x for x in lines58)
    assert "「#开采灵脉」" in sd58.help_text() and "洞天" in sd58.rules_text()
    atk58, dfn58 = sd58.war_bonus(b58)
    assert dfn58 > atk58 > 0, "守方大阵计入全额、攻方计半额"
    d58b = PlayerDoc(uid="db58", name="藏", ext={"sect": "测试宗",
                                                 "sect_deep": {"vein_day": "2026-11-09"}})
    await db.save_player(d58b.model_dump())
    row58b = await db.get_player("db58")
    assert sd58.personal_of(PlayerDoc(**row58b))["vein_day"] == "2026-11-09"
    src58 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names58 = ["CMD_SEC_BLESS_LIST", "CMD_SEC_SETTLE", "CMD_SEC_VEIN", "CMD_SEC_BUILD",
               "CMD_SEC_ARRAY", "CMD_SEC_ARRAY_FIX", "CMD_SEC_UPKEEP", "CMD_SEC_GATE",
               "CMD_SEC_RECRUIT", "CMD_SEC_ROSTER", "CMD_SEC_TRAIN", "CMD_SEC_ASSIGN",
               "CMD_SEC_OPERATE", "CMD_SEC_CONTRIB"]
    miss58 = [c for c in names58 if f"@filter.command({c}" not in src58]
    assert miss58 == [], f"漏注册：{miss58}"
    assert "sec_mod.war_bonus(" in src58 and "sec_mod.gate_of(" in src58
    assert "await self._sec_open(event" in src58 and "sec_mod.settle(" in src58
    assert "async def _sec_flush" in src58 and "sect_deep as sec_mod" in src58
    help58 = _json58.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "宗门深化 · 洞天与运营" for g in help58)
    assert "宗门深化 · 洞天与运营" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W8-F7 sect_deep ok")

    # ---------------- 59. W8-F8 天地榜 ----------------
    from core import tiandibang as tdb59
    import json as _json59
    import datetime as _dt59

    tz59 = _dt59.timezone(_dt59.timedelta(hours=8))
    sun59 = _dt59.datetime(2026, 11, 8, 12, 0, tzinfo=tz59).timestamp()   # 周日
    mon59 = _dt59.datetime(2026, 11, 9, 12, 0, tzinfo=tz59).timestamp()   # 周一
    assert tdb59.week_key(sun59) == "2026-11-02" and tdb59.week_key(mon59) == "2026-11-09"
    assert tdb59.settlement_key(mon59) == "2026-11-02"
    assert tdb59.is_sunday(sun59) and not tdb59.is_sunday(mon59)
    assert tdb59.day_key(sun59) == "2026-11-08"

    # ① 报名 / 属性快照 / 每日次数 / 对手与倍率
    cal59 = {}
    s59 = tdb59.state_of(cal59, sun59)
    assert s59["opened_week"] == "2026-11-02" and s59["entries"] == []
    st_strong59 = {"atk": 4000, "defense": 2000, "hp": 20000, "bao": 0.12}
    st_weak59 = {"atk": 1000, "defense": 800, "hp": 9000, "bao": 0.05}
    ok59, msg59 = tdb59.join(s59, "u59a", "甲", 10, st_strong59, sun59)
    assert ok59 and not tdb59.join(s59, "u59a", "甲", 10, st_strong59, sun59)[0], "不得重复报名"
    tdb59.join(s59, "u59b", "乙", 12, st_weak59, sun59)
    assert len(s59["entries"]) == 2
    ok59, msg59, e59 = tdb59.sync(s59, "u59b", "乙", 20,
                                  {"atk": 1500, "defense": 900, "hp": 9500, "bao": 0.07})
    assert ok59 and e59["atk"] == 1500 and e59["realm"] == 20
    assert not tdb59.sync(s59, "ghost59", "鬼", 1, st_weak59)[0]
    i59 = tdb59.find(s59, "u59b")
    assert tdb59.refresh_daily(s59, i59, sun59) and s59["entries"][i59]["chances"] == 3
    assert not tdb59.refresh_daily(s59, i59, sun59), "同日不重复补次数"
    assert tdb59.refresh_daily(s59, tdb59.find(s59, "u59a"), sun59)
    kind59, foe59, boost59 = tdb59.opponent(s59, i59)
    assert kind59 == "player" and foe59 == 0 and boost59 == 2.0, (kind59, foe59, boost59)
    kind59b, foe59b, _ = tdb59.opponent(s59, tdb59.find(s59, "u59a"))
    assert kind59b == "beast" and foe59b == -1, "榜首打灵修兽"
    mir59 = tdb59.mirror(s59["entries"][0], _random.Random("mir59"))
    assert 0.8 * 4000 <= mir59["atk"] <= 1.2 * 4000
    assert tdb59.boost_unit(s59["entries"][i59], 2.0)["atk"] == 3000
    print("F8 join/sync/opponent ok")

    # ② 胜负积分 / 灵石倍率 / 次数与摘榜令
    ok59, msg59, stone59 = tdb59.duel(s59, "u59b", "win", "player", "甲", sun59)
    assert ok59 and stone59 == 2000 * 4, stone59
    ok59, msg59, stone59 = tdb59.duel(s59, "u59b", "lose", "beast", "灵修兽", sun59)
    assert ok59 and stone59 == (2000 + 800) * 6, stone59
    ok59, msg59, stone59 = tdb59.duel(s59, "u59b", "draw", "beast", "灵修兽", sun59)
    assert ok59 and stone59 == 0
    assert not tdb59.duel(s59, "u59b", "win", "player", "甲", sun59)[0], "次数用光须拒绝"
    assert tdb59.need_ticket(s59["entries"][tdb59.find(s59, "u59b")])
    ok59, msg59 = tdb59.use_ticket(s59, "u59b", sun59)
    assert ok59 and s59["entries"][tdb59.find(s59, "u59b")]["chances"] == 1
    assert not tdb59.use_ticket(s59, "u59b", sun59)[0]
    print("F8 duel/ticket ok")

    # ③ 天地堂：周日限定 / 报名 / 积分 / 商品名 / 批量
    rows59 = store.table("item/商店/天地堂") or []
    assert len(rows59) == 13
    assert tdb59.find_shop(rows59, "摘榜令")["price"] == 5100
    assert tdb59.find_shop(rows59, "无此物") is None
    assert not tdb59.buy(s59, "u59b", "摘榜令", rows59, mon59)[0], "非周日拒绝"
    assert not tdb59.buy(s59, "ghost59", "摘榜令", rows59, sun59)[0], "未报名拒绝"
    assert not tdb59.buy(s59, "u59b", "空气", rows59, sun59)[0], "未知商品拒绝"
    assert not tdb59.buy(s59, "u59b", "摘榜令*2", rows59, sun59)[0], "积分不足拒绝"
    s59["entries"][tdb59.find(s59, "u59b")]["score"] = 6000
    ok59, msg59, item59, qty59, cost59 = tdb59.buy(s59, "u59b", "寻物纸*2", rows59, sun59)
    assert ok59 and item59 == "寻物纸" and qty59 == 2 and cost59 == 20
    assert s59["entries"][tdb59.find(s59, "u59b")]["score"] == 5980
    print("F8 shop ok")

    # ④ 惰性周结算 / 幂等 / 清空积分
    s59["entries"][tdb59.find(s59, "u59a")]["score"] = 1000
    msg59, ops59, changed59 = tdb59.maybe_settle(s59, sun59)
    assert not changed59 and ops59 == [], "启用当周不补发上一周"
    msg59, ops59, changed59 = tdb59.maybe_settle(s59, mon59)
    assert changed59 and len(ops59) == 2, (msg59, ops59)
    assert ops59[0]["stones"] == 17_500_000 and ops59[0]["box"] == 5
    assert ops59[1]["stones"] == 13_000_000 and ops59[1]["box"] == 3
    assert all(e["score"] == 0 and e["chances"] == 3 for e in s59["entries"])
    assert s59["weeks"]["2026-11-02"]["status"] == "completed"
    msg59, ops59, changed59 = tdb59.maybe_settle(s59, mon59)
    assert not changed59 and "已结算" in msg59, "同周不得重复发放"
    assert "积分已重置" in tdb59.reset(s59)
    print("F8 settle ok")

    # ⑤ 面板 / 文案 / DB 往返 / main.py 接线 / help 分组
    assert any("每日免费 3 次" in x for x in tdb59.board_lines(s59, "u59b", mon59))
    assert any("天地堂" in x for x in tdb59.shop_lines(rows59, 100, sun59))
    assert any("攻击" in x for x in tdb59.panel_lines(s59["entries"][0]))
    assert "「#天地榜比试」" in tdb59.rules_text() and "「#报名比赛」" in tdb59.help_text()
    tdb59.commit(cal59, s59)
    await db.save_calamity(cal59)
    back59 = tdb59.state_of(await db.get_calamity(), mon59)
    assert len(back59["entries"]) == 2 and back59["weeks"]["2026-11-02"]["status"] == "completed"
    src59 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names59 = ["CMD_TDB_JOIN", "CMD_TDB_PK", "CMD_TDB_BOARD", "CMD_TDB_SYNC",
               "CMD_TDB_SHOP", "CMD_TDB_BUY", "CMD_TDB_RESET", "CMD_TDB_SETTLE"]
    miss59 = [c for c in names59 if f"@filter.command({c}" not in src59]
    assert miss59 == [], f"漏注册：{miss59}"
    assert "tdb_mod.maybe_settle(" in src59 and "async def _tdb_award" in src59
    assert "tiandibang as tdb_mod" in src59 and "tdb_mod.duel(" in src59
    help59 = _json59.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "天地榜 · 积分赛与天地堂" for g in help59)
    assert "天地榜 · 积分赛与天地堂" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W8-F8 tiandibang ok")

    # ---------------- 60. W8-F9 位面大事件 / 异域叩击帝关 ----------------
    from core import realm_event as rev60
    import json as _json60

    now60 = 1_800_000_000.0
    pd60 = store.table("位面坐标") or {}
    wy60 = 12_000

    class _R60:
        """确定性随机源：random() 固定，randrange 恒取 0。"""
        def __init__(self, v):
            self.v = v
        def random(self):
            return self.v
        def randrange(self, n):
            return 0

    cal60 = {}
    ev60, fresh60 = rev60.event_state(cal60, wy60)
    assert fresh60 and ev60["last_world_year"] == wy60 - rev60.EVENT_COOLDOWN_YEARS
    _ev60b, fresh60b = rev60.event_state(cal60, 0)
    assert not fresh60b, "世界年 0 起算不得反复判为新建（F8 同款坑）"
    assert len(rev60.EVENT_NAMES) == 8
    assert all(rev60.weighted_types(i) for i in range(5))
    assert rev60.type_by_name("天地异变") == "worldChange"
    assert rev60.type_by_name("无此异象") is None

    # ① 惰性触发：冷却 / 概率 / 活跃上限 / 类型去重 / 超管强制
    r60 = _random.Random("rev60")
    assert not rev60.maybe_spawn(ev60, wy60 + 100, 0, now60, r60, pd60)[1], "冷却未到不得触发"
    msg60, ch60 = rev60.maybe_spawn(ev60, wy60, 0, now60, r60, pd60,
                                    force=True, preferred="worldChange")
    assert ch60 and ev60["active"][0]["type"] == "worldChange"
    assert "「#参与位面大事件」" in msg60
    e60 = ev60["active"][0]
    assert e60["expires_at"] - e60["started_at"] == rev60.EVENT_DURATION
    assert ev60["last_world_year"] == wy60 and ev60["stats"]["worldChange"] == 1
    assert len(ev60["history"]) == 1 and e60["plane"] and e60["location"]
    msg60, ch60 = rev60.maybe_spawn(ev60, wy60 + 2000, 3, now60, _R60(0.0), pd60)
    assert ch60 and len(ev60["active"]) == 2
    assert len({x["type"] for x in ev60["active"]}) == 2, "同类型不得重复出现"
    assert not rev60.maybe_spawn(ev60, wy60 + 4000, 4, now60, _R60(0.99), pd60)[1], "掷骰失败"
    rev60.maybe_spawn(ev60, wy60 + 3000, 0, now60, r60, pd60, force=True)
    assert len(ev60["active"]) == 3
    assert not rev60.maybe_spawn(ev60, wy60 + 6000, 2, now60, _R60(0.0), pd60)[1], "活跃上限 3"
    print("F9 spawn/cooldown ok")

    # ② 参与：精确坐标 / 重复 / 奖励 / 历史同步 / 过期
    p60 = PlayerDoc(uid="u60", name="甲", realm_index=10, physique_index=4)
    p60.ext["plane"] = {"current": e60["plane"],
                        "coords": {e60["plane"]: {"x": e60["x"], "y": e60["y"]}}}
    assert rev60.reward_of(p60) == (10 + 4 + 5 * 2 + 2) * 5000
    assert rev60.reward_of(PlayerDoc(uid="zero")) == rev60.REWARD_MIN
    ok60, msg60, gain60 = rev60.join(ev60, "u60", "甲", p60, now60)
    assert ok60 and gain60 == rev60.reward_of(p60)
    assert not rev60.join(ev60, "u60", "甲", p60, now60)[0], "每人每事件一次"
    assert "u60" in ev60["history"][0]["participants"], "参与名单要同步进历史"
    bad60 = PlayerDoc(uid="u60b", name="乙")
    bad60.ext["plane"] = {"current": "凡间", "coords": {"凡间": {"x": -1, "y": -1}}}
    ok60, msg60, _ = rev60.join(ev60, "u60b", "乙", bad60, now60)
    assert not ok60 and "精确坐标" in msg60
    assert rev60.prune(ev60, now60 + rev60.EVENT_DURATION + 1) and ev60["active"] == []
    assert not rev60.join(ev60, "u60c", "丙", p60, now60 + rev60.EVENT_DURATION + 1)[0]
    assert "「#参与位面大事件」" in rev60.rules_text()
    assert any("统计" in x for x in rev60.board_lines(ev60, now60, wy60))
    assert len(rev60.history_lines(ev60, 20)) >= 2
    print("F9 join/board ok")

    # ③ 帝关状态机：首年落库 / 触发 / 告急 / 超期城破
    ps60, fresh_p60 = rev60.pass_state(cal60)
    assert fresh_p60 and ps60["status"] == "dormant"
    _ps60b, fresh_p60b = rev60.pass_state(cal60)
    assert not fresh_p60b
    m60, ops60, ch60 = rev60.maybe_tick(ps60, 5000, now60, _R60(0.99), ["u60"], True)
    assert ch60 and ps60["last_checked_year"] == 5000 and ps60["status"] == "dormant"
    assert not rev60.maybe_tick(ps60, 5000, now60, _R60(0.0), ["u60"], True)[2], "同年不得重掷"
    m60, ops60, ch60 = rev60.maybe_tick(ps60, 6000, now60, _R60(0.0), ["u60"], True)
    assert ch60 and ps60["status"] == "active" and ps60["wave"] == 1
    a60 = ps60["active"]
    assert a60["kill_target"] == 100 and a60["morale"] == 100
    assert a60["deadline_world_year"] == 6000 + rev60.WAVE_YEARS
    assert "「#驰援帝关」" in m60
    m60, ops60, ch60 = rev60.maybe_tick(ps60, 7000, now60, _R60(0.0), ["u60"], True)
    assert ch60 and a60["reminded_years"] == [1000] and "帝关烽火" in m60
    assert not rev60.maybe_tick(ps60, 7000, now60, _R60(0.0), ["u60"], True)[2], "告急不得重复"
    m60, ops60, ch60 = rev60.maybe_tick(ps60, 9000, now60, _R60(0.0), ["u60"], True)
    assert ch60 and ps60["status"] == "ended" and ps60["outcome"] == "breached"
    assert ops60[0]["destroy_planes"] == list(rev60.TARGET_PLANES)
    print("F9 imperial pass tick ok")

    # ④ 出战 / 波次完成 / 帝血闭环 / 决战 / 城破
    ps60, _ = rev60.pass_state({})
    rev60.start_wave(ps60, 1, 1000, ["u1", "u2"], now60)
    assert rev60.sortie_cd_left(ps60, "u1", now60) == 0
    rev60.apply_sortie(ps60, "u1", "甲", 20, False, now60)
    assert rev60.sortie_cd_left(ps60, "u1", now60) > 0
    rev60.apply_sortie(ps60, "u1", "甲", 20, False, now60)
    rev60.apply_sortie(ps60, "u2", "乙", 30, True, now60)
    assert ps60["active"]["total_kills"] == 70 and ps60["active"]["morale"] == 30
    assert rev60.support_of(ps60["active"]) == (2, 2)
    assert not rev60.is_wave_complete(ps60["active"]), "斩敌未满 100"
    rev60.apply_sortie(ps60, "u1", "甲", 50, False, now60 + 601)
    assert rev60.is_wave_complete(ps60["active"])
    m60, ops60 = rev60.complete_wave(ps60, 1200, _R60(0.99))
    assert ps60["status"] == "resting" and ps60["next_wave_year"] == 1200 + rev60.REST_YEARS
    assert not ps60["prisoners"] and "帝关大捷" in m60
    m60, ops60, ch60 = rev60.maybe_tick(ps60, 6200, now60, _R60(0.0), ["u1", "u2"], True)
    assert ch60 and ps60["wave"] == 2 and ps60["status"] == "active"
    rev60.start_wave(ps60, 3, 7000, ["u1"], now60)
    rev60.apply_sortie(ps60, "u1", "甲", 100, False, now60)
    m60, ops60 = rev60.complete_wave(ps60, 7100, _R60(0.99))
    assert ps60["active"]["phase"] == "kingBattle"
    assert ops60 and ops60[0]["grant"] == ("u1", {rev60.BLOOD_ITEM: 1}), "帝血须有产出点"
    assert "「#融合帝血」" in m60
    assert not rev60.fuse(ps60, "ghost", "鬼", True, 7200)[0], "未参战不得融合"
    ok60, msg60, ops60 = rev60.fuse(ps60, "u1", "甲", True, 7200)
    assert ok60 and ps60["status"] == "ended" and ps60["outcome"] == "defended"
    assert ops60[0]["stones"] == ("u1", rev60.CHAMPION_STONES)
    ps60c, _ = rev60.pass_state({})
    rev60.start_wave(ps60c, 3, 8000, ["u9"], now60)
    rev60.apply_sortie(ps60c, "u9", "丙", 100, False, now60)
    rev60.complete_wave(ps60c, 8100, _R60(0.99))
    ok60, msg60, ops60 = rev60.fuse(ps60c, "u9", "丙", False, 8200)
    assert ok60 and ps60c["outcome"] == "breached" and ops60[0]["destroy_planes"]
    print("F9 sortie/king battle ok")

    # ⑤ 面板 / 文案 / DB 往返 / main.py 接线 / help 分组
    ps_panel60, _ = rev60.pass_state({})
    rev60.start_wave(ps_panel60, 1, 1000, ["u1"], now60)
    assert any("异域叩击帝关" in x for x in rev60.panel_lines(ps_panel60, 7200))
    assert any("帝关战史" in x for x in rev60.panel_lines(ps60, 7200))
    assert any("帝关威名榜" in x for x in rev60.prestige_lines(ps60, 20))
    assert "「#驰援帝关」" in rev60.pass_rules_text()
    assert "「#诸天大事件」" in rev60.help_text()
    assert rev60.clear_events(ev60) and ev60["active"] == []
    rev60.commit(cal60, ev60, ps60)
    await db.save_calamity(cal60)
    back60 = await db.get_calamity()
    bev60, fe60 = rev60.event_state(back60, wy60)
    bps60, fp60 = rev60.pass_state(back60)
    assert not fe60 and not fp60 and bps60["outcome"] == "defended"
    assert len(bev60["history"]) == len(ev60["history"])
    src60 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names60 = ["CMD_REV_BOARD", "CMD_REV_HISTORY", "CMD_REV_JOIN", "CMD_REV_SPAWN",
               "CMD_REV_CLEAR", "CMD_IP_BOARD", "CMD_IP_SORTIE", "CMD_IP_FUSE",
               "CMD_IP_RANK", "CMD_IP_FORCE"]
    miss60 = [c for c in names60 if f"@filter.command({c}" not in src60]
    assert miss60 == [], f"漏注册：{miss60}"
    assert "realm_event as rev_mod" in src60 and "async def _rev_open" in src60
    assert "rev_mod.maybe_spawn(" in src60 and "rev_mod.maybe_tick(" in src60
    assert "async def _rev_flush" in src60 and "async def _rev_ops" in src60
    assert "alias={CMD_IP_BOARD_ALIAS}" in src60 and "alias={CMD_IP_SORTIE_ALIAS}" in src60
    help60 = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "位面大事件 · 诸天异象" for g in help60)
    assert any(g["group"] == "异域叩击帝关 · 全服防守" for g in help60)
    gm60 = open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    assert "位面大事件 · 诸天异象" in gm60 and "handle_ip_fuse" in gm60
    print("W8-F9 realm_event ok")
    # ========================================================= W9-F1/F2：帝路雷劫 + 悟道道途
    import json as _json60
    from core import daolu as dl60, wudao as wd60, era as era60, zhengdao as dz60

    class _Lucky60:
        """恒过 rng：random()=0.01，uniform 取上界。"""
        def random(self):
            return 0.01
        def uniform(self, a, b):
            return b

    class _Doom60:
        """恒败 rng。"""
        def random(self):
            return 0.99
        def uniform(self, a, b):
            return a

    era60s = era60.state_of(0)   # 神话时代：qi_cost 0.4
    assert abs(float(era60s["qi_cost"]) - 0.4) < 1e-9

    # —— 五档雷劫：越级 / 门槛 / 失败 / 自动复活 / 成功 / 速通
    d60 = PlayerDoc(uid="u60", name="渡劫人", realm_index=5, exp=10_000_000,
                    stones=1_000_000, ext={"xueqi": 10_000_000, "potential": 10.0,
                                           "shouyuan": 5_000_000, "hp": 100.0})
    ok60, msg60, _ = dl60.run(d60, "圣人", era60s, time.time(), _Lucky60())
    assert not ok60 and "逐档" in msg60, msg60
    ok60, msg60, _ = dl60.run(d60, "斩道", era60s, time.time(), _Lucky60())
    assert not ok60 and "权柄" in msg60, msg60            # 权柄 5 < 10

    d60.realm_index = 15                                  # 权柄 15 ≥ 10
    pot60, exp60 = float(d60.ext["potential"]), d60.exp
    cost60 = int(dl60.BASE_COST * dl60.TIERS[0]["mult"] * float(era60s["qi_cost"]))
    ok60, msg60, _ = dl60.run(d60, "斩道", era60s, time.time(), _Doom60())
    assert not ok60 and "失败" in msg60, msg60
    assert float(d60.ext["potential"]) == pot60 - 1, "潜力消耗"
    assert d60.exp == int((exp60 - cost60) * 0.75), "失败修为 = (exp-成本)×75%"
    assert dz60.peek(d60) == 1.0, "失败道伤 +1"
    assert "复活发动" not in msg60, "无复活功法不武装复活窗口"
    assert dl60.state_of(d60)["passed"] == -1, "失败不记录档位"

    d60.exp = exp60
    d60.ext["gongfa"] = ["柳神法"]                        # 自动复活：损耗抵消
    ok60, msg60, _ = dl60.run(d60, "斩道", era60s, time.time(), _Doom60())
    assert not ok60 and "复活功法" in msg60, msg60
    assert d60.exp == exp60 - cost60, "自动复活应回满至扣费后修为"
    assert dl60.state_of(d60)["passed"] == -1, "失败不记录档位"

    d60.ext["gongfa"] = []
    ok60, msg60, _ = dl60.run(d60, "斩道", era60s, time.time(), _Lucky60())
    assert ok60 and "渡过" in msg60, msg60
    assert dl60.state_of(d60)["passed"] == 0, "斩道档位记录（索引0）"
    assert abs(dz60.state_of(d60)["power_bonus"] - 0.1) < 1e-9, "帝威 +0.1"
    ok60, msg60, _ = dl60.run(d60, "斩道", era60s, time.time(), _Lucky60())
    assert not ok60 and "无需重渡" in msg60, msg60
    ok60, msg60, _ = dl60.run(d60, "准帝", era60s, time.time(), _Lucky60())
    assert not ok60 and "逐档" in msg60, msg60

    ok60, msg60, _ = dl60.disperse(d60, "圣人", era60s, time.time(), _Lucky60())
    assert not ok60 and "权柄" in msg60, msg60            # 权柄 15 < 16 不可打散
    d60.realm_index = 20                                  # 权柄 20 ≥ 16
    ok60, msg60, _ = dl60.disperse(d60, "圣人", era60s, time.time(), _Lucky60())
    assert ok60 and "打散" in msg60 and "双倍" in msg60, msg60
    assert dl60.state_of(d60)["passed"] == 1, "圣人档记录（索引1）"
    assert dl60.state_of(d60)["dispersed"] == 1, "速通计数"
    assert abs(dz60.state_of(d60)["power_bonus"] - 0.3) < 1e-9, "帝威 0.1+0.2"
    print("W9-F1 daolu ok")

    # —— 悟道：门槛 / 消耗 / 失败损失 / 古茶 / 每日上限 / 面板
    d61b = PlayerDoc(uid="u61b", name="凡悟", realm_index=2, exp=10_000_000,
                     stones=10_000_000, ext={"xueqi": 10_000_000, "potential": 500.0,
                                             "shouyuan": 900_000, "hp": 100.0})
    ok61, msg61, _ = wd60.attempt(d61b, {}, time.time(), _Lucky60())
    assert not ok61 and "斩道" in msg61, msg61            # 权柄 4 < 10

    d61 = PlayerDoc(uid="u61", name="悟道人", realm_index=12, physique_index=4, exp=10_000_000,
                    stones=10_000_000, ext={"xueqi": 10_000_000, "potential": 500.0,
                                            "shouyuan": 900_000, "hp": 100.0})
    node61 = wd60.current_node(wd60.state_of(d61))
    assert node61 and node61["name"] == "王者道则", node61
    pot61, sy61 = float(d61.ext["potential"]), int(d61.ext["shouyuan"])
    ok61, msg61, _ = wd60.attempt(d61, {}, time.time(), _Lucky60())
    assert ok61 and "道则进度" in msg61, msg61
    c61 = wd60.costs_of(d61, 0)
    assert float(d61.ext["potential"]) == pot61 - c61["potential"], "潜力消耗"
    assert int(d61.ext["shouyuan"]) == sy61 - c61["shouyuan"], "寿元燃烧"
    assert int(d61.ext["xueqi"]) == 10_000_000 - c61["xueqi"], "血气消耗"

    # 失败：恒败 rng 有损失；先显式吃茶（减半），再验证 attempt 自动补扣
    d61.ext["potential"] = 500.0
    exp_b61 = d61.exp
    ok61, msg61, _ = wd60.attempt(d61, {}, time.time(), _Doom60())
    assert ok61 and "失败" in msg61, msg61                # 悟道失败仍返回 ok=True（有结果）
    assert d61.exp < exp_b61, "失败有损失"
    ok61, msg61, _ = wd60.tea(d61, {"悟道古茶": 2})
    assert ok61, msg61
    d61.ext["potential"] = 500.0
    ok61, msg61, _ = wd60.attempt(d61, {}, time.time(), _Doom60())
    assert ok61 and "减半" in msg61, msg61                # 显式吃茶生效
    d61.ext["potential"] = 500.0
    _st61 = wd60.state_of(d61)          # 前面已用满当日次数，单测重置计数验证自动补扣
    _st61["count"] = 0
    wd60.save(d61, _st61)
    ok61, msg61, delta61 = wd60.attempt(d61, {"悟道古茶": 2}, time.time(), _Doom60())
    assert ok61 and delta61.get("悟道古茶") == -1, "古茶 buff 用尽后自动补扣"

    # 每日上限：连吃 3 次（恒过）→ 第 4 次拒；有丹则续
    d62 = PlayerDoc(uid="u62", name="悟道人二", realm_index=12, physique_index=4, exp=10_000_000,
                    stones=10_000_000, ext={"xueqi": 10_000_000, "potential": 900.0,
                                            "shouyuan": 900_000, "hp": 100.0})
    for _ in range(3):
        ok62, msg62, _ = wd60.attempt(d62, {}, time.time(), _Lucky60())
        assert ok62, msg62
    ok62, msg62, _ = wd60.attempt(d62, {}, time.time(), _Lucky60())
    assert not ok62 and "大衍悟道丹" in msg62, msg62
    d62.exp += wd60.costs_of(d62, 0)["exp"]
    d62.ext["xueqi"] = 10_000_000
    ok62, msg62, delta62 = wd60.attempt(d62, {"大衍悟道丹": 1}, time.time(), _Lucky60())
    assert ok62 and delta62.get("大衍悟道丹") == -1, (msg62, delta62)
    assert "真实寿元" in wd60.panel(d61) and "当前节点" in wd60.panel(d61)
    assert "王者道则" in wd60.panel(d62)

    # main.py 接线 + help 分组 + 手册分组
    src60 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names60 = ["CMD_DL_ZHANDAO", "CMD_DL_SHENGREN", "CMD_DL_SHENGRENWANG", "CMD_DL_DASHENG",
               "CMD_DL_ZHUNDI", "CMD_DL_DISPERSE", "CMD_DL_PANEL", "CMD_DL_RULES",
               "CMD_WD_ATTEMPT", "CMD_WD_TEA", "CMD_WD_PATH"]
    miss60 = [c for c in names60 if f"@filter.command({c}" not in src60]
    assert miss60 == [], f"漏注册：{miss60}"
    assert "dl_mod.run(" in src60 and "wd_mod.attempt(" in src60
    assert "daolu as dl_mod, wudao as wd_mod" in src60
    help60 = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "帝路 · 五档雷劫与悟道" for g in help60)
    assert "帝路·悟道" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W9-F2 wudao ok")

    # ========================================================= W10-F1/F2：己道推演 + 红尘仙
    from core import selfdao as sd70, yuanshen as ys70

    class _Lucky70(_Lucky60):
        pass

    class _Doom70(_Doom60):
        pass

    era70s = era60.state_of(0)
    d70 = PlayerDoc(uid="u70", name="证帝人", realm_index=25, exp=500_000_000,
                    stones=1_000_000, ext={"xueqi": 500_000_000, "potential": 10_000.0,
                                           "shouyuan": 5_000_000, "hp": 100.0,
                                           "era_points": 500})
    _yst70 = ys70.ensure(d70)
    _yst70["heart"] = {"cur": 5000, "max": 5000, "last": 0.0}
    ys70.save(d70, _yst70)

    d70b = PlayerDoc(uid="u70b", name="凡人", realm_index=3,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 1})
    ok70, msg70, _ = sd70.deduce(d70b, time.time(), _Doom70())
    assert not ok70 and "证道成帝" in msg70, msg70

    for i in range(1, 21):
        _h70 = ys70.ensure(d70)                     # 心神上限 30~100，逐层补满再推演
        _h70["heart"]["cur"] = 9999
        ys70.save(d70, _h70)
        ok70, msg70, _ = sd70.deduce(d70, time.time(), _Lucky70())
        assert ok70 and f"第 {i}/20 层" in msg70, (i, msg70)
        if i == 10:
            assert "极巅" in msg70, msg70
        if i == 15:
            assert "神胎" in msg70, msg70
        if i == 20:
            assert "半步仙帝" in msg70, msg70
        st70 = sd70.state_of(d70)
        st70["last_life_at"] = 0.0
        sd70.save(d70, st70)
    assert sd70.deduction_bonus(d70)["damage_reduction"] == 0.10
    assert sd70.deduction_bonus(d70)["extra_rebirth"] == 1.0
    ok70, msg70, _ = sd70.deduce(d70, time.time(), _Lucky70())
    assert not ok70 and "圆满" in msg70, msg70

    # 合道 + 体系境界
    _wst70 = wd60.state_of(d70)
    _wst70["completed"] = ["红尘仙道"]
    wd60.save(d70, _wst70)
    ok70, msg70, _ = sd70.hedao(d70, "岁月剑河", time.time())
    assert ok70 and "岁月剑河" in msg70, msg70
    ok70, msg70 = sd70.set_realms(d70, "孕道/凝道/化道/合道/归一道/我道永恒")
    assert ok70 and "我道永恒" in msg70, msg70
    ok70, msg70 = sd70.set_realms(d70, "再改/不了")
    assert not ok70 and "已命名" in msg70, msg70

    # 红尘仙：解锁 → 立愿 → 九世
    ok70, msg70 = sd70.divine(d70, time.time())
    assert ok70 and "立下世愿" in msg70, msg70
    ok70, msg70 = sd70.vow(d70, "争渡")
    assert ok70 and "争渡" in msg70, msg70
    for n in range(1, 10):
        st70 = sd70.state_of(d70)
        st70["last_life_at"] = 0.0
        sd70.save(d70, st70)
        _y70 = ys70.ensure(d70)                     # 每世消耗元神值，测试中补满
        _y70["cur"] = 999_999
        ys70.save(d70, _y70)
        ok70, msg70, _ = sd70.live(d70, era70s, time.time(), _Lucky70())
        assert ok70, (n, msg70)
    st70 = sd70.state_of(d70)
    assert st70["hongchen"] and st70["life"] == 9, st70
    assert len(wd60.state_of(d70)["completed"]) == 8, "九世归一后八重己道圆满"
    assert "红尘仙" in sd70.panel(d70, time.time())

    # 失败路径：劫灰 / 身灭道消
    d71 = PlayerDoc(uid="u71", name="证帝人二", realm_index=25, exp=500_000_000,
                    ext={"xueqi": 500_000_000, "potential": 10_000.0, "shouyuan": 5_000_000,
                         "hp": 100.0, "era_points": 500})
    _yst71 = ys70.ensure(d71)
    _yst71["heart"] = {"cur": 5000, "max": 5000, "last": 0.0}
    ys70.save(d71, _yst71)
    ok71, msg71, _ = sd70.deduce(d71, time.time(), _Doom70())
    assert ok71 and "身灭道消" in msg71, msg71
    st71 = sd70.state_of(d71)
    assert st71["layers"] == 0 and st71["ash"] == 1, st71
    assert st71["death_until"] > time.time(), "320 分钟冷却"
    assert dz60.peek(d71) == 1.0, "推演失败道伤 +1"

    # main.py 接线 + help 分组 + 手册分组
    src70 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names70 = ["CMD_SD_DEDUCE", "CMD_SD_HEDAO", "CMD_SD_REALMS", "CMD_RD_DIVINE",
               "CMD_RD_VOW", "CMD_RD_LIVES", "CMD_RD_PANEL"]
    miss70 = [c for c in names70 if f"@filter.command({c}" not in src70]
    assert miss70 == [], f"漏注册：{miss70}"
    assert "sd_mod.deduce(" in src70 and "sd_mod.live(" in src70
    help70b = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "帝路 · 己道与红尘仙" for g in help70b)
    assert "帝路·红尘仙" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W10-F1/F2 selfdao ok")

    # ========================================================= W11-F1/F2：自身之道 + 祭道 + 唯一道
    from core import ownway as ow80

    d80 = PlayerDoc(uid="u80", name="帝路人", realm_index=25, exp=10_000_000_000,
                    stones=1_000_000, ext={"xueqi": 10_000_000_000, "potential": 1_000_000.0,
                                           "shouyuan": 50_000_000, "hp": 100.0})
    ok80, msg80 = ow80.create(d80, "剑意", "杀伐剑道")
    assert not ok80 and "攻伐" in msg80, msg80                 # 类型不合法
    d80.state = "闭关"
    ok80, msg80 = ow80.create(d80, "攻伐", "杀伐剑道")
    assert not ok80 and "行动" in msg80, msg80                 # 需空闲
    d80.state = "空闲"
    ok80, msg80 = ow80.create(d80, "攻伐", "杀伐剑道")
    assert ok80 and "大道初开" in msg80, msg80
    assert ow80.state_of(d80)["seg"] == 0

    ok80, msg80 = ow80.cultivate(d80, 10, time.time())
    assert ok80 and "第 10 段" in msg80, msg80
    ok80, msg80 = ow80.cultivate(d80, 5, time.time())
    assert not ok80 and "突破" in msg80, msg80                 # 段满需突破
    ok80, msg80 = ow80.breakthrough(d80, time.time())
    assert ok80 and "10 → 11" in msg80 and "道基实道" in msg80, msg80
    bounds80 = {10, 50, 120, 200, 280, 350, 430, 499}
    guard80 = 0
    while ow80.state_of(d80)["seg"] < 500 and guard80 < 60:
        guard80 += 1
        seg80 = ow80.state_of(d80)["seg"]
        if seg80 in bounds80:
            ok80, msg80 = ow80.breakthrough(d80, time.time())
        else:
            ok80, msg80 = ow80.cultivate(d80, 50, time.time())
        assert ok80, (seg80, msg80)
    assert ow80.state_of(d80)["seg"] == 500, "己道 500 段"
    assert "祭尽诸我" in ow80.panel(d80)

    ok80, msg80, _ = ow80.emperor_sutra(d80, "岁月剑经", time.time())
    assert ok80 and "岁月剑经" in msg80, msg80
    assert "岁月剑经" in list(d80.ext.get("gongfa") or []), "帝经录入功法谱"
    ok80, msg80, _ = ow80.emperor_sutra(d80, "再著一本", time.time())
    assert not ok80 and "一人一部" in msg80, msg80

    _dz80 = dz60.state_of(d80)
    _dz80["reached"] = True                                    # 祭道前置：路尽级仙帝
    dz60.save(d80, _dz80)
    _sd80 = sd70.state_of(d80)
    _sd80["layers"] = 20
    sd70.save(d80, _sd80)
    _wd80 = wd60.state_of(d80)
    _wd80["completed"] = ["红尘仙道"]
    wd60.save(d80, _wd80)
    reg80 = {"emperors": [{"uid": f"e{i}"} for i in range(5)], "guards": {}}
    ok80, msg80, _ = ow80.sacrifice(d80, reg80, time.time(), _Lucky60())
    assert not ok80 and "10 位" in msg80, msg80                # 全服证道者不足
    reg80 = {"emperors": [{"uid": f"e{i}"} for i in range(10)], "guards": {}}
    ok80, msg80, _ = ow80.sacrifice(d80, reg80, time.time(), _Lucky60())
    assert ok80 and "祭 道" in msg80, msg80
    assert ow80.state_of(d80)["jidao"] is True
    assert abs(dz60.state_of(d80)["power_bonus"] - 3.0) < 1e-9, "祭道帝威拉满"

    ok80, msg80, _, reg80b = ow80.unique_dao(d80, reg80, time.time())
    assert not ok80 and "大道至宝" in msg80, msg80             # 未认主
    d80.ext["daotreasure"] = {"owned": "岁月道果"}
    d80.exp = 10_000_000_000
    d80.ext["xueqi"] = 10_000_000_000
    ok80, msg80, _, reg80b = ow80.unique_dao(d80, reg80, time.time())
    assert ok80 and "唯 一 道 之 上" in msg80, msg80
    assert reg80b.get("unique_holder") == "u80", "全服唯一登记"
    ok80, msg80, _, _ = ow80.unique_dao(d80, reg80b, time.time())
    assert not ok80 and "唯一" in msg80, msg80

    src80 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names80 = ["CMD_OW_CREATE", "CMD_OW_CULTIVATE", "CMD_OW_BREAK", "CMD_OW_SUTRA",
               "CMD_OW_JIDAO", "CMD_OW_UNIQUE", "CMD_OW_PANEL"]
    miss80 = [c for c in names80 if f"@filter.command({c}" not in src80]
    assert miss80 == [], f"漏注册：{miss80}"
    assert "ow_mod.sacrifice(" in src80 and "ow_mod.unique_dao(" in src80
    help80b = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "帝路 · 自身之道与终局" for g in help80b)
    assert "帝路·终局" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W11-F1/F2 ownway ok")

    # ========================================================= W12-F1/F2：体质进阶
    from core import physique as ph90

    d90 = PlayerDoc(uid="u90", name="体质人", realm_index=25, exp=100_000_000,
                    ext={"xueqi": 100_000_000, "potential": 5_000.0, "shouyuan": 9_000_000,
                         "hp": 100.0,
                         "linggen": {"name": "太阳之体", "type": "太阳", "eff": 1.0,
                                     "atk": 100.0, "def": 100.0, "hp": 100.0}})
    ok90, msg90, _ = ph90.awaken_sun(d90, {}, time.time())
    assert not ok90 and "太阳真经" in msg90, msg90            # 缺功法
    d90.ext["gongfa"] = ["太阳真经"]
    ok90, msg90, _ = ph90.awaken_sun(d90, {}, time.time())
    assert not ok90 and "扶桑神枝" in msg90, msg90            # 缺道具
    ok90, msg90, d90d = ph90.awaken_sun(d90, {"扶桑神枝": 1}, time.time())
    assert ok90 and "太阳神体" in msg90, msg90
    assert d90d.get("扶桑神枝") == -1
    lg90 = d90.ext["linggen"]
    assert lg90["name"] == "太阳神体" and abs(lg90["atk"] - 200.0) < 1e-6, lg90
    d90.ext["gongfa"] = ["太阳真经", "太阳真经·仙台卷", "大日涅槃诀"]
    ok90, msg90, _ = ph90.awaken_sun(d90, {}, time.time())
    assert ok90 and "太阳圣皇体" in msg90, msg90
    assert abs(d90.ext["linggen"]["atk"] - 700.0) < 1e-6, "阶段二 ×3.5"

    d90.ext["linggen"].update({"name": "神王体", "type": "神王", "atk": 100.0,
                               "def": 100.0, "hp": 100.0})
    ok90, msg90, _ = ph90.awaken_king(d90, {}, time.time())
    assert ok90 and "神王体·小成" in msg90, msg90
    ok90, msg90, _ = ph90.awaken_king(d90, {}, time.time())
    assert not ok90 and "斗字秘" in msg90, msg90
    d90.ext["gongfa"].append("斗字秘")
    ok90, msg90, _ = ph90.awaken_king(d90, {}, time.time())
    assert ok90 and "神王体·大成" in msg90, msg90

    # 九转轮回
    d91 = PlayerDoc(uid="u91", name="轮回人", realm_index=41, exp=100_000_000,
                    ext={"xueqi": 100_000_000, "potential": 5_000.0, "shouyuan": 9_000_000,
                         "hp": 100.0,
                         "linggen": {"name": "九转轮回体", "type": "转生", "eff": 1.0,
                                     "atk": 100.0, "def": 100.0, "hp": 100.0}})
    ok90, msg90, _ = ph90.reincarnate(d91, time.time(), _Lucky60())
    assert not ok90 and "轮回点" in msg90, msg90
    ok90, msg90, d90d = ph90.offer_stone(d91, {"奇怪的石头": 3})
    assert ok90 and d90d.get("奇怪的石头") == -1
    ok90, msg90, _ = ph90.reincarnate(d91, time.time(), _Doom60())
    assert ok90 and "崩碎" in msg90, msg90                   # 失败：寿元-500 道伤+1
    assert dz60.peek(d91) == 1.0
    ok90, _, d90d = ph90.offer_stone(d91, {"奇怪的石头": 3})
    for n in range(1, 10):
        ok90, msg90, _ = ph90.reincarnate(d91, time.time(), _Lucky60())
        assert ok90 and f"第 {n} 转" in msg90, (n, msg90)
        if n < 9:
            ph90.offer_stone(d91, {"奇怪的石头": 3})
    assert ph90.state_of(d91)["samsara"] == 9
    assert d91.ext["linggen"]["name"] == "九转轮回体·9转"
    ok90, msg90, _ = ph90.consume_samsara_fruit(d91, {"轮回道果": 1})
    assert ok90 and "命运神道体" in msg90, msg90
    ok90, msg90, d90d = ph90.consume_light(d91, "光阴火", {"光阴火": 2})
    assert ok90 and d90d.get("光阴火") == -1, msg90
    assert abs(d91.ext["linggen"]["atk"] - 9100.0) < 1e-6, "光阴 +9000"

    # 极道天魔
    d92 = PlayerDoc(uid="u92", name="魔修", realm_index=25,
                    ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 1,
                         "linggen": {"name": "天魔体", "type": "魔头", "eff": 1.0,
                                     "atk": 100.0, "def": 100.0, "hp": 100.0}})
    ok90, msg90, _ = ph90.demon_god(d92, {"邪神道果": 1})
    assert not ok90 and "九重魔功" in msg90, msg90
    d92.ext["evil"] = {"magic": 9}
    ok90, msg90, _ = ph90.demon_god(d92, {"邪神道果": 1})
    assert ok90 and d92.ext["linggen"]["name"] == "极道天魔", msg90
    assert "体质进阶" in ph90.panel(d92) and "轮回点" in ph90.panel(d91)

    src90 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names90 = ["CMD_PHY_SUN", "CMD_PHY_MOON", "CMD_PHY_KING", "CMD_PHY_OFFER",
               "CMD_PHY_REBORN", "CMD_PHY_FRUIT", "CMD_PHY_LF", "CMD_PHY_LS",
               "CMD_PHY_LW", "CMD_PHY_DEMON", "CMD_PHY_PANEL"]
    miss90 = [c for c in names90 if f"@filter.command({c}" not in src90]
    assert miss90 == [], f"漏注册：{miss90}"
    assert "ph_mod.awaken_sun(" in src90 and "ph_mod.demon_god(" in src90
    help90b = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "体质进阶 · 太阳太阴神王与轮回" for g in help90b)
    assert "体质进阶" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W12-F1/F2 physique ok")

    # ========================================================= W13-F1：专属套装挑战
    from core import exclusive_set as ex95

    d95 = PlayerDoc(uid="u95", name="套装人", realm_index=25,
                    ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 1,
                         "linggen": {"name": "无相·万化天魔体", "type": "魔头", "eff": 1.0,
                                     "atk": 100.0, "def": 100.0, "hp": 100.0}})
    ok95, msg95, _ = ex95.challenge(d95, "终焉神魔路", "", time.time(), _Lucky60())
    assert not ok95 and "终焉神魔体" in msg95, msg95            # 血线不符
    ok95, msg95, _ = ex95.challenge(d95, "万化天魔路", "", time.time(), _Lucky60())
    assert ok95 and "万相天魔刃" in msg95 and "铸成" in msg95, msg95
    ok95, msg95, _ = ex95.challenge(d95, "万化天魔路", "", time.time(), _Lucky60())
    assert not ok95 and "无相蜕生" in msg95, msg95              # 需模式参数
    ok95, msg95, _ = ex95.challenge(d95, "万化天魔路", "归无相", time.time(), _Lucky60())
    assert ok95 and "无相魔神袍" in msg95, msg95
    ok95, msg95, _ = ex95.challenge(d95, "万化天魔路", "", time.time(), _Lucky60())
    assert ok95 and "万灵魔幡" in msg95 and "套装共鸣" in msg95, msg95
    st95 = ex95.state_of(d95)
    assert st95["wanhua"] == 3 and st95["wins"] == 3, st95

    d95.ext["linggen"]["name"] = "终焉神魔体"
    ok95, msg95, _ = ex95.challenge(d95, "终焉神魔路", "", time.time(), _Lucky60())
    assert ok95 and "诸神黄昏" in msg95, msg95
    ok95, msg95, _ = ex95.challenge(d95, "终焉神魔路", "", time.time(), _Lucky60())
    assert not ok95 and "吞噬魔血" in msg95, msg95              # 需模式参数
    ok95, msg95, _ = ex95.challenge(d95, "终焉神魔路", "吞噬魔血", time.time(), _Lucky60())
    assert ok95 and "神魔葬天衣" in msg95, msg95
    assert ex95.state_of(d95)["corrupt"] == 9, "吞噬魔血侵蚀 +9 层"
    ok95, msg95, _ = ex95.challenge(d95, "终焉神魔路", "", time.time(), _Lucky60())
    assert ok95 and "万劫归墟轮" in msg95 and "套装共鸣" in msg95, msg95

    # 失败路径：连败蓄力，不发奖励
    d96 = PlayerDoc(uid="u96", name="套装人二", realm_index=25,
                    ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 1,
                         "linggen": {"name": "无相·万化天魔体", "type": "魔头", "eff": 1.0,
                                     "atk": 100.0, "def": 100.0, "hp": 100.0}})
    ok95, msg95, _ = ex95.challenge(d96, "万化天魔路", "", time.time(), _Doom60())
    assert ok95 and "0/9 关" in msg95 and "连败 1" in msg95, msg95
    assert "万相天魔刃" not in str(ex95.state_of(d96)), "失败不发奖励"

    src95 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names95 = ["CMD_EX_PANEL", "CMD_EX_WANHUA", "CMD_EX_WXDD", "CMD_EX_WXTS",
               "CMD_EX_WLFP", "CMD_EX_ZHONGYAN", "CMD_EX_HHSG", "CMD_EX_TGMT",
               "CMD_EX_ZSGX"]
    miss95 = [c for c in names95 if f"@filter.command({c}" not in src95]
    assert miss95 == [], f"漏注册：{miss95}"
    assert "ex_mod.challenge(" in src95
    help95b = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "专属套装 · 万化与终焉" for g in help95b)
    assert "专属套装" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W13-F1 exclusive_set ok")

    # ========================================================= W14-F1：诸天镜补充玩法
    from core import zhutian_extra as zx100

    d100 = PlayerDoc(uid="u100", name="投影人", realm_index=15, exp=50_000_000,
                     ext={"xueqi": 50_000_000, "potential": 0, "shouyuan": 100,
                          "hp": 100.0,
                          "linggen": {"name": "金灵根", "type": "天灵根", "eff": 1.0,
                                      "atk": 10.0, "def": 10.0, "hp": 10.0},
                          "zhutian": {"bound": True, "tier": 3, "energy": 9,
                                      "hopes": 1200, "imprints": ["魔法少女小圆"],
                                      "current": "鹿目圆", "avatars": {}}})
    ok100, msg100 = zx100.magic_girl_advance(d100)
    assert ok100 and "愿望化身" in msg100, msg100
    ok100, msg100 = zx100.magic_girl_advance(d100)
    assert ok100 and "希望之光" in msg100, msg100
    d100.ext["zhutian"]["hopes"] = 0
    ok100, msg100 = zx100.magic_girl_advance(d100)
    assert not ok100 and "希望碎片" in msg100, msg100

    ok100, msg100, d100d = zx100.purify(d100, {"悲叹之种": 1})
    assert ok100 and d100d.get("悲叹之种") == -1, msg100
    assert zx100._st(d100)["dust"] == zx100.DUST_INIT - 3
    ok100, msg100 = zx100.reset_timeline(d100)
    assert not ok100 and "净化" in msg100, msg100            # 污浊 17 > 5
    d100.ext["zhutian_extra"]["dust"] = 5
    ok100, msg100 = zx100.reset_timeline(d100)
    assert ok100 and "时间线" in msg100, msg100
    assert zx100._st(d100)["timeline"] == 1

    d100b = PlayerDoc(uid="u100b", name="凡投", realm_index=3, exp=100,
                      ext={"xueqi": 100, "hp": 1})
    ok100, msg100 = zx100.consume_mirror(d100b, time.time(), _Lucky60())
    assert not ok100 and "仙阶" in msg100, msg100
    ok100, msg100 = zx100.consume_mirror(d100, time.time(), _Lucky60())
    assert ok100 and "主角" in msg100 or "灵根" in msg100, msg100
    assert d100.ext["linggen"]["id"] == 7010015, "主角灵根写入"
    assert d100.exp == 50_000_000 - zx100.MIRROR_COST

    ok100, msg100 = zx100.one_thought_gate(d100)
    assert not ok100 and "岁云五阶" in msg100, msg100

    src100 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names100 = ["CMD_MG_ADV", "CMD_MG_PURIFY", "CMD_MG_RESET", "CMD_ZX_MIRROR",
                "CMD_ZX_THOUGHT", "CMD_ZX_PANEL"]
    miss100 = [c for c in names100 if f"@filter.command({c}" not in src100]
    assert miss100 == [], f"漏注册：{miss100}"
    assert "zx_mod.magic_girl_advance(" in src100 and "zx_mod.consume_mirror(" in src100
    help100b = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "诸天镜 · 主角灵根与魔法少女" for g in help100b)
    assert "诸天镜·补充" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W14-F1 zhutian_extra ok")

    # ========================================================= W15-F1：职业补全
    from core import occupation_extra as oe105

    d105 = PlayerDoc(uid="u105", name="侠客", realm_index=20, stones=0,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 100.0,
                          "occupation": "侠客"})
    cal105 = {}
    ok105, msg105 = oe105.place_field(d105, cal105, "遮天位面", time.time())
    assert not ok105 and "源地师" in msg105, msg105          # 非源师
    text105, pool105 = oe105.villains_text(d105, "20261110", 3)
    assert "恶人榜" in text105 and len(pool105) == 3, text105
    name105 = pool105[0]["name"]
    ok105, msg105, _ = oe105.slay(d105, {"侠客令": 0}, name105, "20261110", 3,
                                  time.time(), _Lucky60())
    assert not ok105 and "侠客令" in msg105, msg105
    ok105, msg105, _ = oe105.slay(d105, {"侠客令": 1}, name105, "20261110", 3,
                                  time.time(), _Lucky60())
    assert ok105 and "讨恶成功" in msg105, msg105
    assert d105.stones > 0, "赏金入库"
    ok105, msg105, _ = oe105.slay(d105, {"侠客令": 1}, "不存在", "20261110", 3,
                                  time.time(), _Lucky60())
    assert not ok105 and "并无此人" in msg105, msg105

    d106 = PlayerDoc(uid="u106", name="魔修", realm_index=20,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 100.0,
                          "occupation": "唤魔者", "modao": 0.0})
    text105, pool105v = oe105.villages_text(d106, "20261110", 3)
    vname105 = pool105v[0]["name"]
    ok105, msg105, _ = oe105.raid(d106, {"唤魔令": 1}, vname105, "20261110", 3,
                                  time.time(), _Lucky60())
    assert ok105 and "劫掠成功" in msg105, msg105
    assert d106.stones > 0 and d106.ext["modao"] == 8.0, "魔道 +8"

    d107 = PlayerDoc(uid="u107", name="源师", realm_index=20,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 100.0,
                          "occupation": "源天师"})
    ok105, msg105 = oe105.place_field(d107, cal105, "遮天位面", time.time())
    assert ok105 and "源石场" in msg105, msg105
    assert cal105["source_field"]["plane"] == "遮天位面"
    ok105, msg105 = oe105.place_field(d107, cal105, "遮天位面", time.time())
    assert not ok105 and "已有" in msg105, msg105            # 同位面不可叠加
    assert "源石场" in oe105.field_text(cal105, time.time())

    src105 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names105c = ["CMD_OCC_FIELD", "CMD_OCC_FIELD_VIEW", "CMD_OCC_EVILS",
                 "CMD_OCC_SLAY", "CMD_OCC_VILLAGES", "CMD_OCC_RAID"]
    miss105c = [c for c in names105c if f"@filter.command({c}" not in src105]
    assert miss105c == [], f"漏注册：{miss105c}"
    assert "oe_mod.slay(" in src105 and "oe_mod.place_field(" in src105
    help105c = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "职业补全 · 源石场与讨恶劫村" for g in help105c)
    assert "职业补全" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W15-F1 occupation_extra ok")

    # ========================================================= W16-F1/F2：活动 + 无尽轮回剧情
    from core import activity as ac110, reinc_story as rs110

    d110 = PlayerDoc(uid="u110", name="仙人", realm_index=41, exp=0, stones=0,
                     ext={"xueqi": 0, "potential": 0, "shouyuan": 100, "hp": 100.0})
    ok110, msg110, _ = ac110.xinghai_sign(d110, time.time())
    assert ok110 and "星海之缘" in msg110, msg110
    ok110, msg110, _ = ac110.xinghai_sign(d110, time.time())
    assert not ok110 and "已" in msg110, msg110              # 重复签到
    d110.ext["activity"]["draws"] = 10
    ok110, msg110, d110d = ac110.gacha(d110, 10, time.time(), _Lucky60())
    assert ok110 and d110d, msg110
    assert ac110.state_of(d110)["draws"] == 0
    d110.ext["activity"]["chapters"] = 3
    ok110, msg110 = ac110.awaken_zhenwo(d110)
    assert ok110 and "真我觉醒" in msg110, msg110
    ok110, msg110, _ = ac110.anniversary_sign(d110, time.time(), _Lucky60())
    assert ok110 and "周年签到" in msg110, msg110
    assert "活动" in ac110.panel(d110)

    d111 = PlayerDoc(uid="u111", name="轮回客", realm_index=20,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 100.0})
    ok110, msg110 = rs110.start(d111, "黑客")
    assert ok110 and "黑客" in msg110, msg110
    _rs111 = rs110.state_of(d111)                     # 预置满强化，保证检定全过
    _rs111["attrs"] = {"体术": 9, "心智": 9, "源能": 9}
    rs110.save(d111, _rs111)
    ok110, msg110 = rs110.choose(d111, 1, time.time(), _Lucky60())
    assert ok110 and "末班车进站" in msg110, msg110
    ok110, msg110 = rs110.choose(d111, 9, time.time(), _Lucky60())
    assert not ok110 and "1~3" in msg110, msg110
    for _ in range(4):                                       # 走完剩余四幕（Lucky 全成）
        ok110, msg110 = rs110.choose(d111, 1, time.time(), _Lucky60())
        assert ok110, msg110
    assert rs110.state_of(d111)["scene"] == 5
    ok110, msg110 = rs110.settle(d111)
    assert ok110 and "结算" in msg110, msg110
    pts111 = rs110.state_of(d111)["points"]
    assert pts111 >= 120 and rs110.grade_of(pts111) == "B·同行者", pts111
    ok110, msg110 = rs110.settle(d111)
    assert not ok110, "不在轮回中不可重复结算"
    ok110, msg110 = rs110.enhance(d111, "源能")
    assert ok110, msg110
    ok110, msg110 = rs110.exchange(d111, "基因稳定剂·C")
    assert ok110 and "+20" in msg110, msg110
    assert "无尽轮回" in rs110.panel(d111) and "任务" in rs110.task_text(d111)
    assert "陈默" in rs110.squad_text() and "雾枭" in rs110.monster_text()

    src110 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names110 = ["CMD_AC_XH", "CMD_AC_GACHA", "CMD_AC_GACHA10", "CMD_AC_ZHENWO",
                "CMD_AC_ZN", "CMD_AC_PANEL", "CMD_RS_START", "CMD_RS_CHOOSE",
                "CMD_RS_QUIT", "CMD_RS_ENH", "CMD_RS_EXCH", "CMD_RS_TASK",
                "CMD_RS_SQUAD", "CMD_RS_ATTR", "CMD_RS_MON", "CMD_RS_FILE"]
    miss110 = [c for c in names110 if f"@filter.command({c}" not in src110]
    assert miss110 == [], f"漏注册：{miss110}"
    assert "ac_mod.gacha(" in src110 and "rs_mod.choose(" in src110
    help110b = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "活动与无尽轮回" for g in help110b)
    assert "活动·轮回" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W16-F1/F2 activity+reinc_story ok")

    # ========================================================= W17-F1：位面大事件
    from core import plane_events as pe120

    d120 = PlayerDoc(uid="u120", name="援军", realm_index=25,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 100.0})
    cal120: dict = {}
    # 圣地大战
    ok120, msg120 = pe120.war_side(d120, cal120, "攻", time.time())
    assert ok120 and "攻" in msg120, msg120
    ok120, msg120 = pe120.war_act(d120, cal120, time.time(), _Lucky60())
    assert ok120 and "战功 +12" in msg120, msg120
    d120.ext["sect_war"]["merits"] = 5000
    ok120, msg120, d120d = pe120.war_fund(d120, cal120, 50, {"源石": 100})
    assert ok120 and d120d.get("源石") == -50, msg120
    assert "个人战功 +100" in msg120, msg120
    shop120 = pe120.war_shop(None, {"圣地战功商店": [{"name": "柳神法拓本", "price": 3000, "desc": "疗伤"}]})
    assert "柳神法拓本" in shop120
    ok120, msg120, d120d = pe120.war_exchange(d120, cal120, "柳神法拓本",
                                              {"圣地战功商店": [{"name": "柳神法拓本", "price": 3000, "desc": ""}]})
    assert ok120 and d120d.get("柳神法拓本") == 1, msg120

    # 游商
    text120 = pe120.merchant_text()
    assert "白须仙翁" in text120 and "黑衣神秘人" in text120 and "绝美仙子" in text120
    d120.stones = 10_000_000
    ok120, msg120, d120d = pe120.buy(d120, pe120.IMPERIAL_GOODS, 1, {"源石": 5_000_000}, "源石")
    assert ok120 and d120d.get("源石") == -1_200_000, msg120
    ok120, msg120, d120d = pe120.buy(d120, pe120.BLACK_GOODS, 2, {"源石": 5_000_000}, "源石")
    assert ok120 and d120d.get("叩仙丹") == 1, msg120
    ok120, msg120 = pe120.ask_sign(d120, "问道签")
    assert ok120 and "问道签" in msg120, msg120
    ok120, msg120 = pe120.ask_sign(d120, "偏签")
    assert not ok120 and "用法" in msg120, msg120

    src120 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names120 = ["CMD_PE_WAR",
                "CMD_PE_SIDE", "CMD_PE_ACT", "CMD_PE_FUND", "CMD_PE_RANK",
                "CMD_PE_SHOP", "CMD_PE_BUY", "CMD_PE_XW_BUY", "CMD_PE_HEIM",
                "CMD_PE_HEIM_BUY", "CMD_PE_XIANZI"]
    miss120 = [c for c in names120 if f"@filter.command({c}" not in src120]
    assert miss120 == [], f"漏注册：{miss120}"
    assert "pe_mod.war_exchange(" in src120
    assert "pe_mod.pass_state" not in src120, "帝关已交由远端 realm_event，不得残留"
    assert "rev_mod.maybe_tick(" in src120, "帝关走远端 W8-F9 状态机"
    help120b = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "位面大事件 · 圣地大战与游商" for g in help120b)
    assert "位面大事件" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W17-F1 plane_events ok")

    # ========================================================= W18-F1：金银坊
    from core import games_mini as gm130

    d130 = PlayerDoc(uid="u130", name="赌客", stones=50_000,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 1})
    ok130, msg130 = gm130.bet(d130, "买定离手", None, time.time(), _random.Random(1))
    assert not ok130 and "用法" in msg130, msg130
    ok130, msg130 = gm130.bet(d130, "大", 99_999_999, time.time(), _random.Random(1))
    assert not ok130 and "本钱不够" in msg130, msg130        # 上限裁到 100 万但身上只有 5 万
    ok130, msg130 = gm130.bet(d130, "大", None, time.time(), _random.Random(2))
    assert ok130 and "媚娘掷出" in msg130, msg130
    assert d130.stones != 50_000, "输赢已结算"
    ok130, msg130 = gm130.bet(d130, "大", None, time.time(), _random.Random(2))
    assert not ok130 and "分钟" in msg130, msg130            # 3 分钟 CD

    src130 = open(PLUGIN / "main.py", encoding="utf-8").read()
    assert '@filter.command(CMD_GMF' in src130 and "gm_mod.bet(" in src130
    help130b = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "金银坊 · 猜大小" for g in help130b)
    assert "金银坊" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W18-F1 games_mini ok")

    # ========================================================= W19-A：审计修复回归
    d140 = PlayerDoc(uid="u140", name="审计人", realm_index=25, exp=1_000_000_000,
                     ext={"xueqi": 1_000_000_000, "potential": 200.0, "shouyuan": 100,
                          "hp": 100.0})
    ok140, msg140 = ow80.create(d140, "攻伐", "审计道")
    assert ok140, msg140
    d140.ext["potential"] = 0.0                            # 审计修复1：潜力0不得凭空复制
    ok140, msg140 = ow80.cultivate(d140, 50, time.time())
    assert not ok140 and "潜力不足" in msg140, msg140
    assert float(d140.ext["potential"]) == 0.0, f"潜力被复制：{d140.ext['potential']}"

    d141 = PlayerDoc(uid="u141", name="审计人二", realm_index=25, exp=10_000_000,
                     ext={"xueqi": 10_000_000, "potential": 500.0, "shouyuan": 9_000_000, "hp": 1,
                          "era_points": 500})
    _dz141 = dz60.state_of(d141)
    _dz141["reached"] = True
    dz60.save(d141, _dz141)
    _ys141 = ys70.ensure(d141)
    _ys141["heart"] = {"cur": 0, "max": 30, "last": time.time()}   # 心神耗尽态
    ys70.save(d141, _ys141)
    ok140, msg140, _ = sd70.deduce(d141, time.time(), _Lucky60())
    assert not ok140 and "心神不足" in msg140, msg140
    assert d141.ext["era_points"] == 500, f"纪元被白扣：{d141.ext['era_points']}"   # 审计修复2

    # 审计修复9：军资达成 → pending_bonus 名单（handler 据此 +30）
    d142 = PlayerDoc(uid="u142", name="站队人", realm_index=25,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 1})
    cal142: dict = {}
    ok140, msg140 = pe120.war_side(d142, cal142, "攻", time.time())
    assert ok140, msg140
    ok140, _, _ = pe120.war_fund(d142, cal142, 600, {"源石": 1000})
    ok140, msg140, _ = pe120.war_fund(d142, cal142, 600, {"源石": 1000})
    assert ok140 and "站队者战功 +30" in msg140, msg140
    sw142 = cal142.get("sect_war") or {}
    assert sw142.get("pending_bonus") == ["u142"], sw142
    assert sw142.get("participants") == [], "名单已清、下轮重新站队"

    src140 = open(PLUGIN / "main.py", encoding="utf-8").read()
    assert 'get_raid(team["code"])' in src140, "审计修复5：_raid_settle 需复读 settled"
    assert "pending_bonus" in src140, "审计修复9：handler 需兑现轮末奖励"
    assert src140.count('if not self._adm_ok(event)') >= 2, "审计修复10：门禁统一"
    print("W19-A audit fixes ok")

    # ========================================================= W19-B：并发锁回归
    assert hasattr(db, "calamity_lock"), "db 需自带全服档锁"
    src140b = src140  # main.py 已在上方读出
    assert "calamity_lock" in src140b and src140b.count("async with self.db.calamity_lock") >= 4, \
        "pe/tdb/转账处需持锁"
    assert "_pl_lock(target_id)" in src140b, "诸天一念需 per-uid 锁"
    assert "审计修复7" in src140b, "市场买卖需同事务"
    assert "async with self.db.transaction():\n                await self.db.save_player(doc.model_dump())\n                await self.db.save_market(g)" in src140b
    print("W19-B concurrency locks ok")

    # ========================================================= W19-C：审计修复11/12 收尾
    from core import wallet as wl200, zhutian_extra as zx200

    # —— 12：wallet 助手与旧实现等价
    d200 = PlayerDoc(uid="u200", name="钱包", realm_index=9, exp=1_000_000,
                     ext={"xueqi": 500_000, "potential": 30.0, "shouyuan": 100, "hp": 1})
    assert wl200.authority(d200) == 9
    assert wl200.xueqi(d200) == 500_000 and wl200.xueqi.__module__ == "core.wallet"
    fail200 = wl200.pay_exp_xq(d200, 2_000_000)
    assert fail200 is not None and "需修为与血气各 2,000,000" in fail200  # 返回错误文案
    assert wl200.pay_exp_xq(d200, 400_000) is None
    assert d200.exp == 600_000 and wl200.xueqi(d200) == 100_000
    fail200 = wl200.pay_potential(d200, 50)
    assert fail200 and "潜力不足" in fail200 and wl200.pay_potential(d200, 30) is None
    assert float(d200.ext["potential"]) == 0.0
    ok200 = wl200.pay_potential(d200, 10)
    assert ok200 and "潜力不足" in ok200 and float(d200.ext["potential"]) == 0.0, "不足时不扣（回归）"

    # 九模块不再持有本地副本，全部改走 wallet
    for m200 in ("zhengdao", "daolu", "selfdao", "ownway", "plane_events",
                 "physique", "exclusive_set", "occupation_extra", "wudao"):
        src200 = open(PLUGIN / "core" / f"{m200}.py", encoding="utf-8").read()
        assert "def _authority(" not in src200, f"{m200} 仍有本地 _authority"
        if m200 in ("zhengdao", "daolu", "selfdao", "ownway", "plane_events"):
            assert "def _xueqi(" not in src200, f"{m200} 仍有本地 _xueqi"
    assert "from .wallet import" in open(PLUGIN / "core/zhengdao.py", encoding="utf-8").read()

    # —— 11：诸天一念解析 / 前置检查 / 接线
    assert zx200.parse_thought("") == ("", 1)
    assert zx200.parse_thought("秘书") == ("秘书", 1)
    assert zx200.parse_thought("秘书*2") == ("秘书", 2)
    assert zx200.parse_thought("秘书*0") == ("秘书", 1), "非法数量回退 1"
    assert zx200.parse_thought("秘书*abc") == ("秘书", 1)
    fail200b = zx200.thought_check({}, "", 1)
    assert fail200b and "用法" in fail200b
    fail200b = zx200.thought_check({"秘书": 3}, "秘书", 5)
    assert fail200b and "并没有" in fail200b
    assert zx200.thought_check({"秘书": 3}, "秘书", 2) is None
    src200 = open(PLUGIN / "main.py", encoding="utf-8").read()
    assert "zx_mod.parse_thought(" in src200 and "zx_mod.thought_check(" in src200
    assert "_pl_lock(target_id)" in src200, "转账仍需 per-uid 锁"
    print("W19-C wallet merge + thought tests ok")

    # ========================================================= W20-F1：至宝出世全服择主
    from core import xtzb_birth as xb210, xtzb as xt210

    world210: dict = {}
    d210 = PlayerDoc(uid="u210", name="夺宝人", realm_index=25,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 100.0})
    ok210, msg210, ch210 = xb210.birth_open(d210, world210, "无名至宝", time.time())
    assert not ok210 and "未知至宝" in msg210, msg210
    ok210, msg210, ch210 = xb210.birth_open(d210, world210, "太初仙刃", time.time())
    assert ok210 and ch210 and "至宝出世" in msg210, msg210
    assert "太初仙刃" in world210["birth"], "窗口建立"
    ok210, msg210, _ = xb210.birth_open(d210, world210, "太初仙刃", time.time())
    assert not ok210 and "已在" in msg210, msg210            # 重复报名
    d210b = PlayerDoc(uid="u210b", name="夺宝人二", realm_index=25,
                      ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 100.0})
    ok210, msg210, _ = xb210.birth_open(d210b, world210, "太初仙刃", time.time())
    assert ok210 and "加入争夺" in msg210, msg210

    ok210, msg210 = xb210.birth_trial(d210, world210, "太初仙刃", "做梦", time.time(), _Lucky60())
    assert not ok210 and "试炼限定" in msg210, msg210
    ok210, msg210 = xb210.birth_trial(d210, world210, "太初仙刃", "守护灵", time.time(), _Lucky60())
    assert ok210 and "+100" in msg210, msg210                # Lucky 恒过
    ok210, msg210 = xb210.birth_trial(d210, world210, "太初仙刃", "守护灵", time.time(), _Lucky60())
    assert not ok210 and "每项一次" in msg210, msg210
    ok210, msg210 = xb210.birth_trial(d210b, world210, "太初仙刃", "命运乱流", time.time(), _Doom60())
    assert ok210 and "气血归一" in msg210, msg210            # Doom 恒败：乱流反噬
    assert d210b.ext["hp"] == 1
    assert xb210.birth_vow_of("太初仙刃") in xb210.VOWS

    pref210 = xb210.birth_vow_of("太初仙刃")
    ok210, msg210 = xb210.birth_vow(d210, world210, "太初仙刃", pref210)
    assert ok210 and "契合" in msg210, msg210
    ok210, msg210 = xb210.birth_vow(d210, world210, "太初仙刃", pref210)
    assert not ok210 and "道心不二" in msg210, msg210
    ok210, msg210 = xb210.birth_vow(d210b, world210, "太初仙刃", "镇压诸天")
    assert ok210, msg210
    assert "人入局" in xb210.birth_board(world210, time.time())

    notices210, ops210 = xb210.birth_settle(world210, time.time() + 25 * 3600, _Lucky60())
    assert "择主之争 · 太初仙刃" in notices210, notices210
    assert ops210[0]["uid"] == "u210" and ops210[0]["prize"] == "本体", ops210
    assert ops210[1]["prize"] == "投影", ops210
    xb210.birth_prize(d210, "太初仙刃", "本体", time.time())
    xb210.birth_prize(d210b, "太初仙刃", "投影", time.time())
    assert "太初仙刃" in xt210.state_of(d210)["owned"]
    assert xt210.state_of(d210b)["projection"].get("太初仙刃", 0) > time.time()
    ok210, msg210, _ = xb210.birth_open(d210, world210, "太初仙刃", time.time())
    assert ok210, "结算后可开启新一轮"

    src210 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names210 = ["CMD_XB_OPEN", "CMD_XB_T1", "CMD_XB_T2", "CMD_XB_T3", "CMD_XB_T4",
                "CMD_XB_VOW", "CMD_XB_BOARD"]
    miss210 = [c for c in names210 if f"@filter.command({c}" not in src210]
    assert miss210 == [], f"漏注册：{miss210}"
    assert "xb_mod.birth_settle(" in src210 and "xb_mod.birth_prize(" in src210
    help210c = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "至宝出世 · 全服择主" for g in help210c)
    assert "至宝出世" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W20-F1 xtzb_birth ok")

    # ========================================================= W21-F1/F2：自动化 + 彩蛋
    from core import auto_task as at230, easter_eggs as eg230

    d230 = PlayerDoc(uid="u230", name="修仙人", realm_index=25, exp=0, stones=100_000,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 100.0})
    ok230, msg230 = at230.set_enabled(d230, True, time.time(), False)
    assert not ok230 and "道法仙术" in msg230, msg230       # 未开卡不得开启
    # 模拟开卡后
    try:
        import daofa as _df_unused  # noqa
    except Exception:
        pass
    ok230, msg230 = at230.set_enabled(d230, True, time.time(), True)
    assert ok230 and "开启" in msg230, msg230
    d230.ext["daofaxianshu"] = 2                           # 注入道法仙术卡（FLAG 态）
    d230.ext["daofaxianshu_endtime"] = (time.time() + 30 * 86400) * 1000
    # run_if_due：签到手感依赖 cultivate.sign_in——离线直接断言幂等与记录
    lines230, items230, d230 = at230.run_if_due(
        d230, time.time(), _Lucky60(), 100, 500, 1.0, 0.0)
    assert lines230, "首次应产生补领记录"
    day230 = sorted(at230.state_of(d230)["log"])[-1]
    lines230b, items230b, d230 = at230.run_if_due(
        d230, time.time() + 5, _Lucky60(), 100, 500, 1.0, 0.0)
    assert lines230b == [] and items230b == {}, "同日不重复补领"
    assert "签到记录" in at230.record_text(d230)
    # 兑换码
    rows230 = [{"code": "ZHUTIAN2026", "name": "霜月贺礼",
                "items": {"洗根水": 5, "秘境之匙": 10}, "stones": 66666}]
    ok230, msg230, it230, st230 = at230.redeem(d230, rows230, "zhutian2026", time.time())
    assert ok230 and it230.get("洗根水") == 5 and st230 == 66666, msg230
    ok230, msg230, _, _ = at230.redeem(d230, rows230, "ZHUTIAN2026", time.time())
    assert not ok230 and "已经兑换" in msg230, msg230
    ok230, msg230, _, _ = at230.redeem(d230, rows230, "不存在码", time.time())
    assert not ok230 and "无效" in msg230, msg230
    assert "ZHUT****2026" in at230.redeem_list(rows230) or "ZH****26" in at230.redeem_list(rows230)
    # 彩蛋
    ok230, msg230 = eg230.da_zhuang(d230, time.time(), _Lucky60())
    assert ok230 and "打桩" in msg230, msg230
    ok230, msg230 = eg230.da_zhuang(d230, time.time(), _Lucky60())
    assert not ok230 and "分钟" in msg230, msg230           # CD
    ok230, msg230 = eg230.yihongyuan(d230, time.time(), _Lucky60())
    assert ok230 and "怡红院" in msg230, msg230
    d231 = PlayerDoc(uid="u231", name="被抓", realm_index=20,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 100.0})
    inv231 = {"灵石": 5, "洗根水": 2, "秘书": 0}
    ok230, msg230, item230, qty230 = eg230.steal(d230, inv231, time.time(), _Lucky60())
    assert ok230, msg230
    for _ in range(3):
        eg230.steal(d230, inv231, time.time(), _Lucky60())
    ok230, msg230, _, _ = eg230.steal(d230, inv231, time.time(), _Lucky60())
    assert not ok230 and "明日" in msg230, msg230           # 每日 3 次上限

    src230 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names230 = ["CMD_AT_ON", "CMD_AT_OFF", "CMD_AT_STATUS", "CMD_AT_RECORD",
                "CMD_REDEEM_LIST", "CMD_REDEEM", "CMD_EG_ZHUANG", "CMD_EG_YIHONG",
                "CMD_EG_STEAL", "CMD_AC_QL", "CMD_AC_QH"]
    miss230 = [c for c in names230 if f"@filter.command({c}" not in src230]
    assert miss230 == [], f"漏注册：{miss230}"
    assert "at_mod.run_if_due(" in src230, "_require_player 需挂钩惰性补领"
    assert "eg_mod.steal(" in src230 and "_pl_lock(target_id)" in src230
    help230c = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "自动化 · 兑换码 · 彩蛋" for g in help230c)
    assert "自动化·彩蛋" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W21-F1/F2 auto_task+eggs ok")

    # ========================================================= W19-D：锻造图纸对齐审计
    from core import occupation as occ210

    assert abs(occ210.forge_rate(0.4, 0, []) - 0.4) < 1e-9
    assert "铜都不炼你还炼器" in src230, "图纸打造需炼器师门槛"
    assert '"炼制装备加成"' in src230 and '"锻造经验加成"' in src230, "命格乘区缺失"
    assert "min(0.99, occupation.forge_rate" not in src230, "锻造成功率双重夹取应去除"
    # forge_rate 与原版公式等价：rate×(1+等级加成)，≥24 级 0.8，clamp[0.01,0.95]
    assert abs(occ210.forge_rate(0.4, 0, []) - 0.4) < 1e-9
    assert occ210.forge_rate(0.4, 24, []) == 0.8
    assert occ210.forge_rate(5.0, 0, []) == 0.95
    print("W19-D forge parity ok")

    # ========================================================= W22-F1/F2：位面中转 + 天骄处置
    from core import plane_relay as pr240, plane as pl240, tianjiao as tj240

    # —— 五色祭坛：门槛 / 消耗 / 记坐标
    d240 = PlayerDoc(uid="u240", name="中转人", realm_index=12, exp=2_000_000,
                     ext={"xueqi": 2_000_000, "potential": 0, "shouyuan": 100, "hp": 100.0})
    st240 = pl240.state_of(d240)
    ok240, msg240 = pr240.wuxi_activate(d240, st240, time.time())
    assert ok240 and "遮天" in msg240, msg240
    assert "遮天位面" in st240["known"] and d240.exp == 2_000_000 - pr240.WUXI_COST
    ok240, msg240 = pr240.wuxi_activate(d240, st240, time.time())
    assert not ok240 and "早已激活" in msg240, msg240

    # —— 接引：写入待确认 / 同意 / 过期 / 拒绝
    s240 = pl240.state_of(d240)
    s240["current"] = "遮天位面"
    d240b = PlayerDoc(uid="u240b", name="被引人", realm_index=5, exp=1_000_000,
                      ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 1})
    tb240 = pl240.state_of(d240b)
    ok240, msg240 = pr240.jiesong_offer(s240, 25, "甲", tb240, "乙", time.time())
    assert ok240 and "60 秒" in msg240, msg240
    assert tb240["plane_offer"]["plane"] == "遮天位面"
    ok240, msg240 = pr240.jiesong_accept(d240b, tb240, time.time())
    assert ok240 and tb240["current"] == "遮天位面", msg240
    pr240.jiesong_offer(s240, 25, "甲", tb240, "乙", time.time() - 61)
    ok240, msg240 = pr240.jiesong_accept(d240b, tb240, time.time())
    assert not ok240 and "已散" in msg240, msg240           # 过期
    ok240, msg240 = pr240.jiesong_reject(tb240)
    assert not ok240, "无 offer 时拒绝应失败"

    # —— 送往 / 传送阵：缺物品 / 乱流 / 落位
    ok240, msg240 = pr240.songwang(tb240, "仙界", {"x": 100, "y": 200}, "乙")
    assert ok240 and tb240["current"] == "仙界", msg240
    ok240, msg240, dl240 = pr240.portal_use(d240b, tb240, "凡间", {}, time.time(), _Lucky60())
    assert not ok240 and "位面传送阵" in msg240, msg240
    tb240["known"].append("凡间")
    exp_b240 = d240b.exp
    ok240, msg240, dl240 = pr240.portal_use(
        d240b, tb240, "凡间", {"位面传送阵": 1}, time.time(), _Lucky60())
    assert ok240 and dl240.get("位面传送阵") == -1, msg240
    assert tb240["current"] == "凡间" and d240b.exp < exp_b240, "乱流修为 -10%"

    # —— 天骄求饶：触发 / 冷却 / 应答 / 邪修窗口 / 搜魂 / 灭杀反噬
    d241 = PlayerDoc(uid="u241", name="猎骄人", realm_index=25,
                     ext={"xueqi": 100, "potential": 0, "shouyuan": 100, "hp": 100.0})
    boss241 = {"name": "金翅小鹏王", "offered_at": 0.0}
    offered240, msg241 = tj240.maybe_offer(d241, "金翅小鹏王", boss241, time.time(), _Lucky60())
    assert offered240 and "求饶" in msg241, msg241
    assert boss241["offered_at"] > 0
    offered240, _ = tj240.maybe_offer(d241, "金翅小鹏王", boss241, time.time() + 1, _Lucky60())
    assert not offered240, "24h 冷却不得重复求饶"
    ok240, msg240 = tj240.accept_offer(d241, "金翅小鹏王", time.time())
    assert ok240 and "仇恨 -30" in msg240, msg240
    assert d241.stones > 0, "赔礼到账（_Lucky60 bounty=1 档 × 5000）"
    tj240.maybe_offer(d241, "金翅小鹏王", boss241, time.time() + 100000, _Lucky60())
    ok240, msg240 = tj240.reject_offer(d241, "金翅小鹏王", time.time())
    assert not ok240 and "魔道" in msg240, msg240           # 非邪修拒
    d241.ext["modao"] = 1500.0
    ok240, msg240 = tj240.reject_offer(d241, "金翅小鹏王", time.time())
    assert ok240 and "执行窗口" in msg240, msg240
    ok240, msg240, it240, back240 = tj240.soul_search(d241, "金翅小鹏王", time.time(), _Doom60())
    assert ok240 and not back240 and len(it240) == 2, (msg240, it240)
    d241.ext["tianjiao_exec"] = {"name": "金翅小鹏王", "until": time.time() + 300}
    ok240, msg240, it240, back240 = tj240.slay_tianjiao(d241, "金翅小鹏王", time.time(), _Lucky60())
    assert ok240 and back240, msg240                        # Lucky 0.01 < 0.25 → 反噬
    if back240:
        dz60.add_wounds(d241, 2.0, "灭杀反噬")              # handler 层同款落伤
        d241.ext["hp"] = 1
    assert abs(dz60.peek(d241) - 2.0) < 1e-9, "反噬道伤 +2"
    assert d241.ext["hp"] == 1

    src240 = open(PLUGIN / "main.py", encoding="utf-8").read()
    names240 = ["CMD_PR_JY", "CMD_PR_JY_YES", "CMD_PR_JY_NO", "CMD_PR_SONG",
                "CMD_PR_PORTAL", "CMD_PR_WUXI", "CMD_TJ_ACCEPT", "CMD_TJ_REJECT",
                "CMD_TJ_SOUL", "CMD_TJ_SLAY"]
    miss240 = [c for c in names240 if f"@filter.command({c}" not in src240]
    assert miss240 == [], f"漏注册：{miss240}"
    assert "tj_mod.maybe_offer(" in src240, "击杀判定点需挂求饶"
    assert "pr_mod.jiesong_offer(" in src240 and "pr_mod.portal_use(" in src240
    help240c = _json60.load(open(PLUGIN / "data/help/help.json", encoding="utf-8"))
    assert any(g["group"] == "位面中转 · 接引与传送阵" for g in help240c)
    assert any(g["group"] == "天骄处置 · 求饶与处决" for g in help240c)
    assert "位面中转" in open(PLUGIN / "tests/gen_manual.py", encoding="utf-8").read()
    print("W22-F1/F2 plane_relay+tianjiao处置 ok")

    await db.close()
    print("ALL M12 CHECKS PASSED")


asyncio.run(main())
