# W33d：三玩法接线（剑云海/一键出售/再入仙途）——最终正确版
import ast
import re as _re

NL = chr(10)
src = open('main.py', encoding='utf-8').read()
assert 'handle_jyh_visit' not in src, 'already wired'

# faction 模块名：from .core import ... faction, ...（无别名）→ faction
FAC = 'faction'

# ---- 1) CMD 常量
anchor = 'CMD_MOJIE = "#堕入魔界"'
assert anchor in src and 'CMD_JYH_VISIT' not in src
src = src.replace(anchor, anchor + NL +
    '# W33c：原版 replyOfficialMessage 玩法对齐——剑云海机缘/一键出售/再入仙途' + NL +
    'CMD_JYH_VISIT = "#造访剑云海"' + NL +
    'CMD_JYH_RULES = "#剑云海规则"' + NL +
    'CMD_SELL_ALL = "#一键出售"' + NL +
    'CMD_REBIRTH = "#再入仙途"', 1)

# ---- 2) import sellall
old_imp = ' tianji as tjge_mod,'
assert old_imp in src
src = src.replace(old_imp, old_imp + ' sellall as sa_mod,', 1)

# ---- 3) db.delete_player_bundle（infra/db.py）
dbsrc = open('infra/db.py', encoding='utf-8').read()
if 'delete_player_bundle' not in dbsrc:
    anchor_db = '    async def get_player(self, uid: str)'
    assert anchor_db in dbsrc
    method = (
        '    async def delete_player_bundle(self, uid: str) -> None:' + NL +
        '        """W33c：再入仙途——删除玩家全部档案行（players/inventory/daily_tasks/' + NL +
        '        boss_ledger/dark_ledger/raid_member）。全局单例与队伍表不动。"""' + NL +
        '        assert self.conn is not None' + NL +
        '        owned = not self.conn.in_transaction' + NL +
        '        for table in ("players", "inventory", "daily_tasks", "boss_ledger",' + NL +
        '                      "dark_ledger", "raid_member"):' + NL +
        '            await self.conn.execute(f"DELETE FROM {table} WHERE uid = ?", (uid,))' + NL +
        '        if owned:' + NL +
        '            await self.conn.commit()' + NL +
        NL
    )
    dbsrc = dbsrc.replace(anchor_db, method + anchor_db, 1)
    open('infra/db.py', 'w', encoding='utf-8', newline=NL).write(dbsrc)
    ast.parse(dbsrc)
    print('db.delete_player_bundle added')

# ---- 4) handlers 块（追加类尾）——全部单行字符串，无多行 f-string
L = []
A = L.append
A('')
A('')
A('    # ==============================================================')
A('    # W33c：剑云海机缘 / 一键出售 / 再入仙途')
A('')
A('    @filter.command(CMD_JYH_VISIT, "造访剑云海（成仙+令牌，三选机缘）")')
A('    async def handle_jyh_visit(self, event: AstrMessageEvent):')
A('        if not self._allowed(event):')
A('            return')
A('        doc, err = await self._require_player(event)')
A('        if err:')
A('            yield event.plain_result(err)')
A('            return')
A('        inv = await self.db.get_inventory(doc.uid)')
A('        ok, msg, cost = ' + FAC + '.jyh_visit(doc, inv, int(doc.realm_index), int(doc.stones or 0))')
A('        if ok and cost:')
A('            async with self.db.transaction():')
A('                await self.db.remove_item(doc.uid, ' + FAC + '.JYH_ITEM, cost)')
A('        yield event.plain_result(msg)')
A('        # W33：原版 shili L1227 三选按钮')
A('        if ok:')
A('            r_ = _uk_row([')
A('                _uk_btn("jyh.c1", "💎修炼资源", a1=1, uid=doc.uid, style="primary"),')
A('                _uk_btn("jyh.c2", "⚔️拜师传人", a1=2, uid=doc.uid, style="primary"),')
A('                _uk_btn("jyh.c3", "🛡帝主庇护", a1=3, uid=doc.uid, style="primary")],')
A('                fallback="#剑云海选择1/2/3（仅一次）", timeout=600)')
A('            res = self._kb(event, "请择机缘（仅一次，不可重选）：", r_)')
A('            if res:')
A('                yield res')
A('')
A('    @filter.command(CMD_JYH_RULES, "剑云海机缘规则")')
A('    async def handle_jyh_rules(self, event: AstrMessageEvent):')
A('        yield event.plain_result(' + FAC + '.jyh_rules())')
A('')
A('    async def handle_jyh_choose(self, event: AstrMessageEvent, choice: str = ""):')
A('        if not self._allowed(event):')
A('            return')
A('        doc, err = await self._require_player(event)')
A('        if err:')
A('            yield event.plain_result(err)')
A('            return')
A('        inv = await self.db.get_inventory(doc.uid)')
A('        ok, msg, delta, stones = ' + FAC + '.jyh_choose(')
A('            doc, int(choice or 0),')
A('            lambda name, qty: int((inv or {}).get(name, 0) or 0) >= qty)')
A('        if ok:')
A('            async with self.db.transaction():')
A('                await self.db.save_player(doc.model_dump())')
A('                for n, q in (delta or {}).items():')
A('                    if q > 0:')
A('                        await self.db.add_items(doc.uid, {n: q})')
A('                    elif q < 0:')
A('                        await self.db.remove_item(doc.uid, n, -q)')
A('        yield event.plain_result(msg)')
A('')
A('    @filter.command(CMD_SELL_ALL, "一键出售（清点可售物品，按钮确认）")')
A('    async def handle_sell_all(self, event: AstrMessageEvent):')
A('        if not self._allowed(event):')
A('            return')
A('        doc, err = await self._require_player(event)')
A('        if err:')
A('            yield event.plain_result(err)')
A('            return')
A('        inv = await self.db.get_inventory(doc.uid)')
A('        list_text, total, sellable = sa_mod.preview(doc, inv, self.item_index.get)')
A('        if not sellable:')
A('            yield event.plain_result("纳戒里没有可出售的物品（关键道具与不可交易物除外）。")')
A('            return')
A('        doc.ext["sellall_pending"] = sellable')
A('        await self._pe_save(doc, {})')
A('        head = (f"【一键出售确认】物品 {sum(sellable.values())} 件｜预估总价 {total:,} 灵石。\\n"')
A('                + "> 会出售清单内全部物品。\\n" + list_text)')
A('        yield event.plain_result(head)')
A('        # W33：原版 UserSellAll L1619 确认按钮')
A('        r_ = _uk_row([_uk_btn("sell.yes", "✅确认出售", uid=doc.uid, style="danger"),')
A('                      _uk_btn("sell.no", "❌取消", uid=doc.uid)],')
A('                     fallback="回复 1 确认 / 0 取消", timeout=120)')
A('        res = self._kb(event, "请确认出售：", r_)')
A('        if res:')
A('            yield res')
A('')
A('    async def handle_sell_yes(self, event: AstrMessageEvent):')
A('        if not self._allowed(event):')
A('            return')
A('        doc, err = await self._require_player(event)')
A('        if err:')
A('            yield event.plain_result(err)')
A('            return')
A('        sellable = doc.ext.pop("sellall_pending", None)')
A('        if not isinstance(sellable, dict) or not sellable:')
A('            yield event.plain_result("当前没有待确认的一键出售，请先 #一键出售。")')
A('            return')
A('        inv = await self.db.get_inventory(doc.uid)')
A('        msg, stones, delta = sa_mod.execute(doc, inv, sellable, self.item_index.get)')
A('        async with self.db.transaction():')
A('            await self.db.save_player(doc.model_dump())')
A('            for n, q in (delta or {}).items():')
A('                await self.db.remove_item(doc.uid, n, -q)')
A('        yield event.plain_result(msg)')
A('')
A('    async def handle_sell_no(self, event: AstrMessageEvent):')
A('        doc = await self._find_player(event)')
A('        if doc:')
A('            doc.ext.pop("sellall_pending", None)')
A('            await self._pe_save(doc, {})')
A('        yield event.plain_result("已取消出售。")')
A('')
A('    @filter.command(CMD_REBIRTH, "再入仙途（断绝此生，清档重开，按钮确认）")')
A('    async def handle_rebirth(self, event: AstrMessageEvent):')
A('        if not self._allowed(event):')
A('            return')
A('        doc, err = await self._require_player(event)')
A('        if err:')
A('            yield event.plain_result(err)')
A('            return')
A('        count = int(float((doc.ext or {}).get("rebirth_count", 0) or 0))')
A('        if count >= 3:')
A('            yield event.plain_result("你已断绝此生 3 次，此路已到尽头。")')
A('            return')
A('        doc.ext["rebirth_pending"] = True')
A('        await self._pe_save(doc, {})')
A('        yield event.plain_result(')
A('            f"【转世重生确认】一旦转世，当世一切与你无缘（已断绝 {count}/3 次）。\\n"')
A('        # W33：原版 UserStart L81 确认按钮')
A('        r_ = _uk_row([_uk_btn("rebirth.yes", "☠断绝此生", uid=doc.uid, style="danger"),')
A('                      _uk_btn("rebirth.no", "🌸再继仙缘", uid=doc.uid, style="success")],')
A('                     fallback="断绝此生 / 再继仙缘", timeout=120)')
A('        res = self._kb(event, "请抉择（120 秒内）：", r_)')
A('        if res:')
A('            yield res')
A('')
A('    async def handle_rebirth_yes(self, event: AstrMessageEvent):')
A('        if not self._allowed(event):')
A('            return')
A('        doc, err = await self._require_player(event)')
A('        if err:')
A('            yield event.plain_result(err)')
A('            return')
A('        if not (doc.ext or {}).pop("rebirth_pending", None):')
A('            yield event.plain_result("请先发送 #再入仙途 发起转世。")')
A('            return')
A('        count = int(float((doc.ext or {}).get("rebirth_count", 0) or 0)) + 1')
A('        old_name = doc.name')
A('        from .core.cultivate import create_player as _cp')
A('        table = self.content.table(doc.realm_table)')
A('        fresh = _cp(doc.uid, old_name or "无名修士", table)')
A('        fresh.ext["rebirth_count"] = count')
A('        async with self.db.transaction():')
A('            await self.db.delete_player_bundle(doc.uid)')
A('            await self.db.save_player(fresh.model_dump())')
A('        yield event.plain_result(')
A('            f"【断绝此生·第 {count} 次】前尘尽散，新生已启——{old_name or "无名修士"} 重入凡尘。\\n"')
A('        yield event.plain_result("发送 #状态 开启新的仙途。（存档已重置）")')
A('')
A('    async def handle_rebirth_no(self, event: AstrMessageEvent):')
A('        doc = await self._find_player(event)')
A('        if doc:')
A('            doc.ext.pop("rebirth_pending", None)')
A('            await self._pe_save(doc, {})')
A('        yield event.plain_result("再继仙缘——当前存档已保留。")')
block = NL.join(L)

src = src.rstrip(NL) + NL + NL + block + NL

# ---- 5) 分发器路由扩充
old = '''            "hb.grab": ("handle_hb_grab", str(a1 or "")),
            # W33：原版 replyOfficialMessage 全量对齐路由'''
new = old + NL + (
'''            "jyh.c1": ("handle_jyh_choose", "1"),
            "jyh.c2": ("handle_jyh_choose", "2"),
            "jyh.c3": ("handle_jyh_choose", "3"),
            "sell.yes": ("handle_sell_yes", ""),
            "sell.no": ("handle_sell_no", ""),
            "rebirth.yes": ("handle_rebirth_yes", ""),
            "rebirth.no": ("handle_rebirth_no", ""),''')
assert old in src, 'routes anchor'
src = src.replace(old, new, 1)

# 参数化集合扩充（jyh.c* 带参数）
old = '''            if act in ("tj.accept", "tj.reject", "xb.t1", "xb.t2", "xb.t3",
                       "xb.t4", "xb.vow", "hb.grab", "pup.destroy", "tb.join",
                       "tr.join", "page.cmd"):'''
new = '''            if act in ("tj.accept", "tj.reject", "xb.t1", "xb.t2", "xb.t3",
                       "xb.t4", "xb.vow", "hb.grab", "pup.destroy", "tb.join",
                       "tr.join", "page.cmd", "jyh.c1", "jyh.c2", "jyh.c3"):'''
assert old in src
src = src.replace(old, new, 1)

open('main.py', 'w', encoding='utf-8', newline=NL).write(src)
ast.parse(src)
print('W33d wired, AST OK')
