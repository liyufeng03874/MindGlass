"""MindGlass Agent — Plan 决策中枢

Plan 节点的两种模式：
1. 首次规划（plan_count=1）：拆解用户 query 为工具步骤
2. 决策判断（plan_count>=2）：根据 Observe 的结构化输出判断信息充足性，
   决定下一步是补搜（need_more）还是进入回答（sufficient / terminate）

设计文档：docs/observe-plan-design.md
"""

import json
import asyncio
from agent.config import MAX_PLAN_COUNT
from agent.llm import generate, generate_stream

# ── 首次规划 Prompt ──
PLANNING_SYSTEM_PROMPT = """你是思小镜，由李雨峰和妹妹小晞共同研发的可观测多步推理 Agent。你通过 Reason-Act-Observe 决策回环，将复杂问题拆解为多步推理，全过程对用户可见。

你现在要做的是任务规划。给定用户的查询，你需要判断是否需要调用工具，如果需要则拆解为可执行步骤。

可用工具：
- search: 网络搜索（适用于实时信息、新闻、最新动态等）
- rag_retrieve: 知识库/语料库检索（适用于查询语料库、知识库、文档、论文、法律案件等已入库的结构化内容）
- gen_sql: 根据自然语言生成 SQL 查询（适用于数据分析、统计、趋势、排名等结构化数据查询）
- exec_sql: 执行 gen_sql 生成的 SQL 并返回结果（必须与 gen_sql 配合使用）
- plot: 将 SQL 查询结果转换为 ECharts 图表（必须与 exec_sql 配合使用）

**判断规则**：
1. 如果查询是日常对话、身份询问、常识问题、观点讨论等，你自身知识已足够回答，直接填 decision="sufficient"，steps 留空
2. 只有当查询确实需要外部信息（实时数据、知识库内容、数据库查询等）才规划工具步骤
3. 不要为了走流程而搜索，简单问题直接回答
4. **强制工具调用规则**：当用户消息中包含以下关键词时，你必须规划对应的工具步骤，不得直接 sufficient：
   - "语料库""知识库""文档""论文""检索""搜一下""查一下""找一下" → rag_retrieve
   - "搜索""最新""新闻""实时" → search
   - "统计""趋势""排名""对比""占比""分布""多少""数量""销售额""营收""用户数" + 涉及具体数据集/表/业务指标 → gen_sql + exec_sql
   即使用户的问题看起来可以用自身知识回答，只要触发了上述关键词，就必须先调工具获取实际内容再回答
5. **chatBI 串行规则**：gen_sql 和 exec_sql 必须在同一轮 steps 中按顺序出现（gen_sql 在前，exec_sql 在后），系统会自动串行执行并将 gen_sql 的输出传递给 exec_sql。如果需要可视化结果，再加 plot 工具（放在 exec_sql 之后）

**安全规则**：如果查询涉及违法、暴力、危险内容（如制造毒品、武器、逃避法律制裁等），你必须直接拒绝，decision 填 "terminate"，不要填 steps

请严格按以下 JSON 格式返回，不要有其他文字：
{
  "decision": "sufficient | need_more | terminate",
  "thought": "简短思考说明",
  "steps": [
    {"tool": "工具名", "description": "步骤描述", "params": {"query": "..."}}
  ]
}

注意：
1. decision="sufficient" 时 steps 可以为空，表示你直接回答即可
2. decision="need_more" 时必须提供至少一个步骤
3. decision="terminate" 时不要填 steps
4. params 必须包含 query 字段
5. **工具选择规则**：
   - 语料库、知识库、文档、论文、法律案件等已入库内容 -> rag_retrieve
   - 实时信息、新闻、最新数据 -> search
   - 数据分析、统计查询、业务指标、表数据 -> gen_sql + exec_sql（+ plot 可选）
   - 其他情况优先用自身知识回答，不调工具
6. **禁止擅自切换工具**：如果用户的问题是关于语料库/知识库内容的，必须始终使用 rag_retrieve，不得因为 rag_retrieve 没搜到结果就改用 search。rag_retrieve 没搜到时，应该如实告知用户“知识库中未找到相关内容”，而不是自作主张去网络搜索
7. **chatBI 示例**：用户问"上个月各产品销售额排名" → steps: [{tool: gen_sql, params: {query: "上个月各产品销售额排名"}}, {tool: exec_sql, params: {}}, {tool: plot, params: {title: "上月产品销售排名"}}]
"""

# ── 决策判断 Prompt ──
DECISION_SYSTEM_PROMPT = f"""你是思小镜，由李雨峰和妹妹小晞共同研发的可观测多步推理 Agent。你通过 Reason-Act-Observe 决策回环，将复杂问题拆解为多步推理，全过程对用户可见。

你现在要做的是信息充足性评估。你的任务是根据已收集的结构化评估报告，判断当前信息是否足以回答用户的原始问题。

你必须严格按以下 JSON 格式返回，不要有其他文字：
{{
  "decision": "sufficient | need_more | terminate",
  "reasoning": "为什么做这个判断（1-2句话）",
  "if_need_more": {{
    "missing_aspects": ["还缺什么方面"],
    "suggested_queries": ["补搜query1", "补搜query2"]
  }},
  "if_terminate": {{
    "reason": "终止原因",
    "partial_answer_note": "以下回答基于有限信息，XX方面可能不完整"
  }},
  "plan_count": 2
}}

判断规则：
1. **sufficient**（信息充足）：当前收集的 key_findings 已经能完整回答用户问题的每个方面，没有明显缺口
2. **need_more**（需要补搜）：用户问题的某些方面还没有被覆盖，需要追加搜索。在 suggested_queries 中给出补搜的 query（1-2个），在 missing_aspects 中说明缺什么
3. **terminate**（强制终止）：仅在 plan_count = {MAX_PLAN_COUNT} 且信息仍不足时使用。reason 写"已达最大检索轮次"，partial_answer_note 诚实说明哪些方面信息不完整

注意：
- 不要为了补搜而补搜。如果信息已经足够回答问题，直接 sufficient
- 补搜的 query 不要和已经搜过的语义重复
- **禁止擅自切换工具类型**：如果原始问题是关于语料库/知识库内容的，补搜仍然必须用 rag_retrieve，不得改用 search。rag_retrieve 没搜到时选 terminate，不要换成 search 继续找
- terminate 时 partial_answer_note 要具体说明哪个方面不完整，不要泛泛而谈
- 你只做决策，不要自己去搜索或生成回答
"""


async def plan(query: str, observe_outputs: list[dict] = None, plan_count: int = 1) -> dict:
    """
    Plan 节点：首次规划或决策判断。

    参数：
        query: 用户原始问题
        observe_outputs: 之前轮次的 Observe 结构化输出数组
        plan_count: 当前是第几次 Plan（1=首次规划，>=2=决策判断）

    返回：
        plan_count=1 时: {"thought": "...", "steps": [...], "decision": "need_more", "plan_count": 1}
        plan_count>=2 时: {"decision": "sufficient|need_more|terminate", "reasoning": "...", ...}
    """
    observe_outputs = observe_outputs or []

    if plan_count == 1:
        # ── 首次规划：拆解步骤 ──
        return await _initial_plan(query)

    # ── 决策判断：根据 observe_outputs 判断充足性 ──
    return await _decide(query, observe_outputs, plan_count)


async def _initial_plan(query: str, stream_emit=None, node_id: str = None, node_type: str = "Plan") -> dict:
    """首次规划：拆解用户 query 为工具步骤（支持流式）"""
    prompt = f"用户查询: {query}\n\n请拆解为可执行步骤："

    if stream_emit is None:
        # 非流式路径：保持原有行为
        result = generate(prompt, system_prompt=PLANNING_SYSTEM_PROMPT)
    else:
        # 流式路径：边收 chunk 边 emit
        loop = asyncio.get_event_loop()
        messages = [
            {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = await _run_llm_stream(messages, loop, stream_emit, node_id, node_type)

    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(cleaned)
        # 首次规划固定为 need_more（需要执行工具）
        parsed["decision"] = "need_more"
        parsed["plan_count"] = 1
        return parsed
    except Exception:
        return {
            "thought": "无法解析规划结果，使用默认搜索策略",
            "steps": [
                {"tool": "search", "description": "搜索相关信息", "params": {"query": query}}
            ],
            "decision": "need_more",
            "plan_count": 1,
        }


async def _decide(query: str, observe_outputs: list[dict], plan_count: int,
                  stream_emit=None, node_id: str = None, node_type: str = "Plan") -> dict:
    """决策判断：根据 Observe 输出判断信息充足性（支持流式）"""
    parts = [f"用户原始问题：{query}\n"]
    parts.append(f"当前是第 {plan_count} 轮规划（最多 {MAX_PLAN_COUNT} 轮）。\n")
    parts.append("=== 各轮检索评估报告 ===")

    for obs in observe_outputs:
        round_num = obs.get("round", "?")
        parts.append(f"\n--- 第 {round_num} 轮 ---")
        parts.append(f"摘要：{obs.get('summary', '')}")
        findings = obs.get("key_findings", [])
        if findings:
            parts.append(f"要点：")
            for f in findings:
                parts.append(f"  - {f}")
        conflicts = obs.get("conflicts", [])
        if conflicts:
            parts.append(f"矛盾：")
            for c in conflicts:
                parts.append(f"  - {c.get('topic', '')}: {c.get('resolution', '')} (置信度: {c.get('confidence', '?')})")
        new_info = obs.get("new_info_vs_previous", "")
        if new_info:
            parts.append(f"新增信息：{new_info}")

    # 如果是最后一轮且信息不足，提示 LLM 必须终止
    if plan_count >= MAX_PLAN_COUNT:
        parts.append(f"\n⚠️ 这是第 {MAX_PLAN_COUNT} 轮（最后一轮）。如果信息仍然不足，你必须选择 terminate，在 partial_answer_note 中诚实说明哪些方面信息不完整。")

    parts.append("\n请判断信息是否足以回答用户问题，按 JSON 格式输出决策。")

    prompt = "\n".join(parts)

    if stream_emit is None:
        # 非流式路径：保持原有行为
        result = generate(prompt, system_prompt=DECISION_SYSTEM_PROMPT)
    else:
        # 流式路径：边收 chunk 边 emit
        loop = asyncio.get_event_loop()
        messages = [
            {"role": "system", "content": DECISION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        result = await _run_llm_stream(messages, loop, stream_emit, node_id, node_type)

    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(cleaned)
        parsed["plan_count"] = plan_count

        # 最后一轮强制：如果 LLM 仍然返回 need_more，覆盖为 terminate
        if plan_count >= MAX_PLAN_COUNT and parsed.get("decision") == "need_more":
            parsed["decision"] = "terminate"
            parsed["reasoning"] = f"已达最大检索轮次（{MAX_PLAN_COUNT}轮），强制终止"
            parsed["if_terminate"] = {
                "reason": "已达最大检索轮次",
                "partial_answer_note": parsed.get("if_need_more", {}).get("missing_aspects", ["部分信息"])[0] + "方面信息可能不完整",
            }

        return parsed
    except Exception:
        # 解析失败：如果信息看起来够了就 sufficient，否则 terminate
        if plan_count >= MAX_PLAN_COUNT:
            return {
                "decision": "terminate",
                "reasoning": "决策解析失败，已达最大轮次，强制终止",
                "if_terminate": {
                    "reason": "决策解析失败",
                    "partial_answer_note": "回答生成过程中出现异常，部分信息可能不完整",
                },
                "plan_count": plan_count,
            }
        return {
            "decision": "sufficient",
            "reasoning": "决策解析失败，基于已有信息生成回答",
            "plan_count": plan_count,
        }


async def _run_llm_stream(messages: list, loop, stream_emit, node_id: str, node_type: str) -> str:
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
