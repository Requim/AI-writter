"""DeepSeek适配器"""
import json
import openai
from typing import Dict, List, Optional, Any
from .base import BaseLLMAdapter, safe_json_parse


class DeepSeekAdapter(BaseLLMAdapter):
    """DeepSeek适配器"""

    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        super().__init__(api_key=api_key, model=model)
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            timeout=180.0,
            max_retries=0,
        )

    async def generate(self, prompt: str, system_prompt: Optional[str] = None,
                       temperature: float = 0.7) -> str:
        """生成文本"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature
        )
        return response.choices[0].message.content

    async def structured_generate(self, prompt: str, schema: Dict[str, Any],
                                  system_prompt: Optional[str] = None,
                                  max_retries: int = 2) -> Dict[str, Any]:
        """结构化生成（含 JSON 修复和重试）"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        last_error = None
        for attempt in range(max_retries + 1):
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            content = response.choices[0].message.content
            if not content:
                return {}

            result = safe_json_parse(content)
            if result:
                return result

            last_error = ValueError(f"JSON解析失败: {content[:200]}")
            print(f"【DeepSeek】JSON解析失败(第{attempt+1}次)", flush=True)

            if attempt == max_retries:
                break

            # 追加错误反馈，让模型修正格式
            print(f"【DeepSeek】重试第{attempt+2}次...", flush=True)
            messages.append({"role": "assistant", "content": content[:500]})
            messages.append({"role": "user", "content": "你的上一条回复 JSON 格式有误，请严格按照 JSON 格式重新输出，确保所有逗号、引号、花括号正确闭合。"})

        print(f"【DeepSeek】所有重试失败，返回空字典。最后错误: {last_error}", flush=True)
        return {}

    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        """对话生成"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature
        )
        return response.choices[0].message.content
