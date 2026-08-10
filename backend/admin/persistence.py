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

# DB 路径：backend/data/mindglass_admin.db（锚定到 backend/ 目录，不依赖 cwd）
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_DIR = os.path.join(_BACKEND_DIR, "data")
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
    snapshot        TEXT,
    conversation_id TEXT,
    interrupted     INTEGER NOT NULL DEFAULT 0,
    safety_interrupt    INTEGER NOT NULL DEFAULT 0,
    resumed         INTEGER NOT NULL DEFAULT 0
)
"""

DDL_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type      TEXT NOT NULL,
    run_id          TEXT,
    conversation_id TEXT,
    detail          TEXT,
    created_at      TEXT NOT NULL
)
"""

# 事件类型常量
EVT_DISCONNECT = 'disconnect'           # SSE 断连
EVT_AUTO_RETRY = 'auto_retry'           # 自动重连尝试
EVT_AUTO_RETRY_EXHAUSTED = 'auto_retry_exhausted'  # 3次自动重连均失败
EVT_RECONNECT = 'reconnect'             # 手动/自动重连成功
EVT_RESUME = 'resume'                   # 续跑触发
EVT_RESUME_SUCCESS = 'resume_success'   # 续跑成功完成
EVT_INTERRUPT = 'interrupt'             # 用户主动打断
EVT_SAFETY = 'safety_interrupt'         # 安全拦截


def init_db():
    """初始化 runs + events 表（含存量库的列补齐）"""
    conn = _get_conn()
    try:
        conn.execute(DDL_RUNS)
        conn.execute(DDL_EVENTS)
        # 存量库补列（幂等）
        cols = [r[1] for r in conn.execute("PRAGMA table_info(runs)")]
        if "conversation_id" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN conversation_id TEXT")
        if "interrupted" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN interrupted INTEGER NOT NULL DEFAULT 0")
        if "safety_interrupt" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN safety_interrupt INTEGER NOT NULL DEFAULT 0")
        if "resumed" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN resumed INTEGER NOT NULL DEFAULT 0")
        # events 表索引：按类型+时间查询
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at)")
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
            # 工具失败：status=error 或 output 为空（后端没启/返回空结果）
            if status == "error":
                tool_error_count += 1
            else:
                output = n.get("data", {}).get("output", "")
                if not output or (isinstance(output, str) and not output.strip()):
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
    safety_interrupt = 0
    # 找最后一个 done 的 Answer 节点
    for n in reversed(nodes):
        if n.get("type") == "Answer" and n.get("status") == "done":
            degraded = 1 if n.get("data", {}).get("degraded") else 0
            safety_interrupt = 1 if n.get("data", {}).get("safety_interrupt") else 0
            break

    interrupted = 1 if meta.get("interrupted") else 0

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
        "interrupted": interrupted,
        "safety_interrupt": safety_interrupt,
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
    conversation_id = meta.get("conversation_id", "")
    created_at = datetime.utcnow().isoformat()

    snapshot_json = json.dumps(snapshot, ensure_ascii=False)

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO runs (
                run_id, query, created_at, final_answer,
                total_nodes, plan_count, toolcall_count, observe_count, answer_count,
                total_duration_ms, degraded, tool_error_count, snapshot, conversation_id,
                interrupted, safety_interrupt
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, query, created_at, stats["final_answer"],
                stats["total_nodes"], stats["plan_count"], stats["toolcall_count"],
                stats["observe_count"], stats["answer_count"],
                stats["total_duration_ms"], stats["degraded"],
                stats["tool_error_count"], snapshot_json, conversation_id,
                stats["interrupted"], stats["safety_interrupt"],
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

# ─────────────────── 事件记录 ───────────────────

def save_event(event_type: str, run_id: str = "", conversation_id: str = "", detail: str = ""):
    """记录一条运维事件（断连/重连/续跑/打断等）"""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO events (event_type, run_id, conversation_id, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (event_type, run_id, conversation_id, detail, datetime.utcnow().isoformat()),
        )
        conn.commit()
    except Exception as e:
        print(f"[admin] save_event 失败: {e}")
    finally:
        conn.close()


def mark_run_resumed(run_id: str):
    """标记某次 run 是续跑完成的"""
    conn = _get_conn()
    try:
        conn.execute("UPDATE runs SET resumed = 1 WHERE run_id = ?", (run_id,))
        conn.commit()
    except Exception as e:
        print(f"[admin] mark_run_resumed 失败: {e}")
    finally:
        conn.close()


# ─────────────────── 查询 ───────────────────

def get_overview() -> dict:
    """总览指标（含断连恢复 + 运行质量）"""
    # 防御：表不存在时先初始化（兑底 init_db 未被调用的场景）
    init_db()
    conn = _get_conn()
    try:
        # Run 级指标
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total_runs,
                SUM(CASE WHEN degraded = 0 AND answer_count > 0 THEN 1 ELSE 0 END) as answer_count,
                SUM(degraded) as degraded_count,
                SUM(tool_error_count) as tool_error_total,
                AVG(total_duration_ms) as avg_duration_ms,
                SUM(interrupted) as interrupted_count,
                SUM(safety_interrupt) as safety_interrupt_count,
                SUM(resumed) as resumed_count,
                AVG(plan_count) as avg_plan_rounds,
                MAX(plan_count) as max_plan_rounds
            FROM runs
            """
        ).fetchone()

        # P50/P95 耗时
        durations = [r[0] for r in conn.execute(
            "SELECT total_duration_ms FROM runs WHERE total_duration_ms > 0 ORDER BY total_duration_ms"
        ).fetchall()]
        p50 = durations[len(durations) // 2] if durations else 0
        p95 = durations[int(len(durations) * 0.95)] if durations else 0

        # 事件级指标
        evt_row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN event_type = 'disconnect' THEN 1 ELSE 0 END) as disconnect_count,
                SUM(CASE WHEN event_type = 'reconnect' THEN 1 ELSE 0 END) as reconnect_count,
                SUM(CASE WHEN event_type = 'resume' THEN 1 ELSE 0 END) as resume_trigger_count,
                SUM(CASE WHEN event_type = 'resume_success' THEN 1 ELSE 0 END) as resume_success_count,
                SUM(CASE WHEN event_type = 'auto_retry_exhausted' THEN 1 ELSE 0 END) as auto_retry_exhausted_count
            FROM events
            """
        ).fetchone()

        total_runs = row["total_runs"] or 0
        answer_count = row["answer_count"] or 0
        degraded_count = row["degraded_count"] or 0

        answer_rate = answer_count / total_runs if total_runs > 0 else 0.0
        degraded_rate = degraded_count / total_runs if total_runs > 0 else 0.0

        no_answer_count = total_runs - answer_count

        return {
            # 基础指标
            "total_runs": total_runs,
            "answer_rate": round(answer_rate, 4),
            "degraded_rate": round(degraded_rate, 4),
            "no_answer_count": no_answer_count,
            "tool_error_total": row["tool_error_total"] or 0,
            "avg_duration_ms": round(row["avg_duration_ms"] or 0, 1),
            # 断连恢复指标
            "disconnect_count": evt_row["disconnect_count"] or 0,
            "reconnect_count": evt_row["reconnect_count"] or 0,
            "resume_trigger_count": evt_row["resume_trigger_count"] or 0,
            "resume_success_count": evt_row["resume_success_count"] or 0,
            "auto_retry_exhausted_count": evt_row["auto_retry_exhausted_count"] or 0,
            "resumed_run_count": row["resumed_count"] or 0,
            # 运行质量指标
            "interrupted_count": row["interrupted_count"] or 0,
            "safety_interrupt_count": row["safety_interrupt_count"] or 0,
            "avg_plan_rounds": round(row["avg_plan_rounds"] or 0, 2),
            "max_plan_rounds": row["max_plan_rounds"] or 0,
            # 性能指标
            "p50_duration_ms": p50,
            "p95_duration_ms": p95,
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
                   total_duration_ms, degraded, tool_error_count, created_at,
                   conversation_id, interrupted, safety_interrupt, resumed
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
                "conversation_id": r["conversation_id"] or r["run_id"],
                "interrupted": bool(r["interrupted"]),
                "safety_interrupt": bool(r["safety_interrupt"]),
                "resumed": bool(r["resumed"]),
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
