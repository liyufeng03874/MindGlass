"""MindGlass — FastAPI 入口"""

import os
import json
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
load_dotenv()

from state.store import ReasoningGraphStore
from state.models import ReasoningNode, ReasoningEdge
from agent.react_loop import ReactLoop
from agent.tools import list_tools

# Admin 持久化层
from admin.persistence import init_db as admin_init_db, save_run as admin_save_run
from admin.persistence import get_overview as admin_get_overview
from admin.persistence import get_runs as admin_get_runs
from admin.persistence import get_run_snapshot as admin_get_run_snapshot
from admin.persistence import save_event as admin_save_event
from admin.persistence import mark_run_resumed as admin_mark_run_resumed

# Redis 热缓存层（断连恢复 + 生产化）
from state import redis_cache

# 初始化 admin DB 表结构
admin_init_db()

# 安全校验模型（启动时加载）
from moderation.predict import load_model

app = FastAPI(title="MindGlass", description="可观测多步推理 Agent")

@app.on_event("startup")
def startup_load_models():
    """启动时加载安全校验模型"""
    load_model()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局状态 store（每个 run 独立实例）
_store = ReasoningGraphStore()


def _redis_change_listener(kind: str, data: dict, meta: dict):
    """图组件新增 → Redis RPUSH 增量追加（正常推进快路径）"""
    redis_cache.append_item(meta.get("run_id", ""), kind, data, meta)


_store.set_change_listener(_redis_change_listener)

# 当前活跃的 ReactLoop 实例（打断端点用；单 store 天然只有一个活跃 run）
_active_loop: Optional[ReactLoop] = None


@app.get("/api/health")
def health():
    return {"status": "ok", "project": "MindGlass", **redis_cache.health()}


@app.get("/api/tools")
def get_tools():
    """列出所有可用工具"""
    return {"tools": list_tools()}


@app.get("/api/graph")
def get_graph():
    """获取当前推理图状态。

    断连恢复：内存图为空（如后端重启）时从 Redis 热缓存重建，
    位置由前端固定算法重排，不存坐标。
    """
    if not _store.nodes:
        snapshot = redis_cache.load()
        if snapshot.get("nodes"):
            _store.load_from_dict(snapshot)
    return _store.to_dict()


@app.post("/api/reuse/check")
def reuse_check(request: dict):
    """高频 query 思维图复用检查。

    body: {"query": "..."}
    用 other-world embed 算语义相似度，命中阈值（默认 0.92）且图还在 → 返回旧图；
    向量化服务不在线/索引为空/未命中 → hit=False，前端照常发起新 run。
    """
    query = request.get("query", "")
    if not query:
        return {"hit": False, "best_similarity": 0.0, "reason": "empty_query"}
    return redis_cache.find_reusable(query)


@app.post("/api/run")
async def run_agent(request: dict):
    """
    启动 ReAct 推理（SSE 流式推送）
    返回 SSE stream，逐步推送节点和状态
    body: {"query": "...", "history": [...], "conversation_id": "conv_xxx"(可选，多轮对话复用)}
    """
    query = request.get("query", "")
    history_msgs = request.get("history", [])
    conversation_id = request.get("conversation_id", "")
    
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    loop = ReactLoop(_store)

    async def event_stream():
        """SSE 事件流，run 完成后自动落盘快照"""
        global _active_loop
        _active_loop = loop
        try:
            async for event in loop.run(query, history_msgs, conversation_id):
                yield event
        finally:
            _active_loop = None
            # SSE 流结束 → run 已完成（或被用户打断）→ 保存快照
            try:
                snapshot = _store.to_dict()
                if snapshot.get("nodes"):
                    admin_save_run(snapshot)
                    # Redis 整体覆盖：流结束时的图是权威的（含打断/状态变更），
                    # 覆盖掉增量追加阶段的中间态
                    redis_cache.overwrite(snapshot.get("meta", {}).get("run_id", ""), snapshot)
            except Exception as e:
                # 落盘失败不影响用户端，仅日志记录
                print(f"[admin] 保存 run 快照失败: {e}")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/interrupt")
def interrupt_run(request: dict):
    """
    打断当前运行中的推理。
    body: { "step_index": 3 }  —— 截断点（保留该节点，之后的节点全部置灰保留）
    """
    if _active_loop is None:
        return {"status": "no_active_run"}
    step_index = request.get("step_index")
    _active_loop.request_interrupt(step_index)
    return {"status": "ok", "cut_step_index": step_index}


@app.post("/api/retry")
def retry_from(request: dict):
    """
    从指定 step 重试
    body: { "step_index": 2, "edited_data": {...} }
    """
    step_index = request.get("step_index")
    if step_index is None:
        raise HTTPException(status_code=400, detail="step_index is required")

    edited_data = request.get("edited_data")
    loop = ReactLoop(_store)

    async def event_stream():
        try:
            async for event in loop.retry_from(step_index, edited_data):
                yield event
        finally:
            # 重试也落盘（upsert 同 run_id），admin 思维重现才能看到重试分支
            try:
                snapshot = _store.to_dict()
                if snapshot.get("nodes"):
                    admin_save_run(snapshot)
                    # 编辑/重放路径：后端算好的完整新图整体覆盖 Redis
                    redis_cache.overwrite(snapshot.get("meta", {}).get("run_id", ""), snapshot)
            except Exception as e:
                print(f"[admin] 保存 retry 快照失败: {e}")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/retry_from_graph")
async def retry_from_graph(request: dict):
    """
    方案 C 并行重试：前端发送完整上下文+标记，后端融合
    body: {
        "step_index": 1,
        "old_nodes": [{...original: 'old'...}],
        "new_nodes": [{...original: 'new'...}],
        "query": "...",
        "plan_info": "..."
    }
    """
    step_index = request.get("step_index")
    old_nodes = request.get("old_nodes", [])
    new_nodes = request.get("new_nodes", [])
    query = request.get("query", "")
    plan_info = request.get("plan_info", "")

    if step_index is None or not new_nodes:
        raise HTTPException(status_code=400, detail="step_index and new_nodes are required")

    loop = ReactLoop(_store)

    async def event_stream():
        try:
            async for event in loop.retry_from_graph(step_index, old_nodes, new_nodes, query, plan_info):
                yield event
        finally:
            try:
                snapshot = _store.to_dict()
                if snapshot.get("nodes"):
                    admin_save_run(snapshot)
                    # 编辑/重放路径：后端算好的完整新图整体覆盖 Redis
                    redis_cache.overwrite(snapshot.get("meta", {}).get("run_id", ""), snapshot)
            except Exception as e:
                print(f"[admin] 保存 retry_from_graph 快照失败: {e}")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/resume")
async def resume_agent():
    """断连续跑：从当前图的最后一个活跃节点继续推理。

    前端断连重连后调用，后端从 Redis/内存恢复图状态后接着跑。
    复用 react_loop 的 _decision_loop / _stream_plan 等已有逻辑。
    """
    # 确保内存图是最新的（后端重启时可能为空）
    if not _store.nodes:
        snapshot = redis_cache.load()
        if snapshot.get("nodes"):
            _store.load_from_dict(snapshot)

    if not _store.nodes:
        raise HTTPException(status_code=400, detail="无可用图状态，无法续跑")

    loop = ReactLoop(_store)

    run_id = _store.meta.run_id or ""
    conv_id = _store.meta.conversation_id or ""
    admin_save_event("resume", run_id, conv_id)

    async def event_stream():
        global _active_loop
        _active_loop = loop
        try:
            async for event in loop.resume():
                yield event
        finally:
            _active_loop = None
            try:
                snapshot = _store.to_dict()
                if snapshot.get("nodes"):
                    admin_save_run(snapshot)
                    admin_mark_run_resumed(run_id)
                    redis_cache.overwrite(
                        snapshot.get("meta", {}).get("run_id", ""), snapshot
                    )
                    # 检查是否有 Answer → 续跑成功
                    has_answer = any(
                        n.get("type") == "Answer" and n.get("status") == "done"
                        for n in snapshot.get("nodes", [])
                    )
                    if has_answer:
                        admin_save_event("resume_success", run_id, conv_id)
            except Exception as e:
                print(f"[admin] 保存 resume 快照失败: {e}")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/events/log")
def log_event(request: dict):
    """前端上报运维事件（断连/重连/续跑/自动重试失败等）。

    body: {"event_type": "disconnect|reconnect|auto_retry_exhausted", "run_id": "...", "detail": "..."}
    """
    event_type = request.get("event_type", "")
    if not event_type:
        raise HTTPException(status_code=400, detail="event_type is required")
    run_id = request.get("run_id", "")
    conversation_id = request.get("conversation_id", "")
    detail = request.get("detail", "")
    admin_save_event(event_type, run_id, conversation_id, detail)
    return {"status": "ok"}


@app.get("/api/list-demos")
def list_demos():
    """列出所有可用的测试用例，返回 [{name, label, source}] 供前端下拉框使用。
    label 显示原始 query（不暴露文件名），source 区分 demo/static vs real run。"""
    import os
    import re
    docs_dir = os.path.join(os.path.dirname(__file__), "docs")
    demos = []

    # 1. 静态 demo 文件：直接从文件内容读 meta.query 作 label
    for f in sorted(os.listdir(docs_dir)):
        if not f.endswith(".txt"):
            continue
        label = ''
        try:
            with open(os.path.join(docs_dir, f), "r", encoding="utf-8") as fh:
                snap = json.loads(fh.read().strip())
            graph = snap.get("data", {}).get("graph", snap)
            label = graph.get("meta", {}).get("query", "").strip()
        except Exception:
            pass
        if not label:
            # 文件里没有 query，用编号兜底，不暴露文件名
            m = re.match(r'^demo_(\w+)', f)
            label = f"测试用例 {m.group(1)}" if m else f.replace('.txt', '')
        demos.append({"name": f, "label": label, "source": "demo"})

    return {"demos": demos}


@app.post("/api/load-demo")
def load_demo(demo: str = Query(default="1")):
    """加载静态测试数据，支持数字编号或完整文件名"""
    import os
    import re
    docs_dir = os.path.join(os.path.dirname(__file__), "docs")

    if re.match(r'^\d+$', demo):
        pattern = re.compile(rf'^demo_{re.escape(demo)}\(.*\)\.txt$')
        matched = [f for f in os.listdir(docs_dir) if pattern.match(f)]
        if not matched:
            raise HTTPException(status_code=404, detail=f"demo_{demo} 不存在")
        demo_name = matched[0]
    else:
        demo_name = demo if demo.endswith(".txt") else f"{demo}.txt"

    demo_path = os.path.join(docs_dir, demo_name)
    if not os.path.exists(demo_path):
        raise HTTPException(status_code=404, detail=f"{demo_name} 不存在")

    with open(demo_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    try:
        # 解析 JSON 格式（可能是嵌套的 {"type": "run_complete", "data": {"graph": {...}}}）
        parsed = json.loads(content)
        # 提取 graph 数据
        if "data" in parsed and "graph" in parsed["data"]:
            graph_data = parsed["data"]["graph"]
        elif "nodes" in parsed and "edges" in parsed:
            graph_data = parsed
        else:
            graph_data = parsed

        # 重置 store 并加载数据
        _store.reset()
        for node in graph_data.get("nodes", []):
            from state.models import ReasoningNode
            _store.add_node(ReasoningNode(
                node_id=node["id"],
                node_type=node["type"],
                data=node["data"],
                status=node["status"],
                step_index=node["step_index"],
                label=node.get("label", node["type"]),
            ))
        for edge in graph_data.get("edges", []):
            from state.models import ReasoningEdge
            _store.add_edge(ReasoningEdge(
                from_id=edge["from"],
                to_id=edge["to"],
                edge_type=edge.get("type", "Normal"),
            ))

        return {"status": "ok", "message": f"已加载 {demo_name} 测试数据", "node_count": len(graph_data.get("nodes", [])), "graph": graph_data}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"JSON 解析失败：{str(e)}")


if __name__ == "__main__":
    port = int(os.getenv("MINDGLASS_PORT", "8002"))
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)


# ──────────────────────────────────────────────────────────────
# Admin 后台管理接口（新增，不影响现有用户端）
# ──────────────────────────────────────────────────────────────

@app.get("/api/admin/overview")
def admin_overview():
    """总览指标：total_runs, answer_rate, degraded_rate, tool_error_total, avg_duration_ms"""
    return admin_get_overview()


@app.get("/api/admin/runs")
def admin_runs(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """run 列表（分页），返回统计字段列（不含完整快照）"""
    return admin_get_runs(limit=limit, offset=offset)


@app.get("/api/admin/runs/{run_id}")
def admin_run_detail(run_id: str):
    """单条完整快照 {nodes,edges,branches,meta}，供前端思维重现"""
    snapshot = admin_get_run_snapshot(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"run_id={run_id} 不存在")
    return snapshot
