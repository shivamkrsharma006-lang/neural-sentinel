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
                {typeof evt.risk_score === 'number' ? ` · R=${evt.risk_score.toFixed(2)}` : ''}
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
