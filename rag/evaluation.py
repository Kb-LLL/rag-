import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List

import requests


REFUSAL_MARKERS = (
    "知识库中没有足够信息",
    "未在知识库中找到",
    "无法从知识库",
    "资料不足",
)


def request_json(method: str, url: str, **kwargs) -> Dict[str, Any]:
    response = requests.request(method, url, timeout=120, **kwargs)
    response.raise_for_status()
    return response.json()


def login(base_url: str, username: str, password: str) -> Dict[str, str]:
    data = request_json(
        "POST",
        f"{base_url}/api/login",
        json={"username": username, "password": password},
    )
    return {"Authorization": f"Bearer {data['token']}"}


def seed_fixture(
    base_url: str,
    headers: Dict[str, str],
    fixture: Dict[str, Any],
) -> str:
    collection = request_json(
        "POST",
        f"{base_url}/api/knowledge-bases",
        headers=headers,
        json={
            "name": f"RAG评测-{int(time.time())}",
            "description": "自动化30题检索评测临时知识库",
        },
    )
    collection_id = collection["id"]
    job_ids = []
    for document in fixture["documents"]:
        result = request_json(
            "POST",
            f"{base_url}/api/knowledge-bases/{collection_id}/documents/text",
            headers=headers,
            json={
                "title": document["title"],
                "content": document["content"],
                "duplicate_action": "version",
            },
        )
        job_ids.append(result["job"]["id"])

    deadline = time.time() + 300
    pending = set(job_ids)
    while pending and time.time() < deadline:
        for job_id in list(pending):
            job = request_json(
                "GET",
                f"{base_url}/api/knowledge-base/jobs/{job_id}",
                headers=headers,
            )
            if job["status"] == "ready":
                pending.remove(job_id)
            elif job["status"] == "failed":
                raise RuntimeError(f"评测文档索引失败: {job.get('error_message')}")
        if pending:
            time.sleep(1.5)
    if pending:
        raise TimeoutError(f"等待知识库索引超时: {sorted(pending)}")
    return collection_id


def evaluate_case(
    base_url: str,
    headers: Dict[str, str],
    collection_id: str,
    case: Dict[str, Any],
) -> Dict[str, Any]:
    result = request_json(
        "POST",
        f"{base_url}/api/rag/query",
        headers=headers,
        json={
            "query": case["question"],
            "knowledge_base_ids": [collection_id],
            "top_k": 6,
            "stream": False,
        },
    )
    answer = result.get("answer", "")
    sources = result.get("sources", [])
    source_titles = [source.get("title") for source in sources]
    should_answer = case.get("should_answer", True)
    expected_document = case.get("expected_document")
    expected_terms = case.get("expected_terms", [])
    refusal = any(marker in answer for marker in REFUSAL_MARKERS)
    return {
        "id": case["id"],
        "question": case["question"],
        "answer": answer,
        "source_titles": source_titles,
        "retrieval_hit": (
            expected_document in source_titles if expected_document else not sources
        ),
        "answer_term_hit": (
            all(term.lower() in answer.lower() for term in expected_terms)
            if should_answer else refusal
        ),
        "citation_correct": (
            bool(sources) and "[" in answer and expected_document in source_titles
            if should_answer else refusal
        ),
        "refusal_correct": refusal if not should_answer else None,
    }


def percentage(values: List[bool]) -> float:
    return round(100 * sum(bool(value) for value in values) / len(values), 2) if values else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the 30-case knowledge-base RAG evaluation.")
    parser.add_argument("--base-url", default="http://localhost:5000")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--collection-id")
    parser.add_argument("--seed-fixture", action="store_true")
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).with_name("eval_dataset.json")),
    )
    parser.add_argument("--output", default="rag/eval_results.json")
    args = parser.parse_args()

    fixture = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    headers = login(args.base_url.rstrip("/"), args.username, args.password)
    collection_id = args.collection_id
    if args.seed_fixture:
        collection_id = seed_fixture(args.base_url.rstrip("/"), headers, fixture)
    if not collection_id:
        raise SystemExit("必须提供 --collection-id，或使用 --seed-fixture 自动创建评测库")

    results = [
        evaluate_case(args.base_url.rstrip("/"), headers, collection_id, case)
        for case in fixture["cases"]
    ]
    answerable = [item for item in results if item["refusal_correct"] is None]
    unanswerable = [item for item in results if item["refusal_correct"] is not None]
    report = {
        "collection_id": collection_id,
        "case_count": len(results),
        "retrieval_hit_rate": percentage([item["retrieval_hit"] for item in answerable]),
        "answer_term_hit_rate": percentage([item["answer_term_hit"] for item in answerable]),
        "citation_correct_rate": percentage([item["citation_correct"] for item in answerable]),
        "no_answer_refusal_rate": percentage([item["refusal_correct"] for item in unanswerable]),
        "results": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
