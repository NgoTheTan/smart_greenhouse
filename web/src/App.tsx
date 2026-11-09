import { NavLink, Route, Routes, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, getToken, setToken } from './lib/api'

import OverviewPage from './pages/OverviewPage'
import ZoneDetailPage from './pages/ZoneDetailPage'
import DevicesPage from './pages/DevicesPage'
import CropProfilesPage from './pages/CropProfilesPage'
import AlertsPage from './pages/AlertsPage'
import ModelsPage from './pages/ModelsPage'
import NotificationsPage from './pages/NotificationsPage'
import LoginPage from './pages/LoginPage'

const PAGES = [
  { path: '/', label: '🌿 Tổng quan' },
  { path: '/devices', label: '📡 Thiết bị' },
  { path: '/crop-profiles', label: '🌱 Crop profile' },
  { path: '/alerts', label: '🔔 Cảnh báo' },
  { path: '/models', label: '🧠 Model & Thí nghiệm' },
  { path: '/settings/notifications', label: '📲 Thông báo' },
]

function HealthBadge() {
  const { data, isError } = useQuery({
    queryKey: ['health'],
    queryFn: () => api<{ status: string; db: boolean }>('/health'),
    refetchInterval: 15_000,
    retry: 1,
  })
  const ok = !isError && data?.status === 'ok'
  return (
    <span className={`badge ${ok ? 'ok' : 'muted'}`} style={{ fontSize: '0.75rem' }}>
      {ok ? '● Cloud API Online' : '○ Standalone / Mock Mode'}
    </span>
  )
}

function UserBadge() {
  const token = getToken()
  if (!token) {
    return (
      <Link to="/login" className="btn btn-sm btn-secondary" style={{ color: '#fff', borderColor: 'rgba(255,255,255,0.4)', background: 'rgba(255,255,255,0.1)' }}>
        Đăng nhập
      </Link>
    )
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <span style={{ fontSize: '0.8rem', opacity: 0.9 }}>👤 Operator</span>
      <button
        onClick={() => {
          setToken(null)
          window.location.reload()
        }}
        className="btn btn-sm"
        style={{ color: '#fff', background: 'rgba(0,0,0,0.2)', padding: '0.2rem 0.5rem', border: 'none' }}
      >
        Thoát
      </button>
    </div>
  )
}

export default function App() {
  return (
    <div className="layout">
      <header>
        <Link to="/" className="header-brand">
          <h1>🌱 GreenHub</h1>
          <span className="logo-tag">SMART AGRI IOT</span>
        </Link>
        <div className="header-actions">
          <HealthBadge />
          <UserBadge />
        </div>
      </header>

      <nav>
        {PAGES.map((p) => (
          <NavLink key={p.path} to={p.path} end>
            {p.label}
          </NavLink>
        ))}
      </nav>

      <main>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/zones/:id" element={<ZoneDetailPage />} />
          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/crop-profiles" element={<CropProfilesPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/settings/notifications" element={<NotificationsPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="*"
            element={
              <div style={{ textAlign: 'center', padding: '3rem 0' }}>
                <h3>Không tìm thấy trang</h3>
                <Link to="/" className="btn btn-primary" style={{ marginTop: '1rem' }}>
                  Quay lại Tổng quan
                </Link>
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  )
}
