/**
 * usePhase · 思镜全局相位系统（v2.1 第一遍：基础版）
 *
 * 相位 = 推理走到哪一步，整个界面的氛围层订阅它，共享一次呼吸。
 *   idle     待机        —— 深空静水
 *   planning 规划中      —— 靛蓝光晕
 *   tooling  调用工具    —— 青绿 + 流星
 *   observing 整合观察   —— 琥珀涟漪
 *   answering 生成回答   —— 金紫收拢
 *   done     完成        —— 归于平静
 *
 * 实现：模块级单例 ref（SPA 内全局唯一），任何组件 import 即共享同一状态。
 * HomeView 负责写入（从 useAgentGraph 推导），StarField 负责读取渲染。
 *
 * ⚠️ 第一遍只粗粒度映射 idle / planning / done 三态，让氛围层先活起来。
 *    细粒度 planning/tooling/observing 由 SSE 事件驱动，是 P0 精修项。
 */
import { computed, ref, type Ref } from 'vue'

export type Phase = 'idle' | 'planning' | 'tooling' | 'observing' | 'answering' | 'done'

/** 相位 → 氛围主色（对应 style.css 里的 --phase-* 语义色） */
export function phaseColor(p: Phase): string {
  switch (p) {
    case 'planning': return '#60a5fa'
    case 'tooling': return '#34d399'
    case 'observing': return '#fbbf24'
    case 'answering': return '#c4b5fd'
    case 'done': return '#a78bfa'
    case 'idle':
    default: return '#3b4a6b'
  }
}

// 模块级单例：全局唯一相位状态
const phase = ref<Phase>('idle')

/** 任意组件调用：读写全局相位（同一引用） */
export function usePhase(): { phase: Ref<Phase> } {
  return { phase }
}

/** 工具：从粗粒度状态推导相位（第一遍用） */
export function derivePhase(isRunning: Ref<boolean>, hasNodes: Ref<boolean>): Ref<Phase> {
  return computed<Phase>(() => {
    if (isRunning.value) return 'planning'
    if (hasNodes.value) return 'done'
    return 'idle'
  })
}
