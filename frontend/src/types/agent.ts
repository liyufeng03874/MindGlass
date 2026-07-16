/**
 * MindGlass — Agent 推理图数据类型
 */

export type NodeType = 'Plan' | 'ToolCall' | 'Observe' | 'Answer'
export type NodeStatus = 'done' | 'current' | 'pending' | 'error' | 'discarded' | 'branch'
export type EdgeType = 'Normal' | 'Retry' | 'Fallback' | 'Branch' | 'Pending'

export interface AgentNode {
  id: string
  type: NodeType
  data: Record<string, any>
  status: NodeStatus
  step_index: number
  branch_id: string | null
  label: string
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
}

export interface ReasoningGraph {
  nodes: AgentNode[]
  edges: AgentEdge[]
  branches: BranchRecord[]
  meta: ReasoningMeta
}

/** SSE 事件类型 */
export interface SSEEvent {
  type: 'node_complete' | 'status' | 'run_complete' | 'error'
  data: Record<string, any>
}
