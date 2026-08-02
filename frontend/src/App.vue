<template>
  <!-- 氛围层：铺满全屏的深空星野，垫在所有页面之下 -->
  <StarField />
  <div class="page-root">
    <RouterView />
  </div>
</template>

<script setup lang="ts">
import { RouterView } from 'vue-router'
import StarField from './components/StarField.vue'
</script>

<style scoped>
/* 页面内容叠在氛围层之上（StarField 为 fixed z:0） */
.page-root {
  position: relative;
  z-index: 1;
  height: 100vh;
}
</style>
