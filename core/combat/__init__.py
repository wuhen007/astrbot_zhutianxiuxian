"""core/combat —— 战斗引擎（W1 重构线）。

按决策④「边移植边重构」：不逐行翻译原版 zd_battle，而是按其语义分阶段落干净抽象——
- engine.py   1v1 回合驱动 + 效果槽（定身/护盾/易伤/反噬/汲取），行为与旧 battle.spar_full 等价
- skills.py   技能注册表（W1-2 填充：daofa 技能池/灵根法球）
- 后续批次：W1-3 护盾/控制体系化、W1-4 帝骑/宿云/高境镇杀、W1-5 团队血量结算、W1-6/7 打劫/比武入口

对外旧 API（battle.Unit / battle.spar / battle.spar_full）保持不变，battle.py 已改为薄壳。
"""

from .engine import Fighter, BattleResult, run_1v1  # noqa: F401
from . import skills  # noqa: F401
