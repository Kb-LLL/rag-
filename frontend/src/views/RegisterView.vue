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
      <h2 class="auth-form-title">创建账号</h2>
      <p class="auth-form-sub">
        已有账号？<router-link to="/login">去登录</router-link>
      </p>

      <div v-if="auth.error" class="auth-error">
        <span class="err-icon">&#9888;</span>
        <span>{{ auth.error }}</span>
      </div>

      <div v-if="registered" class="auth-success">
        <i class="fa-regular fa-circle-check"></i> 注册成功！正在跳转到登录页...
      </div>

      <form @submit.prevent="handleRegister">
        <div class="form-group">
          <label>用户名</label>
          <div class="input-wrap">
            <i class="fa-regular fa-user icon"></i>
            <input
              v-model="username"
              type="text"
              placeholder="请输入用户名（至少2个字符）"
              autocomplete="off"
              :disabled="auth.loading"
            />
          </div>
        </div>

        <div class="form-group">
          <label>邮箱</label>
          <div class="input-wrap">
            <i class="fa-regular fa-envelope icon"></i>
            <input
              v-model="email"
              type="email"
              placeholder="请输入邮箱地址"
              autocomplete="email"
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
              placeholder="请设置密码（至少6位）"
              autocomplete="new-password"
              :disabled="auth.loading"
            />
            <button type="button" class="toggle-pass" @click="showPass = !showPass" tabindex="-1">
              <i :class="showPass ? 'fa-regular fa-eye-slash' : 'fa-regular fa-eye'"></i>
            </button>
          </div>
        </div>

        <button type="submit" class="btn-submit" :disabled="auth.loading || registered || !username || !email || !password">
          <span v-if="auth.loading" class="spinner"></span>
          <span class="btn-text">{{ auth.loading ? '注册中...' : '注 册' }}</span>
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
const email = ref('')
const password = ref('')
const showPass = ref(false)
const registered = ref(false)
const lottieContainer = ref(null)
let lottieInstance = null

async function handleRegister() {
  if (!username.value || !email.value || !password.value) return
  if (username.value.length < 2) {
    auth.error = '用户名至少2个字符'
    return
  }
  if (password.value.length < 6) {
    auth.error = '密码至少6位'
    return
  }
  const ok = await auth.register(username.value, email.value, password.value)
  if (ok) {
    registered.value = true
    setTimeout(() => {
      router.push('/login?registered=1')
    }, 1500)
  }
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
})

onBeforeUnmount(() => {
  if (lottieInstance) {
    lottieInstance.destroy()
    lottieInstance = null
  }
})
</script>