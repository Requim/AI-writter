from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.dependencies import get_tenant_context
from api.routers.research_router import router
from infrastructure.research.library_client import ResearchLibraryClient
from service.entities.identity import TenantContext


def context(role: str) -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(),
        tenant_name="测试编辑部",
        user_id=uuid4(),
        role=role,  # type: ignore[arg-type]
        is_platform_admin=False,
        ai_enabled=True,
        monthly_generation_limit=30,
    )


@pytest.mark.asyncio
async def test_research_router_injects_server_token_for_admin() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers["X-Research-Token"]
        return httpx.Response(200, json={"retrieval_backend": "keyword"})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = FastAPI()
    app.state.research_library = ResearchLibraryClient(
        "http://research", "server-token", client=upstream
    )
    app.include_router(router, prefix="/api/v1/research")
    app.dependency_overrides[get_tenant_context] = lambda: context("admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/research/capabilities",
            headers={"X-Research-Token": "browser-token-must-be-ignored"},
        )

    assert response.status_code == 200
    assert seen == {"token": "server-token"}
    app.dependency_overrides.clear()
    await upstream.aclose()


@pytest.mark.asyncio
async def test_research_router_rejects_regular_members() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"retrieval_backend": "keyword"})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = FastAPI()
    app.state.research_library = ResearchLibraryClient(
        "http://research", "server-token", client=upstream
    )
    app.include_router(router, prefix="/api/v1/research")
    app.dependency_overrides[get_tenant_context] = lambda: context("member")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/research/capabilities")

    assert response.status_code == 403
    assert called is False
    app.dependency_overrides.clear()
    await upstream.aclose()
