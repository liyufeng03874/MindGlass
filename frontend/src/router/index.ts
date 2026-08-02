import { createRouter, createWebHistory } from 'vue-router'

// 延迟导入视图组件，避免未安装 vue-router 时构建失败
const HomeView = () => import('../views/HomeView.vue')
const AdminView = () => import('../views/AdminView.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/admin',
      name: 'admin',
      component: AdminView,
    },
  ],
})

export default router
