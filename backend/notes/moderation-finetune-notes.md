# 输出合规校验 · 微调脚手架交付笔记

## 新增文件清单

| 文件 | 说明 |
|------|------|
| `backend/moderation/__init__.py` | 模块初始化，导出核心接口 |
| `backend/moderation/__main__.py` | 模块入口（`python -m moderation`） |
| `backend/moderation/data_prep.py` | 数据准备：JSONL 读取 → tokenize → train/val 8:2 切分 |
| `backend/moderation/train.py` | 训练模块：WeightedBCETrainer（类别不平衡）+ F1/precision/recall 评估 |
| `backend/moderation/predict.py` | 预测模块：加载 checkpoint，输出 {label, label_name, confidence} |
| `backend/moderation/export_onnx.py` | ONNX 导出：CPU 推理用 .onnx 文件 |
| `backend/moderation/data/sample.jsonl` | 20 条手标冒烟样本（10 合规 + 10 不合规），法律问答场景 |
| `backend/moderation/output/checkpoint/final/` | 训练产出的 checkpoint 目录 |
| `backend/moderation/output/moderation.onnx` | 导出的 ONNX 模型（~1.3 MB） |

## 环境

- Python: `D:\miniconda3\envs\aivenv\python.exe`
- transformers 4.57.6 / torch（CUDA 就绪）
- 本地底座: `D:\ai\bert-base-chinese`（不联网）
- 额外安装: `pip install onnxscript`（ONNX 导出依赖）

## 分支

- `feature/moderation`（只做加法，未动任何现有文件）

## 验证步骤 & 结果

### 1. 语法检查
```bash
cd D:\code\mindglass\backend
D:\miniconda3\envs\aivenv\python.exe -c "import ast; [ast.parse(open(f'moderation/{f}', encoding='utf-8').read()) for f in ['data_prep.py','train.py','predict.py','export_onnx.py','__init__.py']]"
```
✅ 全部通过

### 2. Import 验证
```bash
cd D:\code\mindglass\backend
D:\miniconda3\envs\aivenv\python.exe -c "from moderation.data_prep import load_jsonl; print('OK')"
D:\miniconda3\envs\aivenv\python.exe -c "from moderation.train import run_training; print('OK')"
D:\miniconda3\envs\aivenv\python.exe -c "from moderation.predict import predict_text; print('OK')"
D:\miniconda3\envs\aivenv\python.exe -c "from moderation.export_onnx import export_to_onnx; print('OK')"
```
✅ 全部通过

### 3. 冒烟训练
```bash
cd D:\code\mindglass\backend
D:\miniconda3\envs\aivenv\python.exe -m moderation.train --max_steps 10
```
✅ 10 步训练完成，loss 从 1.17 降到 0.29，模型保存至 `output/checkpoint/final/`

关键指标：
- `train_loss`: 0.576
- `train_runtime`: 9.4s
- `train_samples_per_second`: 17.0

### 4. 预测验证
```bash
cd D:\code\mindglass\backend
D:\miniconda3\envs\aivenv\python.exe -m moderation.predict --text "根据《民法典》，合同违约方应承担赔偿责任。"
```
✅ 输出: `label=0, 合规, confidence=0.8362`

### 5. ONNX 导出
```bash
cd D:\code\mindglass\backend
D:\miniconda3\envs\aivenv\python.exe -m moderation.export_onnx
```
✅ 导出成功: `output/moderation.onnx`（1.3 MB）

## 关键设计决策

### 类别不平衡处理
- 自定义 `WeightedBCETrainer`，重写 `compute_loss`
- 正类（不合规）权重默认 2.0，可通过环境变量 `MODERATION_POS_WEIGHT` 调节
- 权重分配: `label=1 → pos_weight`, `label=0 → 1.0`

### 评估指标
- **F1(macro) + precision(macro) + recall(macro)**，不是 accuracy
- 原因：类别不平衡时 accuracy 会偏向多数类

### 超参数
- lr=2e-5, epochs=3, batch=16, warmup_ratio=0.1, weight_decay=0.01
- 支持 `--max_steps N` 用于冒烟快速验证

## 已知问题 & 修复记录

1. **TrainingArguments `evaluation_strategy` 参数**: transformers 4.57.6 改名为 `eval_strategy` → 已修复
2. **`num_train_epochs=None` + `max_steps` 冲突**: transformers 要求非 None → 设为 999 让 max_steps 截断
3. **`model(**inputs)` 返回 tuple**: transformers 4.57.6 默认不返回 dataclass → 所有地方加 `return_dict=True`
4. **Trainer `tokenizer` 参数废弃**: 4.57.6 用 `processing_class` 替代 → 已修复
5. **ONNX opset 14 版本转换失败**: LayerNormalization 不支持 → 改为 opset 18

## 真实训练还缺什么

### 语料
- **从哪来**: 需要哥哥决定数据来源（用户真实问答记录、人工标注、还是混合）
- **要多少**: 建议至少 2000-5000 条标注样本（合规:不合规 ≈ 3:1 到 5:1）
- **标注规范**: 
  - label=0 (合规): 正常法律解答、政策说明
  - label=1 (不合规): 教唆违法、规避监管、提供非法手段、虚假承诺等

### 正式训练配置
- 去掉 `--max_steps`，跑完整 3 epochs
- 增加 eval 策略: `eval_strategy="epoch"` 监控过拟合
- 可考虑数据增强（同义词替换、句式变换）扩充不合规类样本

## 之后怎么接到 Answer 节点

1. 在 `react_loop.py` 的 Answer 节点产出后、SSE 返回前，调用 `predict.py` 的 `predict_text()`
2. 如果 `label == 1`（不合规），触发降级话术（类似 `degraded=True` 的逻辑）
3. 降级话术示例: "该回答可能包含不适当内容，已为您进行安全过滤。"
4. 可配置: 通过环境变量开关/阈值调整

## 验收标准完成情况

| 标准 | 状态 |
|------|------|
| 从 `D:\ai\bert-base-chinese` 本地加载底座（不联网） | ✅ |
| 四个 py 文件齐全、有注释、import 全部通过 | ✅ |
| `train.py --max_steps 10` 完成训练、产出 checkpoint | ✅ |
| `predict.py` 给出分类结果 | ✅ |
| `export_onnx.py` 导出 .onnx 文件 | ✅ |
| 不接入主流程、不动任何现有文件 | ✅ |
