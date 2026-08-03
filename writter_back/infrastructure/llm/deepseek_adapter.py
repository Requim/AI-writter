"""DeepSeek适配器"""
import logging

import openai
from typing import Any, AsyncIterator, Dict, List, Optional
from .base import (
    STRUCTURED_OUTPUT_ATTEMPTS,
    BaseLLMAdapter,
    safe_json_parse,
    structured_result_errors,
    structured_retry_instruction,
)

logger = logging.getLogger("uvicorn")


class DeepSeekAdapter(BaseLLMAdapter):
    """DeepSeek适配器"""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        timeout: float = 180.0,
        max_retries: int = 2,
    ):
        super().__init__(api_key=api_key, model=model, timeout=timeout)
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
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
        """结构化生成，并自动纠正缺字段或类型错误的 JSON。"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        retry_errors: list[str] = []
        for attempt in range(STRUCTURED_OUTPUT_ATTEMPTS):
            request_messages = list(messages)
            if attempt:
                request_messages.append({
                    "role": "user",
                    "content": structured_retry_instruction(retry_errors),
                })
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=request_messages,
                response_format={"type": "json_object"},
                temperature=temperature,
                top_p=top_p,
            )
            content = response.choices[0].message.content or ""
            result = safe_json_parse(content)
            retry_errors = structured_result_errors(result, schema)
            if not retry_errors:
                return result
            logger.warning(
                "【DeepSeek结构化输出】结果不合格 | 尝试=%s/%s, 长度=%s, 问题=%s",
                attempt + 1, STRUCTURED_OUTPUT_ATTEMPTS, len(content), retry_errors[:12],
            )
        logger.error("【DeepSeek结构化输出】自动纠错失败 | 问题=%s", retry_errors[:12])
        return {}

    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7, top_p: float = 1.0) -> str:
        """对话生成"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
        )
        return response.choices[0].message.content
