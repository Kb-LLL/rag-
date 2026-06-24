# AI 智能对话系统项目介绍

## 项目概述

本项目是一个基于大语言模型（LLM）和 RAG（检索增强生成）技术构建的**多用户 AI 智能对话系统**。系统支持多轮对话、个人知识库管理、文档解析、混合检索（向量 + BM25）、图文多模态理解等核心能力，提供完整的用户体系、对话管理、知识库管理和检索式问答体验。

### 项目亮点
- 完整的多用户体系（注册/登录/JWT 鉴权）
- 支持多知识库管理，按库检索
- 异步任务队列处理文档解析与向量化
- 混合检索（向量检索 + BM25 关键词） + RRF 融合排序
- 多模态支持：图片理解（Vision 模型）+ OCR 降级
- 实时流式回答（SSE），含来源引用 `[1][2]`
- 任务进度可视化，支持重试与重索引
- 30 题检索评测数据集与自动评估

## 核心功能特性

- **用户与权限**：基于 JWT 的无状态鉴权、bcrypt 密码加密、按用户隔离数据
- **多轮对话**：会话管理、消息持久化、Redis 缓存加速
- **知识库 RAG**：多知识库管理、文档上传/解析/切片/向量化、混合检索
- **多模态对话**：支持图片上传与 Vision 模型，无 Vision 时回退 Windows OCR
- **流式响应**：基于 SSE 的打字机效果，回答附引用编号
- **异步任务**：Redis 队列 + Worker 心跳 + 可见性超时 + 自动重试
- **检索评测**：26 题可答 + 4 题拒答，命中率/拒答率/引用正确率多维度评估
- **现代前端**：Vue 3 + Vite + Pinia + Markdown 渲染 + 代码高亮

## 技术架构

系统采用前后端分离 + 异步任务的经典架构。前端 Vue 3 单页应用通过 REST/SSE 与 FastAPI 后端通信；后端通过 LangChain 调用大模型（DeepSeek 等），通过 ChromaDB 进行向量检索，通过 MySQL/Redis/MinIO 分别承担关系数据、缓存与队列、文件存储。知识库的解析、向量化、索引构建由独立的 Worker 进程异步处理。

## 项目目录结构

```
demo1/
├── app.py                    # 后端 FastAPI 主入口（认证、对话、附件、知识库 API）
├── config.py                 # key.txt 配置加载与缓存
├── redis_client.py           # Redis 客户端与缓存工具
├── kb_worker.py              # 知识库异步任务 Worker（心跳、领取、续约）
├── md_to_ppt.py              # 自研 Markdown→PPT 生成工具（ppt-master）
├── requirements.txt          # Python 依赖清单
├── key.txt                   # 模型 API 配置（base-url / api-key / model-name）
├── index.html                # 入口 HTML
├── frontend/                 # 前端项目（Vue 3 + Vite）
│   ├── src/
│   │   ├── views/            # 页面组件：Login/Register/Chat/KnowledgeBase
│   │   ├── api/index.js      # Axios 封装与 API 调用
│   │   ├── stores/auth.js    # Pinia 用户状态
│   │   ├── router/index.js   # Vue Router 路由守卫
│   │   └── assets/main.css   # 全局样式
│   ├── package.json
│   └── vite.config.js
├── rag/                      # RAG 核心模块
│   ├── embeddings.py         # BGE-M3 嵌入模型加载与文本/图像向量化
│   ├── document_parser.py    # 多格式文档解析（TXT/MD/CSV/PDF/DOCX/PPTX/XLSX）
│   ├── knowledge_base.py     # 知识库 CRUD、文档管理、ChromaDB 索引
│   ├── retriever.py          # 向量检索 + BM25 + RRF 融合 + 来源构建
│   ├── generator.py          # RAG Prompt 构造与流式/非流式生成
│   ├── minio_client.py       # MinIO 对象存储客户端
│   ├── job_queue.py          # Redis 任务队列（Lua 原子领取 + 续约）
│   ├── evaluation.py         # 30 题检索评测脚本
│   └── data/                 # 嵌入数据 / 上传文件 / ChromaDB 持久化
└── tests/                    # 单元与回归测试
```

## 实体关系与数据模型

系统核心数据模型包含 5 张 MySQL 表与 1 个向量集合。MySQL 存储结构化数据，ChromaDB 存储文档块的向量表示，二者通过 `document_id` 关联。

| 表名 | 主要字段 | 说明 |
| --- | --- | --- |
| `users` | id, username, email, password_hash | 用户表 |
| `conversations` | id, user_id, title, knowledge_base_ids_json | 会话表（关联多个知识库） |
| `messages` | id, conversation_id, role, content, attachments_json, sources_json | 消息表（含附件与来源） |
| `knowledge_collections` | id, user_id, name, description, is_default | 知识库集合表 |
| `documents` | id, collection_id, title, doc_type, status, minio_object | 文档表（status: pending/ready/failed） |
| `kb_jobs` | id, document_id, status, attempts, error_message | 异步任务表 |
| `chunks` (ChromaDB) | id, document_id, text, embedding, metadata | 文档块向量集合 |

## 系统启动顺序

项目运行需要启动 3 个进程，并依赖 MySQL / Redis / MinIO 三个外部服务。

1. **启动 MySQL / Redis / MinIO** 三个外部服务
2. **安装依赖**：`pip install -r requirements.txt` 与 `npm install`
3. **配置 key.txt**：填入大模型 base-url、api-key、model-name
4. **终端 1：`python app.py`** — 启动 FastAPI（端口 5000）
5. **终端 2：`python kb_worker.py`** — 启动知识库异步 Worker
6. **终端 3：`npm run dev`** — 启动 Vue 前端（端口 3000）
7. 浏览器打开 `http://localhost:3000`，注册账号并登录

## 后端核心：用户认证与会话管理

`app.py` 是后端入口，使用 FastAPI 框架。这里展示 JWT 生成、登录校验与会话管理的核心实现。

```python
# app.py - 鉴权与会话管理
JWT_SECRET = "ai-chat-jwt-secret-key-2025"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72

def create_jwt(user_id: int, username: str) -> str:
    payload = {
        'user_id': user_id,
        'username': username,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRE_HOURS),
        'iat': datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return verify_jwt(credentials.credentials)

@app.post("/api/login")
async def login(req: LoginRequest):
    # 优先用户名查，失败再用 email 查
    cursor.execute("SELECT id, username, email, password_hash FROM users WHERE username = %s", (req.username,))
    user = cursor.fetchone() or cursor.execute(..., email) and fetchone()
    if not user or not bcrypt.checkpw(req.password.encode('utf-8'), user['password_hash'].encode('utf-8')):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"token": create_jwt(user['id'], user['username']), "user": {...}}
```

## 后端核心：流式对话与 RAG 注入

`/api/chat` 是系统的核心接口：支持流式输出、自动建会话、保存消息、注入 RAG 上下文。关键代码如下：

```python
# app.py - 流式聊天 + RAG 上下文注入
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    # 1. 解析选中知识库
    selected_kb_ids = req.knowledge_base_ids or []
    selected_kb_ids = validate_collection_ids(user["user_id"], selected_kb_ids)

    # 2. 转换消息（含附件解析）
    langchain_messages, requires_vision = convert_messages(req.messages, user["user_id"])

    # 3. RAG 检索（如有）
    if selected_kb_ids:
        retrieval = await hybrid_retrieve(query, user_id, kb_ids, history=req.messages[:-1])
        sources = build_sources(retrieval["items"])
        langchain_messages = _apply_rag_context(langchain_messages, format_context(retrieval["items"]))

    # 4. 流式返回
    llm = get_llm(requires_vision=requires_vision)
    async def generate():
        async for chunk in llm.astream(langchain_messages):
            yield f"data: {json.dumps({'content': chunk.content})}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

## 后端核心：附件处理（图片/文档）

`/api/upload/chat-file` 与 `_build_user_message_content` 实现附件解析。图片：优先以 Base64 发送给 Vision 模型；若未配置 Vision，则调用 Windows OCR 识别图片文字。文档：使用 `extract_text_from_file` 解析，按 30k 字符截断并以 `<附件>` 标签注入。

```python
# app.py - 附件处理核心逻辑
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
ALLOWED_DOCUMENT_EXTENSIONS = {'.txt','.md','.csv','.py','.js','.pdf','.docx','.pptx','.xlsx'}

@app.post("/api/upload/chat-file")
async def upload_chat_file(file: UploadFile = File(...), ...):
    # 校验后写入 CHAT_UPLOAD_DIR/<uid>/<uuid>.<ext>
    # 并保存元数据 JSON
    attachment_id = str(uuid.uuid4())
    save_path = user_dir / f'{attachment_id}{ext}'
    save_path.write_bytes(file_bytes)
    metadata_path.write_text(json.dumps({...}), encoding='utf-8')
    return {"id": attachment_id, "name": name, "type": file_type, "size": len(file_bytes)}
```

## RAG 核心：文档解析

`rag/document_parser.py` 支持 TXT/Markdown/CSV/JSON/PDF/DOCX/PPTX/XLSX。解析后按 Markdown 标题或固定长度切分，每段带 `locator`（页码/章节）以便回答时定位来源。

```python
# rag/document_parser.py - 文档解析入口
TEXT_EXTENSIONS = {".txt",".md",".py",".js",".ts",".html",".css",".json",".xml",".yaml",".yml",".sql"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".csv", ".pdf", ".docx", ".pptx", ".xlsx"}

@dataclass
class Section:
    text: str
    locator: Dict[str, Any]  # {"section": "...", "page": 1}

def parse_document(path: Path) -> List[Section]:
    ext = path.suffix.lower()
    if ext in TEXT_EXTENSIONS:  return _parse_text(path)
    if ext == ".csv":           return _parse_csv(path)
    if ext == ".pdf":           return _parse_pdf(path)
    if ext == ".docx":          return _parse_docx(path)
    if ext == ".pptx":          return _parse_pptx(path)
    if ext == ".xlsx":          return _parse_xlsx(path)
    raise ValueError(f"Unsupported: {ext}")
```

## RAG 核心：嵌入模型

`rag/embeddings.py` 加载本地 BGE-M3 模型（1024 维），对文本与图像描述进行向量化，并使用 `normalize_embeddings=True` 余弦相似度友好。

```python
# rag/embeddings.py
from sentence_transformers import SentenceTransformer

MODEL_PATH = str(RAG_DIR / 'models' / 'bge-m3')
_model = None

def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_PATH, trust_remote_code=True)
    return _model

def get_text_embedding(text: str) -> np.ndarray:
    return get_model().encode(text, normalize_embeddings=True).astype(np.float32)

def get_embedding_dim() -> int:
    return 1024
```

## RAG 核心：异步任务队列

`rag/job_queue.py` 使用 Redis + Lua 脚本实现**原子化的任务领取**。Worker 持有 `claim_token` 与 `visibility_timeout`，超时未续约的任务会被重新入队。`kb_worker.py` 是独立的消费者进程。

```python
# rag/job_queue.py - 原子领取（Lua）
CLAIM_SCRIPT = """
local job_id = redis.call('RPOP', KEYS[1])
if not job_id then return nil end
redis.call('ZADD', KEYS[2], ARGV[1], job_id)  -- processing zset: score=expireAt
redis.call('HSET', KEYS[3], job_id, ARGV[2])  -- claim_token
return job_id
"""

def claim(timeout: int = 2):
    redis = get_redis()
    token = uuid.uuid4().hex
    job_id = redis.eval(CLAIM_SCRIPT, 3, QUEUE_KEY, PROCESSING_KEY, CLAIMS_KEY,
                        time.time() + VISIBILITY_TIMEOUT, token)
    return {"job_id": job_id, "claim_token": token} if job_id else None
```

## RAG 核心：Worker 主循环

`kb_worker.py` 是知识库的"心脏"：心跳上报、领取任务、续约、执行 `process_index_job`、失败重试。10 秒一次心跳，15 秒回收超时任务。

```python
# kb_worker.py
def main():
    init_db()
    worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    active_claim = {"job_id": None, "token": None}
    active_lock = threading.Lock()

    def heartbeat_loop():
        while True:
            set_worker_heartbeat(worker_id, {...})
            with active_lock:
                if active_claim["job_id"]:
                    heartbeat_claim(active_claim["job_id"], active_claim["token"])
            time.sleep(10)

    threading.Thread(target=heartbeat_loop, daemon=True).start()
    while True:
        if time.time() - last_recovery > 15:
            requeue_expired(); last_recovery = time.time()
        claimed = claim(timeout=2)
        if not claimed: continue
        # 续约 → 解析/切块/向量化 → 入库 → ack
        result = process_index_job(claimed["job_id"], claimed["claim_token"])
        acknowledge(claimed["job_id"], claimed["claim_token"])
```

## RAG 核心：混合检索（向量 + BM25 + RRF）

`rag/retriever.py` 是 RAG 的"智能大脑"。先做向量检索（ChromaDB 余弦相似度），再用 jieba 分词做 BM25 关键词打分，最后用 **Reciprocal Rank Fusion** 融合排序，保证语义匹配与关键词命中兼具。

```python
# rag/retriever.py
import jieba
import math

def _bm25_scores(corpus, query_tokens):
    k1, b = 1.5, 0.75
    df = {t: sum(1 for d in corpus if t in d) for t in set(q for d in corpus for q in d)}
    idf = {t: math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5)) for t in df}
    return [sum(idf[t]*f*(k1+1)/(f + k1*(1-b+b*len(d)/avgdl))
                for t,f in Counter(d).items() if t in idf) for d in corpus]

def reciprocal_rank_fusion(rankings, limit=12, k=60):
    merged = {}
    for r in rankings:
        for pos, item in enumerate(r, 1):
            cid = item["id"]
            merged.setdefault(cid, dict(item))["rrf_score"] = merged.get(cid,{}).get("rrf_score",0) + 1.0/(k+pos)
    return sorted(merged.values(), key=lambda x: x["rrf_score"], reverse=True)[:limit]
```

## RAG 核心：生成器

`rag/generator.py` 负责构造 RAG Prompt 与流式调用大模型。系统 Prompt 强调：**严格基于参考信息**、每个事实必须紧跟来源编号、覆盖不足时**拒绝编造**。

```python
# rag/generator.py
RAG_SYSTEM_PROMPT = """你是一个基于知识库的智能问答助手。请根据提供的参考信息回答用户的问题。
要求：
1. 严格基于提供的参考信息回答问题，不要编造不存在的知识
2. 如果参考信息不足以回答问题，请明确说明
3. 引用来源时标注编号，如 [1][2]
4. 回答要简洁准确，条理清晰
6. 每个事实性结论必须紧跟来源编号，如 [1] 或 [1][2]
7. 参考信息没有覆盖的问题，明确回答"知识库中没有足够信息"，不要使用模型常识补写"""

async def rag_generate_stream(query, context, history=None):
    llm = get_llm()
    messages = [SystemMessage(content=RAG_SYSTEM_PROMPT), *history,
                HumanMessage(content=f"参考信息：\n{context}\n\n用户问题：{query}")]
    async for chunk in llm.astream(messages):
        yield json.dumps({'content': chunk.content})
```

## 前端核心：API 封装与状态管理

前端使用 Axios 统一封装请求、Pinia 管理用户态，Vue Router 守卫未登录路由。

```javascript
// frontend/src/api/index.js
import axios from 'axios'
import { useAuthStore } from '@/stores/auth'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) config.headers.Authorization = `Bearer ${auth.token}`
  return config
})

api.interceptors.response.use(
  (r) => r.data,
  (err) => { if (err.response?.status === 401) { /* 跳登录 */ } return Promise.reject(err) }
)

export const chat = (data) => api.post('/chat', data, { responseType: 'stream' })
export const uploadChatFile = (form) => api.post('/upload/chat-file', form)
export const listCollections = () => api.get('/knowledge-bases')
```

## 前端核心：知识库页面

`KnowledgeBaseView.vue` 实现知识库的列表、上传、进度展示。Worker 状态通过 `/api/knowledge-base/worker/health` 轮询判断。

```vue
<!-- frontend/src/views/KnowledgeBaseView.vue 核心片段 -->
<template>
  <div class="kb-page">
    <div class="worker-status" :class="{ healthy: workerHealthy }">
      <span class="status-dot"></span>
      {{ workerHealthy ? `索引服务在线（${workerCount}）` : '索引服务未运行' }}
    </div>
    <aside class="collections-panel">
      <button v-for="c in collections" :key="c.id"
        :class="['collection-item', { active: c.id === activeCollectionId }]"
        @click="selectCollection(c.id)">
        <i class="fa-regular fa-folder"></i>
        <span>{{ c.name }}</span>
        <span class="collection-count">{{ c.document_count || 0 }}</span>
      </button>
    </aside>
  </div>
</template>
```

## 配置管理与缓存

`config.py` 与 `redis_client.py` 提供统一的配置加载和缓存能力。`load_config()` 解析 `key.txt`，并支持缓存避免重复 IO；`redis_client` 提供 `cache_get/set/delete/delete_pattern` 的容错封装。

```python
# config.py
def load_config(force_reload: bool = False) -> Dict[str, str]:
    global _config_cache
    if _config_cache is not None and not force_reload:
        return _config_cache
    config = {}
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            if ':' in line:
                k, v = line.split(':', 1)
                config[k.strip()] = v.strip()
    _config_cache = config
    return config

# redis_client.py - 容错缓存
def cache_get(key: str):
    try:
        val = get_redis().get(key)
        return json.loads(val) if val else None
    except Exception:
        return None
```

## 检索评测

`rag/evaluation.py` 内置 30 题评测集（26 个可答 + 4 个无答案），输出命中率、拒答率、引用正确率等指标。

```bash
# 自动化评测：先建临时知识库并灌入评测语料
python -m rag.evaluation --username your-user --password your-password --seed-fixture

# 使用现有知识库评测
python -m rag.evaluation --username your-user --password your-password --collection-id your-kb-id
```

输出到 `rag/eval_results.json`，包含：
- 检索命中率（Top-K 包含正确答案）
- 答案关键事实命中率
- 引用正确率
- 无答案拒答率

## 部署与运维要点

| 项目 | 配置/默认值 | 环境变量 |
| --- | --- | --- |
| MySQL | localhost:3307 / ai_chat | `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE` |
| Redis | localhost:6379 | `REDIS_HOST/PORT/DB/PASSWORD` |
| MinIO | localhost:9000 | `MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET` |
| 知识库文件 | 20MB / 10 个 / 批 | `KB_MAX_FILE_SIZE_MB`、`KB_MAX_FILES_PER_BATCH` |
| 任务重试 | 3 次 | `KB_JOB_MAX_ATTEMPTS` |
| 任务可见性 | 300 秒 | `KB_JOB_VISIBILITY_TIMEOUT` |
| Embedding 批大小 | 16 | `KB_EMBEDDING_BATCH_SIZE` |

## 测试策略

- **核心单测**：`test_knowledge_base_core.py` 覆盖知识库 CRUD、向量化、检索
- **附件回归**：`test_attachment_pipeline.py` 覆盖图片/文档/OCR/Vision 切换
- **聊天改进**：`test_chat_improvements.py` 覆盖流式、RAG 注入、会话保存
- **端到端 RAG**：`test_rag.py` 覆盖完整问答链路
- **编译检查**：`python -m py_compile app.py kb_worker.py rag\*.py`
- **前端构建**：`npm run build`

## 总结与项目价值

本项目从 0 到 1 构建了一个**生产级 AI 智能对话平台**，覆盖了：

1. 完整 Web 全栈（Vue 3 + FastAPI）
2. 用户体系与会话持久化（JWT + MySQL + Redis 缓存）
3. 多模态 LLM 调用（LangChain + OpenAI 兼容协议）
4. 完整的 RAG 链路（解析→切片→嵌入→混合检索→生成）
5. 异步任务体系（Redis 队列 + 心跳 + 可见性 + 重试）
6. 检索评测（30 题自动化评估）
7. 工具链自研（Markdown→PPT 工具 `md_to_ppt.py`）

这套架构既可作为学习 RAG 工程化的范例，也可以作为搭建企业内部知识库问答、客服机器人、文档助手等场景的脚手架。
