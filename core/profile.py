"""Player profile command parsing and validation."""

from __future__ import annotations

import re

PROFILE_PREFIXES = (
    ("gender", ("设置性别", "修改性别", "改性别", "更替性别", "变更性别", "调整性别")),
    ("declaration", ("设置道宣",)),
    ("name", ("设置姓名", "改道号", "更名", "改名")),
)
MALE_WORDS = ("男", "男性", "男修", "爷们", "汉子")
FEMALE_WORDS = ("女", "女性", "女修", "妹子", "姑娘")


def parse_profile_command(message: str) -> tuple[str, str] | None:
    text = str(message or "").strip()
    if not text.startswith("#"):
        return None
    text = text[1:]
    for action, prefixes in PROFILE_PREFIXES:
        for prefix in prefixes:
            if text.startswith(prefix):
                return action, text[len(prefix):].strip()
    return None


def normalize_profile_text(value: str) -> str:
    return re.sub(r"\s|\+", "", str(value or "").strip())


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def validate_name(value: str) -> str:
    name = normalize_profile_text(value)
    if not name:
        raise ValueError("格式：#改名 新道号")
    if _utf16_length(name) > 8:
        raise ValueError("玩家名字最多八字。")
    return name


def validate_unique_name(value: str, existing_names) -> str:
    name = validate_name(value)
    if name in existing_names:
        raise ValueError(f"这世间已存在该名字的人：{name}")
    return name


def validate_declaration(value: str) -> str:
    declaration = normalize_profile_text(value)
    if not declaration:
        raise ValueError("格式：#设置道宣 内容")
    if _utf16_length(declaration) > 50:
        raise ValueError("道宣最多 50 字符。")
    return declaration


def parse_gender(value: str) -> int | None:
    text = str(value or "").strip()
    if any(word in text for word in MALE_WORDS):
        return 2
    if any(word in text for word in FEMALE_WORDS):
        return 1
    return None


def gender_code(value) -> int:
    try:
        code = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return code if code in (1, 2) else 0


def gender_is_set(value) -> bool:
    try:
        return int(value or 0) != 0
    except (TypeError, ValueError):
        return bool(value)


def gender_label(value) -> str:
    return {0: "未设置", 1: "女", 2: "男"}[gender_code(value)]


def parse_discard(message: str) -> tuple[str, int] | None:
    text = str(message or "").strip()
    if text in {"取消丢弃", "#取消丢弃"}:
        return None
    if text.startswith("#"):
        text = text[1:]
    if not text.startswith("丢弃"):
        raise ValueError("格式：#丢弃物品名*数量（数量可省略，默认 1）")
    parts = text[len("丢弃"):].strip().split("*")
    if len(parts) > 2:
        raise ValueError("格式：#丢弃物品名*数量（数量可省略，默认 1）")
    name = parts[0].strip()
    if not name:
        raise ValueError("请提供要丢弃的物品名称。")
    if len(parts) == 1:
        return name, 1
    quantity_text = parts[1].strip()
    if not re.fullmatch(r"[0-9]+", quantity_text):
        raise ValueError("丢弃数量须为正整数。")
    quantity = int(quantity_text)
    if quantity < 1:
        raise ValueError("丢弃数量须为正整数。")
    return name, quantity
