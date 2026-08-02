<!--
  MirrorIcon · 思镜品牌图标（手绘 SVG 镜）
  用 SVG 而非 emoji：任何机器/浏览器渲染一致，永不出现"豆腐块"方框。
  继承 currentColor，可随处染色；size 控制尺寸。
-->
<template>
  <svg
    class="mirror-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-label="思镜"
  >
    <!-- 镜面 -->
    <circle cx="12" cy="9" r="6.5" stroke="currentColor" stroke-width="1.6" />
    <!-- 手柄 -->
    <path d="M12 15.5V21" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
    <!-- 反光 -->
    <path d="M9.2 6.8l1.9 1.9" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" opacity="0.5" />
  </svg>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ size?: number | string }>(), { size: 20 })
</script>

<style scoped>
.mirror-icon {
  display: inline-block;
  vertical-align: -0.15em;
}
</style>
