import { useState, useEffect, useRef } from 'react'
import api from '../api/client'
import { useAuthStore } from '../store/authStore'
import {
  Tv, Cpu, ShieldAlert, Users, Clock, AlertTriangle, RefreshCw, Eye, Camera, Sun, Info, Settings, ShieldCheck, Thermometer
} from 'lucide-react'

export default function Monitor() {
  const token = useAuthStore((s) => s.token)
  const [cameras, setCameras] = useState([])
  const [selectedCam, setSelectedCam] = useState(null)
  const [telemetry, setTelemetry] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadingTelemetry, setLoadingTelemetry] = useState(false)
  const pollRef = useRef(null)

  const loadCameras = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/cameras')
      setCameras(data)
      if (data.length > 0) {
        setSelectedCam(data[0])
      }
    } catch (err) {
      console.error('Failed to load cameras', err)
    } finally {
      setLoading(false)
    }
  }

  const loadTelemetry = async (camId) => {
    if (!camId) return
    try {
      const { data } = await api.get(`/cameras/${camId}/telemetry`)
      setTelemetry(data)
    } catch (err) {
      console.error('Failed to load telemetry', err)
    }
  }

  // Initial load
  useEffect(() => {
    loadCameras()
  }, [])

  // Start polling when camera selection changes
  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
    }

    if (selectedCam) {
      loadTelemetry(selectedCam.id)
      pollRef.current = setInterval(() => {
        loadTelemetry(selectedCam.id)
      }, 1500) // Poll every 1.5 seconds
    }

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
      }
    }
  }, [selectedCam])

  const formatDuration = (secs) => {
    if (!secs || secs <= 0) return 'Just spotted'
    if (secs < 60) return `${Math.round(secs)}s`
    const mins = Math.floor(secs / 60)
    const remain = Math.round(secs % 60)
    return `${mins}m ${remain}s`
  }

  const getFsmStateBadge = (state) => {
    const cls = {
      THREAT: 'badge-critical',
      LOITERING: 'badge-high',
      PRESENT: 'badge-medium',
      ENTERING: 'badge-low',
      IDLE: 'badge-low'
    }
    return <span className={`badge ${cls[state] || 'badge-low'}`} style={{ fontSize: 11 }}>{state}</span>
  }

  const getLightingIcon = (lighting) => {
    if (lighting?.toLowerCase().includes('night') || lighting?.toLowerCase().includes('low')) {
      return <Thermometer size={16} color="var(--primary)" />
    }
    return <Sun size={16} color="var(--warning)" />
  }

  return (
    <div className="monitor-container" style={{ display: 'flex', flexDirection: 'column', gap: 20, paddingBottom: 32 }}>
      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="topbar">
        <div className="topbar-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Tv size={22} color="var(--primary)" />
          AI Monitor & Pipeline Inspector
        </div>
        <div className="topbar-right">
          <select
            value={selectedCam?.id || ''}
            onChange={(e) => {
              const cam = cameras.find(c => c.id === parseInt(e.target.value))
              if (cam) setSelectedCam(cam)
            }}
            className="select"
            style={{ minWidth: 200, height: 38 }}
          >
            {cameras.map(c => (
              <option key={c.id} value={c.id}>{c.name} ({c.status})</option>
            ))}
          </select>
        </div>
      </div>

      {loading && !selectedCam ? (
        <div className="card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 300, gap: 12 }}>
          <RefreshCw size={32} className="spin" color="var(--primary)" />
          <div style={{ color: 'var(--text2)', fontSize: 14 }}>Connecting to video nodes...</div>
        </div>
      ) : !selectedCam ? (
        <div className="card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 300, gap: 16 }}>
          <Camera size={40} color="var(--text3)" />
          <div style={{ color: 'var(--text2)', fontSize: 15 }}>No cameras registered in system.</div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: 24, alignItems: 'start' }} className="monitor-layout-grid">
          
          {/* ── Left Column: Live Feed View ─────────────────────────────── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="card" style={{ padding: 0, overflow: 'hidden', border: '1px solid var(--border)', background: '#000', borderRadius: 12, position: 'relative' }}>
              
              {/* Camera Info HUD Overlay */}
              <div style={{
                position: 'absolute', top: 12, left: 12, right: 12, zIndex: 10,
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                background: 'rgba(0, 0, 0, 0.65)', backdropFilter: 'blur(8px)',
                borderRadius: 8, padding: '8px 16px', border: '1px solid rgba(255,255,255,0.05)'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: selectedCam.status === 'online' ? '#10b981' : '#ef4444',
                    boxShadow: selectedCam.status === 'online' ? '0 0 8px #10b981' : '0 0 8px #ef4444',
                    animation: selectedCam.status === 'online' ? 'blink 2s infinite' : 'none'
                  }} />
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>{selectedCam.name}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 11, color: 'rgba(255,255,255,0.6)' }}>
                  <span>FPS: 25 (capped)</span>
                  <span>ID: {selectedCam.id}</span>
                </div>
              </div>

              {/* Live Video Feed Stream */}
              <div style={{ width: '100%', aspectRatio: '16/10', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#09090b' }}>
                {selectedCam.status === 'disabled' ? (
                  <div style={{ color: 'var(--text3)', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
                    <Eye size={32} />
                    <span>Camera paused by user</span>
                  </div>
                ) : (
                  <img
                    src={`/api/stream/${selectedCam.id}?token=${token}`}
                    alt={selectedCam.name}
                    style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                    onError={(e) => {
                      e.target.style.display = 'none'
                      e.target.nextSibling.style.display = 'flex'
                    }}
                  />
                )}
                <div style={{ display: 'none', color: 'var(--text3)', textAlign: 'center', flexDirection: 'column', alignItems: 'center', gap: 10 }} className="stream-error-placeholder">
                  <AlertTriangle size={32} color="var(--danger)" />
                  <span>Connecting to video node...</span>
                </div>
              </div>
            </div>

            {/* Environmental Gauges */}
            {telemetry?.environment && (
              <div className="card">
                <div className="card-header">
                  <div className="card-title">
                    <Sun size={16} color="var(--primary)" />
                    Live Environment Diagnostics
                  </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
                  {/* Brightness */}
                  <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border)', borderRadius: 8, padding: 12, textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: 'var(--text3)', textTransform: 'uppercase' }}>Brightness</div>
                    <div style={{ fontSize: 22, fontWeight: 700, marginTop: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                      {telemetry.environment.brightness}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4 }}>Avg value (0-255)</div>
                  </div>

                  {/* Contrast */}
                  <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border)', borderRadius: 8, padding: 12, textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: 'var(--text3)', textTransform: 'uppercase' }}>Contrast Index</div>
                    <div style={{ fontSize: 22, fontWeight: 700, marginTop: 6 }}>
                      {telemetry.environment.contrast}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4 }}>Standard Deviation</div>
                  </div>

                  {/* Lighting Condition */}
                  <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border)', borderRadius: 8, padding: 12, textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: 'var(--text3)', textTransform: 'uppercase' }}>Lighting Mode</div>
                    <div style={{ fontSize: 13, fontWeight: 700, marginTop: 12, color: 'var(--text1)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                      {getLightingIcon(telemetry.environment.lighting)}
                      {telemetry.environment.lighting}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* ── Right Column: AI Analytics & Trackers ─────────────────────── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            
            {/* Active Detections & FSM States */}
            <div className="card">
              <div className="card-header">
                <div className="card-title">
                  <Users size={16} color="var(--primary)" />
                  Live Object Trackers ({telemetry?.total_active_tracks || 0})
                </div>
                <div style={{ fontSize: 11, color: 'var(--text3)', display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981', animation: 'blink 1.5s infinite' }} />
                  Live updating
                </div>
              </div>

              {(!telemetry?.active_objects || telemetry.active_objects.length === 0) ? (
                <div style={{ textAlign: 'center', padding: '32px 16px', color: 'var(--text3)', fontSize: 13 }}>
                  No objects currently detected in camera view
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWaitHeight: 280, overflowY: 'auto' }}>
                  {telemetry.active_objects.map((obj, idx) => {
                    const isUnknown = obj.identity === 'UNKNOWN'
                    return (
                      <div
                        key={idx}
                        style={{
                          padding: '10px 12px',
                          background: 'rgba(255,255,255,0.02)',
                          border: '1px solid var(--border)',
                          borderRadius: 6,
                          display: 'flex',
                          flexDirection: 'column',
                          gap: 6
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--primary)' }}>#{obj.track_id}</span>
                            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text1)' }}>
                              {obj.class_name.toUpperCase()}
                            </span>
                            {obj.class_name === 'person' && (
                              <span style={{ fontSize: 11, color: isUnknown ? 'var(--warning)' : 'var(--success)' }}>
                                {isUnknown ? 'UNKNOWN' : obj.identity}
                              </span>
                            )}
                          </div>
                          {getFsmStateBadge(obj.fsm_state)}
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text3)' }}>
                          <span>Tracking: {formatDuration(obj.duration_seconds)}</span>
                          <span>Conf: {(obj.confidence * 100).toFixed(0)}%</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {/* AI Module Pipelines Status */}
            <div className="card">
              <div className="card-header">
                <div className="card-title">
                  <Cpu size={16} color="var(--primary)" />
                  AI Pipeline Module Inspector
                </div>
              </div>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {telemetry?.pipelines && Object.entries(telemetry.pipelines).map(([key, pipeline]) => (
                  <div
                    key={key}
                    style={{
                      padding: '10px 12px',
                      background: 'rgba(255,255,255,0.01)',
                      border: '1px solid var(--border)',
                      borderRadius: 6,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between'
                    }}
                  >
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text1)', textTransform: 'capitalize' }}>
                        {key.replace(/_/g, ' ')}
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>
                        {pipeline.model_name || pipeline.resolution || pipeline.stale_drop_threshold || `Active (${pipeline.states_tracked || pipeline.enrolled_faces} loaded)`}
                      </div>
                    </div>
                    <span className={`badge ${pipeline.status === 'active' ? 'badge-low' : 'badge-critical'}`} style={{ fontSize: 9 }}>
                      {pipeline.status.toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            </div>

          </div>

        </div>
      )}
    </div>
  )
}
