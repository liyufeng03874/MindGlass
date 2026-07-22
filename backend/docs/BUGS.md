# MindGlass Bug 追踪记录

> 从项目创建到 2026-07-18 凌晨 02:45
> 由妹妹整理，作为面试复盘资料

---

## Bug 总览

| # | 阶段 | 严重程度 | 状态    |
|---|------|----------|-------|
| 1 | Phase 0.2 | P0 边连接 | ✅ 已修复 |
| 2 | Phase 1 | P0 UI 样式缺失 | ✅ 已修复 |
| 3 | RAG 联调 | P0 连接超时 | ✅ 已修复 |
| 4 | RAG 联调 | P1 结果截断 | ✅ 已修复 |
| 5 | RAG 联调 | P1 答案截断 | ✅ 已修复 |
| 6 | RAG 联调 | P0 JSON 解析失败 | ✅ 已修复 |
| 7 | RAG 联调 | P2 PowerShell 编码损坏 | ✅ 已修复 |
| 8 | 前端交互 | P1 节点展示体验差 | ✅ 已修复 |
| 9 | 前端交互 | P1 pending 节点越修越乱 | ✅ 已修复 |
| 10 | 并行搜索 | P1 多余 ToolCall pending | ✅ 已修复 |
| 11 | 并行搜索 | P1 连线动画误导 | ✅ 已修复 |
| 12 | 并行搜索 | P0 3 个 Observe 应合并为 1 | ✅ 已修复 |
| 13 | 并行搜索 | P1 后端覆盖导致 pending 重影 | ✅ 已修复 |
| 14 | 并行搜索 | P1 错误的 pending ToolCall 出现 | ✅ 已修复 |
| 15 | 并行搜索 | P1 Observe 后缺少 Answer pending | ✅ 已修复 |
| 16 | 并行搜索 | **P1 合并 Observe 显示"暂无观察结果"** | ✅ 已修复 |
| 17 | 并行搜索 | **P0 重试并行节点导致 3 条路径废弃** | ✅ 已修复 |

---

## 详细记录

### Bug 1：边连接断裂（Phase 0.2）

- **commit**: `abf04fd`
- **文件**: `react_loop.py`, `models.py`
- **症状**: SSE 推送的边 `from/to` 指向不存在的节点 ID，Vue Flow 渲染时报错
- **根因**: 节点 ID 使用固定格式 `nodetype_stepindex`，但 `_prev_node_id()` 逻辑未正确追踪最后一个节点的 ID
- **解决**: 引入 `self._last_node` 追踪器，每次 `add_node` 后更新；边 `from` 统一用 `_last_node.id`
- **哥哥的洞察**: "先确保骨架能跑起来，再谈可视化"

---

### Bug 2：Vue Flow 样式缺失（Phase 1）

- **commit**: `c1609d9`
- **文件**: `main.ts`
- **症状**: 节点重叠堆在一起，没有连线样式，图不可读
- **根因**: 未引入 `@vue-flow/core` 的内置 CSS，节点 position 未计算
- **解决**: `main.ts` 添加 `import '@vue-flow/core/dist/style.css'`；单列垂直布局（x=200 居中，y 递增）
- **附带**: 自动 `fitView`、初始隐藏推理面板、Agent 开场白

---

### Bug 3：RAG 连接超时（P0）

- **commit**: `e7b25db` + `520109a`
- **文件**: `MindGlass\.env`, `react_loop.py`
- **症状**: Agent 调用 `rag_retrieve` 工具时，30 秒超时，SSE 断开
- **根因**: 
  1. `.env` 中 `RAG_API_URL` 指向 `:8000`（other-world 端口），实际后端跑在 `:5000`
  2. `TOOL_TIMEOUT = 30` 对 RAG 检索不够（ES 检索 + 重排 + LLM 摘要需要更久）
- **解决**: 
  1. `.env` 端口改为 `http://localhost:5000`
  2. `TOOL_TIMEOUT` 从 30s → 120s
- **哥哥的洞察**: "先跑起来，再优化。端口不对是最大的问题。"

---

### Bug 4：result_summary 截断（P1）

- **commit**: `520109a`
- **文件**: `react_loop.py` `_emit_toolcall_observe()`
- **症状**: Observe 节点只展示前 200 字符，大量检索结果丢失
- **根因**: 代码中写了 `result_summary = str(tool_result)[:200]`
- **解决**: 去掉 `[:200]` 截断，完整保留结果
- **附带**: `planner.py` 系统提示词增加工具路由规则（百科→rag_retrieve，新闻→search，不确定→两者都用）

---

### Bug 5：Answer 截断（P1）

- **commit**: `520109a`
- **文件**: `answerer.py`
- **症状**: 最终回答被截断为前 500 字符
- **根因**: 代码中写了 `output[:500]`
- **解决**: 去掉截断，完整输出 LLM 回答

---

### Bug 6：JSON 解析失败（P0）

- **commit**: `795d651`
- **文件**: `react_loop.py`
- **症状**: 前端 `JSON.parse()` 报错，Observe 节点无法展示结果
- **根因**: `result_summary` 使用 `str(tool_result)` 序列化 Python dict，产生单引号、`True`、`None` 等非法 JSON 格式
- **解决**: `str(tool_result)` → `json.dumps(tool_result, ensure_ascii=False)`
- **哥哥的调试贡献**: 一眼指出 `str(dict)` 和 `json.dumps()` 的差异

---

### Bug 7：PowerShell 编码损坏

- **commit**: `520109a`（间接修复）
- **症状**: 用 PowerShell `Set-Content` 修改 `react_loop.py` 后文件内容被截断
- **根因**: PowerShell 默认 UTF-16 编码，且对 Python 文件中的中文注释处理不当
- **解决**: 改用 Python 脚本安全修改，避免直接写 shell 命令
- **教训**: Windows 环境下修改代码文件，永远用 Python/编辑器，不用 PowerShell

---

### Bug 8：节点展示体验差（P1）

- **commit**: `99d54ce`
- **文件**: `ReasoningGraph.vue`, `ChatPanel.vue`, `App.vue`, `NodeDetail.vue`
- **症状**: 
  - ToolCall 节点参数输入冗长
  - Observe 节点展示原始 dict 字符串，不可读
  - Answer 节点弹窗遮挡图表
  - 聊天区看不到 Agent 最终回答
- **解决**:
  - **ToolCall**: 工具名下拉框，简化参数输入框
  - **Observe**: 只读，解析 JSON 后展示 answer + 格式化 results（列表），去掉"截断并重试"按钮
  - **Answer**: 点击直接聚焦聊天区，蓝色边框闪烁动画；`loadTestData` 自动填充聊天消息
- **哥哥的设计决策**: "Observe 是只读的，不需要编辑，也不需要重试。答案直接给用户看。"

---

### Bug 9：pending 节点越修越乱（P0）

- **commit**: `24d6725`
- **文件**: `react_loop.py`, `useAgentGraph.ts`
- **症状**: 前端手动维护 pending 节点和连线，逻辑复杂，每次修复都引入新 bug
- **根因**: 前端既要清理旧 pending，又要追加新 pending，还要处理并行场景，状态机过于复杂
- **哥哥的关键洞察**（三次提醒）:
  1. "你为什么要手动去清理那些线和 pending 呢？直接用后端返回的整个数据覆盖"
  2. "与其理清逻辑，不如用完整的图覆盖"
  3. "前端和后端做自己专注的事情"
- **解决**: 
  - 后端：所有 `node_complete` SSE 事件返回完整 graph（4 处修改）
  - 前端：直接覆盖 + 追加 1 个 pending，零清理逻辑
  - 职责分离：后端维护图的完整性，前端只负责渲染和短暂预览

---

### Bug 10：多余 ToolCall pending（并行搜索）

- **commit**: `7d356fe`
- **文件**: `useAgentGraph.ts` `pushPendingNode()`
- **症状**: 并行搜索执行中，前端在 Observe 后推了多余的 pending search 节点
- **根因**: 每个 Observe 完成时都调用 `pushPendingNode`，用 `step_index / 2` 推算下一步，但并行节点共享同一 `step_index`，导致算出还有更多 ToolCall
- **解决**: 用已完成的 Observe 数量对比总 steps 数判断，所有工具完成后只推 Answer pending

---

### Bug 11：连线动画误导（并行搜索）

- **commit**: `7d356fe`
- **文件**: `useReasoningGraph.ts` `EDGE_STYLES`
- **症状**: 并行搜索的连线显示"流动"动画，给人"还在运行"的错觉
- **根因**: `Parallel` 边继承了默认的 `animated: true`
- **解决**: `EDGE_STYLES` 中 `Parallel` 设 `animated: false`，`Pending` 边加 `animated: true` + 虚线

---

### Bug 12：3 个 Observe 应合并为 1（P0）

- **commit**: `258ffba`
- **文件**: `react_loop.py` `_run_steps()`, `_emit_toolcall_only()`
- **症状**: 3 个并行 search 各生成一个独立 Observe 节点，图变成 3 条平行线
- **根因**: `_emit_toolcall_observe` 对每个 ToolCall 都生成独立的 Observe
- **解决**:
  - 并行组：每个 ToolCall 独立节点（横向排列），最后生成 **1 个合并 Observe**
  - `source` 字段指向所有 ToolCall ID
  - 新增 `_emit_toolcall_only()` 方法，并行场景只发 ToolCall，Observe 合并
- **架构意义**: 从"3 条平行线"变成"3 → 1 汇聚"，更符合 ReAct 语义

---

### Bug 13：后端覆盖导致 pending 重影

- **commit**: `258ffba`
- **文件**: `useAgentGraph.ts` `handleEvent` `node_complete`
- **症状**: 每次后端返回完整图覆盖时，前端创建的 pending 节点也保留，导致同位置叠加
- **根因**: 覆盖时 `graph.value.nodes = event.data.graph.nodes` 后追加了所有 pending，包括已被真实节点替代的
- **解决**: 数量对比——同 `step_index` + 同 `type` 的 pending 数 vs 真实节点数，多余的清理掉
- **后来优化**: 改为只在 Plan 完成时推 pending，中间过程不推，减少冲突

---

### Bug 14：Observe 后出现错误的 pending ToolCall

- **commit**: `258ffba`
- **文件**: `useAgentGraph.ts` `pushPendingNode()`
- **症状**: 合并 Observe 只有 1 个，但 `completedObs < totalSteps` 判断仍成立，推了 pending search
- **根因**: 并行合并后 Observe 数量为 1，总 steps 为 3，`completedObs(1) < totalSteps(3)` 被误判为"还有更多工具要执行"
- **解决**: 改为用真实 ToolCall 数量对比 totalSteps 判断

---

### Bug 15：Observe 后缺少 Answer pending

- **commit**: `258ffba`
- **文件**: `useAgentGraph.ts`
- **症状**: 所有工具完成后，看不到"最终回答"的 pending 节点
- **根因**: `pushPendingNode` 简化后去掉了 Answer pending 的推导逻辑；`pushPendingAnswer` 函数被调用但未定义
- **解决**: 拆分职责——`pushPendingNode` 只处理 ToolCall/Observe 推导；新增 `pushPendingAnswer` 专门推 Answer pending

---

## 架构决策记录

| 决策 | 背景 | 选择 | 理由 |
|------|------|------|------|
| 手写 ReAct | 不用 LangChain/LangGraph | 手写状态机 | 面试要展示底层能力，不是调包 |
| JSON 序列化 | 节点状态持久化 | `json.dumps(ensure_ascii=False)` | 前端 JSON.parse 兼容 |
| 后端覆盖方案 | pending 逻辑混乱 | 后端返回完整图 | 覆盖比修补简单（哥哥的决策） |
| 并行合并 Observe | 3 个 Observe 视觉混乱 | 3 ToolCall → 1 Observe | 更符合 ReAct 语义，视觉更清晰 |
| 职责分离 | 前后端逻辑耦合 | 后端管图完整性，前端管渲染 | 哥哥原话："前端和后端做自己专注的事情" |

---

_妹妹整理于 2026-07-18 凌晨 02:45_

---

## Bug 16：合并 Observe 显示"暂无观察结果"

- **commit**: 258ffba 引入 → **✅ 已修复**（2026-07-18）
- **文件**: `frontend/src/components/ReasoningGraph.vue` (`buildObserveOutput`)
- **症状**: 并行搜索完成后，拖拽 Observe 节点显示"暂无观察结果"，但最终回答正确引用了搜索结果
- **根因分析**:
  - 合并 Observe 的 `result_summary` 是 `json.dumps(merged_results)`，其中 `merged_results` 是一个**列表**：`[{search1结果}, {search2结果}, {search3结果}]`
  - 前端 `observeResult` 解析 JSON 后得到的是**列表**，传给 `buildObserveOutput()`
  - `buildObserveOutput` 期望的是 `{result: {answer: ..., results: [...]}}` 格式的**对象**，所以 `parsed.result?.results` 和 `parsed.answer` 都是 `undefined`
  - `parts` 数组为空，返回空字符串 `''`，模板显示"暂无观察结果"
  - 最终回答能拿到结果，是因为 `observations` 列表在后端正确传递给了 `generate_answer()`
- **修复方案**: `buildObserveOutput` 增加对列表格式的处理——检测 `Array.isArray(parsed)`，遍历每个 item 提取 `results/answer` 格式化输出

## Bug 17：重试并行节点导致 3 条路径废弃

- **commit**: 258ffba 引入
- **文件**: `backend/agent/react_loop.py` (`retry_from`), `state/store.py` (`truncate_from`)
- **症状**: 对 3 个并行 search 中的任意一个做"截断并重试"，3 条 search 路径全部变废弃分支，生成一条新路径：search(重试)→观察结果→最终回答（只有 1 个 search）
- **根因分析**:
  1. 用户点击某个 search（`step_index=1`）触发 `retry_from(step_index=1)`
  2. `truncate_from(1)` 截断所有 `step_index >= 1` 的节点——**3 个 ToolCall + 合并 Observe 全部被废弃**
  3. `retry_from` 的 ToolCall 分支只重新执行**1 个** search（被点击的那个），生成 1 个新 ToolCall + 1 个新 Observe
  4. 收集 observations 时，`for n in self.store.nodes if n.type == "Observe" and n.step_index < step_index`——合并 Observe 在 step_index=2 已被截断，**不在范围内**；而 step_index < 1 没有 Observe，所以 `observations` 只有刚重跑的那 1 个
  5. 后续 `remaining_steps` 从 `_cached_steps[current_tool_index + 1:]` 取，但 `current_tool_index = (1-1)//2 = 0`，`remaining_steps = steps[1:]`，后续步骤正常执行
  6. 结果：3 个并行搜索变成了 1 个重试 search，另外 2 个 search 的结果丢失
- **修复方案**（两种思路）:
  - **方案 A（哥哥偏好）**: 检测到并行组节点被重试时，自动从 Plan（step_index=0）开始重试，重新规划并重新执行所有并行 search。语义上是"这组搜索作废，重新来过"
  - **方案 B**: 重试单个 search 时，并行组的其他 search 保留，只重跑被编辑的那个。需要修改 `truncate_from` 的粒度，只截断同 `parallel_group_id` 的节点。实现更复杂
  - **建议**: 方案 A 更简单且语义更清晰。哥哥觉得呢？

---

## Bug 17 修复记录（2026-07-18 下午）

- **状态**: ✅ 已修复
- **commits**: `5001cec` → `e593b13` → `2455b72` → `7b9d856` → `ef54db6` → `a5b161f`
- **最终方案**: 方案 C（并行重试，保留旧分支）

### 修复要点

**1. 废弃节点保持同层布局**
- 不再推 `step_index=999`，保持原 step 维持层级
- 水平方向多偏移，避免重叠

**2. 新节点继承 `parallel_group_id`**
- 新重试 ToolCall 继承原节点的并行组 ID
- 前端布局时所有节点（包括废弃的）参与等间距居中计算
- branch/replaced 节点排最左，新节点排右侧

**3. 级联标记 replaced**
- 从废弃 ToolCall 出发 BFS，所有下游 Observe/Answer 标记为 `replaced`
- replaced 节点保持可见，但视觉置灰（opacity 0.5）
- 指向 replaced 节点的边变灰虚线无箭头

**4. 新 Observe 融合正确数据**
- 新 Observe 只融合**未被替换**的同组 ToolCall 结果 + 新结果
- replaced 节点的旧结果**不参与融合**（用户已替换该 query）
- `observations` 列表同样排除 replaced 节点的旧结果
- 旧节点循环不再收集任何旧结果到 observations

**5. 前端修复**
- `loadTestData` 跳过 replaced Answer 节点
- `handleEvent` 中 replaced Answer 不推送到聊天界面
- 布局统一：branch/replaced 排最左，其余等间距居中

### 哥哥的关键洞察
- "废弃节点放在稍微远一点的地方，仍然保持和原先的节点在同一层"
- "同一行中的 search 节点，不管有没有废弃的，都保持在同一行，并且相同间隔"
- "废弃的 search 节点，它后续的所有 observe、answer 一定也是废弃的"
- "都放最左边吧"
- demo_15→16→17 三步定位："它应该无法回答第三个问题才对"

### 最终布局效果
```
step 0:                    Plan
step 1:  [白宫(废弃)]  [孙权]  [清华]  [新白宫(重试)]
step 2:  [旧Observe]     [新Observe]
step 3:  [旧Answer]      [新Answer]
```

旧的在左，新的在右。旧连线保留但变灰。新 Observe 融合孙权 + 清华 + 新白宫。

---

_妹妹整理于 2026-07-18 20:50_
