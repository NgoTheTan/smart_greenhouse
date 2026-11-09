import { useState } from 'react'
import { MOCK_MODELS, MOCK_EXPERIMENT_KPIS } from '../lib/mockData'

export default function ModelsPage() {
  const [experimentActive, setExperimentActive] = useState(true)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
        <div>
          <h2>🧠 Quản lý Mô hình AI & Bảng Thí nghiệm</h2>
          <p className="muted" style={{ margin: 0 }}>So sánh chỉ số Machine Learning với Baseline & Thực nghiệm Fixed vs Adaptive</p>
        </div>
      </div>

      {/* DANH SÁCH MÔ HÌNH VÀ CHỈ SỐ SO VỚI BASELINE */}
      <div className="card">
        <div className="card-header">
          <div>
            <h3>📦 Các mô hình đang hoạt động (Tầng A2 & A3)</h3>
            <span className="muted" style={{ fontSize: '0.8rem' }}>Mô hình chỉ được kích hoạt (active) khi thắng Baseline trên tập Test</span>
          </div>
          <span className="badge ok">Tất cả mô hình vượt chuẩn</span>
        </div>

        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Tác vụ / Tên mô hình</th>
                <th>Thuật toán</th>
                <th>Phiên bản</th>
                <th>Chỉ số (Test Real)</th>
                <th>Baseline so sánh</th>
                <th>Đánh giá</th>
                <th>Trạng thái</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_MODELS.map((m) => (
                <tr key={m.task}>
                  <td>
                    <strong>{m.name}</strong>
                    <div className="muted" style={{ fontSize: '0.75rem' }}>Task: {m.task}</div>
                  </td>
                  <td><code>{m.algorithm}</code></td>
                  <td>{m.version}</td>
                  <td>
                    <strong style={{ color: 'var(--primary)' }}>{m.metric_val}</strong>
                    <span className="muted" style={{ fontSize: '0.75rem' }}> ({m.metric_name})</span>
                  </td>
                  <td>
                    <span className="muted">{m.baseline_val}</span>
                  </td>
                  <td>
                    <span className="badge ok">{m.status}</span>
                  </td>
                  <td>
                    <span className={`badge ${m.is_active ? 'success' : 'muted'}`}>
                      {m.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* BẢNG THÍ NGHIỆM SO SÁNH FIXED VS ADAPTIVE */}
      <div className="card">
        <div className="card-header">
          <div>
            <h3>⚖️ Thí nghiệm Thực chứng: Cố định (Fixed) vs Thích ứng AI (Adaptive)</h3>
            <span className="muted" style={{ fontSize: '0.8rem' }}>Đo đạc trong cùng điều kiện vi khí hậu để chứng minh hiệu quả AI</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className="muted" style={{ fontSize: '0.85rem' }}>Trạng thái thí nghiệm:</span>
            <button
              className={`btn btn-sm ${experimentActive ? 'btn-danger' : 'btn-primary'}`}
              onClick={() => setExperimentActive(!experimentActive)}
            >
              {experimentActive ? 'Dừng thu thập' : 'Bắt đầu thí nghiệm'}
            </button>
          </div>
        </div>

        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Chỉ số KPI đo lường</th>
                <th>Chế độ Cố định (Fixed)</th>
                <th>Chế độ Adaptive AI</th>
                <th>Mức độ cải thiện</th>
              </tr>
            </thead>
            <tbody>
              {MOCK_EXPERIMENT_KPIS.map((row) => (
                <tr key={row.kpi}>
                  <td><strong>{row.kpi}</strong></td>
                  <td><span className="muted">{row.fixed}</span></td>
                  <td><strong style={{ color: 'var(--primary)' }}>{row.adaptive}</strong></td>
                  <td>
                    <span className="badge ok" style={{ fontSize: '0.8rem' }}>
                      ✨ {row.diff}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

