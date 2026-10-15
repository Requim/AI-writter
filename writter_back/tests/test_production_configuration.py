"""Production settings and browser preflight must match supported operations."""

import httpx
import pytest

from api.main import app
from config import Settings


@pytest.mark.asyncio
async def test_cross_origin_patch_preflight_is_supported():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        response = await client.options(
            "/api/v1/tenants/current",
            headers={"Origin": "http://localhost:5173",
                     "Access-Control-Request-Method": "PATCH",
                     "Access-Control-Request-Headers": "authorization,x-tenant-id"},
        )
    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_background_node_deadline_cannot_disable_timeout_protection():
    with pytest.raises(ValueError, match="positive"):
        Settings(_env_file=None, ENVIRONMENT="test", WORKFLOW_BACKGROUND_NODE_TIMEOUT_SECONDS=0)
