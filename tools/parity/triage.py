# -*- coding: utf-8 -*-
"""原版指令提取 + 与本地命令集合富化，产出分诊底表 triage_raw.csv。

用法：python tools/parity/triage.py
输入：原版仓库路径（环境变量 UPSTREAM 或默认值）、本地 main.py
输出：tools/parity/triage_raw.csv
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

UP = Path(os.environ.get("UPSTREAM", r"Z:/wbsy/2026-11-22-00-39-17/.tmp_up"))
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

REG_RE = re.compile(r"""reg\s*:\s*(['"])(.*?)(?<!\\)\1""", re.S)
CROSS = ("世界", "跨服", "总机", "区服", "频道", "发言", "聊天", "网关", "web", "call", "同步")
FRAG_HINT = ("n", "/", "已", "以", "去", "和", "的")


def expand(pat: str) -> list[str]:
    m = re.search(r"\(([^()]*)\)", pat)
    if not m or "|" not in m.group(1):
        return [pat]
    out = []
    for alt in m.group(1).split("|"):
        out.extend(expand(pat[: m.start()] + alt + pat[m.end():]))
    return out


def head_of(text: str) -> str:
    text = text.replace("\\", "")
    text = re.sub(r"^[\^#]+", "", text)
    text = re.sub(r"[\$\.\*\+\?\[\]\{\}\(\)\|].*$", "", text)
    return text.strip().split(" ")[0].split("　")[0].strip()


# ---- 原版：命令 -> [(文件, 行号, reg 原文)] ----
up: dict[str, list[tuple[str, int, str]]] = {}
for f in sorted(UP.rglob("apps/**/*.js")):
    rel = str(f.relative_to(UP))
    lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
    for i, line in enumerate(lines, 1):
        for _q, pat in REG_RE.findall(line):
            for p in expand(pat):
                h = head_of(p)
                if h and len(h) <= 14 and h not in {".*", ".+"}:
                    up.setdefault(h, []).append((rel, i, pat.strip()[:120]))

# ---- 本地：命令头集合 + 归属模块 ----
src = (ROOT / "main.py").read_text(encoding="utf-8", errors="ignore")
consts = dict(re.findall(r'^(CMD_[A-Z0-9_]+)\s*=\s*"([^"\n]*)"', src, re.M))
zt: dict[str, str] = {}


def add_local(cmd: str, owner: str) -> None:
    h = head_of(cmd)
    if h:
        zt.setdefault(h, owner)


for name, val in consts.items():
    add_local(val, name)
for arg in re.findall(r"@filter\.(?:command|regex)\(\s*(CMD_[A-Z0-9_]+|\"[^\"]*\"|'[^']*')", src):
    val = consts.get(arg, "") if arg.startswith("CMD_") else arg.strip("\"'")
    add_local(val, "filter")
for m in re.finditer(r"@filter\.regex\(\s*r?\"(.+?)\"\s*\)", src, re.S):
    for grp in re.findall(r"#\(\?:\s*([^()]+?)\s*\)", m.group(1)):
        for alt in grp.split("|"):
            add_local(alt, "regex-alias")
extra = re.search(r"EXTRA_ALIASES\s*=\s*\{(.+?)\}", src, re.S)
if extra:
    for m in re.finditer(r'"#([^"]{2,14})"', extra.group(1)):
        add_local("#" + m.group(1), "EXTRA_ALIASES")

rows = []
for cmd, locs in sorted(up.items()):
    if cmd in zt or any(k in cmd for k in CROSS):
        continue
    rel, line, raw = locs[0]
    rows.append({
        "cmd": cmd,
        "module": "\\".join(rel.split("\\")[:2]),
        "file": rel,
        "line": line,
        "raw_reg": raw,
        "hits": len(locs),
        "frag_hint": "Y" if (len(cmd) <= 1 or cmd.endswith("n") or cmd.startswith("/")) else "",
    })

# 最近似命令（本地）
from difflib import SequenceMatcher
PREFIX = ("我的", "查看", "查询", "获取", "领取", "打开", "进入", "前往", "使用", "选择")


def strip_pfx(s: str) -> str:
    for p in PREFIX:
        if s.startswith(p) and len(s) > len(p) + 1:
            return s[len(p):]
    return s


for r in rows:
    c = strip_pfx(r["cmd"])
    best, name = 0.0, ""
    for z in zt:
        zc = strip_pfx(z)
        sc = 0.95 + min(len(c), len(zc)) / max(len(c), len(zc)) * 0.04 if (
            c == zc or c in zc or zc in c) else SequenceMatcher(None, c, zc).ratio()
        if sc > best:
            best, name = sc, z
    r["nearest"] = name
    r["score"] = round(best, 3)
    r["nearest_owner"] = zt.get(name, "")

rows.sort(key=lambda r: (r["module"], r["cmd"]))
out = HERE / "triage_raw.csv"
with out.open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) + ["verdict", "note"])
    w.writeheader()
    for r in rows:
        r["verdict"] = ""
        r["note"] = ""
        w.writerow(r)

print(f"待分诊 {len(rows)} 条 -> {out}")
mods: dict[str, int] = {}
for r in rows:
    mods[r["module"]] = mods.get(r["module"], 0) + 1
for m, n in sorted(mods.items(), key=lambda x: -x[1]):
    print(f"  {n:>3}  {m}")
