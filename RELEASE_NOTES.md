# 代码变更说明：codex/pre-live-test-2026-11-27

> 分叉点 `89023ee`，共 15 个提交，183 个文件变更，+46696 / -13641 行。

## 一、新增玩法模块

| 模块 | 指令入口 | 内容 |
|---|---|---|
| `core/sect_war.py` | `#圣战详情` `#圣战站队` `#战场行动` `#调查战端` `#投入战资` `#提交战场决议` `#查看战场榜` | 圣地大战：五行动与源石战资推四表盘（军势/辎重/真相/封印）、真相 25/50/75 线索、决议投票改写结局、战功排行与历史战果领取（关联 `#战功商店` / `#战功兑换`） |
| `core/other_shore_true_world.py` | `#真世界` 等 8 条 | 彼岸真世界：半径 48 六边形地图、6 生物群系、6 地标、4 档敌人 |
| `core/other_shore_expedition.py` | `#远征` 等 10 条 | 彼岸远征：三战役链（玄阙神炉→先秦归航→母锚归一）、5 阶段、营地 L0-L3、撤离/强撤损失 |
| `core/bingzi_legacy.py` | `#兵字秘` 等 7 条 | 兵字秘传承：24h 限时全服事件，评分与魁首/残卷奖励按原版规则 |
| `core/refine_treasure.py` | `#熔炼灵宝` | 消耗 20 灵宝残片 + 1e8 灵石 + 2e7 源石，10 层上限，每层全属性 +8 |
| `core/dispatch.py` | 派遣相关 | 势力弟子派遣：30 分钟/轮，上限 10 轮，收益 30% |

其余接线：支线任务 4 条、成就核验 `#成就核验`、轮回大道 / 传闻探索 / 无尽组队 /
违禁品清算收尾指令。

## 二、核心机制

- **纪元积累系统**（`core/fashan.py`）：era_of / add_era / spend_era，上限 1000 点，
  存于 `ext["era_points"]`，接入 长河 / 无尽 / 斗法 / 兑换 / 禁地 五个模块收支。
- **圣地大战事件池**（`core/realm_event.py`）：sectWar 入五时代 ERA_WEIGHTS，
  OUTCOMES 加对应条目。

## 三、代码修复

- `infra/db.py`：补 6 个单例访问器（get/save_exchange、get/save_universe、
  get/save_grant），修复 main.py 调用不存在的 db 方法导致的实机崩溃。
- `core/realm_event.py`：`make_event` 中 sectWar 附加块原写在 `return` 之后不可达，
  改为赋值后附加再 return。
- `core/refine_treasure.py`：直接操作 `doc.ext["dibing"]` 引用（原 deepcopy 副本
  改属性不落盘）。
- `core/other_shore_expedition.py`：run 状态显式写回 `st["runs"][star]`。
- `core/grand_universe.py` & `main.py`：下线旧 `CMD_UNI_*` 重复大宇宙入口，统一收口至 `grand_universe`；保留旧 `ext["universe"]` 自动无损迁移（含法则阶/灵韵/秘境/开放状态）与仙古高阶冲关承载读取。
- `core/sect_war.py` & `main.py`：下线旧 `plane_events` 重复圣战入口（保留 `#战功商店`/`#战功兑换` 及游商/问道签），将 `#投入战资`、`#查看战场榜` 并入 `sect_war` 并补齐 `#调查战端` alias 与 `extra_mod` 引用修复。
- DB 版本 18 → 23（v19-v23 只增不改，新增 `grant_state` 表）。

## 四、代码现状

- `core/samsara.py`、`core/rumors.py`、`core/dungeon_party.py` 为 3 行占位骨架，
  后续版本补全。
- 12 个 core 模块未被 main.py 引用（custom_items / pagoda / reinc_story 等），属预留。
- 与原版实现有差异的口径均已在对应模块 docstring 标注。
