import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { setToken } from '../lib/api'

export default function LoginPage() {
  const [email, setEmail] = useState('demo@greenhub.local')
  const [password, setPassword] = useState('greenhub123')
  const [role, setRole] = useState<'operator' | 'owner' | 'viewer'>('operator')
  const navigate = useNavigate()

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault()
    // Lưu token mô phỏng (hoặc JWT từ API khi backend online)
    setToken(`demo-jwt-token-role-${role}`)
    navigate('/')
  }

  return (
    <div style={{ maxWidth: 440, margin: '3rem auto' }}>
      <div className="card" style={{ padding: '2rem' }}>
        <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
          <h2 style={{ fontSize: '1.75rem', marginBottom: '0.25rem' }}>🌱 GreenHub</h2>
          <p className="muted" style={{ fontSize: '0.875rem' }}>Nền tảng Quản lý & Điều khiển Vi khí hậu Nhà kính</p>
        </div>

        <form onSubmit={handleLogin}>
          <div className="form-group">
            <label>Địa chỉ Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@greenhub.local"
              required
            />
          </div>

          <div className="form-group">
            <label>Mật khẩu</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label>Vai trò truy cập (RBAC)</label>
            <select value={role} onChange={(e) => setRole(e.target.value as any)}>
              <option value="operator">Operator (Vận hành & Điều khiển)</option>
              <option value="owner">Owner (Chủ Farm & Quản lý thiết bị)</option>
              <option value="viewer">Viewer (Chỉ xem số liệu)</option>
            </select>
          </div>

          <button type="submit" className="btn btn-primary" style={{ width: '100%', marginTop: '0.5rem', height: 42 }}>
            Đăng nhập vào hệ thống
          </button>
        </form>

        <div style={{ marginTop: '1.5rem', textAlign: 'center', fontSize: '0.8rem', color: 'var(--muted)' }}>
          Hỗ trợ đa tenant: Dữ liệu phân lập an toàn theo FarmID
        </div>
      </div>
    </div>
  )
}

