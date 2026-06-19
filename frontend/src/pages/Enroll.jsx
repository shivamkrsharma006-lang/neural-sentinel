import { useState, useEffect, useRef } from 'react'
import api from '../api/client'
import toast from 'react-hot-toast'
import { UserPlus, Trash2, Camera, Upload, CheckCircle, XCircle } from 'lucide-react'

export default function Enroll() {
  const [faces, setFaces] = useState([])
  const [frStatus, setFrStatus] = useState(null)
  const [name, setName] = useState('')
  const [photo, setPhoto] = useState(null)
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const videoRef = useRef(null)
  const streamRef = useRef(null)

  const load = async () => {
    try {
      const [facesRes, statusRes] = await Promise.all([
        api.get('/faces'),
        api.get('/faces/status'),
      ])
      setFaces(facesRes.data)
      setFrStatus(statusRes.data)
    } catch {}
  }

  useEffect(() => { load() }, [])

  const onFileChange = (e) => {
    const file = e.target.files[0]
    if (!file) return
    setPhoto(file)
    setPreview(URL.createObjectURL(file))
  }

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true })
      streamRef.current = stream
      videoRef.current.srcObject = stream
      setCapturing(true)
    } catch { toast.error('Cannot access camera') }
  }

  const captureFromCamera = () => {
    const video = videoRef.current
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d').drawImage(video, 0, 0)
    canvas.toBlob(blob => {
      const file = new File([blob], 'capture.jpg', { type: 'image/jpeg' })
      setPhoto(file)
      setPreview(URL.createObjectURL(blob))
      streamRef.current?.getTracks().forEach(t => t.stop())
      setCapturing(false)
    }, 'image/jpeg', 0.9)
  }

  const enroll = async (e) => {
    e.preventDefault()
    if (!name || !photo) { toast.error('Enter name and provide a photo'); return }
    setLoading(true)
    try {
      const fd = new FormData()
      fd.append('name', name)
      fd.append('photo', photo)
      await api.post('/faces', fd)
      toast.success(`${name} enrolled successfully!`)
      setName('')
      setPhoto(null)
      setPreview(null)
      load()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Enrollment failed')
    } finally { setLoading(false) }
  }

  const deleteFace = async (id) => {
    try {
      await api.delete(`/faces/${id}`)
      toast.success('Removed')
      load()
    } catch {}
  }

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Face Enrollment</div>
      </div>

      <div className="page-body">
        {/* Status banner */}
        {frStatus && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderRadius: 10, marginBottom: 20, background: frStatus.available ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)', border: `1px solid ${frStatus.available ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}` }}>
            {frStatus.available ? <CheckCircle size={18} color="var(--success)" /> : <XCircle size={18} color="var(--danger)" />}
            <span className="text-sm">{frStatus.message}</span>
            {!frStatus.available && (
              <code style={{ marginLeft: 8, background: 'var(--bg2)', padding: '2px 8px', borderRadius: 4, fontSize: 12 }}>
                pip install insightface onnxruntime
              </code>
            )}
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          {/* Enroll form */}
          <div className="card">
            <div className="card-title" style={{ marginBottom: 16 }}><UserPlus size={16} />Enroll New Person</div>
            <form onSubmit={enroll}>
              <div className="form-group">
                <label className="form-label">Full Name</label>
                <input className="form-input" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. John Doe" required />
              </div>

              {/* Photo options */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 16 }}>
                <label className="btn btn-ghost" style={{ cursor: 'pointer', justifyContent: 'center' }}>
                  <Upload size={14} />Upload Photo
                  <input type="file" accept="image/*" onChange={onFileChange} style={{ display: 'none' }} />
                </label>
                <button type="button" className="btn btn-ghost" onClick={capturing ? captureFromCamera : startCamera}>
                  <Camera size={14} />{capturing ? 'Capture!' : 'Use Camera'}
                </button>
              </div>

              {capturing && (
                <video ref={videoRef} autoPlay muted style={{ width: '100%', borderRadius: 8, marginBottom: 12, background: '#000' }} />
              )}

              {preview && !capturing && (
                <div style={{ marginBottom: 16, borderRadius: 8, overflow: 'hidden', border: '1px solid var(--border)' }}>
                  <img src={preview} alt="preview" style={{ width: '100%', display: 'block' }} />
                </div>
              )}

              <button type="submit" className="btn btn-primary w-full" disabled={loading || !frStatus?.available}>
                {loading ? <span className="spinner" /> : <UserPlus size={14} />}
                Enroll Person
              </button>
            </form>
          </div>

          {/* Enrolled list */}
          <div className="card">
            <div className="card-title" style={{ marginBottom: 16 }}>Enrolled Persons ({faces.length})</div>
            {faces.length === 0 ? (
              <div className="empty-state" style={{ padding: 24 }}>
                <div className="text-sm text-muted">No faces enrolled yet</div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {faces.map(f => (
                  <div key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', background: 'var(--bg2)', borderRadius: 8 }}>
                    <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'linear-gradient(135deg, var(--primary), var(--accent))', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 15, color: '#fff', flexShrink: 0 }}>
                      {f.name[0]?.toUpperCase()}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600 }}>{f.name}</div>
                      <div className="text-xs text-muted">{new Date(f.created_at).toLocaleDateString()}</div>
                    </div>
                    <button className="btn btn-danger btn-sm" onClick={() => deleteFace(f.id)}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Instructions */}
        <div className="card" style={{ marginTop: 20 }}>
          <div className="card-title" style={{ marginBottom: 12 }}>📸 Tips for Good Enrollment</div>
          <ul style={{ fontSize: 13, color: 'var(--text2)', display: 'flex', flexDirection: 'column', gap: 6, paddingLeft: 16 }}>
            <li>Use a clear frontal photo with good lighting</li>
            <li>Face should occupy at least 50% of the frame</li>
            <li>Avoid sunglasses, hats, or face coverings</li>
            <li>Enrolled persons appearing in camera zones will receive auth score 1.0 (reduced risk)</li>
            <li>Unknown persons receive auth score 0.0 (full threat score)</li>
          </ul>
        </div>
      </div>
    </>
  )
}
