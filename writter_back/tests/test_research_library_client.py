import httpx
import pytest

from infrastructure.research.library_client import ResearchLibraryClient


@pytest.mark.asyncio
async def test_research_library_client_searches_type_knowledge() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["genre"] = request.url.params["project_genre"]
        return httpx.Response(200, json={"items": [], "backend": "keyword"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    library = ResearchLibraryClient("http://research", "token", client=client)
    result = await library.search("sci_fi", query="谜团")
    assert result["backend"] == "keyword"
    assert seen == {
        "path": "/internal/v1/research/knowledge/search",
        "genre": "sci_fi",
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_research_library_client_keeps_internal_token_server_side() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers["X-Research-Token"]
        seen["path"] = request.url.path
        return httpx.Response(200, json={"retrieval_backend": "keyword"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    library = ResearchLibraryClient("http://research", "server-token", client=client)
    result = await library.capabilities()
    assert result["retrieval_backend"] == "keyword"
    assert seen == {
        "token": "server-token",
        "path": "/internal/v1/research/capabilities",
    }
    await client.aclose()
