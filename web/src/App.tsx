import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from './lib/api'
import { AuthProvider, useAuth } from './lib/auth'
import { WebSocketProvider, useRealtime } from './lib/ws'
import type { AlertItem } from './lib/types'

import AlertsPage from './pages/AlertsPage'
import CropProfilesPage from './pages/CropProfilesPage'
import DevicesPage from './pages/DevicesPage'
import GreenhousePage from './pages/GreenhousePage'
import LoginPage from './pages/LoginPage'
import ModelsPage from './pages/ModelsPage'
import NotificationsPage from './pages/NotificationsPage'
import OverviewPage from './pages/OverviewPage'
import RecommendationsPage from './pages/RecommendationsPage'
import ZoneDetailPage from './pages/ZoneDetailPage'

function AlertBell() {
  const { isAuthenticated } = useAuth()
  const openAlertsQuery = useQuery({
    queryKey: ['alerts', 'open-count'],
    queryFn: () => api<AlertItem[]>('/alerts?state=open&limit=100'),
    enabled: isAuthenticated,
    refetchInterval: 15_000,
  })
  const openCount = openAlertsQuery.data?.length ?? 0

  if (!isAuthenticated) return null

  return (
    <Link
      to="/alerts"
      title={openCount > 0 ? `Có ${openCount} cảnh báo đang mở` : 'Xem cảnh báo'}
      aria-label="Cảnh báo"
      style={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '2.1rem',
        height: '2.1rem',
        borderRadius: '50%',
        background: 'rgba(255, 255, 255, 0.15)',
        color: '#fff',
        textDecoration: 'none',
        fontSize: '1.1rem',
        transition: 'background 0.15s ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'rgba(255, 255, 255, 0.28)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'rgba(255, 255, 255, 0.15)'
      }}
    >
      🔔
      {openCount > 0 && (
        <span
          style={{
            position: 'absolute',
            top: '-2px',
            right: '-2px',
            background: 'var(--danger, #ef4444)',
            color: '#fff',
            fontSize: '0.65rem',
            fontWeight: 700,
            borderRadius: '9999px',
            minWidth: '1.1rem',
            height: '1.1rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '0 0.25rem',
            border: '2px solid #16a34a',
            boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
            lineHeight: 1,
          }}
        >
          {openCount > 99 ? '99+' : openCount}
        </span>
      )}
    </Link>
  )
}

function UserControls() {
  const { isAuthenticated, user, logout } = useAuth()
  if (!isAuthenticated || !user) {
    return (
      <Link
        to="/login"
        className="btn btn-sm btn-secondary"
        style={{
          color: '#fff',
          borderColor: 'rgba(255,255,255,0.4)',
          background: 'rgba(255,255,255,0.12)',
        }}
      >
        Đăng nhập
      </Link>
    )
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <span
        style={{ fontSize: '0.82rem', fontWeight: 600, opacity: 0.95 }}
        title={`Tài khoản: ${user.email}`}
      >
        🏡 {user.farm_name || user.email}
      </span>
      <button
        type="button"
        onClick={logout}
        className="btn btn-sm"
        style={{
          color: '#fff',
          background: 'rgba(0,0,0,0.22)',
          padding: '0.2rem 0.55rem',
          border: 'none',
        }}
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
        <Link to="/" className="header-brand">
          <h1>🌱 GreenHub</h1>
          <span className="logo-tag">SMART AGRI IOT</span>
        </Link>
        <div className="header-actions">
          <AlertBell />
          <UserControls />
        </div>
      </header>

      {isAuthenticated && (
        <nav aria-label="Điều hướng chính">
          <NavLink
            to="/"
            className={({ isActive }) => (isActive || isOverviewActive ? 'active' : undefined)}
          >
            🌿 Tổng quan
          </NavLink>
          <NavLink to="/devices">📡 Thiết bị</NavLink>
          <NavLink to="/crop-profiles">📋 Crop Profile</NavLink>
        </nav>
      )}

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
            path="/settings/notifications"
            element={
              <RequireAuth>
                <NotificationsPage />
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
