import { useState } from 'react'

export default function DevicesPage() {
  const [soilDry, setSoilDry] = useState(2900)
  const [soilWet, setSoilWet] = useState(1300)
  const [calibrated, setCalibrated] = useState(false)

  const handleSaveCalibration = (e: React.FormEvent) => {
    e.preventDefault()
    setCalibrated(true)
    setTimeout(() => setCalibrated(false), 3000)
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
        <div>
          <h2>📡 Quản lý Thiết bị & Cảm biến</h2>
          <p className="muted" style={{ margin: 0 }}>Theo dõi Gateway ESP32, Node cảm biến ESP-NOW và hiệu chuẩn đất</p>
        </div>
      </div>

      {/* GATEWAY SECTION */}
      <div className="card">
        <div className="card-header">
          <h3>🚪 Gateway ESP32 (Hub trung tâm)</h3>
          <span className="badge ok">● Online (MQTT TLS)</span>
        </div>

        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Tên Gateway</th>
                <th>Địa chỉ MAC / ClientID</th>
                <th>Sóng RSSI</th>
                <th>Phiên bản CFG</th>
                <th>Failsafe Timeout</th>
                <th>Thấy lần cuối</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Gateway Nhà Kính Mini</strong></td>
                <td><code>ESP32_GW_LAB_01</code></td>
                <td><span className="badge ok">-58 dBm (Tốt)</span></td>
                <td>v3 (Đã đồng bộ)</td>
                <td>60 giây</td>
                <td>Vừa xong (12s trước)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* NODES SECTION */}
      <div className="card">
        <div className="card-header">
          <h3>🌱 Các Node cảm biến (ESP-NOW)</h3>
          <button className="btn btn-sm btn-secondary">+ Quét Node mới</button>
        </div>

        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Địa chỉ MAC</th>
                <th>Zone ghép nối</th>
                <th>Cảm biến tích hợp</th>
                <th>Sóng ESP-NOW</th>
                <th>Pin / Nguồn</th>
                <th>Chất lượng (A1)</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><code>24:6F:28:AB:12:01</code></td>
                <td><span className="badge info">Zone 1</span></td>
                <td>AHT20 + Ẩm đất + BH1750 (Lux)</td>
                <td>-62 dBm</td>
                <td>USB 5V</td>
                <td><span className="badge ok">OK (Chuẩn)</span></td>
                <td><button className="btn btn-sm btn-secondary">Đổi Zone</button></td>
              </tr>
              <tr>
                <td><code>24:6F:28:AB:12:02</code></td>
                <td><span className="badge info">Zone 2</span></td>
                <td>AHT20 + Ẩm đất</td>
                <td>-65 dBm</td>
                <td>USB 5V</td>
                <td><span className="badge ok">OK (Chuẩn)</span></td>
                <td><button className="btn btn-sm btn-secondary">Đổi Zone</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* SOIL CALIBRATION SECTION */}
      <div className="card">
        <div className="card-header">
          <h3>⚖️ Hiệu chuẩn Cảm biến Độ ẩm đất 2 điểm</h3>
        </div>
        <p className="muted" style={{ fontSize: '0.85rem' }}>
          Cảm biến điện dung v1.2 đo giá trị ADC 12-bit (0 – 4095). Nhập giá trị đọc được khi để khô ngoài không khí và khi cắm vào đất ướt bão hòa nước.
        </p>

        {calibrated && (
          <div style={{ padding: '0.5rem 0.75rem', background: '#dcfce7', color: '#166534', borderRadius: '6px', marginBottom: '1rem', fontSize: '0.85rem' }}>
            ✅ Đã lưu cấu hình hiệu chuẩn! Bản tin CFG đã được đồng bộ xuống Gateway.
          </div>
        )}

        <form onSubmit={handleSaveCalibration} style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <label>ADC Điểm Khô (Dry RAW)</label>
            <input
              type="number"
              value={soilDry}
              onChange={(e) => setSoilDry(Number(e.target.value))}
              placeholder="VD: 2900"
              required
            />
          </div>

          <div style={{ flex: 1, minWidth: 200 }}>
            <label>ADC Điểm Ướt (Wet RAW)</label>
            <input
              type="number"
              value={soilWet}
              onChange={(e) => setSoilWet(Number(e.target.value))}
              placeholder="VD: 1300"
              required
            />
          </div>

          <button type="submit" className="btn btn-primary" style={{ height: 38 }}>
            Lưu hiệu chuẩn & Đồng bộ Gateway
          </button>
        </form>
      </div>
    </div>
  )
}

