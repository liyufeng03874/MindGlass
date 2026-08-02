"""
Seed 脚本 — 将 backend/docs/ 下 12 个 demo 文件导入 runs 表（幂等）

用法：
    D:\miniconda3\envs\aivenv\python.exe backend/scripts/seed_admin_runs.py

按 run_id（demo_1 ~ demo_12）去重，可重复跑不重复插。
"""

import json
import os
import sys

# 确保能导入 backend 模块
BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from admin.persistence import init_db, seed_run


DOCS_DIR = os.path.join(BACKEND_DIR, "docs")


def load_demo_file(filepath: str) -> dict:
    """加载 demo 文件，提取 {nodes,edges,branches,meta} 格式数据"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read().strip()

    data = json.loads(content)

    # demo 文件可能是嵌套格式 {"type": "run_complete", "data": {"graph": {...}}}
    if "data" in data and "graph" in data["data"]:
        return data["data"]["graph"]
    # 或直接就是 {nodes, edges, ...} 格式
    elif "nodes" in data:
        return data
    else:
        return data


def main():
    """主函数：初始化 DB + 导入所有 demo"""
    # 初始化表结构
    init_db()
    print("[seed] DB 初始化完成")

    # 扫描 docs 目录下的 demo 文件
    demo_files = sorted([
        f for f in os.listdir(DOCS_DIR)
        if f.startswith("demo_") and f.endswith(".txt")
    ])

    imported = 0
    skipped = 0

    for fname in demo_files:
        # 从文件名提取 run_id，如 demo_1(3个百科问题).txt -> demo_1
        # 取第一个 ( 或 . 之前的部分
        base = fname.replace(".txt", "")
        if "(" in base:
            run_id = base[: base.index("(")]
        else:
            run_id = base

        filepath = os.path.join(DOCS_DIR, fname)
        snapshot = load_demo_file(filepath)

        # 幂等写入
        ok = seed_run(run_id, snapshot)
        if ok:
            print(f"  [+] 导入 {run_id} ({fname})")
            imported += 1
        else:
            print(f"  [-] 跳过 {run_id} (已存在)")
            skipped += 1

    print(f"\n[seed] 完成：导入 {imported} 条，跳过 {skipped} 条，共 {len(demo_files)} 个 demo")


if __name__ == "__main__":
    main()
