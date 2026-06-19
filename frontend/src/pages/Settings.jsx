import { useState, useEffect } from 'react'
import api from '../api/client'
import toast from 'react-hot-toast'
import { Bell, Plus, Trash2, Save, X, Check, Wifi } from 'lucide-react'

const ALERT_TYPES = [
  { value: 'sms', label: '📱 SMS (Twilio)', fields: [{ key: 'to_number', label: 'Phone Number', placeholder: '+1234567890' }] },
  { value: 'call', label: '📞 Voice Call (Twilio)', fields: [{ key: 'to_number', label: 'Phone Number', placeholder: '+1234567890' }] },
  { value: 'telegram', label: '✈️ Telegram', fields: [{ key: 'bot_token', label: 'Bot Token', placeholder: '12345:ABC...' }, { key: 'chat_id', label: 'Chat ID', placeholder: '-1001234...' }] },
  { value: 'discord', label: '🎮 Discord Webhook', fields: [{ key: 'webhook_url', label: 'Webhook URL', placeholder: 'https://discord.com/api/webhooks/...' }] },
  { value: 'slack', label: '💬 Slack Webhook', fields: [{ key: 'webhook_url', label: 'Webhook URL', placeholder: 'https://hooks.slack.com/...' }] },
]

export default function Settings() {
  const [alerts, setAlerts] = useState([])
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState({ alert_type: 'sms', config: {}, active: true })
  const [loading, setLoading] = useState(false)
  const [lanIp, setLanIp] = useState('...')

  const load = async () => {
    try {
      const { data } = await api.get('/alerts')
      setAlerts(data)
    } catch {}
  }

  useEffect(() => { load() }, [])

  const addAlert = async () => {
    setLoading(true)
    try {
      await api.post('/alerts', {
        alert_type: form.alert_type,
        config_json: JSON.stringify(form.config),
        active: form.active,
      })
      toast.success('Alert configured!')
      setShowAdd(false)
      setForm({ alert_type: 'sms', config: {}, active: true })
      load()
    } catch { toast.error('Failed') }
    finally { setLoading(false) }
  }

  const deleteAlert = async (id) => {
    try {
      await api.delete(`/alerts/${id}`)
      toast.success('Removed')
      load()
    } catch {}
  }

  const alertDef = ALERT_TYPES.find(a => a.value === form.alert_type)

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Settings</div>
      </div>

      <div className="page-body">
        {/* Alert Channels */}
        <div className="card mb-6">
          <div className="card-header">
            <div className="card-title"><Bell size={16} />Alert Channels</div>
            <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(true)}><Plus size={13} />Add Channel</button>
          </div>

          {alerts.length === 0 ? (
            <div className="empty-state" style={{ padding: 24 }}>
              <div className="text-sm text-muted">No alert channels configured</div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {alerts.map(a => {
                const def = ALERT_TYPES.find(t => t.value === a.alert_type)
                return (
                  <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', background: 'var(--bg2)', borderRadius: 8 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600 }}>{def?.label || a.alert_type}</div>
                      <div className="text-xs text-muted text-mono">
                        {Object.values(JSON.parse(a.config_json || '{}')).join(' · ')}
                      </div>
                    </div>
                    <span className={`badge ${a.active ? 'badge-low' : 'badge-medium'}`}>
                      {a.active ? 'Active' : 'Paused'}
                    </span>
                    <button className="btn btn-danger btn-sm" onClick={() => deleteAlert(a.id)}><Trash2 size={13} /></button>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Remote Access */}
        <div className="card mb-6">
          <div className="card-title" style={{ marginBottom: 14 }}><Wifi size={16} />Remote Access</div>
          <div style={{ display: 'grid', gap: 12 }}>
            <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: '14px 16px' }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>📱 Phone on Same WiFi</div>
              <div className="text-sm text-muted" style={{ marginBottom: 8 }}>
                Open on your phone while connected to the same WiFi network as this laptop:
              </div>
              <code style={{ background: 'var(--surface)', padding: '6px 12px', borderRadius: 6, fontSize: 13, color: 'var(--accent)', display: 'block' }}>
                http://&lt;laptop-LAN-IP&gt;:5173
              </code>
              <div className="text-xs text-muted" style={{ marginTop: 8 }}>
                Find your LAN IP: run <code style={{ color: 'var(--accent)' }}>ipconfig</code> in CMD, look for IPv4 Address
              </div>
            </div>
            <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: '14px 16px' }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>🌐 Access From Anywhere (Tailscale)</div>
              <div className="text-sm text-muted" style={{ marginBottom: 8 }}>
                Free, zero-config VPN — no port forwarding needed:
              </div>
              <ol style={{ fontSize: 13, color: 'var(--text2)', paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 4 }}>
                <li>Install Tailscale on laptop: <a href="https://tailscale.com/download" target="_blank" style={{ color: 'var(--primary)' }}>tailscale.com/download</a></li>
                <li>Install Tailscale on phone and sign in with same account</li>
                <li>Access: <code style={{ color: 'var(--accent)' }}>http://&lt;tailscale-ip&gt;:5173</code></li>
              </ol>
            </div>
            <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: '14px 16px' }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>📷 Add Phone as Camera (IP Webcam)</div>
              <ol style={{ fontSize: 13, color: 'var(--text2)', paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 4 }}>
                <li>Install <strong>IP Webcam</strong> app on Android</li>
                <li>Open app → tap <em>Start Server</em></li>
                <li>Note the URL shown (e.g. <code style={{ color: 'var(--accent)' }}>http://192.168.1.5:8080</code>)</li>
                <li>Add camera in Neural Sentinel: source = <code style={{ color: 'var(--accent)' }}>http://192.168.1.5:8080/video</code></li>
              </ol>
            </div>
          </div>
        </div>

        {/* System info */}
        <div className="card">
          <div className="card-title" style={{ marginBottom: 14 }}>⚙️ System Info</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
            {[
              ['Model', 'YOLOv8n (CPU)'],
              ['Tracking', 'ByteTrack'],
              ['Face Recognition', 'InsightFace (ONNX)'],
              ['Backend', 'FastAPI + SQLite'],
              ['Frontend', 'React + Vite'],
              ['Version', '3.0.0 (Patent Pending)'],
            ].map(([k, v]) => (
              <div key={k} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '10px 14px' }}>
                <div className="text-xs text-muted">{k}</div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{v}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Add Alert Modal */}
      {showAdd && (
        <div className="modal-backdrop" onClick={() => setShowAdd(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title">Add Alert Channel</div>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowAdd(false)}><X size={14} /></button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">Channel Type</label>
                <select className="form-select" value={form.alert_type} onChange={e => setForm(f => ({ ...f, alert_type: e.target.value, config: {} }))}>
                  {ALERT_TYPES.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
                </select>
              </div>
              {alertDef?.fields.map(field => (
                <div className="form-group" key={field.key}>
                  <label className="form-label">{field.label}</label>
                  <input
                    className="form-input"
                    placeholder={field.placeholder}
                    value={form.config[field.key] || ''}
                    onChange={e => setForm(f => ({ ...f, config: { ...f.config, [field.key]: e.target.value } }))}
                  />
                </div>
              ))}
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                <input type="checkbox" checked={form.active} onChange={e => setForm(f => ({ ...f, active: e.target.checked }))} />
                Active
              </label>
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setShowAdd(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={addAlert} disabled={loading}>
                {loading ? <span className="spinner" /> : <Check size={14} />}Save
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
