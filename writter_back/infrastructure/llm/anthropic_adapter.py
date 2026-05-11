"""Anthropic适配器"""
import anthropic
from typing import Dict, List, Optional, Any
from .base import BaseLLMAdapter, safe_json_parse


class AnthropicAdapter(BaseLLMAdapter):
    """Anthropic适配器"""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        super().__init__(api_key=api_key, model=model)
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, prompt: str, system_prompt: Optional[str] = None,
                      temperature: float = 0.7, top_p: float = 1.0) -> str:
        """生成文本"""
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": temperature,
            "top_p": top_p,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self.client.messages.create(**kwargs)
        return response.content[0].text

    async def structured_generate(self, prompt: str, schema: Dict[str, Any],
                                 system_prompt: Optional[str] = None,
                                 temperature: float = 0.3,
                                 top_p: float = 1.0) -> Dict[str, Any]:
        """结构化生成"""
        combined_system = "You must respond with valid JSON matching the requested schema."
        if system_prompt:
            combined_system = f"{system_prompt}\n\n{combined_system}"

        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": temperature,
            "top_p": top_p,
            "messages": [{"role": "user", "content": prompt}],
        }
        if combined_system:
            kwargs["system"] = combined_system

        response = await self.client.messages.create(**kwargs)
        content = response.content[0].text
        return safe_json_parse(content)

    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7, top_p: float = 1.0) -> str:
        """对话生成"""
        system_prompt = None
        chat_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": temperature,
            "top_p": top_p,
            "messages": chat_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self.client.messages.create(**kwargs)
        return response.content[0].text
