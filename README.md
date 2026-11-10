# astrbot_plugin_zhutian · 诸天修仙（Python 移植版）

AstrBot 修仙群聊插件——Yunzai JS 原版 [`mo-wuming/zhutianxiuxian1.0`](https://gitee.com/mo-wuming/zhutianxiuxian1.0)（原作者 [@DD斩首](https://gitee.com/hutao222)）的 **Python 全量移植**（`python-port` 分支，移植者 [@yesu666](https://gitee.com/yesu666)）。

> 玩家向玩法指南见 [`docs/游玩说明.md`](docs/游玩说明.md)；全部指令速查由 `tests/gen_manual.py` 生成《指令手册》（1028 条常量 / 53 个帮助分组）。

## 功能总览

| 板块 | 内容 |
|---|---|
| 基础修炼 | 签到 / 闭关 / 突破 / **双轨境界**（练气 64 + 炼体 63）/ 灵根洗炼 / 命格 75 词条 |
| 帝路 | 五档雷劫（斩道→圣人→圣人王→大圣→准帝）/ 打散速通 / 帝威加成 / 悟道八重道途（燃烧寿元）/ 悟道古茶 / 推演己道 20 层 / 合道自创体系 / 红尘仙逆活九世 / 自身之道 500 段 / 创造帝经 / 祭道 / **唯一道之上**（诸天唯一） |
| 体质 | 太阳体/太阴体/神王体两阶段觉醒 / 九转轮回体 / 命运神道体 / 极道天魔 / 光阴三品（至尊线：斩骨/试炼/仙骨/重瞳/瞳骨合一） |
| 套装 | 【万化】天魔刃·魔神袍·魔幡（万化天魔体三阶段） / 【终焉】诸神黄昏·葬天衣·归墟轮（终焉神魔体三阶段） |
| 职业 | 转职 / 采药 / 采矿 / 炼丹（品质分档）/ 炼器锻造 / 制符 / 源师系寻源 / 源石场 / 侠客讨恶 / 唤魔者劫村 / 猎户——七职业统一 `#职业产出` 产线 |
| 秘境 | 4 图探索 / 沉迷秘境（限时挂机）/ 宗门秘境 / 灵界裂缝（洗根水主产地） |
| 战斗 | 1v1 回合引擎（效果槽 / 技能注册表 263+67+4+17 条）、灵根法球、功法复活技、高境镇杀、岁云同境裁决、帝骑助战 |
| PvP | 切磋 / 打劫（隐身水/替身人偶）/ 比武 / 天地榜积分赛 / 天地堂 |
| 共享 Boss | 世界 Boss / 黑暗动乱 / 团本讨伐（组队伤害账本自动分奖）/ 千年灾劫 / 帝尊 / 若陀龙王 |
| 高阶 | 渡劫·登仙 / 寿元·轮回 / 位面旅行（11 图）/ 时间长河 / 裂界副本 / 禁仙六封 |
| 位面大事件 | 诸天异象（8 类轮换）/ 异域叩击帝关（三波状态机 + 帝血）/ 圣地大战（站队·战功·商店）/ 游商三人组 / 先天至宝出世 |
| Roguelike | 无尽劫境：星图 / 道法 / 劫后抉择 / 万劫道碑 / 厉鬼拼图 / 无尽至宝 / 称号 / 商店 |
| 剧情 | 无尽轮回「雾海市末班车」（5 幕检定 / 9 档结局 / 强化兑换）/ 剧情人物 11 位立绘 / 秘境邂逅 / 护道之约 / 黑皇阵道六阵 |
| 诸天镜 | 投影主线 10 世界 / 库洛牌 / 小樱进阶 / 见泷原（魔法少女四阶）/ 帝骑卡组 / 主角灵根 / 诸天一念 |
| 活动 | 星海之缘（签到 / 召唤 / 真我觉醒）/ 周年庆 / 巡界司裂界 |
| 经济 | 万界灵市（8 商会炒股 / NPC 墨九 / 钱庄借贷）/ 源石坊赌石 / 拍卖 / 洗劫 / 金银坊 / 商店 / 转账 |
| 其他 | 大宇宙 / 神界 / 小世界（种植·工坊·偷菜）/ 师徒 / 道侣 / 问仙令 / 魔头禁术 / 镇妖塔 / 每日任务 / 图鉴 / 纳戒面板 / 本命法宝 / 遗珍 / 至宝择主 |

出图体系：长文本自动转面板图（13 套模板，Playwright 渲染），支持 `#状态` 卡片、位面方图、劫境/团本/秘境面板、纳戒网格等。

## 安装

```bash
# AstrBot WebUI → 插件 → 从仓库安装，或手动：
git clone https://gitee.com/yesu666/zhutianxiuxian1.0.git -b python-port \
  AstrBot/data/plugins/astrbot_plugin_zhutian
```

依赖随 AstrBot 宿主（`pydantic` / `jinja2` / `aiosqlite` / `pillow` / `playwright`）。
首启自动完成：数据表加载（原版 149 张 JSON 1:1 + 22 张移植新增）→ SQLite 迁移（当前 **v17**）→ 指令注册。

## 目录结构

```
astrbot_plugin_zhutian/
├── main.py               # 指令注册与 handler（1028 条 CMD，AST 查重零冲突）
├── core/                 # 纯函数业务层（90+ 模块，可离线单测）
│   ├── combat/           #   战斗引擎：engine / skills / loadout / opening
│   ├── cultivate.py      #   签到/闭关/突破/炼体
│   ├── zhengdao.py       #   道伤 / 证道成帝三路线 / 路尽重证 / 冲关
│   ├── daolu.py          #   帝路五档雷劫（W9）
│   ├── wudao.py          #   悟道八重道途（W9）
│   ├── selfdao.py        #   己道推演 / 合道 / 红尘仙九世（W10）
│   ├── ownway.py         #   自身之道 500 段 / 帝经 / 祭道 / 唯一道之上（W11）
│   ├── physique.py       #   太阳/太阴/神王/九转轮回/命运神道/极道天魔（W12）
│   ├── exclusive_set.py  #   万化/终焉套装三阶段（W13）
│   ├── zhutian_extra.py  #   魔法少女进阶 / 主角灵根 / 诸天一念（W14）
│   ├── occupation_extra.py # 源石场 / 讨恶 / 劫村（W15）
│   ├── activity.py       #   星海之缘 / 周年庆（W16）
│   ├── reinc_story.py    #   无尽轮回「雾海市末班车」剧情（W16）
│   ├── plane_events.py   #   圣地大战 / 游商（W17）
│   ├── games_mini.py     #   金银坊（W18）
│   ├── wallet.py         #   钱包/权柄公共助手（审计 #12 合并）
│   └── endless.py        #   无尽劫境（Roguelike 全套）
├── infra/                # 基础设施：db（aiosqlite + 迁移链 v1→v17）/ content / render
├── templates/            # Jinja + Playwright 面板模板 ×13
├── data/                 # 原版数据表 1:1 携带（tests/verify_data.py 校验）
└── tests/
    ├── selfcheck.py      # 全量自检（W9-W19 各节 + 战斗等价性断言，ALL M12 CHECKS PASSED）
    ├── verify_data.py    # 数据完整性校验
    └── gen_manual.py     # 指令手册生成
```

## 测试与自检

```bash
# 全量自检（离线可跑；playwright 需与已装浏览器匹配，当前 1.64.0 ↔ chromium 1248）
uv run --offline --with pydantic --with aiosqlite --with jinja2 \
  --with pillow --with playwright==1.64.0 python -u tests/selfcheck.py

# 数据完整性 / 指令手册
uv run --with pydantic python tests/verify_data.py
uv run --with pydantic python tests/gen_manual.py <输出路径.md>
```

自检覆盖：全部迁移链、九批新玩法（W9-W19 各节含门槛拒绝/成功路径/失败损失/冷却幂等/接线断言）、战斗引擎与旧版逐种子等价性、渲染管线（真实 Chromium 截图）。

## 开发约定

- **core 层纯函数**：不 import astrbot，全部可离线测试；handler 只做参数解析 + 落库
- **数据库迁移**：改 schema 必须登记 `MIGRATIONS[n]` 并升 `LATEST_DB_VERSION`（当前 17），禁止原地改表
- **指令注册**：`@filter.command(CMD_X)` 装饰器必须与 `async def` 紧邻（踩坑记录：装饰器错位会触发 pydantic 注入而崩）
- **or-falsy 禁令**：`dict.get(key, default) or default` 会吞掉合法的 `0`，一律显式 `is None` 判断
- **钱包助手统一走 `core/wallet.py`**：`authority / xueqi / set_xueqi / pay_exp_xq / pay_potential`，新模块勿再私有复制
- **全服单例读改写**：`calamity_state` 跨度必须持 `db.calamity_lock`（审计修复 3/4）
- **异步定时器玩法**一律同步化为一次性结算，差异在模块 docstring 的 `shortcut:` 列表标注

## 数值移植约定

原版量级（攻 300 亿）与群聊生态不符，全局按 ÷1000 缩放并登记
《数值缩放对照表》；**战斗公式 1:1 直译**（Harm/暴击/劫数/雷抗），比例制
奖励（打劫 1/5、团本分奖）自动适配；个别高阶系统（推演己道/红尘仙/自身之道）
按「相对成帝成本」两级折算，见各模块 docstring。

## 明确不移植

跨服全套（世界聊天 / 跨服交易 / 跨服团本 / 跨服无尽 / 世界网页）——单服形态；
网页面板以 Playwright 出图替代。

## 更新摘要（python-port 分支）

- **W8-F9**：位面大事件 8 类异象 + 异域叩击帝关三波状态机（realm_event.py）
- **W9-W18**：帝路三批（雷劫/己道/红尘仙/自身之道/祭道/唯一道之上）、体质进阶、
  万化与终焉套装、诸天镜补充、职业补全、星海之缘与无尽轮回剧情、圣地大战与游商、金银坊——
  共 +90 条指令
- **审计修复**：ponytail-audit 11 项全清（并发锁 / 潜力复制 / 团本双发 /
  门禁统一 / wallet 合并 / 转账测试）

## 免责

仅供学习交流与小范围使用，请勿用于任何以盈利为目的的场景。玩法与数值版权属于原版作者。
