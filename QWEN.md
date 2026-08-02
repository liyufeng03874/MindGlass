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
