# 移动端响应式适配进度

## 分支
`feature/mobile-responsive`

## 已完成模块

### 1. Tailwind CSS 配置 ✅
- 安装 Tailwind CSS v3 + postcss + autoprefixer
- `tailwind.config.js` 配置 content 扫描 Vue 文件 + 自定义 xs 断点
- `postcss.config.js` 配置 tailwindcss + autoprefixer
- `src/style.css` 添加 `@tailwind base/components/utilities` 指令（修复旧版 v4 语法）

### 2. HomeView 手机端适配 ✅
**文件**: `frontend/src/views/HomeView.vue`
- 手机端主内容区 `flex-direction: column`（上下布局）
- 新增底部导航栏：💬 对话 / 🧠 思维 Tab 切换
- 推理图全屏时隐藏聊天面板，避免 50/50 拥挤
- header 纵向排列，状态栏折行
- `isMobile` 响应式状态（window resize 监听 < 768px）

### 3. ChatPanel 手机端适配 ✅
**文件**: `frontend/src/components/ChatPanel.vue`
- 气泡 max-width → 92%，字号 15px
- 并行工具组网格（2列）→ 手机端单列
- 输入框 font-size: 16px（防止 iOS 自动缩放）
- 发送按钮增大 padding 适配触屏
- avatar 缩小至 20px + 间距调整

### 4. ReasoningGraph 手机端适配 ✅
**文件**: `frontend/src/components/ReasoningGraph.vue`
- 编辑面板手机端改为底部弹出（75% 高度，圆角顶部）
- 废弃回答弹窗全屏适配（96% 宽，圆角）
- 所有输入控件 font-size: 16px 防止 iOS 缩放
- 节点信息、步骤列表、决策标签字号调大

### 5. AdminView 手机端适配 ✅
**文件**: `frontend/src/views/AdminView.vue`
- 表格容器 `overflow-x: auto` 横向滚动（min-width: 900px）
- 指标卡手机端 2x2 网格布局
- 弹窗全屏（width: 100%, height: 100%, border-radius: 0）
- 分页按钮增大，适配触屏
- 修复 ReasoningGraph 缺少 cutNodeId prop 的 TS 错误

## 验收情况
- [x] Vite 构建通过（`npx vite build`）
- [x] PC 端效果不受影响（CSS 用 `@media (max-width: 767px)` 包裹，PC 不生效）
- [x] 手机端布局：底部 Tab 切换、气泡全宽、输入区适配
- [ ] 手机端真实测试：Chrome DevTools 手机模拟器 + 真机访问

## 技术方案
- **断点**: 768px（PC >= 768px 保持不变，手机 < 768px 适配）
- **策略**: 手机端用 `@media (max-width: 767px)` 添加覆盖样式
- **输入**: 所有 `<input>` 在手机端 `font-size: 16px` 防止 iOS 自动缩放
- **导航**: 手机端底部 Tab 切换对话/思维，避免分屏拥挤
- **PC 不变**: 所有响应式样式只在 `max-width: 767px` 生效

## 已知 TS 错误（非本次引入）
- ~~`ChatPanel.vue`: `offsetWidth` 类型问题~~ ✅ 已修复（`el as HTMLElement`）
- ~~`useAgentGraph.ts`: `interrupted`/`safety_interrupt` 类型比较~~ ✅ 已修复（添加到 SSEEvent 类型）
- 构建已通过（`npm run build` 无错误）

## 改了哪些文件
- `frontend/package.json` / `package-lock.json` - 新增 tailwindcss/@tailwindcss/vite
- `frontend/vite.config.ts` - 配置 @tailwindcss/vite 插件
- `frontend/src/style.css` - 添加 @import "tailwindcss" 指令
- `frontend/src/types/agent.ts` - 修复 SSEEvent 类型（添加 interrupted/safety_interrupt）
- `frontend/src/views/HomeView.vue` - 手机端布局 + 底部导航
- `frontend/src/components/ChatPanel.vue` - 手机端响应式样式
- `frontend/src/components/ReasoningGraph.vue` - 编辑面板 + 弹窗适配
- `frontend/src/views/AdminView.vue` - 表格 + 弹窗适配
