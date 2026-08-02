"""
数据准备模块
读取 JSONL 标注文件，tokenize 并切分为 train/val 数据集。
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Tuple

from datasets import Dataset
from transformers import AutoTokenizer


# 本地模型路径（不联网）
MODEL_PATH = os.environ.get(
    "MODERATION_MODEL_PATH",
    r"D:\ai\bert-base-chinese"
)


def load_jsonl(jsonl_path: str) -> List[Dict]:
    """
    读取 JSONL 文件，每行格式: {"text": ..., "label": 0/1}
    返回 dict 列表。
    """
    records = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 跳过注释行（以 # 开头）和空行
            if not line or line.startswith("#"):
                continue
            records.append(json.loads(line))
    return records


def tokenize_and_split(
    jsonl_path: str,
    tokenizer_name: str = MODEL_PATH,
    max_length: int = 128,
    train_ratio: float = 0.8,
    seed: int = 42,
) -> Tuple[Dataset, Dataset]:
    """
    读取 JSONL → tokenize → 按 train_ratio 切分 → 返回 (train_dataset, val_dataset)。
    
    返回的 Dataset 包含字段: input_ids, attention_mask, labels。
    """
    records = load_jsonl(jsonl_path)
    texts = [r["text"] for r in records]
    labels = [r["label"] for r in records]

    # 加载 tokenizer（本地路径，不联网）
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name, local_files_only=True)

    # tokenize
    encoded = tokenizer(
        texts,
        max_length=max_length,
        padding="max_length",
        truncation=True,
        return_tensors="pt",
    )

    # 组装为 HuggingFace Dataset
    dataset = Dataset.from_dict({
        "input_ids": encoded["input_ids"],
        "attention_mask": encoded["attention_mask"],
        "labels": labels,
    })

    # 8:2 切分
    split = dataset.train_test_split(test_size=1 - train_ratio, seed=seed)
    return split["train"], split["test"]


if __name__ == "__main__":
    # 冒烟验证：检查数据能否正常加载和切分
    sample_path = Path(__file__).parent / "data" / "sample.jsonl"
    train_ds, val_ds = tokenize_and_split(str(sample_path))
    print(f"✅ 数据加载成功: train={len(train_ds)}, val={len(val_ds)}")
    print(f"   样本字段: {train_ds.column_names}")
