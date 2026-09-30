"""只读检查本次验收作品的规划检查点，不输出正文或凭证。"""

import asyncio
import json

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from config import settings
from application.agents.novel_plan_node import build_plan

NOVEL_ID = "44dbea4c-982b-445b-b527-cb598441f75a"


async def main():
    url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        async with saver.conn.cursor() as cursor:
            await cursor.execute("select tenant_id from novels where id=%s", (NOVEL_ID,))
            row = await cursor.fetchone()
        tenant = row["tenant_id"]
        checkpoint = await saver.aget_tuple({"configurable": {"thread_id": f"{tenant}:{NOVEL_ID}"}})
        state = checkpoint.checkpoint["channel_values"]
        generation = state.get("plan_generation") or {}
        artifact = state.get("fact_artifact") or {}
        print(json.dumps({"fact_kind": artifact.get("kind"),
                          "artifact_length": len(artifact.get("content") or ""),
                          "constraints_length": len(json.dumps(state.get("chapter_constraints") or {}, ensure_ascii=False)),
                          "fact_snapshot_length": len(json.dumps(state.get("fact_gate_snapshot") or {}, ensure_ascii=False)),
                          "fact_report_keys": list((state.get("fact_reports") or {}).keys())}))
        print(json.dumps({"stage": list(state.get("branch:to:novel_plan_finalize_node", []))
                          if isinstance(state.get("branch:to:novel_plan_finalize_node"), list) else None,
                          "final_validation_attempts": generation.get("final_validation_attempts"),
                          "slots": len(generation.get("chapter_slots", []))}))
        try:
            build_plan(generation, int(state.get("current_chapter_index", 0)))
            print("plan_validation_ok")
        except Exception as error:
            print(type(error).__name__, str(error))


if __name__ == "__main__":
    asyncio.run(main())
