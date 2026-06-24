import { defineStore } from 'pinia'
import { loginAPI, registerAPI, getMeAPI } from '../api'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    token: localStorage.getItem('token') || null,
    loading: false,
    error: null,
  }),

  getters: {
    isAuthenticated: (state) => !!state.token,
    username: (state) => state.user?.username || '',
  },

  actions: {
    async login(username, password) {
      this.loading = true
      this.error = null
      try {
        const { data } = await loginAPI(username, password)
        this.token = data.token
        this.user = data.user
        localStorage.setItem('token', data.token)
        return true
      } catch (err) {
        this.error = err.response?.data?.detail || '登录失败，请检查网络连接'
        return false
      } finally {
        this.loading = false
      }
    },

    async register(username, email, password) {
      this.loading = true
      this.error = null
      try {
        await registerAPI(username, email, password)
        return true
      } catch (err) {
        this.error = err.response?.data?.detail || '注册失败，请检查网络连接'
        return false
      } finally {
        this.loading = false
      }
    },

    async fetchUser() {
      if (!this.token) return null
      try {
        const { data } = await getMeAPI()
        this.user = data
        return data
      } catch {
        this.logout()
        return null
      }
    },

    logout() {
      this.token = null
      this.user = null
      this.error = null
      localStorage.removeItem('token')
    },
  },
})
