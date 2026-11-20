import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './lib/auth'
import { WebSocketProvider, useRealtime } from './lib/ws'

import AlertsPage from './pages/AlertsPage'
import CropProfilesPage from './pages/CropProfilesPage'
import DevicesPage from './pages/DevicesPage'
import GreenhousePage from './pages/GreenhousePage'
import LoginPage from './pages/LoginPage'
import ModelsPage from './pages/ModelsPage'
import OverviewPage from './pages/OverviewPage'
import RecommendationsPage from './pages/RecommendationsPage'
import ZoneDetailPage from './pages/ZoneDetailPage'
import NotificationPopup from './components/NotificationPopup'

function UserControls() {
  const { isAuthenticated, user, logout } = useAuth()
  if (!isAuthenticated || !user) {
    return (
      <Link to="/login" className="btn btn-sm btn-secondary">
        Đăng nhập
      </Link>
    )
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
      <span
        style={{ fontSize: '0.86rem', color: 'var(--text-main, #1C211E)', fontWeight: 400 }}
        title={`Tài khoản: ${user.email}`}
      >
        {user.farm_name || user.email}
      </span>
      <button
        type="button"
        onClick={logout}
        className="btn btn-sm btn-secondary"
      >
        Thoát
      </button>
    </div>
  )
}

function ToastContainer() {
  const { toasts, dismissToast } = useRealtime()
  if (toasts.length === 0) return null

  return (
    <div className="toast-container" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast-item toast-${t.severity}`}>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: '0.86rem' }}>{t.title}</div>
            <div style={{ fontSize: '0.8rem', marginTop: '0.15rem' }}>{t.body}</div>
            {t.url && (
              <Link
                to={t.url}
                style={{ fontSize: '0.78rem', fontWeight: 600, display: 'inline-block', marginTop: '0.25rem' }}
                onClick={() => dismissToast(t.id)}
              >
                Xem chi tiết →
              </Link>
            )}
          </div>
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            style={{ padding: '0.1rem 0.4rem' }}
            onClick={() => dismissToast(t.id)}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  )
}

function RequireAuth({ children }: { children: JSX.Element }) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '2rem' }}>
        Đang xác thực phiên đăng nhập...
      </div>
    )
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }
  return children
}

function AppShell() {
  const { isAuthenticated } = useAuth()
  const location = useLocation()

  // Nút Tổng quan sáng khi ở trang chủ, chi tiết nhà kính hoặc chi tiết zone
  const isOverviewActive =
    location.pathname === '/' ||
    location.pathname.startsWith('/greenhouses') ||
    location.pathname.startsWith('/zones')

  return (
    <div className="layout">
      <header>
        <div className="header-container">
          <div className="header-left">
            <Link to="/" className="header-brand">
              <h1>GreenHub</h1>
            </Link>
            {isAuthenticated && (
              <nav className="header-nav" aria-label="Điều hướng chính">
                <NavLink
                  to="/"
                  className={({ isActive }) =>
                    `header-tab ${isActive || isOverviewActive ? 'active' : ''}`.trim()
                  }
                >
                  Tổng quan
                </NavLink>
                <NavLink
                  to="/devices"
                  className={({ isActive }) =>
                    `header-tab ${isActive ? 'active' : ''}`.trim()
                  }
                >
                  Thiết bị
                </NavLink>
                <NavLink
                  to="/crop-profiles"
                  className={({ isActive }) =>
                    `header-tab ${isActive ? 'active' : ''}`.trim()
                  }
                >
                  Crop Profile
                </NavLink>
              </nav>
            )}
          </div>

          <div className="header-actions">
            {isAuthenticated && <NotificationPopup />}
            <UserControls />
          </div>
        </div>
      </header>

      <main>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <OverviewPage />
              </RequireAuth>
            }
          />
          <Route
            path="/greenhouses/:ghId"
            element={
              <RequireAuth>
                <GreenhousePage />
              </RequireAuth>
            }
          />
          <Route
            path="/zones/:id"
            element={
              <RequireAuth>
                <ZoneDetailPage />
              </RequireAuth>
            }
          />
          <Route
            path="/greenhouses/:ghId/control"
            element={
              <RequireAuth>
                <ZoneDetailPage />
              </RequireAuth>
            }
          />
          <Route
            path="/recommendations"
            element={
              <RequireAuth>
                <RecommendationsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/greenhouses/:id/recommendations"
            element={
              <RequireAuth>
                <RecommendationsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/devices"
            element={
              <RequireAuth>
                <DevicesPage />
              </RequireAuth>
            }
          />
          <Route
            path="/crop-profiles"
            element={
              <RequireAuth>
                <CropProfilesPage />
              </RequireAuth>
            }
          />
          <Route
            path="/alerts"
            element={
              <RequireAuth>
                <AlertsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/models"
            element={
              <RequireAuth>
                <ModelsPage />
              </RequireAuth>
            }
          />
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

      <ToastContainer />
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <WebSocketProvider>
        <AppShell />
      </WebSocketProvider>
    </AuthProvider>
  )
}
