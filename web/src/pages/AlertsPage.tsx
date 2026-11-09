import { useState } from 'react'
import { MOCK_ALERTS } from '../lib/mockData'

export default function AlertsPage() {
  const [alerts, setAlerts] = useState(MOCK_ALERTS)

  const handleAck = (id: string) => {
    setAlerts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, status: 'acknowledged' } : a))
    )
  }

  const handleFeedback = (id: string, feedback: 'true_positive' | 'false_positive') => {
    setAlerts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, feedback } : a))
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
        <div>
          <h2>🔔 Trung tâm Cảnh báo & Đánh giá AI</h2>
          <p className="muted" style={{ margin: 0 }}>Vòng phản hồi người dùng (Human-in-the-loop) để cải thiện độ chính xác của AI</p>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Danh sách cảnh báo đang diễn ra</h3>
          <span className="badge warning">
            {alerts.filter((a) => a.status !== 'resolved').length} cảnh báo cần xử lý
          </span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {alerts.map((alt) => {
            const isCrit = alt.severity === 'critical'
            return (
              <div
                key={alt.id}
                style={{
                  border: `1px solid ${isCrit ? '#fecaca' : '#fed7aa'}`,
                  background: isCrit ? '#fef2f2' : '#fffbeb',
                  borderRadius: 'var(--radius)',
                  padding: '1rem',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  flexWrap: 'wrap',
                  gap: '1rem',
                }}
              >
                <div style={{ flex: 1, minWidth: 260 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
                    <span className={`badge ${isCrit ? 'bad' : 'warning'}`}>
                      {alt.severity.toUpperCase()}
                    </span>
                    <strong style={{ fontSize: '0.95rem' }}>{alt.title}</strong>
                    <span className="muted" style={{ fontSize: '0.75rem' }}>({alt.time})</span>
                  </div>
                  <p style={{ margin: '0.25rem 0', fontSize: '0.85rem' }}>{alt.message}</p>
                  <span className="muted" style={{ fontSize: '0.75rem' }}>
                    Mã sự kiện: <code>{alt.type}</code> • Trạng thái: <strong>{alt.status}</strong>
                  </span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.5rem' }}>
                  <div style={{ display: 'flex', gap: '0.35rem' }}>
                    {alt.status === 'raised' && (
                      <button className="btn btn-sm btn-primary" onClick={() => handleAck(alt.id)}>
                        ✓ Xác nhận (Ack)
                      </button>
                    )}
                  </div>

                  {/* Nút Feedback vòng lặp người dùng */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', background: '#fff', padding: '0.3rem 0.5rem', borderRadius: '6px', border: '1px solid var(--border)' }}>
                    <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--muted)' }}>
                      AI cảnh báo:
                    </span>
                    <button
                      className={`btn btn-sm ${alt.feedback === 'true_positive' ? 'btn-primary' : 'btn-secondary'}`}
                      style={{ fontSize: '0.72rem', padding: '0.15rem 0.45rem' }}
                      onClick={() => handleFeedback(alt.id, 'true_positive')}
                    >
                      👍 Đúng
                    </button>
                    <button
                      className={`btn btn-sm ${alt.feedback === 'false_positive' ? 'btn-danger' : 'btn-secondary'}`}
                      style={{ fontSize: '0.72rem', padding: '0.15rem 0.45rem' }}
                      onClick={() => handleFeedback(alt.id, 'false_positive')}
                    >
                      👎 Báo giả (Sai)
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

