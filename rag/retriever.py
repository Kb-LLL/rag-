import asyncio
import json
import logging
import math
import re
import time
from typing import Any, Dict, List, Optional, Sequence

import jieba
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import load_config
from .embeddings import get_text_embedding
from .knowledge_base import get_chunks, get_knowledge_collection, validate_collection_ids


logger = logging.getLogger(__name__)


def _get_quality_llm() -> ChatOpenAI:
    config = load_config()
    return ChatOpenAI(
        model=config["model-name"],
        openai_api_key=config["api-key"],
        openai_api_base=config["base-url"],
        temperature=0,
        max_tokens=1024,
        request_timeout=20,
    )


def tokenize_for_bm25(text: str) -> List[str]:
    return [
        token.lower()
        for token in jieba.lcut(text)
        if token.strip() and not re.fullmatch(r"\W+", token)
    ]


def _bm25_scores(corpus: Sequence[Sequence[str]], query_tokens: Sequence[str]) -> List[float]:
    if not corpus:
        return []
    document_count = len(corpus)
    average_length = sum(len(document) for document in corpus) / document_count or 1
    document_frequency: Dict[str, int] = {}
    for document in corpus:
        for token in set(document):
            document_frequency[token] = document_frequency.get(token, 0) + 1
    scores = []
    k1 = 1.5
    b = 0.75
    for document in corpus:
        frequencies: Dict[str, int] = {}
        for token in document:
            frequencies[token] = frequencies.get(token, 0) + 1
        score = 0.0
        for token in query_tokens:
            frequency = frequencies.get(token, 0)
            if not frequency:
                continue
            doc_frequency = document_frequency.get(token, 0)
            inverse_document_frequency = math.log(
                1 + (document_count - doc_frequency + 0.5) / (doc_frequency + 0.5)
            )
            denominator = frequency + k1 * (
                1 - b + b * len(document) / average_length
            )
            score += inverse_document_frequency * frequency * (k1 + 1) / denominator
        scores.append(score)
    return scores


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[Dict[str, Any]]],
    limit: int = 12,
    k: int = 60,
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for ranking in rankings:
        for position, item in enumerate(ranking, 1):
            chunk_id = item["id"]
            if chunk_id not in merged:
                merged[chunk_id] = dict(item)
                merged[chunk_id]["rrf_score"] = 0.0
            merged[chunk_id]["rrf_score"] += 1.0 / (k + position)
    return sorted(
        merged.values(),
        key=lambda item: item["rrf_score"],
        reverse=True,
    )[:limit]


def _vector_retrieve(
    query: str,
    user_id: int,
    collection_ids: Sequence[str],
    top_k: int,
) -> List[Dict[str, Any]]:
    if not collection_ids:
        return []
    where = {
        "$and": [
            {"user_id": {"$eq": user_id}},
            {"collection_id": {"$in": list(collection_ids)}},
        ]
    }
    result = get_knowledge_collection().query(
        query_embeddings=[get_text_embedding(query).tolist()],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    items = []
    ids = result.get("ids", [[]])[0]
    for index, chunk_id in enumerate(ids):
        metadata = result["metadatas"][0][index]
        items.append({
            "id": chunk_id,
            "content": result["documents"][0][index],
            "metadata": metadata,
            "vector_score": max(0.0, 1.0 - float(result["distances"][0][index])),
        })
    return items


def _bm25_retrieve(
    query: str,
    user_id: int,
    collection_ids: Sequence[str],
    top_k: int,
) -> List[Dict[str, Any]]:
    chunks = get_chunks(user_id, collection_ids)
    if not chunks:
        return []
    corpus = [tokenize_for_bm25(item["content"]) for item in chunks]
    query_tokens = tokenize_for_bm25(query)
    if not query_tokens:
        return []
    scores = _bm25_scores(corpus, query_tokens)
    ranking = sorted(range(len(chunks)), key=lambda index: scores[index], reverse=True)
    items = []
    for index in ranking[:top_k]:
        if scores[index] <= 0:
            continue
        chunk = chunks[index]
        items.append({
            "id": chunk["id"],
            "content": chunk["content"],
            "metadata": {
                "doc_id": chunk["document_id"],
                "collection_id": chunk["collection_id"],
                "title": chunk["title"],
                "doc_type": chunk["doc_type"],
                "filename": chunk.get("filename"),
                **chunk.get("locator", {}),
            },
            "bm25_score": float(scores[index]),
        })
    return items


async def rewrite_query(query: str, history: Optional[List[Dict[str, Any]]] = None) -> str:
    if not history:
        return query
    recent = history[-6:]
    transcript = "\n".join(
        f"{'用户' if item.get('role') == 'user' else '助手'}: {item.get('content', '')}"
        for item in recent
        if item.get("content")
    )
    if not transcript:
        return query
    try:
        response = await asyncio.wait_for(
            _get_quality_llm().ainvoke([
                SystemMessage(content=(
                    "把最后一个用户问题结合对话历史改写成可独立检索的问题。"
                    "只输出改写后的问题，不回答问题；如果已经独立完整则原样输出。"
                )),
                HumanMessage(content=f"对话历史：\n{transcript}\n\n当前问题：{query}"),
            ]),
            timeout=12,
        )
        rewritten = response.content.strip()
        return rewritten[:1000] or query
    except Exception:
        return query


async def rerank_candidates(
    query: str,
    candidates: List[Dict[str, Any]],
    limit: int = 6,
) -> List[Dict[str, Any]]:
    if len(candidates) <= limit:
        return candidates
    payload = [
        {
            "id": item["id"],
            "text": item["content"][:1200],
            "source": item.get("metadata", {}).get("title"),
        }
        for item in candidates
    ]
    try:
        response = await asyncio.wait_for(
            _get_quality_llm().ainvoke([
                SystemMessage(content=(
                    "你是检索重排器。根据问题选择最相关且能直接支持答案的片段。"
                    "仅返回 JSON，格式为 {\"ids\":[\"chunk-id\"]}，最多选择 6 个。"
                )),
                HumanMessage(content=json.dumps({
                    "query": query,
                    "candidates": payload,
                }, ensure_ascii=False)),
            ]),
            timeout=20,
        )
        match = re.search(r"\{.*\}", response.content, re.S)
        data = json.loads(match.group(0) if match else response.content)
        selected_ids = data.get("ids", [])[:limit]
        lookup = {item["id"]: item for item in candidates}
        selected = [lookup[chunk_id] for chunk_id in selected_ids if chunk_id in lookup]
        return selected or candidates[:limit]
    except Exception as exc:
        logger.warning("rerank fallback: %s", exc)
        return candidates[:limit]


async def hybrid_retrieve(
    query: str,
    user_id: int,
    collection_ids: Sequence[str],
    history: Optional[List[Dict[str, Any]]] = None,
    vector_top_k: int = 20,
    keyword_top_k: int = 20,
    fused_limit: int = 12,
    final_limit: int = 6,
    use_rerank: bool = True,
) -> Dict[str, Any]:
    started = time.perf_counter()
    valid_ids = validate_collection_ids(user_id, collection_ids)
    search_query = await rewrite_query(query, history)
    vector_results, keyword_results = await asyncio.gather(
        asyncio.to_thread(_vector_retrieve, search_query, user_id, valid_ids, vector_top_k),
        asyncio.to_thread(_bm25_retrieve, search_query, user_id, valid_ids, keyword_top_k),
    )
    fused = reciprocal_rank_fusion([vector_results, keyword_results], fused_limit)
    selected = await rerank_candidates(search_query, fused, final_limit) if use_rerank else fused[:final_limit]
    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(json.dumps({
        "event": "kb_retrieve",
        "user_id": user_id,
        "collection_count": len(valid_ids),
        "vector_hits": len(vector_results),
        "keyword_hits": len(keyword_results),
        "selected_hits": len(selected),
        "duration_ms": duration_ms,
    }, ensure_ascii=False))
    return {
        "query": search_query,
        "items": selected,
        "duration_ms": duration_ms,
    }


def build_sources(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sources = []
    for index, item in enumerate(items, 1):
        metadata = item.get("metadata", {})
        locator = {
            key: metadata[key]
            for key in ("page", "section", "slide", "sheet", "row_start", "row_end")
            if metadata.get(key) not in (None, "")
        }
        sources.append({
            "index": index,
            "chunk_id": item["id"],
            "document_id": metadata.get("doc_id"),
            "collection_id": metadata.get("collection_id"),
            "title": metadata.get("title", "未命名文档"),
            "doc_type": metadata.get("doc_type"),
            "locator": locator,
            "snippet": item["content"][:500],
            "score": round(float(item.get("rrf_score", item.get("vector_score", 0))), 4),
        })
    return sources


def format_context(items: Sequence[Dict[str, Any]], max_chars: int = 10000) -> str:
    parts = []
    total = 0
    for index, item in enumerate(items, 1):
        metadata = item.get("metadata", {})
        locator = build_sources([item])[0]["locator"]
        location_text = "，".join(f"{key}: {value}" for key, value in locator.items())
        header = f"[{index}] 来源: {metadata.get('title', '未命名文档')}"
        if location_text:
            header += f"（{location_text}）"
        entry = f"{header}\n{item['content']}"
        if total + len(entry) > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                parts.append(entry[:remaining])
            break
        parts.append(entry)
        total += len(entry)
    return "\n\n".join(parts)


def retrieve(
    query: str,
    user_id: int,
    top_k: int = 5,
    doc_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    del doc_type
    from .knowledge_base import list_collections
    collection_ids = [item["id"] for item in list_collections(user_id)]
    if not collection_ids:
        return []
    vector_results = _vector_retrieve(query, user_id, collection_ids, top_k)
    return [
        {
            "id": item["id"],
            "content": item["content"],
            "metadata": item["metadata"],
            "score": item["vector_score"],
        }
        for item in vector_results
    ]
