# 合并说明文档：codex/pre-live-test-2026-11-27 → main

> 本文档基于分支 `codex/pre-live-test-2026-11-27`（分叉点 `89023ee`，共 15 个提交，
> 183 个文件变更，+46696 / -13641 行）整理，用作 PR 描述与合并操作手册。

## 一、本轮工作目标

以原版玩法仓库（github.com/wuhen007/zhutianxiuxian1.0，V1.0 快照）为基准，对本插件
做**从头到尾的全量核对**：找出遗漏玩法与"部分移植"（有指令无逻辑 / 有逻辑无指令）
的条目，逐条按原版实现逻辑补齐，不打断线上玩家（因此单独开分支）。

核对方法：提取原版 1373 条规则条目，与本地 1311 条注册指令对撞，产出 446 条待判定
清单（`tools/parity/triage.csv`），分 A/B/C 三组逐条判定并接线。

## 二、新增 / 补齐的玩法

### 高频玩法对齐（Phase 1-3）
- **战斗规则对齐**：`core/combat` 按 Phase 0.5 分诊结果补齐原版战斗公式。
- **纪元积累系统**：`core/fashan.py`（era_of / add_era / spend_era，上限 1000 点，
  存于 `ext["era_points"]`），并接入 长河 / 无尽 / 斗法 / 兑换 / 禁地 五个模块的收支。

### Phase 4 大块玩法（原版逐文件移植）
| 玩法 | 新模块 | 入口指令 | 说明 |
|---|---|---|---|
| 圣地大战 | `core/sect_war.py` | `#圣战详情` `#圣战站队` `#战场行动` `#调查战端` `#提交战场决议` | 原版 RealmEvents `sectWar` 事件：五行动表盘（军势/辎重/真相/封印）、真相 25/50/75 线索、决议投票改写结局、按贡献结算奖励（榜首战功徽记） |
| 彼岸真世界 | `core/other_shore_true_world.py` | `#真世界` 等 8 条 | 半径 48 六边形地图、6 生物群系、6 地标、4 档敌人（tier-4 纪元+1） |
| 彼岸远征 | `core/other_shore_expedition.py` | `#远征` 等 10 条 | 三战役链（玄阙神炉→先秦归航→母锚归一）、5 阶段、营地 L0-L3、撤离/强撤 30% 损失 |
| 兵字秘传承 | `core/bingzi_legacy.py` | `#兵字秘` 等 7 条 | 24h 限时全服事件，评分规则按原版（10/10/max(10,40-10×猜)/25+悟性/15-25），魁首习得兵字秘 |
| 灵宝熔炼 | `core/refine_treasure.py` | `#熔炼灵宝` | 消耗 20 灵宝残片 + 1e8 灵石 + 2e7 源石，10 层上限，每层全属性 +8 |
| 支线任务 | （接线） | 4 条 | 原有逻辑救活接线 |
| 成就核验 | （接线） | `#成就核验` | 原有逻辑救活接线 |

### 收尾模块（68e039a）
势力派遣（`core/dispatch.py`）、轮回大道、传闻探索、无尽组队、违禁品清算。

## 三、重要修复（实机必崩 / 死代码级）

1. **db 访问器缺失**：`main.py` 调用 `get_exchange/save_exchange`、`get_universe/
   save_universe`、`get_grant/save_grant`，但 `infra/db.py` 未定义 → 补 6 个单例访问器。
2. **`core/realm_event.py` `make_event` 死代码**：sectWar 附加块写在 `return {...}`
   之后不可达 → 改为赋值后附加再 return。
3. **至宝属性写回丢失**：熔炼原先经 `deepcopy` 副本改属性不落盘 → 直接操作
   `doc.ext["dibing"]` 引用。
4. **`core/other_shore_expedition.py` 副本写回**：run 状态显式写回 `st["runs"][star]`。
5. **DB 迁移**：`LATEST_DB_VERSION` 18 → 23（v19-v23 只增不改，含 `grant_state`
   新表），老库平滑升级。

## 四、质检结果

- `python -m unittest discover`：**363 项全部通过**。
- `tests/selfcheck.py`：全绿（命格断言更新为 76）。
- `tests/verify_data.py`：通过（`折冠破妄` 登记入 ALLOWED_ADDED_ROWS）。
  注：克隆目录下对 `cmd_config.json` 的 FAIL 属预期——该文件为运行时生成，
  已在 `.gitignore`，不影响判定。
- 新增测试：`tests/test_xianyi_relic_conversion.py` 等。

## 五、合并操作手册（merge main ← codex）

1. **冲突文件 4 个**：`CHANGELOG.md`、`main.py`、`metadata.yaml`、`tests/selfcheck.py`。
2. **仙古秘境冲突必须保留 main 侧**：main 的 `3d7061f`（0.5.1）已把仙古秘境重构为
   "神识开图 + 秘境移动"，并新增契约测试 `tests/test_xiangu_explore_command_contract.py`；
   codex 分叉早于该提交，仍保留旧的 `explore_turn` / `choose_explore` 三径择一实现。
   合并时丢弃 codex 侧旧实现，保留 main 重构。
3. **版本号**：main 为 0.5.1，codex 为 0.1.8 → 合并后顺延为 **0.6.0**。
4. **数据库**：main v18 → codex v23，迁移只增不改，老玩家数据无损升级。
5. **重复命令常量**：合并后存在 11 个重复 CMD 值（两套大宇宙 `CMD_UNIVERSE_*`/
   `CMD_UNI_*`、两套圣地大战 `CMD_SW_*`/`CMD_PE_*` 各绑定不同 handler，部分为
   有意双入口）→ 合并提交中人工去重核对一遍。
6. **main.py 冲突合并原则**：codex 的新增 handler（handle_tw_* / handle_exp_* /
   handle_bz_* / handle_sw_* / handle_sq_* / handle_refine / handle_ach_verify）
   全部保留，main 的仙古重构段保留。

## 六、已知遗留（合并后跟踪）

- `core/samsara.py`、`core/rumors.py`、`core/dungeon_party.py` 目前为 3 行骨架占位，
  `core/dispatch.py` 仅基础逻辑（约 61 行）——后续版本补全。
- 12 个 core 模块尚未被 `main.py` 引用（custom_items / pagoda / reinc_story 等），
  属预留实现。
- 与原版的差异点均已在对应模块 docstring 标注（如圣地大战奖励折算口径、
  支援/改队指令族未搬）。

## 七、部署注意事项（重要）

1. **备份数据**：合并前备份 `data/` 目录。
2. **强制重启**：本次包含大量核心逻辑更新（`main.py` 与 `core/*.py`），合并后务必
   重启 AstrBot 进程刷新内存逻辑。
3. **数据库迁移**：首次启动自动执行 v18 → v23，请关注迁移日志。
4. **灰度验证**：上线后建议先在测试群验证：`#圣战详情`（等一场圣地大战爆发）、
   `#熔炼灵宝`、真世界/远征入口、`#成就核验`。
