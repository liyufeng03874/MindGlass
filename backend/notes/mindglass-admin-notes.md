# MindGlass Admin 后台管理 — 交活文档

## 新增/修改文件清单

### 新增文件
| 文件 | 说明 |
|------|------|
| `backend/admin/__init__.py` | admin 模块初始化 |
| `backend/admin/persistence.py` | SQLite 持久化层（WAL 模式），含建表、快照保存、统计字段计算、种子导入、查询接口 |
| `backend/scripts/seed_admin_runs.py` | 幂等 seed 脚本，将 12 个 demo 导入 runs 表 |
| `frontend/src/router/index.ts` | vue-router 配置（`/` → HomeView，`/admin` → AdminView） |
| `frontend/src/views/HomeView.vue` | 首页视图（从原 App.vue 提取的业务逻辑 + 模板） |
| `frontend/src/views/AdminView.vue` | 后台管理视图：顶部 5 个指标卡 + run 列表表格 + 弹窗思维重现 |

### 修改文件
| 文件 | 说明 |
|------|------|
| `.gitignore` | 新增 `backend/data/*.db` 忽略规则 |
| `backend/server.py` | 新增 admin import + 初始化调用 + `/api/admin/overview`、`/api/admin/runs`、`/api/admin/runs/{run_id}` 三个接口 + SSE 流结束后自动落盘快照 |
| `frontend/src/App.vue` | 改为仅含 `<RouterView />` 的路由容器 |
| `frontend/src/main.ts` | 引入并使用 vue-router |

### 不动的（按纪律要求）
- 现有 `/api/run`、`/api/graph`、`/api/retry`、`/api/load-demo` 接口代码完全未改（只包裹了 SSE 流结束后的 `finally` 落盘，不影响原有推送行为）
- `ReasoningGraph.vue` 完全未动，直接 import 复用
- `docs/demo_*.txt` 只读不改
- `state/models.py`、`state/store.py`、`agent/react_loop.py`、`agent/answerer.py` 全部未动

## 指标最终口径

| 指标 | 计算方式 |
|------|----------|
| `total_runs` | `SELECT COUNT(*) FROM runs` |
| `answer_rate` | `SUM(degraded==0) / total_runs`（无 run 时为 0.0） |
| `degraded_rate` | `SUM(degraded==1) / total_runs`（无 run 时为 0.0） |
| `tool_error_total` | `SUM(tool_error_count)`（所有 run 的 status=="error" 的 ToolCall 数之和） |
| `avg_duration_ms` | `AVG(total_duration_ms)`（所有 run 的节点 duration_ms 之和的平均值） |

> 注：无其他 run 时 answer_rate + degraded_rate = 1.0（seed 数据全为 0 degraded，所以 answer_rate=1, degraded_rate=0）

**各统计字段来源**（在 `_compute_stats()` 中从快照计算）：
- `total_nodes` = `snapshot.nodes.length`
- `plan_count` = 节点 type=="Plan" 的数量
- `toolcall_count` = 节点 type=="ToolCall" 的数量
- `observe_count` = 节点 type=="Observe" 的数量
- `answer_count` = 节点 type=="Answer" 的数量
- `total_duration_ms` = 各节点 `duration_ms` 之和（无值时按 0 处理）
- `degraded` = 最后一个 status=="done" 的 Answer 节点的 `data.degraded`
- `tool_error_count` = status=="error" 的 ToolCall 数量
- `final_answer` = 最后一个 status=="done" 的 Answer 节点的 `data.output`

## 验证步骤（Shell 被拦截，请手动执行）

### 1. 安装 vue-router

```bash
cd D:\code\mindglass\frontend
npm install vue-router@4
```

### 2. 切换分支 + 运行 seed 脚本

```bash
cd D:\code\mindglass
git checkout -b feature/admin
D:\miniconda3\envs\aivenv\python.exe backend/scripts/seed_admin_runs.py
```

期望输出：
```
[seed] DB 初始化完成
[+] 导入 demo_1 (demo_1(3个百科问题).txt)
[+] 导入 demo_2 (demo_2(并行诗句问答).txt)
...
[+] 导入 demo_12 (demo_12(无理由爱).txt)
[seed] 完成：导入 12 条，跳过 0 条，共 12 个 demo
```

再跑一次验证幂等：
```bash
D:\miniconda3\envs\aivenv\python.exe backend/scripts/seed_admin_runs.py
```
期望输出应为「跳过 12 条，导入 0 条」。

### 3. 启动后端

```bash
cd D:\code\mindglass\backend
D:\miniconda3\envs\aivenv\python.exe server.py
```

后端在 `http://localhost:8002` 启动（默认端口）。

### 4. 验证 API

**总览接口**：
```bash
curl http://localhost:8002/api/admin/overview
```
期望返回（seed 后 12 条 demo，全部非降级）：
```json
{
  "total_runs": 12,
  "answer_rate": 1.0,
  "degraded_rate": 0.0,
  "tool_error_total": <各 demo 的 tool error 之和>,
  "avg_duration_ms": <平均耗时>
}
```

**Run 列表**：
```bash
curl "http://localhost:8002/api/admin/runs?limit=20&offset=0"
```
期望返回 12 条记录，`total: 12`。

**单条快照**：
```bash
curl http://localhost:8002/api/admin/runs/demo_1
```
期望返回 `{nodes: [...], edges: [...], branches: [...], meta: {...}}` 完整快照。

### 5. 启动前端

```bash
cd D:\code\mindglass\frontend
npm run dev
```

前端默认在 `http://localhost:5173`（或 5174 等，看 vite 输出）。

### 6. 验证前端

1. 打开 `http://localhost:5173/` — 应看到原首页正常工作
2. 打开 `http://localhost:5173/admin` — 应看到：
   - 顶部 5 个指标卡（总 Run 数=12、完答率=100.0%、降级率=0.0% 等）
   - 下方 12 条 run 记录表格
   - 每行有「🔍 思维重现」按钮
3. 点击任意一条的思维重现按钮 — 弹窗中应渲染出推理图（VueFlow 组件）

### 7. 验证真实 run 落盘

在首页发一个查询（如 "1+1等于几"），等 SSE 流结束跑完后，刷新 `/admin` 页面，应能看到新增的一条 run 记录。

## 遗留问题 / 注意事项

1. **Shell 命令被安全策略完全拦截**：所有 shell 操作（git checkout、npm install、python 执行、curl 测试）均被 `Auto mode classifier` 拦截，无法在此会话中直接验证。需要用户手动执行上述验证步骤。

2. **vite proxy 端口不匹配**：现有 `vite.config.ts` 中 proxy 目标为 `localhost:8001`，但 `server.py` 默认端口为 `8002`（`MINDGLASS_PORT` 环境变量）。启动后端时需指定 `MINDGLASS_PORT=8001` 或修改 vite 配置。这是已有问题，未改动。
   启动建议：`cd backend && set MINDGLASS_PORT=8001 && D:\miniconda3\envs\aivenv\python.exe server.py`

3. **vue-router 需手动安装**：`npm install vue-router@4` 无法自动执行，安装后前端才能路由到 `/admin`。

4. **App.vue 改为 RouterView 容器**：原 App.vue 的所有业务逻辑已迁移到 HomeView.vue，App.vue 现在是纯路由容器。如果 HomeView.vue 的样式/行为与原版有差异，请对比调整。

5. **DB 路径**：`backend/data/mindglass_admin.db`，WAL 模式会自动产生 `-wal` 和 `-shm` 伴随文件。`.gitignore` 已添加 `backend/data/*.db`。

6. **run 自动落盘时机**：SSE `event_stream()` 的 `finally` 块中执行落盘。如果 SSE 连接异常中断（非正常完成），可能快照不完整。当前加了 `if snapshot.get("nodes")` 保护。

7. **前端 API_BASE**：AdminView.vue 使用 `import.meta.env.VITE_API_BASE_URL || '/api'`，与 HomeView 一致。vite dev server 的 proxy 配置会确保 `/api` 转发到后端。
