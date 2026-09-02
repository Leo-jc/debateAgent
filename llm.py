"""统一 LLM 调用封装：单网关（OpenAI 兼容），chat + chat_stream。

已验证的网关行为（2026-09-02）：
- GLM 系列默认开思考模式，reasoning_content 先产出；max_tokens 过小会
  把 content 挤空，因此 GLM 请求带较大的 max_tokens 兜底。
- 两家均支持 response_format={"type": "json_object"}。
- 流式增量在 delta.content；思考增量在 delta.reasoning_content（忽略）。
"""
import json
import time
from collections.abc import Generator
from typing import Any

from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL

MAX_RETRIES = 2            # 失败后自动重试次数
GLM_LARGE_MAX_TOKENS = 8192  # GLM 思考模式会占用 max_tokens，给足余量

_client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


def _is_glm(model: str) -> bool:
    return model.startswith("glm")


def _call_kwargs(
    model: str,
    messages: list[dict[str, str]],
    json_mode: bool,
    max_tokens: int | None,
) -> dict[str, Any]:
    """组装请求参数；GLM 用大 max_tokens 防止思考占用挤空正文。"""
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if max_tokens is not None:
        kwargs["max_tokens"] = (
            max(max_tokens, GLM_LARGE_MAX_TOKENS) if _is_glm(model) else max_tokens
        )
    return kwargs


def chat(
    model: str,
    messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
    max_tokens: int | None = None,
) -> str:
    """非流式调用，返回 assistant 正文。失败自动重试 MAX_RETRIES 次（指数退避）。"""
    kwargs = _call_kwargs(model, messages, json_mode, max_tokens)
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = _client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as err:  # noqa: BLE001 网络/限流/超时统一重试
            last_err = err
            if attempt < MAX_RETRIES:
                time.sleep(2**attempt)  # 1s -> 2s
    raise last_err  # type: raise[misc]


def chat_stream(
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
) -> Generator[str, None, None]:
    """流式调用，逐片段产出正文。失败自动重试（重试时从头再流）。"""
    kwargs = _call_kwargs(model, messages, False, max_tokens)
    kwargs["stream"] = True
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with _client.chat.completions.create(**kwargs) as stream:
                for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content
            return
        except Exception as err:  # noqa: BLE001
            last_err = err
            if attempt < MAX_RETRIES:
                time.sleep(2**attempt)
    raise last_err  # type: raise[misc]


def parse_json(text: str) -> dict[str, Any]:
    """从模型返回中提取 JSON 对象。容忍 ```json 围栏和前后杂文。"""
    text = text.strip()
    if text.startswith("```"):
        # 去掉 ```json / ``` 围栏
        lines = text.splitlines()
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 退化：截取第一个 { 到最后一个 } 之间
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise
