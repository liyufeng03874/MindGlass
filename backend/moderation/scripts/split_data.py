#!/usr/bin/env python
"""
重新划分 agent_corpus.jsonl 为 train.jsonl / val.jsonl（80/20）
- 2000 条全量混合，随机 seed=42 确保可重复
- label 分层抽样，保证 train/val 中 0/1 比例一致
"""
import json, random, os

CORPUS = os.path.join(os.path.dirname(__file__), '..', 'data', 'agent_corpus.jsonl')
TRAIN_OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'train.jsonl')
VAL_OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'val.jsonl')

def main():
    # 读取全部样本
    with open(CORPUS, 'r', encoding='utf-8') as f:
        data = [json.loads(line) for line in f]
    
    print(f"总样本数: {len(data)}")
    
    # 按 label 分层
    label_0 = [d for d in data if d['label'] == 0]
    label_1 = [d for d in data if d['label'] == 1]
    print(f"label=0: {len(label_0)}, label=1: {len(label_1)}")
    
    # 随机打乱（固定 seed 确保可重复）
    random.seed(42)
    random.shuffle(label_0)
    random.shuffle(label_1)
    
    # 80/20 分层划分
    def split(lst, ratio=0.8):
        n = int(len(lst) * ratio)
        return lst[:n], lst[n:]
    
    train_0, val_0 = split(label_0)
    train_1, val_1 = split(label_1)
    
    train = train_0 + train_1
    val = val_0 + val_1
    
    # 再次打乱 train/val 内部顺序
    random.shuffle(train)
    random.shuffle(val)
    
    print(f"train: {len(train)} (label0={len(train_0)}, label1={len(train_1)})")
    print(f"val:   {len(val)} (label0={len(val_0)}, label1={len(val_1)})")
    
    # 写入文件
    os.makedirs(os.path.dirname(TRAIN_OUT), exist_ok=True)
    with open(TRAIN_OUT, 'w', encoding='utf-8') as f:
        for item in train:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    with open(VAL_OUT, 'w', encoding='utf-8') as f:
        for item in val:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"✅ 已写入 {TRAIN_OUT} 和 {VAL_OUT}")

if __name__ == '__main__':
    main()
