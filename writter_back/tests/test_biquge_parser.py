from pathlib import Path

import pytest

from infrastructure.research.biquge_parser import (
    ResearchParseError,
    canonical_source_url,
    parse_catalog_page,
    parse_detail_page,
    parse_opening_page,
)


FIXTURES = Path(__file__).parent / "fixtures" / "novel_research"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_catalog_parser_deduplicates_novel_links() -> None:
    result = parse_catalog_page(_fixture("category.html"), "科幻", "popular")
    assert [item.title for item in result] == ["甲书", "乙书"]
    assert all(item.bucket == "popular" for item in result)


def test_catalog_parser_separates_sections_and_prefers_labeled_link() -> None:
    source = """
    <a href='/novel/1.html'><img></a><a href='/novel/1.html'>热门甲</a>
    <h2>最近更新小说列表</h2><a href='/novel/2.html'>最近乙</a>
    <h2>最新入库小说</h2><a href='/novel/3.html'>新书丙</a>
    """
    assert [item.title for item in parse_catalog_page(source, "科幻", "popular")] == ["热门甲"]
    assert [item.title for item in parse_catalog_page(source, "科幻", "recent")] == ["最近乙"]
    assert [item.title for item in parse_catalog_page(source, "科幻", "new")] == ["新书丙"]


def test_detail_parser_caps_sampled_chapter_titles() -> None:
    links = "".join(
        f"<a href='/book/500/{number}.html'>第{number}章 测试</a>"
        for number in range(1, 3001)
    )
    source = "<meta property='og:novel:book_name' content='长篇测试'>" + links
    _, index = parse_detail_page(source, "/novel/500.html")
    assert index.total_count == 3000
    assert len(index.titles) <= 120


def test_detail_parser_reads_metadata_and_chapter_digest() -> None:
    metadata, index = parse_detail_page(_fixture("detail.html"), "/novel/500.html")
    assert metadata.title == "测试小说"
    assert metadata.author == "测试作者"
    assert metadata.project_genres == ("sci_fi",)
    assert metadata.first_chapter_url.endswith("/book/500/one.html")
    assert index.total_count == 4
    assert index.titles[0] == "第1章 异常"
    assert index.digest == "a" * 64 or len(index.digest) == 64


def test_opening_parser_returns_redacted_transient_input() -> None:
    opening = parse_opening_page(_fixture("chapter.html"), "/book/500/one.html")
    assert opening.chapter_title == "第1章 异常"
    assert opening.metrics.paragraph_count == 3
    assert "正文" not in repr(opening)
    opening.discard()
    assert opening.text == ""


def test_source_url_policy_rejects_external_and_unapproved_paths() -> None:
    assert canonical_source_url("/lists/51.html?page=2", "catalog").endswith("?page=2")
    with pytest.raises(ValueError):
        canonical_source_url("https://example.com/novel/1.html", "detail")
    with pytest.raises(ValueError):
        canonical_source_url("/admin/export", "any")
    with pytest.raises(ValueError):
        canonical_source_url("/lists/not-a-category.html", "catalog")


def test_detail_parser_requires_a_title() -> None:
    with pytest.raises(ResearchParseError, match="标题"):
        parse_detail_page("<html><head></head></html>", "/novel/500.html")
