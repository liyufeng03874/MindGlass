import {ref} from 'vue'
import type {AgentNode, ReasoningGraph, SSEEvent, LeftBlock} from '@/types/agent'

// API 地址：生产环境通过 nginx 反代 /api，开发环境可覆盖 VITE_API_BASE_URL
const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

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
  const status = ref('')
  const connected = ref(false)
  const isRunning = ref(false)

  /** 左侧思考直播 Block 列表 */
  const leftBlocks = ref<LeftBlock[]>([])

  const messages = ref<Array<{ role: 'user' | 'agent', content: string }>>([])

  /** 截断点节点（打断后只有它能点重试；重试或新查询后清空） */
  const cutNode = ref<AgentNode | null>(null)

  /** 当前活跃的 EventSource（打断收流用） */
  let activeEventSource: EventSource | null = null
  /** 已收到 interrupted 事件（onerror 不再误报“连接断开”） */
  let interruptedReceived = false
  /** 重试分支标记：重试开始后的新 block 标记 phase=retry（左侧样式区分） */
  let inRetryBranch = false

  function sendMessage(query: string) {
    messages.value.push({ role: 'user', content: query })
    status.value = '🤔 连接中...'
    connected.value = true
    isRunning.value = true
    cutNode.value = null
    interruptedReceived = false
    inRetryBranch = false

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

    const eventSource = new EventSource(
      `${API_BASE}/api/run?query=${encodeURIComponent(query)}`
    )
    activeEventSource = eventSource

    eventSource.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as SSEEvent
        handleEvent(parsed)
      } catch (e) {
        console.error('SSE parse error:', e)
      }
    }

    eventSource.onerror = () => {
      // 打断场景：interrupted 事件已收束，这里主动关闭不算断线
      if (interruptedReceived) {
        eventSource.close()
        activeEventSource = null
        return
      }
      status.value = '连接断开'
      connected.value = false
      isRunning.value = false
      eventSource.close()
      activeEventSource = null
    }
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
    switch (event.type) {
      case 'status':
        status.value = event.data.message
        break

      case 'node_streaming': {
        // 流式内容追加到 leftBlocks
        const { node_id, node_type, content, is_complete, chunk } = event.data
        const blockType = nodeTypeToBlockType(node_type)
        const blockId = `block_${node_id}`
        const title = BLOCK_TITLES[node_type] || node_type

        let block = leftBlocks.value.find((b: LeftBlock) => b.id === blockId)
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
          leftBlocks.value.push(block)
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

        // ToolCall 类型 → 填充 leftBlocks 的 metadata（toolName/params/resultPreview）
        if (node.type === 'ToolCall') {
          const blockType: LeftBlock['type'] = 'toolcall'
          const blockId = `block_${node.id}`
          let block = leftBlocks.value.find((b: LeftBlock) => b.id === blockId)

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
            leftBlocks.value.push(block)
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
          const anyBlock = leftBlocks.value.find((bb: LeftBlock) => bb.id === `block_${node.id}`)
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
            messages.value.push({ role: 'agent', content: node.data.output })
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
        connected.value = false
        isRunning.value = false
        cutNode.value = null
        if (event.data.graph) {
          console.log('[Run Complete] edges:', JSON.stringify(event.data.graph.edges, null, 2))
          graph.value = event.data.graph as ReasoningGraph
          console.log('[Run Complete]', graph.value.nodes.length, 'nodes', graph.value.edges.length, 'edges')
        }
        // 所有 leftBlocks 标记为 done（run_complete 时确保状态正确）
        for (const block of leftBlocks.value) {
          if (block.status === 'loading') {
            block.status = 'done'
          }
        }
        break
      }

      case 'interrupted': {
        // 用户打断：后端已完成收尾（截断点后置灰），前端收束
        interruptedReceived = true
        if (activeEventSource) {
          activeEventSource.close()
          activeEventSource = null
        }
        if (event.data.graph) {
          graph.value = event.data.graph as ReasoningGraph
        }
        // 左侧还在 loading 的流式 block 标记结束；被废弃的 block 标记 phase=cut（置灰）
        const interruptedIds = new Set(
          ((event.data.graph?.nodes as any[]) || [])
            .filter((n: any) => n.data?.interrupted
              || n.status === 'replaced' || n.status === 'branch' || n.status === 'discarded')
            .map((n: any) => n.id)
        )
        for (const block of leftBlocks.value) {
          if (block.status === 'loading') block.status = 'done'
          if (interruptedIds.has(block.nodeId)) block.phase = 'cut'
        }
        // 未流式过的废弃节点（如被打断时还没出现的决策/回答）补成置灰 block，
        // 让左侧聊天完整呈现"被打断侧"的后续链（问题2）
        const existingIds = new Set(leftBlocks.value.map(b => b.nodeId))
        const missedNodes = ((event.data.graph?.nodes as any[]) || [])
          .filter((n: any) => (n.status === 'replaced' || n.status === 'branch')
            && !existingIds.has(n.id)
            && ['Plan', 'Observe', 'Answer', 'ToolCall'].includes(n.type))
          .sort((a: any, b: any) => (a.step_index ?? 0) - (b.step_index ?? 0))
        for (const n of missedNodes) {
          leftBlocks.value.push({
            id: `block_${n.id}`,
            nodeId: n.id,
            type: nodeTypeToBlockType(n.type),
            status: 'done',
            title: n.label || BLOCK_TITLES[n.type] || n.type,
            content: '',
            phase: 'cut',
            metadata: n.type === 'ToolCall' && n.data?.result !== undefined
              ? {
                  toolName: n.data?.tool || '',
                  params: n.data?.params,
                  resultPreview: '',
                  resultFull: typeof n.data.result === 'string' ? n.data.result : JSON.stringify(n.data.result),
                }
              : undefined,
          })
        }
        // 分割线：打断边界
        leftBlocks.value.push({
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
        // 安全策略拦截：清空当前回答，显示拦截提示
        const interruptText = event.data.text || '很抱歉，该回答包含不合规内容，已被安全策略拦截。'
        // 清空左侧 Answer block 的内容，替换为拦截提示
        const answerBlock = leftBlocks.value.find((b: LeftBlock) => b.type === 'answer')
        if (answerBlock) {
          answerBlock.content = interruptText
          answerBlock.status = 'error'
          answerBlock.title = '⚠️ 安全拦截'
        }
        // 右侧消息也显示拦截提示
        messages.value.push({ role: 'agent', content: `⚠️ ${interruptText}` })
        status.value = '⚠️ 安全策略拦截'
        isRunning.value = false
        connected.value = false
        break
      }

      case 'error':
        status.value = `❌ 错误: ${event.data.message}`
        connected.value = false
        isRunning.value = false
        break
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
    leftBlocks.value.push({
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

  return {
    graph,
    status,
    connected,
    isRunning,
    messages,
    leftBlocks,
    cutNode,
    sendMessage,
    interrupt,
    clearCut,
    retryFrom,
    retryFromGraph,
  }
}
