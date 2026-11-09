// Mock Data dự phòng cho GreenHub Web Console (phục vụ test & phát triển độc lập)

export interface ReadingMock {
  time: string
  air_t: number
  air_rh: number
  vpd: number
  soil_m: number
  lux: number
  pump_active: boolean
  fan_active: boolean
}

// Sinh chuỗi dữ liệu 24 điểm đo (mỗi giờ) cho biểu đồ
export function generateMockReadings(): ReadingMock[] {
  const readings: ReadingMock[] = []
  const now = new Date()

  for (let i = 24; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 3600 * 1000)
    const hour = d.getHours()
    
    // Nhiệt độ dao động 22 - 32 độ theo giờ
    const temp = 24 + Math.sin((hour - 6) / 24 * 2 * Math.PI) * 6 + (Math.random() - 0.5)
    // Ẩm nghịch biến với nhiệt
    const rh = 85 - Math.sin((hour - 6) / 24 * 2 * Math.PI) * 25 + (Math.random() - 0.5) * 3
    // VPD tính từ temp và RH
    const vpsat = 0.61078 * Math.exp((17.27 * temp) / (temp + 237.3))
    const vpd = Math.max(0.1, Number((vpsat * (1 - rh / 100)).toFixed(2)))
    
    // Đất khô dần, tưới lúc 8h sáng
    let soil = 65 - ((24 - i) % 12) * 2.5 + (Math.random() - 0.5)
    const pump = hour === 8 || hour === 17
    const fan = temp > 29 || vpd < 0.5

    if (pump) soil += 18

    readings.push({
      time: `${hour.toString().padStart(2, '0')}:00`,
      air_t: Number(temp.toFixed(1)),
      air_rh: Number(rh.toFixed(1)),
      vpd,
      soil_m: Number(soil.toFixed(1)),
      lux: hour >= 6 && hour <= 18 ? Math.round(15000 + Math.sin((hour - 6) / 12 * Math.PI) * 35000) : 0,
      pump_active: pump,
      fan_active: fan,
    })
  }
  return readings
}

export const MOCK_GREENHOUSES = [
  {
    id: 'gh-01',
    name: 'Nhà kính Fomex Mini (Site thật)',
    location: 'Phòng Lab IoT',
    online: true,
    open_alerts: 1,
    zones: [
      { id: 'zone-01', name: 'Zone 1 (Cà chua bi)', zone_index: 1, strategy: 'adaptive' },
      { id: 'zone-02', name: 'Zone 2 (Dâu tây)', zone_index: 2, strategy: 'fixed' },
    ],
  },
  {
    id: 'gh-sim-02',
    name: 'Nhà kính Farm B (Mô phỏng Simulator)',
    location: 'Đà Lạt - Farm 2',
    online: true,
    open_alerts: 0,
    zones: [
      { id: 'zone-sim-03', name: 'Zone 1 (Dưa lưới)', zone_index: 1, strategy: 'fixed' },
    ],
  },
]

export const MOCK_ACTUATORS = [
  { id: 'pump_1', name: 'Bơm nước Zone 1', zone: 1, state: 'off', mode: 'auto', max_run_s: 30 },
  { id: 'pump_2', name: 'Bơm nước Zone 2', zone: 2, state: 'off', mode: 'auto', max_run_s: 30 },
  { id: 'fan', name: 'Quạt đối lưu / hút ẩm', zone: 0, state: 'off', mode: 'auto', max_run_s: 180 },
  { id: 'mist', name: 'Máy tạo sương ẩm', zone: 0, state: 'off', mode: 'manual', max_run_s: 120 },
]

export const MOCK_ALERTS = [
  {
    id: 'alt-01',
    severity: 'warning',
    type: 'DISEASE_RISK_FORECAST',
    title: 'Cảnh báo nguy cơ nấm bệnh (A3 AI)',
    message: 'VPD dự báo duy trì dưới 0.4 kPa liên tục trong 15 phút tới. Quạt sẽ kích hoạt nếu chế độ Auto.',
    time: '10 phút trước',
    status: 'raised',
    feedback: null as 'true_positive' | 'false_positive' | null,
  },
  {
    id: 'alt-02',
    severity: 'critical',
    type: 'SOIL_MOISTURE_LOW',
    title: 'Độ ẩm đất thấp dưới ngưỡng tối thiểu',
    message: 'Zone 1: Độ ẩm đất 42% (ngưỡng min 45%). Cần cấp nước.',
    time: '35 phút trước',
    status: 'acknowledged',
    feedback: 'true_positive' as const,
  },
]

export const MOCK_MODELS = [
  {
    task: 'risk_forecast',
    name: 'Dự báo nguy cơ nấm (A3)',
    algorithm: 'LightGBM Classifier',
    version: 'v2.1',
    trained_at: '2026-11-06 14:00',
    is_active: true,
    metric_name: 'PR-AUC / F1',
    metric_val: '0.84 / 0.81',
    baseline_val: '0.62 / 0.58',
    status: 'Thắng baseline (+23%)',
  },
  {
    task: 'irrigation_eta',
    name: 'Dự báo thời điểm cần tưới (A2)',
    algorithm: 'Ridge Regression',
    version: 'v1.4',
    trained_at: '2026-11-05 20:30',
    is_active: true,
    metric_name: 'MAE (sai số phút)',
    metric_val: '14.2 phút',
    baseline_val: '28.5 phút',
    status: 'Thắng baseline (giảm 50% sai số)',
  },
  {
    task: 'pump_response',
    name: 'Độ nhạy bơm Zone 1 (A2)',
    algorithm: 'Median gain estimation',
    version: 'v1.0',
    trained_at: '2026-11-04 10:00',
    is_active: true,
    metric_name: 'Gain',
    metric_val: '+0.58 %/giây',
    baseline_val: 'N/A',
    status: 'Đã sẵn sàng cho Adaptive',
  },
  {
    task: 'fan_response',
    name: 'Độ nhạy quạt hút (A2)',
    algorithm: 'Median gain estimation',
    version: 'v1.0',
    trained_at: '2026-11-04 10:00',
    is_active: true,
    metric_name: 'Rate',
    metric_val: '+0.012 kPa/giây',
    baseline_val: 'N/A',
    status: 'Đã sẵn sàng cho Adaptive',
  },
]

export const MOCK_EXPERIMENT_KPIS = [
  {
    kpi: 'Số lần bật/tắt bơm mỗi ngày',
    fixed: '14 lần',
    adaptive: '8 lần',
    diff: 'Giảm 42.8% (ít sốc rễ hơn)',
    positive: true,
  },
  {
    kpi: '% thời gian VPD trong dải tối ưu (0.8 - 1.2 kPa)',
    fixed: '62.4 %',
    adaptive: '84.1 %',
    diff: '+21.7 % thời gian tối ưu',
    positive: true,
  },
  {
    kpi: 'Overshoot ẩm đất (vọt lố dư ẩm)',
    fixed: '+9.4 %',
    adaptive: '+2.1 %',
    diff: 'Giảm lãng phí & úng rễ',
    positive: true,
  },
  {
    kpi: 'Tổng thời gian bơm nước (lượng nước)',
    fixed: '420 giây / ngày',
    adaptive: '315 giây / ngày',
    diff: 'Tiết kiệm 25% nước tưới',
    positive: true,
  },
  {
    kpi: 'Tỉ lệ cảnh báo sai (False Positive)',
    fixed: '28 % (dùng luật đơn)',
    adaptive: '9 % (AI LightGBM)',
    diff: 'Độ chính xác cao hơn rõ rệt',
    positive: true,
  },
]

