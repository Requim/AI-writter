"""派生状态提案保留失败证据；无效缓存不永久阻断章节后处理。"""

from application.creative.errors import CreativePause

REGENERABLE = {
    "unknown_character", "unauthorized_character_change", "thread_contract",
    "relationship_identity", "secret_identity", "foreshadow_fields", "secret_fields",
    "backdated_setup", "evidence_missing",
}


async def invalidate_patch(work, patch, error):
    """仅输出契约问题可重新生成，硬约束和事实确认仍保留暂停现场。"""
    retryable = isinstance(error, ValueError) or (isinstance(error, CreativePause) and error.reason in REGENERABLE)
    if retryable:
        await work.save("decision", patch["key"], {**patch["payload"], "validation_error": str(error)},
                        previous=patch, inputs=patch["input_versions"], status="invalid", source="system")
