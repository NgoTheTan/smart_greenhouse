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

  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('owner@greenhub.vn')
  const [password, setPassword] = useState('greenhub123')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [farmName, setFarmName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (isAuthenticated) {
    return <Navigate to={from} replace />
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)

    if (mode === 'register') {
      if (!farmName.trim()) {
        setError('Vui lòng nhập tên Nông trại / Trang trại.')
        return
      }
      if (password.length < 6) {
        setError('Mật khẩu đăng ký phải có tối thiểu 6 ký tự.')
        return
      }
      if (password !== confirmPassword) {
        setError('Mật khẩu xác nhận không trùng khớp.')
        return
      }
    }

    setSubmitting(true)
    try {
      if (mode === 'login') {
        const res = await api<TokenResponse>('/auth/login', {
          method: 'POST',
          body: JSON.stringify({ email: email.trim(), password }),
        })
        await loginWithToken(res.access_token)
      } else {
        const res = await api<TokenResponse>('/auth/register', {
          method: 'POST',
          body: JSON.stringify({
            email: email.trim(),
            password,
            farm_name: farmName.trim(),
          }),
        })
        await loginWithToken(res.access_token)
      }
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
          <p className="muted" style={{ fontSize: '0.875rem', margin: '0 0 0.75rem' }}>
            Nền tảng Giám sát &amp; Điều khiển Vi khí hậu Nhà kính
          </p>
          <div
            style={{
              display: 'inline-block',
              background: '#f1f5f9',
              padding: '0.25rem 0.85rem',
              borderRadius: '9999px',
              fontSize: '0.82rem',
              fontWeight: 600,
              color: 'var(--primary-dark, #15803d)',
            }}
          >
            {mode === 'login' ? '🔐 Đăng nhập hệ thống' : '📝 Đăng ký tài khoản mới'}
          </div>
        </div>

        {error && (
          <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="login-email">Địa chỉ Email *</label>
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="VD: nongdan@greenhub.vn"
              autoComplete="email"
              required
            />
          </div>

          {mode === 'register' && (
            <div className="form-group">
              <label htmlFor="register-farm">Tên Nông trại / Trang trại *</label>
              <input
                id="register-farm"
                type="text"
                value={farmName}
                onChange={(e) => setFarmName(e.target.value)}
                placeholder="VD: Nông trại Hữu cơ Đà Lạt"
                required
              />
            </div>
          )}

          <div className="form-group">
            <label htmlFor="login-password">
              Mật khẩu * {mode === 'register' && <span className="muted">(tối thiểu 6 ký tự)</span>}
            </label>
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Nhập mật khẩu"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              required
            />
          </div>

          {mode === 'register' && (
            <div className="form-group">
              <label htmlFor="register-confirm-password">Xác nhận mật khẩu *</label>
              <input
                id="register-confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Nhập lại mật khẩu"
                autoComplete="new-password"
                required
              />
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%', marginTop: '0.65rem', height: 42, fontSize: '0.95rem', fontWeight: 600 }}
            disabled={submitting}
          >
            {submitting
              ? mode === 'login'
                ? 'Đang đăng nhập...'
                : 'Đang khởi tạo tài khoản...'
              : mode === 'login'
                ? 'Đăng nhập vào hệ thống'
                : 'Tạo tài khoản & Bắt đầu'}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: '1rem', fontSize: '0.85rem' }}>
          {mode === 'login' ? (
            <span className="muted">
              Chưa có tài khoản?{' '}
              <button
                type="button"
                onClick={() => {
                  setMode('register')
                  setError(null)
                  if (email === 'owner@greenhub.vn') setEmail('')
                  if (password === 'greenhub123') setPassword('')
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--primary)',
                  fontWeight: 600,
                  cursor: 'pointer',
                  padding: 0,
                  textDecoration: 'underline',
                }}
              >
                Đăng ký ngay
              </button>
            </span>
          ) : (
            <span className="muted">
              Đã có tài khoản?{' '}
              <button
                type="button"
                onClick={() => {
                  setMode('login')
                  setError(null)
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--primary)',
                  fontWeight: 600,
                  cursor: 'pointer',
                  padding: 0,
                  textDecoration: 'underline',
                }}
              >
                Đăng nhập ngay
              </button>
            </span>
          )}
        </div>

        {mode === 'login' && (
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
        )}
      </div>
    </div>
  )
}
