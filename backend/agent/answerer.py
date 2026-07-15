"""MindGlass Agent — 最终回答生成"""

from agent.llm import generate

ANSWER_SYSTEM_PROMPT = """你是一个专业的 AI 助手。根据用户的问题和收集到的信息，给出准确、完整、有条理的回答。

回答要求：
1. 基于提供的信息回答，不要编造
2. 如果信息不足，说明哪些部分无法确定
3. 回答要有条理，使用适当的格式
"""


async def generate_answer(query: str, observations: list[dict]) -> str:
    """
    基于所有观察结果，生成最终回答
    """
    # 构建上下文
    context_parts = []
    for i, obs in enumerate(observations):
        context_parts.append(f"## 观察 {i+1}")
        if "result" in obs:
            import json
            result_text = json.dumps(obs["result"], ensure_ascii=False, indent=2) if isinstance(obs["result"], dict) else str(obs["result"])
            context_parts.append(result_text[:500])  # 限制长度
        elif "error" in obs:
            context_parts.append(f"错误: {obs['error']}")

    context = "\n\n".join(context_parts)

    prompt = f"""用户问题: {query}

收集到的信息:
{context}

请根据以上信息回答用户的问题："""

    result = generate(prompt, system_prompt=ANSWER_SYSTEM_PROMPT)
    return result
