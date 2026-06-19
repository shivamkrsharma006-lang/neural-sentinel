import { useState, useEffect, useRef } from 'react'
import api from '../api/client'
import { ShieldAlert, Filter, Trash2, Eye, X, ImageOff } from 'lucide-react'
import { formatDateTime } from '../utils/time'
import { useAuthStore } from '../store/authStore'

const LEVELS = ['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

export default function Events() {
  const [events, setEvents] = useState([])
  const [cameras, setCameras] = useState([])
  const [filterLevel, setFilterLevel] = useState('ALL')
  const [filterCam, setFilterCam] = useState('')
  const [loading, setLoading] = useState(false)
  const [previewEvent, setPreviewEvent] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const params = {}
      if (filterLevel !== 'ALL') params.risk_level = filterLevel
      if (filterCam) params.camera_id = filterCam
      params.limit = 200
      const [evtRes, camRes] = await Promise.all([
        api.get('/events', { params }),
        api.get('/cameras'),
      ])
      setEvents(evtRes.data)
      setCameras(camRes.data)
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { load() }, [filterLevel, filterCam])

  const deleteEvent = async (id) => {
    try {
      await api.delete(`/events/${id}`)
      setEvents(e => e.filter(ev => ev.id !== id))
    } catch {}
  }

  const clearAll = async () => {
    if (!confirm('Clear all visible events?')) return
    try {
      const params = {}
      if (filterCam) params.camera_id = filterCam
      await api.delete('/events', { params })
      load()
    } catch {}
  }

  const levelBadge = (level) => {
    const cls = { CRITICAL: 'badge-critical', HIGH: 'badge-high', MEDIUM: 'badge-medium', LOW: 'badge-low' }
    return <span className={`badge ${cls[level] || 'badge-low'}`}>{level}</span>
  }

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Events Log</div>
        <div className="topbar-right">
          <button className="btn btn-danger btn-sm" onClick={clearAll}><Trash2 size={13} />Clear</button>
        </div>
      </div>

      <div className="page-body">
        {/* Filters */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 4 }}>
            {LEVELS.map(l => (
              <button
                key={l}
                className={`btn btn-sm ${filterLevel === l ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setFilterLevel(l)}
              >{l}</button>
            ))}
          </div>
          <select className="form-select" style={{ maxWidth: 180 }} value={filterCam} onChange={e => setFilterCam(e.target.value)}>
            <option value="">All cameras</option>
            {cameras.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          {loading && <div className="spinner" />}
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Camera</th>
                <th>Event</th>
                <th>Object</th>
                <th>Identity</th>
                <th>Risk</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 ? (
                <tr><td colSpan={7} style={{ textAlign: 'center', padding: 32, color: 'var(--text3)' }}>No events found</td></tr>
              ) : events.map(evt => (
                <tr key={evt.id}>
                  <td className="text-mono text-sm">{formatDateTime(evt.timestamp)}</td>
                  <td>{evt.camera_name || `Cam ${evt.camera_id}`}</td>
                  <td style={{ fontWeight: 600 }}>{evt.event_type}</td>
                  <td className="text-sm">{evt.object_class} ({(evt.confidence * 100).toFixed(0)}%)</td>
                  <td className="text-sm" style={{ color: evt.identity === 'UNKNOWN' ? 'var(--danger)' : 'var(--success)' }}>
                    {evt.identity}
                  </td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {levelBadge(evt.risk_level)}
                      <span className="text-mono text-xs text-muted">{evt.risk_score?.toFixed(2)}</span>
                    </div>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 4 }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => setPreviewEvent(evt)} title="View frame">
                        <Eye size={13} />
                      </button>
                      <button className="btn btn-danger btn-sm" onClick={() => deleteEvent(evt.id)}>
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="text-sm text-muted" style={{ marginTop: 8 }}>{events.length} events shown</div>
      </div>

      {/* Evidence Frame Modal */}
      {previewEvent && (
        <FrameModal event={previewEvent} onClose={() => setPreviewEvent(null)} />
      )}
    </>
  )
}

function FrameModal({ event: previewEvent, onClose }) {
  const [imgFailed, setImgFailed] = useState(false)
  const { token } = useAuthStore()
  
  // Reset on each new event
  useEffect(() => { setImgFailed(false) }, [previewEvent?.id])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 720 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">Evidence Frame — {previewEvent.event_type}</div>
          <div style={{ display: 'flex', gap: 8 }}>
            {!imgFailed && (
              <a
                href={`/api/events/${previewEvent.id}/frame/save?token=${token}`}
                className="btn btn-primary btn-sm"
                download
                title="Save frame to disk"
              >
                💾 Save
              </a>
            )}
            <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={14} /></button>
          </div>
        </div>
        <div className="modal-body">
          {imgFailed ? (
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              justifyContent: 'center', gap: 10, padding: '40px 20px',
              background: 'var(--bg2)', borderRadius: 8, color: 'var(--text3)'
            }}>
              <ImageOff size={40} opacity={0.4} />
              <div style={{ fontSize: 13, fontWeight: 600 }}>No frame available</div>
              <div style={{ fontSize: 11, textAlign: 'center', maxWidth: 300 }}>
                This event was recorded before frame persistence was enabled,
                or the frame file was removed. New events always save to disk.
              </div>
            </div>
          ) : (
            <img
              src={`/api/events/${previewEvent.id}/frame?token=${token}`}
              alt="evidence"
              style={{ width: '100%', borderRadius: 8, background: '#000', display: 'block' }}
              onError={() => setImgFailed(true)}
            />
          )}
          <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {[
              ['Risk Score', previewEvent.risk_score?.toFixed(3)],
              ['Risk Level', previewEvent.risk_level],
              ['Identity', previewEvent.identity],
              ['Object', `${previewEvent.object_class} (${(previewEvent.confidence * 100).toFixed(0)}%)`],
              ['Camera', previewEvent.camera_name || `Camera ${previewEvent.camera_id}`],
              ['Time', formatDateTime(previewEvent.timestamp)],
            ].map(([k, v]) => (
              <div key={k} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 12px' }}>
                <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 2 }}>{k}</div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{v}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
