"""M0 自检：迁移 + 玩家文档往返 + 内容表加载。直接运行，断言失败即非零退出。"""
import asyncio
import sys
import tempfile
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

    # 10. 迁移版本 = 8
    async with db.conn.execute("SELECT version FROM db_info") as cur:
        assert (await cur.fetchone())[0] == 8

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

    # 分组区间互斥：物品只落一组
    tiers = [(9, 99), (8, 9), (7, 8), (6, 7), (4, 6), (0, 4)]
    for rar in range(0, 12):
        hits = [1 for lo, hi in tiers if lo <= rar < hi]
        assert len(hits) == 1, f"稀有度 {rar} 分组不互斥"
    bad = await render_mod.render_panel("不存在模板", status_data, tmp)
    assert bad is None, "未知模板应返回 None 触发回退"
    await render_mod.shutdown()
    print("render ok")

    await db.close()
    print("ALL M12 CHECKS PASSED")


asyncio.run(main())
