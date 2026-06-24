<template>
  <div class="kb-page">
    <header class="page-header">
      <div>
        <h2><i class="fa-solid fa-database"></i> 知识库</h2>
        <p>管理资料、查看索引进度，并在聊天中按库检索。</p>
      </div>
      <router-link to="/chat" class="btn secondary">
        <i class="fa-regular fa-comment-dots"></i> 返回对话
      </router-link>
    </header>

    <div class="worker-status" :class="{ healthy: workerHealthy }">
      <span class="status-dot"></span>
      {{ workerHealthy ? `索引服务在线（${workerCount}）` : '索引服务未运行，请启动 python kb_worker.py' }}
    </div>

    <div class="workspace">
      <aside class="collections-panel">
        <div class="panel-title">
          <span>知识库</span>
          <button class="icon-button" @click="showCollectionForm = true" title="新建知识库">
            <i class="fa-solid fa-plus"></i>
          </button>
        </div>

        <button
          v-for="collection in collections"
          :key="collection.id"
          :class="['collection-item', { active: collection.id === activeCollectionId }]"
          @click="selectCollection(collection.id)"
        >
          <i class="fa-regular fa-folder"></i>
          <span class="collection-name">{{ collection.name }}</span>
          <span class="collection-count">{{ collection.document_count || 0 }}</span>
        </button>

        <div v-if="!collections.length && !loadingCollections" class="empty-small">
          暂无知识库
        </div>
      </aside>

      <main class="documents-panel">
        <div v-if="activeCollection" class="documents-header">
          <div>
            <h3>{{ activeCollection.name }}</h3>
            <p>{{ activeCollection.description || '暂无描述' }}</p>
          </div>
          <div class="header-actions">
            <button class="btn secondary" @click="showAddPanel = !showAddPanel">
              <i class="fa-solid fa-plus"></i> 添加资料
            </button>
            <button
              v-if="!activeCollection.is_default"
              class="btn danger"
              @click="removeCollection"
            >
              删除知识库
            </button>
          </div>
        </div>

        <section v-if="showAddPanel && activeCollection" class="add-panel">
          <div class="tabs">
            <button :class="{ active: addMode === 'file' }" @click="addMode = 'file'">上传文件</button>
            <button :class="{ active: addMode === 'text' }" @click="addMode = 'text'">粘贴文本</button>
          </div>

          <div v-if="addMode === 'file'">
            <label class="file-picker">
              <input
                type="file"
                multiple
                accept=".txt,.md,.pdf,.docx,.pptx,.xlsx,.json,.py,.js,.ts,.html,.css,.csv,.xml,.yaml,.yml,.sql"
                @change="onFilesSelected"
              />
              <i class="fa-solid fa-cloud-arrow-up"></i>
              <span>选择文件（一次最多 10 个，单个不超过 20MB）</span>
            </label>
            <div v-if="uploadItems.length" class="upload-list">
              <div v-for="item in uploadItems" :key="item.id" class="upload-item">
                <div class="upload-row">
                  <span>{{ item.name }}</span>
                  <span>{{ item.statusText }}</span>
                </div>
                <div class="progress-track">
                  <div class="progress-bar" :style="{ width: `${item.progress}%` }"></div>
                </div>
              </div>
            </div>
          </div>

          <div v-else class="text-form">
            <input v-model="textTitle" placeholder="资料标题" />
            <textarea v-model="textContent" rows="7" placeholder="粘贴需要进入知识库的内容"></textarea>
            <button
              class="btn primary"
              :disabled="savingText || !textTitle.trim() || !textContent.trim()"
              @click="saveText"
            >
              {{ savingText ? '正在创建任务...' : '保存并建立索引' }}
            </button>
          </div>
        </section>

        <div v-if="loadingDocuments" class="loading">加载资料中...</div>
        <div v-else-if="!documents.length" class="empty-state">
          <i class="fa-regular fa-folder-open"></i>
          <h3>这个知识库还是空的</h3>
          <p>上传文件或粘贴文本后，Worker 会在后台建立索引。</p>
        </div>
        <div v-else class="document-list">
          <article v-for="document in documents" :key="document.id" class="document-card">
            <div class="document-icon"><i :class="documentIcon(document.doc_type)"></i></div>
            <div class="document-main">
              <div class="document-title">{{ document.title }}</div>
              <div class="document-meta">
                {{ document.doc_type.toUpperCase() }} · {{ document.chunk_count || 0 }} 个片段 ·
                {{ formatDate(document.updated_at) }}
              </div>
              <div v-if="isPending(document)" class="job-progress">
                <div class="progress-track">
                  <div class="progress-bar" :style="{ width: `${document.progress || 0}%` }"></div>
                </div>
                <span>{{ stageLabel(document.stage) }} {{ document.progress || 0 }}%</span>
              </div>
              <div v-if="document.status === 'failed'" class="document-error">
                {{ document.job_error || document.error_message || '索引失败' }}
              </div>
            </div>
            <div class="document-status" :class="document.status">
              {{ statusLabel(document.status) }}
            </div>
            <div class="document-actions">
              <button
                v-if="document.status === 'failed' && document.job_id"
                @click="retryJob(document.job_id)"
                title="重试"
              ><i class="fa-solid fa-rotate-right"></i></button>
              <button
                v-if="document.status === 'ready'"
                @click="reindexDocument(document)"
                title="重建索引"
              ><i class="fa-solid fa-arrows-rotate"></i></button>
              <button @click="removeDocument(document)" title="删除">
                <i class="fa-regular fa-trash-can"></i>
              </button>
            </div>
          </article>
        </div>
      </main>
    </div>

    <div v-if="showCollectionForm" class="modal-overlay" @click.self="showCollectionForm = false">
      <form class="modal" @submit.prevent="saveCollection">
        <h3>新建知识库</h3>
        <input v-model="collectionName" placeholder="名称，例如：产品资料" maxlength="120" />
        <textarea v-model="collectionDescription" placeholder="用途说明（可选）" maxlength="500"></textarea>
        <div class="modal-actions">
          <button type="button" class="btn secondary" @click="showCollectionForm = false">取消</button>
          <button class="btn primary" :disabled="!collectionName.trim() || savingCollection">
            创建
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  addKnowledgeBaseTextAPI,
  createKnowledgeBaseAPI,
  deleteKnowledgeBaseAPI,
  deleteKnowledgeBaseDocumentAPI,
  getKnowledgeBaseWorkerHealthAPI,
  listKnowledgeBaseDocumentsAPI,
  listKnowledgeBasesAPI,
  reindexKnowledgeBaseDocumentAPI,
  retryKnowledgeBaseJobAPI,
  uploadKnowledgeBaseDocumentAPI,
} from '../api'

const collections = ref([])
const documents = ref([])
const activeCollectionId = ref(null)
const loadingCollections = ref(true)
const loadingDocuments = ref(false)
const showCollectionForm = ref(false)
const showAddPanel = ref(false)
const collectionName = ref('')
const collectionDescription = ref('')
const savingCollection = ref(false)
const addMode = ref('file')
const textTitle = ref('')
const textContent = ref('')
const savingText = ref(false)
const uploadItems = ref([])
const workerHealthy = ref(false)
const workerCount = ref(0)
let pollTimer = null

const activeCollection = computed(() =>
  collections.value.find(item => item.id === activeCollectionId.value) || null
)

function createId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
}

function documentIcon(type) {
  const icons = {
    pdf: 'fa-regular fa-file-pdf',
    docx: 'fa-regular fa-file-word',
    pptx: 'fa-regular fa-file-powerpoint',
    xlsx: 'fa-regular fa-file-excel',
    py: 'fa-brands fa-python',
    js: 'fa-brands fa-js',
    text: 'fa-regular fa-file-lines',
  }
  return icons[type] || 'fa-regular fa-file'
}

function isPending(document) {
  return ['queued', 'processing'].includes(document.status)
}

function statusLabel(status) {
  return {
    queued: '排队中',
    processing: '索引中',
    ready: '可使用',
    failed: '失败',
  }[status] || status
}

function stageLabel(stage) {
  return {
    queued: '等待处理',
    claiming: '领取任务',
    parsing: '解析文档',
    chunking: '切分内容',
    embedding: '生成向量',
    persisting: '保存索引',
  }[stage] || '处理中'
}

function formatDate(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : ''
}

async function fetchCollections() {
  try {
    const { data } = await listKnowledgeBasesAPI()
    collections.value = data
    if (!activeCollectionId.value || !data.some(item => item.id === activeCollectionId.value)) {
      activeCollectionId.value = data[0]?.id || null
    }
  } finally {
    loadingCollections.value = false
  }
}

async function fetchDocuments(silent = false) {
  if (!activeCollectionId.value) {
    documents.value = []
    return
  }
  if (!silent) loadingDocuments.value = true
  try {
    const { data } = await listKnowledgeBaseDocumentsAPI(activeCollectionId.value)
    documents.value = data
  } finally {
    loadingDocuments.value = false
  }
}

async function fetchWorkerHealth() {
  try {
    const { data } = await getKnowledgeBaseWorkerHealthAPI()
    workerHealthy.value = data.healthy
    workerCount.value = data.workers.length
  } catch {
    workerHealthy.value = false
  }
}

async function selectCollection(id) {
  activeCollectionId.value = id
  showAddPanel.value = false
  uploadItems.value = []
  await fetchDocuments()
}

async function saveCollection() {
  if (!collectionName.value.trim() || savingCollection.value) return
  savingCollection.value = true
  try {
    const { data } = await createKnowledgeBaseAPI(
      collectionName.value.trim(),
      collectionDescription.value.trim(),
    )
    collectionName.value = ''
    collectionDescription.value = ''
    showCollectionForm.value = false
    await fetchCollections()
    await selectCollection(data.id)
  } catch (error) {
    alert(error.response?.data?.detail || '创建知识库失败')
  } finally {
    savingCollection.value = false
  }
}

async function removeCollection() {
  if (!activeCollection.value || !confirm(`确定删除“${activeCollection.value.name}”及其中所有资料？`)) return
  try {
    await deleteKnowledgeBaseAPI(activeCollection.value.id)
    activeCollectionId.value = null
    await fetchCollections()
    await fetchDocuments()
  } catch (error) {
    alert(error.response?.data?.detail || '删除失败')
  }
}

async function uploadOne(file, duplicateMode = 'skip') {
  const item = {
    id: createId(),
    name: file.name,
    progress: 0,
    statusText: '上传中',
  }
  uploadItems.value.push(item)
  try {
    await uploadKnowledgeBaseDocumentAPI(
      activeCollectionId.value,
      file.name,
      file,
      duplicateMode,
      event => {
        if (event.total) item.progress = Math.round(event.loaded / event.total * 100)
      },
    )
    item.progress = 100
    item.statusText = '已进入索引队列'
  } catch (error) {
    if (error.response?.status === 409 && duplicateMode === 'skip') {
      const createVersion = confirm(`${file.name} 内容已存在，是否作为新版本导入？`)
      if (createVersion) {
        uploadItems.value = uploadItems.value.filter(value => value.id !== item.id)
        return uploadOne(file, 'version')
      }
    }
    item.statusText = error.response?.data?.detail || '上传失败'
  }
}

async function onFilesSelected(event) {
  const files = Array.from(event.target.files || []).slice(0, 10)
  event.target.value = ''
  await Promise.all(files.map(file => uploadOne(file)))
  await fetchDocuments(true)
  await fetchCollections()
}

async function saveText(duplicateMode = 'skip') {
  if (savingText.value) return
  savingText.value = true
  try {
    await addKnowledgeBaseTextAPI(
      activeCollectionId.value,
      textTitle.value.trim(),
      textContent.value.trim(),
      duplicateMode,
    )
    textTitle.value = ''
    textContent.value = ''
    await fetchDocuments(true)
    await fetchCollections()
  } catch (error) {
    if (error.response?.status === 409 && duplicateMode === 'skip' && confirm('相同内容已存在，是否创建新版本？')) {
      savingText.value = false
      return await saveText('version')
    }
    alert(error.response?.data?.detail || '保存失败')
  } finally {
    savingText.value = false
  }
}

async function retryJob(jobId) {
  try {
    await retryKnowledgeBaseJobAPI(jobId)
    await fetchDocuments(true)
  } catch (error) {
    alert(error.response?.data?.detail || '重试失败')
  }
}

async function reindexDocument(document) {
  try {
    await reindexKnowledgeBaseDocumentAPI(activeCollectionId.value, document.id)
    await fetchDocuments(true)
  } catch (error) {
    alert(error.response?.data?.detail || '无法重建索引')
  }
}

async function removeDocument(document) {
  if (!confirm(`确定删除“${document.title}”？`)) return
  try {
    await deleteKnowledgeBaseDocumentAPI(activeCollectionId.value, document.id)
    await fetchDocuments(true)
    await fetchCollections()
  } catch (error) {
    alert(error.response?.data?.detail || '删除失败')
  }
}

onMounted(async () => {
  await Promise.all([fetchCollections(), fetchWorkerHealth()])
  await fetchDocuments()
  pollTimer = setInterval(async () => {
    await fetchWorkerHealth()
    if (documents.value.some(isPending)) await fetchDocuments(true)
  }, 1500)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.kb-page { max-width: 1180px; margin: 0 auto; padding: 28px 24px; min-height: 100vh; color: #eef2ff; }
.page-header,.documents-header,.panel-title,.upload-row { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.page-header { margin-bottom:14px; }
.page-header h2 { font-size:24px; margin-bottom:6px; }
.page-header h2 i { color:#818cf8; margin-right:8px; }
.page-header p,.documents-header p { color:rgba(255,255,255,.4); font-size:13px; }
.worker-status { padding:9px 12px; border-radius:10px; background:rgba(248,113,113,.1); color:#fca5a5; font-size:12px; margin-bottom:16px; }
.worker-status.healthy { background:rgba(74,222,128,.1); color:#86efac; }
.status-dot { display:inline-block; width:7px; height:7px; border-radius:50%; background:currentColor; margin-right:7px; }
.workspace { display:grid; grid-template-columns:260px 1fr; gap:16px; min-height:650px; }
.collections-panel,.documents-panel { background:rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.08); border-radius:16px; }
.collections-panel { padding:12px; }
.documents-panel { padding:20px; min-width:0; }
.panel-title { padding:6px 8px 12px; font-weight:600; }
.icon-button,.document-actions button { border:0; background:rgba(255,255,255,.07); color:rgba(255,255,255,.65); border-radius:8px; cursor:pointer; width:30px; height:30px; }
.collection-item { width:100%; display:flex; align-items:center; gap:9px; border:0; background:transparent; color:rgba(255,255,255,.55); padding:11px; border-radius:10px; cursor:pointer; text-align:left; }
.collection-item:hover,.collection-item.active { background:rgba(99,102,241,.16); color:#fff; }
.collection-name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.collection-count { font-size:11px; opacity:.5; }
.header-actions,.modal-actions { display:flex; gap:8px; }
.btn { border:0; border-radius:9px; padding:9px 14px; color:#fff; cursor:pointer; text-decoration:none; font:inherit; font-size:13px; }
.btn.primary { background:linear-gradient(135deg,#667eea,#764ba2); }
.btn.secondary { background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.09); }
.btn.danger { background:rgba(239,68,68,.14); color:#fca5a5; }
.btn:disabled { opacity:.4; cursor:not-allowed; }
.add-panel { margin:18px 0; padding:16px; background:rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.07); border-radius:13px; }
.tabs { display:flex; gap:4px; margin-bottom:14px; }
.tabs button { border:0; background:transparent; color:rgba(255,255,255,.45); padding:8px 13px; border-radius:8px; cursor:pointer; }
.tabs button.active { background:rgba(99,102,241,.18); color:#c7d2fe; }
.file-picker { display:flex; flex-direction:column; align-items:center; gap:8px; padding:26px; border:1px dashed rgba(255,255,255,.18); border-radius:12px; color:rgba(255,255,255,.45); cursor:pointer; }
.file-picker input { display:none; }
.file-picker i { font-size:27px; color:#818cf8; }
.upload-list { margin-top:12px; display:grid; gap:9px; }
.upload-row { font-size:12px; color:rgba(255,255,255,.6); margin-bottom:5px; }
.progress-track { height:5px; background:rgba(255,255,255,.08); border-radius:4px; overflow:hidden; }
.progress-bar { height:100%; background:linear-gradient(90deg,#667eea,#8b5cf6); transition:width .2s; }
.text-form { display:grid; gap:10px; }
.text-form input,.text-form textarea,.modal input,.modal textarea { width:100%; padding:11px 12px; border-radius:9px; border:1px solid rgba(255,255,255,.1); background:rgba(255,255,255,.06); color:#fff; font:inherit; outline:none; }
.document-list { display:grid; gap:9px; margin-top:18px; }
.document-card { display:flex; align-items:center; gap:13px; padding:14px; border-radius:12px; background:rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.06); }
.document-icon { width:40px; height:40px; border-radius:10px; background:rgba(99,102,241,.13); color:#818cf8; display:grid; place-items:center; flex:none; }
.document-main { flex:1; min-width:0; }
.document-title { font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.document-meta { font-size:11px; color:rgba(255,255,255,.3); margin-top:4px; }
.job-progress { display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center; font-size:11px; color:#a5b4fc; margin-top:7px; }
.document-error { color:#fca5a5; font-size:11px; margin-top:6px; }
.document-status { padding:4px 8px; border-radius:12px; font-size:11px; background:rgba(255,255,255,.07); }
.document-status.ready { color:#86efac; background:rgba(74,222,128,.1); }
.document-status.failed { color:#fca5a5; background:rgba(248,113,113,.1); }
.document-status.processing,.document-status.queued { color:#a5b4fc; background:rgba(99,102,241,.12); }
.document-actions { display:flex; gap:5px; }
.document-actions button:hover { color:#fff; background:rgba(99,102,241,.2); }
.empty-state,.loading,.empty-small { text-align:center; color:rgba(255,255,255,.3); padding:70px 20px; }
.empty-state i { font-size:40px; margin-bottom:12px; }
.empty-state h3 { color:rgba(255,255,255,.55); margin-bottom:7px; }
.empty-small { padding:24px 8px; font-size:12px; }
.modal-overlay { position:fixed; inset:0; background:rgba(0,0,0,.65); display:grid; place-items:center; z-index:200; }
.modal { width:min(440px,90vw); display:grid; gap:12px; padding:22px; border-radius:15px; background:#1b1b32; border:1px solid rgba(255,255,255,.1); }
.modal-actions { justify-content:flex-end; }
@media (max-width:800px) {
  .workspace { grid-template-columns:1fr; }
  .collections-panel { max-height:240px; overflow:auto; }
  .documents-header { align-items:flex-start; flex-direction:column; }
}
</style>
