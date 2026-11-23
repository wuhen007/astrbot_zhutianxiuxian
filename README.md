# 诸天修仙

面向 AstrBot 的群聊文字修仙插件。包含角色成长、职业与装备、秘境探索、战斗、宗门社交、位面事件和长线剧情。项目以 Python 重构，玩法参考[上游原作](https://gitee.com/mo-wuming/zhutianxiuxian1.0)；各玩法以本仓库当前实现为准，不承诺与原作逐项相同。

## 安装

要求 AstrBot `>=4.0,<5`。在插件管理中安装：

```text
https://github.com/wuhen007/astrbot_zhutianxiuxian
```

也可手动克隆到插件目录：

```bash
git clone https://github.com/wuhen007/astrbot_zhutianxiuxian.git \
  AstrBot/data/plugins/astrbot_zhutianxiuxian
```

安装后重启 AstrBot。插件元数据声明支持 `aiocqhttp`、`qq_official` 和 `qq_official_webhook`；具体消息能力受平台接口限制。

## 开始游玩

在群聊发送 `#踏入仙途` 创建角色，再发送 `#修仙状态` 查看进度。常用入口：

- 日常成长：`#修仙签到`、`#闭关 120分钟`、`#出关`、`#突破`、`#炼体突破`。
- 任务与背包：`#获取每日任务`、`#我的任务`、`#提交每日任务`、`#我的纳戒`。
- 秘境列表：`#秘境` 查看地点，`#降临秘境 青冥山` 进入程序化秘境，之后用 `#秘境寻宝` 探索、`#逃离` 结算离开。
- 仙古秘境是另一套玩法：用 `#进入仙古秘境` 进入，发送 `#秘境探索` 等指令继续。

`#修仙帮助` 查看帮助目录，`#基础帮助` 查看常用指令。参数、解锁条件和当前可用玩法以游戏内帮助与机器人回复为准。

## 玩法

- 角色创建、练气与炼体成长、命格、灵根、功法和日常任务。
- 闭关、秘境、Boss、PVP、职业采集、炼丹锻造、装备与物品交易。
- 宗门、师徒、道侣、拍卖、源石坊对决、镇园石王等群体玩法。
- 位面探索、诸天事件、无尽劫境与无尽轮回等长线内容。

功能开放受境界、职业、道具、群设置和平台能力影响；未列出的上游玩法不代表本插件已实现。

## QQ 群功能

官方 QQ 机器人有主动消息额度限制。群主可使用 `#邀请群加入推送` 登记群聊，并用 `#群推送分类 时代 每日 拍卖 活动` 选择推送类别；群主或机器人主人可使用 `#退出群推送` 停止本群全部推送。主动推送只发往已登记且允许机器人发送消息的群。

群主或机器人主人可创建道具发放单。玩家通过私聊机器人领取；当群聊与私聊账号身份不一致时，需要被 @ 的玩家回到原群确认。发放流程是公益功能，请勿为领取道具付费。

## 配置与数据

- `ACCESS_CONTROL.WHITELIST_GROUPS`：限制可使用插件的群号；留空时不按群号限制。
- `RENDER_ENABLE`：启用图片面板渲染；需要可用的 Playwright/Chromium 环境。不可用时支持的面板回退为文本。
- SQLite 数据库和面板文件位于 `data/plugin_data/astrbot_zhutianxiuxian`。首次启动时会把旧目录 `data/plugin_data/zhutian` 中缺少的数据复制到新目录，不会自动删除旧目录。

升级前建议备份插件数据目录。数据库迁移在启动时执行。

## 开发验证

在安装项目依赖的 Python 环境中运行：

```bash
python -m unittest discover -s tests
python tests/selfcheck.py
python -m compileall -q main.py core infra
git diff --check
```

许可信息见 [LICENSE](LICENSE)。

版本变更见 [CHANGELOG](CHANGELOG.md)。
