"""在SDK实际发请求的位置记账；旧模式保留原客户端与重试行为。"""

from contextlib import asynccontextmanager
from typing import Any

from service.ports.model_meter import active_model_meter


def usage_dict(response: Any) -> dict:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    raw = usage.model_dump() if hasattr(usage, "model_dump") else usage
    return raw if isinstance(raw, dict) else {}


async def completion(client: Any, *, provider: str = "openai", **kwargs: Any) -> Any:
    """先持久化消耗，再发送一次关闭SDK隐式重试的请求。"""
    meter = active_model_meter.get()
    request_id = await meter.reserve() if meter else None
    selected = client.with_options(max_retries=0) if meter else client
    create = selected.messages.create if provider == "anthropic" else selected.chat.completions.create
    kwargs = unique_creative_rules(kwargs, provider) if meter else kwargs
    annotations = applied_style_annotations(kwargs) if meter else {}
    response = await create(**kwargs)
    if not meter:
        return response
    if kwargs.get("stream"):
        return _metered_stream(response, meter, request_id, annotations)
    await meter.finish(request_id, {**usage_dict(response), **annotations})
    return response


async def _metered_stream(stream: Any, meter: Any, request_id: str, annotations=None):
    usage = {}
    try:
        async for chunk in stream:
            usage = usage_dict(chunk) or usage
            yield chunk
        await meter.finish(request_id, {**usage, **(annotations or {})})
    finally:
        close = getattr(stream, "close", None)
        if close:
            await close()


@asynccontextmanager
async def anthropic_stream(client: Any, **kwargs: Any):
    """Anthropic流式管理器同样逐次记账，异常中断保持unknown状态。"""
    meter = active_model_meter.get()
    request_id = await meter.reserve() if meter else None
    selected = client.with_options(max_retries=0) if meter else client
    kwargs = unique_creative_rules(kwargs, "anthropic") if meter else kwargs
    async with selected.messages.stream(**kwargs) as stream:
        yield stream
        if meter:
            message = await stream.get_final_message()
            await meter.finish(request_id, {**usage_dict(message), **applied_style_annotations(kwargs)})


def unique_creative_rules(kwargs, provider):
    """嵌套模板共享规则只发送一份，避免重复注入三组作者对照。"""
    from application.creative.runtime import active_creative_rules
    rules = active_creative_rules.get()
    if not rules:
        return kwargs
    updated, found = dict(kwargs), False
    messages = []
    for message in kwargs.get("messages", []):
        item = dict(message)
        content = item.get("content")
        if isinstance(content, str) and rules in content:
            found = True
            item["content"] = content.replace(rules, "")
        messages.append(item)
    system = kwargs.get("system", "")
    if isinstance(system, str) and rules in system:
        found = True
        updated["system"] = system.replace(rules, "")
    if not found:
        return kwargs
    if provider == "anthropic":
        updated["system"] = str(updated.get("system") or "") + rules
    else:
        messages.insert(0, {"role": "system", "content": rules})
    updated["messages"] = messages
    return updated


def applied_style_annotations(kwargs):
    """只有本次物理请求确实携带审美规则，才记录应用而不是仅编译。"""
    from application.creative.runtime import active_creative_rules, active_style_evidence
    evidence, rules = active_style_evidence.get(), active_creative_rules.get()
    contents = [m.get("content", "") for m in kwargs.get("messages", [])]
    contents.append(kwargs.get("system", ""))
    if evidence and rules and any(isinstance(text, str) and rules in text for text in contents):
        return {"author_style_applied": evidence}
    return {}
