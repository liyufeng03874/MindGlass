"""MindGlass Agent — 最终回答生成

输入变更（v2）：
- 旧：observations[]（raw tool results 列表）
- 新：observe_outputs[]（Observe 结构化评估报告数组）+ Plan 决策 + 降级标记

设计文档：docs/observe-plan-design.md
"""

import json
import asyncio
from agent.llm import generate, generate_stream

ANSWER_SYSTEM_PROMPT = """你是一个专业的 AI 助手。根据用户的问题、各轮检索评估报告和收集到的结构化信息，给出准确、完整、有条理的回答。

回答要求：
1. 基于提供的结构化评估报告回答，不要编造
2. 如果存在矛盾（conflicts），采用评估报告中已选取的结论（resolution），不要自行重新判断
3. 如果信息不足（降级模式），在回答开头诚实说明哪些方面信息可能不完整，然后基于已有信息给出尽可能有用的回答
4. 回答要有条理，使用适当的格式
5. 必须用中文回答
"""

ANSWER_DEGRADED_PREFIX = """⚠️ 信息完整性提示：{note}

---

"""


async def generate_answer(
    query: str,
    observe_outputs: list[dict],
    plan_decision: dict = None,
    degraded: bool = False,
    stream_emit=None,
    node_id: str = None,
    node_type: str = "Answer",
) -> str:
    """
    基于 Observe 结构化评估报告生成最终回答（支持流式）。

    参数：
        query: 用户原始问题
        observe_outputs: Observe 结构化输出数组（每轮一个对象）
        plan_decision: Plan 节点的最终决策（含 reasoning、if_terminate 等）
        degraded: 是否为降级模式（强制终止，信息可能不完整）
        stream_emit: 可选回调 (chunk, content)，用于流式推送
        node_id: 节点 ID（用于流式事件标识）
        node_type: 节点类型（用于流式事件标识）
    """
    # 构建上下文
    context_parts = []

    # 1. 各轮评估报告
    for obs in observe_outputs:
        round_num = obs.get("round", "?")
        context_parts.append(f"## 第 {round_num} 轮检索评估")
        context_parts.append(f"摘要：{obs.get('summary', '')}")

        findings = obs.get("key_findings", [])
        if findings:
            context_parts.append("要点：")
            for f in findings:
                context_parts.append(f"  - {f}")

        conflicts = obs.get("conflicts", [])
        if conflicts:
            context_parts.append("矛盾处理：")
            for c in conflicts:
                context_parts.append(f"  - {c.get('topic', '')}: {c.get('resolution', '')} (置信度: {c.get('confidence', '?')})")

        new_info = obs.get("new_info_vs_previous", "")
        if new_info and round_num != 1:
            context_parts.append(f"新增信息：{new_info}")

    # 2. Plan 决策上下文
    if plan_decision:
        reasoning = plan_decision.get("reasoning", "")
        if reasoning:
            context_parts.append(f"\n## 决策说明\n{reasoning}")

    context = "\n\n".join(context_parts)

    prompt = f"""用户问题: {query}

收集到的结构化评估报告:
{context}

请根据以上评估报告回答用户的问题："""

    if stream_emit is None:
        # 非流式路径：保持原有行为
        result = generate(prompt, system_prompt=ANSWER_SYSTEM_PROMPT)
    else:
        # 流式路径：边收 chunk 边 emit
        messages = [
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = await _run_llm_stream(messages, stream_emit, node_id, node_type)

    # 降级模式：在回答前加提示信息
    if degraded and plan_decision:
        note = plan_decision.get("if_terminate", {}).get(
            "partial_answer_note",
            "部分信息可能不完整，建议进一步查证。"
        )
        result = ANSWER_DEGRADED_PREFIX.format(note=note) + result

    return result


async def _run_llm_stream(messages: list, stream_emit, node_id: str, node_type: str) -> str:
    """通用流式 LLM 调用：边收 chunk 边 emit，返回完整文本。
    
    stream_emit(chunk, content) 回调，content 为累计全文。
    """
    from agent.llm import LLM_MODEL
    from agent.llm import client

    full_text = ""
    stream = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=2048,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            token = chunk.choices[0].delta.content
            full_text += token
            stream_emit(token, full_text)
    return full_text
