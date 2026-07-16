"""MindGlass Agent — 工具注册与执行"""

import httpx
from typing import Callable, Optional
from dotenv import load_dotenv
import os
import re
from bs4 import BeautifulSoup

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
    description="网络搜索，返回搜索结果摘要（使用 Tavily AI 搜索引擎）",
    params=[
        {"name": "query", "type": "string", "description": "搜索关键词"},
        {"name": "top_k", "type": "integer", "description": "返回结果数量", "default": 5},
    ],
)
async def tool_search(query: str, top_k: int = 5) -> dict:
    """
    网络搜索工具（使用 Tavily AI 搜索引擎）
    返回结构化搜索结果
    """
    import os
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        return {"query": query, "error": "TAVILY_API_KEY not configured", "results": []}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "query": query,
                    "search_depth": "basic",
                    "max_results": top_k,
                    "include_answer": True,
                    "include_images": False,
                },
                headers={"Authorization": f"Bearer {tavily_key}", "Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for r in data.get("results", []):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("content", ""),
                    })
                return {
                    "query": query,
                    "answer": data.get("answer", ""),
                    "results": results,
                    "count": len(results),
                }
            else:
                return {"query": query, "error": f"Tavily API error: {resp.status_code} - {resp.text}", "results": []}
    except Exception as e:
        return {"query": query, "error": str(e), "results": []}


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
