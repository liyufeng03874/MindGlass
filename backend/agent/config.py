"""MindGlass Agent — 共享配置常量

所有模块共享的常量（避免循环 import），禁止散落魔法数字。
"""

# 最大规划轮次——所有"最多 N 轮"/强制终止判断统一引用
MAX_PLAN_COUNT = 5
