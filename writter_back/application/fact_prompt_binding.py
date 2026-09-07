"""在每次模型调用末尾附加事实约束，避免场景补写和上下文裁剪遗漏依据。"""

import json
from typing import Any, AsyncIterator

from application.errors import RetryableWorkflowError
from application.prompts.template_loader import render_prompt
from service.ports.llm_service import LLMService
from service.value_objects.chapter_constraints import ChapterConstraintSet

MAX_FACT_CONTEXT_CHARACTERS = 24000


def render_fact_constraints(snapshot: ChapterConstraintSet) -> str:
    """只渲染生效事实及其引用实体；超过预算时拒绝静默截断。"""
    facts = sorted(snapshot.active_facts, key=lambda fact: (str(fact.subject_id), fact.predicate))
    ids = {fact.subject_id for fact in facts} | {fact.object_entity_id for fact in facts if fact.object_entity_id}
    entities = sorted((item for item in snapshot.entities if item.id in ids), key=lambda item: str(item.id))
    payload = {"chapter_number": snapshot.chapter_number, "snapshot_digest": snapshot.digest,
        "status": "confirmed_constraints" if facts else "no_confirmed_facts",
        "entities": [item.model_dump(mode="json") for item in entities],
        "facts": [item.model_dump(mode="json") for item in facts]}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(encoded) > MAX_FACT_CONTEXT_CHARACTERS:
        raise RetryableWorkflowError("本章事实约束超过上下文预算，未截断或继续生成")
    return render_prompt("fact_constraints.txt", constraints=encoded)


class FactBoundLLM(LLMService):
    """节点级代理；不修改共享模型实例，不对输出做虚假的一致性认证。"""

    def __init__(self, delegate: LLMService, context: str) -> None:
        self.delegate = delegate
        self.context = context

    def _prompt(self, prompt: str) -> str:
        return prompt + "\n\n" + self.context

    async def generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
        """普通生成同样携带快照约束。"""
        return await self.delegate.generate(self._prompt(prompt), *args, **kwargs)

    async def stream_text(self, prompt: str, *args: Any, **kwargs: Any) -> AsyncIterator[str]:
        """流式正文、场景续写和补写统一携带约束。"""
        async for part in self.delegate.stream_text(self._prompt(prompt), *args, **kwargs):
            yield part

    async def structured_generate(self, prompt: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """结构化细纲和局部修订统一携带约束，并保留原有调用参数。"""
        return await self.delegate.structured_generate(self._prompt(prompt), *args, **kwargs)

    async def chat(self, messages: list[dict[str, str]], *args: Any, **kwargs: Any) -> str:
        """对话接口追加独立数据消息，不改写调用方的历史消息。"""
        return await self.delegate.chat([*messages, {"role": "user", "content": self.context}], *args, **kwargs)
