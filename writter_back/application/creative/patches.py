"""派生状态提案保留失败证据；无效缓存不永久阻断章节后处理。"""

from application.creative.errors import CreativePause
from application.creative.artifacts import json_text

REGENERABLE = {
    "unknown_character", "unauthorized_character_change", "thread_contract",
    "relationship_identity", "secret_identity", "foreshadow_fields", "secret_fields",
    "backdated_setup", "evidence_missing",
}


async def invalidate_patch(work, patch, error):
    """仅输出契约问题可重新生成，硬约束和事实确认仍保留暂停现场。"""
    if _retryable(error):
        await work.save("decision", patch["key"], {**patch["payload"], "validation_error": str(error)},
                        previous=patch, inputs=patch["input_versions"], status="invalid", source="system")


def _retryable(error):
    return isinstance(error, ValueError) or (
        isinstance(error, CreativePause) and error.reason in REGENERABLE)


async def apply_generated_patch(work, key, chapter, prompt_builder, schema, apply_payload):
    """Reuse durable metadata; allow one repair without overriding hard constraints."""
    patch = await work.latest("decision", key)
    for attempt in range(2):
        if patch is None or patch["status"] == "invalid":
            prompt = await prompt_builder()
            if patch:
                prompt += "\n上次派生状态提案未通过校验；只修正元数据，不改正文或绕过硬约束：\n" + json_text(
                    {"validation_error": patch["payload"].get("validation_error"),
                     "rejected": patch["payload"]})
            result = await work.generate(prompt, schema, max_attempts=1)
            patch = await work.save("decision", key, result, previous=patch,
                inputs={"chapter": chapter["version"]})
        try:
            return await apply_payload(patch["payload"])
        except (ValueError, CreativePause) as error:
            await invalidate_patch(work, patch, error)
            if attempt or not _retryable(error):
                raise
            patch = await work.latest("decision", key)
