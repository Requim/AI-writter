"""小说 CRUD 集成测试"""
import pytest
import pytest_asyncio
from uuid import uuid4
from httpx import AsyncClient, ASGITransport

from service.value_objects.novel_type import NovelType
from service.entities.novel import Novel
from service.value_objects.progress import Progress


@pytest_asyncio.fixture
async def app():
    """创建测试用 FastAPI 应用"""
    from api.main import app as fastapi_app
    yield fastapi_app


@pytest_asyncio.fixture
async def async_client(app):
    """异步 HTTP 客户端"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestNovelCRUD:
    """小说 CRUD 测试"""

    async def test_create_novel(self, async_client, repository):
        """测试创建小说"""
        response = await async_client.post(
            "/api/v1/novels",
            json={
                "novel_type": "suspense",
                "title": "测试悬疑小说",
                "summary": "这是一个测试小说",
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "novel_id" in data
        assert "thread_id" in data
        assert data["status"] == "created"
        
        # 验证数据库中的数据
        novel = await repository.find_by_id(data["novel_id"])
        assert novel is not None
        assert novel.title == "测试悬疑小说"
        assert novel.novel_type == "suspense"

    async def test_create_novel_invalid_type(self, async_client):
        """测试创建小说时传入无效类型"""
        response = await async_client.post(
            "/api/v1/novels",
            json={
                "novel_type": "invalid_type",
                "title": "测试",
            },
        )
        
        assert response.status_code == 400
        assert "无效的小说类型" in response.json()["detail"]

    async def test_get_novel(self, async_client, repository, sample_novel):
        """测试获取小说详情"""
        # 先保存一个小说
        saved = await repository.save(sample_novel)
        
        response = await async_client.get(f"/api/v1/novels/{saved.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(saved.id)
        assert data["title"] == sample_novel.title
        assert data["novel_type"] == sample_novel.novel_type

    async def test_get_novel_not_found(self, async_client):
        """测试获取不存在的小说"""
        fake_id = str(uuid4())
        response = await async_client.get(f"/api/v1/novels/{fake_id}")
        
        assert response.status_code == 404
        assert "小说不存在" in response.json()["detail"]

    async def test_list_novels(self, async_client, repository, sample_novel):
        """测试列出所有小说"""
        # 保存一个小说
        await repository.save(sample_novel)
        
        response = await async_client.get("/api/v1/novels")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["title"] == sample_novel.title

    async def test_get_progress(self, async_client, repository, sample_novel):
        """测试获取小说进度"""
        saved = await repository.save(sample_novel)
        
        response = await async_client.get(f"/api/v1/novels/{saved.id}/progress")
        
        assert response.status_code == 200
        data = response.json()
        assert "current_chapter" in data
        assert "total_chapters" in data
        assert "percentage" in data
        assert "status" in data

    async def test_list_chapters_empty(self, async_client, repository, sample_novel):
        """测试获取章节列表（空）"""
        saved = await repository.save(sample_novel)
        
        response = await async_client.get(f"/api/v1/novels/{saved.id}/chapters")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0


class TestNovelWithOutline:
    """带大纲的小说测试"""

    async def test_create_novel_with_outline(
        self, async_client, repository, sample_novel_with_outline
    ):
        """测试创建带大纲的小说"""
        novel = sample_novel_with_outline
        outline = novel.total_outline
        outline_dict = {
            "story_background": outline.story_background,
            "main_characters": outline.main_characters,
            "main_plot": outline.main_plot,
            "chapters": outline.chapters,
            "writing_style": outline.writing_style,
            "total_chapters": outline.total_chapters,
        }
        
        response = await async_client.post(
            "/api/v1/novels",
            json={
                "novel_type": novel.novel_type,
                "title": novel.title,
                "summary": novel.summary,
                "total_outline": outline_dict,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # 验证大纲已保存
        saved = await repository.find_by_id(data["novel_id"])
        assert saved.total_outline is not None
        assert saved.total_outline.story_background == "一个发生在封闭别墅的谋杀案"
