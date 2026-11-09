# astrbot_plugin_zhutian · 诸天修仙

AstrBot 修仙群聊插件 —— 原版 Yunzai JS 项目 [`zhutianxiuxian1.0`](https://gitee.com/yesu666/zhutianxiuxian1.0) 的 **Python 全量移植**（`python-port` 分支）。

> 玩家向玩法指南见 [`docs/游玩说明.md`](docs/游玩说明.md)；全部指令速查由 `tests/gen_manual.py` 生成《指令手册》（338+ 条）。

## 功能总览

| 板块 | 内容 |
|---|---|
| 基础修炼 | 签到 / 闭关 / 突破 / **双轨境界**（练气 + 炼体）/ 灵根洗炼 / 命格 75 词条 |
| 职业 | 转职 / 采药 / 采矿 / 炼丹（品质分档）/ 炼器锻造 / 制符 |
| 秘境 | 4 图探索 / 沉迷秘境（限时挂机）/ 宗门秘境 |
| 战斗 | 1v1 回合引擎（效果槽 / 技能注册表）、灵根法球、功法复活技、技能池（263+67+4+17 条）、高境镇杀、岁云同境裁决、帝骑助战 |
| PvP | 切磋 / 打劫（隐身水/替身人偶）/ 比武 |
| 共享 Boss | 世界 Boss / 黑暗动乱 / 团本讨伐（组队伤害账本自动分奖）/ 千年灾劫 |
| 高阶 | 渡劫·登仙 / 寿元·轮回 / 位面旅行（11 图）/ 时间长河 / 裂界副本 |
| 帝路 | 五档雷劫（斩道→圣人→圣人王→大圣→准帝）/ 打散速通 / 帝威加成 / 悟道八重道途（燃烧寿元）/ 悟道古茶 / 推演己道 20 层 / 合道自创体系 / 红尘仙逆活九世 |
| Roguelike | 无尽劫境：星图 / 道法 / 劫后抉择 / 万劫道碑 / 无尽至宝 / 称号 / 商店 |
| 剧情 | 剧情人物图鉴（11 位立绘）/ 秘境邂逅 / 护道之约 / 黑皇阵道六阵 |
| 其他 | 诸天镜主线 / 大宇宙 / 神界 / 小世界 / 师徒 / 道侣 / 问仙令 / 源石坊赌石 / 魔头禁术 / 灵界裂缝 / 彼岸古文明 / 镇妖塔 / 每日任务 / 图鉴 / 纳戒面板 |

出图体系：长文本自动转面板图（13 套模板，Playwright 渲染），支持 `#状态` 卡片、位面方图、劫境/团本/秘境面板、纳戒网格等。

## 安装

```bash
# AstrBot WebUI → 插件 → 从仓库安装，或手动：
git clone https://gitee.com/yesu666/zhutianxiuxian1.0.git -b python-port \
  AstrBot/data/plugins/astrbot_plugin_zhutian
```

依赖随 AstrBot 宿主（`pydantic` / `jinja2` / `aiosqlite` / `pillow` / `playwright`）。
首启自动完成：数据表加载（149 张原版 JSON）→ SQLite 迁移（当前 **v14**）→ 指令注册。

## 目录结构

```
astrbot_plugin_zhutian/
├── main.py               # 指令注册与 handler（330+ 条，AST 查重零冲突）
├── core/                 # 纯函数业务层（30 个模块，可离线单测）
│   ├── combat/           #   战斗引擎：engine / skills / loadout / opening
│   ├── cultivate.py      #   签到/闭关/突破/炼体
│   ├── secret.py         #   秘境探索（PvE 战斗接入装填）
│   ├── endless.py        #   无尽劫境（Roguelike 全套）
│   ├── trib.py           #   渡劫/登仙/功法熟练度
│   ├── lifespan.py       #   寿元/轮回
│   ├── mingge.py         #   命格（11 个消费点）
│   ├── pvp.py            #   打劫/比武结算
│   ├── plane.py          #   位面坐标/旅行
│   └── ...
├── infra/                # 基础设施：db（aiosqlite + 迁移链 v1→v14）/ content / render
├── templates/            # Jinja + Playwright 面板模板 ×13
├── data/                 # 原版数据表 149 张 1:1 携带（tests/verify_data.py 校验）
├── tests/
│   ├── selfcheck.py      # 自检 73 组（离线可跑，含战斗等价性断言）
│   ├── verify_data.py    # 数据完整性校验
│   └── gen_manual.py     # 指令手册生成 → Z:/dsh/指令手册.md
└── docs/游玩说明.md      # 玩家向玩法指南
```

## 开发约定

- **core 层纯函数**：不 import astrbot，全部可离线测试；handler 只做参数解析 + 落库
- **自检**：`uv tool` 环境跑 `python tests/selfcheck.py`，73 组断言含战斗引擎与旧
  `spar_full` 的逐种子等价性兜底
- **数据库迁移**：改 schema 必须登记 `MIGRATIONS[n]` 并升 `LATEST_DB_VERSION`，
  禁止原地改表
- **指令注册**：`@filter.command(CMD_X)` 装饰器必须与 `async def` 紧邻（踩坑记录：
  抽函数重构时装饰器错位会导致框架按注解注入 pydantic 构造而崩）
- **or-falsy 禁令**：`dict.get(key, default) or default` 会吞掉合法的 `0`
  （复活 pr=0 / 护盾 beilv=0 两次踩坑），一律显式 `is None` 判断

## 数值移植约定

原版量级（攻 300 亿）与群聊生态不符，全局按 ÷1000 缩放并登记
《数值缩放对照表》；**战斗公式 1:1 直译**（Harm/暴击/劫数/雷抗），比例制
奖励（打劫 1/5、团本分奖）自动适配。原版异步定时器玩法（渡劫逐道落雷、
寿元流逝、时间长河 phase）统一同步化为一次性结算，shortcut 均在模块
docstring 标注。

## 文档

- 《指令手册》：`tests/gen_manual.py` 生成（338+ 条，按系统分组）
- 《指令映射表》：原版 1315 条正则 → 本移植状态（✅/⬜/📌 逐条登记）
- 《移植范围确认清单》《五维验收报告》《B档推进规划》《后续推进计划》
- 明确不移植：跨服世界聊天 / web 服务 / 仙古 18 图（15 文件重度系统，时间长河
  轻量版替代）/ 万象归一 / 厉鬼拼图 / 皮肤（shortcut 详见各模块 docstring）

## 致谢

原版 JS 项目 [zhutianxiuxian1.0](https://gitee.com/yesu666/zhutianxiuxian1.0)
的全部数据表、数值设计与玩法框架均来自原作者，本项目为其 Python/AstrBot 移植版。
