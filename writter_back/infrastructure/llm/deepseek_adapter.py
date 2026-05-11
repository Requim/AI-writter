"""DeepSeek适配器"""
import logging
logger = logging.getLogger("uvicorn")
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
                                  max_retries: int = 2,
                                  temperature: float = 0.3,
                                  top_p: float = 1.0) -> Dict[str, Any]:
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
                temperature=temperature,
                top_p=top_p,
            )
            content = response.choices[0].message.content
            if not content:
                return {}

            result = safe_json_parse(content)
            if result:
                return result

            error_detail = ""
            try:
                json.loads(content)
            except json.JSONDecodeError as e:
                error_detail = str(e)

            last_error = ValueError(f"JSON解析失败: {content[:200]}")
            logger.info(f"【DeepSeek】JSON解析失败(第{attempt+1}次) | {error_detail}")

            if attempt == max_retries:
                break

            # 追加具体错误反馈，让模型修正格式
            logger.info(f"【DeepSeek】重试第{attempt+2}次...")
            messages.append({"role": "assistant", "content": content[:500]})
            fix_instruction = (
                f"上一条回复 JSON 解析失败：{error_detail}\n"
                f"请特别注意：\n"
                f"1. 字符串中的双引号（如对话内容、引用语）必须用反斜杠转义为 \\\"\n"
                f"2. 中文字符中的破折号——、省略号……等特殊符号不需要转义，直接使用\n"
                f"3. 确保所有花括号 {{}} 和方括号 [] 正确闭合和匹配\n"
                f"请严格按照 JSON 格式重新输出完整的 JSON 对象。"
            )
            messages.append({"role": "user", "content": fix_instruction})

        logger.info(f"【DeepSeek】所有重试失败，返回空字典。最后错误: {last_error}")
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
