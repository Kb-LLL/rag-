import asyncio
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from rag.document_parser import Section, chunk_sections, parse_document
from rag.knowledge_base import begin_job, validate_collection_ids
from rag.retriever import (
    _bm25_scores,
    build_sources,
    reciprocal_rank_fusion,
    rerank_candidates,
    tokenize_for_bm25,
)


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        if not self.rows:
            return []
        rows = self.rows
        self.rows = []
        return rows


class FakeConnection:
    def __init__(self, rows=None):
        self.cursor_instance = FakeCursor(rows)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class DocumentParserTests(unittest.TestCase):
    def test_chunking_preserves_english_spacing_and_overlap(self):
        section = Section(
            "The quick brown fox jumps over the lazy dog.",
            {"section": "Example"},
        )

        chunks = chunk_sections([section], target_tokens=5, overlap_tokens=2)

        self.assertEqual(chunks[0]["content"], "The quick brown fox jumps")
        self.assertTrue(chunks[1]["content"].startswith("fox jumps over"))
        self.assertEqual(chunks[0]["token_count"], 5)
        self.assertEqual(chunks[0]["locator"]["section"], "Example")

    def test_markdown_headings_are_retained_as_locators(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.md"
            path.write_text("# Install\nRun setup.\n## Usage\nOpen the app.", encoding="utf-8")

            sections = parse_document(path)

        self.assertEqual([section.locator["section"] for section in sections], ["Install", "Usage"])
        self.assertIn("Run setup", sections[0].text)

    def test_xlsx_fallback_reads_shared_strings_and_numbers(self):
        workbook_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <sheetData>
            <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
            <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>2999</v></c></row>
          </sheetData>
        </worksheet>"""
        strings_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <si><t>Product</t></si><si><t>Price</t></si><si><t>M200</t></si>
        </sst>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "products.xlsx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("xl/sharedStrings.xml", strings_xml)
                archive.writestr("xl/worksheets/sheet1.xml", workbook_xml)
            with patch.dict("sys.modules", {"openpyxl": None}):
                sections = parse_document(path)

        self.assertEqual(len(sections), 1)
        self.assertIn("Product\tPrice", sections[0].text)
        self.assertIn("M200\t2999", sections[0].text)
        self.assertEqual(sections[0].locator["row_start"], 2)


class RetrievalTests(unittest.TestCase):
    def test_chinese_bm25_prefers_matching_document(self):
        corpus = [
            tokenize_for_bm25("M200 手机电池容量为 8000mAh"),
            tokenize_for_bm25("A100 耳机支持主动降噪"),
        ]
        scores = _bm25_scores(corpus, tokenize_for_bm25("M200 电池容量"))
        self.assertGreater(scores[0], scores[1])

    def test_rrf_merges_dense_and_keyword_rankings(self):
        dense = [{"id": "a"}, {"id": "b"}]
        keyword = [{"id": "b"}, {"id": "c"}]

        result = reciprocal_rank_fusion([dense, keyword])

        self.assertEqual(result[0]["id"], "b")
        self.assertGreater(result[0]["rrf_score"], result[1]["rrf_score"])

    def test_sources_keep_document_locator_and_score(self):
        sources = build_sources([{
            "id": "chunk-1",
            "content": "Battery capacity is 8000mAh.",
            "metadata": {
                "doc_id": "doc-1",
                "collection_id": "kb-1",
                "title": "Product Manual",
                "page": 3,
                "section": "Battery",
            },
            "rrf_score": 0.03125,
        }])

        self.assertEqual(sources[0]["index"], 1)
        self.assertEqual(sources[0]["locator"], {"page": 3, "section": "Battery"})
        self.assertEqual(sources[0]["score"], 0.0312)

    def test_reranker_failure_falls_back_to_rrf_order(self):
        candidates = [
            {"id": str(index), "content": f"chunk {index}", "metadata": {}}
            for index in range(8)
        ]
        failing_llm = AsyncMock()
        failing_llm.ainvoke.side_effect = TimeoutError("timeout")
        with patch("rag.retriever._get_quality_llm", return_value=failing_llm):
            result = asyncio.run(rerank_candidates("question", candidates, limit=6))

        self.assertEqual([item["id"] for item in result], ["0", "1", "2", "3", "4", "5"])


class SecurityAndJobTests(unittest.TestCase):
    def test_collection_validation_rejects_cross_user_ids(self):
        connection = FakeConnection([{"id": "owned"}])
        with patch("rag.knowledge_base.get_db", return_value=connection):
            with self.assertRaisesRegex(ValueError, "无权访问"):
                validate_collection_ids(7, ["owned", "other-user-kb"])

    def test_exhausted_job_marks_job_and_document_failed(self):
        connection = FakeConnection([{
            "id": "job-1",
            "document_id": "doc-1",
            "status": "queued",
            "attempts": 3,
            "max_attempts": 3,
        }])
        with patch("rag.knowledge_base.get_db", return_value=connection):
            result = begin_job("job-1", "claim-token")

        self.assertIsNone(result)
        sql = "\n".join(statement for statement, _ in connection.cursor_instance.executed)
        self.assertIn("UPDATE kb_jobs SET status='failed'", sql)
        self.assertIn("UPDATE kb_documents SET status='failed'", sql)
        self.assertTrue(connection.committed)


if __name__ == "__main__":
    unittest.main()
