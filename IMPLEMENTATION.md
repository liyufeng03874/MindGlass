# MindGlass 实现步骤清单

> 项目名称：MindGlass（可观测多步推理 Agent）
> 技术栈：FastAPI + Vue 3 + TS + @vue-flow + SSE
> 路径：`d:/code/MindGlass`

---

## Phase 0：项目骨架搭建（1-2 天）

### 0.1 后端骨架
- [ ] 创建 `backend/server.py` — FastAPI 入口 + CORS + 静态路由
- [ ] 创建 `backend/agent/react_loop.py` — ReAct 循环主类
  - 核心方法：`run(query)` → 循环执行 Plan → ToolCall → Observe → Answer
  - 支持 SSE 事件推送
- [ ] 创建 `backend/agent/tools.py` — 工具注册系统
  - 装饰器 `@register_tool`
  - 内置工具：`search`（真实搜索 API）
  - 工具调用返回统一格式
- [ ] 创建 `backend/agent/planner.py` — 任务规划（LLM 调用）
- [ ] 创建 `backend/agent/answerer.py` — 最终回答生成（LLM 调用）
- [ ] 创建 `backend/state/store.py` — 状态存储
- [ ] 创建 `backend/state/models.py` — Node/Link/Branch 数据模型
- [ ] 创建 `backend/requirements.txt`

### 0.2 前端骨架
- [ ] 创建 Vue 3 + TS 项目（`npm create vite@latest frontend -- --template vue-ts`）
- [ ] 安装依赖：`@vue-flow/core`, `@vue-flow/styling`
- [ ] 创建 `frontend/src/components/ChatPanel.vue` — 基础对话界面
- [ ] 创建 `frontend/src/components/ReasoningGraph.vue` — @vue-flow 空图组件
- [ ] 创建 `frontend/src/components/NodePanel.vue` — 节点详情面板
- [ ] 创建 `frontend/src/types/agent.ts` — Node/Link/Branch TS 类型定义
- [ ] 创建 `frontend/src/composables/useAgentChat.ts` — SSE 连接骨架
- [ ] 创建 `frontend/src/composables/useReasoningGraph.ts` — 图渲染 composable
- [ ] 创建 `frontend/src/composables/useStepControl.ts` — 步骤控制 composable

### 0.3 联调打通
- [ ] 后端启动，`/api/health` 可访问
- [ ] 前端启动，页面能加载
- [ ] 前后端 CORS 配置正确

---

## Phase 1：第一个可用推理流程（2-3 天）

### 1.1 后端 ReAct 循环
- [ ] 实现 `Planner`：接收 query，调用 LLM 返回拆解步骤列表
- [ ] 实现 `ToolCall` 执行：根据 Planner 输出选择工具并执行
- [ ] 实现 `Observe`：收集工具返回结果
- [ ] 实现 `Answerer`：基于所有观察结果，调用 LLM 生成最终回答
- [ ] ReAct 循环跑通一个完整流程：Plan → ToolCall → Observe → Answer
- [ ] 每个步骤生成 Node 对象，状态按序更新

### 1.2 状态序列化
- [ ] 实现 `ReasoningGraphStore`：管理 nodes + links + meta
- [ ] 每个步骤完成后，序列化当前状态为 JSON
- [ ] 提供 `/api/runs` 接口获取当前运行状态

### 1.3 SSE 实时推送
- [ ] 后端实现 `/api/sse/run` SSE 端点
- [ ] 每个步骤完成时推送事件：`{"type": "node_complete", "node": {...}}`
- [ ] 循环结束时推送：`{"type": "run_complete", "graph": {...}}`

### 1.4 前端实时渲染
- [ ] `useAgentChat.ts`：连接 SSE，接收事件
- [ ] `useReasoningGraph.ts`：收到节点事件后添加到 @vue-flow
- [ ] `ChatPanel.vue`：显示用户输入和 Agent 最终回答
- [ ] `ReasoningGraph.vue`：实时渲染新增的节点和连线

### 1.5 验收
- [ ] 输入 "帮我查三篇论文的共同点"
- [ ] 前端看到节点逐个出现：Plan → ToolCall → Observe → Answer
- [ ] 连线自动生成，颜色正确
- [ ] 最终回答显示在对话面板

---

## Phase 2：节点交互与干预（3-4 天）

### 2.1 节点点击详情
- [ ] 点击节点打开 `NodePanel.vue`
- [ ] 显示节点类型、状态、输入、输出、参数
- [ ] 不同节点类型显示不同内容

### 2.2 Plan 节点编辑
- [ ] Plan 节点可编辑拆解思路
- [ ] 编辑弹窗：展示当前规划步骤，可增删改
- [ ] 确认后触发重试逻辑

### 2.3 ToolCall 节点编辑
- [ ] 工具参数编辑界面（动态表单，根据工具类型生成）
- [ ] 支持更换工具（下拉选择）
- [ ] 参数编辑弹窗：当前参数 + 原输出（折叠）

### 2.4 重试/回滚/删除
- [ ] 实现 `截断 + 重放` 逻辑
- [ ] 节点操作按钮：[重试] [编辑并重试] [删除]
- [ ] 后端处理：`nodes.slice(0, N+1)`，后续标记 discarded
- [ ] 前端更新：旧节点灰色显示，新节点追加

### 2.5 分支保留
- [ ] discarded 节点保留在数据中，状态标记
- [ ] 前端用不同视觉样式区分（灰色/半透明）
- [ ] 分支连线用不同颜色

### 2.6 验收
- [ ] 点击 ToolCall 节点 → 编辑参数 → 重试
- [ ] 看到新分支生成，旧路径保留
- [ ] 前端视觉清晰区分原路径和新路径

---

## Phase 3：工具扩展与打磨（2-3 天）

### 3.1 更多工具
- [ ] RAG 检索工具（复用 other-world 后端）
- [ ] 代码执行工具（可选）
- [ ] 工具注册系统支持热插拔

### 3.2 可视化打磨
- [ ] 节点样式优化（不同类型不同配色）
- [ ] 流光/粒子装饰效果
- [ ] 动画过渡（节点出现、连线绘制）

### 3.3 错误处理
- [ ] 工具调用失败 → 错误节点
- [ ] LLM 超时 → 错误状态
- [ ] 前端错误提示

### 3.4 验收
- [ ] 多工具场景跑通
- [ ] 视觉效果好，面试官能眼前一亮
- [ ] 异常情况有合理展示

---

## Phase 4：面试级打磨（2-3 天）

### 4.1 分支对比视图
- [ ] 展示同一节点不同参数下的后续差异
- [ ] 左右对比展示

### 4.2 Reflect 节点（可选）
- [ ] 添加自我评估节点
- [ ] 展示 Agent 对自身输出质量的判断

### 4.3 完整 Demo 场景
- [ ] 准备 2-3 个典型 demo query
- [ ] 每个 demo 都有完整的推理路径展示
- [ ] 确保面试时能流畅演示

### 4.4 项目文档
- [ ] README.md（项目介绍、技术栈、运行方式）
- [ ] 架构图
- [ ] 面试话术文档

---

## 总计预估

| Phase | 内容 | 工作日 |
|-------|------|--------|
| Phase 0 | 项目骨架 | 1-2 |
| Phase 1 | 第一个可用流程 | 2-3 |
| Phase 2 | 节点交互与干预 | 3-4 |
| Phase 3 | 工具扩展与打磨 | 2-3 |
| Phase 4 | 面试级打磨 | 2-3 |
| **合计** | | **10-15 天** |

---

## 待确认事项

- [x] **工具清单**：search（真实搜索 API）+ RAG 检索（复用 other-world）
- [x] **RAG 后端**：复用 other-world 的召回/检索/重排能力，核心业务（规划、执行）独立
- [x] **LLM 配置**：与 other-world 相同的 base_url + api_key，模型待确认
- [x] **前端样式**：浅色主题（思维过程可视化，不再适合深色）
- [x] **项目名**：MindGlass
- [x] **项目结构**：独立新项目，与 Stelladream 无关

## Demo Query 建议（从测评集中选取）

1. **百科类**："孙权封王称帝后立谁为太子？" → 展示 RAG 检索 + 回答生成
2. **医疗类**："激光治眼睛会复发吗" → 展示多步推理（搜索补充 + RAG 召回）
3. **综合类**："帮我查三篇论文的共同点" → 展示完整 Plan → ToolCall 链路
