<template>
  <div class="chat-layout">
    <!-- Sidebar -->
    <aside :class="['sidebar', { open: sidebarOpen }]">
      <div class="sidebar-header">
        <button class="btn-new-chat" @click="newConversation">
          <i class="fa-regular fa-pen-to-square"></i>
          新对话
        </button>
      </div>
      <div class="sidebar-list">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          :class="['conv-item', { active: conv.id === currentConvId }]"
          @click="switchConversation(conv)"
        >
          <i class="fa-regular fa-message"></i>
          <span
            v-if="editingConvId !== conv.id"
            class="conv-title"
            :title="conv.title"
          >{{ conv.title }}</span>
          <input
            v-else
            v-focus
            class="conv-title-input"
            v-model="editingTitle"
            @keydown.enter.stop="saveRename(conv.id)"
            @keydown.escape.stop="cancelRename"
            @blur="saveRename(conv.id)"
            @click.stop
          />
          <button class="btn-more" @click.stop="toggleMenu(conv.id)" title="更多">
            <i class="fa-solid fa-ellipsis"></i>
          </button>
          <div v-if="menuOpenConvId === conv.id" class="conv-menu" @click.stop>
            <button class="menu-item" @click="startRename(conv)">
              <i class="fa-regular fa-pen-to-square"></i> 重命名
            </button>
            <button class="menu-item menu-danger" @click="deleteConversation(conv.id)">
              <i class="fa-regular fa-trash-can"></i> 删除
            </button>
          </div>
        </div>
        <div v-if="!conversations.length" class="sidebar-empty">
          <i class="fa-regular fa-comment-dots"></i>
          <p>暂无历史会话</p>
        </div>
      </div>
      <div class="sidebar-footer">
        <div class="sidebar-links">
          <router-link to="/knowledge-base" class="sidebar-link">
            <i class="fa-solid fa-database"></i> 知识库
          </router-link>
        </div>
        <div class="sidebar-user">
          <div class="user-info">
            <i class="fa-regular fa-circle-user"></i>
            <span>{{ username }}</span>
          </div>
          <button class="btn-logout-side" @click="handleLogout" title="退出登录">
            <i class="fa-solid fa-right-from-bracket"></i>
          </button>
        </div>
      </div>
    </aside>

    <!-- Mobile overlay -->
    <div v-if="sidebarOpen" class="sidebar-overlay" @click="sidebarOpen = false"></div>

    <!-- Main chat area -->
    <div class="main-chat">
      <!-- Mobile toggle -->
      <div class="mobile-topbar">
        <button class="btn-menu" @click="sidebarOpen = true">
          <i class="fa-solid fa-bars"></i>
        </button>
        <span class="mobile-title">{{ currentTitle }}</span>
        <button class="btn-logout-mobile" @click="handleLogout">
          <i class="fa-solid fa-right-from-bracket"></i>
        </button>
      </div>

      <!-- Messages -->
      <div class="messages-area" ref="messagesRef">
        <div v-if="!messages.length" class="empty-state">
          <i class="fa-regular fa-comment-dots"></i>
          <h2>有什么可以帮你的？</h2>
          <p>输入问题开始对话，或上传文件/图片进行分析</p>
          <div class="welcome-suggestions">
            <span class="chip" @click="sendSuggestion('用Python写一个快速排序算法')">排序算法</span>
            <span class="chip" @click="sendSuggestion('解释一下什么是机器学习')">机器学习</span>
            <span class="chip" @click="sendSuggestion('写一首关于秋天的诗')">写一首诗</span>
            <span class="chip" @click="sendSuggestion('如何提高代码质量？')">代码质量</span>
          </div>
        </div>

        <div v-for="(msg, idx) in messages" :key="idx" :class="['message', msg.role === 'assistant' ? 'ai' : msg.role]">
          <div class="msg-avatar">
            <i :class="msg.role === 'assistant' || msg.role === 'ai' ? 'fa-solid fa-robot' : 'fa-solid fa-user'"></i>
          </div>
          <div class="bubble">
            <div v-if="msg.attachments && msg.attachments.length" class="msg-attachments">
              <div v-for="(att, ai) in msg.attachments" :key="ai" class="msg-attach-item">
                <i :class="att.type === 'image' ? 'fa-regular fa-image' : 'fa-regular fa-file'"></i>
                <span>{{ att.name }}</span>
              </div>
            </div>
            <div class="content" v-html="renderMarkdown(msg.content)"></div>
            <div v-if="msg.sources && msg.sources.length" class="message-sources">
              <div class="sources-title">回答依据</div>
              <details v-for="source in msg.sources" :key="source.chunk_id" class="source-card">
                <summary>
                  <span>[{{ source.index }}] {{ source.title }}</span>
                  <small>{{ formatSourceLocation(source.locator) }}</small>
                </summary>
                <p>{{ source.snippet }}</p>
              </details>
            </div>
            <div class="timestamp">{{ msg.time || '' }}</div>
          </div>
        </div>

        <div v-if="isStreaming" class="typing-indicator">
          <div class="msg-avatar"><i class="fa-solid fa-robot"></i></div>
          <div class="typing-dots"><span></span><span></span><span></span></div>
        </div>
      </div>

      <div v-if="activeKnowledgeBaseIds.length" class="active-kb-bar">
        <i class="fa-solid fa-database"></i>
        <span>本会话检索：</span>
        <span v-for="collection in activeKnowledgeBases" :key="collection.id" class="active-kb-chip">
          {{ collection.name }}
        </span>
        <button @click="clearKnowledgeBases" title="清除知识库范围">&times;</button>
      </div>

      <!-- Attachments preview - square cards with dark-to-light progress -->
      <div v-if="attachments.length" class="attachments-bar">
        <div v-for="att in attachments" :key="att.localId" class="attach-card" :class="att.status">
          <!-- Image preview -->
          <div v-if="att.type === 'image' && att.preview" class="attach-card-img" :style="{ backgroundImage: 'url(' + att.preview + ')' }"></div>
          <!-- File icon -->
          <div v-else class="attach-card-icon">
            <i :class="att.type === 'image' ? 'fa-regular fa-image' : att.type === 'kb' ? 'fa-solid fa-database' : 'fa-regular fa-file-lines'"></i>
            <span class="attach-card-ext">{{ att.ext || '' }}</span>
          </div>
          <!-- Overlay - from dark to bright during upload -->
          <div class="attach-card-overlay" :style="{ opacity: att.status === 'uploading' ? (1 - att.progress / 100) : 0 }"></div>
          <!-- Progress bar at bottom -->
          <div v-if="att.status === 'uploading'" class="attach-card-progress">
            <div class="attach-card-progress-bar" :style="{ width: att.progress + '%' }"></div>
          </div>
          <div v-if="att.status === 'uploading'" class="attach-card-percent">
            {{ att.progress < 100 ? `${att.progress}%` : '处理中' }}
          </div>
          <!-- Status icon -->
          <div v-if="att.status === 'completed'" class="attach-card-check"><i class="fa-solid fa-circle-check"></i></div>
          <div v-else-if="att.status === 'error'" class="attach-card-error" :title="att.errorMsg"><i class="fa-solid fa-circle-exclamation"></i></div>
          <!-- Remove button -->
          <button class="attach-card-remove" @click="removeAttachment(att.localId)" v-if="att.status !== 'uploading'">&times;</button>
          <!-- File name -->
          <div class="attach-card-name">{{ att.name }}</div>
        </div>
      </div>

      <!-- Input area -->
      <div class="input-area">
        <div class="input-wrapper">
          <!-- Attach button -->
          <div class="attach-control" ref="attachMenuRef">
            <button class="btn-attach" type="button" @click.stop="toggleAttachMenu" title="添加附件">
              <i class="fa-solid fa-plus"></i>
            </button>
            <div v-if="showAttachMenu" class="attach-menu" @click.stop @mousedown.stop>
              <button class="attach-menu-item" type="button" @click.stop="triggerImageInput">
                <i class="fa-regular fa-image"></i> 添加图片
              </button>
              <button class="attach-menu-item" type="button" @click.stop="triggerDocInput">
                <i class="fa-regular fa-file"></i> 添加文件
              </button>
              <button class="attach-menu-item" type="button" @click.stop="doOpenKB">
                <i class="fa-solid fa-database"></i> 知识库
              </button>
              <div class="attach-menu-divider"></div>
              <button class="attach-menu-item attach-menu-toggle" type="button" @click.stop="toggleWebSearch">
                <i class="fa-solid fa-globe"></i> 联网搜索
                <span class="toggle-switch" :class="{ on: webSearch }"><span class="toggle-knob"></span></span>
              </button>
            </div>
          </div>
          <!-- Hidden file inputs (always in DOM) -->
          <input type="file" id="file-image-input" accept="image/*" multiple @change="onImagePick($event)" class="hidden-input" ref="imageInput" />
          <input type="file" id="file-doc-input" accept=".txt,.md,.pdf,.docx,.pptx,.xlsx,.json,.py,.js,.ts,.html,.css,.csv,.xml,.yaml,.yml,.sql" multiple @change="onDocPick($event)" class="hidden-input" ref="docInput" />
          <!-- Web search indicator -->
          <div v-if="webSearch" class="websearch-chip" @click="toggleWebSearch" title="点击关闭联网搜索">
            <i class="fa-solid fa-globe"></i>
            <span>联网搜索</span>
            <i class="fa-solid fa-xmark"></i>
          </div>
          <!-- Textarea -->
          <textarea
            v-model="inputText"
            rows="1"
            placeholder="有什么可以帮你的？可以添加图片或文件..."
            @input="autoResize"
            @keydown="handleKeyDown"
            ref="inputRef"
          ></textarea>
          <button
            class="btn-send"
            @click="sendMessage"
            :disabled="isStreaming || hasPendingUploads || hasUploadErrors || (!inputText.trim() && !readyAttachments.length)"
            :title="sendButtonTitle"
          >
            <i class="fa-solid fa-arrow-up"></i>
          </button>
        </div>
      </div>
    </div>

    <!-- KB Selector Modal -->
    <div v-if="showKBModal" class="modal-overlay" @click.self="showKBModal = false">
      <div class="modal-panel">
        <div class="modal-header">
          <h3>选择本会话使用的知识库</h3>
          <button class="modal-close" @click="showKBModal = false">&times;</button>
        </div>
        <div class="modal-search">
          <input v-model="kbSearch" placeholder="搜索知识库文件..." class="search-input" />
        </div>
        <div class="modal-list">
          <div
            v-for="collection in filteredKB"
            :key="collection.id"
            class="kb-item"
            :class="{ selected: selectedKBIds.includes(collection.id) }"
            @click="toggleKBSelection(collection.id)"
          >
            <i class="fa-regular fa-folder"></i>
            <div class="kb-item-info">
              <span class="kb-item-title">{{ collection.name }}</span>
              <span class="kb-item-meta">
                {{ collection.document_count || 0 }} 份资料 · {{ collection.chunk_count || 0 }} 个片段
              </span>
            </div>
            <i v-if="selectedKBIds.includes(collection.id)" class="fa-solid fa-check check-icon"></i>
          </div>
          <div v-if="!filteredKB.length" class="modal-empty">暂无知识库文件</div>
        </div>
        <div class="modal-footer">
          <button class="modal-btn modal-btn-cancel" @click="showKBModal = false">取消</button>
          <button class="modal-btn modal-btn-confirm" @click="confirmKBSelect">应用选择</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import {
  listConversationsAPI,
  createConversationAPI,
  renameConversationAPI,
  deleteConversationAPI,
  getMessagesAPI,
  listKnowledgeBasesAPI,
} from '../api'
import { marked } from 'marked'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import python from 'highlight.js/lib/languages/python'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import 'highlight.js/styles/atom-one-dark.css'

hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('css', css)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('json', json)

marked.setOptions({
  breaks: true,
  gfm: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try { return hljs.highlight(code, { language: lang }).value } catch (e) {}
    }
    return hljs.highlightAuto(code).value
  },
})

const auth = useAuthStore()
const router = useRouter()

const inputText = ref('')
const isStreaming = ref(false)
const messages = ref([])
const conversations = ref([])
const currentConvId = ref(null)
const messagesRef = ref(null)
const inputRef = ref(null)
const sidebarOpen = ref(false)
const editingConvId = ref(null)
const editingTitle = ref('')
const menuOpenConvId = ref(null)

// Attachment state
const attachments = ref([])
const showAttachMenu = ref(false)
const webSearch = ref(false)
const attachMenuRef = ref(null)
const imageInput = ref(null)
const docInput = ref(null)

// KB selector state
const showKBModal = ref(false)
const kbList = ref([])
const kbSearch = ref('')
const selectedKBIds = ref([])
const activeKnowledgeBaseIds = ref([])

const vFocus = {
  mounted: (el) => el.focus(),
}

const username = computed(() => auth.user?.username || '')
const currentTitle = computed(() => {
  if (!currentConvId.value) return '新对话'
  const c = conversations.value.find(u => u.id === currentConvId.value)
  return c?.title || '新对话'
})

const filteredKB = computed(() => {
  const q = kbSearch.value.toLowerCase().trim()
  if (!q) return kbList.value
  return kbList.value.filter(d => d.name.toLowerCase().includes(q))
})
const activeKnowledgeBases = computed(() =>
  kbList.value.filter(item => activeKnowledgeBaseIds.value.includes(item.id))
)

const readyAttachments = computed(() => attachments.value.filter(a => a.status === 'completed'))
const hasPendingUploads = computed(() => attachments.value.some(a => a.status === 'uploading'))
const hasUploadErrors = computed(() => attachments.value.some(a => a.status === 'error'))
const sendButtonTitle = computed(() => {
  if (hasPendingUploads.value) return '请等待附件上传完成'
  if (hasUploadErrors.value) return '请移除上传失败的附件'
  return '发送'
})

function createLocalId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
}

function clearAttachments() {
  attachments.value.forEach((attachment) => {
    if (attachment.preview) URL.revokeObjectURL(attachment.preview)
  })
  attachments.value = []
}

function formatTime() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function formatSourceLocation(locator = {}) {
  if (locator.page) return `第 ${locator.page} 页`
  if (locator.slide) return `第 ${locator.slide} 张幻灯片`
  if (locator.sheet) {
    const rows = locator.row_start ? ` 第 ${locator.row_start}-${locator.row_end || locator.row_start} 行` : ''
    return `${locator.sheet}${rows}`
  }
  return locator.section || ''
}

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + 'B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + 'KB'
  return (bytes / 1048576).toFixed(1) + 'MB'
}

function renderMarkdown(content) {
  return marked.parse(content)
}

function autoResize(e) {
  const el = e.target
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 100) + 'px'
}

function handleKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

async function fetchConversations() {
  try {
    const { data } = await listConversationsAPI()
    conversations.value = data
  } catch (e) {}
}

async function newConversation() {
  sidebarOpen.value = false
  currentConvId.value = null
  messages.value = []
  inputText.value = ''
  activeKnowledgeBaseIds.value = []
  clearAttachments()
  if (inputRef.value) inputRef.value.focus()
}

async function switchConversation(conv) {
  sidebarOpen.value = false
  clearAttachments()
  currentConvId.value = conv.id
  activeKnowledgeBaseIds.value = conv.knowledge_base_ids || []
  try {
    const { data } = await getMessagesAPI(conv.id)
    messages.value = data.map(m => ({
      role: m.role,
      content: m.content,
      attachments: m.attachments || [],
      sources: m.sources || [],
      time: m.created_at ? new Date(m.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '',
    }))
    scrollToBottom()
  } catch (e) {
    messages.value = []
  }
  if (inputRef.value) inputRef.value.focus()
}

async function deleteConversation(id) {
  try {
    await deleteConversationAPI(id)
    if (currentConvId.value === id) {
      currentConvId.value = null
      messages.value = []
    }
    conversations.value = conversations.value.filter(c => c.id !== id)
  } catch (e) {}
}

function startRename(conv) {
  editingConvId.value = conv.id
  editingTitle.value = conv.title
}

async function saveRename(id) {
  const title = editingTitle.value.trim()
  if (!title || editingConvId.value !== id) {
    cancelRename()
    return
  }
  try {
    await renameConversationAPI(id, title)
    const c = conversations.value.find(x => x.id === id)
    if (c) c.title = title
  } catch (e) {}
  cancelRename()
}

function cancelRename() {
  editingConvId.value = null
  editingTitle.value = ''
}

function toggleMenu(id) {
  menuOpenConvId.value = menuOpenConvId.value === id ? null : id
}

function onDocumentClick(e) {
  menuOpenConvId.value = null
  cancelRename()
  if (showAttachMenu.value && attachMenuRef.value && !attachMenuRef.value.contains(e.target)) {
    showAttachMenu.value = false
  }
}

function toggleAttachMenu() {
  showAttachMenu.value = !showAttachMenu.value
}

function toggleWebSearch() {
  webSearch.value = !webSearch.value
  showAttachMenu.value = false
}

async function triggerImageInput() {
  showAttachMenu.value = false
  await nextTick()
  const input = imageInput.value
  if (input) {
    input.value = ''
    input.click()
  }
}

async function triggerDocInput() {
  showAttachMenu.value = false
  await nextTick()
  const input = docInput.value
  if (input) {
    input.value = ''
    input.click()
  }
}

function doOpenKB() {
  showAttachMenu.value = false
  selectedKBIds.value = [...activeKnowledgeBaseIds.value]
  kbSearch.value = ''
  fetchKBList()
  showKBModal.value = true
}

async function fetchKBList() {
  try {
    const { data } = await listKnowledgeBasesAPI()
    kbList.value = data
  } catch (e) {
    kbList.value = []
  }
}

function toggleKBSelection(id) {
  if (selectedKBIds.value.includes(id)) {
    selectedKBIds.value = selectedKBIds.value.filter(value => value !== id)
  } else {
    selectedKBIds.value.push(id)
  }
}

function confirmKBSelect() {
  activeKnowledgeBaseIds.value = [...selectedKBIds.value]
  showKBModal.value = false
  if (inputRef.value) inputRef.value.focus()
}

function clearKnowledgeBases() {
  activeKnowledgeBaseIds.value = []
}

async function onImagePick(e) {
  showAttachMenu.value = false
  const files = Array.from(e.target.files || [])
  if (!files.length) return
  e.target.value = ''
  await Promise.all(files.map(file => uploadAttachment(file, 'image')))
}

async function onDocPick(e) {
  showAttachMenu.value = false
  const files = Array.from(e.target.files || [])
  if (!files.length) return
  e.target.value = ''
  await Promise.all(files.map(file => uploadAttachment(file, 'file')))
}

async function uploadAttachment(file, fileType) {
  const localId = createLocalId()
  const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : ''
  let previewUrl = null
  if (fileType === 'image') {
    previewUrl = URL.createObjectURL(file)
  }

  attachments.value.push({
    localId,
    type: fileType,
    name: file.name,
    size: file.size,
    status: 'uploading',
    progress: 0,
    content: '',
    ext,
    preview: previewUrl,
  })

  return new Promise((resolve) => {
    const updateAttachment = (changes) => {
      const attachment = attachments.value.find(item => item.localId === localId)
      if (!attachment) return
      Object.assign(attachment, changes)
    }

    const form = new FormData()
    form.append('file', file)
    form.append('filename', file.name)

    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/upload/chat-file')
    xhr.setRequestHeader('Authorization', `Bearer ${auth.token}`)

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100)
        updateAttachment({ progress: pct })
      }
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText)
          updateAttachment({
            id: data.id,
            type: data.type,
            name: data.name,
            mime: data.mime,
            size: data.size,
            status: 'completed',
            progress: 100,
          })
        } catch (e) {
          updateAttachment({ status: 'error', errorMsg: '解析上传响应失败' })
        }
      } else {
        let errMsg = '上传失败'
        try {
          const err = JSON.parse(xhr.responseText)
          errMsg = err.detail || errMsg
        } catch (e) {}
        updateAttachment({ status: 'error', errorMsg: errMsg })
      }
      resolve()
    }

    xhr.onerror = () => {
      updateAttachment({ status: 'error', errorMsg: '网络错误' })
      resolve()
    }

    xhr.send(form)
  })
}

function removeAttachment(localId) {
  const index = attachments.value.findIndex(item => item.localId === localId)
  if (index === -1) return
  const [removed] = attachments.value.splice(index, 1)
  if (removed.preview) URL.revokeObjectURL(removed.preview)
}

async function sendMessage() {
  const text = inputText.value.trim()
  if ((!text && !readyAttachments.value.length) || isStreaming.value || hasPendingUploads.value || hasUploadErrors.value) return

  // 保存当前附件用于显示
  const currentAttachments = readyAttachments.value.map(a => ({
    id: a.id,
    type: a.type,
    name: a.name,
    mime: a.mime,
    docId: a.docId,
  }))

  // 添加用户消息到界面
  messages.value.push({
    role: 'user',
    content: text || '请分析以上内容',
    time: formatTime(),
    attachments: currentAttachments,
  })

  // 清空输入框和附件,准备下一轮输入
  inputText.value = ''
  clearAttachments()
  await nextTick()
  if (inputRef.value) inputRef.value.style.height = 'auto'
  scrollToBottom()

  isStreaming.value = true

  const history = messages.value.map(m => ({
    role: m.role,
    content: m.content,
    attachments: m.attachments || [],
  }))

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${auth.token}`,
      },
      body: JSON.stringify({
        conversation_id: currentConvId.value,
        knowledge_base_ids: activeKnowledgeBaseIds.value,
        messages: history,
        stream: true,
        web_search: webSearch.value,
      }),
    })
    if (!resp.ok) {
      const errData = await resp.json()
      if (resp.status === 401) { handleLogout(); return }
      throw new Error(errData.detail || `HTTP ${resp.status}`)
    }

    let fullContent = ''
    let newConvId = currentConvId.value
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let eventBuffer = ''

    const appendAssistantContent = (content) => {
      fullContent += content
      if (messages.value.length && messages.value[messages.value.length - 1].role === 'assistant') {
        messages.value[messages.value.length - 1].content = fullContent
      } else {
        messages.value.push({ role: 'assistant', content: fullContent, time: formatTime() })
      }
      scrollToBottom()
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      eventBuffer += decoder.decode(value, { stream: true })
      const events = eventBuffer.split('\n\n')
      eventBuffer = events.pop() || ''
      for (const event of events) {
        for (const line of event.split('\n')) {
          if (!line.startsWith('data: ')) continue
          const dataStr = line.slice(6).trim()
          if (dataStr === '[DONE]') continue
          try {
            const data = JSON.parse(dataStr)
            if (data.error) {
              appendAssistantContent(`\n\n> 错误: ${data.error}`)
            } else if (data.sources) {
              const assistant = [...messages.value].reverse().find(message => message.role === 'assistant')
              if (assistant) assistant.sources = data.sources
            } else if (data.conv_id) {
              if (!currentConvId.value) {
                newConvId = data.conv_id
                currentConvId.value = data.conv_id
              }
              if (data.knowledge_base_ids) {
                activeKnowledgeBaseIds.value = data.knowledge_base_ids
              }
            } else if (data.content) {
              appendAssistantContent(data.content)
            }
          } catch (e) {}
        }
      }
    }

    if (!fullContent) {
      messages.value.push({ role: 'assistant', content: '未收到有效回复，请重试。', time: formatTime() })
    }

    if (newConvId && currentConvId.value === newConvId) {
      await fetchConversations()
    }
    scrollToBottom()
  } catch (err) {
    messages.value.push({ role: 'assistant', content: `请求失败: ${err.message}`, time: formatTime() })
    scrollToBottom()
  } finally {
    isStreaming.value = false
    if (inputRef.value) inputRef.value.focus()
  }
}

function sendSuggestion(text) {
  inputText.value = text
  sendMessage()
}

function handleLogout() {
  auth.logout()
  router.push('/login')
}

watch(() => auth.token, (token) => {
  if (!token) router.push('/login')
})

onMounted(async () => {
  await Promise.all([fetchConversations(), fetchKBList()])
  if (inputRef.value) inputRef.value.focus()
  document.addEventListener('click', onDocumentClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  clearAttachments()
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  width: 100%;
  height: 100vh;
  background: #111;
}

/* Sidebar */
.sidebar {
  width: 280px;
  min-width: 280px;
  background: rgba(255,255,255,0.03);
  border-right: 1px solid rgba(255,255,255,0.06);
  display: flex;
  flex-direction: column;
  transition: transform 0.3s ease;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}

.btn-new-chat {
  width: 100%;
  padding: 12px;
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  color: rgba(255,255,255,0.8);
  font-size: 14px;
  font-family: inherit;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: all 0.2s;
}

.btn-new-chat:hover {
  background: rgba(102,126,234,0.15);
  border-color: rgba(102,126,234,0.3);
  color: #fff;
}

.sidebar-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.sidebar-list::-webkit-scrollbar { width: 4px; }
.sidebar-list::-webkit-scrollbar-track { background: transparent; }
.sidebar-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

.conv-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 2px;
  position: relative;
  color: rgba(255,255,255,0.6);
}

.conv-item:hover {
  background: rgba(255,255,255,0.06);
  color: rgba(255,255,255,0.9);
}

.conv-item.active {
  background: rgba(102,126,234,0.15);
  color: #fff;
}

.conv-item i { font-size: 14px; flex-shrink: 0; }

.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
}

.conv-title-input {
  flex: 1;
  min-width: 0;
  background: rgba(102,126,234,0.15);
  border: 1px solid rgba(102,126,234,0.4);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 14px;
  font-family: inherit;
  color: #fff;
  outline: none;
}

.btn-more {
  background: none;
  border: none;
  color: rgba(255,255,255,0.25);
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 6px;
  opacity: 0;
  transition: all 0.2s;
  font-size: 14px;
  line-height: 1;
}

.conv-item:hover .btn-more { opacity: 1; }
.btn-more:hover { color: rgba(255,255,255,0.8); background: rgba(255,255,255,0.08); }

.conv-menu {
  position: absolute;
  right: 4px;
  top: calc(100% + 2px);
  background: rgba(30,30,50,0.98);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  padding: 4px;
  z-index: 50;
  min-width: 140px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  animation: fadeIn 0.15s ease;
}

@keyframes fadeIn {
  from { opacity:0; transform: translateY(-4px); }
  to { opacity:1; transform: translateY(0); }
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  border: none;
  background: none;
  color: rgba(255,255,255,0.75);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.15s;
  text-align: left;
}

.menu-item:hover { background: rgba(255,255,255,0.08); color: #fff; }
.menu-item i { font-size: 13px; width: 16px; text-align: center; }

.menu-danger:hover { background: rgba(239,68,68,0.15); color: #fca5a5; }

.sidebar-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 20px;
  color: rgba(255,255,255,0.2);
  text-align: center;
}

.sidebar-empty i { font-size: 32px; }
.sidebar-empty p { font-size: 13px; }

.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid rgba(255,255,255,0.06);
}

.sidebar-links {
  margin-bottom: 10px;
}

.sidebar-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  color: rgba(255,255,255,0.4);
  font-size: 13px;
  text-decoration: none;
  transition: all 0.2s;
}

.sidebar-link:hover {
  background: rgba(102,126,234,0.1);
  color: #a5b4fc;
}

.sidebar-user {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  color: rgba(255,255,255,0.5);
  font-size: 13px;
}

.user-info i { font-size: 16px; }

.btn-logout-side {
  background: none;
  border: none;
  color: rgba(255,255,255,0.3);
  cursor: pointer;
  padding: 6px 10px;
  border-radius: 8px;
  transition: all 0.2s;
  font-size: 14px;
}

.btn-logout-side:hover { color: #f87171; background: rgba(239,68,68,0.1); }

/* Main chat */
.main-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
}

.mobile-topbar {
  display: none;
  padding: 12px 16px;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}

.btn-menu {
  background: none;
  border: none;
  color: rgba(255,255,255,0.6);
  font-size: 20px;
  cursor: pointer;
  padding: 4px;
}

.mobile-title {
  flex: 1;
  font-size: 15px;
  font-weight: 500;
  color: rgba(255,255,255,0.8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
}

.btn-logout-mobile {
  background: none;
  border: none;
  color: rgba(255,255,255,0.4);
  font-size: 18px;
  cursor: pointer;
  padding: 4px;
}

/* Messages area */
.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  scroll-behavior: smooth;
}

.messages-area::-webkit-scrollbar { width: 5px; }
.messages-area::-webkit-scrollbar-track { background: transparent; }
.messages-area::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }

.message {
  display: flex;
  gap: 10px;
  max-width: 88%;
  animation: fadeInUp 0.3s ease;
}

@keyframes fadeInUp {
  from { opacity:0; transform:translateY(10px); }
  to { opacity:1; transform:translateY(0); }
}

.message.user { align-self: flex-end; flex-direction: row-reverse; }

.msg-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  margin-top: 4px;
}

.message.ai .msg-avatar { background: linear-gradient(135deg,#667eea,#764ba2); color: white; }
.message.user .msg-avatar { background: linear-gradient(135deg,#f093fb,#f5576c); color: white; }

.bubble {
  padding: 12px 16px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.7;
  word-wrap: break-word;
}

.message.ai .bubble {
  background: rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.92);
  border-bottom-left-radius: 5px;
  border: 1px solid rgba(255,255,255,0.06);
}

.message.user .bubble {
  background: linear-gradient(135deg,#667eea,#764ba2);
  color: white;
  border-bottom-right-radius: 5px;
}

.bubble p { margin-bottom: 6px; }
.bubble p:last-child { margin-bottom: 0; }

.bubble pre {
  background: rgba(0,0,0,0.3)!important;
  border-radius: 10px;
  padding: 14px;
  margin: 8px 0;
  overflow-x: auto;
  border: 1px solid rgba(255,255,255,0.06);
}

.bubble pre code {
  font-family: 'JetBrains Mono','Fira Code','Consolas',monospace;
  font-size: 13px;
  line-height: 1.6;
  background: none!important;
  padding: 0!important;
  color: #e4e4e4;
}

.bubble code:not(pre code) {
  background: rgba(102,126,234,0.2);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  color: #a5b4fc;
}

.bubble ul, .bubble ol { padding-left: 20px; margin: 5px 0; }
.bubble blockquote { border-left: 3px solid rgba(102,126,234,0.5); padding-left: 12px; color: rgba(255,255,255,0.5); margin: 6px 0; }
.bubble table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 13px; }
.bubble th,.bubble td { border: 1px solid rgba(255,255,255,0.12); padding: 6px 10px; text-align: left; }
.bubble th { background: rgba(255,255,255,0.04); font-weight: 600; }
.bubble a { color: #a5b4fc; text-decoration: none; }
.bubble a:hover { text-decoration: underline; }

.timestamp {
  font-size: 10px;
  color: rgba(255,255,255,0.18);
  margin-top: 4px;
  text-align: right;
}

.typing-indicator {
  display: flex;
  gap: 10px;
  max-width: 88%;
  animation: fadeInUp 0.3s ease;
}

.typing-dots {
  background: rgba(255,255,255,0.08);
  padding: 14px 22px;
  border-radius: 16px;
  border-bottom-left-radius: 5px;
  display: flex;
  gap: 4px;
  align-items: center;
  border: 1px solid rgba(255,255,255,0.06);
}

.typing-dots span {
  width: 7px;
  height: 7px;
  background: rgba(255,255,255,0.35);
  border-radius: 50%;
  display: inline-block;
  animation: bounce 1.4s infinite ease-in-out both;
}

.typing-dots span:nth-child(1) { animation-delay: -0.32s; }
.typing-dots span:nth-child(2) { animation-delay: -0.16s; }
.typing-dots span:nth-child(3) { animation-delay: 0s; }

@keyframes bounce { 0%,80%,100% { transform:scale(0.6); } 40% { transform:scale(1); } }

/* Input */
.input-area {
  padding: 16px 24px;
  background: rgba(255,255,255,0.03);
  border-top: 1px solid rgba(255,255,255,0.06);
}

.input-wrapper {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  background: rgba(255,255,255,0.06);
  border-radius: 14px;
  padding: 3px;
  border: 1px solid rgba(255,255,255,0.08);
  transition: border-color 0.3s, box-shadow 0.3s;
}

.input-wrapper:focus-within {
  border-color: rgba(102,126,234,0.5);
  box-shadow: 0 0 16px rgba(102,126,234,0.08);
}

.input-wrapper textarea {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  padding: 10px 14px;
  font-size: 14px;
  color: rgba(255,255,255,0.9);
  font-family: inherit;
  resize: none;
  max-height: 100px;
  line-height: 1.5;
}

.input-wrapper textarea::placeholder { color: rgba(255,255,255,0.25); }

.btn-send {
  width: 40px;
  height: 40px;
  border: none;
  background: linear-gradient(135deg,#667eea,#764ba2);
  border-radius: 11px;
  color: white;
  font-size: 16px;
  cursor: pointer;
  transition: all 0.25s;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin: 3px;
}

.btn-send:hover { transform: scale(1.05); box-shadow: 0 4px 12px rgba(102,126,234,0.35); }
.btn-send:active { transform: scale(0.95); }
.btn-send:disabled { opacity: 0.35; cursor: not-allowed; transform: none; box-shadow: none; }

/* Empty state */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: rgba(255,255,255,0.18);
  gap: 12px;
  user-select: none;
}

.empty-state i { font-size: 48px; }
.empty-state h2 { font-size: 20px; font-weight: 500; color: rgba(255,255,255,0.25); }
.empty-state p { font-size: 13px; color: rgba(255,255,255,0.12); }

.welcome-suggestions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 20px;
}

.chip {
  padding: 7px 14px;
  border-radius: 18px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.4);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.chip:hover {
  background: rgba(102,126,234,0.18);
  border-color: rgba(102,126,234,0.25);
  color: rgba(255,255,255,0.75);
}

/* Sidebar overlay for mobile */
.sidebar-overlay {
  display: none;
}

@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 100;
    transform: translateX(-100%);
    width: 260px;
  }

  .sidebar.open {
    transform: translateX(0);
  }

  .sidebar-overlay {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.5);
    z-index: 99;
  }

  .mobile-topbar { display: flex; }
  .messages-area { padding: 16px; }
  .input-area { padding: 12px 16px; }
  .message { max-width: 95%; }
}

/* Attach button */
.btn-attach {
  width: 36px;
  height: 36px;
  border: none;
  background: transparent;
  color: rgba(255,255,255,0.35);
  font-size: 18px;
  cursor: pointer;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  margin: 3px 0 3px 3px;
  flex-shrink: 0;
}

.attach-control {
  position: relative;
  flex-shrink: 0;
}

.btn-attach:hover {
  background: rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.7);
}

.attach-menu {
  position: absolute;
  bottom: calc(100% + 4px);
  left: 0;
  background: rgba(30,30,50,0.98);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 4px;
  z-index: 50;
  min-width: 160px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  animation: fadeIn 0.15s ease;
}

.attach-menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 14px;
  border: none;
  background: none;
  color: rgba(255,255,255,0.75);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.15s;
  text-align: left;
}

.attach-menu-item:hover { background: rgba(255,255,255,0.08); color: #fff; }
.attach-menu-item i { font-size: 15px; width: 18px; text-align: center; }
.attach-menu-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.08);
  margin: 4px 0;
}
.attach-menu-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.toggle-switch {
  position: relative;
  width: 32px;
  height: 18px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 999px;
  transition: background 0.2s;
  flex-shrink: 0;
}
.toggle-switch.on { background: #3b82f6; }
.toggle-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  background: #fff;
  border-radius: 50%;
  transition: transform 0.2s;
}
.toggle-switch.on .toggle-knob { transform: translateX(14px); }
.websearch-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  align-self: flex-start;
  padding: 4px 10px;
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 999px;
  font-size: 12px;
  cursor: pointer;
  margin: 6px 0 0 44px;
  transition: all 0.2s;
}
.websearch-chip:hover { background: rgba(59, 130, 246, 0.25); }
.websearch-chip i { font-size: 11px; }

/* Attachments bar */
.attachments-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 24px 0;
  animation: fadeIn 0.2s ease;
}

/* Square attachment cards */
.attach-card {
  position: relative;
  width: 80px;
  height: 80px;
  border-radius: 12px;
  overflow: hidden;
  background: #1a1a2e;
  border: 1px solid rgba(255,255,255,0.1);
  cursor: default;
  animation: fadeIn 0.25s ease;
  transition: border-color 0.3s;
}

.attach-card.completed {
  border-color: rgba(74,222,128,0.4);
}

.attach-card.error {
  border-color: rgba(248,113,113,0.4);
}

/* Image preview inside card */
.attach-card-img {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center;
}

/* File icon inside card */
.attach-card-icon {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  color: rgba(255,255,255,0.35);
}

.attach-card-icon i {
  font-size: 24px;
}

.attach-card-ext {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  color: rgba(255,255,255,0.25);
  letter-spacing: 0.5px;
}

/* Dark overlay - fades out during upload (dark -> bright) */
.attach-card-overlay {
  position: absolute;
  inset: 0;
  background: #000;
  pointer-events: none;
  transition: opacity 0.3s ease;
}

/* Progress bar at bottom */
.attach-card-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: rgba(255,255,255,0.1);
}

.attach-card-progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #667eea, #764ba2);
  transition: width 0.15s ease;
}

.attach-card-percent {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  text-shadow: 0 1px 4px rgba(0,0,0,0.9);
  pointer-events: none;
}

/* Completed check icon */
.attach-card-check {
  position: absolute;
  bottom: 6px;
  right: 6px;
  color: #4ade80;
  font-size: 18px;
  filter: drop-shadow(0 1px 3px rgba(0,0,0,0.5));
  animation: fadeIn 0.3s ease;
}

/* Error icon */
.attach-card-error {
  position: absolute;
  bottom: 6px;
  right: 6px;
  color: #f87171;
  font-size: 18px;
  filter: drop-shadow(0 1px 3px rgba(0,0,0,0.5));
  animation: fadeIn 0.3s ease;
}

/* Remove button on card */
.attach-card-remove {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: rgba(0,0,0,0.6);
  border: none;
  color: rgba(255,255,255,0.7);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s, background 0.2s;
}

.attach-card:hover .attach-card-remove {
  opacity: 1;
}

.attach-card-remove:hover {
  background: rgba(239,68,68,0.8);
  color: #fff;
}

/* File name at bottom */
.attach-card-name {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 3px 5px;
  background: linear-gradient(transparent, rgba(0,0,0,0.7));
  font-size: 9px;
  color: rgba(255,255,255,0.7);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Message attachments */
.msg-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}

.msg-attach-item {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  background: rgba(255,255,255,0.06);
  border-radius: 6px;
  font-size: 11px;
  color: rgba(255,255,255,0.5);
}

.msg-attach-item i { font-size: 12px; }

.message-sources {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid rgba(255,255,255,0.08);
}

.sources-title {
  font-size: 11px;
  color: rgba(255,255,255,0.4);
  margin-bottom: 6px;
}

.source-card {
  margin-top: 5px;
  padding: 7px 9px;
  background: rgba(255,255,255,0.05);
  border-radius: 8px;
  font-size: 11px;
}

.source-card summary {
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: rgba(255,255,255,0.72);
}

.source-card summary small {
  color: rgba(255,255,255,0.3);
  flex-shrink: 0;
}

.source-card p {
  margin-top: 7px;
  color: rgba(255,255,255,0.48);
  white-space: pre-wrap;
}

.active-kb-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
  padding: 8px 24px 0;
  color: rgba(255,255,255,0.42);
  font-size: 11px;
}

.active-kb-bar > i {
  color: #818cf8;
}

.active-kb-chip {
  padding: 4px 8px;
  border-radius: 12px;
  background: rgba(99,102,241,0.15);
  color: #c7d2fe;
}

.active-kb-bar button {
  border: 0;
  background: transparent;
  color: rgba(255,255,255,0.35);
  cursor: pointer;
  font-size: 17px;
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  animation: fadeIn 0.15s ease;
}

.modal-panel {
  width: 90%;
  max-width: 480px;
  max-height: 80vh;
  background: rgba(25,25,45,0.98);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 16px 48px rgba(0,0,0,0.5);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}

.modal-header h3 {
  font-size: 16px;
  color: rgba(255,255,255,0.9);
  font-weight: 600;
}

.modal-close {
  background: none;
  border: none;
  color: rgba(255,255,255,0.3);
  font-size: 22px;
  cursor: pointer;
  padding: 4px;
  line-height: 1;
  transition: color 0.2s;
}

.modal-close:hover { color: #fff; }

.modal-search {
  padding: 12px 20px;
}

.search-input {
  width: 100%;
  padding: 9px 12px;
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px;
  font-size: 13px;
  color: rgba(255,255,255,0.8);
  font-family: inherit;
  outline: none;
  transition: border-color 0.2s;
}

.search-input:focus {
  border-color: rgba(102,126,234,0.4);
}

.search-input::placeholder { color: rgba(255,255,255,0.2); }

.modal-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 12px 12px;
}

.modal-list::-webkit-scrollbar { width: 4px; }
.modal-list::-webkit-scrollbar-track { background: transparent; }
.modal-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

.kb-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 2px;
}

.kb-item:hover { background: rgba(255,255,255,0.06); }
.kb-item.selected { background: rgba(102,126,234,0.15); }

.kb-item i:first-child {
  font-size: 16px;
  color: rgba(255,255,255,0.3);
  flex-shrink: 0;
}

.kb-item.selected i:first-child { color: #a5b4fc; }

.kb-item-info {
  flex: 1;
  min-width: 0;
}

.kb-item-title {
  display: block;
  font-size: 13px;
  color: rgba(255,255,255,0.8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-item-meta {
  display: block;
  font-size: 11px;
  color: rgba(255,255,255,0.25);
  margin-top: 2px;
}

.check-icon {
  color: #667eea !important;
  font-size: 16px;
}

.modal-empty {
  text-align: center;
  color: rgba(255,255,255,0.2);
  padding: 40px 20px;
  font-size: 13px;
}

.modal-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding: 12px 20px;
  border-top: 1px solid rgba(255,255,255,0.06);
}

.modal-btn {
  padding: 8px 18px;
  border-radius: 10px;
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
}

.modal-btn-cancel {
  background: rgba(255,255,255,0.06);
  color: rgba(255,255,255,0.6);
}

.modal-btn-cancel:hover { background: rgba(255,255,255,0.1); }

.modal-btn-confirm {
  background: linear-gradient(135deg,#667eea,#764ba2);
  color: white;
}

/* Hidden file input - off-screen but still clickable via label */
.hidden-input {
  position: absolute;
  left: -10000px;
  top: -10000px;
  width: 0;
  height: 0;
  opacity: 0;
}
</style>
