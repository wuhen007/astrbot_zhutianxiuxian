"""全插件统一的「游戏日」时钟：一切按天判定都用北京时间（UTC+8）切日。

此前 infra/db.py 用固定 UTC+8，core 里却散落 time.localtime（跟随主机
时区），只在主机时区恰为北京时间时两者一致；统一到本模块后，换机器
部署不再出现签到日与每日任务日错位。
"""

import time


def day_key(ts: float) -> str:
    """北京时间日期键（YYYY-MM-DD）。"""
    return time.strftime("%Y-%m-%d", time.gmtime(ts + 8 * 3600))
