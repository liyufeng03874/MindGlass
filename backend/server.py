"""MindGlass — FastAPI 入口"""

import os
import json
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
load_dotenv()

from state.store import ReasoningGraphStore
from state.models import ReasoningNode, ReasoningEdge
from agent.react_loop import ReactLoop

# Admin 持久化层
from admin.persistence import init_db as admin_init_db, save_run as admin_save_run
from admin.persistence import get_overview as admin_get_overview
from admin.persistence import get_runs as admin_get_runs
from admin.persistence import get_run_snapshot as admin_get_run_snapshot

# 初始化 admin DB 表结构
admin_init_db()

app = FastAPI(title="MindGlass", description="可观测多步推理 Agent")

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


@app.get("/api/health")
def health():
    return {"status": "ok", "project": "MindGlass"}


@app.get("/api/tools")
def get_tools():
    """列出所有可用工具"""
    return {"tools": list_tools()}


@app.get("/api/graph")
def get_graph():
    """获取当前推理图状态"""
    return _store.to_dict()


@app.get("/api/run")
async def run_agent(query: str = Query(...)):
    """
    启动 ReAct 推理（SSE 流式推送）
    返回 SSE stream，逐步推送节点和状态
    """
    loop = ReactLoop(_store)

    async def event_stream():
        """SSE 事件流，run 完成后自动落盘快照"""
        try:
            async for event in loop.run(query):
                yield event
        finally:
            # SSE 流结束 → run 已完成 → 保存快照
            try:
                snapshot = _store.to_dict()
                if snapshot.get("nodes"):
                    admin_save_run(snapshot)
            except Exception as e:
                # 落盘失败不影响用户端，仅日志记录
                print(f"[admin] 保存 run 快照失败: {e}")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
        async for event in loop.retry_from(step_index, edited_data):
            yield event

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
        async for event in loop.retry_from_graph(step_index, old_nodes, new_nodes, query, plan_info):
            yield event

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/load-demo")
def load_demo(demo: str = Query(default="1")):
    """加载 demo 静态数据，支持数字编号（如 1、2、3）或完整文件名"""
    import os
    import re
    docs_dir = os.path.join(os.path.dirname(__file__), "docs")

    # 如果传入的是纯数字，匹配 demo_N(描述).txt 格式
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
