import { useState, useEffect, useRef, useCallback } from 'react'
import api from '../api/client'
import {
  FileText, Users, Car, ShieldAlert, Clock,
  Calendar, RefreshCw, AlertTriangle, ArrowRight, UserCheck, Eye, Search, Inbox
} from 'lucide-react'

export default function Summary() {
  const getTodayDateString = () => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }

  const [date, setDate] = useState('')
  const [cameraId, setCameraId] = useState('')
  const [cameras, setCameras] = useState([])
  const [loading, setLoading] = useState(false)
  const [digest, setDigest] = useState(null)
  const requestCountRef = useRef(0)

  const loadCameras = async () => {
    try {
      const { data } = await api.get('/cameras')
      setCameras(data)
    } catch (err) {
      console.error('Failed to load cameras', err)
    }
  }

  const loadLatestEventDate = async () => {
    try {
      const { data } = await api.get('/events', { params: { limit: 1 } })
      if (data && data.length > 0) {
        const latestDate = data[0].timestamp.split('T')[0]
        setDate(latestDate)
      } else {
        setDate(getTodayDateString())
      }
    } catch (err) {
      console.error('Failed to get latest event date', err)
      setDate(getTodayDateString())
    }
  }

  const fetchDigest = useCallback(async () => {
    if (!date) return
    const reqId = ++requestCountRef.current
    setLoading(true)
    try {
      const params = { date }
      if (cameraId) params.camera_id = cameraId
      const { data } = await api.get('/digest', { params })
      if (reqId === requestCountRef.current) {
        setDigest(data)
      }
    } catch (err) {
      console.error('Failed to fetch digest', err)
    } finally {
      if (reqId === requestCountRef.current) {
        setLoading(false)
      }
    }
  }, [date, cameraId])

  useEffect(() => {
    loadCameras()
    loadLatestEventDate()
  }, [])

  useEffect(() => {
    fetchDigest()
  }, [fetchDigest])

  const formatTime = (isoStr) => {
    if (!isoStr) return ''
    try {
      return new Date(isoStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    } catch {
      return isoStr
    }
  }

  const formatDuration = (secs) => {
    if (!secs || secs <= 0) return 'Instantaneous'
    if (secs < 60) return `${Math.round(secs)}s`
    const mins = Math.floor(secs / 60)
    const remain = Math.round(secs % 60)
    return `${mins}m ${remain}s`
  }

  const getRiskColor = (score) => {
    if (score >= 0.7) return 'var(--danger)'
    if (score >= 0.4) return 'var(--warning)'
    return 'var(--success)'
  }

  const getRiskBadgeClass = (score) => {
    if (score >= 0.7) return 'badge-critical'
    if (score >= 0.4) return 'badge-high'
    return 'badge-low'
  }

  // Calculate stats and parameters
  const stats = digest?.aggregate_stats || {
    total_persons: 0,
    known_persons: 0,
    unknown_persons: 0,
    total_vehicles: 0,
    total_events: 0,
    alerts_triggered: 0,
    peak_hour: null,
  }

  const hourlyActivity = digest?.hourly_activity || {}
  const maxHourCount = Math.max(...Object.values(hourlyActivity), 1)

  const identities = digest?.identity_groups || []
  const notableEvents = digest?.notable_events || []

  return (
    <div className="summary-container" style={{ display: 'flex', flexDirection: 'column', gap: 24, paddingBottom: 32 }}>
      {/* ── Topbar ────────────────────────────────────────────────────────── */}
      <div className="topbar">
        <div className="topbar-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <FileText size={22} color="var(--primary)" />
          Activity Summary & Digest
        </div>
        <div className="topbar-right" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', borderRadius: 8, padding: '4px 12px' }}>
            <Calendar size={15} color="var(--text3)" />
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text)',
                outline: 'none',
                fontSize: 13,
                fontFamily: 'inherit',
                cursor: 'pointer'
              }}
            />
          </div>

          <select
            value={cameraId}
            onChange={(e) => setCameraId(e.target.value)}
            className="select"
            style={{ minWidth: 160, height: 38 }}
          >
            <option value="">All Cameras</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>

          <button className="btn btn-ghost btn-sm" onClick={fetchDigest} disabled={loading} style={{ height: 38, width: 38, padding: 0, minWidth: 0 }}>
            <RefreshCw size={15} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      {/* ── Content States ────────────────────────────────────────────────── */}
      {loading && !digest ? (
        <div className="card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 300, gap: 12 }}>
          <RefreshCw size={32} className="spin" color="var(--primary)" />
          <div style={{ color: 'var(--text2)', fontSize: 14 }}>Compiling surveillance analytics...</div>
        </div>
      ) : !date ? (
        <div className="card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 300, gap: 12 }}>
          <RefreshCw size={32} className="spin" color="var(--primary)" />
          <div style={{ color: 'var(--text2)', fontSize: 14 }}>Finding latest event logs...</div>
        </div>
      ) : stats.total_events === 0 ? (
        <div className="card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 350, gap: 16, textAlign: 'center' }}>
          <div style={{ height: 64, width: 64, borderRadius: '50%', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Inbox size={28} color="var(--text3)" />
          </div>
          <div>
            <h3 style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>No Activity Recorded</h3>
            <p style={{ fontSize: 13, color: 'var(--text3)', maxWidth: 300 }}>
              There are no captured events or objects for {date} on this camera selection.
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* ── Metric Cards Grid ────────────────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
            {/* Total Events */}
            <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 12, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Total Events</div>
                <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4, color: 'var(--text)' }}>{stats.total_events}</div>
                <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 4 }}>Surveillance logs</div>
              </div>
              <div style={{ height: 42, width: 42, borderRadius: 8, background: 'rgba(255,255,255,0.03)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid var(--border)' }}>
                <FileText size={18} color="var(--primary)" />
              </div>
            </div>

            {/* People Detected */}
            <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 12, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Unique People</div>
                <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4, color: 'var(--text)' }}>{stats.total_persons}</div>
                <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>
                  <span style={{ color: 'var(--success)' }}>{stats.known_persons} Known</span>
                  {'  •  '}
                  <span style={{ color: 'var(--warning)' }}>{stats.unknown_persons} Unknown</span>
                </div>
              </div>
              <div style={{ height: 42, width: 42, borderRadius: 8, background: 'rgba(255,255,255,0.03)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid var(--border)' }}>
                <Users size={18} color="var(--primary)" />
              </div>
            </div>

            {/* Vehicles Detected */}
            <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 12, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Unique Vehicles</div>
                <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4, color: 'var(--text)' }}>{stats.total_vehicles}</div>
                <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 4 }}>Transport detection</div>
              </div>
              <div style={{ height: 42, width: 42, borderRadius: 8, background: 'rgba(255,255,255,0.03)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid var(--border)' }}>
                <Car size={18} color="var(--primary)" />
              </div>
            </div>

            {/* Alerts Triggered */}
            <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 12, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Alerts Fired</div>
                <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4, color: stats.alerts_triggered > 0 ? 'var(--danger)' : 'var(--text)' }}>
                  {stats.alerts_triggered}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 4 }}>High/Critical threat level</div>
              </div>
              <div style={{
                height: 42, width: 42, borderRadius: 8,
                background: stats.alerts_triggered > 0 ? 'rgba(239, 68, 68, 0.1)' : 'rgba(255,255,255,0.03)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                border: stats.alerts_triggered > 0 ? '1px solid rgba(239, 68, 68, 0.2)' : '1px solid var(--border)'
              }}>
                <ShieldAlert size={18} color={stats.alerts_triggered > 0 ? 'var(--danger)' : 'var(--primary)'} />
              </div>
            </div>

            {/* Peak Hour */}
            <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 12, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Peak Hour</div>
                <div style={{ fontSize: 24, fontWeight: 700, marginTop: 7, color: 'var(--text)' }}>
                  {stats.peak_hour ? `${stats.peak_hour}:00` : 'N/A'}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 5 }}>Most active period</div>
              </div>
              <div style={{ height: 42, width: 42, borderRadius: 8, background: 'rgba(255,255,255,0.03)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid var(--border)' }}>
                <Clock size={18} color="var(--primary)" />
              </div>
            </div>
          </div>

          {/* ── Hourly Distribution ──────────────────────────────────────── */}
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <Clock size={16} color="var(--primary)" />
                Hourly Activity Distribution
              </div>
            </div>
            <div style={{
              display: 'flex',
              alignItems: 'flex-end',
              justifyContent: 'space-between',
              height: 120,
              paddingTop: 20,
              paddingBottom: 10,
              gap: 4,
              borderBottom: '1px solid var(--border)'
            }}>
              {Object.entries(hourlyActivity).map(([hour, count]) => {
                const isPeak = hour === stats.peak_hour
                const heightPct = count > 0 ? (count / maxHourCount) * 100 : 0
                return (
                  <div
                    key={hour}
                    style={{
                      flex: 1,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      height: '100%',
                      justifyContent: 'flex-end',
                      position: 'relative'
                    }}
                    title={`${hour}:00 — ${count} events`}
                  >
                    <div style={{
                      height: `${heightPct}%`,
                      width: '100%',
                      background: isPeak ? 'var(--primary)' : 'rgba(255,255,255,0.15)',
                      borderRadius: '2px 2px 0 0',
                      transition: 'height 0.3s ease, background-color 0.2s',
                      cursor: 'pointer'
                    }}
                    className="summary-bar-hover"
                    />
                  </div>
                )
              })}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text3)', marginTop: 8, paddingLeft: 4, paddingRight: 4 }}>
              <span>12 AM</span>
              <span>4 AM</span>
              <span>8 AM</span>
              <span>12 PM</span>
              <span>4 PM</span>
              <span>8 PM</span>
              <span>11 PM</span>
            </div>
          </div>

          {/* ── Details Sections ─────────────────────────────────────────── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            
            {/* Identities Directory */}
            <div className="card">
              <div className="card-header">
                <div className="card-title">
                  <Users size={16} color="var(--primary)" />
                  Identities Directory ({identities.length})
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {identities.map((item, idx) => {
                  const isUnknown = item.identity === 'UNKNOWN'
                  const isPerson = item.object_class === 'person'
                  
                  return (
                    <div
                      key={idx}
                      style={{
                        padding: '12px 16px',
                        background: 'rgba(255,255,255,0.02)',
                        border: '1px solid var(--border)',
                        borderRadius: 8,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 10
                      }}
                    >
                      {/* Top Row: Identity name, count, risk */}
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          {isPerson ? (
                            isUnknown ? (
                              <span className="badge badge-high" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                                <AlertTriangle size={11} />
                                UNKNOWN Person
                              </span>
                            ) : (
                              <span className="badge badge-low" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                                <UserCheck size={11} />
                                {item.identity} [VERIFIED]
                              </span>
                            )
                          ) : (
                            <span className="badge badge-medium" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                              <Car size={11} />
                              {item.identity} ({item.object_class})
                            </span>
                          )}
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                          <span style={{ fontSize: 12, color: 'var(--text2)' }}>
                            <strong>{item.event_count}</strong> {item.event_count === 1 ? 'event' : 'events'}
                          </span>
                          <span className={`badge ${getRiskBadgeClass(item.avg_risk_score)}`} style={{ fontSize: 11 }}>
                            Avg Risk: {item.avg_risk_score.toFixed(2)}
                          </span>
                        </div>
                      </div>

                      {/* Bottom Row: metadata stats */}
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12, borderTop: '1px solid rgba(255,255,255,0.03)', paddingTop: 10 }}>
                        <div style={{ fontSize: 12, color: 'var(--text2)', display: 'flex', flexDirection: 'column', gap: 2 }}>
                          <span style={{ color: 'var(--text3)', fontSize: 11 }}>Time Span</span>
                          <div>
                            {formatTime(item.first_seen)} 
                            <ArrowRight size={10} style={{ margin: '0 6px', color: 'var(--text3)' }} /> 
                            {formatTime(item.last_seen)}
                          </div>
                        </div>

                        <div style={{ fontSize: 12, color: 'var(--text2)', display: 'flex', flexDirection: 'column', gap: 2 }}>
                          <span style={{ color: 'var(--text3)', fontSize: 11 }}>Duration of Presence</span>
                          <div>{formatDuration(item.duration_seconds)}</div>
                        </div>

                        <div style={{ fontSize: 12, color: 'var(--text2)', display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <span style={{ color: 'var(--text3)', fontSize: 11 }}>Zones & Cameras</span>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                            {item.cameras.map((cam, i) => (
                              <span key={i} className="camera-badge ONLINE" style={{ fontSize: 10, padding: '2px 6px' }}>{cam}</span>
                            ))}
                            {item.zones.map((zone, i) => (
                              <span key={i} className="camera-badge MEDIUM" style={{ fontSize: 10, padding: '2px 6px' }}>{zone}</span>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Notable Alerts Table */}
            {notableEvents.length > 0 && (
              <div className="card">
                <div className="card-header">
                  <div className="card-title" style={{ color: 'var(--danger)' }}>
                    <ShieldAlert size={16} color="var(--danger)" />
                    Notable Threat Alerts ({notableEvents.length})
                  </div>
                </div>
                <div className="table-responsive">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Type</th>
                        <th>Identity</th>
                        <th>Risk Level</th>
                        <th>Risk Score</th>
                        <th>Camera / Zone</th>
                      </tr>
                    </thead>
                    <tbody>
                      {notableEvents.map((evt) => (
                        <tr key={evt.event_id}>
                          <td style={{ fontSize: 12 }}>{formatTime(evt.timestamp)}</td>
                          <td>
                            <span style={{ fontWeight: 600, fontSize: 12 }}>{evt.event_type}</span>
                          </td>
                          <td style={{ fontSize: 12 }}>
                            {evt.identity === 'UNKNOWN' ? (
                              <span style={{ color: 'var(--text3)' }}>UNKNOWN</span>
                            ) : (
                              <span style={{ color: 'var(--success)', fontWeight: 500 }}>{evt.identity}</span>
                            )}
                          </td>
                          <td>
                            <span className={`badge ${evt.risk_level === 'CRITICAL' ? 'badge-critical' : 'badge-high'}`}>
                              {evt.risk_level}
                            </span>
                          </td>
                          <td style={{ fontWeight: 700, fontSize: 12 }}>
                            {evt.risk_score.toFixed(2)}
                          </td>
                          <td style={{ fontSize: 12, color: 'var(--text2)' }}>
                            {evt.camera} {evt.zone ? ` / ${evt.zone}` : ''}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

          </div>
        </>
      )}
    </div>
  )
}
