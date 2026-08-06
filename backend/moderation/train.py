"""
训练模块
使用 transformers Trainer 对 bert-base-chinese 进行二分类微调。
支持 --max_steps 参数用于冒烟快速验证。
"""

import argparse
import os
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import f1_score, precision_score, recall_score
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    TrainingArguments,
    Trainer,
    TrainerCallback,
)

from .data_prep import tokenize_and_split, MODEL_PATH


# ──────────────────────────────────────────────
# 1. 类别不平衡处理：自定义 loss（class weight）
# ──────────────────────────────────────────────

class WeightedBCETrainer(Trainer):
    """
    重写 compute_loss，为不合规类(label=1)加更高权重，
    以应对类别不平衡（通常不合规样本更少）。
    weight 可通过环境变量 MODERATION_POS_WEIGHT 调节，默认 2.0。
    """
    
    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        outputs = model(**inputs, return_dict=True)
        logits = outputs.logits
        
        # 从环境变量获取正类权重，默认 2.0
        pos_weight = float(os.environ.get("MODERATION_POS_WEIGHT", "2.0"))
        # 根据 label 分配权重: label=1 → pos_weight, label=0 → 1.0
        weights = torch.where(labels == 1, pos_weight, 1.0).to(logits.device)
        
        loss_fct = torch.nn.CrossEntropyLoss(reduction="none")
        loss = loss_fct(logits.view(-1, 2), labels.view(-1))
        loss = (loss * weights).mean()
        
        outputs.loss = loss
        return (loss, outputs) if return_outputs else loss


# ──────────────────────────────────────────────
# 2. 评估指标：F1 + precision + recall（非 accuracy）
# ──────────────────────────────────────────────

def compute_metrics(eval_pred):
    """
    计算 F1(macro)、precision(macro)、recall(macro)。
    """
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {
        "f1": f1_score(labels, preds, average="macro", zero_division=0),
        "precision": precision_score(labels, preds, average="macro", zero_division=0),
        "recall": recall_score(labels, preds, average="macro", zero_division=0),
    }


# ──────────────────────────────────────────────
# 3. 训练主函数
# ──────────────────────────────────────────────

def run_training(
    jsonl_path: str,
    output_dir: str = "output/checkpoint",
    model_path: str = MODEL_PATH,
    max_steps: int = None,
    epochs: int = 3,
    batch_size: int = 16,
    lr: float = 2e-5,
    warmup_ratio: float = 0.1,
    weight_decay: float = 0.01,
    seed: int = 42,
):
    """
    执行训练流程。
    
    参数:
        jsonl_path: JSONL 数据文件路径
        output_dir: checkpoint 输出目录
        model_path: 预训练模型路径（本地）
        max_steps: 最大训练步数（None 表示跑完全部 epochs）
        epochs: 训练轮数
        batch_size: batch 大小
        lr: 学习率
        warmup_ratio: warmup 比例
        weight_decay: 权重衰减
        seed: 随机种子
    """
    print(f"[DATA] 加载数据: {jsonl_path}")
    train_dataset, val_dataset = tokenize_and_split(jsonl_path)
    print(f"[OK] train={len(train_dataset)}, val={len(val_dataset)}")

    # 加载 tokenizer 和模型（本地，不联网）
    print(f"[MODEL] 加载模型: {model_path}")
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_path,
        num_labels=2,
        local_files_only=True,
        ignore_mismatched_sizes=True,  # 分类头可能不匹配
    )

    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)

    # 训练参数
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        learning_rate=lr,
        warmup_ratio=warmup_ratio,
        weight_decay=weight_decay,
        eval_strategy="no",  # 冒烟阶段不做 eval
        save_strategy="steps" if max_steps else "epoch",
        save_steps=max_steps if max_steps else epochs * len(train_dataset) // batch_size + 1,
        save_total_limit=1,
        logging_steps=1,
        seed=seed,
        fp16=torch.cuda.is_available(),
        report_to="none",  # 不上报
    )

    if max_steps is not None:
        training_args.max_steps = max_steps
        # transformers 4.57.6 要求 num_train_epochs 必须为非 None 整数
        # 设一个较大值，让 max_steps 先截断
        training_args.num_train_epochs = 999

    trainer = WeightedBCETrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=data_collator,
        processing_class=tokenizer,  # transformers 5.0: processing_class 替代 tokenizer
        compute_metrics=compute_metrics,
    )

    print("[TRAIN] 开始训练...")
    train_result = trainer.train()

    # 保存最终 checkpoint
    final_path = os.path.join(output_dir, "final")
    trainer.save_model(final_path)
    tokenizer.save_pretrained(final_path)
    print(f"[OK] 模型已保存至: {final_path}")

    # 输出训练指标
    metrics = train_result.metrics
    print(f"[METRICS] 训练指标: {metrics}")
    
    return final_path


# ──────────────────────────────────────────────
# 4. CLI 入口
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="合规校验模型微调训练")
    parser.add_argument(
        "--data",
        type=str,
        default=str(Path(__file__).parent / "data" / "sample.jsonl"),
        help="JSONL 数据文件路径",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(Path(__file__).parent / "output" / "checkpoint"),
        help="checkpoint 输出目录",
    )
    parser.add_argument(
        "--max_steps",
        type=int,
        default=None,
        help="最大训练步数（用于冒烟快速验证）",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="训练轮数",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=MODEL_PATH,
        help="预训练模型路径",
    )
    
    args = parser.parse_args()
    run_training(
        jsonl_path=args.data,
        output_dir=args.output,
        model_path=args.model,
        max_steps=args.max_steps,
        epochs=args.epochs,
    )


if __name__ == "__main__":
    main()
