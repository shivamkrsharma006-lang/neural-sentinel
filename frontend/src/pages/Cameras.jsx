import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import toast from 'react-hot-toast'
import { Camera, Plus, Trash2, Edit3, Wifi, WifiOff, Settings, X, Check } from 'lucide-react'

export default function Cameras() {
  const [cameras, setCameras] = useState([])
  const [showAdd, setShowAdd] = useState(false)
  const [editCam, setEditCam] = useState(null)  // {id, name, source} or null
  const [form, setForm] = useState({ name: '', source: '0' })
  const [editForm, setEditForm] = useState({ name: '', source: '' })
  const [testing, setTesting] = useState(false)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const load = async () => {
    try {
      const { data } = await api.get('/cameras')
      setCameras(data)
    } catch {}
  }

  useEffect(() => { load() }, [])

  const testSource = async () => {
    setTesting(true)
    try {
      const { data } = await api.post('/cameras/test', form)
      if (data.accessible) toast.success('Camera accessible ✓')
      else toast.error('Cannot reach camera source')
    } catch { toast.error('Test failed') }
    finally { setTesting(false) }
  }

  const addCamera = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      await api.post('/cameras', form)
      toast.success('Camera added!')
      setShowAdd(false)
      setForm({ name: '', source: '0' })
      load()
    } catch (err) { toast.error(err.response?.data?.detail || 'Failed') }
    finally { setLoading(false) }
  }

  const deleteCamera = async (id) => {
    if (!confirm('Delete this camera and all its zones?')) return
    try {
      await api.delete(`/cameras/${id}`)
      toast.success('Camera removed')
      load()
    } catch { toast.error('Failed to delete') }
  }

  const openEdit = (cam) => {
    setEditCam(cam)
    setEditForm({ name: cam.name, source: cam.source })
  }

  const saveEdit = async (e) => {
    e.preventDefault()
    if (!editCam) return
    setLoading(true)
    try {
      const payload = {}
      if (editForm.name !== editCam.name) payload.name = editForm.name
      if (editForm.source !== editCam.source) payload.source = editForm.source
      if (Object.keys(payload).length === 0) { setEditCam(null); return }
      await api.patch(`/cameras/${editCam.id}`, payload)
      toast.success('Camera updated!')
      setEditCam(null)
      load()
    } catch (err) { toast.error(err.response?.data?.detail || 'Update failed') }
    finally { setLoading(false) }
  }

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Cameras</div>
        <div className="topbar-right">
          <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
            <Plus size={15} />Add Camera
          </button>
        </div>
      </div>

      <div className="page-body">
        <div style={{ display: 'grid', gap: 14 }}>
          {cameras.length === 0 ? (
            <div className="card">
              <div className="empty-state">
                <Camera size={48} />
                <div style={{ fontSize: 16, fontWeight: 600 }}>No cameras yet</div>
                <div className="text-muted">Add your first camera to start monitoring</div>
                <button className="btn btn-primary" onClick={() => setShowAdd(true)}><Plus size={14} />Add Camera</button>
              </div>
            </div>
          ) : cameras.map(cam => (
            <div key={cam.id} className="card" style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
              {/* Thumbnail */}
              <div style={{ width: 160, height: 90, background: '#000', borderRadius: 8, overflow: 'hidden', flexShrink: 0 }}>
                <img src={`/stream/${cam.id}`} alt={cam.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <div style={{ fontWeight: 700, fontSize: 15 }}>{cam.name}</div>
                  <span className={`badge ${cam.status === 'online' ? 'badge-low' : 'badge-critical'}`}>
                    {cam.status === 'online' ? <Wifi size={10} /> : <WifiOff size={10} />}
                    {cam.status}
                  </span>
                </div>
                <div className="text-sm text-muted" style={{ fontFamily: 'var(--font-mono)' }}>
                  Source: {cam.source}
                </div>
                <div className="text-xs text-muted" style={{ marginTop: 4 }}>
                  Added {new Date(cam.created_at).toLocaleDateString()}
                </div>
              </div>

              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => openEdit(cam)}
                  title="Edit name / URL"
                >
                  <Edit3 size={14} />
                </button>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => navigate(`/cameras/${cam.id}/zones`)}
                  title="Edit zones"
                >
                  <Settings size={14} />Zones
                </button>
                <button className="btn btn-danger btn-sm" onClick={() => deleteCamera(cam.id)}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Source tips */}
        <div className="card" style={{ marginTop: 20 }}>
          <div className="card-title" style={{ marginBottom: 12 }}>📡 Camera Source Examples</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
            {[
              { label: 'Laptop webcam', value: '0' },
              { label: 'Second USB cam', value: '1' },
              { label: 'IP Webcam (Android)', value: 'http://192.168.1.x:8080/video' },
              { label: 'DroidCam', value: 'http://192.168.1.x:4747/video' },
              { label: 'RTSP camera', value: 'rtsp://user:pass@192.168.1.x/stream' },
            ].map(ex => (
              <div key={ex.label} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '10px 14px' }}>
                <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 4 }}>{ex.label}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent)' }}>{ex.value}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Edit Camera Modal */}
      {editCam && (
        <div className="modal-backdrop" onClick={() => setEditCam(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title">Edit Camera — {editCam.name}</div>
              <button className="btn btn-ghost btn-sm" onClick={() => setEditCam(null)}><X size={14} /></button>
            </div>
            <form onSubmit={saveEdit}>
              <div className="modal-body">
                <div className="form-group">
                  <label className="form-label">Camera Name</label>
                  <input className="form-input" value={editForm.name} onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Source URL</label>
                  <input className="form-input" value={editForm.source} onChange={e => setEditForm(f => ({ ...f, source: e.target.value }))} placeholder="0 or http://... or rtsp://..." required />
                  <span className="text-xs text-muted">Changing the URL will hot-swap the camera stream without losing zones.</span>
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-ghost" onClick={() => setEditCam(null)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={loading}>
                  {loading ? <span className="spinner" /> : <Check size={14} />}
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add Camera Modal */}
      {showAdd && (
        <div className="modal-backdrop" onClick={() => setShowAdd(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title">Add Camera</div>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowAdd(false)}><X size={14} /></button>
            </div>
            <form onSubmit={addCamera}>
              <div className="modal-body">
                <div className="form-group">
                  <label className="form-label">Camera Name</label>
                  <input className="form-input" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Front Door" required />
                </div>
                <div className="form-group">
                  <label className="form-label">Source</label>
                  <input className="form-input" value={form.source} onChange={e => setForm(f => ({ ...f, source: e.target.value }))} placeholder="0 or rtsp://... or http://..." required />
                  <span className="text-xs text-muted">Use 0 for laptop webcam, or enter IP Webcam URL for phone cameras</span>
                </div>
                <button type="button" className="btn btn-ghost btn-sm" onClick={testSource} disabled={testing}>
                  {testing ? <span className="spinner" /> : <Wifi size={13} />}
                  Test Connection
                </button>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-ghost" onClick={() => setShowAdd(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={loading}>
                  {loading ? <span className="spinner" /> : <Check size={14} />}
                  Add Camera
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}
