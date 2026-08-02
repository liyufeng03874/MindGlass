"""
预测模块
加载训练好的 checkpoint，对输入文本进行合规性分类。
输出: {label: int, label_name: str, confidence: float}
"""

import os
from pathlib import Path
from typing import Optional

import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, AutoModelForSequenceClassification


# 默认 checkpoint 路径（训练产出）
DEFAULT_CHECKPOINT = os.environ.get(
    "MODERATION_CHECKPOINT",
    str(Path(__file__).parent / "output" / "checkpoint" / "final"),
)

# 标签映射
LABEL_MAP = {0: "合规", 1: "不合规"}


def load_moderation_model(
    checkpoint_path: str = DEFAULT_CHECKPOINT,
    model_path: Optional[str] = None,
    device: str = "cpu",
):
    """
    加载训练好的模型和 tokenizer。
    
    参数:
        checkpoint_path: 训练产出的 checkpoint 目录（含 config.json + pytorch_model.bin）
        model_path: 若指定则覆盖 checkpoint_path
        device: 推理设备
    
    返回:
        (model, tokenizer)
    """
    path = model_path or checkpoint_path
    
    print(f"📂 加载模型: {path}")
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        path,
        local_files_only=True,
    )
    model = model.to(device)
    model.eval()
    print(f"✅ 模型加载成功，设备: {device}")
    
    return model, tokenizer


def predict_text(
    text: str,
    model=None,
    tokenizer=None,
    checkpoint_path: str = DEFAULT_CHECKPOINT,
    device: str = "cpu",
    max_length: int = 128,
) -> dict:
    """
    对单条文本进行合规性分类。
    
    参数:
        text: 输入文本
        model: 已加载的模型（None 则自动加载）
        tokenizer: 已加载的 tokenizer（None 则自动加载）
        checkpoint_path: 模型路径（自动加载时用）
        device: 推理设备
        max_length: 最大序列长度
    
    返回:
        {
            "label": 0 或 1,
            "label_name": "合规" 或 "不合规",
            "confidence": 0.0~1.0 的置信度,
        }
    """
    if model is None or tokenizer is None:
        model, tokenizer = load_moderation_model(checkpoint_path, device=device)
    
    # tokenize
    inputs = tokenizer(
        text,
        max_length=max_length,
        padding="max_length",
        truncation=True,
        return_tensors="pt",
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}
    
    # 推理
    with torch.no_grad():
        outputs = model(**inputs, return_dict=True)
        logits = outputs.logits
        probs = F.softmax(logits, dim=-1)
    
    # 取最高概率的类别
    pred_label = int(torch.argmax(probs, dim=-1).item())
    confidence = float(probs[0, pred_label].item())
    
    return {
        "label": pred_label,
        "label_name": LABEL_MAP.get(pred_label, "未知"),
        "confidence": round(confidence, 4),
    }


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="合规校验模型预测")
    parser.add_argument(
        "--text",
        type=str,
        default="根据《民法典》，合同违约方应承担赔偿责任。",
        help="待分类的文本",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=DEFAULT_CHECKPOINT,
        help="checkpoint 目录路径",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        choices=["cpu", "cuda"],
        help="推理设备",
    )
    
    args = parser.parse_args()
    
    result = predict_text(
        text=args.text,
        checkpoint_path=args.checkpoint,
        device=args.device,
    )
    print(f"📝 输入: {args.text}")
    print(f"🏷️  结果: label={result['label']}, {result['label_name']}, confidence={result['confidence']}")


if __name__ == "__main__":
    main()
