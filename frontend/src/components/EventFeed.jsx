import { formatDistanceToNow } from '../utils/time'
import { ShieldX, AlertTriangle, Info, CheckCircle } from 'lucide-react'

const levelIcon = {
  CRITICAL: <ShieldX size={13} color="var(--danger)" />,
  HIGH:     <AlertTriangle size={13} color="var(--warning)" />,
  MEDIUM:   <Info size={13} color="var(--primary)" />,
  LOW:      <CheckCircle size={13} color="var(--success)" />,
}

const levelColor = {
  CRITICAL: 'var(--danger)',
  HIGH:     'var(--warning)',
  MEDIUM:   'var(--primary)',
  LOW:      'var(--success)',
}

export default function EventFeed({ events = [] }) {
  if (!events.length) {
    return (
      <div className="empty-state" style={{ padding: 24 }}>
        <div className="text-sm text-muted">No events yet — system monitoring…</div>
      </div>
    )
  }

  return (
    <div className="event-feed">
      {events.map((evt, i) => {
        const level   = evt.risk_level || 'LOW'
        const color   = levelColor[level] || 'var(--text2)'
        // Always parse as UTC — both API (has Z) and WS (now has Z) are UTC
        const tsStr   = evt.timestamp || ''
        const ts      = tsStr.endsWith('Z') || tsStr.includes('+')
          ? new Date(tsStr)
          : new Date(tsStr + 'Z')
        const relTime = formatDistanceToNow(ts)

        // Camera label: prefer camera_name (from WS), fall back to cam_name from API
        const camLabel = evt.camera_name || `Camera ${evt.camera_id}`
        const zonePart = evt.zone_name ? ` · ${evt.zone_name}` : ''
        const objPart  = evt.object_class
          ? `${evt.object_class}${typeof evt.confidence === 'number' ? ` (${(evt.confidence * 100).toFixed(0)}%)` : ''}`
          : ''

        return (
          <div key={evt.id || `ws-${i}`} className={`event-item ${level}`}>
            <div style={{ flexShrink: 0, marginTop: 1 }}>{levelIcon[level]}</div>
            <div className="event-meta" style={{ flex: 1, minWidth: 0 }}>
              <div className="event-type" style={{ color }}>
                {evt.violation_type || evt.event_type || 'Alert'}
              </div>
              <div className="event-detail" style={{ fontSize: 11, color: 'var(--text3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {camLabel}{zonePart}
                {objPart ? ` · ${objPart}` : ''}
                {evt.direction && evt.direction !== 'stationary' ? ` · ${evt.direction}` : ''}
                {typeof evt.risk_score === 'number' ? ` · R=${evt.risk_score.toFixed(2)}` : ''}
                {/* V4 color dots */}
                {evt.dominant_colors && Array.isArray(evt.dominant_colors) && evt.dominant_colors.length > 0 && (
                  <span style={{ marginLeft: 4, display: 'inline-flex', gap: 2, verticalAlign: 'middle' }}>
                    {evt.dominant_colors.slice(0, 2).map((c, ci) => (
                      <span key={ci} style={{
                        width: 8, height: 8, borderRadius: '50%',
                        background: c === 'navy' ? '#001f3f' : c,
                        display: 'inline-block', border: '1px solid rgba(255,255,255,0.15)'
                      }} />
                    ))}
                  </span>
                )}
              </div>
            </div>
            <div className="event-time" style={{ flexShrink: 0, fontSize: 10, color: 'var(--text3)' }}>
              {relTime}
            </div>
          </div>
        )
      })}
    </div>
  )
}
