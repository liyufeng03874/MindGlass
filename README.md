# 🧠 MindGlass — 可观测多步推理 Agent

> 让 AI 的思考过程像玻璃一样透明可见。

## 项目简介

MindGlass 是一个基于 ReAct 范式（Reason + Act）的多步推理 Agent 前端项目。用户提出问题后，Agent 会自动将问题拆解为多个步骤，调用搜索/RAG 等工具收集信息，最终生成回答——**整个过程以思维图的形式实时可视化呈现**。

### 核心亮点

- **思维透明**：推理过程不再是黑盒，每一步（规划→执行→观察→回答）都实时可视化
- **可干预**：点击任意节点可编辑参数、更换工具、重试，支持分支保留与对比
- **并行推理**：支持多工具并行执行（如同时搜索+RAG检索），显著提升响应速度
- **前端主导**：Vue 3 + TypeScript + @vue-flow，完整的图可视化与交互体验

## 技术栈

### 前端
| 技术 | 用途 |
|------|------|
| Vue 3 + TypeScript | UI 框架 |
| @vue-flow/core | 思维图渲染引擎 |
| markdown-it | Agent 回答 Markdown 渲染 |
| SSE (EventSource) | 实时流式接收推理事件 |

### 后端
| 技术 | 用途 |
|------|------|
| FastAPI | API 框架 |
| OpenAI 兼容 API (qwen3.6-plus) | LLM 规划/回答生成 |
| Tavily Search API | 网络搜索工具 |
| other-world RAG | 本地知识库检索（复用） |

## 架构设计

### ReAct 循环

```
User Query
    ↓
  [Plan] ── LLM 拆解为步骤列表
    ↓
[ToolCall] ── 执行 search / rag_retrieve
    ↓
 [Observe] ── 收集工具返回结果
    ↓
 [Answer] ── LLM 基于所有观察结果生成回答
    ↓
User Response
```

### 数据流

```
后端 ReActLoop ──SSE──→ 前端 useAgentGraph ──→ 状态管理
                                                   ↓
                                          ReasoningGraph.vue（@vue-flow 渲染）
                                                   ↓
                                          ChatPanel.vue（对话 + 最终回答）
```

### 节点类型

| 节点 | 颜色 | 说明 |
|------|------|------|
| 🧠 Plan | 蓝 | LLM 规划步骤，输出 JSON 格式的步骤列表 |
| 🔧 ToolCall | 绿 | 工具执行节点（search / rag_retrieve） |
| 📡 Observe | 橙 | 观察结果收集（可合并多个 ToolCall 结果） |
| 💬 Answer | 紫 | 最终回答生成 |

### 分支与重试

- 编辑并重试任意节点时，原路径标记为 `branch`（灰色保留），新路径正常显示
- 支持并行节点重试：方案 C 支持只重跑被截断的工具，融合结果后直接送 Answer，无需重新规划

## 快速开始

### 环境准备

```bash
# 后端
cd backend
pip install -r requirements.txt

# 配置 .env（参考 .env.example）
cp .env.example .env
# 编辑 .env 填入 API_KEY, OPENAI_BASE_URL, TAVILY_API_KEY 等

# 前端
cd frontend
npm install
```

### 启动

```bash
# 终端 1：后端
cd backend
python server.py
# 访问 http://localhost:8002/api/health 确认

# 终端 2：前端
cd frontend
npm run dev
# 访问 http://localhost:5173
```

### 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `API_KEY` | LLM API Key | `sk-xxxxx` |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址 | `https://api.xxx.com/v1` |
| `MODEL` | 模型名称 | `qwen3.6-plus` |
| `TAVILY_API_KEY` | Tavily 搜索 API Key | `tvly-xxxxx` |
| `RAG_API_URL` | RAG 服务地址 | `http://localhost:8001` |
| `MINDGLASS_PORT` | 后端端口 | `8002` |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/tools` | 列出可用工具 |
| GET | `/api/graph` | 获取当前推理图状态 |
| GET | `/api/run?query=xxx` | SSE 流式推理 |
| POST | `/api/retry` | 从指定 step 重试（SSE） |
| POST | `/api/load-demo` | 加载测试数据（开发用） |

## Demo Query

| 类型 | Query | 展示能力 |
|------|-------|----------|
| 百科类 | 孙权封王称帝后立谁为太子？ | RAG 检索 + 回答生成 |
| 医疗类 | 激光治眼睛会复发吗？ | 多步推理 + RAG 召回 |
| 综合类 | 帮我查三篇论文的共同点 | 完整 Plan → ToolCall → Observe → Answer |
| 游戏类 | 星辰变大后期哪个职业最强？ | 本地知识库检索 |
| 搜索类 | 2025年华为前端开发最新技术趋势 | Tavily 网络搜索 |

## 项目结构

```
MindGlass/
├── backend/
│   ├── server.py              # FastAPI 入口
│   ├── agent/
│   │   ├── react_loop.py      # ReAct 循环主类
│   │   ├── planner.py         # LLM 任务规划
│   │   ├── answerer.py        # LLM 回答生成
│   │   ├── tools.py           # 工具注册与执行
│   │   └── llm.py             # LLM 调用封装
│   ├── state/
│   │   ├── models.py          # 数据模型（Node/Edge/Branch）
│   │   └── store.py           # 图状态管理
│   └── docs/
│       ├── BUGS.md            # Bug 记录与架构决策
│       └── BUG-17-DISCUSS.md  # 并行重试方案 C 讨论
├── frontend/
│   ├── src/
│   │   ├── App.vue            # 主应用（左右分栏布局）
│   │   ├── components/
│   │   │   ├── ChatPanel.vue      # 对话面板
│   │   │   ├── ReasoningGraph.vue # 思维图 + 节点编辑
│   │   │   └── NodeDetail.vue     # 节点详情面板
│   │   ├── composables/
│   │   │   ├── useAgentGraph.ts   # SSE + 状态管理 + 重试
│   │   │   └── useReasoningGraph.ts # 图渲染逻辑
│   │   └── types/
│   │       └── agent.ts       # TypeScript 类型定义
│   └── ...
└── README.md
```

## 架构决策记录

详见 `backend/docs/BUGS.md` 中的「架构决策记录」表，记录了以下关键决策：

| 编号 | 决策 | 原因 |
|------|------|------|
| AD-002 | 搜索 → Observe 输出使用 answer+results 组合 | 用户可理解性 |
| AD-003 | 合并 Observe 前端展示格式化（遍历列表） | 可读性与信息完整性 |
| AD-005 | 重试用完整图覆盖而非理清逻辑 | 与其理清复杂逻辑不如用干净数据覆盖 |

## 当前状态

- ✅ Phase 0：项目骨架
- ✅ Phase 1：第一个可用推理流程
- ✅ Phase 2：节点交互与干预（基础完成，Bug 17 待修）
- ✅ Phase 3：工具扩展与打磨（基础完成，Bug 16 待修）
- ⏳ Phase 4：面试级打磨（进行中）

## License

个人项目，用于面试展示与技术能力验证。
