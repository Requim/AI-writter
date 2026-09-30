"""笔趣阁目录、详情和首章页面的受限解析器。"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import html
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urljoin, urlparse

from service.value_objects.novel_research import (
    BIQUGE_SOURCE_CATEGORIES,
    CatalogCandidate,
    ChapterIndex,
    NovelMetadata,
    OpeningMetrics,
    project_genres_for,
)


BASE_URL = "https://www.biquge.pro/"
_NOVEL_PATH = re.compile(r"^/novel/(\d+)\.html$")
_LIST_PATH = re.compile(r"^/lists/\d+\.html$")
_CHAPTER_PATH = re.compile(r"^/book/(\d+)/([A-Za-z0-9]+)\.html$")
_CHAPTER_NUMBER = re.compile(r"第\s*(\d+)\s*[章节]")
_CONTENT_SCRIPT = re.compile(r"\bcontent\s*:\s*'((?:\\.|[^'])*)'", re.S)
_CHAPTER_TITLE = re.compile(r"id=[\"']chapterTitle[\"'][^>]*>(.*?)</", re.S | re.I)


class ResearchParseError(ValueError):
    """页面缺少研究所需的结构化字段。"""


@dataclass(frozen=True)
class ParsedLink:
    href: str
    text: str
    title: str
    classes: frozenset[str]


class _HtmlCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metas: dict[str, str] = {}
        self.links: list[ParsedLink] = []
        self.scripts: list[str] = []
        self.content_parts: list[str] = []
        self._link: dict[str, object] | None = None
        self._script_parts: list[str] | None = None
        self._content_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.metas[key.lower()] = values["content"]
        if tag.lower() == "a":
            self._link = {"href": values.get("href", ""), "title": values.get("title", ""), "text": ""}
        if tag.lower() == "script":
            self._script_parts = []
        if self._is_content_node(values):
            self._content_depth = 1
        elif self._content_depth:
            self._content_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._link is not None:
            self._link["text"] = str(self._link["text"]) + data
        if self._script_parts is not None:
            self._script_parts.append(data)
        if self._content_depth:
            self.content_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "a" and self._link is not None:
            self.links.append(self._build_link(self._link))
            self._link = None
        if lowered == "script" and self._script_parts is not None:
            self.scripts.append("".join(self._script_parts))
            self._script_parts = None
        if self._content_depth:
            self._content_depth -= 1

    @staticmethod
    def _build_link(value: dict[str, object]) -> ParsedLink:
        return ParsedLink(
            href=str(value["href"]).strip(), text=_clean_text(str(value["text"])),
            title=_clean_text(str(value["title"])), classes=frozenset(),
        )

    @staticmethod
    def _is_content_node(values: dict[str, str]) -> bool:
        node_id = values.get("id", "").lower()
        classes = set(values.get("class", "").lower().split())
        return node_id == "chaptercontent" or "read-article" in classes


class _FragmentTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"p", "br", "div"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


@dataclass
class TransientOpeningInput:
    """首章正文仅在授权分析回调期间驻留内存，repr 永不展示正文。"""

    source_url: str
    chapter_title: str
    text: str
    metrics: OpeningMetrics

    def __repr__(self) -> str:
        return f"TransientOpeningInput(source_url={self.source_url!r}, text=<redacted>)"

    def discard(self) -> None:
        self.text = ""


def _clean_text(value: str) -> str:
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


def canonical_source_url(raw_url: str, kind: str = "any") -> str:
    """只接受笔趣阁公开页面的有限路径，拒绝任意 URL。"""
    absolute = urljoin(BASE_URL, raw_url.strip())
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"biquge.pro", "www.biquge.pro"}:
        raise ValueError("来源地址不在 biquge.pro 允许范围内")
    path = parsed.path or "/"
    allowed = {
        "home": path == "/",
        "catalog": bool(_LIST_PATH.fullmatch(path)) or path == "/",
        "detail": bool(_NOVEL_PATH.fullmatch(path)),
        "chapter": bool(_CHAPTER_PATH.fullmatch(path)),
        "any": path == "/" or bool(_LIST_PATH.fullmatch(path)) or bool(_NOVEL_PATH.fullmatch(path)) or bool(_CHAPTER_PATH.fullmatch(path)),
    }
    if not allowed.get(kind, False):
        raise ValueError("来源路径不在研究适配器允许范围内")
    query = parse_qs(parsed.query)
    if query and not (path.startswith("/lists/") and set(query) == {"page"} and query["page"][0].isdigit()):
        raise ValueError("来源查询参数不在允许范围内")
    page = f"?page={query['page'][0]}" if query else ""
    return f"https://www.biquge.pro{path}{page}"


def _collector(source: str) -> _HtmlCollector:
    parser = _HtmlCollector()
    try:
        parser.feed(source)
        parser.close()
    except (TypeError, ValueError) as exc:
        raise ResearchParseError("HTML 解析失败") from exc
    return parser


def _novel_links(parser: _HtmlCollector) -> list[ParsedLink]:
    result: list[ParsedLink] = []
    positions: dict[str, int] = {}
    for link in parser.links:
        if not _NOVEL_PATH.fullmatch(urlparse(link.href).path):
            continue
        url = canonical_source_url(link.href, "detail")
        candidate = ParsedLink(url, link.text, link.title, link.classes)
        position = positions.get(url)
        if position is None:
            positions[url] = len(result)
            result.append(candidate)
            continue
        current = result[position]
        if not _clean_text(current.text or current.title) and _clean_text(link.text or link.title):
            result[position] = candidate
    return result


def _catalog_scope(source: str, bucket: str) -> str:
    recent_marker = "最近更新小说列表"
    new_marker = "最新入库小说"
    if bucket == "popular":
        return source.split(recent_marker, 1)[0]
    if bucket == "recent" and recent_marker in source:
        return source.split(recent_marker, 1)[1].split(new_marker, 1)[0]
    if bucket == "new" and new_marker in source:
        return source.split(new_marker, 1)[1]
    return source


def parse_catalog_page(source: str, category: str, bucket: str = "fallback") -> list[CatalogCandidate]:
    """提取目录页中的小说入口，不读取小说正文。"""
    if category not in BIQUGE_SOURCE_CATEGORIES:
        raise ValueError("不支持的笔趣阁分类")
    result = []
    for rank, link in enumerate(_novel_links(_collector(_catalog_scope(source, bucket))), start=1):
        title = _clean_text(link.text or link.title)
        if title:
            result.append(CatalogCandidate(url=link.href, title=title, source_category=category, bucket=bucket, rank=rank))
    return result


def _chapter_number(link: ParsedLink) -> int | None:
    match = _CHAPTER_NUMBER.search(link.text or link.title)
    return int(match.group(1)) if match else None


def _chapter_rows(parser: _HtmlCollector) -> dict[int, tuple[str, str]]:
    rows: dict[int, tuple[str, str]] = {}
    for link in parser.links:
        if not _CHAPTER_PATH.fullmatch(urlparse(link.href).path):
            continue
        number = _chapter_number(link)
        if number is None or number in rows:
            continue
        rows[number] = (_clean_text(link.text or link.title), canonical_source_url(link.href, "chapter"))
    return rows


def _sample_titles(rows: dict[int, tuple[str, str]]) -> tuple[str, ...]:
    numbers = sorted(rows)
    if len(numbers) <= 120:
        return tuple(rows[number][0] for number in numbers)
    head, tail = numbers[:30], numbers[-10:]
    middle = numbers[30:-10]
    slots = 120 - len(set(head + tail))
    step = max(1, (len(middle) + slots - 1) // slots)
    selected = head + middle[::step][:slots] + tail
    return tuple(rows[number][0] for number in sorted(set(selected)))


def _chapter_digest(rows: dict[int, tuple[str, str]]) -> str:
    payload = "\n".join(f"{number}:{rows[number][0]}" for number in sorted(rows))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_detail_page(source: str, source_url: str, fallback_category: str = "其他") -> tuple[NovelMetadata, ChapterIndex]:
    """解析详情页的元数据和目录标题摘要，不保留页面 HTML。"""
    parser = _collector(source)
    url = canonical_source_url(source_url, "detail")
    novel_id_match = _NOVEL_PATH.fullmatch(urlparse(url).path)
    if not novel_id_match:
        raise ResearchParseError("详情页地址缺少小说 ID")
    meta = parser.metas
    title = _clean_text(meta.get("og:novel:book_name", ""))
    if not title:
        raise ResearchParseError("详情页缺少小说标题")
    rows = _chapter_rows(parser)
    first_url = rows.get(1, ("", ""))[1] or None
    category = _clean_text(meta.get("og:novel:category", "")) or fallback_category
    metadata = NovelMetadata(
        source_url=url, source_id=novel_id_match.group(1), title=title,
        author=_clean_text(meta.get("og:novel:author", "")), source_category=category,
        project_genres=project_genres_for(category), status=_clean_text(meta.get("og:novel:status", "")),
        summary=_clean_text(meta.get("og:novel:description", "") or meta.get("og:description", "")),
        updated_at=_clean_text(meta.get("og:novel:update_time", "")) or None,
        latest_chapter=_clean_text(meta.get("og:novel:latest_chapter_name", "")), first_chapter_url=first_url,
    )
    index = ChapterIndex(titles=_sample_titles(rows), total_count=max(rows, default=0), digest=_chapter_digest(rows), sampled=len(rows) > 120)
    return metadata, index


def _decode_script_content(scripts: list[str]) -> str:
    for script in scripts:
        match = _CONTENT_SCRIPT.search(script)
        if not match:
            continue
        raw = match.group(1)
        try:
            return str(ast.literal_eval("'" + raw + "'"))
        except (SyntaxError, ValueError):
            return raw.replace("\\'", "'").replace("\\/", "/").replace("\\n", "\n")
    return ""


def _fragment_text(fragment: str) -> str:
    parser = _FragmentTextParser()
    parser.feed(html.unescape(fragment))
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def _opening_metrics(text: str) -> OpeningMetrics:
    count = len(text)
    paragraphs = [line for line in text.splitlines() if line.strip()]
    dialogue = sum(text.count(mark) for mark in "“”‘’「」")
    pressure_words = ("危险", "警告", "任务", "死亡", "陌生", "异常", "追杀")
    offsets = [text.find(word) for word in pressure_words if text.find(word) >= 0]
    return OpeningMetrics(
        character_count=count, paragraph_count=len(paragraphs),
        dialogue_ratio=min(1, dialogue / max(1, count)),
        first_pressure_offset=min(offsets) if offsets else None,
    )


def parse_opening_page(source: str, source_url: str, max_chars: int = 20000) -> TransientOpeningInput:
    """授权后提取首章临时文本；调用方必须在分析结束后调用 discard。"""
    if max_chars < 1 or max_chars > 20000:
        raise ValueError("首章临时文本上限必须在1到20000字符之间")
    parser = _collector(source)
    fragment = _decode_script_content(parser.scripts) or "".join(parser.content_parts)
    text = _fragment_text(fragment)[:max_chars]
    if not text:
        raise ResearchParseError("首章页面没有可分析正文")
    title_match = _CHAPTER_TITLE.search(source)
    title = _clean_text(title_match.group(1)) if title_match else ""
    return TransientOpeningInput(
        source_url=canonical_source_url(source_url, "chapter"), chapter_title=title,
        text=text, metrics=_opening_metrics(text),
    )
