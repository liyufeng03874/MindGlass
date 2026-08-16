"""LLM 调用封装 — 复用 OpenAI 兼容接口"""

import os
from openai import OpenAI
from typing import Generator

from dotenv import load_dotenv
# .env 在仓库根目录（backend 的上级），不在 backend/ 里——按文件位置定位，避免依赖启动 cwd
_ROOT_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
load_dotenv(_ROOT_ENV)
load_dotenv()  # 兜底：当前目录的 .env 仍可覆盖

LLM_MODEL = os.getenv("MODEL", "qwen3.6-plus")

client = OpenAI(
    api_key=os.getenv("API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL", ""),
)


def generate(prompt: str, system_prompt: str = "", model: str = None, temperature: float = 0.0) -> str:
    """调用 LLM 生成回答（完整返回）"""
    model_name = model or LLM_MODEL
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    resp = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
        max_tokens=2048,
        # 火山方舟思考开关：关闭深度思考（思考内容在 reasoning_content，默认代码读不到，
        # 思考过长时 content 为空 -> 上层误判超时）
        extra_body={"thinking": {"type": "disabled"}},
    )
    return resp.choices[0].message.content or ""


def generate_stream(prompt: str, system_prompt: str = "", model: str = None, temperature: float = 0.0) -> Generator[str, None, str]:
    """流式调用 LLM"""
    model_name = model or LLM_MODEL
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    full_text = ""
    stream = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
        max_tokens=2048,
        stream=True,
        # 火山方舟思考开关：同上，关闭深度思考保证输出直出
        extra_body={"thinking": {"type": "disabled"}},
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            token = chunk.choices[0].delta.content
            full_text += token
            yield token
    return full_text
