"""MindGlass — FastAPI 入口"""

import os
import json
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
load_dotenv()

from state.store import ReasoningGraphStore
from agent.react_loop import ReactLoop

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
        async for event in loop.run(query):
            yield event

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
    方案 C 并行重试：接收完整图数据 + 新工具参数，只重跑新工具，融合后送 Answer
    body: {
        "step_index": 1,
        "full_graph": { nodes: [...], edges: [...] },
        "new_tool_calls": [{ "tool": "search", "params": {...} }],
        "preserved_observations": [...],
        "query": "...",
        "plan_info": "..."
    }
    """
    step_index = request.get("step_index")
    new_tool_calls = request.get("new_tool_calls", [])
    preserved_observations = request.get("preserved_observations", [])
    query = request.get("query", "")
    plan_info = request.get("plan_info", "")

    if step_index is None or not new_tool_calls:
        raise HTTPException(status_code=400, detail="step_index and new_tool_calls are required")

    loop = ReactLoop(_store)

    async def event_stream():
        async for event in loop.retry_from_graph(step_index, new_tool_calls, preserved_observations, query, plan_info):
            yield event

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/load-demo")
def load_demo():
    """加载 demo_6.txt 作为测试数据"""
    import os
    demo_path = os.path.join(os.path.dirname(__file__), "docs", "demo_6.txt")
    if not os.path.exists(demo_path):
        raise HTTPException(status_code=404, detail="demo_6.txt 不存在")

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

        return {"status": "ok", "message": "已加载 demo_6 测试数据", "node_count": len(graph_data.get("nodes", []))}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"JSON 解析失败：{str(e)}")


if __name__ == "__main__":
    port = int(os.getenv("MINDGLASS_PORT", "8002"))
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
