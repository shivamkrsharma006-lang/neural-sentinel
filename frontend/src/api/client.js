import axios from 'axios'
import { useAuthStore } from '../store/authStore'

const api = axios.create({ baseURL: '/api' })

// ── Backend-offline state ──────────────────────────────────────────────────────
// Exports a simple event bus so any component can subscribe to online/offline
export const backendState = {
  isOnline: true,
  listeners: new Set(),
  setOnline(val) {
    if (this.isOnline !== val) {
      this.isOnline = val
      this.listeners.forEach(fn => fn(val))
    }
  },
  subscribe(fn) {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }
}

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => {
    backendState.setOnline(true)
    return r
  },
  (err) => {
    // Network error (ECONNREFUSED, ECONNRESET) — backend is down
    if (!err.response) {
      backendState.setOnline(false)
    } else {
      backendState.setOnline(true)
      if (err.response.status === 401) {
        useAuthStore.getState().logout()
      }
    }
    return Promise.reject(err)
  }
)

export default api
