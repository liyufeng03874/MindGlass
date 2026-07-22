# MindGlass 新版 Observe / Plan 架构设计

> 定稿日期：2026-07-22
> 状态：设计完成，待实施
> 配套架构图：`mindglass-architecture.html`（workspace）

---

## 1. 问题

当前 Observe 节点只是 `json.dumps(merged_results)`，将 ToolCall 的返回结果原样搬运，没有做任何评估。

**架构层面的硬伤：**
- ToolCall → Observe → Answer 实质是直连的，Plan-and-Execute 的"观察-反思-再决策"环节缺失
- 多源搜索结果未经验证直接交给 Answer，可能包含矛盾、重复、无关信息
- 没有"信息够不够"的判断，不管搜到什么都是一把梭到 Answer
- **面试时，设计过 Agent 的面试官一眼就能看出：这不是真正的 Plan-and-Execute，是个带壳的 chain**

**当前代码对应：**
- `react_loop.py`：`obs_node.data = {"result_summary": json.dumps(merged_results)}`（纯搬运）
- `planner.py`：只输出 `steps[]`，不做充足性判断
- `answerer.py`：接收原始 `observations[]`（raw results），无结构化输入

---

## 2. 新架构核心变更

### 2.1 节点职责重新定义

| 节点 | 旧职责 | 新职责 |
|------|--------|--------|
| **Plan** | 仅规划工具步骤 | **决策中枢**：判断信息充足性，决定下一步是 Tool / Answer / 终止 |
| **ToolCall** | 执行搜索 | 不变 |
| **Observe** | 原样搬运结果 | **评估**：总结 / 去重 / 矛盾检测 / 结构化输出，汇报给 Plan |
| **Answer** | 最终回答 | 不变（但输入变为 Observe 的结构化输出） |

### 2.2 节点流转

```
Query → Plan(1) → ToolCall(并行) → Observe → Plan(2) → ...
                                                    ↓
                                          sufficient → Answer
                                          need_more  → ToolCall(补搜) → Observe → Plan(3)
                                          terminate  → Answer(降级)     [count=3 强制]
```

### 2.3 决策权归属（铁律）

- **Observe 只评估，不决策**：产出结构化评估报告，告诉 Plan"信息够不够、缺什么、有没有矛盾"
- **Plan 只决策，不评估**：根据 Observe 的报告 + 原始 query，决定下一步节点
- Observe 之后**一定是 Plan**，Plan 之后**不确定**（可能是 Tool / Answer / Answer+降级）

### 2.4 终止条件

1. **自然终止**：Plan 判断信息充足 → Answer（任意轮次可触发，通常 Plan(2) 或 Plan(3)）
2. **强制终止**：plan_count = 3 且信息仍不足 → Answer + 降级标记
   - 降级话术（由 prompt 约束，不是硬编码）：
   > "经过 3 轮检索，我在 XX 方面仍未找到充分信息。以下是基于已有信息的回答，其中 YY 部分可能不够准确，建议进一步查证。"
   - **不是"我废物"，是"我尽力了，但我诚实告诉你哪里不确定"**

### 2.5 数据流

- **Plan 看到**：原始 query + observe_outputs[]（所有轮次的结构化输出数组）+ plan_count
- **Observe 输出**：每轮一个结构化对象，追加到 observe_outputs[]
- **Observe 看到**：本轮 raw results + 上一轮的 observe_outputs（用于增量对比、去重）
- **Answer 输入**：所有 Observe 的 key_findings + conflicts + Plan 的最终决策（不是原始搜索结果）

---

## 3. 结构化输出 Schema

### 3.1 Observe 输出（每轮一个对象，追加到 observe_outputs 数组）

```json
{
  "round": 1,
  "summary": "本轮检索的核心信息提炼（2-3句话）",
  "key_findings": ["要点1", "要点2", "要点3"],
  "conflicts": [
    {
      "topic": "矛盾点描述",
      "sources": ["来源A说...", "来源B说..."],
      "resolution": "按发布时间/权威性选取了A，因为...",
      "confidence": "high | medium | low"
    }
  ],
  "duplicates_removed": 2,
  "new_info_vs_previous": "相比上轮新增了什么（首轮写'首轮检索'）"
}
```

### 3.2 Plan 输出

```json
{
  "decision": "sufficient | need_more | terminate",
  "reasoning": "为什么做这个判断（1-2句）",
  "if_need_more": {
    "missing_aspects": ["还缺什么方面"],
    "suggested_queries": ["补搜query1", "补搜query2"]
  },
  "if_terminate": {
    "reason": "已达最大轮次，信息仍不完整",
    "partial_answer_note": "以下回答基于有限信息，XX方面可能不完整"
  },
  "plan_count": 2
}
```

### 3.3 Answer 输入（变更）

旧：`observations[]`（raw tool results 列表）
新：`observe_outputs[]`（结构化评估报告数组）+ Plan 的最终决策 + 降级标记（如有）

---

## 4. 矛盾处理策略

完全放权给 LLM，通过 Observe prompt 约束：

1. 如果多个结果存在矛盾：综合按**发布时间**和**发布机构**选取权威度更高的，**禁止自行中和矛盾**
2. 如果实在无法调和：整理矛盾后说明存在的矛盾，继续往后输出
3. 也可以让 LLM 基于内容本身判断可信度
4. **不管经过多少个 ToolCall，经过 Observe 之后一定是结构化输出**
5. 矛盾检测的判断理由要暴露出来（MindGlass"可观测"的卖点——让用户看到 Agent 为什么信 A 不信 B）

---

## 5. 前端预测逻辑

| 当前节点 | 预测下一节点 | 说明 |
|----------|-------------|------|
| ToolCall | Observe | 固定，不变 |
| Observe | Plan | 固定，不变 |
| Plan | **待决策** | 可能是 ToolCall / Answer / Answer+降级 |

- "待决策"节点在 Plan 的 SSE 事件到达后 resolve 为实际节点
- **terminate 出来的 Answer 有视觉区分**：橙色边框 + "信息可能不完整"标签
- 前端在 Plan 节点完成后读取 `data.decision` 字段来确定下一步

---

## 6. 需要修改的文件

### 后端

| 文件 | 改动 |
|------|------|
| `agent/react_loop.py` | **核心改动**：执行循环从 `Plan → [Tool→Observe]* → Answer` 改为 `Plan → [Tool→Observe→Plan]* → Answer`，支持决策回环 |
| `agent/planner.py` | 增加充足性判断逻辑，接收 `observe_outputs[]` + `plan_count`，输出 decision + steps |
| `agent/observer.py` | **新增**：结构化评估逻辑，调用 LLM 做总结/去重/矛盾检测，输出结构化 JSON |
| `agent/answerer.py` | 输入从 raw observations 改为结构化 observe_outputs + Plan 决策 |
| `state/models.py` | `ReasoningMeta` 增加 `plan_count` 字段；Observe 节点 data 结构变更 |
| `server.py` | SSE 事件适配（Plan 节点 data 增加 decision 字段，前端据此 resolve 待决策节点） |

### 前端

| 文件 | 改动 |
|------|------|
| `composables/useAgentGraph.ts` | 支持 Plan 后的"待决策"pending 节点；读取 Plan.decision 来 resolve |
| `composables/useAgentChat.ts` | Observe 结构化输出的展示（不再是 raw JSON） |
| `components/ChatPanel.vue` | 展示 Observe 的 key_findings / conflicts；降级 Answer 的视觉区分 |
| 图渲染组件 | "待决策"节点的渲染 + 降级 Answer 的橙色边框 |

### Prompt

| Prompt | 改动 |
|--------|------|
| PLANNING_SYSTEM_PROMPT | 从"拆解步骤"改为"判断信息充足性 + 决定下一步 + 如需补搜则给出 queries" |
| OBSERVE_SYSTEM_PROMPT | **新增**：结构化评估 prompt（总结/去重/矛盾检测/增量对比） |
| ANSWER_SYSTEM_PROMPT | 输入格式从 raw results 改为结构化 observe_outputs |

---

## 7. 执行循环伪代码

```python
async def run(query):
    plan_count = 0
    observe_outputs = []

    # ── 初始规划（Plan 1，必定输出工具步骤）──
    plan_count += 1
    plan_result = await plan(query, observe_outputs=[], plan_count=1)
    emit_node(plan_node)  # Plan(1)

    # ── 决策回环 ──
    while plan_result["decision"] == "need_more" and plan_count < 3:
        # 执行工具
        steps = plan_result["if_need_more"]["suggested_queries"]
        raw_results = await execute_tools_parallel(steps)
        emit_nodes(toolcall_nodes)  # ToolCall(并行)

        # Observe：结构化评估
        obs_output = await observe(query, raw_results, observe_outputs)
        observe_outputs.append(obs_output)
        emit_node(observe_node)  # Observe

        # 重新规划
        plan_count += 1
        plan_result = await plan(query, observe_outputs, plan_count)
        emit_node(plan_node)  # Plan(2) 或 Plan(3)

    # ── 终止 ──
    if plan_result["decision"] == "terminate" or plan_count >= 3:
        # 强制终止 + 降级
        answer = await generate_answer(query, observe_outputs, degraded=True,
                                       note=plan_result.get("if_terminate", {}))
        emit_node(answer_node_degraded)  # Answer(降级，橙色边框)
    else:
        # 自然终止
        answer = await generate_answer(query, observe_outputs)
        emit_node(answer_node)  # Answer(正常)

    emit_run_complete()
```

---

## 8. 不变的部分

- ToolCall 的并行搜索逻辑不变（`asyncio.gather`）
- SSE 通信机制不变（只增加 data 字段）
- 截断重放（`retry_from` / `retry_from_graph`）的核心逻辑不变，但需适配新的 Observe data 结构
- demo 数据格式兼容（graph.nodes 结构不变，只是 Observe 节点 data 更丰富）
- `NodeType` 枚举不变（Plan / ToolCall / Observe / Answer 四种）
- `NodeStatus` 枚举不变（done / current / pending / error / discarded / branch）

---

## 9. 面试话术要点

> "MindGlass 的 Agent 采用改进的 Plan-and-Execute 架构。核心创新在于 Observe 节点不是简单的结果搬运，而是一个**结构化评估节点**——它会对多源搜索结果做总结、去重、矛盾检测，输出结构化报告给 Plan 节点。Plan 节点作为决策中枢，根据 Observe 的报告判断信息是否充足，决定是补搜还是进入回答。这形成了一个真正的 Reason-Act-Observe 决策回环，最多 3 轮，超限后优雅降级并诚实告知用户信息不完整。"

**面试官可能追问的点：**
- Q: 为什么最多 3 轮？→ A: 平衡延迟和信息完整性，超过 3 轮边际收益递减
- Q: 矛盾怎么检测？→ A: 放权给 LLM，prompt 约束按发布时间/机构权威性选取，禁止中和矛盾
- Q: Observe 和 Plan 的边界？→ A: Observe 只评估不决策，Plan 只决策不评估，职责单一
- Q: 降级怎么处理？→ A: 不是报错，是诚实告知"XX 方面信息不足"，比硬编一个答案负责
- Q: 为什么不用 ReAct？→ A: Plan-and-Execute + 人工干预 = 最佳组合。ReAct 每步都思考延迟高，纯 Plan-and-Execute 规划后不可修改。我们的方案在 Plan 层做决策，保留了人工干预入口
