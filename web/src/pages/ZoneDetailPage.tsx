import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceArea,
  LineChart,
  Line,
  Legend,
} from 'recharts'
import { generateMockReadings, MOCK_ACTUATORS } from '../lib/mockData'

export default function ZoneDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [data] = useState(generateMockReadings())
  const [chartType, setChartType] = useState<'vpd' | 'climate' | 'soil'>('vpd')
  const [actuators, setActuators] = useState(MOCK_ACTUATORS)
  const [strategy, setStrategy] = useState<'fixed' | 'adaptive'>('adaptive')
  const [lastCommandStatus, setLastCommandStatus] = useState<string | null>(null)
  const [durationInput, setDurationInput] = useState<number>(30)

  // Điểm đo mới nhất
  const current = data[data.length - 1]

  const handleToggleActuator = (actId: string, currentAction: string) => {
    const isTurningOn = currentAction === 'off'
    
    // Kiểm tra interlock: quạt và máy tạo ẩm không chạy cùng lúc
    if (isTurningOn) {
      if (actId === 'mist' && actuators.find((a) => a.id === 'fan')?.state === 'on') {
        setLastCommandStatus('❌ Lệnh bị từ chối: Vi phạm an toàn Interlock! Quạt đang chạy, không thể bật máy tạo ẩm.')
        return
      }
    }

    setLastCommandStatus(`⏳ Đang gửi lệnh [${actId}: ${isTurningOn ? 'BẬT ' + durationInput + 's' : 'TẮT'}]... (pending)`)

    setTimeout(() => {
      setActuators((prev) =>
        prev.map((a) => {
          if (a.id === actId) {
            return { ...a, state: isTurningOn ? 'on' : 'off' }
          }
          // Nếu bật quạt vì rủi ro thì ép tắt máy tạo ẩm
          if (isTurningOn && actId === 'fan' && a.id === 'mist') {
            return { ...a, state: 'off' }
          }
          return a
        })
      )
      setLastCommandStatus(`✅ Gateway phản hồi: ACK [${actId}] trạng thái applied lúc ${new Date().toLocaleTimeString()}`)
    }, 600)
  }

  const handleToggleMode = (actId: string) => {
    setActuators((prev) =>
      prev.map((a) => (a.id === actId ? { ...a, mode: a.mode === 'auto' ? 'manual' : 'auto' } : a))
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Link to="/" style={{ color: 'var(--muted)', textDecoration: 'none' }}>← Danh sách</Link>
            <h2 style={{ margin: 0 }}>🌱 Chi tiết Zone: {id?.includes('2') ? 'Zone 2 (Dâu tây)' : 'Zone 1 (Cà chua bi)'}</h2>
          </div>
          <p className="muted" style={{ margin: '0.25rem 0 0' }}>Theo dõi vi khí hậu, đất và dự báo AI thời gian thực</p>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--muted)' }}>Chiến lược:</span>
          <button
            className={`btn btn-sm ${strategy === 'fixed' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setStrategy('fixed')}
          >
            Fixed (Cố định)
          </button>
          <button
            className={`btn btn-sm ${strategy === 'adaptive' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setStrategy('adaptive')}
          >
            Adaptive (AI Thông minh)
          </button>
        </div>
      </div>

      {/* AI INSIGHT BANNER */}
      <div className="ai-card" style={{ marginBottom: '1.25rem' }}>
        <h3 style={{ margin: '0 0 0.5rem', color: 'var(--primary-text)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          🧠 Dự báo thông minh từ AI (Tầng A2 & A3)
        </h3>
        <div className="grid grid-cols-2" style={{ gap: '1rem', marginTop: '0.5rem' }}>
          <div style={{ background: 'rgba(255,255,255,0.7)', padding: '0.75rem', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.8rem', color: 'var(--muted)', fontWeight: 600 }}>DỰ BÁO NHU CẦU TƯỚI (A2):</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#0369a1', margin: '0.2rem 0' }}>
              Cần tưới sau ~42 phút
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--muted)' }}>
              Mô hình Ridge: Tốc độ khô 0.12%/phút • Thời lượng dự kiến bơm: <strong>18 giây</strong>
            </div>
          </div>

          <div style={{ background: 'rgba(255,255,255,0.7)', padding: '0.75rem', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.8rem', color: 'var(--muted)', fontWeight: 600 }}>RỦI RO NẤM BỆNH 15 PHÚT TỚI (A3):</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: current.vpd < 0.6 ? '#dc2626' : '#15803d', margin: '0.2rem 0' }}>
              {current.vpd < 0.6 ? '⚠️ Nguy cơ cao (Score 0.78)' : '✅ An toàn (Score 0.18)'}
            </div>
            <div style={{ fontSize: '0.78rem', color: 'var(--muted)' }}>
              LightGBM: Khuyến nghị đối lưu không khí nếu VPD tiếp tục duy trì dưới 0.4 kPa
            </div>
          </div>
        </div>
      </div>

      {/* METRIC TILES */}
      <div className="grid grid-cols-4" style={{ marginBottom: '1.25rem' }}>
        <div className="metric-tile vpd-optimal">
          <span className="label">VPD (Áp suất thiếu hụt)</span>
          <span className="value">
            {current.vpd} <span className="unit">kPa</span>
          </span>
          <div className="subtext">
            <span className="badge ok">Dải chuẩn: 0.8 - 1.2 kPa</span>
          </div>
        </div>

        <div className="metric-tile">
          <span className="label">Nhiệt độ không khí</span>
          <span className="value">
            {current.air_t} <span className="unit">°C</span>
          </span>
          <div className="subtext">
            <span className="muted">T_lá ước tính ≈ {(current.air_t - 1).toFixed(1)} °C</span>
          </div>
        </div>

        <div className="metric-tile">
          <span className="label">Độ ẩm không khí (RH)</span>
          <span className="value">
            {current.air_rh} <span className="unit">%</span>
          </span>
          <div className="subtext">
            <span className="muted">Nguy cơ nấm nếu &gt; 90%</span>
          </div>
        </div>

        <div className="metric-tile">
          <span className="label">Độ ẩm đất</span>
          <span className="value">
            {current.soil_m} <span className="unit">%</span>
          </span>
          <div className="subtext">
            <span className="badge info">Ngưỡng tưới: 45% - 70%</span>
          </div>
        </div>
      </div>

      {/* CHART BOX */}
      <div className="card">
        <div className="chart-header">
          <div>
            <h3 style={{ margin: 0 }}>📈 Biểu đồ lịch sử 24 giờ</h3>
            <span className="muted" style={{ fontSize: '0.8rem' }}>Dữ liệu cảm biến và dải tối ưu sinh học</span>
          </div>

          <div style={{ display: 'flex', gap: '0.35rem' }}>
            <button
              className={`btn btn-sm ${chartType === 'vpd' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setChartType('vpd')}
            >
              VPD & Dải tối ưu
            </button>
            <button
              className={`btn btn-sm ${chartType === 'climate' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setChartType('climate')}
            >
              Nhiệt & Ẩm không khí
            </button>
            <button
              className={`btn btn-sm ${chartType === 'soil' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setChartType('soil')}
            >
              Độ ẩm đất & Lần tưới
            </button>
          </div>
        </div>

        <div style={{ width: '100%', height: 320 }}>
          <ResponsiveContainer width="100%" height="100%">
            {chartType === 'vpd' ? (
              <AreaChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="time" stroke="#64748b" fontSize={12} />
                <YAxis domain={[0, 2.5]} stroke="#64748b" fontSize={12} unit=" kPa" />
                <Tooltip />
                <Legend />
                {/* Dải tối ưu của cây trồng: 0.8 đến 1.2 kPa */}
                <ReferenceArea y1={0.8} y2={1.2} fill="#dcfce7" fillOpacity={0.7} label="Dải tối ưu (0.8 - 1.2)" />
                <Area type="monotone" dataKey="vpd" stroke="#15803d" strokeWidth={2} fill="#bbf7d0" fillOpacity={0.4} name="VPD (kPa)" />
              </AreaChart>
            ) : chartType === 'climate' ? (
              <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="time" stroke="#64748b" fontSize={12} />
                <YAxis yAxisId="t" domain={[15, 40]} stroke="#f97316" fontSize={12} unit=" °C" />
                <YAxis yAxisId="rh" orientation="right" domain={[30, 100]} stroke="#0284c7" fontSize={12} unit=" %" />
                <Tooltip />
                <Legend />
                <Line yAxisId="t" type="monotone" dataKey="air_t" stroke="#f97316" strokeWidth={2} dot={false} name="Nhiệt độ (°C)" />
                <Line yAxisId="rh" type="monotone" dataKey="air_rh" stroke="#0284c7" strokeWidth={2} dot={false} name="Độ ẩm khí (%)" />
              </LineChart>
            ) : (
              <AreaChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="time" stroke="#64748b" fontSize={12} />
                <YAxis domain={[20, 100]} stroke="#64748b" fontSize={12} unit=" %" />
                <Tooltip />
                <Legend />
                <ReferenceArea y1={45} y2={70} fill="#e0f2fe" fillOpacity={0.6} label="Khoảng ẩm tối ưu (45 - 70%)" />
                <Area type="monotone" dataKey="soil_m" stroke="#0284c7" strokeWidth={2} fill="#bae6fd" fillOpacity={0.4} name="Độ ẩm đất (%)" />
              </AreaChart>
            )}
          </ResponsiveContainer>
        </div>
      </div>

      {/* BẢNG ĐIỀU KHIỂN ACTUATORS */}
      <div className="card">
        <div className="card-header">
          <div>
            <h3>⚙️ Điều khiển Chấp hành & An toàn Interlock</h3>
            <span className="muted" style={{ fontSize: '0.8rem' }}>Mọi lệnh Bật đều có thời hạn tự ngắt an toàn tại Gateway</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.85rem', color: 'var(--muted)' }}>Thời lượng bật:</span>
            <input
              type="number"
              style={{ width: 80, padding: '0.25rem 0.5rem' }}
              value={durationInput}
              min={5}
              max={600}
              onChange={(e) => setDurationInput(Number(e.target.value))}
            />
            <span style={{ fontSize: '0.85rem' }}>giây</span>
          </div>
        </div>

        {lastCommandStatus && (
          <div style={{ padding: '0.6rem 0.85rem', background: '#f8fafc', border: '1px solid var(--border)', borderRadius: 'var(--radius)', marginBottom: '1rem', fontSize: '0.85rem' }}>
            {lastCommandStatus}
          </div>
        )}

        <div className="grid grid-cols-4">
          {actuators.map((act) => {
            const isOn = act.state === 'on'
            return (
              <div key={act.id} className={`actuator-card ${isOn ? 'on' : ''}`}>
                <div>
                  <div className="title-row">
                    <strong>{act.name}</strong>
                    <span className="status-indicator" />
                  </div>
                  <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.5rem' }}>
                    <span className={`badge ${isOn ? 'success' : 'muted'}`}>
                      {isOn ? 'Đang chạy' : 'Đang tắt'}
                    </span>
                    <button
                      className={`badge ${act.mode === 'auto' ? 'info' : 'warning'}`}
                      style={{ cursor: 'pointer', border: 'none' }}
                      onClick={() => handleToggleMode(act.id)}
                      title="Bấm để chuyển Auto / Manual"
                    >
                      {act.mode.toUpperCase()}
                    </button>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.5rem' }}>
                  <button
                    className={`btn btn-sm ${isOn ? 'btn-danger' : 'btn-primary'}`}
                    style={{ flex: 1 }}
                    onClick={() => handleToggleActuator(act.id, act.state)}
                  >
                    {isOn ? 'TẮT NGAY' : `BẬT ${durationInput}s`}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

