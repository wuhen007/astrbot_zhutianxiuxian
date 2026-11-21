# 诸天修仙 Python 插件

AstrBot 群聊修仙插件，移植自 [Yunzai JS 原版](https://gitee.com/mo-wuming/zhutianxiuxian1.0)。本仓库是 AstrBot 专用移植，内容对应上游的 `python-port` 分支；上游 `master` 是 Yunzai JS 原始实现，不是 AstrBot 插件。

玩家玩法说明见 [docs/游玩说明.md](docs/游玩说明.md)，指令以插件帮助页和当前生成的指令手册为准。移植范围、近期对照结果和未验证边界见 [GAMEPLAY-PARITY.md](GAMEPLAY-PARITY.md)。

## 安装

可在 AstrBot WebUI 中填写本仓库地址直接安装，或手动克隆：

```bash
git clone https://github.com/wuhen007/astrbot_plugin_xiuxian.git \
  AstrBot/data/plugins/astrbot_plugin_zhutian
```

插件内部标识（`metadata.yaml` 的 `name`）仍为 `astrbot_plugin_zhutian`，安装目录名请保持一致，以免既有的 `plugin_data` 数据失效。

依赖由 AstrBot 环境提供，包括 `pydantic`、`jinja2`、`aiosqlite`、`pillow` 和 `playwright`。插件启动时加载 JSON 内容表、执行 SQLite 迁移并注册指令。当前数据库版本为 v17。

## 项目结构

```text
.
├── main.py                   AstrBot 指令注册、消息处理、生命周期任务
├── core/                      玩法与领域逻辑
│   ├── combat/                战斗引擎、技能和战斗配置
│   ├── endless.py             无尽劫境
│   ├── reinc_state.py         无尽轮回分支剧情状态机
│   ├── reincarnation_data.json 原版轮回场景、职业、队友、怪物与结局数据
│   ├── projection_story.py    诸天投影事件条件与效果
│   ├── projection_events.json 原版投影事件数据
│   ├── auction.py             星阁竞拍及玩家拍卖状态逻辑
│   ├── xiangu.py              仙古地图和秘境状态
│   └── xiangu_npc.py          NPC 交互与生态移动
├── infra/                     SQLite、内容加载、渲染等宿主设施
├── data/                      游戏配置、内容表与帮助信息
├── templates/                 面板图片模板
└── tests/                     离线回归测试及工具
```

本项目不是对上游所有平台能力和全部玩法的逐项等价移植；跨服、网页系统、皮肤上传及部分协作玩法不在当前范围。具体边界以 [GAMEPLAY-PARITY.md](GAMEPLAY-PARITY.md) 和各模块说明为准。

## 开发与验证

使用安装了项目依赖的 Python 环境运行：

```bash
python -m unittest discover -s tests
python -m py_compile main.py core/*.py
python -m json.tool data/help/help.json > /dev/null
git diff --check
```

如需生成指令手册：

```bash
python tests/gen_manual.py 指令手册.md
```

部分旧版 `tests/selfcheck.py` 会执行浏览器渲染检查；需安装与 Playwright 匹配的 Chromium。它不是本次回归测试的替代物，浏览器缺失时应单独记录渲染检查未完成。

## 开发约定

- `core/` 尽量保持独立于 AstrBot；消息适配、授权和持久化由 `main.py` 处理。
- 数据库结构变更通过 `infra/db.py` 的迁移链升级，不原地改写已发布结构。
- 全服共享状态使用 `db.calamity_lock`；玩家档案并发修改使用对应玩家锁。
- 保留明确的兼容层时，在模块文档中标清其用途；不要把历史简化或历史计划当作当前实现。
- 上游对照以本次实际使用的固定源码版本为准；同步上游后重新核对差异和测试。

## 文档索引

- [玩家游玩说明](docs/游玩说明.md)
- [最近玩法移植与验证边界](GAMEPLAY-PARITY.md)
- [此前五项修复记录](GAMEPLAY-FIXES.md)：历史记录，不代表当前轮回剧情范围或全部测试状态
- [MD 按钮交互改造方案](docs/MD按钮交互改造方案.md)：调研提案，不是当前功能承诺

## 许可与声明

仅供学习交流与小范围使用。玩法与数值版权属于上游原版作者。
