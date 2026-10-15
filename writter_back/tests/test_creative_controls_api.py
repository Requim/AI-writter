"""The deployed API exposes creative rollout controls with real tenant isolation."""

from dataclasses import replace

import pytest
from sqlalchemy import select

from api.dependencies import get_tenant_context
from api.main import app
from infrastructure.database.models import TenantModel


@pytest.mark.asyncio
async def test_creative_options_are_reachable_without_being_parsed_as_a_novel_id(async_client):
    response = await async_client.get("/api/v1/novels/creative-options")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["tenant_enabled"] is False


@pytest.mark.asyncio
async def test_regular_owner_cannot_enable_autonomous_rollout(async_client):
    response = await async_client.put("/api/v1/novels/creative-options", json={
        "enabled": True, "request_limit": 200})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_rollout_changes_only_selected_tenant(
    async_client, repository, tenant_context, other_tenant_context, monkeypatch,
):
    monkeypatch.setattr("config.settings.AUTONOMOUS_AUTHOR_ENABLED", True)
    monkeypatch.setattr("config.settings.NOVEL_PLANNING_V1_ENABLED", True)
    async with repository.async_session() as session, session.begin():
        tenant = await session.get(TenantModel, tenant_context.tenant_id)
        tenant.novel_planning_v1_enabled = True
    app.dependency_overrides[get_tenant_context] = lambda: replace(
        tenant_context, is_platform_admin=True, novel_planning_v1_enabled=True)
    response = await async_client.put("/api/v1/novels/creative-options", json={
        "enabled": True, "request_limit": 200})
    assert response.status_code == 200
    options = await async_client.get("/api/v1/novels/creative-options")
    assert options.json()["enabled"] is True and options.json()["request_limit"] == 200
    async with repository.async_session() as session:
        other = await session.scalar(select(TenantModel).where(TenantModel.id == other_tenant_context.tenant_id))
        assert other.autonomous_author_enabled is False
        assert other.autonomous_request_limit == 10000
