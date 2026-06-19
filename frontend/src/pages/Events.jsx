import { useState, useEffect, useRef } from 'react'
import api from '../api/client'
import { ShieldAlert, Filter, Trash2, Eye, X, ImageOff, Search, ArrowUp, ArrowDown, ArrowRight, Minus } from 'lucide-react'
import { formatDateTime } from '../utils/time'
import { useAuthStore } from '../store/authStore'

const LEVELS = ['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
const OBJECT_TYPES = ['All', 'person', 'car', 'truck', 'bus', 'motorcycle']
const COLOR_CHIPS = ['red', 'blue', 'green', 'yellow', 'white', 'black', 'gray', 'orange', 'pink', 'purple', 'brown', 'navy']

export default function Events() {
  const [events, setEvents] = useState([])
  const [cameras, setCameras] = useState([])
  const [filterLevel, setFilterLevel] = useState('ALL')
  const [filterCam, setFilterCam] = useState('')
  const [filterObj, setFilterObj] = useState('All')
  const [filterColor, setFilterColor] = useState('')
  const [filterIdentity, setFilterIdentity] = useState('')
  const [filterDateFrom, setFilterDateFrom] = useState('')
  const [filterDateTo, setFilterDateTo] = useState('')
  const [searchText, setSearchText] = useState('')
  const [loading, setLoading] = useState(false)
  const [previewEvent, setPreviewEvent] = useState(null)
  const [useSearch, setUseSearch] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const hasAdvanced = searchText || filterColor || filterIdentity || filterDateFrom || filterDateTo || filterObj !== 'All'
      const endpoint = hasAdvanced ? '/events/search' : '/events'
      const params = {}
      if (filterLevel !== 'ALL') params.risk_level = filterLevel
      if (filterCam) params.camera_id = filterCam
      if (filterObj !== 'All') params.object_class = filterObj
      if (filterColor) params.color = filterColor
      if (filterIdentity) params.identity = filterIdentity
      if (filterDateFrom) params.date_from = filterDateFrom
      if (filterDateTo) params.date_to = filterDateTo
      if (searchText) params.q = searchText
      params.limit = 200
      const [evtRes, camRes] = await Promise.all([
        api.get(endpoint, { params }),
        api.get('/cameras'),
      ])
      setEvents(evtRes.data)
      setCameras(camRes.data)
    } catch {} finally { setLoading(false) }
  }

  useEffect(() => { load() }, [filterLevel, filterCam, filterObj, filterColor])

  const handleSearch = (e) => {
    e?.preventDefault()
    load()
  }

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

  const parseColors = (colorStr) => {
    if (!colorStr) return []
    try { return JSON.parse(colorStr) } catch { return [] }
  }

  const directionIcon = (dir) => {
    if (dir === 'entering') return <ArrowDown size={12} style={{ color: 'var(--warning)' }} />
    if (dir === 'exiting') return <ArrowUp size={12} style={{ color: 'var(--success)' }} />
    if (dir === 'crossing') return <ArrowRight size={12} style={{ color: 'var(--info, #4cc9f0)' }} />
    if (dir === 'stationary') return <Minus size={12} style={{ color: 'var(--text3)' }} />
    return null
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
        {/* Search Bar */}
        <form onSubmit={handleSearch} style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text3)' }} />
            <input
              type="text"
              className="form-input"
              placeholder="Search events... (e.g. red car, UNKNOWN, LOITERING)"
              value={searchText}
              onChange={e => setSearchText(e.target.value)}
              style={{ paddingLeft: 32, width: '100%' }}
            />
          </div>
          <button type="submit" className="btn btn-primary btn-sm">Search</button>
        </form>

        {/* Filters Row */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ display: 'flex', gap: 4 }}>
            {LEVELS.map(l => (
              <button
                key={l}
                className={`btn btn-sm ${filterLevel === l ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setFilterLevel(l)}
              >{l}</button>
            ))}
          </div>
          <select className="form-select" style={{ maxWidth: 150 }} value={filterCam} onChange={e => setFilterCam(e.target.value)}>
            <option value="">All cameras</option>
            {cameras.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <select className="form-select" style={{ maxWidth: 130 }} value={filterObj} onChange={e => setFilterObj(e.target.value)}>
            {OBJECT_TYPES.map(t => <option key={t} value={t}>{t === 'All' ? 'All objects' : t}</option>)}
          </select>
          {loading && <div className="spinner" />}
        </div>

        {/* Advanced Filters Row */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            type="text"
            className="form-input"
            placeholder="Identity..."
            value={filterIdentity}
            onChange={e => setFilterIdentity(e.target.value)}
            onBlur={load}
            style={{ maxWidth: 140 }}
          />
          <input type="date" className="form-input" value={filterDateFrom} onChange={e => { setFilterDateFrom(e.target.value); }} onBlur={load} style={{ maxWidth: 150 }} />
          <span style={{ color: 'var(--text3)', fontSize: 12 }}>to</span>
          <input type="date" className="form-input" value={filterDateTo} onChange={e => { setFilterDateTo(e.target.value); }} onBlur={load} style={{ maxWidth: 150 }} />

          {/* Color chips */}
          <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
            {COLOR_CHIPS.map(c => (
              <button
                key={c}
                onClick={() => setFilterColor(filterColor === c ? '' : c)}
                title={c}
                style={{
                  width: 20, height: 20, borderRadius: '50%',
                  background: c === 'navy' ? '#001f3f' : c,
                  border: filterColor === c ? '2px solid var(--primary)' : '2px solid transparent',
                  cursor: 'pointer', boxShadow: filterColor === c ? '0 0 0 2px var(--primary)' : 'none',
                  transition: 'box-shadow .15s',
                }}
              />
            ))}
            {filterColor && (
              <button className="btn btn-ghost btn-sm" onClick={() => setFilterColor('')} style={{ fontSize: 11 }}>
                ✕ {filterColor}
              </button>
            )}
          </div>
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
                <th>Colors</th>
                <th>Movement</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 ? (
                <tr><td colSpan={9} style={{ textAlign: 'center', padding: 32, color: 'var(--text3)' }}>No events found</td></tr>
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
                    <div style={{ display: 'flex', gap: 3 }}>
                      {parseColors(evt.dominant_colors).map((c, i) => (
                        <span
                          key={i}
                          title={c}
                          style={{
                            width: 14, height: 14, borderRadius: '50%',
                            background: c === 'navy' ? '#001f3f' : c,
                            border: '1px solid rgba(255,255,255,0.2)',
                            display: 'inline-block'
                          }}
                        />
                      ))}
                    </div>
                  </td>
                  <td className="text-sm">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      {directionIcon(evt.direction)}
                      <span>{evt.direction || '—'}</span>
                      {evt.speed_estimate && evt.speed_estimate !== 'stationary' && (
                        <span className="text-xs text-muted">({evt.speed_estimate})</span>
                      )}
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

  const parseColors = (colorStr) => {
    if (!colorStr) return []
    try { return JSON.parse(colorStr) } catch { return [] }
  }

  const parseDetails = (detailStr) => {
    if (!detailStr || detailStr === '{}') return null
    try { return JSON.parse(detailStr) } catch { return null }
  }

  const details = parseDetails(previewEvent.object_details)

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
          <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
            {[
              ['Risk Score', previewEvent.risk_score?.toFixed(3)],
              ['Risk Level', previewEvent.risk_level],
              ['Identity', previewEvent.identity],
              ['Object', `${previewEvent.object_class} (${(previewEvent.confidence * 100).toFixed(0)}%)`],
              ['Camera', previewEvent.camera_name || `Camera ${previewEvent.camera_id}`],
              ['Time', formatDateTime(previewEvent.timestamp)],
              ['Direction', previewEvent.direction || '—'],
              ['Speed', previewEvent.speed_estimate || '—'],
              ['Duration', previewEvent.duration_seconds ? `${previewEvent.duration_seconds.toFixed(1)}s` : '—'],
              ['FSM State', previewEvent.fsm_state || '—'],
            ].map(([k, v]) => (
              <div key={k} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 12px' }}>
                <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 2 }}>{k}</div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{v}</div>
              </div>
            ))}
            {/* Color dots */}
            <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 12px' }}>
              <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 4 }}>Colors</div>
              <div style={{ display: 'flex', gap: 4 }}>
                {parseColors(previewEvent.dominant_colors).map((c, i) => (
                  <span key={i} title={c} style={{
                    width: 18, height: 18, borderRadius: '50%',
                    background: c === 'navy' ? '#001f3f' : c,
                    border: '1px solid rgba(255,255,255,0.2)',
                    display: 'inline-block'
                  }} />
                ))}
                {parseColors(previewEvent.dominant_colors).length === 0 && <span style={{ fontSize: 13 }}>—</span>}
              </div>
            </div>
          </div>

          {/* Object details */}
          {details && (
            <div style={{ marginTop: 12, background: 'var(--bg2)', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 6 }}>Object Details</div>
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 13 }}>
                {Object.entries(details).map(([k, v]) => (
                  <div key={k}>
                    <span style={{ color: 'var(--text3)' }}>{k.replace(/_/g, ' ')}: </span>
                    <span style={{ fontWeight: 600 }}>
                      {Array.isArray(v) ? v.join(', ') || '—' : typeof v === 'boolean' ? (v ? '✓' : '✗') : String(v) || '—'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
