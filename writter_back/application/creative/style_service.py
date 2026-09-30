"""把固定档案版本真正编译到任务，并保存每次应用的偏好来源。"""

from application.creative.author_style import compile_style
from service.value_objects.creative import CreativeRecord


class CreativeStyleService:
    def __init__(self, authors, creative):
        self.authors, self.creative = authors, creative

    async def compile_for_task(self, tenant_id, novel_id, session, task, state):
        config = session["config"]
        profile_id, version = config.get("author_profile_id"), config.get("author_profile_version")
        if not profile_id:
            return {"learned": False}
        profile = await self.authors.profile(tenant_id, profile_id, version)
        samples = {r["key"]: r["payload"] for r in await self.authors.records(tenant_id, "sample")}
        outline = (state.get("chapter_outlines") or [{}])[-1]
        compiled = compile_style(
            profile, samples, task=task, novel_id=novel_id, genre=state.get("novel_type", ""),
            scene_function=(outline.get("chapter_intent") or {}).get("primary_function", ""),
        )
        key = f"{task}:{state.get('current_chapter_index', 0)}:{profile_id}:v{version}"
        if not await self.creative.latest(tenant_id, novel_id, "style_application", key):
            await self.creative.put(tenant_id, novel_id, CreativeRecord(
                kind="style_application", key=key, payload=compiled,
                status="compiled" if compiled.get("learned") else "legacy_style",
                source="system", input_versions={"profile": version},
            ), expected_version=0, idempotency_key=f"style:{session['id']}:{key}")
        return compiled
