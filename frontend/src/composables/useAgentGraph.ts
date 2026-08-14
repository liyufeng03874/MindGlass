import {ref} from 'vue'
import type {AgentNode, ReasoningGraph, SSEEvent, LeftBlock, Round} from '@/types/agent'

// API 地址：生产环境通过 nginx 反代 /api，开发环境可覆盖 VITE_API_BASE_URL
const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

// ── localStorage 重连 key ──
const STORAGE_RUN_ID = 'mindglass_run_id'
const STORAGE_ROUNDS = 'mindglass_rounds'

let pendingIdCounter = 0

// ── Block 标题映射 ──
const BLOCK_TITLES: Record<string, string> = {
  Plan: '🧠 正在规划...',
  Observe: '🔍 评估中...',
  Answer: '💬 生成回答...',
}

function nodeTypeToBlockType(nodeType: string): LeftBlock['type'] {
  const map: Record<string, LeftBlock['type']> = {
    Plan: 'plan',
    ToolCall: 'toolcall',
    Observe: 'observe',
    Answer: 'answer',
  }
  return map[nodeType] || 'plan'
}

export function useAgentGraph() {
  const graph = ref<ReasoningGraph>({
    nodes: [],
    edges: [],
    branches: [],
    meta: { current_step_index: 0, total_steps: 0, query: '', run_id: '' },
  })

  // ── localStorage 重连：推理进行中持久化 runId，刷新/误关后可恢复 ──
  function saveRunId(runId: string) {
    if (runId) {
      try { localStorage.setItem(STORAGE_RUN_ID, runId) } catch (e) { /* 静默 */ }
    }
  }
  function clearRunId() {
    try { localStorage.removeItem(STORAGE_RUN_ID) } catch (e) { /* 静默 */ }
  }
  function getPendingRunId(): string | null {
    try { return localStorage.getItem(STORAGE_RUN_ID) } catch (e) { return null }
  }

  // ── localStorage 缓存 rounds（左侧聊天区），刷新后恢复 ──
  function saveRounds() {
    try {
      localStorage.setItem(STORAGE_ROUNDS, JSON.stringify(rounds.value))
    } catch (e) { /* 静默：quota exceeded 等 */ }
  }
  function restoreRounds(): boolean {
    try {
      const raw = localStorage.getItem(STORAGE_ROUNDS)
      if (!raw) return false
      const parsed = JSON.parse(raw) as Round[]
      if (Array.isArray(parsed) && parsed.length > 0) {
        rounds.value = parsed
        return true
      }
      return false
    } catch (e) { return false }
  }
  function clearRoundsCache() {
    try { localStorage.removeItem(STORAGE_ROUNDS) } catch (e) { /* 静默 */ }
  }

  /** 上报运维事件到后端（断连/重连/续跑/自动重试失败等），静默失败不影响主流程 */
  function logEvent(eventType: string, detail: string = '') {
    const runId = graph.value?.meta?.run_id || ''
    const convId = graph.value?.meta?.conversation_id || ''
    fetch(`${API_BASE}/api/events/log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: eventType, run_id: runId, conversation_id: convId, detail }),
    }).catch(() => { /* 静默失败 */ })
  }

  const status = ref('')
  const connected = ref(false)
  const isRunning = ref(false)
  /** SSE 断连标记：true 时本地图保留、流程图显示重连按钮 */
  const disconnected = ref(false)
  /** 自动重连中：true 时按钮显示“正在尝试重连”且不可点击 */
  const autoRetrying = ref(false)
  /** 自动重连已尝试次数（0-3），用于按钮文案展示 */
  const autoRetryCount = ref(0)

  /** 轮次数组：每轮 = 用户 query + 本轮后端推送的事件 blocks + 最终回答 */
  const rounds = ref<Round[]>([])
  let roundCounter = 0

  /** 会话 ID：同一次页面会话内的多轮 run 共享，清空页面时重置（新会话） */
  let conversationId: string | null = null

  /** 当前轮（最近一轮，SSE 事件都写进它） */
  function currentBlocks(): LeftBlock[] {
    if (rounds.value.length === 0) {
      // 兑底：没有轮次时先造一个（demo/异常场景）
      roundCounter++
      rounds.value.push({ id: `round_${roundCounter}`, query: '', blocks: [] })
    }
    return rounds.value[rounds.value.length - 1].blocks
  }

  function currentRound(): Round {
    currentBlocks()
    return rounds.value[rounds.value.length - 1]
  }

  /** 清空所有轮次（页面清空用），同时开启新会话 */
  function clearRounds() {
    rounds.value = []
    conversationId = null
    clearRoundsCache()
  }

  /** 截断点节点（打断后只有它能点重试；重试或新查询后清空） */
  const cutNode = ref<AgentNode | null>(null)

  /** 已收到 interrupted 事件 */
  let interruptedReceived = false
  /** 重试分支标记：重试开始后的新 block 标记 phase=retry（左侧样式区分） */
  let inRetryBranch = false

  /** 从完整图快照提取最终回答（恢复/复用共用） */
  function finalAnswerOf(nodes: AgentNode[]): string {
    const ans = [...nodes].reverse().find(n => n.type === 'Answer' && n.status === 'done')
    return (ans?.data?.output as string) || ''
  }

  /** 断连恢复：页面加载时探测 /api/graph（后端内存空时会从 Redis 重建）。
   *  有图就渲染 + 左侧补一轮对话记录；无图/后端不在线静默返回 false。 */
  async function tryRestoreFromCache(): Promise<boolean> {
    try {
      const resp = await fetch(`${API_BASE}/api/graph`)
      if (!resp.ok) return false
      const snapshot = await resp.json()
      if (!snapshot?.nodes || snapshot.nodes.length === 0) return false
      graph.value = snapshot as ReasoningGraph
      // 只恢复图到右侧思维面板，不往聊天区 push rounds（保持开场白干净）
      connected.value = true
      status.value = '📡 已从缓存恢复上一次的思维图，点「💡思维」查看'
      return true
    } catch (e) {
      return false
    }
  }

  /** 高频 query 复用检查：语义相似命中时直接渲染旧图，不发起新 run。
   *  任何异常（后端没起/向量化服务不在线）都返回 null → 照常新 run。 */
  async function checkReuse(query: string) {
    try {
      const resp = await fetch(`${API_BASE}/api/reuse/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      })
      if (!resp.ok) return null
      const r = await resp.json()
      return r?.hit ? r : null
    } catch (e) {
      return null
    }
  }

  async function sendMessage(query: string) {
    // 先立刻显示用户气泡 + 助手"规划中"占位，不让用户以为卡了
    roundCounter++
    const currentRoundId = `round_${roundCounter}`
    rounds.value.push({ id: currentRoundId, query, blocks: [{ id: 'placeholder_plan', nodeId: '', type: 'plan', status: 'loading', title: '🤔 规划中...', content: '' }] })

    // ── 复用检查：语义相似的已缓存思维图直接渲染，不重跑 ──
    const reuse = await checkReuse(query)
    if (reuse && reuse.graph?.nodes?.length) {
      // 命中复用，更新已 push 的轮次
      const r = rounds.value.find(r => r.id === currentRoundId)
      if (r) r.answer = finalAnswerOf(reuse.graph.nodes)
      graph.value = reuse.graph as ReasoningGraph
      if (!conversationId) {
        conversationId = `conv_${new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)}`
      }
      connected.value = true
      status.value = `♻️ 命中相似问题缓存（相似度 ${reuse.similarity}），复用已有思维图`
      // 复用命中 = 推理已完成，清 pending 标记 + 保存最终 rounds
      clearRunId()
      saveRounds()
      return
    }

    // 提取历史对话（最近 3 轮，每条截 200 字）——在新轮入队前取
    const history = rounds.value.flatMap(r => {
      const pair: Array<{ role: string, content: string }> = [
        { role: 'user', content: r.query.slice(0, 200) },
      ]
      if (r.answer) pair.push({ role: 'assistant', content: r.answer.slice(0, 200) })
      return pair
    }).slice(-6)

    // 首轮生成会话 ID，后续轮复用（多轮对话关联）
    if (!conversationId) {
      conversationId = `conv_${new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)}`
    }

    status.value = '🤔 连接中...'
    connected.value = true
    isRunning.value = true
    cutNode.value = null
    interruptedReceived = false
    inRetryBranch = false

    // ── localStorage 重连：推理开始即标记 pending，刷新/误关后可恢复 ──
    saveRunId('pending')
    // 新轮次入队后立即缓存（handleEvent 之前就有内容了）
    saveRounds()

    // 重置图状态
    graph.value = {
      nodes: [],
      edges: [],
      branches: [],
      meta: { current_step_index: 0, total_steps: 0, query: '', run_id: '' },
    }
    // 立即显示 pending "规划中..." 节点
    pendingIdCounter++
    graph.value.nodes.push({
      id: `frontend_pending_${pendingIdCounter}`,
      type: 'Plan',
      data: { pending: true, label: '规划中...' },
      status: 'pending',
      step_index: 0,
      branch_id: null,
      label: '规划中...',
    })

    // 提取历史对话（最近 3 轮，每条截 200 字）——在新轮入队前取

    // 用 fetch POST 发送请求（EventSource 只支持 GET，URL 长度有限制）
    fetch(`${API_BASE}/api/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, history, conversation_id: conversationId }),
    }).then(async response => {
      if (!response.ok || !response.body) {
        console.error('Run failed:', response.status)
        return
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        // 60s 超时：没收到数据就标记断连
        const readPromise = reader.read()
        const timeoutPromise = new Promise<{ timedOut: true }>((resolve) =>
          setTimeout(() => resolve({ timedOut: true }), 60000)
        )
        const result = await Promise.race([readPromise, timeoutPromise])

        if ('timedOut' in result) {
          // 60 秒没数据 → SSE 断连
          // 关键：保留本地图（含 pending 预测节点），不拉 Redis 覆盖
          connected.value = false
          isRunning.value = false

          // 本地 orphan pending 节点标灰
          for (const node of graph.value.nodes) {
            if (node.status === 'pending') {
              node.status = 'discarded'
              node.label = (node.label || '') + '（已中断）'
            }
          }
          graph.value.nodes = [...graph.value.nodes]

          // 当前轮 loading block 标记 done
          for (const block of currentBlocks()) {
            if (block.status === 'loading') block.status = 'done'
          }

          // ── 自动重连：每 30 秒尝试一次，最多 3 次失败后显示手动按钮 ──
          const MAX_AUTO_RETRIES = 3
          let autoRetryTimer: ReturnType<typeof setInterval> | null = null

          // 上报断连事件
          logEvent('disconnect', `SSE timeout at step ${graph.value.meta?.current_step_index}`)

          // 进入自动重连状态
          autoRetrying.value = true
          autoRetryCount.value = 0
          disconnected.value = false  // 自动重连期间不显示手动按钮

          const tryAutoReconnect = async () => {
            autoRetryCount.value++
            status.value = `🔄 正在恢复连接 (${autoRetryCount.value}/${MAX_AUTO_RETRIES})...`
            try {
              const probe = await fetch(`${API_BASE}/api/health`)
              if (probe.ok) {
                // 后端恢复了，停止定时器，执行重连
                if (autoRetryTimer) { clearInterval(autoRetryTimer); autoRetryTimer = null }
                autoRetrying.value = false
                logEvent('reconnect', `auto_retry_${autoRetryCount.value}`)
                // 关键：reconnect() 内部有 if (!disconnected.value) return 守卫
                // 自动重连期间 disconnected 被设为 false（隐藏手动按钮），
                // 必须先置 true 才能让 reconnect() 正常执行增量合并+续跑
                disconnected.value = true
                await reconnect()
                return
              }
            } catch (e) { /* 后端还没起来 */ }

            if (autoRetryCount.value >= MAX_AUTO_RETRIES) {
              // 3 次都失败 → 切换为手动重连模式
              if (autoRetryTimer) { clearInterval(autoRetryTimer); autoRetryTimer = null }
              autoRetrying.value = false
              disconnected.value = true
              logEvent('auto_retry_exhausted', `3 retries failed`)
              status.value = '📡 连接断开 · 点击图中按钮重连'
            }
          }

          // 立即尝试第一次
          await tryAutoReconnect()
          // 如果还没成功且没超限，启动定时器
          if (!connected.value && autoRetryCount.value < MAX_AUTO_RETRIES) {
            autoRetryTimer = setInterval(async () => {
              if (connected.value) { clearInterval(autoRetryTimer!); return }
              await tryAutoReconnect()
              if (connected.value || autoRetryCount.value >= MAX_AUTO_RETRIES) {
                clearInterval(autoRetryTimer!)
              }
            }, 30000)
          }

          break  // 旧 stream 已断，结束 readLoop
        }

        const { done, value } = result
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const parsed = JSON.parse(line.slice(6)) as SSEEvent
              handleEvent(parsed)
            } catch (e) {
              // 忽略解析错误
            }
          }
        }
      }
    }).catch(async (err) => {
      console.error('Run error:', err)
      // SSE reader 抛网络错误（后端被杀/网络断开）→ 也记一次断连
      // timeout 路径已在上面单独上报，这里只补网络异常的情况
      if (connected.value) {
        connected.value = false
        isRunning.value = false
        for (const node of graph.value.nodes) {
          if (node.status === 'pending') {
            node.status = 'discarded'
            node.label = (node.label || '') + '（已中断）'
          }
        }
        graph.value.nodes = [...graph.value.nodes]
        for (const block of currentBlocks()) {
          if (block.status === 'loading') block.status = 'done'
        }
        logEvent('disconnect', `network_error: ${err?.message || 'unknown'}`)
        // 进入自动重连（复用同一逻辑）
        autoRetrying.value = true
        autoRetryCount.value = 0
        disconnected.value = false
        const MAX_AUTO_RETRIES = 3
        let autoRetryTimer: ReturnType<typeof setInterval> | null = null
        const tryAutoReconnect = async () => {
          autoRetryCount.value++
          status.value = `🔄 正在恢复连接 (${autoRetryCount.value}/${MAX_AUTO_RETRIES})...`
          try {
            const probe = await fetch(`${API_BASE}/api/health`)
            if (probe.ok) {
              if (autoRetryTimer) { clearInterval(autoRetryTimer); autoRetryTimer = null }
              autoRetrying.value = false
              logEvent('reconnect', `auto_retry_${autoRetryCount.value}`)
              disconnected.value = true
              await reconnect()
              return
            }
          } catch (e) { /* 后端还没起来 */ }
          if (autoRetryCount.value >= MAX_AUTO_RETRIES) {
            if (autoRetryTimer) { clearInterval(autoRetryTimer); autoRetryTimer = null }
            autoRetrying.value = false
            disconnected.value = true
            logEvent('auto_retry_exhausted', `3 retries failed`)
            status.value = '📡 连接断开 · 点击图中按钮重连'
          }
        }
        await tryAutoReconnect()
        if (!connected.value && autoRetryCount.value < MAX_AUTO_RETRIES) {
          autoRetryTimer = setInterval(async () => {
            if (connected.value) { clearInterval(autoRetryTimer!); return }
            await tryAutoReconnect()
            if (connected.value || autoRetryCount.value >= MAX_AUTO_RETRIES) {
              clearInterval(autoRetryTimer!)
            }
          }, 30000)
        }
      }
    })
  }

  /** 打断当前运行：通知后端设中断标志，后端收尾后发 interrupted 事件 */
  async function interrupt(node: AgentNode) {
    if (!isRunning.value) return
    cutNode.value = node
    status.value = '✂️ 正在打断...'
    try {
      const resp = await fetch(`${API_BASE}/api/interrupt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step_index: node.step_index }),
      })
      const body = await resp.json().catch(() => ({}))
      // 后端无活跃 run（回答已生成完毕才点到截断）：明确告知而非静默
      if (body && body.status === 'no_active_run') {
        cutNode.value = null
        status.value = '回答已完成，本次无需打断'
      }
    } catch (e) {
      status.value = '❌ 打断请求失败'
      cutNode.value = null
    }
  }

  /** 清除截断点状态（清空页面用） */
  function clearCut() {
    cutNode.value = null
  }

  function handleEvent(event: SSEEvent) {
    // console.log('[SSE]', event.type, event.data)

    // ── localStorage 重连：首次拿到具体 run_id 时更新 pending 标记 ──
    const currentRunId = graph.value?.meta?.run_id
    if (currentRunId && getPendingRunId() === 'pending') {
      saveRunId(currentRunId)
    }

    // 标记本轮是否需要保存 rounds（结束事件清除缓存后不再保存）
    let shouldSaveRounds = true

    switch (event.type) {
      case 'status':
        status.value = event.data.message
        break

      case 'node_streaming': {
        // 流式内容追加到当前轮的 blocks
        const { node_id, node_type, content, is_complete, chunk } = event.data
        const blockType = nodeTypeToBlockType(node_type)
        const blockId = `block_${node_id}`
        const title = BLOCK_TITLES[node_type] || node_type

        const blocks = currentBlocks()
        // 清掉占位 block（用户发消息时加的"规划中"）
        const placeholderIdx = blocks.findIndex(b => b.id === 'placeholder_plan')
        if (placeholderIdx >= 0) blocks.splice(placeholderIdx, 1)
        let block = blocks.find((b: LeftBlock) => b.id === blockId)
        if (!block) {
          block = {
            id: blockId,
            nodeId: node_id,
            type: blockType,
            status: 'loading',
            title,
            content: '',
            phase: inRetryBranch ? 'retry' : undefined,
          }
          blocks.push(block)
        }
        // chunk 里的报错提示（后端异常时会塞在 chunk 里）拼进 content，不让错误被静默吞掉
        if (typeof chunk === 'string' && (chunk.startsWith('[流式调用出错') || chunk.startsWith('[LLM 流式调用超时'))) {
          block.content = (block.content || '') + chunk
          block.status = 'error'
        } else {
          block.content = content  // 用 content 直接覆盖（累计全文）
        }
        if (is_complete) {
          block.status = 'done'
          block.title = title.replace('正在', '').replace('中...', '完成')
        }
        break
      }

      case 'node_complete': {
        const node = event.data.node as AgentNode

        // 后端返回完整图，直接覆盖
        if (event.data.graph?.nodes) {
          const backendNodes = event.data.graph.nodes
          const oldPendings = graph.value.nodes.filter(n => n.status === 'pending')

          // pending 存活规则：后端图推进后，step_index <= 后端最大 step 的 pending 全部清除
          const maxBackendStep = backendNodes.reduce(
            (m, n) => Math.max(m, n.step_index ?? 0), 0
          )
          const survivingPendings = oldPendings.filter(
            p => (p.step_index ?? 0) > maxBackendStep
          )

          const survivingPendingIds = new Set(survivingPendings.map(n => n.id))
          const survivingEdges = graph.value.edges.filter(
            e => survivingPendingIds.has(e.from) || survivingPendingIds.has(e.to)
          )

          graph.value.nodes = [...backendNodes, ...survivingPendings]
          graph.value.edges = [...(event.data.graph.edges || []), ...survivingEdges]
        } else {
          graph.value.nodes.push(node)
          const activeNodes = graph.value.nodes.filter(
            n => n.status !== 'branch' && n.status !== 'discarded' && n.id !== node.id
          )
          if (activeNodes.length > 0) {
            const prevNode = activeNodes[activeNodes.length - 1]
            graph.value.edges.push({
              from: prevNode.id,
              to: node.id,
              type: 'Normal',
            })
          }
        }

        // ToolCall 类型 → 填充当前轮 blocks 的 metadata（toolName/params/resultPreview）
        if (node.type === 'ToolCall') {
          const blockType: LeftBlock['type'] = 'toolcall'
          const blockId = `block_${node.id}`
          const blocks = currentBlocks()
          // 清掉占位 block
          const placeholderIdx = blocks.findIndex(b => b.id === 'placeholder_plan')
          if (placeholderIdx >= 0) blocks.splice(placeholderIdx, 1)
          let block = blocks.find((b: LeftBlock) => b.id === blockId)

          // 后端 node_complete 事件将 tool_name/params/result_preview/result_full 放在 event.data 顶层
          const toolName = event.data.tool_name || node.data?.tool || ''
          const params = event.data.params || node.data?.params
          const resultPreview = event.data.result_preview || ''
          // 任务⑦：完整结果 JSON 字符串——左侧人读视图直接用，避免 500 字符截断
          const resultFull = event.data.result_full || ''

          if (!block) {
            block = {
              id: blockId,
              nodeId: node.id,
              type: blockType,
              status: node.status === 'error' ? 'error' : 'done',
              title: `🔧 调用工具: ${toolName || '未知'}`,
              content: '',
              metadata: {
                toolName,
                params,
                resultPreview,
                resultFull,
              },
              parallelGroupId: node.data?.parallel_group_id,
              phase: inRetryBranch ? 'retry' : undefined,
            }
            blocks.push(block)
          } else {
            block.status = node.status === 'error' ? 'error' : 'done'
            // 后端补发 node_complete（branch/replaced 标记等）时不带 result 字段，
            // 空值不能覆盖已有结果，否则已有结果的卡片会退化成"无结果"（问题2）
            block.metadata = {
              toolName: toolName || block.metadata?.toolName || '',
              params: params ?? block.metadata?.params,
              resultPreview: resultPreview || block.metadata?.resultPreview || '',
              resultFull: resultFull || block.metadata?.resultFull || '',
            }
          }
          // 废弃节点（branch/replaced/discarded）在左侧聊天置灰（问题2）
          if (node.status === 'branch' || node.status === 'replaced' || node.status === 'discarded') {
            block.phase = 'cut'
          }
        }

        // 非 ToolCall 节点（observe/plan/answer）废弃时同样置灰对应 block（问题2）
        if (node.status === 'branch' || node.status === 'replaced' || node.status === 'discarded') {
          const anyBlock = currentBlocks().find((bb: LeftBlock) => bb.id === `block_${node.id}`)
          if (anyBlock) anyBlock.phase = 'cut'
        }

        // v2 预测逻辑：
        //   Plan   → 待决策（Plan 之后不确定是 ToolCall 还是 Answer）
        //   ToolCall → Observe（固定）
        //   Observe  → Plan（固定，Observe 之后一定是 Plan）
        // 只对活跃节点做预测——废弃/替换节点不产生预测，避免瞬态幽灵节点
        const isActiveForPredict =
          node.status !== 'branch' && node.status !== 'replaced' && node.status !== 'discarded'
        if (isActiveForPredict) {
          if (node.type === 'Plan') {
            pushPendingDecision(node)
          } else if (node.type === 'ToolCall') {
            pushPendingObserve(node)
          } else if (node.type === 'Observe') {
            pushPendingPlan(node)
          }
        }

        if (node.type === 'Answer' && node.status !== 'replaced') {
          // 安全拦截的 Answer 不重复推送（safety_interrupt 事件已推送过）
          if (!node.data?.safety_interrupt) {
            currentRound().answer = node.data.output
            status.value = '✅ 完成'
          } else {
            status.value = '⚠️ 安全策略拦截'
          }
          isRunning.value = false
        } else {
          status.value = `已生成 ${node.type} 节点`
        }
        break
      }

      case 'run_complete': {
        clearRunId()
        clearRoundsCache()
        shouldSaveRounds = false
        connected.value = false
        isRunning.value = false
        cutNode.value = null
        if (event.data.graph) {
          console.log('[Run Complete] edges:', JSON.stringify(event.data.graph.edges, null, 2))
          graph.value = event.data.graph as ReasoningGraph
          console.log('[Run Complete]', graph.value.nodes.length, 'nodes', graph.value.edges.length, 'edges')
        }
        // 当前轮所有 loading 的 block 标记为 done（run_complete 时确保状态正确）
        for (const block of currentBlocks()) {
          if (block.status === 'loading') {
            block.status = 'done'
          }
        }
        break
      }

      case 'interrupted': {
        clearRunId()
        clearRoundsCache()
        shouldSaveRounds = false
        // 用户打断：后端已完成收尾（截断点后置灰），前端收束
        interruptedReceived = true
        if (event.data.graph) {
          graph.value = event.data.graph as ReasoningGraph
        }
        const graphNodes = ((event.data.graph?.nodes as any[]) || [])
        // 从物化节点的 data 里取已物化内容（问题B修复）：
        // Answer→output 文本，Plan→output/reasoning，Observe→结构化 observe_output
        const blockContentFromNode = (n: any): string => {
          const d = n.data || {}
          if (n.type === 'Answer') return typeof d.output === 'string' ? d.output : ''
          if (n.type === 'Plan') return (typeof d.output === 'string' && d.output) || (typeof d.reasoning === 'string' && d.reasoning) || ''
          if (n.type === 'Observe') return d.observe_output ? JSON.stringify(d.observe_output) : (typeof d.summary === 'string' ? d.summary : '')
          return ''
        }
        // 当前轮还在 loading 的流式 block 标记结束；被废弃的 block 标记 phase=cut（置灰）
        const roundBlocks = currentBlocks()
        const interruptedIds = new Set(
          (graphNodes)
            .filter((n: any) => n.data?.interrupted
              || n.status === 'replaced' || n.status === 'branch' || n.status === 'discarded')
            .map((n: any) => n.id)
        )
        for (const block of roundBlocks) {
          if (block.status === 'loading') block.status = 'done'
          if (interruptedIds.has(block.nodeId)) {
            block.phase = 'cut'
            // 打断早于首个 chunk 到达时流式 block 内容为空——用物化内容回填，不显示"等待内容"
            if (!block.content) {
              const srcNode = graphNodes.find((n: any) => n.id === block.nodeId)
              if (srcNode) block.content = blockContentFromNode(srcNode)
            }
          }
        }
        // 未流式过的废弃节点（如被打断时还没出现的决策/回答）补成置灰 block，
        // 让左侧聊天完整呈现"被打断侧"的后续链（问题2）
        const existingIds = new Set(roundBlocks.map(b => b.nodeId))
        const missedNodes = graphNodes
          .filter((n: any) => (n.status === 'replaced' || n.status === 'branch')
            && !existingIds.has(n.id)
            && ['Plan', 'Observe', 'Answer', 'ToolCall'].includes(n.type))
          .sort((a: any, b: any) => (a.step_index ?? 0) - (b.step_index ?? 0))
        for (const n of missedNodes) {
          roundBlocks.push({
            id: `block_${n.id}`,
            nodeId: n.id,
            type: nodeTypeToBlockType(n.type),
            status: 'done',
            title: n.label || BLOCK_TITLES[n.type] || n.type,
            // 问题B修复：从 node.data 带出已物化内容，不再留空导致"等待内容"
            content: blockContentFromNode(n),
            phase: 'cut',
            metadata: n.type === 'ToolCall' && n.data?.result !== undefined
              ? {
                  toolName: n.data?.tool || '',
                  params: n.data?.params,
                  resultPreview: typeof n.data.result_preview === 'string' ? n.data.result_preview : '',
                  resultFull: typeof n.data.result === 'string' ? n.data.result : JSON.stringify(n.data.result),
                }
              : undefined,
          })
        }
        // 分割线：打断边界
        roundBlocks.push({
          id: `divider_cut_${Date.now()}`,
          nodeId: '',
          type: 'divider',
          status: 'done',
          title: '✂️ 在此打断',
          content: '',
        })
        status.value = '⏸ 已打断 · 在截断点可重试'
        isRunning.value = false
        connected.value = false
        break
      }

      case 'safety_interrupt': {
        clearRunId()
        clearRoundsCache()
        shouldSaveRounds = false
        // 安全策略拦截：清空当前回答，显示拦截提示
        const interruptText = event.data.text || '很抱歉，该回答包含不合规内容，已被安全策略拦截。'
        // 清空当前轮 Answer block 的内容，替换为拦截提示
        const answerBlock = currentBlocks().find((b: LeftBlock) => b.type === 'answer')
        if (answerBlock) {
          answerBlock.content = interruptText
          answerBlock.status = 'error'
          answerBlock.title = '⚠️ 安全拦截'
        }
        // 回答气泡也显示拦截提示
        currentRound().answer = `⚠️ ${interruptText}`
        status.value = '⚠️ 安全策略拦截'
        isRunning.value = false
        connected.value = false
        break
      }

      case 'error':
        clearRunId()
        clearRoundsCache()
        shouldSaveRounds = false
        status.value = `❌ 错误: ${event.data.message}`
        connected.value = false
        isRunning.value = false
        break
    }

    // ── 每个 SSE 事件处理后，同步缓存 rounds 到 localStorage（结束事件已清除缓存则跳过）──
    if (shouldSaveRounds) {
      saveRounds()
    }
  }

  // ── v2 pending 节点推送 ──

  /** 通用 pending 推送 */
  function pushPending(prevNode: AgentNode, type: AgentNode['type'], label: string) {
    pendingIdCounter++
    const pendingNode: AgentNode = {
      id: `frontend_pending_${pendingIdCounter}`,
      type,
      data: { pending: true, label },
      status: 'pending',
      step_index: prevNode.step_index + 1,
      branch_id: prevNode.branch_id,
      label,
    }
    graph.value.nodes.push(pendingNode)
    graph.value.edges.push({
      from: prevNode.id,
      to: pendingNode.id,
      type: 'Pending',
    })
    graph.value.nodes = [...graph.value.nodes]
    graph.value.edges = [...graph.value.edges]
  }

  /** Plan 之后 → 根据 decision 精确预测下一节点（decision 已在 Plan.data 中） */
  function pushPendingDecision(prevNode: AgentNode) {
    const decision = prevNode.data?.decision
    if (decision === 'sufficient') {
      // 信息充足 → 下一节点是最终回答
      pushPending(prevNode, 'Answer', '最终回答')
    } else if (decision === 'terminate') {
      // 强制终止 → 下一节点是降级回答（信息可能不完整）
      pushPending(prevNode, 'Answer', '最终回答（可能不完整）')
    } else if (decision === 'need_more') {
      // 需要补搜 → 下一节点是工具执行
      pushPending(prevNode, 'ToolCall', '执行工具')
    } else {
      // 兜底：未知 decision 才显示"待决策"
      pushPending(prevNode, 'Decision', '⏳ 待决策')
    }
  }

  /** ToolCall 之后 → Observe（固定）；并行组时把存活兄弟一起连上预测的评估节点 */
  function pushPendingObserve(prevNode: AgentNode) {
    const pgId = prevNode.data?.parallel_group_id
    const nextStep = (prevNode.step_index ?? 0) + 1

    if (pgId) {
      // 复用同 step 已有的 pending Observe，避免多个并行 ToolCall 产生重复预测
      const existingPending = graph.value.nodes.find(
        n => n.status === 'pending' && n.type === 'Observe' && n.step_index === nextStep
      )
      if (existingPending) {
        connectGroupToPendingObserve(pgId, existingPending.id)
        return
      }
    }

    pushPending(prevNode, 'Observe', '评估中...')

    if (pgId) {
      const pendingObserve = graph.value.nodes.find(
        n => n.status === 'pending' && n.type === 'Observe' && n.step_index === nextStep
      )
      if (pendingObserve) {
        connectGroupToPendingObserve(pgId, pendingObserve.id)
      }
    }
  }

  /** 把同一并行组内所有存活（done）的 ToolCall 连接到 pending Observe */
  function connectGroupToPendingObserve(pgId: string, pendingId: string) {
    const siblings = graph.value.nodes.filter(
      n => n.type === 'ToolCall'
        && n.status === 'done'
        && n.data?.parallel_group_id === pgId
    )
    let added = false
    for (const sib of siblings) {
      const hasEdge = graph.value.edges.some(e => e.from === sib.id && e.to === pendingId)
      if (!hasEdge) {
        graph.value.edges.push({ from: sib.id, to: pendingId, type: 'Pending' })
        added = true
      }
    }
    if (added) {
      graph.value.edges = [...graph.value.edges]
    }
  }

  /** Observe 之后 → Plan（固定，Observe 之后一定是 Plan 做决策） */
  function pushPendingPlan(prevNode: AgentNode) {
    pushPending(prevNode, 'Plan', '决策中...')
  }

  /** 从指定 step_index 重试（支持编辑后重跑） */
  async function retryFrom(stepIndex: number, originalNode: any, editedData?: Record<string, any>) {
    // 重试开始后清除截断点状态，进入重试分支
    cutNode.value = null
    inRetryBranch = true
    // 重试属于同一轮对话，分割线追加到当前轮
    currentBlocks().push({
      id: `divider_retry_${Date.now()}`,
      nodeId: '',
      type: 'divider',
      status: 'done',
      title: '🔄 重试分支',
      content: '',
    })
    // 检测：如果是 ToolCall 类型且属于并行组，走方案 C
    const isParallelGroup = originalNode?.data?.parallel_group_id

    if (isParallelGroup) {
      // 方案 C：并行重试，只重跑被点击的那个
      return retryFromGraph(stepIndex, originalNode, editedData)
    }

    // 普通串行重试
    status.value = '🔄 正在重试...'
    connected.value = true
    isRunning.value = true

    const response = await fetch(`${API_BASE}/api/retry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step_index: stepIndex, edited_data: editedData }),
    })

    if (!response.ok) {
      status.value = `❌ 重试失败: HTTP ${response.status}`
      connected.value = false
      isRunning.value = false
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      status.value = '❌ SSE 读取失败'
      connected.value = false
      isRunning.value = false
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const parsed = JSON.parse(line.slice(6)) as SSEEvent
            handleEvent(parsed)
          } catch (e) {
            console.error('SSE parse error:', e)
          }
        }
      }
    }
  }

  /** 方案 C：并行重试——被编辑的旧节点废弃推远，新节点占原位 */
  async function retryFromGraph(stepIndex: number, originalNode: any, editedData?: Record<string, any>) {
    // 分割线由 retryFrom 统一推（并行重试也会经过 retryFrom），这里不重复推
    cutNode.value = null
    inRetryBranch = true
    status.value = '🔄 正在并行重试...'
    connected.value = true
    isRunning.value = true

    // 旧节点：只有被编辑的那个（将废弃并推到远位置）
    const oldNode = {
      ...originalNode,
      data: {
        ...originalNode.data,
        original: 'old' as const,
      },
    }

    // 新节点：编辑后的版本（占据原位置）
    const newNode = {
      ...originalNode,
      data: {
        ...originalNode.data,
        tool: editedData?.tool || originalNode.data?.tool,
        params: editedData?.params || originalNode.data?.params,
        original: 'new' as const,
      },
    }

    // 获取 query 和 plan_info
    const planNode = graph.value.nodes.find(n => n.type === 'Plan' && n.status !== 'pending')
    const query = planNode?.data?.input || ''
    const planInfo = planNode?.data?.output || ''

    const response = await fetch(`${API_BASE}/api/retry_from_graph`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        step_index: stepIndex,
        old_nodes: [oldNode],
        new_nodes: [newNode],
        query,
        plan_info: planInfo,
      }),
    })

    if (!response.ok) {
      status.value = `❌ 重试失败: HTTP ${response.status}`
      connected.value = false
      isRunning.value = false
      return
    }

    const reader = response.body?.getReader()
    if (!reader) {
      status.value = '❌ SSE 读取失败'
      connected.value = false
      isRunning.value = false
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const parsed = JSON.parse(line.slice(6)) as SSEEvent
            handleEvent(parsed)
          } catch (e) {
            console.error('SSE parse error:', e)
          }
        }
      }
    }
  }

  /** 手动重连：从 Redis 拉最新图，增量合并到本地图（补新节点、保留本地已有状态）。
   *  只在 disconnected=true 时可调用；成功后 cleared disconnected。 */
  async function reconnect() {
    if (!disconnected.value) return
    logEvent('reconnect', 'manual')
    status.value = '🔄 正在重连...'
    try {
      const resp = await fetch(`${API_BASE}/api/graph`)
      if (!resp.ok) {
        status.value = '❌ 重连失败：后端不可达'
        return
      }
      const snapshot = await resp.json()
      if (!snapshot?.nodes?.length) {
        // 后端无缓存图 → 恢复已不可能，清标记避免死循环弹窗
        clearRunId()
        clearRoundsCache()
        status.value = '📡 后端无缓存图，请重新提问'
        disconnected.value = false
        return
      }

      // ── 增量合并策略 ──
      // 1. 后端有但本地没有的节点 → 补进本地图（断连期间后端可能又推了几个）
      // 2. 本地有但后端没有的 pending/discarded 节点 → 保留（前端预测产生的虚拟节点）
      // 3. 两边都有的节点 → 用后端版本（后端是权威源）
      const localNodeMap = new Map(graph.value.nodes.map(n => [n.id, n]))
      const remoteNodeIds = new Set(snapshot.nodes.map((n: AgentNode) => n.id))

      const mergedNodes: AgentNode[] = []
      // 先放后端节点（权威）
      for (const rn of snapshot.nodes as AgentNode[]) {
        mergedNodes.push(rn)
      }
      // 再补本地独有且非 pending 的节点（如前端预测后被 discard 的）
      for (const ln of graph.value.nodes) {
        if (!remoteNodeIds.has(ln.id) && ln.status !== 'pending') {
          mergedNodes.push(ln)
        }
      }

      // 边也做合并：后端边为主，本地独有的边保留
      const remoteEdgeKeys = new Set(
        (snapshot.edges as AgentEdge[]).map((e: AgentEdge) => `${e.from}->${e.to}`)
      )
      const mergedEdges: AgentEdge[] = [...(snapshot.edges as AgentEdge[])]
      for (const le of graph.value.edges) {
        const key = `${le.from}->${le.to}`
        if (!remoteEdgeKeys.has(key)) {
          mergedEdges.push(le)
        }
      }

      graph.value = {
        nodes: mergedNodes,
        edges: mergedEdges,
        branches: snapshot.branches || graph.value.branches,
        meta: snapshot.meta || graph.value.meta,
      }

      // 更新当前轮 answer（如果后端图里有完成的 Answer）
      const r = rounds.value[rounds.value.length - 1]
      if (r) r.answer = finalAnswerOf(mergedNodes)

      // ── 补 pending：避免合并后图中出现“无 pending 也无 Answer”的断裂感 ──
      // 场景：断连时本地 pending 被标 discarded，Redis 里也没有对应真实节点
      // → 合并后图的末端秃了。根据最后一个活跃节点重新预测下一步。
      const hasAnswer = mergedNodes.some(
        (n: AgentNode) => n.type === 'Answer' && n.status === 'done' && !n.data?.safety_interrupt
      )
      const hasPending = mergedNodes.some((n: AgentNode) => n.status === 'pending')
      if (!hasAnswer && !hasPending) {
        // 找最后一个活跃（非 discarded/branch/replaced）节点作为预测锚点
        const activeNodes = mergedNodes.filter(
          (n: AgentNode) => n.status !== 'discarded' && n.status !== 'branch' && n.status !== 'replaced' && n.status !== 'pending'
        )
        const lastActive = activeNodes.length > 0
          ? activeNodes.reduce((a, b) => (a.step_index ?? 0) >= (b.step_index ?? 0) ? a : b)
          : null
        if (lastActive) {
          // 复用已有的预测逻辑
          if (lastActive.type === 'Plan') {
            pushPendingDecision(lastActive)
          } else if (lastActive.type === 'ToolCall') {
            pushPendingObserve(lastActive)
          } else if (lastActive.type === 'Observe') {
            pushPendingPlan(lastActive)
          }
        }
      }

      disconnected.value = false
      connected.value = true

      if (hasAnswer) {
        status.value = '✅ 重连成功 · 推理已完成'
        isRunning.value = false
      } else {
        // ── 自动续跑：没有 Answer → 调 /api/resume 接 SSE 流继续推理 ──
        status.value = '🔄 重连成功 · 正在恢复推理...'
        isRunning.value = true
        cutNode.value = null
        interruptedReceived = false
        inRetryBranch = false

        // 保留预测 pending：后端真实节点到达时 handleEvent 的 pending 存活规则会自动清除
        // 不提前清除，避免 resume SSE 流首个事件到达前图中出现“无 pending 也无真实节点”的断裂感

        try {
          const resumeResp = await fetch(`${API_BASE}/api/resume`, { method: 'POST' })
          if (!resumeResp.ok || !resumeResp.body) {
            status.value = '❌ 续跑失败：后端返回错误'
            isRunning.value = false
            return
          }

          const reader = resumeResp.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''

          while (true) {
            const readPromise = reader.read()
            const timeoutPromise = new Promise<{ timedOut: true }>((resolve) =>
              setTimeout(() => resolve({ timedOut: true }), 60000)
            )
            const result = await Promise.race([readPromise, timeoutPromise])

            if ('timedOut' in result) {
              connected.value = false
              disconnected.value = true
              isRunning.value = false
              for (const node of graph.value.nodes) {
                if (node.status === 'pending') {
                  node.status = 'discarded'
                  node.label = (node.label || '') + '（已中断）'
                }
              }
              graph.value.nodes = [...graph.value.nodes]
              for (const block of currentBlocks()) {
                if (block.status === 'loading') block.status = 'done'
              }
              status.value = '📡 连接再次断开 · 点击图中按钮重连'
              break
            }

            const { done, value } = result
            if (done) break

            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() || ''

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const parsed = JSON.parse(line.slice(6)) as SSEEvent
                  handleEvent(parsed)
                } catch (e) { /* ignore parse errors */ }
              }
            }
          }
        } catch (e) {
          status.value = '❌ 续跑失败：网络异常'
          isRunning.value = false
        }
      }
    } catch (e) {
      status.value = '❌ 重连失败：网络异常'
    }
  }

  // ── localStorage 重连：页面加载时检测到未完成 run，用户确认后恢复 ──
  async function resumePendingRun() {
    const pendingId = getPendingRunId()
    if (!pendingId) return false
    // ⚠️ 不在这里 clearRunId！等推理真正结束（run_complete/interrupted/error）时由 handleEvent 清除。
    // 这样推理进行中再次刷新仍能弹窗恢复。
    // 先恢复左侧聊天区（rounds），再恢复右侧思维图（reconnect）
    restoreRounds()
    // 让现有 reconnect() 能执行（它要求 disconnected=true）
    disconnected.value = true
    await reconnect()
    return true
  }

  function abandonPendingRun() {
    clearRunId()
    clearRoundsCache()
  }

  return {
    graph,
    status,
    connected,
    isRunning,
    disconnected,
    autoRetrying,
    autoRetryCount,
    rounds,
    clearRounds,
    cutNode,
    sendMessage,
    interrupt,
    clearCut,
    retryFrom,
    retryFromGraph,
    tryRestoreFromCache,
    reconnect,
    getPendingRunId,
    resumePendingRun,
    abandonPendingRun,
  }
}
