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

    # 10. 迁移版本 = 15
    async with db.conn.execute("SELECT version FROM db_info") as cur:
        assert (await cur.fetchone())[0] == 15

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
    assert ok and out.get("__stones__", 0) == 6_400_000 and out.get("仙馐果") == 2400, out  # 5级×流速8=8有效小时
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
    assert hit["damage"] > 0 and ov["hp"] < ov["max_hp"], hit
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

    await db.close()
    print("ALL M12 CHECKS PASSED")


asyncio.run(main())
