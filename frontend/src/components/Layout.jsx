import { useState, useEffect } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import {
  LayoutDashboard, Camera, ShieldAlert, Users, Settings,
  LogOut, Shield, WifiOff
} from 'lucide-react'
import { backendState } from '../api/client'

const navItems = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/cameras', label: 'Cameras', icon: Camera },
  { to: '/events', label: 'Events', icon: ShieldAlert },
  { to: '/enroll', label: 'Enroll Faces', icon: Users },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export default function Layout() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()
  const [isOnline, setIsOnline] = useState(backendState.isOnline)

  useEffect(() => {
    return backendState.subscribe(setIsOnline)
  }, [])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="app-shell">
      {!isOnline && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, zIndex: 9999,
          background: '#7f1d1d', color: '#fecaca',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: 8, padding: '8px 16px', fontSize: 13, fontWeight: 600,
          borderBottom: '1px solid #991b1b'
        }}>
          <WifiOff size={14} />
          Backend offline — restart the Python server then refresh
        </div>
      )}
      <aside className="sidebar" style={{ marginTop: !isOnline ? 37 : 0 }}>
        <div className="sidebar-logo">
          <Shield size={28} color="var(--primary)" />
          <div>
            <div className="logo-text">Neural Sentinel</div>
            <div className="logo-sub">AI Surveillance</div>
          </div>
        </div>

        <nav className="sidebar-nav">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
            >
              <Icon className="nav-icon" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="user-pill">
            <div className="user-avatar">
              {user?.username?.[0]?.toUpperCase() || 'U'}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="user-name">{user?.username}</div>
              <div className="user-role">Operator</div>
            </div>
            <button
              onClick={handleLogout}
              className="btn btn-ghost btn-sm"
              title="Logout"
              style={{ padding: '4px', minWidth: 0 }}
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </aside>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
