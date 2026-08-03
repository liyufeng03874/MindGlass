/**
 * MindGlass — Agent 推理图数据类型
 */

export type NodeType = 'Plan' | 'ToolCall' | 'Observe' | 'Answer' | 'Decision'
export type NodeStatus = 'done' | 'current' | 'pending' | 'error' | 'discarded' | 'branch' | 'replaced'
export type EdgeType = 'Normal' | 'Retry' | 'Fallback' | 'Branch' | 'Parallel' | 'Pending'

export interface AgentNode {
  id: string
  type: NodeType
  data: Record<string, any>
  status: NodeStatus
  step_index: number
  branch_id: string | null
  label: string
  duration_ms?: number  // 节点执行耗时（毫秒）
}

export interface AgentEdge {
  from: string
  to: string
  type: EdgeType
}

export interface BranchRecord {
  id: string
  discarded_from: string
  discarded_node_ids: string[]
  reason: string
}

export interface ReasoningMeta {
  current_step_index: number
  total_steps: number
  query: string
  run_id: string
  run_started_at?: number  // 本次运行开始时间（秒级时间戳）
  plan_count?: number      // Plan 轮次（v2 决策循环）
}

export interface ReasoningGraph {
  nodes: AgentNode[]
  edges: AgentEdge[]
  branches: BranchRecord[]
  meta: ReasoningMeta
}

/** SSE 事件类型 */
export interface SSEEvent {
  type: 'node_streaming' | 'node_complete' | 'status' | 'run_complete' | 'error'
  data: Record<string, any>
}

/** 左侧思考直播 Block */
export interface LeftBlock {
  id: string            // = node_id
  nodeId: string
  type: 'plan' | 'toolcall' | 'observe' | 'answer'
  status: 'loading' | 'done' | 'error'
  title: string         // 如 "🧠 正在规划..."
  content: string       // 流式内容（node_streaming 的 content 直接覆盖）
  metadata?: {
    toolName?: string
    params?: Record<string, any>
    resultPreview?: string
  }
  // 用于并行工具块分组
  parallelGroupId?: string
}
