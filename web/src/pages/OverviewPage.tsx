import { Link } from 'react-router-dom'
import { MOCK_GREENHOUSES } from '../lib/mockData'

export default function OverviewPage() {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
        <div>
          <h2>🌿 Tổng quan các Nhà kính & Farm</h2>
          <p className="muted" style={{ margin: 0 }}>Hệ thống quản lý vi khí hậu đa vùng GreenHub</p>
        </div>
        <div className="badge ok">
          ● 2 Nhà kính đang hoạt động
        </div>
      </div>

      <div className="grid grid-cols-2">
        {MOCK_GREENHOUSES.map((gh) => (
          <div key={gh.id} className="card">
            <div className="card-header">
              <div>
                <h3 style={{ marginBottom: '0.25rem' }}>{gh.name}</h3>
                <span className="muted" style={{ fontSize: '0.8rem' }}>📍 {gh.location}</span>
              </div>
              <span className={`badge ${gh.online ? 'ok' : 'bad'}`}>
                {gh.online ? 'Online' : 'Offline'}
              </span>
            </div>

            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', fontSize: '0.85rem' }}>
              <div>
                <span className="muted">Cảnh báo đang mở: </span>
                <strong style={{ color: gh.open_alerts > 0 ? 'var(--danger)' : 'var(--success)' }}>
                  {gh.open_alerts}
                </strong>
              </div>
              <div>
                <span className="muted">Số vùng (Zones): </span>
                <strong>{gh.zones.length}</strong>
              </div>
            </div>

            <div>
              <h4 style={{ fontSize: '0.9rem', marginBottom: '0.5rem', color: 'var(--muted)' }}>CÁC VÙNG TRỒNG (ZONES):</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {gh.zones.map((z) => (
                  <Link
                    key={z.id}
                    to={`/zones/${z.id}`}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '0.65rem 0.85rem',
                      background: '#f8fafc',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius)',
                      textDecoration: 'none',
                      color: 'inherit',
                      fontWeight: 500,
                    }}
                  >
                    <span>🌱 {z.name}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span className="badge info" style={{ fontSize: '0.7rem' }}>
                        Chiến lược: {z.strategy === 'adaptive' ? 'Adaptive AI' : 'Fixed'}
                      </span>
                      <span style={{ color: 'var(--primary)', fontWeight: 600 }}>Xem chi tiết →</span>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

