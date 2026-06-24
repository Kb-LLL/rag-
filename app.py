import json
import datetime
import uuid
import base64
import io
import mimetypes
import os
import subprocess
import sys
import httpx
from pathlib import Path
from typing import List, Optional

import pymysql
import bcrypt
import jwt
from fastapi import FastAPI, HTTPException, Depends, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from PIL import Image, UnidentifiedImageError
from config import load_config
from rag import (
    init_kb_db, add_document, list_documents, delete_document, get_document,
    create_collection, list_collections, get_collection, update_collection,
    delete_collection, create_document, get_job, retry_job, create_reindex_job,
    ensure_default_collection, validate_collection_ids,
    retrieve, hybrid_retrieve, build_sources, format_context,
    rag_generate_stream, rag_generate, extract_text_from_file, UPLOAD_DIR,
    upload_file_bytes as minio_upload_file_bytes,
)
from rag.generator import RAG_SYSTEM_PROMPT
from rag.job_queue import list_workers
from rag.document_parser import SUPPORTED_EXTENSIONS
from rag.minio_client import delete_object as minio_delete_object
from redis_client import cache_get, cache_set, cache_delete, cache_delete_pattern

app = FastAPI(title="AI Chat with Auth")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

JWT_SECRET = "ai-chat-jwt-secret-key-2025"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72

def get_model_config():
    config = load_config()
    base_url = config['base-url']
    api_key = config['api-key']
    model_name = config['model-name']
    vision_model_name = config.get('vision-model-name', '').strip()
    vision_base_url = config.get('vision-base-url', base_url).strip() or base_url
    vision_api_key = config.get('vision-api-key', api_key).strip() or api_key
    return {
        'base_url': base_url,
        'api_key': api_key,
        'model_name': model_name,
        'vision_model_name': vision_model_name,
        'vision_base_url': vision_base_url,
        'vision_api_key': vision_api_key,
    }

MAX_CHAT_FILE_SIZE = 10 * 1024 * 1024
MAX_DOCUMENT_TEXT = 30_000
MAX_TOTAL_DOCUMENT_TEXT = 80_000
MAX_IMAGES_PER_REQUEST = 6
MAX_KB_FILE_SIZE = int(os.getenv("KB_MAX_FILE_SIZE_MB", "20")) * 1024 * 1024
MAX_KB_FILES_PER_BATCH = int(os.getenv("KB_MAX_FILES_PER_BATCH", "10"))
CHAT_UPLOAD_DIR = UPLOAD_DIR / 'chat'
CHAT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
ALLOWED_DOCUMENT_EXTENSIONS = {
    '.txt', '.md', '.csv', '.py', '.js', '.ts', '.html', '.css',
    '.json', '.xml', '.yaml', '.yml', '.sql', '.pdf', '.docx',
    '.pptx', '.xlsx',
}

DB_CONFIG = {
    'host': 'localhost',
    'port': 3307,
    'user': 'root',
    'password': '1234',
    'database': 'ai_chat',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
}

def get_db():
    return pymysql.connect(**DB_CONFIG)

def get_llm(requires_vision: bool = False, web_search: bool = False):
    model_config = get_model_config()
    if requires_vision and not model_config['vision_model_name']:
        raise HTTPException(
            status_code=400,
            detail=(
                "当前聊天模型不支持图片理解。请在 key.txt 中配置 "
                "vision-model-name、vision-base-url 和 vision-api-key 后重试。"
            ),
        )
    if web_search:
        return ChatOpenAI(
            model=model_config['vision_model_name'] if requires_vision else model_config['model_name'],
            openai_api_key=model_config['vision_api_key'] if requires_vision else model_config['api_key'],
            openai_api_base=model_config['vision_base_url'] if requires_vision else model_config['base_url'],
            streaming=True,
            temperature=0.7,
            max_tokens=4096,
            extra_body={"enable_search": True},
        )
    return ChatOpenAI(
        model=model_config['vision_model_name'] if requires_vision else model_config['model_name'],
        openai_api_key=model_config['vision_api_key'] if requires_vision else model_config['api_key'],
        openai_api_base=model_config['vision_base_url'] if requires_vision else model_config['base_url'],
        streaming=True,
        temperature=0.7,
        max_tokens=4096,
    )


class _DashScopeWebSearch:
    """百炼联网搜索: 调用 DashScope 原生 generation API（OpenAI 兼容模式对 deepseek 不支持 enable_search）"""

    NATIVE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"

    def __init__(self, model_config: dict):
        self.model = model_config.get('model_name') or 'deepseek-v4-pro'
        # 兼容 base_url 是 OpenAI 兼容端点的情况
        api_key = model_config.get('api_key') or model_config.get('vision_api_key')
        self.api_key = api_key
        self.base_url = model_config.get('base_url') or ''

    def _convert_messages(self, langchain_messages) -> List[dict]:
        out = []
        for m in langchain_messages:
            role = getattr(m, 'type', None) or getattr(m, 'role', None) or 'user'
            role_map = {'human': 'user', 'ai': 'assistant', 'system': 'system'}
            role = role_map.get(role, role)
            content = getattr(m, 'content', '')
            if isinstance(content, list):
                text = ''.join([
                    c.get('text', '') if isinstance(c, dict) else str(c)
                    for c in content
                ])
            else:
                text = str(content)
            out.append({"role": role, "content": text})
        return out

    def _resolve_endpoint(self) -> str:
        # 如果用户配置的是 compatible-mode 端点，则切到原生 generation 端点
        if 'compatible-mode' in (self.base_url or ''):
            return self.NATIVE_URL
        return self.NATIVE_URL

    async def astream(self, langchain_messages):
        payload = {
            "model": self.model,
            "input": {"messages": self._convert_messages(langchain_messages)},
            "parameters": {
                "enable_search": True,
                "incremental_output": True,
                "result_format": "message",
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", self._resolve_endpoint(), json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = data.get("output", {}).get("choices") or data.get("choices")
                        if not choices:
                            continue
                        msg = choices[0].get("message") or choices[0].get("delta") or {}
                        content = msg.get("content")
                        if content:
                            yield content

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    email: str = Field(..., min_length=5, max_length=100)
    password: str = Field(..., min_length=6, max_length=100)

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)

class ChatRequest(BaseModel):
    conversation_id: Optional[int] = None
    messages: List[dict]
    knowledge_base_ids: Optional[List[str]] = None
    stream: bool = True
    web_search: bool = False

class CreateConversationRequest(BaseModel):
    title: str = "新对话"

class RenameConversationRequest(BaseModel):
    title: str

class RAGQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    doc_type: Optional[str] = None
    knowledge_base_ids: List[str] = Field(default_factory=list)
    use_rag: bool = True
    stream: bool = True

class AddDocumentRequest(BaseModel):
    title: str
    content: str = ""
    doc_type: str = "text"
    collection_id: Optional[str] = None
    duplicate_mode: str = "skip"

class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)

class UpdateKnowledgeBaseRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)

def create_jwt(user_id: int, username: str) -> str:
    payload = {
        'user_id': user_id,
        'username': username,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRE_HOURS),
        'iat': datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的登录凭证")

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return verify_jwt(credentials.credentials)

def get_db_conn():
    return pymysql.connect(**DB_CONFIG)

@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / 'index.html')

@app.post("/api/register")
async def register(req: RegisterRequest):
    conn = get_db_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = %s", (req.username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="用户名已被注册")
        cursor.execute("SELECT id FROM users WHERE email = %s", (req.email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="邮箱已被注册")
        password_hash = bcrypt.hashpw(req.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
            (req.username, req.email, password_hash)
        )
        conn.commit()
        return {"message": "注册成功"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")
    finally:
        conn.close()

@app.post("/api/login")
async def login(req: LoginRequest):
    conn = get_db_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, password_hash FROM users WHERE username = %s", (req.username,))
        user = cursor.fetchone()
        if not user:
            cursor.execute("SELECT id, username, email, password_hash FROM users WHERE email = %s", (req.username,))
            user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not bcrypt.checkpw(req.password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = create_jwt(user['id'], user['username'])
        return {"token": token, "user": {"id": user['id'], "username": user['username'], "email": user['email']}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")
    finally:
        conn.close()

@app.get("/api/user/me")
async def get_me(user: dict = Depends(get_current_user)):
    conn = get_db_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, created_at FROM users WHERE id = %s", (user['user_id'],))
        u = cursor.fetchone()
        if not u:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"id": u['id'], "username": u['username'], "email": u['email'],
                "created_at": u['created_at'].isoformat() if u['created_at'] else None}
    finally:
        conn.close()

@app.get("/api/conversations")
async def list_conversations(user: dict = Depends(get_current_user)):
    uid = user['user_id']
    cached = cache_get(f"conv:list:{uid}")
    if cached is not None:
        return cached
    conn = get_db_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, knowledge_base_ids_json, created_at, updated_at "
            "FROM conversations WHERE user_id = %s ORDER BY updated_at DESC",
            (uid,)
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            try:
                knowledge_base_ids = json.loads(row.get("knowledge_base_ids_json") or "[]")
            except json.JSONDecodeError:
                knowledge_base_ids = []
            result.append({
                "id": row["id"],
                "title": row["title"],
                "knowledge_base_ids": knowledge_base_ids,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            })
        cache_set(f"conv:list:{uid}", result, expire=60)
        return result
    finally:
        conn.close()

@app.post("/api/conversations")
async def create_conversation(req: CreateConversationRequest, user: dict = Depends(get_current_user)):
    uid = user['user_id']
    conn = get_db_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO conversations (user_id, title) VALUES (%s, %s)",
            (uid, req.title)
        )
        conn.commit()
        cache_delete(f"conv:list:{uid}")
        return {"id": cursor.lastrowid, "title": req.title}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.put("/api/conversations/{conv_id}")
async def rename_conversation(conv_id: int, req: RenameConversationRequest, user: dict = Depends(get_current_user)):
    uid = user['user_id']
    conn = get_db_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM conversations WHERE id = %s AND user_id = %s", (conv_id, uid))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="会话不存在")
        cursor.execute("UPDATE conversations SET title = %s WHERE id = %s", (req.title, conv_id))
        conn.commit()
        cache_delete(f"conv:list:{uid}")
        cache_delete(f"conv:msg:{uid}:{conv_id}")
        return {"message": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: int, user: dict = Depends(get_current_user)):
    uid = user['user_id']
    conn = get_db_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM conversations WHERE id = %s AND user_id = %s", (conv_id, uid))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="会话不存在")
        cursor.execute("DELETE FROM conversations WHERE id = %s", (conv_id,))
        conn.commit()
        cache_delete(f"conv:list:{uid}")
        cache_delete(f"conv:msg:{uid}:{conv_id}")
        return {"message": "已删除"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/conversations/{conv_id}/messages")
async def get_messages(conv_id: int, user: dict = Depends(get_current_user)):
    uid = user['user_id']
    cache_key = f"conv:msg:{uid}:{conv_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    conn = get_db_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM conversations WHERE id = %s AND user_id = %s", (conv_id, uid))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="会话不存在")
        cursor.execute(
            "SELECT id, role, content, attachments_json, sources_json, created_at "
            "FROM messages WHERE conversation_id = %s ORDER BY id ASC",
            (conv_id,)
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            try:
                attachments = json.loads(row.get('attachments_json') or '[]')
            except (TypeError, json.JSONDecodeError):
                attachments = []
            try:
                sources = json.loads(row.get("sources_json") or "[]")
            except (TypeError, json.JSONDecodeError):
                sources = []
            result.append({
                "id": row['id'],
                "role": row['role'],
                "content": row['content'],
                "attachments": attachments,
                "sources": sources,
                "created_at": row['created_at'].isoformat() if row['created_at'] else None,
            })
        cache_set(cache_key, result, expire=120)
        return result
    finally:
        conn.close()

def _normalise_attachment_reference(attachment: dict) -> dict:
    return {
        key: attachment.get(key)
        for key in ('id', 'name', 'type', 'mime', 'docId')
        if attachment.get(key) is not None
    }


def _load_chat_attachment(user_id: int, attachment: dict):
    attachment_id = str(attachment.get('id', ''))
    try:
        attachment_id = str(uuid.UUID(attachment_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="附件标识无效，请重新上传")

    user_dir = CHAT_UPLOAD_DIR / str(user_id)
    metadata_path = user_dir / f'{attachment_id}.json'
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="附件已失效，请重新上传")

    try:
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="附件元数据损坏，请重新上传")

    file_path = user_dir / metadata['stored_name']
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="附件文件不存在，请重新上传")
    return metadata, file_path


def _extract_image_text_windows(file_path: Path) -> str:
    if sys.platform != 'win32':
        return ''

    script = r'''
$ErrorActionPreference = 'Stop'
$path = $env:CHAT_IMAGE_PATH
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
function Await($operation, [Type]$resultType) {
  $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
      $_.Name -eq 'AsTask' -and
      $_.IsGenericMethod -and
      $_.GetParameters().Count -eq 1
    } |
    Select-Object -First 1
  $task = $method.MakeGenericMethod($resultType).Invoke($null, @($operation))
  $task.Wait()
  return $task.Result
}
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { exit 0 }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::Write($result.Text)
'''
    env = dict(os.environ)
    env['CHAT_IMAGE_PATH'] = str(file_path.resolve())
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            env=env,
            timeout=20,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


def _build_user_message_content(
    content: str,
    attachments: List[dict],
    user_id: int,
    use_vision: bool = True,
):
    text_sections = [content.strip() or "请分析这些附件"]
    image_blocks = []
    document_chars = 0

    for attachment in attachments:
        if attachment.get('type') == 'kb':
            text_sections.append(f"[知识库文件: {attachment.get('name', '未命名')}]")
            continue

        metadata, file_path = _load_chat_attachment(user_id, attachment)
        if metadata['type'] == 'image':
            if not use_vision:
                image_text = _extract_image_text_windows(file_path)
                if image_text:
                    text_sections.append(
                        f"<图片OCR name=\"{metadata['name']}\">\n"
                        f"{image_text[:MAX_DOCUMENT_TEXT]}\n</图片OCR>"
                    )
                else:
                    text_sections.append(
                        f"[图片: {metadata['name']}] "
                        "未识别到文字。当前模型只能处理图片中的文字，不能可靠描述纯视觉内容。"
                    )
                continue
            if len(image_blocks) >= MAX_IMAGES_PER_REQUEST:
                raise HTTPException(
                    status_code=400,
                    detail=f"一次最多发送 {MAX_IMAGES_PER_REQUEST} 张图片",
                )
            encoded = base64.b64encode(file_path.read_bytes()).decode('ascii')
            image_blocks.append({
                'type': 'image_url',
                'image_url': {
                    'url': f"data:{metadata['mime']};base64,{encoded}",
                    'detail': 'auto',
                },
            })
            text_sections.append(f"[图片: {metadata['name']}]")
            continue

        try:
            extracted_text = extract_text_from_file(file_path).strip()
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"无法解析文件 {metadata['name']}: {exc}",
            )
        if not extracted_text:
            raise HTTPException(
                status_code=400,
                detail=f"文件 {metadata['name']} 没有可读取的文本内容",
            )

        remaining = MAX_TOTAL_DOCUMENT_TEXT - document_chars
        if remaining <= 0:
            break
        extracted_text = extracted_text[:min(MAX_DOCUMENT_TEXT, remaining)]
        document_chars += len(extracted_text)
        text_sections.append(
            f"<附件 name=\"{metadata['name']}\">\n{extracted_text}\n</附件>"
        )

    combined_text = '\n\n'.join(text_sections)
    if image_blocks:
        return [{'type': 'text', 'text': combined_text}, *image_blocks], True
    return combined_text, False


def convert_messages(messages: List[dict], user_id: int):
    model_config = get_model_config()
    has_vision_model = bool(model_config['vision_model_name'])
    langchain_messages = []
    has_images = False
    for msg in messages:
        role = msg.get('role', 'user')
        content = msg.get('content', '')
        if role == 'system':
            langchain_messages.append(SystemMessage(content=content))
        elif role == 'user':
            message_attachments = msg.get('attachments') or []
            message_has_images = any(
                attachment.get('type') == 'image'
                for attachment in message_attachments
            )
            built_content, _ = _build_user_message_content(
                content,
                message_attachments,
                user_id,
                use_vision=has_vision_model,
            )
            has_images = has_images or message_has_images
            langchain_messages.append(HumanMessage(content=built_content))
        elif role == 'assistant':
            langchain_messages.append(AIMessage(content=content))
    return langchain_messages, has_vision_model and has_images


def _apply_rag_context(langchain_messages, context: str):
    langchain_messages.insert(0, SystemMessage(content=RAG_SYSTEM_PROMPT))
    for index in range(len(langchain_messages) - 1, -1, -1):
        message = langchain_messages[index]
        if not isinstance(message, HumanMessage):
            continue
        prefix = f"参考信息：\n{context or '未检索到可用的知识库片段。'}\n\n用户问题及附件：\n"
        if isinstance(message.content, str):
            message.content = prefix + message.content
        elif isinstance(message.content, list):
            content_blocks = list(message.content)
            if content_blocks and content_blocks[0].get("type") == "text":
                content_blocks[0] = {
                    **content_blocks[0],
                    "text": prefix + content_blocks[0].get("text", ""),
                }
            else:
                content_blocks.insert(0, {"type": "text", "text": prefix})
            message.content = content_blocks
        break
    return langchain_messages

@app.post("/api/chat")
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    conn = get_db_conn()
    conv_id = req.conversation_id
    user_message_content = ""
    assistant_message_content = ""
    user_message_attachments = []
    selected_kb_ids = []
    sources = []

    if req.messages:
        last_user_msg = next((m for m in reversed(req.messages) if m.get('role') == 'user'), None)
        if last_user_msg:
            user_message_content = last_user_msg.get('content', '')
            user_message_attachments = [
                _normalise_attachment_reference(attachment)
                for attachment in (last_user_msg.get('attachments') or [])
            ]

    try:
        cursor = conn.cursor()
        if conv_id:
            cursor.execute(
                "SELECT id,knowledge_base_ids_json FROM conversations "
                "WHERE id=%s AND user_id=%s",
                (conv_id, user["user_id"]),
            )
            conversation = cursor.fetchone()
            if not conversation:
                raise HTTPException(status_code=404, detail="会话不存在")
            if req.knowledge_base_ids is None:
                try:
                    selected_kb_ids = json.loads(conversation.get("knowledge_base_ids_json") or "[]")
                except json.JSONDecodeError:
                    selected_kb_ids = []
            else:
                selected_kb_ids = req.knowledge_base_ids
        else:
            selected_kb_ids = req.knowledge_base_ids or []

        try:
            selected_kb_ids = validate_collection_ids(user["user_id"], selected_kb_ids)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc))

        langchain_messages, requires_vision = convert_messages(req.messages, user["user_id"])
        if selected_kb_ids:
            retrieval = await hybrid_retrieve(
                user_message_content or "请根据知识库分析附件",
                user["user_id"],
                selected_kb_ids,
                history=req.messages[:-1],
            )
            sources = build_sources(retrieval["items"])
            langchain_messages = _apply_rag_context(
                langchain_messages,
                format_context(retrieval["items"]),
            )
        llm = get_llm(requires_vision=requires_vision, web_search=req.web_search)

        # 联网搜索走 DashScope 原生 API（OpenAI 兼容模式对 deepseek-v4-pro 不支持 enable_search）
        web_search_handler = None
        if req.web_search:
            web_search_handler = _DashScopeWebSearch(get_model_config())

        if not conv_id:
            title_source = user_message_content or (
                user_message_attachments[0].get('name') if user_message_attachments else "新对话"
            )
            title = (title_source[:50] + "...") if len(title_source) > 50 else title_source
            cursor.execute(
                "INSERT INTO conversations (user_id,title,knowledge_base_ids_json) VALUES (%s,%s,%s)",
                (user["user_id"], title, json.dumps(selected_kb_ids)),
            )
            conn.commit()
            conv_id = cursor.lastrowid
        else:
            cursor.execute(
                "UPDATE conversations SET knowledge_base_ids_json=%s WHERE id=%s",
                (json.dumps(selected_kb_ids), conv_id),
            )
            conn.commit()

        if user_message_content or user_message_attachments:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO messages (conversation_id, role, content, attachments_json) "
                "VALUES (%s, 'user', %s, %s)",
                (
                    conv_id,
                    user_message_content or "请分析这些附件",
                    json.dumps(user_message_attachments, ensure_ascii=False),
                ),
            )
            conn.commit()

        if req.stream:
            async def generate():
                nonlocal assistant_message_content, sources
                try:
                    if web_search_handler is not None:
                        async for content in web_search_handler.astream(langchain_messages):
                            if content:
                                assistant_message_content += content
                                yield f"data: {json.dumps({'content': content})}\n\n"
                    else:
                        async for chunk in llm.astream(langchain_messages):
                            content = chunk.content
                            if content:
                                assistant_message_content += content
                                yield f"data: {json.dumps({'content': content})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                finally:
                    if assistant_message_content:
                        db_conn = get_db_conn()
                        try:
                            cur = db_conn.cursor()
                            cur.execute(
                                "INSERT INTO messages "
                                "(conversation_id,role,content,sources_json) VALUES (%s,'assistant',%s,%s)",
                                (
                                    conv_id,
                                    assistant_message_content,
                                    json.dumps(sources, ensure_ascii=False),
                                ),
                            )
                            cur.execute("UPDATE conversations SET updated_at = NOW() WHERE id = %s", (conv_id,))
                            db_conn.commit()
                            cache_delete(f"conv:msg:{user['user_id']}:{conv_id}")
                            cache_delete(f"conv:list:{user['user_id']}")
                        except Exception as save_err:
                            print(f"Save message error: {save_err}")
                        finally:
                            db_conn.close()
                    if sources:
                        yield f"data: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'conv_id': conv_id, 'knowledge_base_ids': selected_kb_ids})}\n\n"
                    yield "data: [DONE]\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
            )
        else:
            if web_search_handler is not None:
                parts = []
                async for content in web_search_handler.astream(langchain_messages):
                    if content:
                        parts.append(content)
                assistant_message_content = "".join(parts)
                from types import SimpleNamespace
                response = SimpleNamespace(content=assistant_message_content)
            else:
                response = await llm.ainvoke(langchain_messages)
                assistant_message_content = response.content
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO messages (conversation_id,role,content,sources_json) "
                "VALUES (%s,'assistant',%s,%s)",
                (conv_id, assistant_message_content, json.dumps(sources, ensure_ascii=False)),
            )
            cursor.execute("UPDATE conversations SET updated_at = NOW() WHERE id = %s", (conv_id,))
            conn.commit()
            cache_delete(f"conv:msg:{user['user_id']}:{conv_id}")
            cache_delete(f"conv:list:{user['user_id']}")
            return {
                "choices": [{"message": {"content": response.content}}],
                "conv_id": conv_id,
                "knowledge_base_ids": selected_kb_ids,
                "sources": sources,
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/upload/chat-file")
async def upload_chat_file(
    file: UploadFile = File(...),
    filename: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    name = Path(filename or file.filename or 'upload').name
    ext = Path(name).suffix.lower()

    if ext not in ALLOWED_IMAGE_EXTENSIONS | ALLOWED_DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}")

    file_bytes = await file.read(MAX_CHAT_FILE_SIZE + 1)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(file_bytes) > MAX_CHAT_FILE_SIZE:
        raise HTTPException(status_code=413, detail="单个附件不能超过 10MB")

    file_type = "image" if ext in ALLOWED_IMAGE_EXTENSIONS else "file"
    mime_type = file.content_type or mimetypes.guess_type(name)[0] or 'application/octet-stream'
    if file_type == 'image':
        try:
            with Image.open(io.BytesIO(file_bytes)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError):
            raise HTTPException(status_code=400, detail="图片文件无效或已损坏")

    attachment_id = str(uuid.uuid4())
    user_dir = CHAT_UPLOAD_DIR / str(user['user_id'])
    user_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f'{attachment_id}{ext}'
    save_path = user_dir / stored_name
    metadata_path = user_dir / f'{attachment_id}.json'
    save_path.write_bytes(file_bytes)
    metadata_path.write_text(
        json.dumps({
            'id': attachment_id,
            'name': name,
            'type': file_type,
            'mime': mime_type,
            'size': len(file_bytes),
            'stored_name': stored_name,
        }, ensure_ascii=False),
        encoding='utf-8',
    )

    return {
        "id": attachment_id,
        "name": name,
        "type": file_type,
        "mime": mime_type,
        "size": len(file_bytes),
        "ext": ext,
    }

# ===== RAG Knowledge Base API =====

@app.on_event("startup")
async def startup():
    conn = get_db_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SHOW COLUMNS FROM messages LIKE 'attachments_json'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE messages ADD COLUMN attachments_json LONGTEXT NULL AFTER content")
            conn.commit()
    finally:
        conn.close()
    cache_delete_pattern("conv:msg:*")
    init_kb_db()


@app.get("/api/knowledge-bases")
async def kb_collections_list(user: dict = Depends(get_current_user)):
    return list_collections(user["user_id"])


@app.post("/api/knowledge-bases")
async def kb_collections_create(
    req: CreateKnowledgeBaseRequest,
    user: dict = Depends(get_current_user),
):
    try:
        return create_collection(user["user_id"], req.name, req.description)
    except pymysql.err.IntegrityError:
        raise HTTPException(status_code=409, detail="同名知识库已存在")


@app.get("/api/knowledge-bases/{collection_id}")
async def kb_collections_get(collection_id: str, user: dict = Depends(get_current_user)):
    collection = get_collection(collection_id, user["user_id"])
    if not collection:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return collection


@app.put("/api/knowledge-bases/{collection_id}")
async def kb_collections_update(
    collection_id: str,
    req: UpdateKnowledgeBaseRequest,
    user: dict = Depends(get_current_user),
):
    try:
        if not update_collection(
            collection_id,
            user["user_id"],
            req.name,
            req.description,
        ):
            raise HTTPException(status_code=404, detail="知识库不存在")
    except pymysql.err.IntegrityError:
        raise HTTPException(status_code=409, detail="同名知识库已存在")
    return get_collection(collection_id, user["user_id"])


@app.delete("/api/knowledge-bases/{collection_id}")
async def kb_collections_delete(collection_id: str, user: dict = Depends(get_current_user)):
    collection = get_collection(collection_id, user["user_id"])
    if not collection:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if collection["is_default"]:
        raise HTTPException(status_code=400, detail="默认知识库不能删除")
    delete_collection(collection_id, user["user_id"])
    return {"message": "已删除"}


@app.get("/api/knowledge-bases/{collection_id}/documents")
async def kb_documents_list(collection_id: str, user: dict = Depends(get_current_user)):
    if not get_collection(collection_id, user["user_id"]):
        raise HTTPException(status_code=404, detail="知识库不存在")
    return list_documents(user["user_id"], collection_id)


@app.post("/api/knowledge-bases/{collection_id}/documents/text", status_code=202)
async def kb_documents_add_text(
    collection_id: str,
    req: AddDocumentRequest,
    user: dict = Depends(get_current_user),
):
    try:
        result = create_document(
            user_id=user["user_id"],
            collection_id=collection_id,
            title=req.title,
            doc_type=req.doc_type or "text",
            source_text=req.content,
            duplicate_mode=req.duplicate_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result["duplicate"]:
        raise HTTPException(
            status_code=409,
            detail=f"相同内容已存在：{result['document']['title']}",
        )
    return result


@app.post("/api/knowledge-bases/{collection_id}/documents/upload", status_code=202)
async def kb_documents_upload(
    collection_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    duplicate_mode: str = Form("skip"),
    user: dict = Depends(get_current_user),
):
    if not get_collection(collection_id, user["user_id"]):
        raise HTTPException(status_code=404, detail="知识库不存在")
    name = Path(file.filename or "upload").name
    extension = Path(name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {extension}")
    data = await file.read(MAX_KB_FILE_SIZE + 1)
    if not data:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(data) > MAX_KB_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"单个知识库文件不能超过 {MAX_KB_FILE_SIZE // 1024 // 1024}MB",
        )
    object_name = f"kb/{user['user_id']}/{collection_id}/{uuid.uuid4().hex}{extension}"
    mime = file.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    minio_object, minio_url = minio_upload_file_bytes(data, object_name, mime)
    try:
        result = create_document(
            user_id=user["user_id"],
            collection_id=collection_id,
            title=title.strip() or name,
            doc_type=extension.lstrip("."),
            filename=name,
            minio_object=minio_object,
            minio_url=minio_url,
            content_bytes=data,
            duplicate_mode=duplicate_mode,
        )
    except Exception:
        minio_delete_object(minio_object)
        raise
    if result["duplicate"]:
        minio_delete_object(minio_object)
        raise HTTPException(
            status_code=409,
            detail=f"相同文件已存在：{result['document']['title']}",
        )
    return result


@app.delete("/api/knowledge-bases/{collection_id}/documents/{document_id}")
async def kb_documents_delete(
    collection_id: str,
    document_id: str,
    user: dict = Depends(get_current_user),
):
    document = get_document(document_id, user["user_id"])
    if not document or document["collection_id"] != collection_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    delete_document(document_id, user["user_id"])
    return {"message": "已删除"}


@app.post("/api/knowledge-bases/{collection_id}/documents/{document_id}/reindex", status_code=202)
async def kb_documents_reindex(
    collection_id: str,
    document_id: str,
    user: dict = Depends(get_current_user),
):
    document = get_document(document_id, user["user_id"])
    if not document or document["collection_id"] != collection_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    return create_reindex_job(document_id, user["user_id"])


@app.get("/api/knowledge-base/jobs/{job_id}")
async def kb_jobs_get(job_id: str, user: dict = Depends(get_current_user)):
    job = get_job(job_id, user["user_id"])
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.post("/api/knowledge-base/jobs/{job_id}/retry", status_code=202)
async def kb_jobs_retry(job_id: str, user: dict = Depends(get_current_user)):
    job = retry_job(job_id, user["user_id"])
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.get("/api/knowledge-base/worker/health")
async def kb_worker_health(user: dict = Depends(get_current_user)):
    del user
    workers = list_workers()
    return {"healthy": bool(workers), "workers": workers}


# Compatibility endpoints mapped to the user's default knowledge base.
@app.get("/api/knowledge-base")
async def kb_list(user: dict = Depends(get_current_user)):
    uid = user['user_id']
    return list_documents(uid, ensure_default_collection(uid))

@app.post("/api/knowledge-base")
async def kb_add(req: AddDocumentRequest, user: dict = Depends(get_current_user)):
    uid = user['user_id']
    result = create_document(
        user_id=uid,
        collection_id=req.collection_id or ensure_default_collection(uid),
        title=req.title,
        doc_type=req.doc_type,
        source_text=req.content,
        duplicate_mode=req.duplicate_mode,
    )
    if result["duplicate"]:
        raise HTTPException(status_code=409, detail="相同内容已存在")
    return result

@app.post("/api/knowledge-base/upload", status_code=202)
async def kb_upload(
    file: UploadFile = File(...),
    title: str = Form(""),
    filename: Optional[str] = Form(None),
    duplicate_mode: str = Form("skip"),
    user: dict = Depends(get_current_user),
):
    uid = user['user_id']
    collection_id = ensure_default_collection(uid)
    if filename:
        file.filename = Path(filename).name
    return await kb_documents_upload(
        collection_id,
        file,
        title,
        duplicate_mode,
        user,
    )

@app.delete("/api/knowledge-base/{doc_id}")
async def kb_delete(doc_id: str, user: dict = Depends(get_current_user)):
    uid = user['user_id']
    ok = delete_document(doc_id, uid)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"message": "已删除"}

@app.get("/api/knowledge-base/{doc_id}")
async def kb_get(doc_id: str, user: dict = Depends(get_current_user)):
    cache_key = f"kb:doc:{user['user_id']}:{doc_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    doc = get_document(doc_id, user['user_id'])
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    cache_set(cache_key, doc, expire=300)
    return doc

# ===== RAG Query API =====

@app.post("/api/rag/query")
async def rag_query(req: RAGQueryRequest, user: dict = Depends(get_current_user)):
    if not req.use_rag:
        return await normal_chat(req, user)

    try:
        collection_ids = req.knowledge_base_ids or [
            collection["id"] for collection in list_collections(user["user_id"])
        ]
        result = await hybrid_retrieve(
            req.query,
            user["user_id"],
            collection_ids,
            vector_top_k=max(req.top_k, 20),
            final_limit=req.top_k,
        )
        retrieved = result["items"]
        if not retrieved:
            return {"answer": "未在知识库中找到相关信息。", "sources": [], "use_rag": False}

        context = format_context(retrieved)
        sources = build_sources(retrieved)

        if req.stream:
            async def generate():
                async for chunk in rag_generate_stream(req.query, context):
                    yield f"data: {chunk}\n\n"
                yield f"data: {json.dumps({'sources': sources, 'use_rag': True})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
            )
        else:
            answer = await rag_generate(req.query, context)
            return {"answer": answer, "sources": sources, "use_rag": True}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG查询失败: {str(e)}")

async def normal_chat(req, user):
    return {"answer": "请使用 /api/chat 端点进行普通对话。", "use_rag": False}

if __name__ == "__main__":
    import uvicorn
    print(f"  Model: {get_model_config()['model_name']}")
    print(f"  MySQL: localhost:3307/ai_chat")
    print(f"  Server: http://localhost:5000")
    uvicorn.run(app, host="0.0.0.0", port=5000)
