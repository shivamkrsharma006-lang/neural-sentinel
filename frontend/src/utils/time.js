/**
 * Time utilities — all timestamps from backend are UTC (no Z suffix).
 * We must force UTC interpretation before converting to local time.
 */

function toUtcDate(date) {
  const s = String(date)
  // If already has timezone info, use as-is
  if (s.endsWith('Z') || s.includes('+')) return new Date(date)
  // Backend sends naive UTC — append Z so browser treats it as UTC
  return new Date(s + 'Z')
}

export function formatDistanceToNow(date) {
  const d = toUtcDate(date)
  const seconds = Math.floor((Date.now() - d.getTime()) / 1000)
  if (seconds < 10) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

export function formatDateTime(date) {
  return toUtcDate(date).toLocaleString(undefined, {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
