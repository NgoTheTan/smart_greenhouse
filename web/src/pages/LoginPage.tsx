import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { api, formatApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { TokenResponse } from '../lib/types'

const DEV_ACCOUNTS = [
  { label: 'Chủ farm 1 (owner@greenhub.vn)', email: 'owner@greenhub.vn' },
  { label: 'Chủ farm 2 (owner2@greenhub.vn)', email: 'owner2@greenhub.vn' },
]

export default function LoginPage() {
  const { isAuthenticated, loginWithToken } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from || '/'

  const [email, setEmail] = useState('owner@greenhub.vn')
  const [password, setPassword] = useState('greenhub123')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (isAuthenticated) {
    return <Navigate to={from} replace />
  }

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const res = await api<TokenResponse>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email: email.trim(), password }),
      })
      await loginWithToken(res.access_token)
      navigate(from, { replace: true })
    } catch (err) {
      setError(formatApiError(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ maxWidth: 440, margin: '2.5rem auto' }}>
      <div className="card" style={{ padding: '2rem' }}>
        <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
          <h2 style={{ fontSize: '1.75rem', marginBottom: '0.25rem' }}>🌱 GreenHub</h2>
          <p className="muted" style={{ fontSize: '0.875rem', margin: 0 }}>
            Nền tảng Giám sát &amp; Điều khiển Vi khí hậu Nhà kính
          </p>
        </div>

        {error && (
          <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
            {error}
          </div>
        )}

        <form onSubmit={handleLogin}>
          <div className="form-group">
            <label htmlFor="login-email">Địa chỉ Email</label>
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="owner@greenhub.vn"
              autoComplete="email"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="login-password">Mật khẩu</label>
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Nhập mật khẩu"
              autoComplete="current-password"
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%', marginTop: '0.5rem', height: 42 }}
            disabled={submitting}
          >
            {submitting ? 'Đang đăng nhập...' : 'Đăng nhập vào hệ thống'}
          </button>
        </form>

        <div
          style={{
            marginTop: '1.25rem',
            paddingTop: '1rem',
            borderTop: '1px solid var(--border)',
          }}
        >
          <div className="muted" style={{ fontSize: '0.78rem', marginBottom: '0.5rem' }}>
            Điền nhanh tài khoản mẫu (môi trường phát triển):
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
            {DEV_ACCOUNTS.map((acc) => (
              <button
                key={acc.email}
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => {
                  setEmail(acc.email)
                  setPassword('greenhub123')
                  setError(null)
                }}
              >
                {acc.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
