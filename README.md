# 🧠 MindGlass — 可观测多步推理 Agent

> 让 AI 的思考过程像玻璃一样透明可见。

## 项目简介

MindGlass 是一个基于 ReAct 范式（Reason + Act）的多步推理 Agent 前端项目。用户提出问题后，Agent 会自动将问题拆解为多个步骤，调用搜索/RAG 等工具收集信息，最终生成回答——**整个过程以思维图的形式实时可视化呈现**。

### 核心亮点

- **思维透明**：推理过程不再是黑盒，每一步（规划→执行→观察→回答）都实时可视化
- **可干预**：点击任意节点可编辑参数、更换工具、重试，支持分支保留与对比；运行中可任意节点打断
- **并行推理**：支持多工具并行执行（如同时搜索+RAG检索），显著提升响应速度
- **多轮对话**：支持历史对话上下文，多轮连续提问；会话自动关联（conversation_id）
- **Redis 热缓存**：思维图增量缓存（RPUSH）+ 断联恢复（后端重启后前端自动重建图）+ 高频 query 语义复用（embedding 相似检索）
- **双端适配**：PC 左右分栏 / 移动端上下分栏 + 底部 tab（Tailwind CSS 响应式）
- **安全防线**：BERT 内容安全模型四层拦截（prompt 层 + Plan 校验 + Answer 流式校验 + 前端拦截）
- **chatBI 数据分析**：自然语言 → SQL 生成 → 只读执行 → ECharts 图表（gen_sql / exec_sql / plot 三工具，多数据库支持，串行链路自动传参）
- **前端主导**：Vue 3 + TypeScript + @vue-flow，完整的图可视化与交互体验

## 技术栈

### 前端
| 技术 | 用途 |
|------|------|
| Vue 3 + TypeScript | UI 框架 |
| @vue-flow/core | 思维图渲染引擎 |
| Tailwind CSS | 双端响应式适配（移动端上下分栏 + 底部 tab） |
| markdown-it | Agent 回答 Markdown 渲染（含 ```echarts 代码块自定义渲染） |
| ECharts | 图表渲染（深色主题，服务端生成 option） |
| fetch + ReadableStream | SSE 流式接收（POST 请求体携带 history，避开 URL 长度限制） |

### 后端
| 技术 | 用途 |
|------|------|
| FastAPI | API 框架 |
| Redis 5.x (redis-py, RESP2) | 思维图热缓存 / 断联恢复 / query 复用索引 |
| OpenAI 兼容 API (deepseek-v4-flash) | LLM 规划/回答生成（2026-08 从 qwen3.6-plus 切换，TTFT 快 2-4 倍） |
| Tavily Search API | 网络搜索工具 |
| other-world RAG | 法律知识检索（仅法律案情类问题触发，docker 服务名互访） |
| MySQL (pymysql, readonly) | chatBI 数据分析（employees + northwind 两库） |
| BERT 安全模型 (ONNX Runtime) | 内容安全四层拦截 |

## 架构设计

### 决策回环（v2）

```
User Query（+ 历史对话）
    ↓
  [Plan] ── 决策中枢：sufficient（直答）/ need_more（补搜）/ terminate（降级）
    ↓ need_more
[ToolCall] ── 并行执行 search / rag_retrieve（rag 仅限法律案情类）
    ↓
 [Observe] ── 只做观察：整合/去重/摘要/矛盾检测/增量对比，不参与决策
    ↓
  [Plan] ── 回到决策，直到 sufficient 或 5 轮硬上限
    ↓
 [Answer] ── 流式生成最终回答（每 100 字过一次 BERT 安全校验）
    ↓
User Response
```

> 人工在环：运行中可在任意节点打断（截断点后置灰保留，可重试）；编辑节点参数重新执行；废弃分支置灰不删除（"边只标记不删除"）。

### chatBI 数据分析链路（2026-08-16）

> 让思镜不只是搜文档，还能查库、算数、画图——面向数据库的结构化数据分析能力。

```
用户问题（各部门平均薪资排名）
    ↓
[Plan] ── 关键词触发：统计/趋势/排名/占比 + 业务指标 → gen_sql + exec_sql + plot
    ↓（串行执行 _SERIAL_TOOL_GROUPS）
[gen_sql] ── 自然语言 → SQL（LLM 生成 + 安全校验，拒绝非 SELECT）
    ↓ 自动传 SQL
[exec_sql] ── 只读执行（readonly 账号 + Redis 结果缓存 TTL 30min）
    ↓ 自动传数据
[plot] ── 查询结果 → ECharts option（服务端生成深色主题）
    ↓
[Answer] ── 回答 + ```echarts 代码块渲染图表
```

- **多数据库**：`CHATBI_DATABASES` 环境变量（comma 分隔）；已接入 **employees**（员工/薪资/职称/部门，30 万+ 员工）+ **northwind**（订单/产品/客户，电商）；跨库 JOIN 用 `database=None`
- **串行执行**：gen_sql → exec_sql → plot 必须按序，react_loop `_SERIAL_TOOL_GROUPS` 控制，数据链自动传递（exec_sql 自动收 SQL，plot 自动收数据）
- **缓存**：schema 缓存 `mg:schema:{db}`（TTL 1h）、SQL 结果缓存 `mg:sql_result:{hash}`（TTL 30min），Redis 不可用静默降级
- **安全**：exec_sql 只读（SELECT 白名单校验）、readonly 数据库账号、观察层只看结果不评 SQL 语句
- **前端差异化**：gen_sql 可编辑 SQL 文本框 / exec_sql 只读 SQL + 结果表格（前 20 行）/ plot ECharts 预览 / 左侧聊天流内联渲染图表
- **序列化兜底**：pymysql 返回 Decimal（如 AVG()），SSE 发送统一 `_json_default`（Decimal→float）防连接崩断

### Redis 热缓存层（2026-08-10）

**设计定稿（哥哥 08-10 凌晨推演）**：同一套 Redis 存 graph 本身（node+edge+branch），不搞事件流转换；位置不存，前端固定算法重排。

```
正常推进（高频快路径）  add_node/add_edge/create_branch → RPUSH 增量追加
编辑/重放（低频慢路径）  后端算完整新图 → DEL+RPUSH 整体覆盖
run 收尾               后台线程登记 query 向量 → mg:query:index（复用候选）
断联恢复               GET /api/graph 内存空 → 从 Redis 重建 → 前端渲染
语义复用               发消息前 POST /api/reuse/check → 命中旧图直接渲染不重跑
```

| Redis Key | 类型 | 内容 |
|-----------|------|------|
| `mg:graph:{run_id}:items` | LIST | 图组件 JSON（node/edge/branch 增量） |
| `mg:graph:{run_id}:meta` | STRING | meta JSON |
| `mg:graph:current` | STRING | 最近 run_id（恢复入口） |
| `mg:query:index` | HASH | field=run_id，value={query, 1024维向量} |

- TTL 24h（热缓存）；SQLite 仍是冷存储/权威层（run 结束落盘）
- **降级原则**：Redis/embedding 服务挂了绝不影响主流程，全部静默降级
- 语义复用阈值默认 0.92（`MINDGLASS_REUSE_THRESHOLD`，待真实 query 校准）
- 实现细节/验收记录：`memory/projects/mindglass/Redis缓存开发记录-20260810.md`

### 数据流

```
后端 ReactLoop ──SSE──→ 前端 useAgentGraph ──→ rounds 数组（每轮 = query + blocks + answer）
                                                   ↓
                              ReasoningGraph.vue（右侧思维图）+ ChatPanel.vue（左侧按轮渲染）
```

### 节点类型

| 节点 | 颜色 | 说明 |
|------|------|------|
| 🧠 Plan | 蓝 | LLM 规划步骤，输出 JSON 格式的步骤列表 |
| 🔧 ToolCall | 绿 | 工具执行节点（search / rag_retrieve / gen_sql / exec_sql / plot） |
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
uvicorn server:app --host 0.0.0.0 --port 8001
# 访问 http://localhost:8001/api/health 确认

# 终端 2：前端
cd frontend
npm run dev
# 访问 http://localhost:5173（vite 代理 /api → localhost:8001）
```

### 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `API_KEY` | LLM API Key | `sk-xxxxx` |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址 | `https://api.xxx.com/v1` |
| `MODEL` | 模型名称 | `deepseek-v4-flash` |
| `TAVILY_API_KEY` | Tavily 搜索 API Key | `tvly-xxxxx` |
| `RAG_API_URL` | RAG 服务地址 | `http://localhost:5000`（本地）/ `http://otherworld-backend:8000`（Docker） |
| `CHATBI_DB_HOST/PORT/USER/PASS/NAME` | chatBI MySQL 连接（readonly 账号） | `127.0.0.1` / `3306` / `readonly` / `...` / `employees` |
| `CHATBI_DATABASES` | chatBI 可用数据库列表（逗号分隔） | `employees,northwind` |
| `BERT_SAFETY_MODEL` | BERT 安全模型路径 | `/app/models/bert-safety` |
| `MINDGLASS_PORT` | 后端端口 | `8001` |
| `MINDGLASS_REDIS_HOST/PORT/DB` | Redis 地址 | `127.0.0.1` / `6379` / `0` |
| `MINDGLASS_REUSE_THRESHOLD` | 语义复用相似度阈值 | `0.92` |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/tools` | 列出可用工具 |
| GET | `/api/graph` | 获取当前推理图（内存空时自动从 Redis 恢复） |
| POST | `/api/reuse/check` | 高频 query 复用语义检索，body: {query}；命中返回缓存图 |
| POST | `/api/run` | SSE 流式推理，body: {query, history, conversation_id} |
| POST | `/api/retry` | 从指定 step 重试（SSE） |
| POST | `/api/retry_from_graph` | 并行重试方案 C（SSE） |
| POST | `/api/interrupt` | 运行中打断（截断点后置灰保留） |
| GET | `/api/list-demos` | chatBI 演示用例列表（标签从文件 meta.query 提取，不暴露文件名） |
| POST | `/api/load-demo` | 加载演示用例（只读静态文件） |
| GET | `/api/admin/runs` | admin 运行记录（含 conversation_id 会话分组） |
| GET | `/api/admin/runs/{run_id}` | 单条运行快照（思维重现） |
| GET | `/api/admin/overview` | 总览指标（完答率/降级率/平均耗时） |

## Demo Query

| 类型 | Query | 展示能力 |
|------|-------|----------|
| 百科类 | 孙权封王称帝后立谁为太子？ | RAG 检索 + 回答生成 |
| 医疗类 | 激光治眼睛会复发吗？ | 多步推理 + RAG 召回 |
| 综合类 | 帮我查三篇论文的共同点 | 完整 Plan → ToolCall → Observe → Answer |
| 游戏类 | 星辰变大后期哪个职业最强？ | 本地知识库检索 |
| 搜索类 | 2025年华为前端开发最新技术趋势 | Tavily 网络搜索 |
| chatBI 基础 | 各部门平均薪资排名 | gen_sql → exec_sql → plot 柱状图 |
| chatBI 进阶 | 入职超过 20 年的员工最多的部门 | 多表 JOIN + 统计 |
| chatBI 高阶 | 每个部门薪资最高的员工是谁 | 窗口函数 RANK() 排名 |
| chatBI 电商 | northwind 各产品类别销量 TOP5 | 跨库查询 + 饼图/柱状图 |

## 项目结构

```
MindGlass/
├── backend/
│   ├── server.py              # FastAPI 入口
│   ├── agent/
│   │   ├── react_loop.py      # ReAct 循环主类（含 _SERIAL_TOOL_GROUPS 串行执行）
│   │   ├── planner.py         # LLM 任务规划（含 chatBI 工具触发规则）
│   │   ├── answerer.py        # LLM 回答生成（含 ```echarts 输出规则）
│   │   ├── tools.py           # 工具注册与执行（search/rag_retrieve/gen_sql/exec_sql/plot）
│   │   └── llm.py             # LLM 调用封装
│   ├── state/
│   │   ├── models.py          # 数据模型（Node/Edge/Branch）
│   │   ├── store.py           # 图状态管理（变更监听器 + 快照恢复）
│   │   └── redis_cache.py     # Redis 热缓存层（增量/覆盖/恢复/语义复用）
│   └── docs/
│       ├── BUGS.md            # Bug 记录与架构决策
│       └── BUG-17-DISCUSS.md  # 并行重试方案 C 讨论
├── frontend/
│   ├── src/
│   │   ├── App.vue            # 主应用（PC 左右分栏 / 移动端上下分栏）
│   │   ├── components/
│   │   │   ├── ChatPanel.vue      # 对话面板（按轮次渲染，含 ```echarts 图表渲染）
│   │   │   ├── ThoughtBlockList.vue # 思考直播 block 渲染（SQL 代码块/结果表格/内联图表）
│   │   │   ├── ReasoningGraph.vue # 思维图 + 节点编辑 + 打断（chatBI 差异化工具弹窗）
│   │   │   └── NodeDetail.vue     # 节点详情面板
│   │   ├── views/
│   │   │   ├── HomeView.vue       # 首页（对话 + 思维图）
│   │   │   └── AdminView.vue      # 后台（运行记录树状表格 + 思维重现）
│   │   ├── composables/
│   │   │   ├── useAgentGraph.ts   # SSE + rounds 状态管理 + 重试/打断
│   │   │   └── useReasoningGraph.ts # 图渲染逻辑
│   │   └── types/
│   │       └── agent.ts       # TypeScript 类型定义（含 Round）
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
- ✅ Phase 2：节点交互与干预
- ✅ Phase 3：工具扩展与打磨
- ✅ Phase 4：决策回环 v2 重构 + 打断/重试大修（边只标记不删除）
- ✅ Phase 5：BERT 安全防线 + 移动端适配 + 多轮对话 + 会话关联（2026-08）
- ✅ Phase 6：Redis 热缓存层——断联恢复 + 高频 query 语义复用（2026-08-10，本地验收通过）
- ✅ Phase 7：chatBI 数据分析能力——gen_sql/exec_sql/plot 三工具 + ECharts 可视化（2026-08-16，分支 feature/chatbi）
- ✅ 已上线：mindglass.stelladream.cn（Docker Compose + Nginx）

## License

个人项目，用于面试展示与技术能力验证。
