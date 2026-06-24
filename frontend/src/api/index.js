import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

export function loginAPI(username, password) {
  return api.post('/login', { username, password })
}

export function registerAPI(username, email, password) {
  return api.post('/register', { username, email, password })
}

export function getMeAPI() {
  return api.get('/user/me')
}

export function listConversationsAPI() {
  return api.get('/conversations')
}

export function createConversationAPI(title = '新对话') {
  return api.post('/conversations', { title })
}

export function renameConversationAPI(id, title) {
  return api.put(`/conversations/${id}`, { title })
}

export function deleteConversationAPI(id) {
  return api.delete(`/conversations/${id}`)
}

export function getMessagesAPI(convId) {
  return api.get(`/conversations/${convId}/messages`)
}

export function listKBAPI() {
  return api.get('/knowledge-base')
}

export function listKnowledgeBasesAPI() {
  return api.get('/knowledge-bases')
}

export function createKnowledgeBaseAPI(name, description = '') {
  return api.post('/knowledge-bases', { name, description })
}

export function updateKnowledgeBaseAPI(id, name, description = '') {
  return api.put(`/knowledge-bases/${id}`, { name, description })
}

export function deleteKnowledgeBaseAPI(id) {
  return api.delete(`/knowledge-bases/${id}`)
}

export function listKnowledgeBaseDocumentsAPI(collectionId) {
  return api.get(`/knowledge-bases/${collectionId}/documents`)
}

export function addKnowledgeBaseTextAPI(collectionId, title, content, duplicate_mode = 'skip') {
  return api.post(`/knowledge-bases/${collectionId}/documents/text`, {
    title,
    content,
    doc_type: 'text',
    duplicate_mode,
  })
}

export function uploadKnowledgeBaseDocumentAPI(
  collectionId,
  title,
  file,
  duplicate_mode = 'skip',
  onUploadProgress = undefined,
) {
  const form = new FormData()
  form.append('file', file)
  form.append('title', title)
  form.append('duplicate_mode', duplicate_mode)
  return api.post(`/knowledge-bases/${collectionId}/documents/upload`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress,
  })
}

export function deleteKnowledgeBaseDocumentAPI(collectionId, documentId) {
  return api.delete(`/knowledge-bases/${collectionId}/documents/${documentId}`)
}

export function reindexKnowledgeBaseDocumentAPI(collectionId, documentId) {
  return api.post(`/knowledge-bases/${collectionId}/documents/${documentId}/reindex`)
}

export function getKnowledgeBaseJobAPI(jobId) {
  return api.get(`/knowledge-base/jobs/${jobId}`)
}

export function retryKnowledgeBaseJobAPI(jobId) {
  return api.post(`/knowledge-base/jobs/${jobId}/retry`)
}

export function getKnowledgeBaseWorkerHealthAPI() {
  return api.get('/knowledge-base/worker/health')
}

export function addKBAPI(title, content, doc_type = 'text') {
  return api.post('/knowledge-base', { title, content, doc_type })
}

export function uploadKBAPI(title, file) {
  const form = new FormData()
  form.append('file', file)
  form.append('title', title)
  return api.post('/knowledge-base/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function deleteKBAPI(docId) {
  return api.delete(`/knowledge-base/${docId}`)
}

export function ragQueryAPI(query, top_k = 5) {
  return api.post('/rag/query', { query, top_k, stream: false })
}

export default api
