import { useState } from 'react'

export default function CropProfilesPage() {
  const [selectedCrop, setSelectedCrop] = useState<'tomato' | 'strawberry'>('tomato')
  const [mode, setMode] = useState<'demo' | 'real'>('demo')
  const [saved, setSaved] = useState(false)

  // Thông số ngưỡng
  const [vpdMin, setVpdMin] = useState(0.8)
  const [vpdMax, setVpdMax] = useState(1.2)
  const [soilMin, setSoilMin] = useState(45)
  const [soilMax, setSoilMax] = useState(70)

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
        <div>
          <h2>🌿 Hồ sơ Cây trồng (Crop Profiles)</h2>
          <p className="muted" style={{ margin: 0 }}>Cấu hình ngưỡng sinh học và thông số thời gian điều khiển</p>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              className={`btn btn-sm ${selectedCrop === 'tomato' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setSelectedCrop('tomato')}
            >
              🍅 Cà chua bi (Zone 1)
            </button>
            <button
              className={`btn btn-sm ${selectedCrop === 'strawberry' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setSelectedCrop('strawberry')}
            >
              🍓 Dâu tây (Zone 2)
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--muted)' }}>Bộ thông số:</span>
            <button
              className={`btn btn-sm ${mode === 'demo' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => {
                setMode('demo')
                setSoilMin(50)
                setSoilMax(65)
              }}
            >
              Demo (Thu nhỏ thời gian)
            </button>
            <button
              className={`btn btn-sm ${mode === 'real' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => {
                setMode('real')
                setSoilMin(45)
                setSoilMax(70)
              }}
            >
              Real (Thực tế nông nghiệp)
            </button>
          </div>
        </div>

        {saved && (
          <div style={{ padding: '0.6rem 0.85rem', background: '#dcfce7', color: '#166534', borderRadius: '6px', marginBottom: '1rem', fontSize: '0.85rem' }}>
            ✅ Đã lưu hồ sơ cây trồng! Phiên bản cấu hình <code>cfg_version</code> đã tăng và đang đẩy xuống Gateway.
          </div>
        )}

        <form onSubmit={handleSave}>
          <div className="grid grid-cols-2" style={{ gap: '1.5rem', marginBottom: '1.5rem' }}>
            <div>
              <h4 style={{ margin: '0 0 0.75rem', color: 'var(--primary-text)' }}>1. Ngưỡng Vi khí hậu & VPD</h4>
              <div className="form-group">
                <label>VPD Tối ưu Tối thiểu (Optimal Min - kPa)</label>
                <input
                  type="number"
                  step="0.05"
                  value={vpdMin}
                  onChange={(e) => setVpdMin(Number(e.target.value))}
                  required
                />
                <span className="muted" style={{ fontSize: '0.75rem' }}>Dưới mức này có nguy cơ nấm bệnh, quạt đối lưu sẽ kích hoạt</span>
              </div>

              <div className="form-group">
                <label>VPD Tối ưu Tối đa (Optimal Max - kPa)</label>
                <input
                  type="number"
                  step="0.05"
                  value={vpdMax}
                  onChange={(e) => setVpdMax(Number(e.target.value))}
                  required
                />
                <span className="muted" style={{ fontSize: '0.75rem' }}>Trên mức này không khí quá khô, kích hoạt máy tạo ẩm</span>
              </div>
            </div>

            <div>
              <h4 style={{ margin: '0 0 0.75rem', color: 'var(--primary-text)' }}>2. Ngưỡng Ẩm đất & Tưới (Hysteresis)</h4>
              <div className="form-group">
                <label>Độ ẩm đất tối thiểu cần tưới (Soil Min - %)</label>
                <input
                  type="number"
                  value={soilMin}
                  onChange={(e) => setSoilMin(Number(e.target.value))}
                  required
                />
                <span className="muted" style={{ fontSize: '0.75rem' }}>Khi đất khô chạm ngưỡng này, bơm sẽ tự động kích hoạt</span>
              </div>

              <div className="form-group">
                <label>Độ ẩm đất ngắt tưới (Soil Max - %)</label>
                <input
                  type="number"
                  value={soilMax}
                  onChange={(e) => setSoilMax(Number(e.target.value))}
                  required
                />
                <span className="muted" style={{ fontSize: '0.75rem' }}>Ngưỡng ngắt bơm để chống úng rễ</span>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button type="submit" className="btn btn-primary">
              💾 Lưu Cấu hình & Đồng bộ Gateway
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

