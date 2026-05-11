"""OpenAI适配器"""
import openai
from typing import Dict, List, Optional, Any
from .base import BaseLLMAdapter, safe_json_parse


class OpenAIAdapter(BaseLLMAdapter):
    """OpenAI适配器"""

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        super().__init__(api_key=api_key, model=model)
        self.client = openai.AsyncOpenAI(api_key=api_key)

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

    async def structured_generate(self, prompt: str, schema: Dict[str, Any],
                                 system_prompt: Optional[str] = None,
                                 temperature: float = 0.3,
                                 top_p: float = 1.0) -> Dict[str, Any]:
        """结构化生成"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=temperature,
            top_p=top_p,
        )

        content = response.choices[0].message.content
        return safe_json_parse(content)

    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7, top_p: float = 1.0) -> str:
        """对话生成"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
        )
        return response.choices[0].message.content
