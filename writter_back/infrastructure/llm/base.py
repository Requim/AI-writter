"""LLM适配器基类"""
import json
import re
from abc import abstractmethod
from typing import Dict, List, Optional, Any
from service.ports.llm_service import LLMService


def _repair_json(raw: str) -> str:
    """尝试修复常见的 JSON 格式错误"""
    raw = re.sub(r'^```(?:json)?\s*', '', raw.strip())
    raw = re.sub(r'\s*```$', '', raw.strip())
    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]
    raw = re.sub(r',\s*}', '}', raw)
    raw = re.sub(r',\s*]', ']', raw)
    if raw.count('"') % 2 != 0:
        raw = raw.rstrip() + '"'
    return raw


def safe_json_parse(content: str) -> Dict[str, Any]:
    """安全解析 JSON，失败则返回空字典"""
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        try:
            return json.loads(_repair_json(content))
        except json.JSONDecodeError:
            print(f"【JSON解析】修复后仍失败，返回空字典。内容前200字符: {content[:200]}", flush=True)
            return {}


class BaseLLMAdapter(LLMService):
    """LLM适配器基类"""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.temperature = 0.7

    async def generate(self, prompt: str, system_prompt: Optional[str] = None,
                       temperature: float = 0.7) -> str:
        raise NotImplementedError

    async def structured_generate(self, prompt: str, schema: Dict[str, Any],
                                  system_prompt: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        raise NotImplementedError
