import { useState } from 'react'
import api from '../api/client'
import { useAuthStore } from '../store/authStore'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Eye, EyeOff } from 'lucide-react'

export default function Login() {
  const [form, setForm] = useState({ username: '', password: '' })
  const [loading, setLoading] = useState(false)
  const [showPw, setShowPw] = useState(false)
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()

  const update = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      const { data } = await api.post('/auth/login', form)
      setAuth(data.access_token, data.user)
      navigate('/dashboard')
      toast.success(`Welcome back, ${data.user.username}!`)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Invalid credentials')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <div style={{ fontSize: 52, marginBottom: 8 }}>🛡️</div>
          <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: -0.5 }}>Neural Sentinel</div>
          <div style={{ fontSize: 11, color: 'var(--primary)', letterSpacing: 3, textTransform: 'uppercase', marginTop: 6 }}>
            AI Surveillance Platform
          </div>
        </div>

        <form onSubmit={submit} style={{ marginTop: 32 }}>
          <div className="form-group">
            <label className="form-label">Username</label>
            <input
              className="form-input"
              value={form.username}
              onChange={update('username')}
              placeholder="admin"
              required
              autoFocus
              autoComplete="username"
            />
          </div>
          <div className="form-group">
            <label className="form-label">Password</label>
            <div style={{ position: 'relative' }}>
              <input
                className="form-input"
                type={showPw ? 'text' : 'password'}
                value={form.password}
                onChange={update('password')}
                placeholder="••••••••"
                required
                autoComplete="current-password"
                style={{ paddingRight: 42 }}
              />
              <button type="button" onClick={() => setShowPw(!showPw)}
                style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: 'var(--text2)', cursor: 'pointer' }}>
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
          <button className="btn btn-primary w-full" type="submit" disabled={loading} style={{ marginTop: 16 }}>
            {loading ? <span className="spinner" /> : '🔐 Sign In'}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: 28, fontSize: 11, color: 'var(--text3)', lineHeight: 1.8 }}>
          Neural Sentinel v3.0 · Multi-agent AI · Patent pending<br />
          <span style={{ color: 'var(--text3)', fontSize: 10 }}>Single-user secured system</span>
        </div>
      </div>
    </div>
  )
}
