"""Read-only player-facing summaries of recent plugin commits."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

MAX_ENTRIES = 10


def read_commits(repo_dir: Path, limit: int = MAX_ENTRIES) -> list[dict[str, str]]:
    count = min(MAX_ENTRIES, max(1, int(limit)))
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "log", f"-{count}", "--date=short",
             "--pretty=format:%ad%x09%s"],
            check=True, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=5,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return []

    entries = []
    for line in result.stdout.splitlines():
        date, separator, subject = line.partition("\t")
        if separator and subject.strip():
            entries.append({"date": date.strip(), "subject": subject.strip()})
    return entries[:count]


def format_updates(commits: Any) -> str:
    entries = [
        item for item in commits[:MAX_ENTRIES]
        if isinstance(item, dict) and str(item.get("subject") or "").strip()
    ] if isinstance(commits, list) else []
    if not entries:
        return "【修仙更新】暂时读不到更新记录（仓库缺少 git 信息）。"

    lines = [f"【修仙更新·最近 {len(entries)} 条】"]
    last_date = ""
    for item in entries:
        date = str(item.get("date") or "").strip()
        if date and date != last_date:
            lines.extend(("", date))
            last_date = date
        lines.append(f"· {str(item['subject']).strip()}")
    return "\n".join(lines)
