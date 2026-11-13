"""MD 消息与按钮 UI 工厂（W30）——放插件根级而非 core/，因为需要 import
astrbot 组件（core 层纯函数约定：不 import astrbot）。

对应 AstrBot qq_official 适配器（源码已核对）：
- `MessageEventResult.use_markdown(True)` → QQ msg_type=2 MarkdownPayload
- `ActionRow(buttons, fallback_text, action_timeout)` → msg_type=4 内联键盘
- 点击 → ButtonInteraction 事件 → 插件 `@filter.button_action()` 分发

约束（适配器源码实测）：
- 键盘最多 5 行 × 每行 5 按钮；按钮 id 同键盘内唯一；label 截断；回调 data ≤1024B
- 回调注册表是进程内存态，重启失效 → 每行必带 fallback_text 提示文本指令
- 回调 data 只放 {"act","a1","a2","uid"} 四元组；`own()` 注入发起者 uid 供分发器
  校验点击者，防冒用（公开玩法如抢红包不注入）

组件 import 失败（旧版 AstrBot）时整体降级：`available=False`，所有构造返回 None，
调用方据此跳过按钮发送——纯文本行为与改造前完全一致。
"""

from __future__ import annotations

from typing import Any

try:  # 旧版 AstrBot 无 Button/ActionRow 组件时优雅降级
    from astrbot.api.message_components import ActionRow, Button, Plain

    AVAILABLE = True
except Exception:  # pragma: no cover
    Button = ActionRow = Plain = None
    AVAILABLE = False

LABEL_MAX = 16          # 保守截断（适配器还会再截一次）
DATA_MAX = 1024         # 适配器硬限：回调 action data 字节数


def available() -> bool:
    return AVAILABLE


def md_text(text: str) -> str:
    """QQ 官方原生 Markdown 渲染规则：单个 \\n 不换行。

    行尾补两空格强制换行；连续空行压缩；粗体标题行加 **。"""
    lines = str(text or "").split("\n")
    out = []
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if not stripped:
            out.append("")
            continue
        # 标题行（以【或 # 开头，或以】结尾的整行短语）加粗
        if (stripped.startswith("【") and stripped.endswith("】")) or \
                stripped.startswith("# "):
            stripped = f"**{stripped}**"
        # 行尾两空格 = markdown 强制换行；最后一行不需要
        if i < len(lines) - 1 and stripped:
            stripped += "  "
        out.append(stripped)
    return "\n".join(out)


def own(data: dict | None, uid: Any) -> dict:
    """回调 data 注入发起者 uid（分发器校验点击者==发起者，防冒用）。"""
    d = dict(data or {})
    if uid is not None:
        d["uid"] = str(uid)
    return d


def btn(act: str, label: str, a1: Any = None, a2: Any = None,
        uid: Any = None, style: str = "default") -> Any | None:
    """构造回调按钮。id 用 act+参数+label 组合保证同键盘唯一。"""
    if not AVAILABLE:
        return None
    data: dict = {"act": str(act), "a1": a1, "a2": a2}
    if uid is not None:
        data["uid"] = str(uid)
    ident = f"{act}|{a1 if a1 is not None else ''}|{label}"[:64]
    style_map = {"default": Button.Style.DEFAULT, "primary": Button.Style.PRIMARY,
                 "success": Button.Style.SUCCESS, "danger": Button.Style.DANGER}
    return Button(id=ident, label=str(label)[:LABEL_MAX],
                  action=Button.CallbackAction(data=data),
                  style=style_map.get(style, Button.Style.DEFAULT))


def row(buttons: list[Any], fallback: str | None = None,
        timeout: float | None = None) -> Any | None:
    """构造一行按钮（fallback 文本必给：按钮过期/重启后提示文本指令）。"""
    if not AVAILABLE:
        return None
    btns = [b for b in buttons if b is not None]
    if not btns:
        return None
    return ActionRow(buttons=btns,
                     fallback_text=(fallback or " / ".join(
                         b.label for b in btns) + "（按钮失效请直接发送指令）"),
                     action_timeout=timeout)


def kb_result(event: Any, text: str, *rows: Any, markdown: bool = True) -> Any | None:
    """构造「短文本 + 键盘」消息结果；组件不可用时退化为纯文本结果。"""
    rows = [r for r in rows if r is not None]
    if AVAILABLE and rows:
        # 键盘消息必须承载于 markdown（msg_type=2），md_text 行尾双空格换行
        chain = [Plain(md_text(text)), *rows]
        res = event.chain_result(chain)
        if markdown:
            res.use_markdown(True)
        return res
    # W34-fix：无按钮行走原生文本（msg_type=0，\n 自带换行）——QQ 原生 markdown
    # 对无键盘消息的行尾双空格不生效，会把多行压成一段（剑与魔法子页排版事故）。
    return event.plain_result(text) if text else None


def data_ok(data: Any) -> dict:
    """取按钮回调 data（非 dict 视为空）。"""
    return data if isinstance(data, dict) else {}


def encode_size_ok(data: dict) -> bool:
    """回调 data 是否在适配器 1024 字节限内。"""
    try:
        import json
        return len(json.dumps(data, ensure_ascii=False).encode("utf-8")) <= DATA_MAX
    except Exception:
        return False
