"""OpenAI适配器"""
import asyncio
import logging

import openai
from typing import Any, AsyncIterator, Dict, List, Optional
from .base import (
    BaseLLMAdapter,
    safe_json_parse,
    structured_output_attempts,
    structured_result_errors,
    structured_retry_instruction,
)


logger = logging.getLogger("uvicorn")


def _is_retryable_stream_error(exc: openai.APIError) -> bool:
    """识别 SDK 不会自动恢复的瞬时流式传输错误。"""
    message = str(exc).lower()
    return "stream" in message and "interrupt" in message


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
                                 top_p: float = 1.0,
                                 max_attempts: int | None = None) -> Dict[str, Any]:
        """流式生成 JSON，并自动纠正不完整或类型错误的结果。"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        retry_errors: list[str] = []
        attempts = structured_output_attempts(max_attempts)
        for attempt in range(attempts):
            request_messages = list(messages)
            if attempt:
                request_messages.append({
                    "role": "user",
                    "content": structured_retry_instruction(retry_errors),
                })
            raw, finish_reason = await self._stream_structured_response(
                request_messages,
                temperature=temperature,
                top_p=top_p,
            )
            result = safe_json_parse(raw)
            retry_errors = structured_result_errors(result, schema)
            if not retry_errors:
                return result
            logger.warning(
                "【OpenAI结构化输出】结果不合格 | 尝试=%s/%s, 长度=%s, finish_reason=%s, 问题=%s",
                attempt + 1, attempts, len(raw),
                finish_reason or "unknown", retry_errors[:12],
            )
        return {}

    async def _stream_structured_response(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        top_p: float,
    ) -> tuple[str, str | None]:
        """收集结构化响应，并对瞬时流中断进行一次原请求重试。"""
        for transport_attempt in range(2):
            try:
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
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
                    if choice.delta.content:
                        parts.append(choice.delta.content)
                return "".join(parts), finish_reason
            except openai.APIError as exc:
                if transport_attempt or not _is_retryable_stream_error(exc):
                    raise
                logger.warning("【OpenAI结构化输出】响应流中断，重试当前请求一次")
                await asyncio.sleep(0.5)
        raise RuntimeError("unreachable structured stream retry state")

    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7, top_p: float = 1.0) -> str:
        """对话生成"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
        )
        return response.choices[0].message.content
