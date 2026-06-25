import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import api from '../api/client'
import toast from 'react-hot-toast'
import { ArrowLeft, Plus, Trash2, Save, RotateCcw, Minus } from 'lucide-react'
import { useAuthStore } from '../store/authStore'

const ZONE_COLORS = {
  polygon: '#f97316',
  tripwire: '#3b82f6',
  speedgate: '#22c55e',
}

export default function ZoneEditor() {
  const token = useAuthStore((s) => s.token)
  const { cameraId } = useParams()
  const navigate = useNavigate()
  const canvasRef = useRef(null)
  const [snapshot, setSnapshot] = useState(null)
  const [zones, setZones] = useState([])
  const [drawing, setDrawing] = useState(false)
  const [currentPoints, setCurrentPoints] = useState([])
  const [tool, setTool] = useState('polygon')  // polygon | tripwire | speedgate
  const [form, setForm] = useState({
    name: '', dwell_time: 5, crowd_limit: 0,
    direction: 'any', speed_limit: 5, class_filter: 'person',
    arming_enabled: false, arming_start: '08:00', arming_end: '20:00',
  })
  const imgRef = useRef(null)
  const [imgSize, setImgSize] = useState({ w: 640, h: 360 })

  const [snapshotError, setSnapshotError] = useState(false)

  const loadZones = useCallback(async () => {
    try {
      const { data } = await api.get(`/cameras/${cameraId}/zones`)
      setZones(data)
    } catch {}
  }, [cameraId])

  useEffect(() => {
    setSnapshot(`/snapshot/${cameraId}?token=${token}&t=${Date.now()}`)
    setSnapshotError(false)
    loadZones()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, token])  // loadZones excluded — stable identity via useCallback on cameraId

  const redrawCanvas = useCallback(() => {
    const canvas = canvasRef.current
    const img = imgRef.current
    if (!canvas || !img) return
    const ctx = canvas.getContext('2d')
    const w = canvas.width
    const h = canvas.height
    ctx.clearRect(0, 0, w, h)
    ctx.drawImage(img, 0, 0, w, h)

    // Draw saved zones
    zones.forEach(zone => {
      try {
        const pts = JSON.parse(zone.points_json).map(p => ({ x: p.x * w, y: p.y * h }))
        const color = ZONE_COLORS[zone.zone_type] || '#fff'
        ctx.strokeStyle = color
        ctx.lineWidth = 2
        ctx.fillStyle = color + '33'
        if (zone.zone_type === 'polygon' && pts.length >= 2) {
          ctx.beginPath()
          ctx.moveTo(pts[0].x, pts[0].y)
          pts.forEach(p => ctx.lineTo(p.x, p.y))
          ctx.closePath()
          ctx.fill()
          ctx.stroke()
        } else if (pts.length >= 2) {
          ctx.beginPath()
          ctx.moveTo(pts[0].x, pts[0].y)
          ctx.lineTo(pts[1].x, pts[1].y)
          ctx.stroke()
          // Arrow
          const mx = (pts[0].x + pts[1].x) / 2
          const my = (pts[0].y + pts[1].y) / 2
          ctx.beginPath()
          ctx.moveTo(mx, my)
          ctx.lineTo(mx + 15, my)
          ctx.stroke()
        }
        // Label
        ctx.fillStyle = color
        ctx.font = '12px Inter'
        ctx.fillText(zone.name, (pts[0]?.x || 0) + 4, (pts[0]?.y || 0) - 4)
      } catch {}
    })

    // Draw current in-progress points
    if (currentPoints.length > 0) {
      const color = ZONE_COLORS[tool] || '#fff'
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.setLineDash([5, 5])
      ctx.beginPath()
      ctx.moveTo(currentPoints[0].x, currentPoints[0].y)
      currentPoints.forEach(p => ctx.lineTo(p.x, p.y))
      ctx.stroke()
      ctx.setLineDash([])
      currentPoints.forEach((p, i) => {
        ctx.fillStyle = i === 0 ? '#fff' : color
        ctx.beginPath()
        ctx.arc(p.x, p.y, 5, 0, Math.PI * 2)
        ctx.fill()
      })
    }
  }, [zones, currentPoints, tool])

  // Draw placeholder when no snapshot is available (system disarmed)
  const drawPlaceholder = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#0a0f1a'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.fillStyle = '#334155'
    ctx.font = 'bold 15px Inter, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('📷 Arm the system to load a live snapshot', canvas.width / 2, canvas.height / 2 - 12)
    ctx.font = '12px Inter, sans-serif'
    ctx.fillStyle = '#475569'
    ctx.fillText('You can still draw zones — they will be saved and applied when armed.', canvas.width / 2, canvas.height / 2 + 14)
    ctx.textAlign = 'left'
  }, [])

  useEffect(() => {
    if (snapshotError) drawPlaceholder()
    else redrawCanvas()
  }, [redrawCanvas, snapshotError, drawPlaceholder])

  const canvasClick = (e) => {
    const canvas = canvasRef.current
    const rect = canvas.getBoundingClientRect()
    const x = (e.clientX - rect.left) * (canvas.width / rect.width)
    const y = (e.clientY - rect.top) * (canvas.height / rect.height)
    const newPts = [...currentPoints, { x, y }]
    setCurrentPoints(newPts)
    setDrawing(true)

    // Auto-finish tripwire/speedgate at 2 points
    if ((tool === 'tripwire' || tool === 'speedgate') && newPts.length === 2) {
      finishZone(newPts)
    }
  }

  const canvasDblClick = () => {
    if (tool === 'polygon' && currentPoints.length >= 3) {
      finishZone(currentPoints)
    }
  }

  const finishZone = async (pts) => {
    if (!form.name) {
      toast.error('Enter a zone name first')
      return
    }
    const w = canvasRef.current.width
    const h = canvasRef.current.height
    const normalized = pts.map(p => ({ x: +(p.x / w).toFixed(4), y: +(p.y / h).toFixed(4) }))

    const config = {
      dwell_time: Number(form.dwell_time),
      crowd_limit: Number(form.crowd_limit),
      direction: form.direction,
      speed_limit: Number(form.speed_limit),
      class_filter: form.class_filter,
      arming_schedule: form.arming_enabled
        ? { enabled: true, start_time: form.arming_start, end_time: form.arming_end, days: [] }
        : { enabled: false },
    }

    try {
      await api.post(`/cameras/${cameraId}/zones`, {
        name: form.name,
        zone_type: tool,
        points_json: JSON.stringify(normalized),
        config_json: JSON.stringify(config),
      })
      toast.success(`Zone "${form.name}" saved!`)
      setCurrentPoints([])
      setDrawing(false)
      loadZones()
    } catch (err) { toast.error('Failed to save zone') }
  }

  const deleteZone = async (zoneId) => {
    try {
      await api.delete(`/cameras/${cameraId}/zones/${zoneId}`)
      toast.success('Zone deleted')
      loadZones()
    } catch { toast.error('Failed') }
  }

  const toggleZone = async (zoneId) => {
    try {
      await api.patch(`/cameras/${cameraId}/zones/${zoneId}/toggle`)
      loadZones()
    } catch {}
  }

  return (
    <>
      <div className="topbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => navigate('/cameras')}>
            <ArrowLeft size={14} />Back
          </button>
          <div className="topbar-title">Zone Editor — Camera {cameraId}</div>
        </div>
      </div>

      <div className="page-body" style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20 }}>
        {/* Canvas */}
        <div>
          <div className="zone-editor-wrap">
            {snapshot && !snapshotError && (
              <img
                ref={imgRef}
                src={snapshot}
                alt="snapshot"
                style={{ display: 'none' }}
                onLoad={() => {
                  const img = imgRef.current
                  const canvas = canvasRef.current
                  if (img && canvas) {
                    canvas.width = img.naturalWidth || 640
                    canvas.height = img.naturalHeight || 360
                    setImgSize({ w: canvas.width, h: canvas.height })
                    redrawCanvas()
                  }
                }}
                onError={() => {
                  setSnapshotError(true)
                  drawPlaceholder()
                }}
              />
            )}
            <canvas
              ref={canvasRef}
              className="zone-canvas"
              width={640}
              height={360}
              onClick={canvasClick}
              onDoubleClick={canvasDblClick}
              style={{ cursor: 'crosshair' }}
            />
          </div>

          <div className="card" style={{ marginTop: 12 }}>
            <div style={{ fontSize: 12, color: 'var(--text2)' }}>
              {tool === 'polygon'
                ? '🖊 Click to add points. Double-click to close the polygon.'
                : '🖊 Click two points to draw the line.'}
            </div>
          </div>
        </div>

        {/* Controls */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* Tool picker */}
          <div className="card">
            <div className="card-title" style={{ marginBottom: 12 }}>Zone Type</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {['polygon', 'tripwire', 'speedgate'].map(t => (
                <button
                  key={t}
                  className={`btn ${tool === t ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => { setTool(t); setCurrentPoints([]) }}
                >
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: ZONE_COLORS[t], flexShrink: 0 }} />
                  {t === 'polygon' ? '⬡ Polygon Zone' : t === 'tripwire' ? '→ Tripwire' : '⚡ Speed Gate'}
                </button>
              ))}
            </div>
          </div>

          {/* Zone config */}
          <div className="card">
            <div className="card-title" style={{ marginBottom: 12 }}>Zone Settings</div>
            <div className="form-group">
              <label className="form-label">Zone Name *</label>
              <input className="form-input" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. Restricted Area" />
            </div>
            <div className="form-group">
              <label className="form-label">Class Filter</label>
              <select className="form-select" value={form.class_filter} onChange={e => setForm(f => ({ ...f, class_filter: e.target.value }))}>
                <option value="person">Person</option>
                <option value="car">Car</option>
                <option value="all">All objects</option>
              </select>
            </div>
            {tool === 'polygon' && (
              <>
                <div className="form-group">
                  <label className="form-label">Dwell Time (seconds)</label>
                  <input className="form-input" type="number" min={1} value={form.dwell_time} onChange={e => setForm(f => ({ ...f, dwell_time: e.target.value }))} />
                </div>
                <div className="form-group">
                  <label className="form-label">Crowd Limit (0 = disabled)</label>
                  <input className="form-input" type="number" min={0} value={form.crowd_limit} onChange={e => setForm(f => ({ ...f, crowd_limit: e.target.value }))} />
                </div>
              </>
            )}
            {tool === 'tripwire' && (
              <div className="form-group">
                <label className="form-label">Direction</label>
                <select className="form-select" value={form.direction} onChange={e => setForm(f => ({ ...f, direction: e.target.value }))}>
                  <option value="any">Any direction</option>
                  <option value="forward">Forward only</option>
                  <option value="backward">Backward only</option>
                </select>
              </div>
            )}
            {tool === 'speedgate' && (
              <div className="form-group">
                <label className="form-label">Speed Limit (m/s)</label>
                <input className="form-input" type="number" min={1} value={form.speed_limit} onChange={e => setForm(f => ({ ...f, speed_limit: e.target.value }))} />
              </div>
            )}
            <div className="form-group">
              <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input type="checkbox" checked={form.arming_enabled} onChange={e => setForm(f => ({ ...f, arming_enabled: e.target.checked }))} />
                Arming Schedule
              </label>
            </div>
            {form.arming_enabled && (
              <div className="grid-2">
                <div className="form-group">
                  <label className="form-label">Start</label>
                  <input className="form-input" type="time" value={form.arming_start} onChange={e => setForm(f => ({ ...f, arming_start: e.target.value }))} />
                </div>
                <div className="form-group">
                  <label className="form-label">End</label>
                  <input className="form-input" type="time" value={form.arming_end} onChange={e => setForm(f => ({ ...f, arming_end: e.target.value }))} />
                </div>
              </div>
            )}
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-ghost btn-sm" onClick={() => setCurrentPoints([])}>
                <RotateCcw size={13} />Clear
              </button>
              {tool === 'polygon' && currentPoints.length >= 3 && (
                <button className="btn btn-primary btn-sm" onClick={() => finishZone(currentPoints)}>
                  <Save size={13} />Save Zone
                </button>
              )}
            </div>
          </div>

          {/* Existing zones */}
          <div className="card">
            <div className="card-title" style={{ marginBottom: 12 }}>Saved Zones ({zones.length})</div>
            {zones.length === 0
              ? <div className="text-sm text-muted">No zones yet</div>
              : zones.map(z => (
                <div key={z.id} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, padding: '6px 10px', background: 'var(--bg2)', borderRadius: 8, borderLeft: `3px solid ${ZONE_COLORS[z.zone_type] || '#999'}` }}>
                  <span style={{ flex: 1, fontSize: 13, fontWeight: 500 }}>{z.name}</span>
                  <span style={{ fontSize: 11, color: 'var(--text3)' }}>{z.zone_type}</span>
                  <button className="btn btn-ghost btn-sm" onClick={() => toggleZone(z.id)} style={{ padding: '2px 6px', fontSize: 11 }}>
                    {z.active ? '●' : '○'}
                  </button>
                  <button className="btn btn-danger btn-sm" onClick={() => deleteZone(z.id)} style={{ padding: '4px' }}>
                    <Trash2 size={12} />
                  </button>
                </div>
              ))
            }
          </div>
        </div>
      </div>
    </>
  )
}
