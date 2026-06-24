import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import chromadb
import pymysql
from chromadb.config import Settings

from .document_parser import Section, chunk_sections, parse_document
from .embeddings import DATA_DIR, get_text_embeddings
from .job_queue import enqueue
from .minio_client import delete_object as minio_delete_object
from .minio_client import download_object_bytes
from redis_client import get_redis


DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3307")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "1234"),
    "database": os.getenv("MYSQL_DATABASE", "ai_chat"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

CHROMA_DIR = DATA_DIR / "chroma"
CHROMA_DIR.mkdir(exist_ok=True)
MAX_JOB_ATTEMPTS = int(os.getenv("KB_JOB_MAX_ATTEMPTS", "3"))
EMBEDDING_BATCH_SIZE = int(os.getenv("KB_EMBEDDING_BATCH_SIZE", "16"))

_chroma_client = None
_knowledge_collection = None
_index_version = None


def get_db():
    return pymysql.connect(**DB_CONFIG)


def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
    return _chroma_client


def get_knowledge_collection():
    global _chroma_client, _knowledge_collection, _index_version
    try:
        remote_version = get_redis().get("kb:index:version") or "0"
    except Exception:
        remote_version = _index_version or "0"
    if _knowledge_collection is not None and _index_version != remote_version:
        try:
            _chroma_client.close()
            _chroma_client.clear_system_cache()
        except Exception:
            pass
        _chroma_client = None
        _knowledge_collection = None
    if _knowledge_collection is None:
        _knowledge_collection = get_chroma_client().get_or_create_collection(
            name="knowledge_base",
            metadata={"hnsw:space": "cosine"},
        )
        _index_version = remote_version
    return _knowledge_collection


def _publish_index_version() -> None:
    global _index_version
    try:
        _index_version = str(get_redis().incr("kb:index:version"))
    except Exception:
        _index_version = str(int(_index_version or "0") + 1)


def _column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (column,))
    return bool(cursor.fetchone())


def _add_column(cursor, table: str, column: str, definition: str) -> None:
    if not _column_exists(cursor, table, column):
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")


def _serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def ensure_default_collection(user_id: int, cursor=None) -> str:
    owns_connection = cursor is None
    conn = get_db() if owns_connection else None
    cur = conn.cursor() if owns_connection else cursor
    cur.execute(
        "SELECT id FROM kb_collections WHERE user_id=%s AND is_default=1 LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    if row:
        collection_id = row["id"]
    else:
        collection_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO kb_collections "
            "(id,user_id,name,description,is_default) VALUES (%s,%s,%s,%s,1)",
            (collection_id, user_id, "默认知识库", "由系统自动创建"),
        )
    if owns_connection:
        conn.commit()
        conn.close()
    return collection_id


def _migrate_legacy_chunks(cursor) -> None:
    cursor.execute("SELECT id,user_id,collection_id,title,doc_type,version FROM kb_documents")
    documents = cursor.fetchall()
    chroma = get_knowledge_collection()
    for document in documents:
        if not document["collection_id"]:
            collection_id = ensure_default_collection(document["user_id"], cursor)
            cursor.execute(
                "UPDATE kb_documents SET collection_id=%s WHERE id=%s",
                (collection_id, document["id"]),
            )
            document["collection_id"] = collection_id

        cursor.execute("SELECT COUNT(*) AS count FROM kb_chunks WHERE document_id=%s", (document["id"],))
        if cursor.fetchone()["count"]:
            continue
        legacy = chroma.get(
            where={"doc_id": document["id"]},
            include=["documents", "metadatas", "embeddings"],
        )
        migrated_metadatas = []
        for index, content in enumerate(legacy.get("documents") or []):
            metadata = (legacy.get("metadatas") or [{}])[index] or {}
            chunk_id = (legacy.get("ids") or [])[index]
            locator = {
                key: metadata[key]
                for key in ("page", "section", "slide", "sheet", "row_start", "row_end")
                if metadata.get(key) is not None
            }
            cursor.execute(
                "INSERT IGNORE INTO kb_chunks "
                "(id,document_id,collection_id,user_id,chunk_index,content,content_hash,locator_json,token_count) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    chunk_id,
                    document["id"],
                    document["collection_id"],
                    document["user_id"],
                    index,
                    content,
                    hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    json.dumps(locator, ensure_ascii=False),
                    len(content),
                ),
            )
            migrated_metadatas.append({
                **metadata,
                "doc_id": document["id"],
                "collection_id": document["collection_id"],
                "user_id": document["user_id"],
                "title": document["title"],
                "doc_type": document["doc_type"],
                "chunk_index": index,
            })
        if legacy.get("ids") and legacy.get("embeddings") is not None:
            chroma.upsert(
                ids=legacy["ids"],
                embeddings=legacy["embeddings"],
                documents=legacy["documents"],
                metadatas=migrated_metadatas,
            )
            _publish_index_version()
        cursor.execute(
            "UPDATE kb_documents SET status='ready', error_message=NULL, "
            "indexed_at=COALESCE(indexed_at,NOW()) WHERE id=%s",
            (document["id"],),
        )


def init_db() -> None:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_collections (
                id VARCHAR(36) PRIMARY KEY,
                user_id INT NOT NULL,
                name VARCHAR(120) NOT NULL,
                description VARCHAR(500) DEFAULT '',
                is_default TINYINT(1) NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_kb_collection_name (user_id,name),
                KEY idx_kb_collection_user (user_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_documents (
                id VARCHAR(36) PRIMARY KEY,
                user_id INT NOT NULL,
                collection_id VARCHAR(36) DEFAULT NULL,
                title VARCHAR(200) NOT NULL,
                doc_type VARCHAR(20) NOT NULL DEFAULT 'text',
                filename VARCHAR(255) DEFAULT NULL,
                file_path VARCHAR(500) DEFAULT NULL,
                minio_object VARCHAR(500) DEFAULT NULL,
                minio_url TEXT DEFAULT NULL,
                source_text LONGTEXT DEFAULT NULL,
                file_hash CHAR(64) DEFAULT NULL,
                version INT NOT NULL DEFAULT 1,
                status VARCHAR(20) NOT NULL DEFAULT 'queued',
                error_message TEXT DEFAULT NULL,
                chunk_count INT DEFAULT 0,
                indexed_at DATETIME DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_kb_document_user (user_id),
                KEY idx_kb_document_collection (collection_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        _add_column(cursor, "kb_documents", "collection_id", "VARCHAR(36) DEFAULT NULL AFTER user_id")
        _add_column(cursor, "kb_documents", "source_text", "LONGTEXT DEFAULT NULL AFTER minio_url")
        _add_column(cursor, "kb_documents", "file_hash", "CHAR(64) DEFAULT NULL AFTER source_text")
        _add_column(cursor, "kb_documents", "version", "INT NOT NULL DEFAULT 1 AFTER file_hash")
        _add_column(cursor, "kb_documents", "status", "VARCHAR(20) NOT NULL DEFAULT 'queued' AFTER version")
        _add_column(cursor, "kb_documents", "error_message", "TEXT DEFAULT NULL AFTER status")
        _add_column(cursor, "kb_documents", "indexed_at", "DATETIME DEFAULT NULL AFTER chunk_count")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_chunks (
                id VARCHAR(96) PRIMARY KEY,
                document_id VARCHAR(36) NOT NULL,
                collection_id VARCHAR(36) NOT NULL,
                user_id INT NOT NULL,
                chunk_index INT NOT NULL,
                content MEDIUMTEXT NOT NULL,
                content_hash CHAR(64) NOT NULL,
                locator_json JSON DEFAULT NULL,
                token_count INT NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_kb_document_chunk (document_id,chunk_index),
                KEY idx_kb_chunks_collection (user_id,collection_id),
                FULLTEXT KEY ft_kb_chunk_content (content)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS kb_jobs (
                id VARCHAR(36) PRIMARY KEY,
                document_id VARCHAR(36) NOT NULL,
                user_id INT NOT NULL,
                job_type VARCHAR(20) NOT NULL DEFAULT 'index',
                status VARCHAR(20) NOT NULL DEFAULT 'queued',
                progress INT NOT NULL DEFAULT 0,
                stage VARCHAR(50) NOT NULL DEFAULT 'queued',
                attempts INT NOT NULL DEFAULT 0,
                max_attempts INT NOT NULL DEFAULT 3,
                claim_token VARCHAR(64) DEFAULT NULL,
                error_message TEXT DEFAULT NULL,
                started_at DATETIME DEFAULT NULL,
                finished_at DATETIME DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                KEY idx_kb_jobs_user (user_id),
                KEY idx_kb_jobs_document (document_id),
                KEY idx_kb_jobs_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        _add_column(cursor, "conversations", "knowledge_base_ids_json", "LONGTEXT DEFAULT NULL")
        _add_column(cursor, "messages", "sources_json", "LONGTEXT DEFAULT NULL")
        cursor.execute("SELECT id FROM users")
        for row in cursor.fetchall():
            ensure_default_collection(row["id"], cursor)
        _migrate_legacy_chunks(cursor)
        conn.commit()
    finally:
        conn.close()


def create_collection(user_id: int, name: str, description: str = "") -> Dict[str, Any]:
    collection_id = str(uuid.uuid4())
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO kb_collections (id,user_id,name,description) VALUES (%s,%s,%s,%s)",
            (collection_id, user_id, name.strip(), description.strip()),
        )
        conn.commit()
        return get_collection(collection_id, user_id)
    finally:
        conn.close()


def list_collections(user_id: int) -> List[Dict[str, Any]]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT c.*,
                   COUNT(d.id) AS document_count,
                   COALESCE(SUM(d.chunk_count),0) AS chunk_count,
                   SUM(CASE WHEN d.status='ready' THEN 1 ELSE 0 END) AS ready_count
            FROM kb_collections c
            LEFT JOIN kb_documents d ON d.collection_id=c.id
            WHERE c.user_id=%s
            GROUP BY c.id
            ORDER BY c.is_default DESC,c.updated_at DESC
            """,
            (user_id,),
        )
        return [_serialize_row(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_collection(collection_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM kb_collections WHERE id=%s AND user_id=%s",
            (collection_id, user_id),
        )
        row = cursor.fetchone()
        return _serialize_row(row) if row else None
    finally:
        conn.close()


def update_collection(collection_id: str, user_id: int, name: str, description: str) -> bool:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE kb_collections SET name=%s,description=%s WHERE id=%s AND user_id=%s",
            (name.strip(), description.strip(), collection_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_collection(collection_id: str, user_id: int) -> bool:
    collection = get_collection(collection_id, user_id)
    if not collection or collection["is_default"]:
        return False
    for document in list_documents(user_id, collection_id):
        delete_document(document["id"], user_id)
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM kb_collections WHERE id=%s AND user_id=%s",
            (collection_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def _document_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_document(
    user_id: int,
    collection_id: str,
    title: str,
    doc_type: str,
    filename: Optional[str] = None,
    minio_object: Optional[str] = None,
    minio_url: Optional[str] = None,
    source_text: Optional[str] = None,
    content_bytes: Optional[bytes] = None,
    duplicate_mode: str = "skip",
) -> Dict[str, Any]:
    if not get_collection(collection_id, user_id):
        raise ValueError("知识库不存在")
    data = content_bytes if content_bytes is not None else (source_text or "").encode("utf-8")
    if not data.strip():
        raise ValueError("文档内容不能为空")
    file_hash = _document_hash(data)
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id,title,status FROM kb_documents "
            "WHERE user_id=%s AND collection_id=%s AND file_hash=%s ORDER BY version DESC LIMIT 1",
            (user_id, collection_id, file_hash),
        )
        duplicate = cursor.fetchone()
        if duplicate and duplicate_mode != "version":
            return {"duplicate": True, "document": _serialize_row(duplicate)}

        version = 1
        if duplicate_mode == "version":
            cursor.execute(
                "SELECT COALESCE(MAX(version),0)+1 AS version FROM kb_documents "
                "WHERE user_id=%s AND collection_id=%s AND title=%s",
                (user_id, collection_id, title),
            )
            version = cursor.fetchone()["version"]

        document_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO kb_documents
            (id,user_id,collection_id,title,doc_type,filename,minio_object,minio_url,
             source_text,file_hash,version,status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued')
            """,
            (
                document_id, user_id, collection_id, title, doc_type, filename,
                minio_object, minio_url, source_text, file_hash, version,
            ),
        )
        cursor.execute(
            "INSERT INTO kb_jobs "
            "(id,document_id,user_id,job_type,status,progress,stage,max_attempts) "
            "VALUES (%s,%s,%s,'index','queued',0,'queued',%s)",
            (job_id, document_id, user_id, MAX_JOB_ATTEMPTS),
        )
        conn.commit()
    finally:
        conn.close()
    enqueue(job_id)
    return {
        "duplicate": False,
        "document_id": document_id,
        "job_id": job_id,
        "status": "queued",
    }


def add_document(
    user_id: int,
    title: str,
    content: Optional[str] = None,
    doc_type: str = "text",
    file_path: Optional[str] = None,
    minio_object: Optional[str] = None,
    minio_url: Optional[str] = None,
    collection_id: Optional[str] = None,
) -> Dict[str, Any]:
    collection_id = collection_id or ensure_default_collection(user_id)
    if file_path:
        path = Path(file_path)
        return create_document(
            user_id=user_id,
            collection_id=collection_id,
            title=title,
            doc_type=path.suffix.lstrip(".") or doc_type,
            filename=path.name,
            minio_object=minio_object,
            minio_url=minio_url,
            content_bytes=path.read_bytes(),
        )
    return create_document(
        user_id=user_id,
        collection_id=collection_id,
        title=title,
        doc_type=doc_type,
        source_text=content or "",
    )


def list_documents(user_id: int, collection_id: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        sql = (
            "SELECT d.*,j.id AS job_id,j.status AS job_status,j.progress,j.stage,"
            "j.error_message AS job_error FROM kb_documents d "
            "LEFT JOIN kb_jobs j ON j.id=("
            "SELECT j2.id FROM kb_jobs j2 WHERE j2.document_id=d.id ORDER BY j2.created_at DESC LIMIT 1"
            ") WHERE d.user_id=%s"
        )
        params: List[Any] = [user_id]
        if collection_id:
            sql += " AND d.collection_id=%s"
            params.append(collection_id)
        sql += " ORDER BY d.updated_at DESC"
        cursor.execute(sql, params)
        return [_serialize_row(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_document(document_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM kb_documents WHERE id=%s AND user_id=%s",
            (document_id, user_id),
        )
        row = cursor.fetchone()
        return _serialize_row(row) if row else None
    finally:
        conn.close()


def get_job(job_id: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        sql = "SELECT * FROM kb_jobs WHERE id=%s"
        params: List[Any] = [job_id]
        if user_id is not None:
            sql += " AND user_id=%s"
            params.append(user_id)
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return _serialize_row(row) if row else None
    finally:
        conn.close()


def retry_job(job_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM kb_jobs WHERE id=%s AND user_id=%s",
            (job_id, user_id),
        )
        job = cursor.fetchone()
        if not job:
            return None
        cursor.execute(
            "UPDATE kb_jobs SET status='queued',stage='queued',progress=0,"
            "error_message=NULL,claim_token=NULL,finished_at=NULL WHERE id=%s",
            (job_id,),
        )
        cursor.execute(
            "UPDATE kb_documents SET status='queued',error_message=NULL WHERE id=%s",
            (job["document_id"],),
        )
        conn.commit()
    finally:
        conn.close()
    enqueue(job_id)
    return get_job(job_id, user_id)


def create_reindex_job(document_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    if not get_document(document_id, user_id):
        return None
    job_id = str(uuid.uuid4())
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO kb_jobs "
            "(id,document_id,user_id,job_type,status,progress,stage,max_attempts) "
            "VALUES (%s,%s,%s,'reindex','queued',0,'queued',%s)",
            (job_id, document_id, user_id, MAX_JOB_ATTEMPTS),
        )
        cursor.execute(
            "UPDATE kb_documents SET status='queued',error_message=NULL WHERE id=%s",
            (document_id,),
        )
        conn.commit()
    finally:
        conn.close()
    enqueue(job_id)
    return get_job(job_id, user_id)


def update_job(
    job_id: str,
    status: str,
    stage: str,
    progress: int,
    error_message: Optional[str] = None,
    claim_token: Optional[str] = None,
) -> None:
    conn = get_db()
    try:
        cursor = conn.cursor()
        started_sql = ",started_at=COALESCE(started_at,NOW())" if status == "processing" else ""
        finished_sql = ",finished_at=NOW()" if status in {"ready", "failed"} else ""
        cursor.execute(
            f"UPDATE kb_jobs SET status=%s,stage=%s,progress=%s,error_message=%s,"
            f"claim_token=COALESCE(%s,claim_token){started_sql}{finished_sql} WHERE id=%s",
            (status, stage, max(0, min(progress, 100)), error_message, claim_token, job_id),
        )
        cursor.execute("SELECT document_id FROM kb_jobs WHERE id=%s", (job_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE kb_documents SET status=%s,error_message=%s WHERE id=%s",
                ("ready" if status == "ready" else status, error_message, row["document_id"]),
            )
        conn.commit()
    finally:
        conn.close()


def begin_job(job_id: str, claim_token: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM kb_jobs WHERE id=%s FOR UPDATE", (job_id,))
        job = cursor.fetchone()
        if not job or job["status"] == "ready":
            conn.rollback()
            return None
        if job["attempts"] >= job["max_attempts"]:
            cursor.execute(
                "UPDATE kb_jobs SET status='failed',stage='failed',progress=100,"
                "error_message='超过最大重试次数',finished_at=NOW() WHERE id=%s",
                (job_id,),
            )
            cursor.execute(
                "UPDATE kb_documents SET status='failed',error_message='超过最大重试次数' "
                "WHERE id=%s",
                (job["document_id"],),
            )
            conn.commit()
            return None
        cursor.execute(
            "UPDATE kb_jobs SET status='processing',stage='claiming',progress=1,"
            "attempts=attempts+1,claim_token=%s,started_at=COALESCE(started_at,NOW()) WHERE id=%s",
            (claim_token, job_id),
        )
        conn.commit()
        return get_job(job_id)
    finally:
        conn.close()


def _load_document_sections(document: Dict[str, Any]) -> List[Section]:
    if document.get("source_text") is not None:
        return [Section(document["source_text"], {"section": document["title"]})]
    if not document.get("minio_object"):
        raise ValueError("原始文件不存在，无法重建索引")
    data = download_object_bytes(document["minio_object"])
    suffix = Path(document.get("filename") or f".{document['doc_type']}").suffix
    with tempfile.TemporaryDirectory(prefix="kb-index-") as temp_dir:
        path = Path(temp_dir) / f"source{suffix}"
        path.write_bytes(data)
        return parse_document(path)


def _chroma_delete_document(document_id: str) -> None:
    collection = get_knowledge_collection()
    existing = collection.get(where={"doc_id": document_id})
    if existing.get("ids"):
        collection.delete(ids=existing["ids"])


def process_index_job(job_id: str, claim_token: str) -> Dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise ValueError("任务不存在")
    document = get_document(job["document_id"], job["user_id"])
    if not document:
        raise ValueError("文档不存在")

    update_job(job_id, "processing", "parsing", 10, claim_token=claim_token)
    sections = _load_document_sections(document)
    update_job(job_id, "processing", "chunking", 30)
    chunks = chunk_sections(sections)
    if not chunks:
        raise ValueError("文档中没有可索引内容")

    chunk_rows = []
    texts = [chunk["content"] for chunk in chunks]
    update_job(job_id, "processing", "embedding", 45)
    embeddings = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        embeddings.extend(get_text_embeddings(texts[start:start + EMBEDDING_BATCH_SIZE]).tolist())
        progress = 45 + int(35 * min(start + EMBEDDING_BATCH_SIZE, len(texts)) / len(texts))
        update_job(job_id, "processing", "embedding", progress)

    for index, chunk in enumerate(chunks):
        content_hash = hashlib.sha256(chunk["content"].encode("utf-8")).hexdigest()
        chunk_id = f"{document['id']}:v{document['version']}:{index}:{content_hash[:16]}"
        chunk_rows.append({
            "id": chunk_id,
            "index": index,
            "content": chunk["content"],
            "hash": content_hash,
            "locator": chunk["locator"],
            "token_count": chunk.get("token_count", len(chunk["content"])),
        })

    update_job(job_id, "processing", "persisting", 85)
    _chroma_delete_document(document["id"])
    chroma = get_knowledge_collection()
    chroma.upsert(
        ids=[row["id"] for row in chunk_rows],
        embeddings=embeddings,
        documents=[row["content"] for row in chunk_rows],
        metadatas=[{
            "doc_id": document["id"],
            "collection_id": document["collection_id"],
            "user_id": document["user_id"],
            "title": document["title"],
            "doc_type": document["doc_type"],
            "chunk_index": row["index"],
            **{key: value for key, value in row["locator"].items() if value is not None},
        } for row in chunk_rows],
    )

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM kb_chunks WHERE document_id=%s", (document["id"],))
        cursor.executemany(
            "INSERT INTO kb_chunks "
            "(id,document_id,collection_id,user_id,chunk_index,content,content_hash,locator_json,token_count) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(
                row["id"], document["id"], document["collection_id"], document["user_id"],
                row["index"], row["content"], row["hash"],
                json.dumps(row["locator"], ensure_ascii=False), row["token_count"],
            ) for row in chunk_rows],
        )
        cursor.execute(
            "UPDATE kb_documents SET status='ready',error_message=NULL,chunk_count=%s,indexed_at=NOW() "
            "WHERE id=%s",
            (len(chunk_rows), document["id"]),
        )
        cursor.execute(
            "UPDATE kb_jobs SET status='ready',stage='ready',progress=100,error_message=NULL,"
            "finished_at=NOW() WHERE id=%s",
            (job_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        _chroma_delete_document(document["id"])
        raise
    finally:
        conn.close()
    _publish_index_version()
    return {"document_id": document["id"], "chunk_count": len(chunk_rows)}


def fail_job(job_id: str, error: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    final = job["attempts"] >= job["max_attempts"]
    status = "failed" if final else "queued"
    update_job(job_id, status, status, 100 if final else 0, error[:2000])
    if not final:
        enqueue(job_id)


def delete_document(document_id: str, user_id: int) -> bool:
    document = get_document(document_id, user_id)
    if not document:
        return False
    _chroma_delete_document(document_id)
    _publish_index_version()
    if document.get("minio_object"):
        minio_delete_object(document["minio_object"])
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM kb_jobs WHERE document_id=%s AND user_id=%s", (document_id, user_id))
        cursor.execute("DELETE FROM kb_chunks WHERE document_id=%s AND user_id=%s", (document_id, user_id))
        cursor.execute("DELETE FROM kb_documents WHERE id=%s AND user_id=%s", (document_id, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_chunks(user_id: int, collection_ids: Sequence[str]) -> List[Dict[str, Any]]:
    if not collection_ids:
        return []
    placeholders = ",".join(["%s"] * len(collection_ids))
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT c.id,c.document_id,c.collection_id,c.chunk_index,c.content,c.locator_json,
                   d.title,d.doc_type,d.filename
            FROM kb_chunks c
            JOIN kb_documents d ON d.id=c.document_id
            WHERE c.user_id=%s AND c.collection_id IN ({placeholders}) AND d.status='ready'
            """,
            [user_id, *collection_ids],
        )
        rows = cursor.fetchall()
        for row in rows:
            try:
                row["locator"] = json.loads(row.pop("locator_json") or "{}")
            except json.JSONDecodeError:
                row["locator"] = {}
        return rows
    finally:
        conn.close()


def validate_collection_ids(user_id: int, collection_ids: Sequence[str]) -> List[str]:
    unique_ids = list(dict.fromkeys(collection_ids))
    if not unique_ids:
        return []
    placeholders = ",".join(["%s"] * len(unique_ids))
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT id FROM kb_collections WHERE user_id=%s AND id IN ({placeholders})",
            [user_id, *unique_ids],
        )
        valid = {row["id"] for row in cursor.fetchall()}
    finally:
        conn.close()
    if len(valid) != len(unique_ids):
        raise ValueError("包含无权访问或不存在的知识库")
    return unique_ids


def get_all_chunks(user_id: int) -> List[Dict[str, Any]]:
    collection_ids = [item["id"] for item in list_collections(user_id)]
    return get_chunks(user_id, collection_ids)
