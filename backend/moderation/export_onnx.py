"""
ONNX 导出模块
将训练好的 bert-base-chinese 分类模型导出为 ONNX 格式（CPU 推理用）。
"""

import os
from pathlib import Path
from typing import Optional

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification


# 默认 checkpoint 路径
DEFAULT_CHECKPOINT = os.environ.get(
    "MODERATION_CHECKPOINT",
    str(Path(__file__).parent / "output" / "checkpoint" / "final"),
)

# 默认 ONNX 输出路径
DEFAULT_ONNX_PATH = os.environ.get(
    "MODERATION_ONNX_PATH",
    str(Path(__file__).parent / "output" / "moderation.onnx"),
)


def export_to_onnx(
    checkpoint_path: str = DEFAULT_CHECKPOINT,
    output_path: str = DEFAULT_ONNX_PATH,
    model_path: Optional[str] = None,
    max_length: int = 128,
):
    """
    将训练好的模型导出为 ONNX 格式。
    
    参数:
        checkpoint_path: 训练产出的 checkpoint 目录
        output_path: ONNX 输出文件路径
        model_path: 若指定则覆盖 checkpoint_path
        max_length: 用于导出时 dummy input 的序列长度
    """
    path = model_path or checkpoint_path
    
    print(f"📂 加载模型: {path}")
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        path,
        local_files_only=True,
    )
    model.eval()
    
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    # 创建 dummy input（用于 ONNX trace）
    dummy_text = "这是一个测试文本。"
    inputs = tokenizer(
        dummy_text,
        max_length=max_length,
        padding="max_length",
        truncation=True,
        return_tensors="pt",
    )
    
    # 导出 ONNX（opset 14，兼容多数推理引擎）
    print(f"📦 导出 ONNX: {output_path}")
    torch.onnx.export(
        model,
        (inputs["input_ids"], inputs["attention_mask"]),
        output_path,
        export_params=True,
        opset_version=18,  # opset 18 避免版本转换失败
        do_constant_folding=True,
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch_size"},
            "attention_mask": {0: "batch_size"},
            "logits": {0: "batch_size"},
        },
    )
    
    file_size = os.path.getsize(output_path)
    print(f"✅ ONNX 导出成功: {output_path} ({file_size / 1024 / 1024:.1f} MB)")
    
    return output_path


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="合规校验模型 ONNX 导出")
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=DEFAULT_CHECKPOINT,
        help="checkpoint 目录路径",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=DEFAULT_ONNX_PATH,
        help="ONNX 输出文件路径",
    )
    
    args = parser.parse_args()
    export_to_onnx(
        checkpoint_path=args.checkpoint,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
