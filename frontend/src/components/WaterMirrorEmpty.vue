<!--
  WaterMirrorEmpty · 思镜空态水镜
  当 graph 为空时显示：深空星野 + 中央水镜（倒影 + 涟漪 + 镜面反射）
  水镜 = 一条水平镜面线 + 上方思镜图标 + 下方倒影（模糊 + 透明度衰减）
  涟漪 = 从镜面中心向外扩散的同心圆
-->
<template>
  <div class="water-mirror-empty">
    <!-- 水镜主体 -->
    <div class="mirror-container">
      <!-- 上方：思镜图标 -->
      <div class="mirror-top">
        <MirrorIcon :size="80" class="mirror-icon" />
        <div class="mirror-title">思镜</div>
        <div class="mirror-subtitle">照见思考的镜子</div>
      </div>

      <!-- 镜面线 -->
      <div class="mirror-line"></div>

      <!-- 下方：倒影（模糊 + 透明度衰减） -->
      <div class="mirror-bottom">
        <MirrorIcon :size="80" class="mirror-icon reflection" />
        <div class="mirror-title reflection">思镜</div>
      </div>

      <!-- 涟漪（从镜面中心向外扩散） -->
      <div class="ripples">
        <div class="ripple ripple-1"></div>
        <div class="ripple ripple-2"></div>
        <div class="ripple ripple-3"></div>
      </div>
    </div>

    <!-- 提示文字 -->
    <div class="hint">
      <p>投一个问题进来，看思绪如何成形</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import MirrorIcon from './MirrorIcon.vue'
</script>

<style scoped>
.water-mirror-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  width: 100%;
  padding: 40px 20px;
  position: relative;
}

.mirror-container {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
}

.mirror-top {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.mirror-icon {
  color: var(--accent);
  filter: drop-shadow(0 0 20px rgba(167, 139, 250, 0.6));
  animation: float 4s ease-in-out infinite;
}

.mirror-title {
  font-size: 28px;
  font-weight: 600;
  color: var(--text-h);
  letter-spacing: 2px;
  text-shadow: 0 0 20px rgba(167, 139, 250, 0.4);
}

.mirror-subtitle {
  font-size: 14px;
  color: var(--text-dim);
  letter-spacing: 1px;
}

/* 镜面线 */
.mirror-line {
  width: 200px;
  height: 2px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(167, 139, 250, 0.3) 20%,
    rgba(167, 139, 250, 0.6) 50%,
    rgba(167, 139, 250, 0.3) 80%,
    transparent 100%
  );
  box-shadow: 0 0 10px rgba(167, 139, 250, 0.4);
  margin: 10px 0;
}

/* 倒影 */
.mirror-bottom {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  margin-top: 20px;
  transform: scaleY(-1);  /* 垂直翻转 */
  opacity: 0.3;
  filter: blur(2px);
  mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.6) 0%, transparent 80%);
  -webkit-mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.6) 0%, transparent 80%);
}

.reflection {
  opacity: 0.6;
}

/* 涟漪 */
.ripples {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  pointer-events: none;
}

.ripple {
  position: absolute;
  border: 1px solid rgba(167, 139, 250, 0.4);
  border-radius: 50%;
  animation: ripple-expand 4s ease-out infinite;
}

.ripple-1 {
  width: 100px;
  height: 100px;
  top: -50px;
  left: -50px;
  animation-delay: 0s;
}

.ripple-2 {
  width: 150px;
  height: 150px;
  top: -75px;
  left: -75px;
  animation-delay: 1.3s;
}

.ripple-3 {
  width: 200px;
  height: 200px;
  top: -100px;
  left: -100px;
  animation-delay: 2.6s;
}

@keyframes ripple-expand {
  0% {
    transform: scale(0);
    opacity: 0.8;
  }
  100% {
    transform: scale(1.5);
    opacity: 0;
  }
}

@keyframes float {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-10px);
  }
}

.hint {
  margin-top: 40px;
  text-align: center;
}

.hint p {
  font-size: 16px;
  color: var(--text-dim);
  font-style: italic;
  letter-spacing: 1px;
}
</style>
