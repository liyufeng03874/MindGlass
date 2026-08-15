"""MindGlass Agent - Observe 结构化评估

Observe 节点的核心逻辑:
- 对 ToolCall 返回的原始结果做总结、去重、矛盾检测
- 输出结构化 JSON,追加到 observe_outputs 数组
- 只做评估,不做决策(决策权归 Plan)

设计文档:docs/observe-plan-design.md
"""

import json
import asyncio
from agent.llm import generate, generate_stream

OBSERVE_SYSTEM_PROMPT = """你是一个信息评估专家。你的任务是对搜索工具返回的原始结果进行结构化评估。

你必须严格按以下 JSON 格式返回,不要有其他文字:
{
  "round": 1,
  "summary": "本轮检索的核心信息提炼(2-3句话)",
  "key_findings": ["要点1", "要点2", "要点3"],
  "conflicts": [
    {
      "topic": "矛盾点描述",
      "sources": ["来源A说...", "来源B说..."],
      "resolution": "选取了A,因为...",
      "confidence": "high | medium | low"
    }
  ],
  "duplicates_removed": 0,
  "new_info_vs_previous": "首轮检索"
}

评估规则：
1. **总结**：提炼本轮检索的核心信息，不是复制粘贴，是理解后的精炼表达
2. **与用户问题的相关性优先**：key_findings 必须优先保留与用户原始问题直接相关的细节。例如用户问“h7指标是什么意思”，则 h7 的定义、计算公式、具体数值等原文细节必须保留在 key_findings 中，不得概括丢失。**宁可多保留相关细节，也不要过度精炼导致关键信息丢失**
3. **SQL 结果评估（当工具结果包含 columns/rows 字段时）**：
   - 检查返回的数据是否回答了用户问题（字段是否对得上、行数是否合理）
   - key_findings 中保留关键数据点（如“产品A销售额最高为 50万”、“共有 12 条记录”）
   - 如果 SQL 执行报错或返回空结果，如实报告，不要编造数据
   - **不评估 SQL 语句本身是否正确**，只评估执行结果的数据内容
4. **去重**：如果多条结果说的是同一件事，合并为一条，duplicates_removed 记录去重数量
5. **矛盾检测**：
   - 如果多个结果存在矛盾，综合按发布时间和发布机构选取权威度更高的
   - **禁止自行中和矛盾**（不要说“A和B都有道理”）
   - 如果实在无法调和，在 resolution 中说明存在的矛盾，confidence 标为 low
   - 也可以基于内容本身判断可信度
5. **增量对比**：如果不是首轮，new_info_vs_previous 说明相比上一轮新增了什么信息
6. key_findings 是去重、矛盾处理后的干净要点列表，每个要点应该是一个完整的信息单元，且必须包含回答用户问题所需的具体事实/定义/数据

注意:你只做评估,不做决策。不要建议"是否需要继续搜索"或"信息是否充足"--那是 Plan 节点的职责。"""


async def observe(query: str, raw_results: list[dict], previous_outputs: list[dict] = None,
                  stream_emit=None, node_id: str = None, node_type: str = "Observe") -> dict:
    """
    对工具返回的原始结果进行结构化评估(支持流式)。

    参数:
        query: 用户原始问题(提供评估上下文)
        raw_results: 本轮 ToolCall 返回的原始结果列表
        previous_outputs: 之前轮次的 observe 输出(用于增量对比)
        stream_emit: 可选回调 (chunk, content),用于流式推送
        node_id: 节点 ID(用于流式事件标识)
        node_type: 节点类型(用于流式事件标识)

    返回:
        结构化评估对象(符合 OBSERVE_SYSTEM_PROMPT 定义的 schema)
    """
    previous_outputs = previous_outputs or []

    # 构建 prompt
    parts = [f"用户原始问题:{query}\n"]

    # 历史轮次摘要(如果有)
    if previous_outputs:
        parts.append("=== 之前轮次的评估结果 ===")
        for i, prev in enumerate(previous_outputs):
            parts.append(f"\n--- 第 {prev.get('round', i + 1)} 轮 ---")
            parts.append(f"摘要:{prev.get('summary', '')}")
            findings = prev.get('key_findings', [])
            if findings:
                parts.append(f"要点:{'; '.join(findings)}")
        parts.append("\n=== 本轮新检索结果 ===")

    # 本轮原始结果
    for i, result in enumerate(raw_results):
        parts.append(f"\n--- 工具结果 {i + 1} ---")
        if isinstance(result, dict):
            if "error" in result:
                parts.append(f"错误: {result['error']}")
            else:
                parts.append(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            parts.append(str(result))

    round_num = len(previous_outputs) + 1
    parts.append(f"\n\n这是第 {round_num} 轮检索。请按 JSON 格式输出结构化评估(round 字段填 {round_num})。")

    prompt = "\n".join(parts)

    if stream_emit is None:
        # 非流式路径:保持原有行为
        result = generate(prompt, system_prompt=OBSERVE_SYSTEM_PROMPT)
    else:
        # 流式路径:边收 chunk 边 emit
        messages = [
            {"role": "system", "content": OBSERVE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = await _run_llm_stream(messages, stream_emit, node_id, node_type)

    # 解析 JSON
    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(cleaned)
        # 确保 round 字段正确
        parsed["round"] = round_num
        return parsed
    except Exception:
        # 解析失败时返回兜底结构
        return {
            "round": round_num,
            "summary": "评估结果解析失败,原始结果已保留",
            "key_findings": [],
            "conflicts": [],
            "duplicates_removed": 0,
            "new_info_vs_previous": "首轮检索" if round_num == 1 else "解析失败",
            "_raw_fallback": result[:500],
        }


async def _run_llm_stream(messages: list, stream_emit, node_id: str, node_type: str) -> str:
    """通用流式 LLM 调用:边收 chunk 边 emit,返回完整文本。

    stream_emit(chunk, content) 回调,content 为累计全文。
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
