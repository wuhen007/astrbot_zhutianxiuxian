"""阶段 1 数据校验：原版 zip resources/data 与插件 data/ 逐域条数比对。

用法：python tests/verify_data.py [原版zip路径]
默认 zip：Z:/wbsy/2026-10-28-18-07-52/ref/zhutianxiuxian1.0-master.zip
输出：逐表条数比对 + 汇总结论（0 差异 = 通过）。
"""
import json
import os
import sys
import zipfile

DEFAULT_ZIP = r"Z:/wbsy/2026-10-28-18-07-52/ref/zhutianxiuxian1.0-master.zip"
PLUGIN_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PREFIX = "zhutianxiuxian1.0-master/resources/data/"


def load_count(raw: bytes) -> int:
    d = json.loads(raw.decode("utf-8"))
    if isinstance(d, (list, dict)):
        return len(d)
    return 1


def main() -> int:
    zip_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ZIP
    z = zipfile.ZipFile(zip_path)
    orig = {}
    for n in z.namelist():
        if n.startswith(PREFIX) and n.endswith(".json"):
            orig[n[len(PREFIX):]] = load_count(z.read(n))
    mine = {}
    for root, _dirs, files in os.walk(PLUGIN_DATA):
        for fn in files:
            if fn.endswith(".json"):
                rel = os.path.relpath(os.path.join(root, fn), PLUGIN_DATA).replace("\\", "/")
                with open(os.path.join(root, fn), "rb") as f:
                    mine[rel] = load_count(f.read())

    only_orig = sorted(set(orig) - set(mine))
    only_mine = sorted(set(mine) - set(orig))
    diff = [(k, orig[k], mine[k]) for k in sorted(set(orig) & set(mine)) if orig[k] != mine[k]]

    print(f"原版 JSON 表: {len(orig)} | 插件 JSON 表: {len(mine)}")
    print(f"仅原版有: {len(only_orig)} {only_orig[:10]}")
    print(f"仅插件有: {len(only_mine)} {only_mine[:10]}")
    print(f"条数不一致: {len(diff)} {diff[:10]}")

    # 计划指定的关键抽样
    checks = {
        "item/丹药列表.json": 221,
        "item/炼丹师丹药.json": 29,
        "occupation/炼丹配方.json": 21,
        "item/灵根列表.json": 139,
    }
    for k, want in checks.items():
        got = orig.get(k)
        status = "OK" if got == want else "FAIL"
        print(f"抽样 {k}: 原={got} 期望={want} [{status}]")
        assert got == want, f"源数据基线变化: {k}"
        assert mine.get(k) == want, f"插件数据不一致: {k}"

    ok = not only_orig and not diff and all(mine.get(k) == v for k, v in checks.items())
    print("数据校验:", "PASS（与源 1:1 对齐）" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
