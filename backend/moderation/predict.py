"""安全校验模块 - BERT 内容安全检查（ONNX Runtime 轻量版）"""
import os
import numpy as np
from tokenizers import Tokenizer

# 模型路径（支持环境变量配置，默认使用本地路径）
MODEL_DIR = os.environ.get("BERT_SAFETY_MODEL", os.path.join(os.path.dirname(__file__), "output"))

# 全局模型实例
_session = None
_tokenizer = None


def load_model():
    """加载安全校验模型（启动时调用一次）"""
    global _session, _tokenizer
    
    try:
        import onnxruntime as ort
        
        onnx_path = os.path.join(MODEL_DIR, "moderation.onnx")
        _session = ort.InferenceSession(onnx_path, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        _tokenizer = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))
        _tokenizer.enable_truncation(max_length=512)
        _tokenizer.enable_padding(length=512)
        
        print(f"[OK] 安全校验模型加载成功 (ONNX Runtime)")
        return True
    except Exception as e:
        print(f"[WARN] 安全校验模型加载失败: {e}")
        _session = None
        _tokenizer = None
        return False


def check_safety(text: str) -> tuple[bool, float]:
    """
    检查文本是否安全
    返回: (is_safe, confidence)
    - is_safe: True=安全, False=违规
    - confidence: 模型置信度 (0-1)
    """
    if _session is None or _tokenizer is None:
        # 模型未加载，降级为全部放行
        return True, 0.0
    
    # 截断到 512 字符（BERT 输入限制）
    text_to_check = text[:512] if len(text) > 512 else text
    
    # Tokenize
    encoding = _tokenizer.encode(text_to_check)
    input_ids = np.array([encoding.ids], dtype=np.int64)
    attention_mask = np.array([encoding.attention_mask], dtype=np.int64)
    token_type_ids = np.array([encoding.type_ids], dtype=np.int64)
    
    # Run inference
    inputs = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "token_type_ids": token_type_ids,
    }
    outputs = _session.run(None, inputs)
    logits = outputs[0]
    
    # Softmax
    exp_logits = np.exp(logits - np.max(logits, axis=-1, keepdims=True))
    probs = exp_logits / np.sum(exp_logits, axis=-1, keepdims=True)
    pred = np.argmax(probs, axis=-1).item()
    conf = probs[0][pred].item()
    
    # pred=0 表示合规，pred=1 表示违规
    is_safe = (pred == 0)
    return is_safe, conf
