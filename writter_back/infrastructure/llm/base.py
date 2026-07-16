"""LLM适配器基类"""
import logging
logger = logging.getLogger("uvicorn")
import json
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from json_repair import repair_json

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
    # 补全不匹配的引号
    if raw.count('"') % 2 != 0:
        raw = raw.rstrip() + '"'
    # 补全未闭合的花括号（截断场景）
    opens = raw.count('{')
    closes = raw.count('}')
    if opens > closes:
        raw += '}' * (opens - closes)
    opens_b = raw.count('[')
    closes_b = raw.count(']')
    if opens_b > closes_b:
        raw += ']' * (opens_b - closes_b)
    return raw


def safe_json_parse(content: str) -> Dict[str, Any]:
    """Parse structured output, repairing common model truncation when possible."""
    if not content:
        return {}
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError as initial_error:
        try:
            repaired = repair_json(content, return_objects=True)
            if isinstance(repaired, dict):
                logger.info(
                    "【JSON解析】已修复模型输出 | 原始长度=%s, 初始错误=%s",
                    len(content),
                    initial_error.msg,
                )
                return repaired
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

        # Keep the small local repair as a final fallback for fenced responses.
        try:
            parsed = json.loads(_repair_json(content))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError as repair_error:
            logger.warning(
                "【JSON解析】修复失败 | 原始长度=%s, 错误位置=%s",
                len(content),
                repair_error.pos,
            )
            return {}


class BaseLLMAdapter(LLMService):
    """LLM适配器基类"""

    def __init__(self, api_key: str, model: str, timeout: float = 180.0):
        if not api_key:
            raise ValueError(f"Missing API key for model {model}")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = 0.7

    async def generate(self, prompt: str, system_prompt: Optional[str] = None,
                       temperature: float = 0.7, top_p: float = 1.0) -> str:
        raise NotImplementedError

    def stream_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        top_p: float = 1.0,
    ) -> AsyncIterator[str]:
        raise NotImplementedError

    async def structured_generate(self, prompt: str, schema: Dict[str, Any],
                                  system_prompt: Optional[str] = None,
                                  temperature: float = 0.3,
                                  top_p: float = 1.0) -> Dict[str, Any]:
        raise NotImplementedError

    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7, top_p: float = 1.0) -> str:
        raise NotImplementedError
