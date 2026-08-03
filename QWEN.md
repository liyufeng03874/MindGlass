# MindGlass — 可观测多步推理 Agent

FastAPI 后端 + Vue3/TypeScript 前端。核心是 Reason-Act-Observe 决策回环：Plan(决策) → 并行 ToolCall → Observe(结构化评估) → 回 Plan 或 Answer，支持人工在环干预（截断/编辑/重跑节点）。

## 项目结构

```
mindglass/
├── backend/
│   ├── server.py              # FastAPI 入口（:8000 左右，见 run 脚本）
│   ├── state/
│   │   ├── models.py          # NodeType(Plan/ToolCall/Observe/Answer) / NodeStatus(done/current/pending/error/discarded/branch) / ReasoningNode(含 duration_ms) / ReasoningEdge / BranchRecord / ReasoningMeta(query/run_id/run_started_at/plan_count)
│   │   └── store.py           # ReasoningGraphStore：nodes/edges/branches/meta 全在【内存】，to_dict() 输出 {nodes,edges,branches,meta} —— 这就是 demo 格式
│   ├── agent/
│   │   ├── react_loop.py      # 决策回环主逻辑（756 行）。MAX_PLAN_COUNT=3。工具失败→ToolCall 节点 status="error"；硬终止→decision=="terminate"→Answer 节点 data.degraded=True、label 含「信息可能不完整」
│   │   └── answerer.py        # generate_answer
│   ├── docs/                  # demo_1 ~ demo_12，每个是一份完整 demo 格式 JSON（{nodes:[...],...}）
│   └── requirements.txt
├── frontend/                  # Vite + Vue3 + TS（用户端推理图界面）
│   └── src/
│       ├── components/
│       │   ├── ReasoningGraph.vue   # ⭐ 推理图渲染组件（吃 {nodes,edges} demo 格式）——思维重现必须复用它，不许重写
│       │   ├── ChatPanel.vue
│       │   └── NodeDetail.vue
│       ├── composables/{useAgentChat,useAgentGraph,useReasoningGraph}.ts
│       └── types/agent.ts
└── QWEN.md                    # 本文件
```

## 关键事实（写代码前务必消化）

- **当前无任何持久化**：真实 run 只活在内存 `_store`（server.py 的全局单例），重启即丢，也没有任何 run 历史。本任务的地基就是给 run 加落盘。
- **demo 格式 = 快照格式**：`store.to_dict()` 产出的 `{nodes,edges,branches,meta}` 与 docs/demo_*.txt 完全同构。前端 `ReasoningGraph.vue` 吃的就是这个格式。
- **降级信号**：`Answer.data.degraded == True`（对应 Plan decision=="terminate" 硬终止）。自然充分终止则 degraded==False。
- **工具失败信号**：`ToolCall` 节点 `status == "error"`。
- **最终答案**：最后一个 `status=="done"` 的 Answer 节点的 `data.output`。
- Python 唯一环境：`D:\miniconda3\envs\aivenv\python.exe`（勿用 C:\Python314）。

## 执行纪律（开工前读）

### 环境
- Python 只用 `D:\miniconda3\envs\aivenv\python.exe`。
- 本机内存紧张，别并发跑多个重进程。

### 边界（隔离勿动）
- **不要改动任何现有用户端逻辑/接口**（`/api/run`、`/api/graph`、`/api/retry`、`/api/load-demo`、ReasoningGraph.vue 等）。本任务只做**加法**：新增持久化层 + 新增 `/api/admin/*` + 前端新增 admin 路由。
- 现有 `docs/demo_*.txt` 只读，别改。
- 改代码前先 `git status` 看清分支。**新开分支 `feature/admin` 再动手，别直接在 master 改。**

### 代码纪律
- 优先精确小范围编辑；新建文件可以整文件写。
- **新写的代码必须加注释**（项目的人要看，中文注释 OK）。
- 每改完先做语法/导入检查（`python -c "import ast; ..."` / 能 import）再说“完成”，别凭“看起来对”。

### 怎么算完成
- 跑通验证（能 import、接口能返回、前端能渲染）才算完成。
- 卡住别硬绕：同一点试 2-3 次还不通就停，把现状+卡点写进 notes 交回。

### 怎么交活
- 结果只写进 `backend/notes/mindglass-admin-notes.md`（没有就建目录）：改了哪些文件、怎么验证的、指标口径最终怎么定的、遗留什么。
- **notes 是你唯一的交付接口**，调用方不会读你的完整对话。

---

# 📌 当前任务：MindGlass 后台管理（run 历史总览 + 思维重现）

## 目标
给 MindGlass 加一个后台管理视图：把每次 run 的完整推理图快照落盘，用一张表直观展示所有 run，顶部放总览指标，每条记录能一键把推理图渲染出来（思维重现）。

## 三层需求

### 1. 持久化（地基，先做）
- run 跑完（SSE 流结束、Answer 节点产出后），把 `store.to_dict()` 的完整快照（demo 格式）存进 SQLite。
- DB 路径：`backend/data/mindglass_admin.db`（把 `backend/data/*.db` 加进 .gitignore）。用标准库 sqlite3，WAL 模式即可（参考成熟做法，无需 ORM）。
- 每条 run 存：完整快照 JSON + 计算好的统计字段，便于列表直接取，不用每次反序列化全图：
  - `run_id`、`query`（=meta.query）、`created_at`
  - `final_answer`（最后一个 done Answer 的 data.output）
  - `total_nodes`、`plan_count`、`toolcall_count`、`observe_count`、`answer_count`（各类型节点数）
  - `total_duration_ms`（各节点 duration_ms 之和）
  - `degraded`（最终 Answer 的 data.degraded，0/1）
  - `tool_error_count`（status=="error" 的 ToolCall 数）
  - `snapshot`（完整 demo 格式 JSON 文本，供重现）
- **初始化种子**：把 `docs/demo_1~demo_12` 这 12 份也导入 runs 表（它们本就是 demo 格式），让后台一打开就有数据。写一个幂等的 seed 脚本 `backend/scripts/seed_admin_runs.py`（按 run_id/文件名去重，可重复跑不重复插）。demo 没有的统计字段（如 duration）按快照里有的算、没有的置空/0。

### 2. 后端接口（新增，勿动现有）
- `GET /api/admin/overview` → 总览指标：
  - `total_runs`（总 run 数）
  - `answer_rate`（完答率 = degraded==0 的 run 数 / 总 run 数）
  - `degraded_rate`（降级率 = degraded==1 的 run 数 / 总 run 数）
  - `tool_error_total`（所有 run 的 tool_error_count 之和）
  - `avg_duration_ms`（平均总耗时）
- `GET /api/admin/runs` → run 列表（按 created_at 倒序），返回统计字段列（不含完整快照，避免体量大）：run_id / query / final_answer(可截断预览) / total_nodes / 各类型节点数 / total_duration_ms / degraded / tool_error_count / created_at。支持分页（limit/offset）。
- `GET /api/admin/runs/{run_id}` → 单条完整快照（`{nodes,edges,branches,meta}`），供前端思维重现直接喂给 ReasoningGraph。

### 3. 前端（加到现有 frontend，复用图组件）
- 在现有 frontend 里新增一个 admin 视图/路由（如 `/admin`），**不要另起一个独立前端工程**——目的是直接 import 复用 `ReasoningGraph.vue`，避免重写图渲染。
- 布局：
  - 顶部：总览指标卡（完答率 / 降级率 / 工具失败次数 / 总 run 数 / 平均耗时）。
  - 主体：run 列表表格，列含 原始 query、最终 answer（预览）、总节点数、各类型节点数、耗时、是否降级、时间。
  - 每行一个【思维重现】按钮 → 调 `/api/admin/runs/{run_id}` 拿快照 → 用 `ReasoningGraph.vue` 在弹窗/抽屉里渲染出推理图。
- 技术栈与现有前端一致（Vue3 + TS + Vite）。样式跟现有界面协调即可，不用过度设计。

## 验收标准（逐条做到再报完成）
1. 跑 seed 脚本后，`GET /api/admin/runs` 能返回 12 条 demo 记录。
2. `GET /api/admin/overview` 五个指标都有值且口径正确（完答率+降级率=1，在无其他 run 时）。
3. 前端 `/admin` 打开能看到 12 条记录的表格 + 顶部指标卡。
4. 点任意一条【思维重现】，能渲染出该 run 的推理图（和用户端看到的图一致）。
5. 真实跑一次 `/api/run`（随便一个 query），跑完后该 run 自动出现在 admin 列表里。
6. 现有用户端功能（`/api/run`、推理图界面）不受影响。

## 交活
全部结果写进 `backend/notes/mindglass-admin-notes.md`：新增/修改的文件清单、指标最终口径、如何验证的（贴关键命令/返回）、遗留问题。

---

# 📌 当前任务②：输出合规校验 · 微调脚手架（只做脚手架 + 冒烟，不真训）

> ⚠️ **qwen 注意**：做这一节（任务②），**不要碰上面那个 admin 任务**。

## 背景
哥哥要给 MindGlass 的 Answer 输出加一层“合规校验”：主 LLM 出答案后，用一个**微调过的 bert-base-chinese 二分类器**判“合规/不合规”，不合规走降级话术。本步先搭工程脚手架 + 用小样本冒烟跑通整条链路，**证明流程可行**；真实语料收集和正式训练由哥哥之后拍板，本次不做。

## 模型
- 本地底座：`D:\ai\bert-base-chinese`（已确认存在，含 pytorch_model.bin / config.json / tokenizer / vocab）。**从本地加载，不联网下载。**

## 环境 & 纪律
- Python 只用 `D:\miniconda3\envs\aivenv\python.exe`（transformers 4.57.6 / torch CUDA 已就绪，勿重装）。
- **新开分支 `feature/moderation` 再动手**，别在 master 改。
- **只做加法**：新建 `backend/moderation/` 模块，**不许碰** server.py / react_loop.py / 前端 / 现有接口。本次不接入主流程，只出独立可调的脚手架。
- 新代码必须加中文注释；改完先 import/语法检查再说完成。

## 需要交付的文件（backend/moderation/）
1. `data_prep.py` — 读 JSONL（每行 `{"text": ..., "label": 0/1}`，1=不合规），tokenize，切 train/val（8:2），产出 transformers `Dataset`。
2. `train.py` — 用 `AutoModelForSequenceClassification`（num_labels=2，从本地底座加载）+ `Trainer`。超参：lr=2e-5、epochs=3、batch=16、warmup_ratio=0.1、weight_decay=0.01；**针对类别不平衡配置**（loss 加 class weight）；评估指标 **F1 + precision + recall**（不是 accuracy）。支持 `--max_steps N` 用于冒烟。
3. `predict.py` — 加载训好的 checkpoint，对一段文本输出 `{label, label_name, confidence}`。
4. `export_onnx.py` — 把训好的模型导成 ONNX（CPU 推理用）。
5. `data/sample.jsonl` — **20 条手标小样本**（合规/不合规各约一半，法律问答场景），仅供冒烟，**不是真实语料**。文件头注释写明“冒烟样本，非真实训练集”。

## 验收标准（逐条做到再报完成）
1. 能从 `D:\ai\bert-base-chinese` 本地加载底座（不联网），打印加载成功。
2. 四个 py 文件齐全、有注释、`python -c "import ..."` 全部通过。
3. 用 `sample.jsonl` 跑 `train.py --max_steps 10` 能完成几步训练、产出 checkpoint（证明训练循环通）。
4. `predict.py` 能用冒烟 checkpoint 对一条文本给出分类结果。
5. `export_onnx.py` 能导出 .onnx 文件。
6. **不接入主流程、不动任何现有文件**。

## 交活
写进 `backend/notes/moderation-finetune-notes.md`：新增文件清单、每步怎么跑（贴命令）、冒烟结果、**真实训练还缺什么（语料从哪来、要多少、标注规范）**、之后怎么接到 Answer 节点。

## ⚠️ 边界强调
- **不要收集/构造真实语料，不要跑完整训练**——本次只冒烟。真实数据是哥哥下一步的决定。
- 本机内存紧张，训练冒烟用小 batch / 少 step，别 OOM。

---

# 📌 当前任务③：水镜 Live v2.2 · 第一批（左侧思考过程实时直播）

> ⚠️ **qwen 注意**：只做这一节（任务③），不要碰任务①②（admin / moderation）。
> 设计全文见 workspace 的《水镜v2.2设计文档》，这里是执行版 brief。

## 背景与目标
现在思镜左侧（ChatPanel）在 LLM 执行过程中几乎空荡荡，直到最后才出最终回答。
目标：**左侧变成思考过程的实时直播**——规划流式显示、工具调用结果实时显示（限高可展开）、评估/决策流式显示、回答流式显示。内容不断追加，不是最后才给。

本批只做 **Phase 1 基础流式显示**，不做思考动画、左右联动（那是第二批）。

## 关键事实（先消化）
- `backend/agent/llm.py` **已有** `generate_stream(prompt, system_prompt, model, temperature)`，返回 chunk 生成器——不要重新实现流式调用，直接用它。
- SSE 事件统一走 `react_loop.py` 的 `_emit(event_type, data)`，格式 `event: {type}\ndata: {json}\n\n`。
- 现有事件类型：`node_added / node_updated / node_complete / status / run_complete / error`。
- 前端 `frontend/src/composables/useAgentGraph.ts` 的 `handleEvent` 是事件分发入口；左侧渲染在 `frontend/src/components/ChatPanel.vue`（目前只有 messages 数组：用户问题 + 最终回答）。
- Plan 在 `agent/planner.py`（initial plan + decide，都用非流式 generate）；Answer 在 `agent/answerer.py`；Observe 在 `agent/observer.py`。

## 后端改造（backend/）

### 1. 新增 SSE 事件 `node_streaming`
- 数据格式：`{"node_id": str, "node_type": "Plan"|"Observe"|"Answer", "chunk": str(本次增量文本), "content": str(累计全文), "is_complete": bool}`
- chunk 是增量，content 是累计（前端用 content 直接覆盖渲染，不用自己拼）。

### 2. 三个 LLM 环节接流式
- **Plan（规划+决策）**：planner 的 `_initial_plan` 和 `_decide` 改用 `generate_stream`，边收 chunk 边 yield `node_streaming` 事件。注意：Plan 的最终产物仍要解析成现有 JSON 结构（决策 steps/decision），**流式只用于展示过程，不改变节点数据结构**。解析失败兜底逻辑保留。
- **Answer**：answerer 改流式，边收边 emit，最后照常 `node_complete`。
- **Observe**：observer 改流式，同上。
- 如果某个环节改流式风险大（JSON 解析被打断等），允许保留该环节非流式，但在 notes 里说明原因，**不许悄悄跳过**。

### 3. 工具结果事件补强
- 每个 ToolCall 完成时，`node_complete` 的 data 里确保带上 `tool_name`、`params`（关键参数如 query/top_k）、`result_preview`（结果截断 500 字）——前端左侧要直接展示这些。现有结构已有 data.output 的话，补 params/tool_name 即可，不破坏现有字段。

### 4. 纪律
- **只做加法或小改**：不许改变 node_complete/run_complete 的现有字段语义，右侧 ReasoningGraph 的渲染不能受影响。
- 改完用 curl 跑一次 `/api/run?query=...`，确认事件流里出现 node_streaming，且原有 node_complete 序列不变。

## 前端改造（frontend/）

### 5. useAgentGraph 增加左侧内容块状态
- 新增响应式数组 `leftBlocks`，每项：
  ```ts
  interface LeftBlock {
    id: string;            // = node_id
    nodeId: string;
    type: 'plan' | 'toolcall' | 'observe' | 'answer';
    status: 'loading' | 'done' | 'error';
    title: string;         // 如 "🧠 正在规划..." / "🔧 调用工具: search" / "🔍 评估中..." / "💬 生成回答..."
    content: string;       // 流式内容（node_streaming 的 content 直接覆盖）
    metadata?: { toolName?: string; params?: Record<string, any>; resultPreview?: string };
  }
  ```
- `node_streaming` → 找到或新建对应 block，status=loading，content 覆盖更新。
- `node_complete` → 对应 block status=done；ToolCall 类型填 metadata（toolName/params/resultPreview）。
- 事件到来顺序即 block 追加顺序，**只追加不删除**（一次 run 内）。

### 6. ChatPanel.vue 增加「思考直播区」
- 位置：messages 列表内、最终回答之前——即用户提问之后，随 run 进行不断追加 leftBlocks。
- 每个 block 渲染：标题行（icon+文字，loading 时带轻微脉冲动画，done 时恢复）+ 内容区。
- **Plan/Observe/Answer block**：内容用 markdown-it 渲染（复用 ChatPanel 现有 md 实例），Plan 若是 JSON 原文则用 `<pre>` 等宽展示。
- **ToolCall block**：
  - 标题行显示工具名+关键参数摘要（如 query）。
  - 结果区**默认最大高度 200px、overflow-y auto**，标题行加「展开/收起」按钮切换（展开=不限高）。
  - **并行多个 ToolCall**：同一轮的多个工具 block 用 CSS grid 两列排列（`display:grid; grid-template-columns:1fr 1fr; gap`），样式统一。判断"同一轮"：连续到达且类型都是 toolcall 且都属于当前 plan 轮次的 block 归为一组（可用相邻 toolcall 聚合的简单实现，notes 里写清你的聚合规则）。
- 一次 run 结束（run_complete）后，思考直播区保留可见，最终回答照常出现在其后（现有 messages 逻辑不动）。
- 自动滚动：新 block/chunk 到来时若用户贴底则自动滚到底；用户上滑查看历史时停止自动滚动，显示「回到最新」小按钮。

### 7. 样式
- 与现有暗色主题协调（复用 style.css 的 CSS 变量：--panel-bg / --text-dim / --accent 等）。
- loading 脉冲动画用 CSS keyframes（box-shadow 呼吸即可），不引第三方库。

## 提交纪律（重要）
- **新开分支 `feature/water-mirror-live`**，别在 master 改。
- **分批次提交**：后端跑通一次 commit（`feat(backend): node_streaming 流式事件`），前端跑通一次 commit（`feat(frontend): 左侧思考直播区 Phase1`）。每批提交前确保能编译/能 import。

## 验收标准（逐条做到再报完成）
1. curl `/api/run?query=xxx`，事件流中出现 node_streaming（至少 Plan 和 Answer 两个环节）。
2. 右侧 ReasoningGraph 渲染与改造前完全一致（现有 node 事件语义未变）。
3. 前端打开页面发起一次真实 run：左侧随进度不断追加「规划→工具调用→评估→决策→回答」内容块，过程中左侧始终有内容，不再空荡。
4. ToolCall 结果默认限高 200px，可展开；并行工具呈两列网格。
5. run 完成后思考直播区保留，最终回答照常显示。
6. 自动滚动贴底跟随、上滑不打断、有「回到最新」按钮。
7. demo 数据加载（/api/load-demo）不受影响。

## 交活
写进 `backend/notes/water-mirror-live-notes.md`：改动文件清单、node_streaming 最终格式、哪些环节真接了流式/哪些没有及原因、前端聚合规则、怎么验证的（贴命令）、遗留问题（第二批要做的：思考动画、左右联动）。

---

# 📌 当前任务⑤：水镜 Phase1 实测修复（哥哥 2026-08-04 00:06 实测提的三个问题）

> ⚠️ qwen 注意：只做这一节。后端已由妹妹重启为新代码（8001），流式/工具结果字段问题已排除后端因素，本任务只做前端。

## 问题清单（哥哥实测截图）

### P1：思考直播区位置错 + 工具结果空
- 现状：leftBlocks 整块渲染在 ChatPanel 最顶端，出现在用户问题气泡**之前**；应该在**用户问题之后、最终回答之前**。
- 现状：工具 block 显示"已完成"但结果区为空。后端已确认会发 `result_preview`（curl 可见），检查 useAgentGraph.ts 里 node_complete 的 metadata 映射和 ChatPanel.vue 的 `tool-result` 渲染条件，找到为什么取不到并修好。若是事件到达顺序问题（node_complete 先到、字段在 event.data 顶层），确保映射读 `event.data.result_preview`。
- 要求：一次 run 内的显示顺序 = 用户问题气泡 → 该 run 的思考直播 blocks（按事件顺序追加）→ 最终回答气泡。demo 加载场景也要正常（blocks 为空时不留空白区）。

### P2：规划/评估/决策左侧无流式（已排除后端）
- 后端 8001 已重启为新代码，node_streaming 事件已会推送。若重启后浏览器仍无流式显示，检查前端 SSE 解析是否识别 `node_streaming` 类型（useAgentGraph 的 handleEvent + SSE 分行解析逻辑），修到左侧实时出现 🧠/🔍 blocks。

### P3：流程图节点配色与星空背景不搭
- 现状：ReasoningGraph.vue 节点是浅色纯底（浅蓝/浅绿/浅橙）+ 深色文字，与深空星空背景冲突。
- 改为深空主题：节点背景半透明深色（如 rgba(10,14,31,0.72)）+ 轻微 backdrop-blur；边框用发光色（规划=靛蓝 #60a5fa、工具=青绿 #34d399、评估=琥珀 #fbbf24、回答=金紫 #c4b5fd），1.5px + 外发光 box-shadow；文字浅色（#e6e9f5 系）；选中/悬停态提亮。连线颜色同步调柔（低饱和）。保持现有布局/交互不变，只改配色样式。

## 纪律
- 分支 feature/water-mirror-live 继续；改完 npm run build 必须通过；分批次 commit（中文 message：`fix(frontend): 思考直播区位置与工具结果修复` / `style(frontend): 流程图节点适配星空主题`）。
- 验证：起 vite dev（5177 已在跑则热更即可），用浏览器无关的方式至少确认 build 通过 + 代码逻辑自查；最终视觉验收由哥哥做。
- 结果写进 backend/notes/water-mirror-live-notes.md 追加一节「任务⑤修复记录」。

---

# 📌 当前任务⑥：实测第四轮修复（哥哥 2026-08-04 01:29 提的四个问题）

> ⚠️ qwen 注意：只做这一节。分支 feature/water-mirror-live。已确认上一轮（任务⑤及后续修复 c103eb0/5b4d9a2/c51922c）生效：右侧一层一节点、深空配色、左侧滚动正常。本轮四个问题：

## P1：左侧思考直播区 JSON 要"读给人听"，不要原样 JSON
- 现状：规划/评估/决策 block 用 `formattedJson` 把原始 JSON 美化后直接 `pre` 展示，字段（thought/steps/params/round/summary/key_findings/conflicts...）裸露，哥哥认为不便阅读。
- 改为**人读样式**（ChatPanel.vue）：plan/observe/answer(非最终回答) 的 content 若能解析成 JSON，按类型提取关键字段渲染成结构化但友好的视图：
  - **Plan（规划/决策）**：显示「思考」一行（thought/reasoning 文本）；若有 steps，列成带序号的小列表（工具中文名 + description + query 参数摘要）；显示决策标签（need_more→"需要补搜" / terminate→"终止" / sufficient→"信息充足"），用彩色小徽章。
  - **Observe（评估）**：显示 summary 一段话；key_findings 列成 bullet 列表；conflicts 非空时列「矛盾」列表；new_info_vs_previous 一行。
  - 流式过程中（JSON 不完整）保持原文展示即可，完成后切换人读视图。
  - 保留「查看原文」小按钮（点击展开原始 JSON 的 pre，复用 json-body 样式），默认不展开。
- 注意：最终回答（answer 且是 run 的最终回答气泡）保持 markdown 渲染不变。

## P2：最大规划轮数 3 → 5
- 后端 react_loop.py 的 MAX_PLAN_COUNT（或等价常量）从 3 改 5。
- 注意连带文案：第 3 轮强制 terminate 的逻辑、"这是第 3 轮（最后一轮）"的 prompt 文案、_parse_decision_result 里 plan_count>=3 强制 terminate 的判断，全部跟着 5 走（抽常量 MAX_PLAN_COUNT 统一引用，别再散落魔法数字）。
- 前端如有"最多 3 轮"的展示文案也同步改。

## P3：节点编辑弹窗主题化
- 现状：点击右侧节点弹出的编辑/详情弹窗是纯白背景，灰字在白底上几乎不可见，且与深空主题不符。
- 找到该弹窗组件（ReasoningGraph.vue 内或独立组件），改为深空主题：背景 rgba(10,14,31,0.92)+backdrop-blur，边框 1px 发光色（同节点配色），文字 #e6e9f5 系，输入框/按钮深色样式，滚动条同 P4 风格。所有文字保证对比度（禁用低对比灰字）。

## P4：全局滚动条主题化
- 给左侧 .messages、.tool-result、.json-body、弹窗内滚动区等所有滚动容器加 webkit 自定义滚动条：轨道透明/深色 rgba(255,255,255,0.04)，滑块 rgba(167,139,250,0.35) 圆角 4px，hover 提亮 rgba(167,139,250,0.6)，宽度 8px；firefox 用 scrollbar-width: thin + scrollbar-color。
- 抽成一个公共 class（如 .themed-scroll）统一复用。

## 纪律
- 改完 npm run build 通过；分批次 commit（中文 message：`feat(frontend): 思考直播区人读视图+原文折叠` / `fix(backend): 最大规划轮数3→5抽常量` / `style(frontend): 节点弹窗与滚动条深空主题化`）。
- 结果追加写进 backend/notes/water-mirror-live-notes.md「任务⑥修复记录」。


---

# 任务⑦：哥哥验收反馈两修（toolcall 人读视图 + 点击聚焦联动）

## 背景
哥哥验收任务⑥成果后提出两个改进点。

## T1：toolcall 人读视图 + 截断修复
**现象**：
1. 左侧「调用工具: search」block 仍是 raw JSON（resultPreview），未做人读视图
2. 左侧工具结果被截断（500 字符上限），右侧节点弹窗却能看到完整 output——两侧口径不一致

**关键事实**：
- backend/agent/react_loop.py 第 756~758 行：result_preview = json.dumps(res,...)[:500]，截断 500 字符
- 完整工具结果在 node_complete 事件的 node output 里（右侧弹窗显示的就是它）
- 前端 ChatPanel.vue：单列 toolcall block（约 129 行 template）和并行组卡片（约 144 行起）都渲染 metadata.resultPreview 为 pre.tool-result
- search 工具返回结构（backend/agent/tools.py）：{query, results: [{title, url, snippet}], count} 或 {query, error, results: []}

**要求**：
1. 后端：result_preview 上限 500 → 4000；同时 node_complete 的 metadata 里加 result_full 字段（放完整结果 JSON 字符串），保证左侧能展示不截断的主内容
2. 前端人读视图：解析 result_full（回退 result_preview），若为搜索结果（含 results 数组）→ 渲染结果列表：每条 = 标题（a 标签 target=_blank rel=noopener 打开 url）+ 来源域名 + snippet；error 或 results 为空 → 显示错误信息/无结果。保留「查看原文」折叠按钮（复用现有 showRaw/toggleRaw 机制，展示格式化 JSON）
3. 并行组卡片与单列用同一套人读逻辑（抽公共函数或子组件，勿复制粘贴两份）
4. 结果列表默认最多显示 3 条，超出部分用「展开全部 N 条」按钮；与现有 expandedBlocks 展开/收起机制二选一融合，不要出现双层折叠嵌套

**验收标准**：
- 「调用工具: search」block 显示人读结果列表（标题+来源+摘要），不再是 raw JSON
- 左侧内容不再被 500 字符截断
- 并行 toolcall 组与单列渲染一致
- 「查看原文」可回退原始 JSON
- npm run build 通过

## T2：点击最终回答节点 = 复播聚焦动画
**现象**：早期版本点击最终回答节点会放大左侧回答内容；现在最终回答完成后自带聚焦动画，但点击节点不触发/不对位。

**关键事实**：
- ReasoningGraph.vue 约 370 行：点击 Answer 节点已 emit('focus-answer')（replaced/branch 走弹窗，不动）
- HomeView.vue 约 142 行：onFocusAnswer() → chatPanelRef.highlightLastMessage()
- ChatPanel.vue 约 299~312 行：highlightLastMessage() 滚动到 props.messages 最后一条 + highlightIndex → .bubble.highlighted → answerHighlight 2s 动画
- 问题根源：水镜 v2.2 的最终回答渲染在左侧思考直播区的 thought-block（displayItems 里 type=answer），不在 messages 气泡里——动画打错了对象

**要求**：
1. ChatPanel 里新增/改造聚焦函数：滚动到左侧思考直播区最后一个 type=answer 的 block，并对该 block 播放聚焦动画（与完成时的自动聚焦动画视觉一致——可复用 answerHighlight 样式或给 answer block 单独定义同款闪光/放大效果）
2. 统一成一个函数：回答完成时自动调用一次 + 点击节点时再调用一次（行为完全一致，可重复触发）
3. HomeView.onFocusAnswer 改为调用新函数；保持 defineExpose 接口不破坏
4. 不影响 replaced/branch Answer 的弹窗逻辑

**验收标准**：
- 回答完成后，点击右侧推理图「最终回答」节点 → 左侧滚动到答案 block 并播放聚焦动画（与完成时动画一致）
- 重复点击可重复触发动画
- npm run build 通过

## 纪律
- 改完 npm run build 必须通过；分批次 commit（中文 message，如 feat(frontend): toolcall人读视图 / feat(frontend): 点击最终回答节点聚焦联动）
- 后端有改动（react_loop.py）→ notes 里标注「需重启 8001」，妹妹负责重启
- 结果追加写进 backend/notes/water-mirror-live-notes.md「任务⑦修复记录」
