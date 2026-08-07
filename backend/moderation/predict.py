"""安全校验模块 - BERT 内容安全检查"""
import os
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# 模型路径（支持环境变量配置，默认使用本地路径）
MODEL_PATH = os.environ.get("BERT_SAFETY_MODEL", os.path.join(os.path.dirname(__file__), "output", "checkpoint", "final"))

# 全局模型实例
_model = None
_tokenizer = None
_device = None


def load_model():
    """加载安全校验模型（启动时调用一次）"""
    global _model, _tokenizer, _device
    
    try:
        _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
        _model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH, local_files_only=True)
        _model.to(_device)
        _model.eval()
        print(f"[OK] 安全校验模型加载成功，设备: {_device}")
        return True
    except Exception as e:
        print(f"[WARN] 安全校验模型加载失败: {e}")
        _model = None
        _tokenizer = None
        _device = None
        return False


def check_safety(text: str) -> tuple[bool, float]:
    """
    检查文本是否安全
    返回: (is_safe, confidence)
    - is_safe: True=安全, False=违规
    - confidence: 模型置信度 (0-1)
    """
    if _model is None or _tokenizer is None:
        # 模型未加载，降级为全部放行
        return True, 0.0
    
    # 截断到 512 字符（BERT 输入限制）
    text_to_check = text[:512] if len(text) > 512 else text
    
    inputs = _tokenizer(text_to_check, return_tensors="pt", truncation=True, max_length=512, padding=True)
    inputs = {k: v.to(_device) for k, v in inputs.items()}
    
    with torch.no_grad():
        outputs = _model(**inputs)
        logits = outputs[0] if isinstance(outputs, tuple) else outputs.logits
        probs = torch.softmax(logits, dim=-1)
        pred = torch.argmax(probs, dim=-1).item()
        conf = probs[0][pred].item()
    
    # pred=0 表示合规，pred=1 表示违规
    is_safe = (pred == 0)
    return is_safe, conf
