"""MindGlass Agent — 任务规划"""

from agent.llm import generate

PLANNING_SYSTEM_PROMPT = """你是一个任务规划专家。给定用户的查询，你需要将其拆解为一系列可执行的步骤。
每一步应该是一个明确的动作，并且能够被以下工具之一执行：
- search: 网络搜索
- rag_retrieve: 本地知识库检索

请严格按以下 JSON 格式返回，不要有其他文字：
{
  "thought": "简短思考说明",
  "steps": [
    {"tool": "工具名", "description": "步骤描述", "params": {"query": "..."}}
  ]
}

注意：
1. 如果查询很简单，可以直接用一步完成
2. 如果需要多步，按逻辑顺序排列
3. params 必须包含 query 字段
"""


async def plan(query: str) -> dict:
    """
    接收用户 query，调用 LLM 返回拆解的步骤列表
    返回: {"thought": "...", "steps": [{"tool": "...", "description": "...", "params": {...}}]}
    """
    prompt = f"用户查询: {query}\n\n请拆解为可执行步骤："
    result = generate(prompt, system_prompt=PLANNING_SYSTEM_PROMPT)

    import json
    # 尝试解析 JSON（LLM 可能返回 markdown 代码块包裹的 JSON）
    try:
        # 清理 markdown 代码块
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(cleaned)
        return parsed
    except Exception:
        # 如果解析失败，返回一个默认的 search 步骤
        return {
            "thought": "无法解析规划结果，使用默认搜索策略",
            "steps": [
                {"tool": "search", "description": "搜索相关信息", "params": {"query": query}}
            ],
        }
