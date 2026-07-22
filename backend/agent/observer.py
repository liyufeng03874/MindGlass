"""MindGlass Agent — Observe 结构化评估

Observe 节点的核心逻辑：
- 对 ToolCall 返回的原始结果做总结、去重、矛盾检测
- 输出结构化 JSON，追加到 observe_outputs 数组
- 只做评估，不做决策（决策权归 Plan）

设计文档：docs/observe-plan-design.md
"""

import json
from agent.llm import generate

OBSERVE_SYSTEM_PROMPT = """你是一个信息评估专家。你的任务是对搜索工具返回的原始结果进行结构化评估。

你必须严格按以下 JSON 格式返回，不要有其他文字：
{
  "round": 1,
  "summary": "本轮检索的核心信息提炼（2-3句话）",
  "key_findings": ["要点1", "要点2", "要点3"],
  "conflicts": [
    {
      "topic": "矛盾点描述",
      "sources": ["来源A说...", "来源B说..."],
      "resolution": "选取了A，因为...",
      "confidence": "high | medium | low"
    }
  ],
  "duplicates_removed": 0,
  "new_info_vs_previous": "首轮检索"
}

评估规则：
1. **总结**：提炼本轮检索的核心信息，不是复制粘贴，是理解后的精炼表达
2. **去重**：如果多条结果说的是同一件事，合并为一条，duplicates_removed 记录去重数量
3. **矛盾检测**：
   - 如果多个结果存在矛盾，综合按发布时间和发布机构选取权威度更高的
   - **禁止自行中和矛盾**（不要说"A和B都有道理"）
   - 如果实在无法调和，在 resolution 中说明存在的矛盾，confidence 标为 low
   - 也可以基于内容本身判断可信度
4. **增量对比**：如果不是首轮，new_info_vs_previous 说明相比上一轮新增了什么信息
5. key_findings 是去重、矛盾处理后的干净要点列表，每个要点应该是一个完整的信息单元

注意：你只做评估，不做决策。不要建议"是否需要继续搜索"或"信息是否充足"——那是 Plan 节点的职责。"""


async def observe(query: str, raw_results: list[dict], previous_outputs: list[dict] = None) -> dict:
    """
    对工具返回的原始结果进行结构化评估。

    参数：
        query: 用户原始问题（提供评估上下文）
        raw_results: 本轮 ToolCall 返回的原始结果列表
        previous_outputs: 之前轮次的 observe 输出（用于增量对比）

    返回：
        结构化评估对象（符合 OBSERVE_SYSTEM_PROMPT 定义的 schema）
    """
    previous_outputs = previous_outputs or []

    # 构建 prompt
    parts = [f"用户原始问题：{query}\n"]

    # 历史轮次摘要（如果有）
    if previous_outputs:
        parts.append("=== 之前轮次的评估结果 ===")
        for i, prev in enumerate(previous_outputs):
            parts.append(f"\n--- 第 {prev.get('round', i + 1)} 轮 ---")
            parts.append(f"摘要：{prev.get('summary', '')}")
            findings = prev.get('key_findings', [])
            if findings:
                parts.append(f"要点：{'; '.join(findings)}")
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
    parts.append(f"\n\n这是第 {round_num} 轮检索。请按 JSON 格式输出结构化评估（round 字段填 {round_num}）。")

    prompt = "\n".join(parts)

    result = generate(prompt, system_prompt=OBSERVE_SYSTEM_PROMPT)

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
            "summary": "评估结果解析失败，原始结果已保留",
            "key_findings": [],
            "conflicts": [],
            "duplicates_removed": 0,
            "new_info_vs_previous": "首轮检索" if round_num == 1 else "解析失败",
            "_raw_fallback": result[:500],
        }
