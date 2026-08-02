"""
MindGlass Admin 持久化层

负责：
1. SQLite 初始化（WAL 模式）
2. run 快照写入（含统计字段预计算）
3. run 列表/详情/总览查询
4. demo 种子导入（幂等）
"""

import json
import os
import sqlite3
from datetime import datetime
from typing import Optional

# DB 路径：backend/data/mindglass_admin.db
_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(_DB_DIR, "mindglass_admin.db")


def _ensure_dir():
    """确保 data 目录存在"""
    os.makedirs(_DB_DIR, exist_ok=True)


def _get_conn() -> sqlite3.Connection:
    """获取 WAL 模式的 SQLite 连接"""
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────── 表结构初始化 ───────────────────

DDL_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    query           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    final_answer    TEXT,
    total_nodes     INTEGER NOT NULL DEFAULT 0,
    plan_count      INTEGER NOT NULL DEFAULT 0,
    toolcall_count  INTEGER NOT NULL DEFAULT 0,
    observe_count   INTEGER NOT NULL DEFAULT 0,
    answer_count    INTEGER NOT NULL DEFAULT 0,
    total_duration_ms   INTEGER NOT NULL DEFAULT 0,
    degraded        INTEGER NOT NULL DEFAULT 0,
    tool_error_count    INTEGER NOT NULL DEFAULT 0,
    snapshot        TEXT
)
"""


def init_db():
    """初始化 runs 表"""
    conn = _get_conn()
    try:
        conn.execute(DDL_RUNS)
        conn.commit()
    finally:
        conn.close()


# ─────────────────── 快照统计字段计算 ───────────────────

def _compute_stats(snapshot: dict) -> dict:
    """从 demo 格式快照 {nodes,edges,branches,meta} 计算统计字段"""
    nodes = snapshot.get("nodes", [])
    meta = snapshot.get("meta", {})

    plan_count = 0
    toolcall_count = 0
    observe_count = 0
    answer_count = 0
    total_duration_ms = 0
    tool_error_count = 0

    final_answer = None

    for n in nodes:
        ntype = n.get("type", "")
        status = n.get("status", "")
        duration = n.get("duration_ms", 0) or 0
        total_duration_ms += duration

        if ntype == "Plan":
            plan_count += 1
        elif ntype == "ToolCall":
            toolcall_count += 1
            if status == "error":
                tool_error_count += 1
        elif ntype == "Observe":
            observe_count += 1
        elif ntype == "Answer":
            answer_count += 1
            # 最终答案 = 最后一个 status==done 的 Answer 节点的 output
            if status == "done":
                final_answer = n.get("data", {}).get("output")

    # degraded 判定：最终 Answer 的 data.degraded 字段
    degraded = 0
    # 找最后一个 done 的 Answer 节点
    for n in reversed(nodes):
        if n.get("type") == "Answer" and n.get("status") == "done":
            degraded = 1 if n.get("data", {}).get("degraded") else 0
            break

    return {
        "total_nodes": len(nodes),
        "plan_count": plan_count,
        "toolcall_count": toolcall_count,
        "observe_count": observe_count,
        "answer_count": answer_count,
        "total_duration_ms": total_duration_ms,
        "degraded": degraded,
        "tool_error_count": tool_error_count,
        "final_answer": final_answer,
    }


# ─────────────────── 写入 ───────────────────

def save_run(snapshot: dict) -> str:
    """
    保存一次 run 的完整快照。
    返回 run_id。
    """
    stats = _compute_stats(snapshot)
    meta = snapshot.get("meta", {})
    run_id = meta.get("run_id", "")
    query = meta.get("query", "")
    created_at = datetime.utcnow().isoformat()

    snapshot_json = json.dumps(snapshot, ensure_ascii=False)

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO runs (
                run_id, query, created_at, final_answer,
                total_nodes, plan_count, toolcall_count, observe_count, answer_count,
                total_duration_ms, degraded, tool_error_count, snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, query, created_at, stats["final_answer"],
                stats["total_nodes"], stats["plan_count"], stats["toolcall_count"],
                stats["observe_count"], stats["answer_count"],
                stats["total_duration_ms"], stats["degraded"],
                stats["tool_error_count"], snapshot_json,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return run_id


def seed_run(run_id: str, snapshot: dict) -> bool:
    """
    幂等导入一条 run 记录（用于 demo 种子数据）。
    如果 run_id 已存在则跳过，返回 False；否则插入，返回 True。
    """
    stats = _compute_stats(snapshot)
    meta = snapshot.get("meta", {})
    query = meta.get("query", "")

    # 用 demo 文件名中的序号推算 created_at（demo_1 最早，demo_12 最晚）
    # 这里统一用一个基准时间 + 序号偏移
    created_at = datetime.utcnow().isoformat()

    snapshot_json = json.dumps(snapshot, ensure_ascii=False)

    conn = _get_conn()
    try:
        cur = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,))
        if cur.fetchone():
            return False  # 已存在，跳过

        conn.execute(
            """INSERT INTO runs (
                run_id, query, created_at, final_answer,
                total_nodes, plan_count, toolcall_count, observe_count, answer_count,
                total_duration_ms, degraded, tool_error_count, snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, query, created_at, stats["final_answer"],
                stats["total_nodes"], stats["plan_count"], stats["toolcall_count"],
                stats["observe_count"], stats["answer_count"],
                stats["total_duration_ms"], stats["degraded"],
                stats["tool_error_count"], snapshot_json,
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


# ─────────────────── 查询 ───────────────────

def get_overview() -> dict:
    """总览指标"""
    conn = _get_conn()
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total_runs,
                SUM(CASE WHEN degraded = 0 THEN 1 ELSE 0 END) as answer_count,
                SUM(degraded) as degraded_count,
                SUM(tool_error_count) as tool_error_total,
                AVG(total_duration_ms) as avg_duration_ms
            FROM runs
            """
        ).fetchone()

        total_runs = row["total_runs"] or 0
        answer_count = row["answer_count"] or 0
        degraded_count = row["degraded_count"] or 0

        answer_rate = answer_count / total_runs if total_runs > 0 else 0.0
        degraded_rate = degraded_count / total_runs if total_runs > 0 else 0.0

        return {
            "total_runs": total_runs,
            "answer_rate": round(answer_rate, 4),
            "degraded_rate": round(degraded_rate, 4),
            "tool_error_total": row["tool_error_total"] or 0,
            "avg_duration_ms": round(row["avg_duration_ms"] or 0, 1),
        }
    finally:
        conn.close()


def get_runs(limit: int = 20, offset: int = 0) -> dict:
    """
    run 列表（分页），返回统计字段列（不含 snapshot）。
    返回 {runs: [...], total: int}
    """
    conn = _get_conn()
    try:
        # 总数
        total_row = conn.execute("SELECT COUNT(*) as cnt FROM runs").fetchone()
        total = total_row["cnt"]

        # 列表
        rows = conn.execute(
            """
            SELECT run_id, query, final_answer, total_nodes,
                   plan_count, toolcall_count, observe_count, answer_count,
                   total_duration_ms, degraded, tool_error_count, created_at
            FROM runs
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()

        runs = []
        for r in rows:
            runs.append({
                "run_id": r["run_id"],
                "query": r["query"],
                "final_answer": r["final_answer"],
                "total_nodes": r["total_nodes"],
                "plan_count": r["plan_count"],
                "toolcall_count": r["toolcall_count"],
                "observe_count": r["observe_count"],
                "answer_count": r["answer_count"],
                "total_duration_ms": r["total_duration_ms"],
                "degraded": bool(r["degraded"]),
                "tool_error_count": r["tool_error_count"],
                "created_at": r["created_at"],
            })

        return {"runs": runs, "total": total}
    finally:
        conn.close()


def get_run_snapshot(run_id: str) -> Optional[dict]:
    """获取单条完整快照 {nodes,edges,branches,meta}"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT snapshot FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row and row["snapshot"]:
            return json.loads(row["snapshot"])
        return None
    finally:
        conn.close()
