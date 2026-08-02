<!--
  StarField · 思镜氛围层
  铺满全屏的深空星野：缓慢漂移的星点 + 相位变色光晕 + 掠过流星。
  订阅全局相位 phase，让整个房间随推理状态呼吸。
  z-index:0，垫在所有 UI 之下，pointer-events:none 不吃交互。
-->
<template>
  <canvas ref="canvasRef" class="starfield"></canvas>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { phaseColor, usePhase } from '../composables/usePhase'

const canvasRef = ref<HTMLCanvasElement | null>(null)
const { phase } = usePhase()

// 目标光晕颜色（随相位切换），当前颜色每帧朝它插值，过渡才柔和
let target = { r: 59, g: 74, b: 107 }   // --phase-idle
let cur = { ...target }
let raf = 0

interface Star { x: number; y: number; r: number; base: number; tw: number; ph: number; vx: number; vy: number }
interface Meteor { x: number; y: number; vx: number; vy: number; life: number; max: number }

let stars: Star[] = []
let meteors: Meteor[] = []
let w = 0
let h = 0
let t = 0
let lastMeteorPhase = ''

const hexToRgb = (hex: string) => {
  const n = parseInt(hex.slice(1), 16)
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
}
const lerp = (a: number, b: number, k: number) => a + (b - a) * k

// 按视口面积布星，密度恒定；每颗有闪烁相位与极慢漂移速度
const initStars = () => {
  const count = Math.min(220, Math.floor((w * h) / 9000))
  stars = Array.from({ length: count }, () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    r: Math.random() * 1.4 + 0.3,
    base: Math.random() * 0.5 + 0.3,
    tw: Math.random() * 0.02 + 0.005,
    ph: Math.random() * Math.PI * 2,
    vx: (Math.random() - 0.5) * 0.03,
    vy: (Math.random() - 0.5) * 0.03,
  }))
}

const spawnMeteor = () => {
  const fromLeft = Math.random() > 0.5
  meteors.push({
    x: fromLeft ? -50 : w * (0.3 + Math.random() * 0.7),
    y: Math.random() * h * 0.4,
    vx: (fromLeft ? 1 : -1) * (6 + Math.random() * 4),
    vy: 3 + Math.random() * 2,
    life: 0,
    max: 60 + Math.random() * 30,
  })
}

const resize = () => {
  const cv = canvasRef.value
  if (!cv) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  w = window.innerWidth
  h = window.innerHeight
  cv.width = w * dpr
  cv.height = h * dpr
  cv.style.width = w + 'px'
  cv.style.height = h + 'px'
  const ctx = cv.getContext('2d')
  if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  initStars()
}

const draw = () => {
  const cv = canvasRef.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  if (!ctx) return
  t += 1

  // 相位 → 目标色，当前色缓动逼近
  target = hexToRgb(phaseColor(phase.value))
  cur.r = lerp(cur.r, target.r, 0.02)
  cur.g = lerp(cur.g, target.g, 0.02)
  cur.b = lerp(cur.b, target.b, 0.02)

  ctx.clearRect(0, 0, w, h)

  // 相位光晕：呼吸感径向渐变，强度随相位轻微起伏
  const pulse = 0.10 + 0.03 * Math.sin(t * 0.01)
  const g = ctx.createRadialGradient(w * 0.62, h * 0.30, 0, w * 0.62, h * 0.30, Math.max(w, h) * 0.75)
  g.addColorStop(0, `rgba(${cur.r | 0},${cur.g | 0},${cur.b | 0},${pulse})`)
  g.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, w, h)

  // 星点：闪烁 + 慢漂移，越界回卷
  for (const s of stars) {
    s.ph += s.tw
    s.x += s.vx
    s.y += s.vy
    if (s.x < 0) s.x += w; else if (s.x > w) s.x -= w
    if (s.y < 0) s.y += h; else if (s.y > h) s.y -= h
    const a = s.base + Math.sin(s.ph) * 0.25
    ctx.beginPath()
    ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
    ctx.fillStyle = `rgba(226,232,255,${Math.max(0.05, a)})`
    ctx.fill()
  }

  // 相位跃迁到 tooling 时放一颗流星（并行工具 = 多颗，留待 P0 精修）
  if (phase.value === 'tooling' && lastMeteorPhase !== 'tooling') spawnMeteor()
  lastMeteorPhase = phase.value

  // 流星：拖尾线段 + 头部亮点，寿命耗尽移除
  meteors = meteors.filter((m) => m.life < m.max)
  for (const m of meteors) {
    m.life += 1
    m.x += m.vx
    m.y += m.vy
    const fade = 1 - m.life / m.max
    const tailX = m.x - m.vx * 6
    const tailY = m.y - m.vy * 6
    const grad = ctx.createLinearGradient(m.x, m.y, tailX, tailY)
    grad.addColorStop(0, `rgba(255,255,255,${0.8 * fade})`)
    grad.addColorStop(1, 'rgba(255,255,255,0)')
    ctx.strokeStyle = grad
    ctx.lineWidth = 1.6
    ctx.beginPath()
    ctx.moveTo(m.x, m.y)
    ctx.lineTo(tailX, tailY)
    ctx.stroke()
  }

  raf = requestAnimationFrame(draw)
}

onMounted(() => {
  resize()
  window.addEventListener('resize', resize)
  raf = requestAnimationFrame(draw)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  window.removeEventListener('resize', resize)
})
</script>

<style scoped>
.starfield {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}
</style>
