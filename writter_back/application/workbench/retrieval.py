"""Deterministic paragraph retrieval; offsets always refer to original text."""

import re
import unicodedata

MAX_CHUNK = 1600
MAX_CONTEXT = 8000


def chunk_text(content: str) -> list[dict]:
    chunks = []
    start = 0
    while start < len(content):
        limit = min(start + MAX_CHUNK, len(content))
        end = limit
        if limit < len(content):
            boundary = content.rfind("\n\n", start + MAX_CHUNK // 2, limit)
            if boundary >= 0:
                end = boundary + 2
        chunks.append({"start": start, "end": end, "text": content[start:end]})
        start = end
    return chunks


def query_terms(query: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", query).casefold()
    parts = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", normalized)
    terms = []
    for part in parts:
        terms.append(part)
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            terms.extend(part[i:i + 2] for i in range(len(part) - 1))
    return list(dict.fromkeys(term for term in terms if len(term) > 1))[:120]


def rank_sources(query: str, candidates: list[dict], limit: int = 8) -> list[dict]:
    terms = query_terms(query)
    result = []
    for source in candidates:
        title = unicodedata.normalize("NFKC", source.get("title", "")).casefold()
        body = unicodedata.normalize("NFKC", source["text"]).casefold()
        score = sum((8 if term in title else 0) + (min(len(term), 12) if term in body else 0) for term in terms)
        score += float(source.get("similarity", 0)) * 2
        if score > 0:
            result.append({**source, "score": score})
    result.sort(key=lambda row: (-row["score"], row.get("source_id", ""), row.get("start", 0)))
    return result[:limit]


def assemble_context(settings: list[str], hits: list[dict], explicit: list[str] | None = None) -> str:
    fixed = "\n\n".join(settings)
    selected = "\n\n".join(explicit or [])
    remaining = MAX_CONTEXT
    passages = []
    for hit in hits[:8]:
        prefix = f"【来源 {hit.get('title', hit.get('source_id', ''))} / v{hit.get('version', 1)}】\n"
        if remaining <= len(prefix):
            break
        passage = prefix + hit["text"][:remaining - len(prefix)]
        passages.append(passage)
        remaining -= len(passage)
    return f"【当前有效硬设定】\n{fixed or '暂无'}\n\n【用户明确引用】\n{selected or '无'}\n\n【检索参考原文】\n" + "\n\n".join(passages)
