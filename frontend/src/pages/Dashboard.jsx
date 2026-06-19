import { useEffect, useState, useRef, useCallback } from 'react'
import api from '../api/client'
import { useAuthStore } from '../store/authStore'
import { ShieldAlert, Camera, Eye, Activity, Wifi, WifiOff, Power, X, ChevronLeft, ChevronRight, Maximize2, Minimize2 } from 'lucide-react'
import EventFeed from '../components/EventFeed'

// Module-level WS singleton — survives React StrictMode double-mount
// without creating duplicate connections or reconnect storms.
let _wsInstance = null
let _wsListeners = []

function getOrCreateWS(token, onMessage) {
  // Reuse existing healthy connection
  if (_wsInstance && _wsInstance.readyState === WebSocket.OPEN) {
    _wsListeners.push(onMessage)
    return () => { _wsListeners = _wsListeners.filter(l => l !== onMessage) }
  }
  // Close any stale socket
  if (_wsInstance) {
    try { _wsInstance.close() } catch (_) {}
    _wsInstance = null
  }
  _wsListeners = [onMessage]
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/events?token=${token}`)
  _wsInstance = ws
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      _wsListeners.forEach(fn => fn(msg))
    } catch (_) {}
  }
  ws.onclose = () => {
    if (_wsInstance === ws) _wsInstance = null
  }
  ws.onerror = () => {
    if (_wsInstance === ws) _wsInstance = null
  }
  return () => { _wsListeners = _wsListeners.filter(l => l !== onMessage) }
}

export default function Dashboard() {
  const { token } = useAuthStore()
  const [cameras, setCameras] = useState([])
  const [events, setEvents] = useState([])
  const [stats, setStats] = useState({ total: 0, critical: 0, high: 0, cameras_online: 0 })
  const [v4Stats, setV4Stats] = useState(null)
  const [liveEvents, setLiveEvents] = useState([])
  const [isArmed, setIsArmed] = useState(null)
  const [sysLoading, setSysLoading] = useState(false)
  const [isSurveillance, setIsSurveillance] = useState(false)
  const [fullscreenCamIdx, setFullscreenCamIdx] = useState(null)

  const handlePrevCamera = useCallback((e) => {
    if (e) e.stopPropagation()
    setFullscreenCamIdx(prev => (prev === 0 ? cameras.length - 1 : prev - 1))
  }, [cameras.length])

  const handleNextCamera = useCallback((e) => {
    if (e) e.stopPropagation()
    setFullscreenCamIdx(prev => (prev === cameras.length - 1 ? 0 : prev + 1))
  }, [cameras.length])

  const fetchData = useCallback(async () => {
    try {
      const today = new Date().toISOString().slice(0, 10)
      const [camRes, evtRes, sysRes, statsRes] = await Promise.all([
        api.get('/cameras'),
        api.get('/events?limit=50'),
        api.get('/system/status'),
        api.get('/events/stats', { params: { date_from: today } }).catch(() => ({ data: null })),
      ])
      setCameras(camRes.data)
      setEvents(evtRes.data)
      setIsArmed(sysRes.data.armed)
      if (statsRes.data) setV4Stats(statsRes.data)
      const evts = evtRes.data
      setStats({
        total: evts.length,
        critical: evts.filter(e => e.risk_level === 'CRITICAL').length,
        high: evts.filter(e => e.risk_level === 'HIGH').length,
        cameras_online: camRes.data.filter(c => c.status === 'online').length,
      })
    } catch (e) {
      console.error("Failed to fetch system status", e)
    }
  }, [])

  const toggleArm = async () => {
    if (isArmed === null || sysLoading) return
    setSysLoading(true)
    try {
      const endpoint = isArmed ? '/system/disarm' : '/system/arm'
      console.log(`Sending ${isArmed ? 'DISARM' : 'ARM'} command...`)
      const { data } = await api.post(endpoint)
      console.log("System response:", data)
      setIsArmed(data.armed)
    } catch (e) {
      console.error("Toggle failed", e)
    } finally {
      setSysLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000)

    // WebSocket — module-level singleton survives React StrictMode double-mount
    const removeListener = getOrCreateWS(token, (msg) => {
      if (msg.type === 'violation') {
        setLiveEvents(prev => [msg, ...prev].slice(0, 20))
        setStats(s => ({
          ...s,
          total: s.total + 1,
          critical: msg.risk_level === 'CRITICAL' ? s.critical + 1 : s.critical,
          high: msg.risk_level === 'HIGH' ? s.high + 1 : s.high,
        }))
      }
    })

    return () => {
      clearInterval(interval)
      removeListener()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])  // fetchData intentionally excluded — it never changes identity meaningfully

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (fullscreenCamIdx !== null) {
        if (e.key === 'Escape') {
          setFullscreenCamIdx(null)
        } else if (e.key === 'ArrowLeft') {
          handlePrevCamera()
        } else if (e.key === 'ArrowRight') {
          handleNextCamera()
        }
      } else if (isSurveillance) {
        if (e.key === 'Escape') {
          setIsSurveillance(false)
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [fullscreenCamIdx, isSurveillance, handlePrevCamera, handleNextCamera])

  const gridClass = cameras.length === 1 ? 'n1' : cameras.length === 2 ? 'n2' : cameras.length === 3 ? 'n3' : 'n4'

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Live Dashboard</div>
        <div className="topbar-right" style={{ display: 'flex', gap: 10 }}>
          <button 
            className="btn btn-sm btn-ghost" 
            onClick={() => setIsSurveillance(true)}
            disabled={cameras.length === 0}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
            title="Enter full-screen surveillance grid"
          >
            <Maximize2 size={14} />
            Surveillance Mode
          </button>

          <button 
            className={`btn btn-sm ${isArmed === true ? 'btn-success' : 'btn-ghost'}`} 
            onClick={toggleArm}
            disabled={isArmed === null || sysLoading}
            style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: 6, 
              opacity: (isArmed === null || sysLoading) ? 0.5 : 1,
              minWidth: 140,
              justifyContent: 'center'
            }}
          >
            {sysLoading ? <div className="spinner" style={{ width: 12, height: 12 }} /> : (isArmed === true ? <Activity size={14} /> : <ShieldAlert size={14} />)}
            {isArmed === null ? 'Connecting...' : (isArmed === true ? 'System Armed' : 'System Disarmed')}
          </button>
        </div>
      </div>

      <div className="page-body">
        {/* Sleek Horizontal Metrics Row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
          <div className="stat-card danger" style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div className="stat-label" style={{ fontSize: 10, letterSpacing: 0.5 }}>Critical Events</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--danger)', fontFamily: 'var(--font-mono)' }}>{stats.critical}</div>
          </div>
          <div className="stat-card warning" style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div className="stat-label" style={{ fontSize: 10, letterSpacing: 0.5 }}>High Risk Events</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--warning)', fontFamily: 'var(--font-mono)' }}>{stats.high}</div>
          </div>
          <div className="stat-card primary" style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div className="stat-label" style={{ fontSize: 10, letterSpacing: 0.5 }}>Active Detections</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--primary)', fontFamily: 'var(--font-mono)' }}>{stats.total}</div>
          </div>
          <div className="stat-card success" style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div className="stat-label" style={{ fontSize: 10, letterSpacing: 0.5 }}>Cameras Online</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--success)', fontFamily: 'var(--font-mono)' }}>{stats.cameras_online}/{cameras.length}</div>
          </div>
        </div>

        {/* Camera Grid + Live Events — Main Prominent Layout */}
        <div style={{ display: 'grid', gridTemplateColumns: cameras.length > 0 ? '1fr 340px' : '1fr', gap: 16, alignItems: 'start' }}>
          {/* Camera Grid */}
          <div>
            {cameras.length === 0 ? (
              <div className="card">
                <div className="empty-state">
                  <Camera size={48} />
                  <div style={{ fontSize: 16, fontWeight: 600 }}>No cameras configured</div>
                  <div className="text-muted">Go to Cameras to add your first camera</div>
                </div>
              </div>
            ) : (
              <div className={`camera-grid ${gridClass}`}>
                {cameras.slice(0, 4).map((cam, idx) => (
                  <CameraCell 
                    key={cam.id} 
                    camera={cam} 
                    index={idx + 1} 
                    liveEvents={liveEvents} 
                    isArmed={isArmed} 
                    onClick={() => setFullscreenCamIdx(idx)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Live Event Feed */}
          {cameras.length > 0 && (
            <div className="card" style={{ position: 'sticky', top: 80 }}>
              <div className="card-header">
                <div className="card-title"><ShieldAlert size={16} />Live Events</div>
                <span className="badge badge-critical" style={{ fontSize: 10 }}>LIVE</span>
              </div>
              <EventFeed events={liveEvents.length > 0 ? liveEvents : events.slice(0, 15)} />
            </div>
          )}
        </div>

        {/* Analytics Section — Positioned below the streams */}
        {v4Stats && (
          <div className="card" style={{ marginTop: 20, padding: '16px 20px' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', marginBottom: 14, display: 'flex', alignItems: 'center', gap: 6 }}>
              <Activity size={14} color="var(--primary)" /> System Activity & Metrics Summary
            </div>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 24, alignItems: 'center' }}>
              {/* Chart */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 11, color: 'var(--text2)' }}>Hourly Detection Frequency</span>
                  {v4Stats.total_events === 0 && <span style={{ fontSize: 11, color: 'var(--danger)' }}>No activity recorded today</span>}
                </div>
                
                <div className="activity-bar-container">
                  {Object.entries(v4Stats.hourly_activity || {}).map(([hour, count]) => {
                    const maxVal = Math.max(1, ...Object.values(v4Stats.hourly_activity || {}))
                    const pct = (count / maxVal) * 100
                    const isNow = parseInt(hour) === new Date().getHours()
                    
                    let barColor = 'rgba(255, 255, 255, 0.04)'
                    if (count > 0) {
                      barColor = isNow ? 'var(--accent)' : 'var(--primary)'
                    } else if (isNow) {
                      barColor = 'rgba(34, 211, 238, 0.15)'
                    }
                    
                    return (
                      <div
                        key={hour}
                        className="activity-bar"
                        data-tooltip={`${hour}:00 — ${count} event${count === 1 ? '' : 's'}`}
                        style={{
                          height: `${Math.max(4, pct)}%`,
                          background: barColor,
                        }}
                      />
                    )
                  })}
                </div>
                
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
                  {['00:00', '04:00', '08:00', '12:00', '16:00', '20:00', '23:00'].map(lbl => (
                    <span key={lbl} style={{ fontSize: 9, color: 'var(--text3)', fontFamily: 'var(--font-mono)' }}>{lbl}</span>
                  ))}
                </div>
              </div>

              {/* Metrics list */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ background: 'rgba(255,255,255,0.02)', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border2)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, color: 'var(--text2)' }}>Persons Detected</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--primary)' }}>
                    {v4Stats.total_persons} <span style={{ fontSize: 9, fontWeight: 400, color: 'var(--text3)' }}>({v4Stats.known_persons} K / {v4Stats.unknown_persons} U)</span>
                  </span>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.02)', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border2)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, color: 'var(--text2)' }}>Vehicles Tracked</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)' }}>{v4Stats.total_vehicles}</span>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.02)', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border2)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, color: 'var(--text2)' }}>High Risk Events</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--danger)' }}>{v4Stats.alerts_triggered}</span>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.02)', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border2)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, color: 'var(--text2)' }}>Peak Hour</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--warning)' }}>{v4Stats.peak_hour ? `${v4Stats.peak_hour}:00` : '—'}</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Surveillance Overlay Grid */}
      {isSurveillance && (
        <div className="surveillance-overlay">
          <button className="exit-surveillance-btn" onClick={() => setIsSurveillance(false)}>
            <Minimize2 size={13} /> Exit Surveillance
          </button>
          <div className={`camera-grid ${gridClass}`} style={{ flex: 1 }}>
            {cameras.slice(0, 4).map((cam, idx) => (
              <CameraCell 
                key={cam.id} 
                camera={cam} 
                index={idx + 1} 
                liveEvents={liveEvents} 
                isArmed={isArmed} 
                onClick={() => setFullscreenCamIdx(idx)} 
              />
            ))}
          </div>
        </div>
      )}

      {/* Fullscreen stream detail zoom view */}
      {fullscreenCamIdx !== null && cameras[fullscreenCamIdx] && (
        <div className="fullscreen-stream-overlay">
          <button className="fullscreen-close-btn" onClick={() => setFullscreenCamIdx(null)} title="Close (Esc)">
            <X size={20} />
          </button>
          
          <div className="fullscreen-nav-zone left" onClick={handlePrevCamera} title="Previous Camera (Left Arrow)">
            <ChevronLeft size={36} className="nav-arrow" />
          </div>

          <div className="fullscreen-stream-container">
            <img
              src={`/stream/${cameras[fullscreenCamIdx].id}`}
              alt={cameras[fullscreenCamIdx].name}
              className="fullscreen-stream-feed"
              onError={(e) => { e.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><rect fill="%23111827" width="640" height="360"/><text fill="%23475569" font-family="Inter" font-size="18" x="50%" y="50%" text-anchor="middle" dy=".3em">No Signal</text></svg>' }}
            />
            
            <div className="fullscreen-stream-info">
              <div className={`camera-status-dot ${(isArmed === false || cameras[fullscreenCamIdx].status === 'disabled') ? 'offline' : cameras[fullscreenCamIdx].status}`} />
              <h3>Camera {fullscreenCamIdx + 1}: {cameras[fullscreenCamIdx].name}</h3>
            </div>
          </div>

          <div className="fullscreen-nav-zone right" onClick={handleNextCamera} title="Next Camera (Right Arrow)">
            <ChevronRight size={36} className="nav-arrow" />
          </div>
        </div>
      )}
    </>
  )
}

function CameraCell({ camera, index, liveEvents, isArmed, onClick }) {
  const [alertLevel, setAlertLevel] = useState(null)
  const [camEnabled, setCamEnabled] = useState(camera.status !== 'disabled')
  const [toggling, setToggling] = useState(false)
  const imgRef = useRef(null)

  useEffect(() => {
    const camEvent = liveEvents.find(e => e.camera_id === camera.id)
    if (camEvent) {
      setAlertLevel(camEvent.risk_level)
      const t = setTimeout(() => setAlertLevel(null), 5000)
      return () => clearTimeout(t)
    }
  }, [liveEvents, camera.id])

  // Force-reload the img connection when armed/enabled state changes
  useEffect(() => {
    if (imgRef.current) {
      if (isArmed === true && camEnabled) {
        imgRef.current.src = `/stream/${camera.id}`
      } else {
        imgRef.current.src = ''
      }
    }
  }, [isArmed, camEnabled, camera.id])

  const toggleCamera = async () => {
    if (toggling) return
    setToggling(true)
    try {
      const endpoint = camEnabled
        ? `/cameras/${camera.id}/pause`
        : `/cameras/${camera.id}/resume`
      await api.post(endpoint)
      setCamEnabled(prev => !prev)
    } catch (e) {
      console.error('Camera toggle failed', e)
    } finally {
      setToggling(false)
    }
  }

  const isOff = isArmed === false || !camEnabled
  const cellClass = `camera-cell${alertLevel === 'CRITICAL' ? ' threat' : alertLevel === 'HIGH' ? ' warning' : ''}`
  const displayLabel = `Camera ${index} — ${camera.name}`

  return (
    <div className={cellClass} onClick={onClick} style={{ cursor: 'pointer' }}>
      {isOff ? (
        <div style={{
          width: '100%', height: '100%',
          background: '#080c14',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          gap: 8, color: '#334155'
        }}>
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M15 10l4.55-2.27A1 1 0 0121 8.7V17a1 1 0 01-1.55.83L15 15M3 8a2 2 0 012-2h10a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8z"/>
            <line x1="1" y1="1" x2="23" y2="23" stroke="currentColor" strokeWidth="1.5"/>
          </svg>
          <span style={{ fontSize: 12, fontWeight: 600, letterSpacing: 1, textTransform: 'uppercase' }}>
            {!camEnabled ? 'Camera Disabled' : 'Disarmed'}
          </span>
        </div>
      ) : (
        <img
          ref={imgRef}
          className="camera-feed"
          src={`/stream/${camera.id}`}
          alt={displayLabel}
          onError={(e) => { e.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><rect fill="%23111827" width="640" height="360"/><text fill="%23475569" font-family="Inter" font-size="18" x="50%" y="50%" text-anchor="middle" dy=".3em">No Signal</text></svg>' }}
        />
      )}

      <div className="camera-overlay" style={{ pointerEvents: 'none' }}>
        <div className="flex flex-center gap-2" style={{ justifyContent: 'space-between' }}>
          <div className="flex flex-center gap-2">
            <div className={`camera-status-dot ${isOff ? 'offline' : camera.status}`} />
            <span className="camera-name">{displayLabel}</span>
          </div>
          {/* Per-camera power toggle — clickable even when stream is off */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              toggleCamera();
            }}
            disabled={toggling || isArmed === false}
            title={camEnabled ? 'Disable this camera' : 'Enable this camera'}
            style={{
              pointerEvents: 'all',
              background: camEnabled ? 'rgba(16,185,129,0.2)' : 'rgba(100,100,100,0.2)',
              border: `1px solid ${camEnabled ? 'rgba(16,185,129,0.5)' : 'rgba(100,100,100,0.4)'}`,
              borderRadius: 6,
              padding: '3px 6px',
              cursor: toggling || isArmed === false ? 'not-allowed' : 'pointer',
              opacity: toggling ? 0.5 : 1,
              display: 'flex', alignItems: 'center', gap: 4,
              color: camEnabled ? '#10b981' : '#64748b',
              fontSize: 10, fontWeight: 700
            }}
          >
            <Power size={11} />
            {camEnabled ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>

      {alertLevel && !isOff && (
        <div className={`camera-badge ${alertLevel}`}>{alertLevel}</div>
      )}
    </div>
  )
}
