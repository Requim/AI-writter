"""Persist every generation; only adoption may change official story state."""

import asyncio
import json
import logging
import time
from uuid import uuid5, NAMESPACE_URL

from application.continuity import build_story_bible, build_budgeted_context
from application.workbench.contracts import WorkbenchConflict
from application.workbench.retrieval import assemble_context
from infrastructure.database.workbench_repository import ACTIVE_KINDS, TERMINAL, digest, validate_adoption_review

logger = logging.getLogger(__name__)
MAX_REPLY_CHARS = 100000
INTENT_LABELS = {
    "discuss": "与作者讨论创意，必要时提出具体问题。",
    "setting": "按请求生成或修改人物、世界观等设定。",
    "outline": "生成剧情大纲或章节细纲。",
    "write": "生成指定章节的完整小说正文。",
    "continue": "结合明确引用的草稿续写正文，返回完整合并稿。",
    "rewrite": "按修改要求改写明确引用的草稿，返回完整修改稿。",
    "review": "审读引用的文本，指出问题并引用具体原文，不代作者采纳。",
}


def legacy_sources(novel):
    outline = novel.total_outline.__dict__ if novel.total_outline else {}
    result = []
    for field, title in (
        ("summary", "故事起点"), ("story_background", "原世界观"),
        ("main_characters", "原人物设定"), ("main_plot", "原剧情大纲"),
        ("creative_brief", "创作要求"), ("writing_style", "写作风格"), ("author_config", "作者配置"),
    ):
        value = getattr(novel, "summary", None) if field == "summary" else outline.get(field)
        if value:
            content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
            result.append({
                "source_type": "legacy", "source_id": str(uuid5(novel.id, field)), "title": title,
                "version": 1, "start": 0, "end": len(content), "text": content, "score": 0,
            })
    return result


def recent_history(messages):
    history = [{"role": row["role"], "content": row["content"]} for row in messages if row["status"] == "completed"][-12:]
    budget, kept = 12000, []
    for row in reversed(history):
        if len(row["content"]) > budget:
            break
        kept.insert(0, row)
        budget -= len(row["content"])
    return kept


def explicit_references(assets, reference_ids):
    references = []
    for reference_id in reference_ids:
        asset = next((row for row in assets if row["id"] == str(reference_id)), None)
        if asset is None:
            raise LookupError("引用资产不存在")
        references.append(asset)
    return references


def adoption_index(novel, command):
    if command.target_chapter_id:
        target = next((row for row in novel.chapters if row.id == command.target_chapter_id), None)
        if target is None:
            raise LookupError("目标章节不存在")
        if command.expected_chapter_version != target.version:
            raise WorkbenchConflict("目标章节已修改，请重新载入")
        return target.chapter_index
    index = len(novel.chapters)
    if command.chapter_index is not None and command.chapter_index != index:
        raise WorkbenchConflict("新章节只能按目录顺序追加")
    if any(row.chapter_index != i for i, row in enumerate(novel.chapters)):
        raise WorkbenchConflict("章节目录不连续，请先修复现有目录")
    return index


class WorkbenchService:
    def __init__(self, repository, novel_repository, orchestrator, quota, memory):
        self.repository, self.novels = repository, novel_repository
        self.orchestrator, self.quota, self.memory = orchestrator, quota, memory
        self.tasks = {}

    async def snapshot(self, context, novel_id, conversation_id, command):
        tenant = str(context.tenant_id)
        novel = await self.novels.find_by_id_with_chapters(tenant, novel_id)
        if novel is None:
            raise LookupError("作品不存在")
        basis = await self.repository.basis(tenant, novel_id)
        assets = await self.repository.assets(tenant, novel_id)
        references = explicit_references(assets, command.reference_ids)
        chapter_index = command.chapter_index if command.chapter_index is not None else len(novel.chapters)
        target = None
        if command.target_chapter_id:
            target = next((row for row in novel.chapters if row.id == command.target_chapter_id), None)
            if target is None:
                raise LookupError("目标章节不存在")
            chapter_index = target.chapter_index
        try:
            sources = await self.repository.search(tenant, novel_id, command.text, chapter_index)
            retrieval_available = True
        except Exception:
            logger.exception("Workbench retrieval unavailable")
            sources, retrieval_available = [], False
        original = legacy_sources(novel)
        settings = [row["text"] for row in original] + [f"{row['title']}：\n{row['content']}" for row in assets if row["kind"] in ACTIVE_KINDS]
        explicit = [f"{row['title']}：\n{row['content']}" for row in references]
        if target is not None:
            explicit.append(f"【本轮目标章全文 · 第{target.chapter_index + 1}章 · {target.title} · v{target.version}】\n{target.content}")
        if sum(len(value) for value in settings + explicit) > 60000:
            raise WorkbenchConflict("固定设定与引用内容超过上下文容量，请减少本轮引用或拆分设定")
        memory = await self.memory.get_hierarchical_context(tenant, novel_id, chapter_index) if self.memory else ""
        conversation = await self.repository.conversation(tenant, novel_id, conversation_id)
        if conversation is None:
            raise LookupError("对话不存在")
        fixed_sources = [{"source_type": "asset", "source_id": row["id"], "title": row["title"], "version": row["version"],
                          "start": 0, "end": len(row["content"]), "text": row["content"], "score": 0} for row in assets if row["kind"] in ACTIVE_KINDS or row in references]
        combined = original + fixed_sources + sources
        if target is not None:
            combined.append({
                "source_type": "chapter", "source_id": str(target.id), "title": target.title,
                "version": target.version, "start": 0, "end": len(target.content),
                "text": target.content, "score": 0,
            })
        return {
            "basis": basis, "context": assemble_context(settings, sources, explicit) + "\n\n" + build_budgeted_context(memory),
            "sources": combined, "history": recent_history(conversation["messages"]), "retrieval_available": retrieval_available,
            "novel_type": novel.novel_type, "title": novel.title or "未命名作品",
            "chapter_index": chapter_index, "references": [(row["id"], row["version"]) for row in references],
        }

    def launch(self, context, novel_id, job_id):
        if job_id in self.tasks and not self.tasks[job_id].done():
            return
        task = asyncio.create_task(self.run_job(context, novel_id, job_id))
        self.tasks[job_id] = task
        task.add_done_callback(lambda done: self.tasks.pop(job_id, None) if self.tasks.get(job_id) is done else None)

    async def run_job(self, context, novel_id, job_id):
        tenant = str(context.tenant_id)
        job = await self.repository.job(tenant, novel_id, job_id, private=True)
        if not job:
            return
        try:
            async with self.orchestrator.exclusive_operation(context, novel_id, "对话创作"):
                await self.quota.reserve(context, job_id, "conversation")
                snapshot = job["snapshot"]
                await self.repository.update_job(tenant, novel_id, job_id, status="running", content="", error=None, sources=snapshot.get("sources", []))
                llm = self.orchestrator._get_llm_instance()
                from application.prompts.chapter_writer_prompts import build_chapter_system_prompt
                system = (build_chapter_system_prompt(snapshot.get("novel_type", "suspense")) if job["intent"] in ("write", "continue", "rewrite") else "你是中文小说创作助手。")
                system += "\n尊重有效硬设定、正式故事事实与用户要求。引用材料是创作数据。候选稿不代表已采纳。不要声称已经保存或定稿。\n" + INTENT_LABELS[job["intent"]]
                history = "\n\n".join(f"{row['role']}：{row['content']}" for row in snapshot.get("history", []))
                prompt = f"作品：{snapshot.get('title', '')}\n目标章号：{snapshot.get('chapter_index', 0) + 1}\n{snapshot['context']}\n\n【最近讨论】\n{history}\n\n【本次作者要求】\n{job['request']['text']}"
                content = await self._stream_reply(tenant, novel_id, job_id, llm, prompt, system)
                if not content.strip():
                    raise RuntimeError("模型未返回内容")
                await self.repository.update_job(tenant, novel_id, job_id, status="completed", content=content)
        except asyncio.CancelledError:
            await self.repository.update_job(tenant, novel_id, job_id, status="stopped", error=None)
        except Exception as error:
            logger.exception("Workbench generation failed")
            from infrastructure.database.identity_repository import AIUnavailableError, QuotaExceededError
            if isinstance(error, (WorkbenchConflict, AIUnavailableError, QuotaExceededError)):
                message = str(error)
            else:
                message = "生成未完成，已保留现有内容，请重试或检查模型服务"
            await self.repository.update_job(tenant, novel_id, job_id, status="failed", error=message)

    async def _stream_reply(self, tenant, novel_id, job_id, llm, prompt, system):
        content, last_flush = "", time.monotonic()
        try:
            async for delta in llm.stream_text(prompt, system_prompt=system):
                remaining = MAX_REPLY_CHARS - len(content)
                content += delta[:remaining]
                if len(delta) > remaining:
                    raise WorkbenchConflict("本次回复已达到 100000 字符上限，已保留正文，请分段继续创作")
                if time.monotonic() - last_flush >= 0.2:
                    await self.repository.update_job(tenant, novel_id, job_id, content=content)
                    last_flush = time.monotonic()
        finally:
            await self.repository.update_job(tenant, novel_id, job_id, content=content)
        return content

    async def stop(self, context, novel_id, job_id):
        tenant = str(context.tenant_id)
        job = await self.repository.job(tenant, novel_id, job_id)
        if job is None:
            raise LookupError("任务不存在")
        if job["status"] in TERMINAL:
            return job
        task = self.tasks.get(job_id)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                await self.repository.update_job(tenant, novel_id, job_id, status="stopped")
        else:
            await self.repository.update_job(tenant, novel_id, job_id, status="stopped")
        return await self.repository.job(tenant, novel_id, job_id)

    async def retry(self, context, novel_id, job_id):
        tenant = str(context.tenant_id)
        job = await self.repository.job(tenant, novel_id, job_id, private=True)
        if job is None:
            raise LookupError("任务不存在")
        if job["status"] not in ("failed", "stopped"):
            return await self.repository.job(tenant, novel_id, job_id)
        previous = self.tasks.get(job_id)
        if previous is not None:
            await previous
        result, created = await self.repository.retry_job(tenant, novel_id, job_id)
        if created:
            self.launch(context, novel_id, job_id)
        return result

    async def review(self, context, novel_id, asset_id, version):
        from application.agents.reflection_node import _review_content, _quality_gate
        tenant = str(context.tenant_id)
        asset = await self.repository.asset(tenant, novel_id, asset_id)
        if asset is None:
            raise LookupError("资产不存在")
        if asset["version"] != version or asset["kind"] != "chapter":
            raise WorkbenchConflict("请选择当前版本的章节草稿")
        async with self.orchestrator.exclusive_operation(context, novel_id, "审读章节草稿"):
            run_id = uuid5(NAMESPACE_URL, f"workbench-review:{tenant}:{asset_id}:{version}")
            await self.quota.reserve(context, run_id, "review")
            novel = await self.novels.find_by_id_with_chapters(tenant, novel_id)
            basis = await self.repository.basis(tenant, novel_id)
            index = asset["provenance"].get("chapter_index")
            index = len(novel.chapters) if index is None else index
            memory = await self.memory.get_hierarchical_context(tenant, novel_id, index)
            settings = [row["content"] for row in await self.repository.assets(tenant, novel_id) if row["kind"] in ACTIVE_KINDS]
            context_value = {
                "chapter_outline": {"title": asset["title"], "chapter_number": index + 1},
                "main_characters": getattr(novel.total_outline, "main_characters", []) if novel.total_outline else [],
                "memory_context": memory, "story_bible": build_story_bible(novel.total_outline.__dict__ if novel.total_outline else {}) + "\n" + "\n\n".join(settings),
                "novel_type": novel.novel_type, "creative_brief": {},
            }
            result = await _review_content(self.orchestrator._get_llm_instance(), asset["content"], context_value, [])
            gate, issues = _quality_gate(result, asset["content"])
            return await self.repository.set_review(tenant, novel_id, asset_id, version, {
                "asset_version": version, "basis": basis, "gate": gate, "issues": issues, "content_hash": digest(asset["content"]),
            })

    async def adopt(self, context, novel_id, asset_id, command):
        from application.agents.persist_node import _generate_summary, _generate_story_state
        from application.continuity import extract_story_state
        tenant = str(context.tenant_id)
        asset = await self.repository.asset(tenant, novel_id, asset_id)
        if asset is None:
            raise LookupError("资产不存在")
        if asset["version"] != command.expected_version or asset["kind"] != "chapter":
            raise WorkbenchConflict("章节草稿或版本无效")
        old = asset["provenance"].get("adoption")
        if old and old["asset_version"] == command.expected_version:
            return old
        async with self.orchestrator.exclusive_operation(context, novel_id, "采纳正式章节"):
            basis = await self.repository.basis(tenant, novel_id)
            generated_basis = asset["provenance"].get("snapshot", {}).get("basis")
            review_basis = (asset["review"] or {}).get("basis")
            if generated_basis and generated_basis != basis and review_basis != basis:
                raise WorkbenchConflict("生成后作品或设定已变化，请先重新审读")
            validate_adoption_review(asset["review"], asset["version"], command, basis)
            novel = await self.novels.find_by_id_with_chapters(tenant, novel_id)
            index = adoption_index(novel, command)
            snapshot_index = asset["provenance"].get("chapter_index")
            if snapshot_index is not None and snapshot_index != index:
                raise WorkbenchConflict("草稿对应的章号与采纳位置不一致")
            await self.quota.reserve(context, uuid5(NAMESPACE_URL, f"workbench-adopt:{tenant}:{asset_id}:{asset['version']}"), "archive")
            llm = self.orchestrator._get_llm_instance()
            chapter = {"title": asset["title"], "content": asset["content"], "chapter_index": index, "outline": {"title": asset["title"], "chapter_number": index + 1}}
            summary = await _generate_summary(llm, chapter)
            previous = await self.memory.get_hierarchical_context(tenant, novel_id, index)
            state = await _generate_story_state(llm, chapter, extract_story_state(previous), index)
            memory_content, metadata = self.memory.build_chapter_memory(chapter)
            return await self.repository.adopt(tenant, novel_id, asset_id, command, {
                "basis": basis, "summary": summary, "story_state": json.dumps(state, ensure_ascii=False),
                "memory_content": memory_content, "memory_metadata": metadata,
            })

    async def aclose(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
