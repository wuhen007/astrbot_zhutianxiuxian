# 诸天修仙

面向 AstrBot 的群聊文字修仙游戏。玩家可体验境界养成、秘境探索、战斗、职业与装备、宗门互动，以及诸天位面和长线剧情玩法。项目以 AstrBot 原生 Python 插件形式运行，玩法设定和部分内容参考[上游原作](https://gitee.com/mo-wuming/zhutianxiuxian1.0)。

## 安装

AstrBot 版本要求：`>=4.0,<5`。

在 AstrBot WebUI 的插件管理中使用仓库地址安装：

```text
https://github.com/wuhen007/astrbot_zhutianxiuxian
```

也可以手动克隆到插件目录：

```bash
git clone https://github.com/wuhen007/astrbot_zhutianxiuxian.git \
  AstrBot/data/plugins/astrbot_zhutianxiuxian
```

安装后重启 AstrBot。升级前建议备份插件数据目录；插件会在启动时检查并执行 SQLite 数据库迁移。

## 开始游玩

在群聊中发送 `#踏入仙途` 阅读序章并选择降临方向，再按提示发送 `#降临 修仙界` 创建角色。之后可用以下指令开始：

- `#修仙状态`：查看角色状态与当前行动。
- `#修仙签到`：领取每日签到奖励。
- `#闭关 120分钟`、`#出关`：开始并结算闭关修炼。
- `#突破`、`#炼体突破`：推进练气或炼体境界。
- `#获取每日任务`、`#我的任务`、`#提交每日任务`：接取、查看和提交每日任务。
- `#进入仙古秘境`、`#秘境探索`：进入仙古秘境并继续探索。

`#修仙帮助` 查看帮助目录，`#基础帮助` 查看常用修仙指令。不同系统有单独的帮助页，实际参数和解锁条件以机器人回复为准。更多入门流程见[玩家指南](docs/游玩说明.md)。

## 功能

- 角色创建、练气与炼体成长、命格、灵根和功法。
- 闭关、任务、秘境、Boss、PVP 与队伍挑战。
- 职业、采集、炼丹、锻造、装备和物品交易。
- 宗门、师徒、道侣、拍卖及其他群体玩法。
- 位面探索、诸天事件、无尽劫境和无尽轮回等长线内容。

功能入口和开放条件以当前帮助页为准；本项目不承诺覆盖上游原作的所有玩法或其他平台功能。

## 配置与数据

- `ACCESS_CONTROL.WHITELIST_GROUPS`：限制可使用插件的群号；留空时不按群号限制。
- `RENDER_ENABLE`：控制图片面板渲染。启用需要可用的 Playwright/Chromium 环境；渲染不可用时相关面板会回退到文本输出。
- 数据库与面板文件保存在 `data/plugin_data/astrbot_zhutianxiuxian`。从旧版本升级时，插件会在首次启动时将 `data/plugin_data/zhutian` 中缺失的数据复制到新目录，并保留旧目录作为回退副本；确认新目录数据正常后可自行清理旧目录。

## 开发验证

在已安装项目依赖的 Python 环境中运行：

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests
python -m compileall -q main.py core infra
python -m json.tool data/help/help.json > /dev/null
git diff --check
```

## 许可

软件许可见 [LICENSE](LICENSE)。原作与内容来源见上游项目说明。
