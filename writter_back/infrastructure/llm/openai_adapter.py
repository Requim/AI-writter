"""OpenAI适配器"""
import logging

import openai
from typing import Any, AsyncIterator, Dict, List, Optional
from .base import BaseLLMAdapter, safe_json_parse


logger = logging.getLogger("uvicorn")


class OpenAIAdapter(BaseLLMAdapter):
    """OpenAI适配器"""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        timeout: float = 180.0,
        base_url: str | None = None,
        max_retries: int = 2,
    ):
        super().__init__(api_key=api_key, model=model, timeout=timeout)
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    async def generate(self, prompt: str, system_prompt: Optional[str] = None,
                      temperature: float = 0.7, top_p: float = 1.0) -> str:
        """生成文本"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
        )
        return response.choices[0].message.content

    async def stream_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        top_p: float = 1.0,
    ) -> AsyncIterator[str]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            stream=True,
        )
        async for chunk in stream:
            text = chunk.choices[0].delta.content if chunk.choices else None
            if text:
                yield text

    async def structured_generate(self, prompt: str, schema: Dict[str, Any],
                                 system_prompt: Optional[str] = None,
                                 temperature: float = 0.3,
                                 top_p: float = 1.0) -> Dict[str, Any]:
        """Stream JSON and retry once when the compatible gateway returns invalid output."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        best_result: Dict[str, Any] = {}
        expected_keys = set(schema)
        for attempt in range(2):
            request_messages = list(messages)
            if attempt:
                request_messages.append({
                    "role": "user",
                    "content": (
                        "上一次输出不是完整的JSON。请重新输出且只输出JSON；"
                        "必须包含schema全部顶层字段，压缩说明文字并确保数组和对象完整闭合。"
                    ),
                })
            try:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=request_messages,
                    response_format={"type": "json_object"},
                    temperature=temperature,
                    top_p=top_p,
                    stream=True,
                )
                parts: list[str] = []
                finish_reason: str | None = None
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    finish_reason = getattr(choice, "finish_reason", None) or finish_reason
                    content = choice.delta.content
                    if content:
                        parts.append(content)
                raw = "".join(parts)
                result = safe_json_parse(raw)
                if result:
                    best_result = result
                if result and expected_keys.issubset(result):
                    return result
                logger.warning(
                    "【OpenAI结构化输出】结果不完整 | 尝试=%s/2, 长度=%s, finish_reason=%s, 缺少字段=%s",
                    attempt + 1,
                    len(raw),
                    finish_reason or "unknown",
                    sorted(expected_keys - set(result)),
                )
            except Exception:
                if best_result and attempt:
                    logger.exception("【OpenAI结构化输出】重试请求失败，使用首次可修复结果")
                    return best_result
                raise
        return best_result

    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7, top_p: float = 1.0) -> str:
        """对话生成"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
        )
        return response.choices[0].message.content
