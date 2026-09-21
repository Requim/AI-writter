"""写作服务访问独立研究库的最小 HTTP 客户端。"""

from __future__ import annotations

from typing import Any

import httpx


class ResearchLibraryUnavailable(RuntimeError):
    """研究库未配置、不可用或返回了错误。"""

    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


class ResearchLibraryClient:
    def __init__(
        self,
        base_url: str,
        token: str | None,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token or ""
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """由服务端携带内部令牌调用研究服务。"""
        if not self.base_url:
            raise ResearchLibraryUnavailable("研究库地址未配置")
        try:
            response = await self.client.request(
                method,
                f"{self.base_url}{path}",
                headers={"X-Research-Token": self.token},
                params=params,
                json=json,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = "研究库请求失败"
            try:
                payload = exc.response.json()
                if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
                    detail = payload["detail"]
            except ValueError:
                pass
            raise ResearchLibraryUnavailable(detail, exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise ResearchLibraryUnavailable("研究库请求失败") from exc
        return response.json()

    async def capabilities(self) -> dict[str, Any]:
        """读取研究服务能力。"""
        return await self._request("GET", "/internal/v1/research/capabilities")

    async def create_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        """创建研究采集批次。"""
        return await self._request("POST", "/internal/v1/research/batches", json=payload)

    async def job(self, job_id: str) -> dict[str, Any]:
        """查询研究采集任务。"""
        return await self._request("GET", f"/internal/v1/research/jobs/{job_id}")

    async def search(
        self,
        project_genre: str,
        query: str = "",
        opening_pattern: str | None = None,
        mechanism: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        """按题材检索当前已审核的类型知识包。"""
        return await self._request(
            "GET",
            "/internal/v1/research/knowledge/search",
            params={
                "project_genre": project_genre,
                "q": query,
                "opening_pattern": opening_pattern,
                "mechanism": mechanism,
                "limit": limit,
            },
        )

    async def current(self, project_genre: str) -> dict[str, Any]:
        """读取指定题材当前已审核知识包。"""
        return await self._request(
            "GET", f"/internal/v1/research/knowledge/{project_genre}"
        )

    async def review(self, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """审核研究知识版本。"""
        return await self._request(
            "POST",
            f"/internal/v1/research/knowledge/{version_id}/review",
            json=payload,
        )
