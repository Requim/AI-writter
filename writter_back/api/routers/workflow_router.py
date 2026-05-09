"""工作流路由 - 支持 interrupt/resume"""
import logging
logger = logging.getLogger("uvicorn")
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, Any, Dict, AsyncGenerator
from pydantic import BaseModel
import json

from application.orchestrator import NovelOrchestrator
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.memory.postgres_memory import PostgresMemoryAdapter
from config import settings

from fastapi.responses import StreamingResponse

router = APIRouter()

# ---------- Dependency Injection ----------
_workflow_orchestrator: Optional[NovelOrchestrator] = None


async def shutdown_orchestrator():
    """应用关闭时释放编排器的连接池"""
    global _workflow_orchestrator
    if _workflow_orchestrator is not None:
        await _workflow_orchestrator.aclose()
        _workflow_orchestrator = None


async def get_orchestrator() -> NovelOrchestrator:
    global _workflow_orchestrator
    if _workflow_orchestrator is None:
        repo = PostgresNovelRepository(settings.DATABASE_URL)
        async_session = repo.async_session
        # PostgresMemoryAdapter expects the async URL with +asyncpg
        memory_service = PostgresMemoryAdapter(settings.DATABASE_URL, async_session)
        llm_config = {
            "provider": settings.DEFAULT_LLM_PROVIDER,
            "model": settings.DEFAULT_MODEL_NAME,
            "deepseek_api_key": settings.DEEPSEEK_API_KEY,
            "openai_api_key": settings.OPENAI_API_KEY,
            "anthropic_api_key": settings.ANTHROPIC_API_KEY,
        }
        _workflow_orchestrator = NovelOrchestrator(
            repository=repo,
            memory_service=memory_service,
            llm_config=llm_config,
        )
    return _workflow_orchestrator


# ---------- Request / Response Schemas ----------
class WorkflowInvokeRequest(BaseModel):
    input: Optional[Dict[str, Any]] = None
    command: Optional[Dict[str, Any]] = None


# ---------- Endpoints ----------
@router.post("/{thread_id}/invoke")
async def invoke_workflow(
    thread_id: str,
    request: WorkflowInvokeRequest,
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
):
    """
    启动或恢复工作流
    - 首次调用：传入 input（包含 novel_id, novel_type 等）
    - 恢复调用：传入 command: {"resume": ...}
    """
    mode = '恢复' if request.command is not None else '启动'
    logger.info(f"{'='*60}")
    logger.info(f"【工作流API·{mode}】进入 | thread_id={thread_id}")
    if request.command is not None:
        logger.info(f"【工作流API·{mode}】请求体={request.model_dump()}")
    
    # 检查是否正在执行中（防重复）
    if orchestrator.is_executing(thread_id):
        logger.info(f"【工作流API·{mode}】thread_id={thread_id} 正在执行中, 拒绝并发请求")
        raise HTTPException(status_code=409, detail="该工作流正在执行中，请等待完成后再试")
    orchestrator.mark_executing(thread_id, True)
    
    import asyncio
    
    try:
        if request.command is not None:
            resume_value = request.command.get("resume")
            logger.info(f"【工作流API·恢复】thread_id={thread_id}, 恢复值类型={type(resume_value).__name__}, 恢复值预览={str(resume_value)[:80]}")
            try:
                result = await asyncio.wait_for(
                    orchestrator.resume(thread_id, resume_value),
                    timeout=600.0
                )
            except asyncio.TimeoutError:
                logger.info(f"【工作流API·恢复】超时! thread_id={thread_id}")
                raise HTTPException(status_code=504, detail="工作流执行超时，请稍后重试")
        else:
            input_data = request.input or {}
            input_data.setdefault("novel_id", thread_id)
            logger.info(f"【工作流API·启动】thread_id={thread_id}, 输入字段={list(input_data.keys())}")
            try:
                result = await asyncio.wait_for(
                    orchestrator.invoke(thread_id, input_data),
                    timeout=600.0
                )
            except asyncio.TimeoutError:
                logger.info(f"【工作流API·启动】超时! thread_id={thread_id}")
                raise HTTPException(status_code=504, detail="工作流执行超时，请稍后重试")
        
        has_interrupt = "__interrupt__" in str(type(result)) or (isinstance(result, dict) and "__interrupt__" in result)
        logger.info(f"【工作流API·{mode}】完成 | thread_id={thread_id}, 结果类型={type(result).__name__}, 产生中断={'是' if has_interrupt else '否'}")
        # 诊断：打印中断数据的前200字符
        if has_interrupt and isinstance(result, dict):
            interrupt_raw = result.get("__interrupt__")
            if interrupt_raw:
                first_int = interrupt_raw[0] if hasattr(interrupt_raw, '__getitem__') else None
                int_value = getattr(first_int, 'value', str(first_int)[:200]) if first_int else 'N/A'
                logger.info(f"【工作流API·诊断】中断数量={len(interrupt_raw) if hasattr(interrupt_raw, '__len__') else '?'}, 第一个中断value={str(int_value)[:200]}")
        logger.info(f"{'='*60}")
        return result
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        logger.info(f"【工作流API】超时(外层捕获) | thread_id={thread_id}")
        logger.info(f"{'='*60}")
        raise HTTPException(status_code=504, detail="工作流执行超时，请检查后端日志")
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.info(f"【工作流API】错误 | thread_id={thread_id}, 错误={str(e)}")
        logger.info(f"{'='*60}")
        raise HTTPException(status_code=500, detail=f"工作流执行失败: {str(e)}")
    finally:
        orchestrator.mark_executing(thread_id, False)


@router.get("/{thread_id}/state")
async def get_workflow_state(
    thread_id: str,
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
):
    """
    获取工作流当前状态
    - 返回是否有待处理的中断及其内容
    """
    await orchestrator._ensure_workflow()
    config = orchestrator._make_config(thread_id)
    import asyncio
    try:
        state = await asyncio.wait_for(
            orchestrator._workflow.aget_state(config),
            timeout=10.0
        )
    except asyncio.TimeoutError:
        # 超时：可能 checkpoint 不存在，返回空状态
        return {
            "thread_id": thread_id,
            "has_interrupt": False,
            "interrupts": [],
            "state_values": {},
        }

    # 获取中断信息
    tasks = getattr(state, 'tasks', []) or []
    pending_interrupts = []
    for task in tasks:
        for interrupt in (task.interrupts or []):
            pending_interrupts.append({
                "value": interrupt.value,
                "resumable": getattr(interrupt, 'resumable', True),
            })

    return {
        "thread_id": thread_id,
        "has_interrupt": len(pending_interrupts) > 0,
        "interrupts": pending_interrupts,
        "state_values": getattr(state, 'values', {}),
    }


@router.post("/{thread_id}/stream")
async def stream_workflow_post(
    thread_id: str,
    request: WorkflowInvokeRequest,
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
):
    """SSE 流式获取工作流执行过程（POST 版本，支持恢复）"""
    # 检查是否正在执行中（防重复）
    if orchestrator.is_executing(thread_id):
        logger.info(f"【工作流API·SSE】thread_id={thread_id} 正在执行中, 拒绝并发请求")
        raise HTTPException(status_code=409, detail="该工作流正在执行中，请等待完成后再试")
    orchestrator.mark_executing(thread_id, True)

    from fastapi.responses import StreamingResponse
    from fastapi.encoders import jsonable_encoder

    async def generate() -> AsyncGenerator[str, None]:
        try:
            if request.command is not None:
                # Resume path: use ainvoke (via orchestrator.resume) which properly
                # handles Command(resume=...) — astream does NOT in langgraph 1.1.x.
                resume_value = request.command.get("resume")
                result = await orchestrator.resume(thread_id, resume_value)
                data = json.dumps(jsonable_encoder(result), ensure_ascii=False)
                yield f"data: {data}\n\n"
            else:
                # New invocation path: use astream for real-time streaming
                input_data = request.input or {"novel_id": thread_id}
                input_data.setdefault("novel_id", thread_id)
                async for chunk in orchestrator.stream(thread_id, input_data):
                    if isinstance(chunk, dict):
                        data = json.dumps(jsonable_encoder(chunk), ensure_ascii=False)
                    else:
                        data = str(chunk)
                    yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"
        finally:
            orchestrator.mark_executing(thread_id, False)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{thread_id}/stream")
async def stream_workflow(
    thread_id: str,
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
):
    """SSE 流式获取工作流执行过程"""
    # 检查是否正在执行中（防重复）
    if orchestrator.is_executing(thread_id):
        logger.info(f"【工作流API·SSE-GET】thread_id={thread_id} 正在执行中, 拒绝并发请求")
        raise HTTPException(status_code=409, detail="该工作流正在执行中，请等待完成后再试")
    orchestrator.mark_executing(thread_id, True)

    from fastapi.responses import StreamingResponse
    from fastapi.encoders import jsonable_encoder

    async def generate() -> AsyncGenerator[str, None]:
        try:
            async for chunk in orchestrator.stream(thread_id, {"novel_id": thread_id}):
                if isinstance(chunk, dict):
                    data = json.dumps(jsonable_encoder(chunk), ensure_ascii=False)
                else:
                    data = str(chunk)
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            import traceback
            traceback.print_exc()
            error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"
        finally:
            orchestrator.mark_executing(thread_id, False)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
