<template>
  <!-- ── 密码门：未认证时只显示登录框 ── -->
  <div v-if="!authenticated" class="auth-gate">
    <div class="auth-box">
      <h2>🔒 MindGlass Admin</h2>
      <p class="auth-hint">请输入访问密码</p>
      <input
        v-model="passwordInput"
        type="password"
        placeholder="密码"
        @keydown.enter="checkPassword"
        autofocus
      />
      <button @click="checkPassword">进入</button>
      <p v-if="authError" class="auth-error">❌ 密码错误</p>
    </div>
  </div>

  <div v-else class="admin-page">
    <header class="admin-header">
      <router-link to="/" class="back-link">← 返回首页</router-link>
      <h1>🧠 MindGlass 后台管理</h1>
      <span class="subtitle">Run 历史总览 · 思维重现</span>
    </header>

    <!-- 基础指标卡 -->
    <section class="overview-cards" v-if="overview">
      <div class="card">
        <div class="card-value">{{ overview.total_runs }}</div>
        <div class="card-label">总 Run 数</div>
      </div>
      <div class="card">
        <div class="card-value">{{ (overview.answer_rate * 100).toFixed(1) }}%</div>
        <div class="card-label">完答率</div>
      </div>
      <div class="card">
        <div class="card-value" :class="{ 'card-warn': overview.no_answer_count > 0 }">{{ overview.no_answer_count }}</div>
        <div class="card-label">未完成回答</div>
      </div>
      <div class="card">
        <div class="card-value">{{ (overview.degraded_rate * 100).toFixed(1) }}%</div>
        <div class="card-label">降级率</div>
      </div>
      <div class="card">
        <div class="card-value">{{ overview.tool_error_total }}</div>
        <div class="card-label">工具失败</div>
      </div>
      <div class="card">
        <div class="card-value">{{ formatDurationMs(overview.avg_duration_ms) }}</div>
        <div class="card-label">平均耗时</div>
      </div>
    </section>

    <!-- 断连恢复指标卡 -->
    <section class="overview-cards section-title" v-if="overview">
      <h3 class="section-heading">📡 断连恢复</h3>
      <div class="card">
        <div class="card-value">{{ overview.disconnect_count }}</div>
        <div class="card-label">断连次数</div>
      </div>
      <div class="card">
        <div class="card-value">{{ overview.reconnect_count }}</div>
        <div class="card-label">重连成功</div>
      </div>
      <div class="card">
        <div class="card-value">{{ overview.resume_trigger_count }}</div>
        <div class="card-label">续跑触发</div>
      </div>
      <div class="card">
        <div class="card-value">{{ overview.resume_success_count }}</div>
        <div class="card-label">续跑成功</div>
      </div>
      <div class="card">
        <div class="card-value card-warn">{{ overview.auto_retry_exhausted_count }}</div>
        <div class="card-label">自动重试耗尽</div>
      </div>
    </section>

    <!-- 运行质量指标卡 -->
    <section class="overview-cards" v-if="overview">
      <h3 class="section-heading">🔍 运行质量</h3>
      <div class="card">
        <div class="card-value">{{ overview.interrupted_count }}</div>
        <div class="card-label">用户打断</div>
      </div>
      <div class="card">
        <div class="card-value">{{ overview.safety_interrupt_count }}</div>
        <div class="card-label">安全拦截</div>
      </div>
      <div class="card">
        <div class="card-value">{{ overview.avg_plan_rounds }}</div>
        <div class="card-label">平均决策轮数</div>
      </div>
      <div class="card">
        <div class="card-value">{{ formatDurationMs(overview.p50_duration_ms) }}</div>
        <div class="card-label">P50 耗时</div>
      </div>
      <div class="card">
        <div class="card-value">{{ formatDurationMs(overview.p95_duration_ms) }}</div>
        <div class="card-label">P95 耗时</div>
      </div>
    </section>
    <section class="overview-cards" v-else>
      <div class="card"><div class="card-value">加载中...</div></div>
    </section>

    <!-- Run 列表 -->
    <section class="run-list-section">
      <table class="run-table">
        <thead>
          <tr>
            <th>Run ID</th>
            <th>Query</th>
            <th>Final Answer</th>
            <th>节点数</th>
            <th>Plan</th>
            <th>ToolCall</th>
            <th>Observe</th>
            <th>Answer</th>
            <th>耗时</th>
            <th>降级</th>
            <th>工具错误</th>
            <th>时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in conversationGroups" :key="group.convId">
            <!-- 多轮会话：父行（首轮 query + 轮数，可展开） -->
            <template v-if="group.runs.length > 1">
              <tr class="conv-parent" @click="toggleConv(group.convId)">
                <td class="id-cell"><span class="expand-arrow">{{ expandedConvs[group.convId] ? '▼' : '▶' }}</span> <code>{{ group.runs.length }} 轮</code></td>
                <td class="query-cell">💬 {{ group.runs[0].query }}</td>
                <td class="answer-cell" :title="group.runs[group.runs.length - 1].final_answer || '无'">
                  {{ truncate(group.runs[group.runs.length - 1].final_answer || '无', 40) }}
                </td>
                <td colspan="5" class="conv-stats">
                  共 {{ group.runs.reduce((s, r) => s + r.total_nodes, 0) }} 节点
                </td>
                <td>{{ formatDurationMs(group.runs.reduce((s, r) => s + r.total_duration_ms, 0)) }}</td>
                <td>
                  <span v-if="group.runs.some(r => r.degraded)" class="badge degraded">⚠️</span>
                  <span v-else class="badge ok">✓</span>
                </td>
                <td>{{ group.runs.reduce((s, r) => s + r.tool_error_count, 0) }}</td>
                <td class="time-cell">{{ formatTime(group.runs[0].created_at) }}</td>
                <td></td>
              </tr>
              <!-- 子行：各轮 run -->
              <tr v-if="expandedConvs[group.convId]" v-for="(run, i) in group.runs" :key="run.run_id" class="conv-child">
                <td class="id-cell"><span class="turn-badge">第{{ i + 1 }}轮</span></td>
                <td class="query-cell">{{ run.query }}</td>
                <td class="answer-cell" :title="run.final_answer || '无'">
                  {{ truncate(run.final_answer || '无', 40) }}
                </td>
                <td>{{ run.total_nodes }}</td>
                <td>{{ run.plan_count }}</td>
                <td>{{ run.toolcall_count }}</td>
                <td>{{ run.observe_count }}</td>
                <td>{{ run.answer_count }}</td>
                <td>{{ formatDurationMs(run.total_duration_ms) }}</td>
                <td>
                  <span v-if="run.degraded" class="badge degraded">⚠️ 降级</span>
                  <span v-else class="badge ok">✓</span>
                </td>
                <td>{{ run.tool_error_count }}</td>
                <td class="time-cell">{{ formatTime(run.created_at) }}</td>
                <td>
                  <button class="replay-btn" @click="openReplay(run.run_id)">🔍 思维重现</button>
                </td>
              </tr>
            </template>
            <!-- 单轮会话：普通行 -->
            <tr v-else>
              <td class="id-cell"><code>{{ group.runs[0].run_id }}</code></td>
              <td class="query-cell">{{ group.runs[0].query }}</td>
              <td class="answer-cell" :title="group.runs[0].final_answer || '无'">
                {{ truncate(group.runs[0].final_answer || '无', 40) }}
              </td>
              <td>{{ group.runs[0].total_nodes }}</td>
              <td>{{ group.runs[0].plan_count }}</td>
              <td>{{ group.runs[0].toolcall_count }}</td>
              <td>{{ group.runs[0].observe_count }}</td>
              <td>{{ group.runs[0].answer_count }}</td>
              <td>{{ formatDurationMs(group.runs[0].total_duration_ms) }}</td>
              <td>
                <span v-if="group.runs[0].degraded" class="badge degraded">⚠️ 降级</span>
                <span v-else class="badge ok">✓</span>
              </td>
              <td>{{ group.runs[0].tool_error_count }}</td>
              <td class="time-cell">{{ formatTime(group.runs[0].created_at) }}</td>
              <td>
                <button class="replay-btn" @click="openReplay(group.runs[0].run_id)">🔍 思维重现</button>
              </td>
            </tr>
          </template>
          <tr v-if="runs.length === 0">
            <td colspan="13" class="empty-row">暂无数据</td>
          </tr>
        </tbody>
      </table>

      <!-- 分页 -->
      <div class="pagination" v-if="total > limit">
        <button :disabled="offset === 0" @click="loadPage(offset - limit)">← 上一页</button>
        <span class="page-info">第 {{ Math.floor(offset / limit) + 1 }} 页 / 共 {{ Math.ceil(total / limit) }} 页</span>
        <button :disabled="offset + limit >= total" @click="loadPage(offset + limit)">下一页 →</button>
      </div>
    </section>

    <!-- 思维重现弹窗 -->
    <div v-if="showReplay" class="replay-overlay" @click.self="closeReplay">
      <div class="replay-dialog">
        <div class="replay-header">
          <h2>🔍 思维重现 — {{ replayRunId }}</h2>
          <button class="close-btn" @click="closeReplay">✕</button>
        </div>
        <div class="replay-body">
          <div v-if="replayLoading" class="replay-loading">
            <p>加载中...</p>
          </div>
          <ReasoningGraph
            v-else-if="replayGraph"
            :graph="replayGraph"
            :isRunning="false"
            :cutNodeId="null"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import ReasoningGraph from '../components/ReasoningGraph.vue'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

// ── Admin 密码门（防一般人，密码硬编码在前端）──
const ADMIN_PASSWORD = 'csbt34.YDHL12S'
const AUTH_KEY = 'mindglass_admin_auth'
const authenticated = ref(false)
const passwordInput = ref('')
const authError = ref(false)

function checkPassword() {
  if (passwordInput.value === ADMIN_PASSWORD) {
    authenticated.value = true
    authError.value = false
    try { localStorage.setItem(AUTH_KEY, 'ok') } catch (e) { /* 静默 */ }
  } else {
    authError.value = true
    passwordInput.value = ''
  }
}

// 页面加载时检查是否已认证
try {
  if (localStorage.getItem(AUTH_KEY) === 'ok') {
    authenticated.value = true
  }
} catch (e) { /* 静默 */ }

// ── 指标 ──
interface Overview {
  total_runs: number
  answer_rate: number
  degraded_rate: number
  no_answer_count: number
  tool_error_total: number
  avg_duration_ms: number
}
const overview = ref<Overview | null>(null)

// ── 列表 ──
interface RunRow {
  run_id: string
  query: string
  final_answer: string | null
  total_nodes: number
  plan_count: number
  toolcall_count: number
  observe_count: number
  answer_count: number
  total_duration_ms: number
  degraded: boolean
  tool_error_count: number
  created_at: string
  conversation_id?: string
}
const runs = ref<RunRow[]>([])
const total = ref(0)
const limit = ref(20)
const offset = ref(0)

// ── 会话分组：同 conversation_id 的 run 归为一组 ──
interface ConvGroup {
  convId: string
  runs: RunRow[]  // 组内按轮次升序（时间早→晚）
}

const conversationGroups = computed<ConvGroup[]>(() => {
  const groups = new Map<string, RunRow[]>()
  const order: string[] = []
  for (const r of runs.value) {
    const cid = r.conversation_id || r.run_id
    if (!groups.has(cid)) {
      groups.set(cid, [])
      order.push(cid)
    }
    groups.get(cid)!.push(r)
  }
  return order.map(cid => ({
    convId: cid,
    // runs 列表是时间倒序，组内反转为轮次正序
    runs: [...groups.get(cid)!].reverse(),
  }))
})

const expandedConvs = ref<Record<string, boolean>>({})

function toggleConv(convId: string) {
  expandedConvs.value[convId] = !expandedConvs.value[convId]
}

// ── 思维重现 ──
const showReplay = ref(false)
const replayRunId = ref('')
const replayGraph = ref<any>(null)
const replayLoading = ref(false)

async function loadOverview() {
  try {
    const res = await fetch(`${API_BASE}/admin/overview`)
    overview.value = await res.json()
  } catch (e) {
    console.error('加载 overview 失败:', e)
  }
}

async function loadRuns() {
  try {
    const res = await fetch(`${API_BASE}/admin/runs?limit=${limit.value}&offset=${offset.value}`)
    const data = await res.json()
    runs.value = data.runs || []
    total.value = data.total || 0
  } catch (e) {
    console.error('加载 runs 失败:', e)
  }
}

function loadPage(newOffset: number) {
  offset.value = Math.max(0, newOffset)
  loadRuns()
}

async function openReplay(runId: string) {
  replayRunId.value = runId
  replayGraph.value = null
  replayLoading.value = true
  showReplay.value = true

  try {
    const res = await fetch(`${API_BASE}/admin/runs/${runId}`)
    const snapshot = await res.json()
    replayGraph.value = {
      nodes: snapshot.nodes || [],
      edges: snapshot.edges || [],
      branches: snapshot.branches || [],
      meta: snapshot.meta || {},
    }
  } catch (e) {
    console.error('加载快照失败:', e)
  } finally {
    replayLoading.value = false
  }
}

function closeReplay() {
  showReplay.value = false
  replayGraph.value = null
  replayRunId.value = ''
}

function truncate(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s
  return s.slice(0, maxLen) + '...'
}

function formatDurationMs(ms: number): string {
  if (!ms || ms === 0) return '0ms'
  if (ms < 1000) return `${ms.toFixed(0)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatTime(iso: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(() => {
  loadOverview()
  loadRuns()
})
</script>

<style scoped>
/* ── Admin 密码门 ── */
.auth-gate {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0a0e1f;
}
.auth-box {
  text-align: center;
  padding: 40px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 16px;
  backdrop-filter: blur(16px);
}
.auth-box h2 {
  color: #e0e0e0;
  margin-bottom: 8px;
}
.auth-hint {
  color: #888;
  font-size: 13px;
  margin-bottom: 20px;
}
.auth-box input {
  padding: 10px 16px;
  font-size: 15px;
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 8px;
  background: rgba(255,255,255,0.08);
  color: #fff;
  outline: none;
  width: 200px;
  margin-bottom: 12px;
}
.auth-box input:focus {
  border-color: #a78bfa;
}
.auth-box button {
  padding: 10px 24px;
  font-size: 15px;
  border: none;
  border-radius: 8px;
  background: #a78bfa;
  color: #fff;
  cursor: pointer;
}
.auth-box button:hover {
  background: #8b6fe0;
}
.auth-error {
  color: #ff7875;
  font-size: 13px;
  margin-top: 12px;
}
.admin-page {
  min-height: 100vh;
  background: #f5f7fa;
}

.admin-header {
  background: #fff;
  padding: 12px 24px;
  border-bottom: 1px solid #e8e8e8;
  display: flex;
  align-items: center;
  gap: 16px;
}

.back-link {
  padding: 4px 12px;
  background: #f0f0f0;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  font-size: 13px;
  color: #555;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.2s;
}

.back-link:hover {
  background: #e8e8e8;
  color: #333;
}

.admin-header h1 {
  font-size: 20px;
  color: #1a1a2e;
}

.subtitle {
  font-size: 13px;
  color: #888;
}

/* 指标卡 */
.overview-cards {
  display: flex;
  gap: 16px;
  padding: 20px 24px;
  flex-wrap: wrap;
}

.card {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 16px 24px;
  min-width: 140px;
  text-align: center;
}

.card-value {
  font-size: 24px;
  font-weight: 600;
  color: #1a1a2e;
}

.card-label {
  font-size: 12px;
  color: #888;
  margin-top: 4px;
}

.card-value.card-warn {
  color: #e74c3c;
}

.section-heading {
  width: 100%;
  font-size: 14px;
  font-weight: 600;
  color: #555;
  margin: 0 0 -8px;
  padding-bottom: 4px;
  border-bottom: 1px solid #eee;
}

/* 表格 */
.run-list-section {
  padding: 0 24px 24px;
}

.run-table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

.run-table th {
  background: #fafafa;
  padding: 10px 12px;
  font-size: 12px;
  color: #666;
  text-align: left;
  border-bottom: 1px solid #e8e8e8;
  white-space: nowrap;
}

.run-table td {
  padding: 8px 12px;
  font-size: 13px;
  border-bottom: 1px solid #f0f0f0;
  vertical-align: middle;
}

.run-table tr:hover td {
  background: #f9f9f9;
}

/* 会话分组：父行/子行 */
.run-table tr.conv-parent {
  cursor: pointer;
  background: #faf7ff;
}
.run-table tr.conv-parent:hover td {
  background: #f3edff;
}
.expand-arrow {
  font-size: 10px;
  color: #8b6ff0;
}
.conv-stats {
  color: #888;
  font-size: 12px;
}
.run-table tr.conv-child td {
  background: #fcfcfe;
}
.run-table tr.conv-child:hover td {
  background: #f5f3fb;
}
.turn-badge {
  display: inline-block;
  background: #efe9ff;
  color: #8b6ff0;
  border-radius: 4px;
  font-size: 11px;
  padding: 2px 6px;
  white-space: nowrap;
}

.id-cell code {
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}

.query-cell {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.answer-cell {
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #555;
}

.time-cell {
  white-space: nowrap;
  color: #888;
  font-size: 12px;
}

.empty-row {
  text-align: center;
  padding: 24px;
  color: #888;
}

/* Badge */
.badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
}

.badge.ok {
  background: #e8f5e9;
  color: #2e7d32;
}

.badge.degraded {
  background: #fff3e0;
  color: #e65100;
}

/* 重现按钮 */
.replay-btn {
  padding: 4px 10px;
  background: #5b9bd5;
  border: 1px solid #5b9bd5;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s;
  white-space: nowrap;
}

.replay-btn:hover {
  background: #4a89c4;
}

/* 分页 */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 16px;
}

.pagination button {
  padding: 6px 16px;
  background: #fff;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  color: #333;
}

.pagination button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pagination button:hover:not(:disabled) {
  background: #f0f0f0;
}

.page-info {
  font-size: 13px;
  color: #888;
}

/* 弹窗 */
.replay-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.replay-dialog {
  background: #fff;
  border-radius: 8px;
  width: 90%;
  height: 85vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.replay-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid #e8e8e8;
}

.replay-header h2 {
  font-size: 16px;
  color: #1a1a2e;
}

.close-btn {
  padding: 4px 12px;
  background: #ff4d4f;
  border: 1px solid #ff4d4f;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  color: #fff;
  transition: all 0.2s;
}

.close-btn:hover {
  background: #ff7875;
}

.replay-body {
  flex: 1;
  overflow: hidden;
}

.replay-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #888;
}

/* ═══ 手机端响应式适配 ═══ */
@media (max-width: 767px) {
  .admin-page {
    min-height: 100vh;
  }

  .admin-header {
    flex-wrap: wrap;
    padding: 10px 14px;
    gap: 8px;
  }

  .admin-header h1 {
    font-size: 17px;
  }

  .subtitle {
    font-size: 11px;
    width: 100%;
    order: 10;
  }

  .back-link {
    font-size: 14px;
    padding: 6px 14px;
  }

  /* 指标卡纵向排列 */
  .overview-cards {
    padding: 12px 14px;
    gap: 10px;
  }

  .card {
    min-width: 0;
    flex: 1 1 calc(50% - 5px);
    padding: 12px 16px;
  }

  .card-value {
    font-size: 20px;
  }

  .card-label {
    font-size: 11px;
  }

  /* 表格横向滚动 */
  .run-list-section {
    padding: 0 10px 20px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .run-table {
    min-width: 900px; /* 保证表格不被压缩 */
  }

  .run-table th,
  .run-table td {
    padding: 8px 8px;
    font-size: 12px;
  }

  /* 分页适配 */
  .pagination {
    flex-wrap: wrap;
    padding: 12px;
    gap: 10px;
  }

  .pagination button {
    padding: 8px 14px;
    font-size: 14px;
  }

  .page-info {
    font-size: 12px;
    width: 100%;
    text-align: center;
  }

  /* 弹窗全屏 */
  .replay-overlay {
    padding: 0;
  }

  .replay-dialog {
    width: 100%;
    height: 100%;
    border-radius: 0;
  }

  .replay-header {
    padding: 10px 14px;
  }

  .replay-header h2 {
    font-size: 14px;
  }

  .close-btn {
    font-size: 13px;
    padding: 6px 12px;
  }
}
</style>
