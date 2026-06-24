# AI Chat 智能对话与 RAG 知识库系统

基于 FastAPI、Vue 3、MySQL、Redis、MinIO、ChromaDB 和本地 BGE-M3 向量模型构建的智能对话系统。项目支持用户注册登录、多轮对话、流式输出、聊天附件、联网搜索、知识库管理，以及基于知识库的 RAG 问答。

## 功能概览

| 模块     | 说明                                                         |
| -------- | ------------------------------------------------------------ |
| 用户认证 | 注册、登录、JWT 鉴权，前端通过 `Authorization: Bearer <token>` 调用接口 |
| 智能对话 | 多轮上下文、SSE 流式响应、历史会话管理、Markdown 渲染        |
| 附件分析 | 聊天中可上传图片和文档；图片可走视觉模型，文档会提取文本后放入提示词 |
| 联网搜索 | 聊天时可开启 `web_search`，后端调用 DashScope 原生搜索能力   |
| 知识库   | 支持创建多个知识库，上传文件或粘贴文本，后台异步建立索引     |
| RAG 问答 | 向量检索 + BM25 关键词检索 + RRF 融合 + LLM 重排 + 带来源回答 |
| 异步索引 | Redis 队列分发任务，`kb_worker.py` 独立处理文档解析、分块、向量化和入库 |
| 对象存储 | MinIO 保存知识库上传的原始文件，便于重建索引、下载和删除     |

## 技术栈

| 层级     | 技术                                                         |
| -------- | ------------------------------------------------------------ |
| 前端     | Vue 3、Vite、Pinia、Vue Router、Axios、Marked、Highlight.js  |
| 后端     | Python、FastAPI、Uvicorn、PyMySQL、PyJWT、bcrypt             |
| 大模型   | LangChain OpenAI 兼容接口，配置来自 `key.txt`                |
| RAG      | BAAI/bge-m3、SentenceTransformers、ChromaDB、jieba BM25      |
| 文档解析 | PyMuPDF、python-docx、python-pptx、openpyxl、CSV/JSON/Markdown/代码文本 |
| 基础设施 | MySQL、Redis、MinIO                                          |

## 目录结构

```text
demo1/
|-- app.py                    # FastAPI 后端入口
|-- config.py                 # 读取 key.txt 中的大模型配置
|-- redis_client.py           # Redis 连接与缓存工具
|-- kb_worker.py              # 知识库异步索引 Worker
|-- requirements.txt          # Python 依赖
|-- docker-compose.yml        # MySQL / Redis / MinIO 本地开发环境
|-- frontend/                 # Vue 3 前端
|   |-- src/api/index.js      # Axios API 封装
|   |-- src/router/index.js   # 前端路由
|   |-- src/views/            # 登录、注册、聊天、知识库页面
|   |-- package.json
|   `-- vite.config.js
`-- rag/
    |-- document_parser.py    # 文档解析与分块
    |-- embeddings.py         # BGE-M3 向量模型加载
    |-- generator.py          # RAG 生成 Prompt 与 LLM 调用
    |-- job_queue.py          # Redis 任务队列
    |-- knowledge_base.py     # 知识库元数据、索引、任务状态
    |-- minio_client.py       # MinIO 上传、下载、删除
    `-- retriever.py          # 混合检索、RRF 融合、重排
```

## 环境要求

| 环境           | 建议版本                         |
| -------------- | -------------------------------- |
| Python         | 3.10+，推荐 3.11                 |
| Node.js        | 18+                              |
| MySQL          | 8.0                              |
| Redis          | 7.x                              |
| MinIO          | 最新稳定版                       |
| Docker Desktop | 用于一键启动 MySQL、Redis、MinIO |

Windows 可以用 `winget` 安装常用环境：

```powershell
winget install Python.Python.3.11
winget install OpenJS.NodeJS.LTS
winget install Docker.DockerDesktop
winget install Git.Git
```

安装完成后检查版本：

```powershell
python --version
node --version
npm --version
docker --version
git --version
```

## 快速启动

### 1. 启动基础设施

项目根目录已提供 `docker-compose.yml`，默认会启动：

| 服务         | 地址                    | 账号                      |
| ------------ | ----------------------- | ------------------------- |
| MySQL        | `localhost:3307`        | `root / 1234`             |
| Redis        | `localhost:6379`        | 无密码                    |
| MinIO API    | `localhost:9000`        | `minioadmin / minioadmin` |
| MinIO 控制台 | `http://localhost:9001` | `minioadmin / minioadmin` |

启动命令：

```powershell
cd F:\demo1
docker compose up -d
```

查看容器状态：

```powershell
docker compose ps
```

### 2. 初始化 MySQL 基础表

后端启动时会自动创建和迁移知识库相关表，但用户、会话、消息三张基础表需要先创建：

```sql
CREATE DATABASE IF NOT EXISTS ai_chat
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE ai_chat;

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(50) UNIQUE NOT NULL,
  email VARCHAR(100) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS conversations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  title VARCHAR(200) DEFAULT '新对话',
  knowledge_base_ids_json LONGTEXT DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS messages (
  id INT AUTO_INCREMENT PRIMARY KEY,
  conversation_id INT NOT NULL,
  role VARCHAR(20) NOT NULL,
  content LONGTEXT NOT NULL,
  attachments_json LONGTEXT NULL,
  sources_json LONGTEXT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

如果使用 Docker 中的 MySQL，可以这样进入：

```powershell
docker exec -it ai-chat-mysql mysql -uroot -p1234
```

### 3. 配置大模型 Key

在项目根目录创建 `key.txt`：

```text
base-url: https://dashscope.aliyuncs.com/compatible-mode/v1
model-name: deepseek-v4-pro
api-key: sk-your-api-key
```

如需图片理解能力，再增加视觉模型配置：

```text
vision-model-name: qwen-vl-max
vision-base-url: https://dashscope.aliyuncs.com/compatible-mode/v1
vision-api-key: sk-your-vision-api-key
```

`key.txt` 包含敏感信息，不要提交到 GitHub。本仓库 `.gitignore` 已默认忽略该文件。

### 4. 安装后端依赖

```powershell
cd F:\demo1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

首次使用 RAG 时会加载 `rag/models/bge-m3` 下的本地模型。如果没有模型文件，需要提前下载 BAAI/bge-m3 到该目录，或者根据自己的环境调整 `rag/embeddings.py` 中的 `MODEL_PATH`。

### 5. 安装前端依赖

```powershell
cd F:\demo1\frontend
npm install
```

### 6. 启动项目

需要同时启动三个进程。

终端 1，启动后端 API：

```powershell
cd F:\demo1
.\.venv\Scripts\Activate.ps1
python app.py
```

终端 2，启动知识库 Worker：

```powershell
cd F:\demo1
.\.venv\Scripts\Activate.ps1
python kb_worker.py
```

终端 3，启动前端：

```powershell
cd F:\demo1\frontend
npm run dev
```

访问地址：

| 地址                         | 说明                 |
| ---------------------------- | -------------------- |
| `http://localhost:3000`      | 前端页面             |
| `http://localhost:5000/docs` | FastAPI Swagger 文档 |
| `http://localhost:9001`      | MinIO 控制台         |

## 配置项说明

### 大模型配置

`config.py` 会读取项目根目录的 `key.txt`，格式为 `key: value`。

| 配置                | 说明                          |
| ------------------- | ----------------------------- |
| `base-url`          | OpenAI 兼容接口地址           |
| `model-name`        | 普通聊天和 RAG 使用的模型     |
| `api-key`           | 普通聊天和 RAG 使用的 API Key |
| `vision-model-name` | 可选，图片理解模型            |
| `vision-base-url`   | 可选，图片理解模型接口地址    |
| `vision-api-key`    | 可选，图片理解模型 API Key    |

### Redis 配置

`redis_client.py` 支持环境变量：

| 环境变量         | 默认值      |
| ---------------- | ----------- |
| `REDIS_HOST`     | `localhost` |
| `REDIS_PORT`     | `6379`      |
| `REDIS_DB`       | `0`         |
| `REDIS_PASSWORD` | 空          |

### MinIO 配置

`rag/minio_client.py` 支持环境变量：

| 环境变量           | 默认值           |
| ------------------ | ---------------- |
| `MINIO_ENDPOINT`   | `localhost:9000` |
| `MINIO_ACCESS_KEY` | `minioadmin`     |
| `MINIO_SECRET_KEY` | `minioadmin`     |
| `MINIO_BUCKET`     | `ros123`         |
| `MINIO_SECURE`     | `false`          |

### 知识库任务配置

| 环境变量                    | 默认值 | 说明                          |
| --------------------------- | ------ | ----------------------------- |
| `KB_MAX_FILE_SIZE_MB`       | `20`   | 单个知识库文件最大大小        |
| `KB_MAX_FILES_PER_BATCH`    | `10`   | 前端单批上传数量              |
| `KB_JOB_VISIBILITY_TIMEOUT` | `300`  | Worker 认领任务后的可见性超时 |
| `KB_JOB_MAX_ATTEMPTS`       | `3`    | 索引任务最大重试次数          |
| `KB_EMBEDDING_BATCH_SIZE`   | `16`   | 向量化批大小                  |

## 项目整体流程

### 用户登录流程

1. 前端调用 `/api/register` 创建账号，后端使用 `bcrypt` 保存密码哈希。
2. 前端调用 `/api/login` 登录，后端生成 72 小时有效的 JWT。
3. 前端把 token 存入 `localStorage`，之后 Axios 自动带上 `Authorization` 请求头。
4. 后端接口通过 `get_current_user` 校验 JWT，并从 token 中得到当前用户 ID。

### 普通对话流程

1. 用户在 `ChatView.vue` 输入问题，可选择上传图片、文档、选择知识库或开启联网搜索。
2. 前端调用 `/api/chat`，以流式方式接收后端 SSE 数据。
3. 后端校验用户、读取会话、整理历史消息和附件。
4. 如果选择了知识库，后端先调用 `hybrid_retrieve` 检索相关片段，并把检索上下文插入系统提示词。
5. 如果开启联网搜索，后端调用 DashScope 原生 generation API；否则调用 OpenAI 兼容模型接口。
6. 模型响应一边流式返回给前端，一边在结束后写入 `messages` 表。
7. 后端清理 Redis 中对应会话缓存，前端刷新历史消息和来源信息。

### 知识库导入流程

```text
创建知识库
  -> 上传文件或粘贴文本
  -> MySQL 写入 kb_documents 和 kb_jobs
  -> 文件上传到 MinIO
  -> Redis 写入待处理任务
  -> kb_worker.py 领取任务
  -> 解析文档
  -> 分块
  -> BGE-M3 生成向量
  -> 写入 ChromaDB 和 MySQL kb_chunks
  -> 更新任务状态为 ready
```

文本型资料会直接保存到 MySQL 的 `source_text` 字段。文件型资料会先保存到 MinIO，再把对象名和临时访问 URL 记录到 MySQL，Worker 处理时再从 MinIO 下载原文件。

## Redis 用法说明

本项目的 Redis 有四类用途。

### 1. 接口缓存

`redis_client.py` 封装了 `cache_get`、`cache_set`、`cache_delete`、`cache_delete_pattern`。

| Key                            | 过期时间 | 场景                              |
| ------------------------------ | -------- | --------------------------------- |
| `conv:list:{user_id}`          | 60 秒    | 缓存用户会话列表，减少 MySQL 查询 |
| `conv:msg:{user_id}:{conv_id}` | 120 秒   | 缓存某个会话的消息列表            |
| `kb:doc:{user_id}:{doc_id}`    | 300 秒   | 缓存单个知识库文档详情            |

会话新增、重命名、删除、消息写入后会删除对应缓存。后端启动时会执行 `cache_delete_pattern("conv:msg:*")`，避免旧消息缓存影响展示。

### 2. 知识库异步任务队列

`rag/job_queue.py` 使用 Redis 实现轻量任务队列。

| Key                  | 类型       | 作用                                         |
| -------------------- | ---------- | -------------------------------------------- |
| `kb:jobs:pending`    | List       | 等待 Worker 处理的 job_id 队列               |
| `kb:jobs:processing` | Sorted Set | 已被 Worker 认领的任务，score 是超时时间     |
| `kb:jobs:claims`     | Hash       | 保存 job_id 与 claim_token，防止错误确认任务 |

入队时调用 `enqueue(job_id)`：先移除重复 job_id，再 `LPUSH` 到 pending 队列。

Worker 认领时调用 `claim()`：通过 Lua 脚本原子执行 `RPOP pending`、`ZADD processing`、`HSET claims`，确保多 Worker 并发时一个任务只会被一个 Worker 领取。

任务成功后调用 `acknowledge()`：校验 claim_token，删除 processing 和 claims 中的记录。任务超时未确认时，`requeue_expired()` 会把它重新放回 pending 队列。

### 3. Worker 心跳和健康检查

`kb_worker.py` 每 10 秒写入：

```text
kb:worker:{worker_id}
```

该 Key 使用 `SETEX`，过期时间 30 秒。后端接口 `/api/knowledge-base/worker/health` 通过扫描 `kb:worker:*` 判断索引服务是否在线。Worker 处理任务期间也会刷新当前任务在 `kb:jobs:processing` 中的超时时间。

### 4. 索引版本通知

知识库索引写入或删除后会执行：

```text
INCR kb:index:version
```

后端读取 ChromaDB collection 时会对比本地版本和 Redis 中的远端版本。如果发现版本变化，会重建 Chroma 客户端缓存，保证 API 进程能看到 Worker 刚写入的新索引。

## MinIO 应用场景

MinIO 用来保存知识库上传的原始文件，主要解决三个问题：

1. 原文件持久化：上传 PDF、Word、PPT、Excel 等文件后，文件体不会直接塞进数据库，而是作为对象存入 MinIO。
2. 后台异步处理：API 只负责上传和创建任务，Worker 之后通过 `download_object_bytes()` 从 MinIO 下载文件并解析。
3. 重建和删除：用户点击重建索引时，可以重新下载原文件生成分块；用户删除文档时，会同步删除 MinIO 对象。

对象名格式：

```text
kb/{user_id}/{collection_id}/{uuid}.{ext}
```

上传后 `upload_file_bytes()` 会返回：

| 字段           | 用途                                                      |
| -------------- | --------------------------------------------------------- |
| `minio_object` | 对象名，保存到 `kb_documents.minio_object`                |
| `minio_url`    | 7 天有效的预签名访问链接，保存到 `kb_documents.minio_url` |

注意：聊天窗口中的临时附件目前保存到本地目录 `rag/data/uploads/chat/{user_id}`，不是 MinIO。MinIO 主要服务于知识库文件。

## RAG 知识库思路

RAG 的核心目标是：先从用户自己的资料里找证据，再让大模型基于证据回答。

### 建库阶段

1. 用户创建知识库，对应 MySQL 的 `kb_collections`。
2. 用户上传文件或粘贴文本，对应 MySQL 的 `kb_documents`。
3. 文件上传到 MinIO，文本直接写入 MySQL。
4. 系统创建 `kb_jobs` 任务，并把 job_id 放入 Redis 队列。
5. Worker 领取任务后解析文档。
6. `document_parser.py` 按文件类型提取文本，并保留定位信息，例如页码、幻灯片页、工作表、行号、标题。
7. `chunk_sections()` 按约 500 token 分块，80 token 重叠，避免上下文断裂。
8. `embeddings.py` 使用本地 `BAAI/bge-m3` 生成 1024 维归一化向量。
9. 向量写入 ChromaDB，文本块和定位信息写入 MySQL 的 `kb_chunks`。

### 检索阶段

1. 用户提问时，如果带了历史对话，`rewrite_query()` 会把当前问题改写成更适合检索的独立问题。
2. 向量检索：在 ChromaDB 中按语义相似度召回相关片段。
3. 关键词检索：用 `jieba` 分词后做 BM25，适合命中专有名词、编号、字段名等精确表达。
4. `reciprocal_rank_fusion()` 使用 RRF 融合两路结果，降低单一路径漏召回的风险。
5. 可选 LLM 重排：`rerank_candidates()` 让模型从候选片段中挑出更能支撑答案的内容。
6. `format_context()` 把最终片段整理进 Prompt，`build_sources()` 生成前端展示的来源列表。
7. `rag_generate_stream()` 或 `/api/chat` 中的模型调用基于来源回答，并返回引用信息。

### 为什么同时用 ChromaDB 和 MySQL

| 存储                 | 保存内容                         | 用途                            |
| -------------------- | -------------------------------- | ------------------------------- |
| ChromaDB             | chunk 向量、chunk 文本、metadata | 语义向量检索                    |
| MySQL `kb_chunks`    | chunk 文本、定位、文档关系       | BM25 检索、文档管理、可追溯来源 |
| MySQL `kb_documents` | 文档元数据、状态、MinIO 对象名   | 展示进度、重试、删除、重建索引  |
| MySQL `kb_jobs`      | 异步任务状态                     | 前端轮询索引进度                |

## 常用命令

构建前端生产包：

```powershell
cd F:\demo1\frontend
npm run build
```

停止基础设施：

```powershell
cd F:\demo1
docker compose down
```

查看 Redis 队列：

```powershell
docker exec -it ai-chat-redis redis-cli
LLEN kb:jobs:pending
ZRANGE kb:jobs:processing 0 -1 WITHSCORES
KEYS kb:worker:*
GET kb:index:version
```

## GitHub 上传注意事项

不要提交以下内容：

| 内容                     | 原因                                        |
| ------------------------ | ------------------------------------------- |
| `key.txt`                | 包含 API Key                                |
| `.venv/`、`__pycache__/` | 本地 Python 环境和缓存                      |
| `frontend/node_modules/` | 前端依赖体积大，应通过 `npm install` 生成   |
| `frontend/dist/`         | 构建产物，可由 CI 或本地重新生成            |
| `rag/data/`              | 本地上传文件、ChromaDB 数据、聊天附件       |
| `rag/models/`            | 本地大模型文件体积很大，不适合普通 Git 仓库 |
| `*.log`、`*.err.log`     | 运行日志                                    |
| 大体积视频文件           | 体积过大，建议放 Release 或网盘             |

首次上传 GitHub 可以参考：

```powershell
cd F:\demo1
git init
git add .
git status
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/your-name/your-repo.git
git push -u origin main
```

如果 `key.txt` 中的真实密钥曾经被提交或分享，请立即到对应平台作废旧密钥并重新生成。

## 常见问题

### 后端启动时报 MySQL 连接失败

确认 Docker 容器已启动，并且 MySQL 端口是 `3307`：

```powershell
docker compose ps
```

代码默认连接 `localhost:3307`，用户名 `root`，密码 `1234`，数据库 `ai_chat`。

### 知识库一直显示排队中

确认 Worker 已启动：

```powershell
python kb_worker.py
```

也可以在前端知识库页面查看 Worker 健康状态，或请求 `/api/knowledge-base/worker/health`。

### 上传知识库文件失败

检查三点：

1. MinIO 是否启动，控制台是否能打开 `http://localhost:9001`。
2. 文件格式是否在支持范围内：`.txt`、`.md`、`.json`、`.csv`、`.xml`、`.yaml`、`.yml`、`.sql`、`.py`、`.js`、`.ts`、`.html`、`.css`、`.pdf`、`.docx`、`.pptx`、`.xlsx`。
3. 单个文件是否超过 `KB_MAX_FILE_SIZE_MB`，默认 20MB。

### 聊天上传图片后模型不能理解图片

需要在 `key.txt` 中配置 `vision-model-name`、`vision-base-url`、`vision-api-key`。如果没有视觉模型配置，后端只能尝试 OCR 或把图片当作普通附件提示。

### RAG 回答没有来源

通常是知识库没有 ready 状态的文档，或检索没有召回片段。先确认文档索引完成，再检查问题是否和知识库内容相关。
