import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Cameras from './pages/Cameras'
import ZoneEditor from './pages/ZoneEditor'
import Events from './pages/Events'
import Enroll from './pages/Enroll'
import Settings from './pages/Settings'
import Summary from './pages/Summary'
import Monitor from './pages/Monitor'
import Layout from './components/Layout'

function PrivateRoute({ children }) {
  const token = useAuthStore((s) => s.token)
  return token ? children : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<PrivateRoute><Layout /></PrivateRoute>}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="cameras" element={<Cameras />} />
          <Route path="cameras/:cameraId/zones" element={<ZoneEditor />} />
          <Route path="events" element={<Events />} />
          <Route path="enroll" element={<Enroll />} />
          <Route path="settings" element={<Settings />} />
          <Route path="summary" element={<Summary />} />
          <Route path="monitor" element={<Monitor />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
