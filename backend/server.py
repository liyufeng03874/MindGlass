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


if __name__ == "__main__":
    port = int(os.getenv("MINDGLASS_PORT", "8002"))
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
