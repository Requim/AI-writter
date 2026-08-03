"""LLM适配器基类"""
import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from json_repair import repair_json

from service.ports.llm_service import LLMService

logger = logging.getLogger("uvicorn")
STRUCTURED_OUTPUT_ATTEMPTS = 3


def _matches_schema_type(value: object, expected: str) -> bool:
    """判断模型字段是否符合轻量 schema 类型。"""
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected_types = {
        "object": dict,
        "array": list,
        "string": str,
        "boolean": bool,
    }
    expected_type = expected_types.get(expected)
    return expected_type is None or isinstance(value, expected_type)


def _collect_schema_errors(
    value: object, schema: object, path: str, errors: list[str]
) -> None:
    if isinstance(schema, str):
        if not _matches_schema_type(value, schema):
            errors.append(f"{path} 应为 {schema}")
        return
    if not isinstance(schema, dict):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _collect_schema_errors(item, schema, f"{path}[{index}]", errors)
        return
    if not isinstance(value, dict):
        errors.append(f"{path} 应为 object")
        return
    for key, child_schema in schema.items():
        child_path = f"{path}.{key}" if path else key
        if key not in value:
            errors.append(f"{child_path} 缺失")
            continue
        _collect_schema_errors(value[key], child_schema, child_path, errors)


def structured_result_errors(
    result: object, schema: Dict[str, Any]
) -> list[str]:
    """返回结构化模型结果相对 schema 的字段错误。"""
    errors: list[str] = []
    _collect_schema_errors(result, schema, "", errors)
    return errors


def structured_retry_instruction(errors: list[str]) -> str:
    """生成不携带业务数据的结构化输出纠错提示。"""
    detail = "；".join(errors[:12]) or "JSON 为空或无法解析"
    return (
        "上一次输出不符合要求，请重新输出且只输出完整 JSON。"
        f"具体问题：{detail}。"
        "必须包含 schema 的全部字段并保持字段类型正确；压缩说明文字，确保数组、对象完整闭合。"
    )


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
