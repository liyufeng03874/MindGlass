"""MindGlass Agent — 工具注册与执行"""

import httpx
from typing import Callable, Optional
from dotenv import load_dotenv
import os

load_dotenv()

RAG_API_URL = os.getenv("RAG_API_URL", "http://localhost:8001")

# 工具注册表
_tools: dict[str, dict] = {}


def register_tool(name: str, description: str, params: list[dict]):
    """装饰器：注册工具"""
    def decorator(func: Callable):
        _tools[name] = {
            "name": name,
            "description": description,
            "params": params,
            "func": func,
        }
        return func
    return decorator


def get_tool(name: str) -> Optional[dict]:
    return _tools.get(name)


def list_tools() -> list[dict]:
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "params": t["params"],
        }
        for t in _tools.values()
    ]


# ============ 内置工具 ============

@register_tool(
    name="search",
    description="网络搜索，返回搜索结果摘要",
    params=[
        {"name": "query", "type": "string", "description": "搜索关键词"},
        {"name": "top_k", "type": "integer", "description": "返回结果数量", "default": 5},
    ],
)
async def tool_search(query: str, top_k: int = 5) -> dict:
    """
    网络搜索工具（使用 web_fetch 模拟，实际可接 Tavily/Serper/Google API）
    返回结构化搜索结果
    """
    # 模拟搜索结果 —— 实际对接真实 API 时替换
    results = [
        {
            "title": f"搜索结果 {i} - {query}",
            "url": f"https://example.com/result_{i}",
            "snippet": f"这是关于「{query}」的第 {i} 条搜索结果摘要信息...",
        }
        for i in range(1, min(top_k + 1, 6))
    ]
    return {
        "query": query,
        "results": results,
        "count": len(results),
    }


@register_tool(
    name="rag_retrieve",
    description="从本地知识库检索相关段落（复用 other-world 的 RAG 能力）",
    params=[
        {"name": "query", "type": "string", "description": "检索查询"},
        {"name": "top_k", "type": "integer", "description": "返回段落数量", "default": 5},
    ],
)
async def tool_rag_retrieve(query: str, top_k: int = 5) -> dict:
    """
    调用 other-world 的 RAG 检索接口
    POST /api/chat/rag-es
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{RAG_API_URL}/api/chat/rag-es",
                json={"message": query},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "query": query,
                    "passages": data.get("sources", []),
                    "answer": data.get("message", ""),
                    "count": len(data.get("sources", [])),
                }
            else:
                return {
                    "query": query,
                    "error": f"RAG API error: {resp.status_code}",
                    "passages": [],
                    "count": 0,
                }
    except Exception as e:
        return {
            "query": query,
            "error": str(e),
            "passages": [],
            "count": 0,
        }


# ============ 工具执行器 ============

async def execute_tool(tool_name: str, params: dict) -> dict:
    """执行指定工具"""
    tool = get_tool(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}", "tool": tool_name, "params": params}

    func = tool["func"]
    try:
        result = await func(**params)
        return {
            "tool": tool_name,
            "params": params,
            "result": result,
        }
    except Exception as e:
        return {
            "tool": tool_name,
            "params": params,
            "error": str(e),
        }
