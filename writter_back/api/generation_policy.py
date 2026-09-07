"""运营暂停只阻止新生成命令，保留阅读、人工编辑和取消入口。"""
from fastapi import HTTPException
from config import settings


def ensure_generation_enabled() -> None:
    if settings.WORKFLOW_GENERATION_PAUSED:
        raise HTTPException(status_code=503, detail={'code': 'generation_paused',
            'message': '自动创作暂时暂停，已有稿件仍可查看和编辑', 'retryable': False})
