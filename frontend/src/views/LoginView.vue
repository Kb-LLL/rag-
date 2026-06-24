<template>
  <div class="auth-split">
    <div class="auth-left">
      <div ref="lottieContainer" class="lottie-box"></div>
      <div class="tagline">
        <h2>AI 智能助手</h2>
        <p>基于 GLM-5.1 大模型 · 流畅对话体验</p>
      </div>
    </div>
    <div class="auth-right">
      <h2 class="auth-form-title">欢迎回来</h2>
      <p class="auth-form-sub">
        还没有账号？<router-link to="/register">立即注册</router-link>
      </p>

      <div v-if="showSuccess" class="auth-success">
        <i class="fa-regular fa-circle-check"></i> 注册成功！请使用账号密码登录。
      </div>

      <div v-if="auth.error" class="auth-error">
        <span class="err-icon">&#9888;</span>
        <span>{{ auth.error }}</span>
      </div>

      <form @submit.prevent="handleLogin">
        <div class="form-group">
          <label>用户名 / 邮箱</label>
          <div class="input-wrap">
            <i class="fa-regular fa-user icon"></i>
            <input
              v-model="username"
              type="text"
              placeholder="请输入用户名或邮箱"
              autocomplete="username"
              :disabled="auth.loading"
            />
          </div>
        </div>

        <div class="form-group">
          <label>密码</label>
          <div class="input-wrap">
            <i class="fa-solid fa-lock icon"></i>
            <input
              v-model="password"
              :type="showPass ? 'text' : 'password'"
              placeholder="请输入密码"
              autocomplete="current-password"
              :disabled="auth.loading"
            />
            <button type="button" class="toggle-pass" @click="showPass = !showPass" tabindex="-1">
              <i :class="showPass ? 'fa-regular fa-eye-slash' : 'fa-regular fa-eye'"></i>
            </button>
          </div>
        </div>

        <button type="submit" class="btn-submit" :disabled="auth.loading || !username || !password">
          <span v-if="auth.loading" class="spinner"></span>
          <span class="btn-text">{{ auth.loading ? '登录中...' : '登 录' }}</span>
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import lottie from 'lottie-web'

const auth = useAuthStore()
const router = useRouter()

const username = ref('')
const password = ref('')
const showPass = ref(false)
const showSuccess = ref(false)
const lottieContainer = ref(null)
let lottieInstance = null

async function handleLogin() {
  if (!username.value || !password.value) return
  const ok = await auth.login(username.value, password.value)
  if (ok) router.push('/chat')
}

onMounted(() => {
  if (lottieContainer.value) {
    lottieInstance = lottie.loadAnimation({
      container: lottieContainer.value,
      renderer: 'svg',
      loop: true,
      autoplay: true,
      path: 'https://assets2.lottiefiles.com/packages/lf20_givpconn.json',
    })
  }
  if (router.currentRoute.value.query.registered === '1') {
    showSuccess.value = true
  }
})

onBeforeUnmount(() => {
  if (lottieInstance) {
    lottieInstance.destroy()
    lottieInstance = null
  }
})
</script>