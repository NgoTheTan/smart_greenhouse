export type UserRole = 'owner'
export type ActuatorName = 'pump_1' | 'pump_2' | 'fan' | 'light' | (string & {})
export type ActuatorMode = 'auto' | 'manual'
export type AlertSeverity = 'info' | 'warning' | 'critical'
export type AlertState = 'raised' | 'notified' | 'acknowledged' | 'resolved'
export type CropCode = 'tomato_cherry' | 'strawberry' | 'lettuce' | 'cucumber' | 'bell_pepper'
export type CycleStatus = 'active' | 'harvested' | 'abandoned'

export interface User {
  id: string
  farm_id: string
  email: string
  role: UserRole
  created_at: string
  farm_name?: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface Zone {
  id: string
  greenhouse_id: string
  zone_index: number
  name: string | null
  crop_profile_id: string | null
  area_m2: number | null
  planting_date: string | null
  pump_channel: number | null
  soil_dry_raw: number | null
  soil_wet_raw: number | null
}

export interface Greenhouse {
  id: string
  farm_id: string
  name: string | null
  location: string | null
  created_at: string
  gateway_id: string | null
  is_simulated: boolean
  online: boolean
  open_alerts: number
  zones: Zone[]
}

export interface GatewayProvisionResponse {
  gateway_id: string
  farm_id: string
  greenhouse_id: string
  mqtt_username: string
  mqtt_password: string
  host: string
  port: number
  is_simulated: boolean
}

export interface GatewayStatus {
  id: string
  greenhouse_id: string
  mqtt_username: string
  is_simulated: boolean
  online: boolean
  last_seen: string | null
  fw_version: string | null
  rssi: number | null
  reported: {
    actuators?: Partial<Record<ActuatorName, 'on' | 'off'>>
    uptime_s?: number
    heap?: number
    queue_len?: number
    nodes?: Array<{ mac: string; zone: number; last_seen_s: number }>
    [key: string]: unknown
  }
  desired: {
    modes?: Partial<Record<ActuatorName, { mode: ActuatorMode; until: string | null }>>
    [key: string]: unknown
  }
  cfg_version_desired: number
  cfg_version_reported: number
}

export interface ConfigSyncResponse {
  greenhouse_id: string
  cfg_version_desired: number
  cfg_version_reported: number
  synced: boolean
  updated_at: string
}

export interface DeviceNode {
  id: string
  mac_address: string
  greenhouse_id: string | null
  zone_id: string | null
  status: 'discovered' | 'paired' | 'offline' | string
  firmware_version: string | null
  battery_mv: number | null
  rssi: number | null
  first_seen: string
  last_seen: string | null
}

export interface CropParameters {
  schema_version: number
  vpd: {
    optimal: [number, number]
    low_crit: number
    low_off: number
    high_crit: number
    leaf_offset_c: number
  }
  temp_c: {
    optimal: [number, number]
  }
  light: {
    dli_optimal: [number, number]
    lux_min?: number
    lux_max?: number
  }
  soil_moisture_pct: {
    min: number
    max: number
  }
  disease: {
    rh_gt: number
    temp_range_c: [number, number]
    fungal_minutes_alert: number
  }
  irrigation: {
    max_run_s: number
    min_gap_s: number
    max_total_s_per_hour: number
    soil_settle_s: number
  }
  fan: {
    min_on_s: number
    max_on_s: number
  }
  risk: {
    vpd_low_duration_min: number
  }
  cycle: {
    days: number
  }
  yield: {
    reference_kg_m2: number
  }
  ai: {
    recommend_window_h: number
    min_cycle_hours: number
    inference_interval_s: number
    min_coverage: number
  }
  sample_interval_s: number
  failsafe: {
    temp_critical_high_c: number
    soil_moisture_critical_low_pct: number
  }
}

export interface CropProfile {
  id: string
  farm_id: string | null
  crop_code: CropCode | string
  crop_name: string
  variety: string | null
  schema_version: number
  parameters_json: CropParameters
}

export interface ReadingPoint {
  ts: string
  air_temp: number | null
  air_rh: number | null
  vpd: number | null
  soil_moisture: number | null
  soil_raw: number | null
  lux: number | null
  quality: string | null
  source: string | null
}

export interface DliResponse {
  zone_id: string
  date: string
  dli_mol_m2_day: number
  sample_count: number
}

export interface CommandItem {
  id: string
  greenhouse_id: string
  actuator: ActuatorName | string
  action: 'on' | 'off'
  duration_s: number | null
  source: 'auto' | 'manual' | string
  requested_by: string | null
  reason: string | null
  status: 'pending' | 'sent' | 'applied' | 'rejected' | 'expired' | 'timeout' | string
  reject_reason: string | null
  created_at: string
  sent_at: string | null
  acked_at: string | null
  expires_at: string
}

export interface AlertItem {
  id: string
  greenhouse_id: string
  zone_id: string | null
  alert_type: string
  severity: AlertSeverity
  state: AlertState
  dedupe_key: string
  payload: Record<string, unknown> | null
  created_at: string
  notified_at: string | null
  acknowledged_at: string | null
  acked_by: string | null
  resolved_at: string | null
}

export interface CropCycleFeedback {
  variety?: string
  quality_rating?: number
  loss_percentage?: number
  ai_accuracy_evaluation?: 'accurate' | 'overestimated' | 'underestimated'
  farmer_notes?: string
  yield_kg_m2?: number
}

export interface CropCycle {
  id: string
  zone_id: string
  crop_profile_id: string
  crop_code: string | null
  crop_name: string | null
  started_at: string
  harvested_at: string | null
  area_m2: number
  yield_kg: number | null
  yield_kg_m2: number | null
  status: CycleStatus
  notes: string | null
  feedback?: CropCycleFeedback | null
  created_by: string | null
  created_at: string
}

export interface YieldForecastDetails {
  crop_code?: string
  reference_kg_m2?: number
  cycle_days_elapsed?: number
  window_hours?: number
  interval?: [number, number]
  interval_relative?: [number, number]
  coverage?: number
  low_confidence?: boolean
  ood_features?: string[]
  features?: Record<string, number | null>
}

export interface RecommendationCandidate {
  crop_code: string
  crop_name: string
  relative_yield: number
  expected_kg_m2: number
  interval: [number, number]
  reasons: string[]
}

export interface CropRecommendationDetails {
  window_h?: number
  coverage?: number
  low_confidence?: boolean
  ood_features?: string[]
  climate_summary?: {
    t_mean?: number | null
    t_day_mean?: number | null
    t_night_mean?: number | null
    rh_mean?: number | null
    vpd_mean?: number | null
    dli_mean?: number | null
  }
  features?: Record<string, number | null>
  ranking?: RecommendationCandidate[]
}

export interface PredictionItem<T = Record<string, unknown>> {
  id: string
  ts: string
  task: 'yield_forecast' | 'crop_recommendation' | string
  greenhouse_id: string
  zone_id: string | null
  crop_cycle_id: string | null
  model_id: string | null
  value: number | null
  score: number | null
  details: T | null
}

export interface ModelSourceMetrics {
  n: number
  mae_kg_m2: number
  rmse_kg_m2: number
}

export interface ModelCropMetrics {
  n: number
  mae_kg_m2: number
  rmse_kg_m2: number
  r2: number
}

export interface ModelMetricsBlock {
  n?: number
  mae_kg_m2?: number
  rmse_kg_m2?: number
  r2?: number
  mape?: number
  top1_accuracy?: number
  ndcg_at_3?: number
  n_eval?: number
  by_crop?: Record<string, ModelCropMetrics>
  by_source?: Record<string, ModelSourceMetrics>
  train_stats?: Record<string, { mean: number; std: number }>
}

export interface FeatureDriftEntry {
  train_mean: number | null
  train_std: number | null
  recent_mean: number | null
  recent_std: number | null
  z_score: number | null
  drifted: boolean
  n_recent: number
}

export interface MlModelItem {
  id: string
  task: string
  version: number
  feature_version: number
  artifact_path: string
  trained_at: string
  n_samples: number | null
  n_greenhouses: number | null
  source_mix: Record<string, number> | null
  crops: Array<{ crop_code: string; n: number; reference_kg_m2: number }> | null
  metrics: ModelMetricsBlock | null
  baseline_metrics: { B0?: ModelMetricsBlock; B1?: ModelMetricsBlock } | null
  is_active: boolean
  notes: string | null
  feature_drift: {
    window_days: number
    n_predictions: number
    features: Record<string, FeatureDriftEntry>
  } | null
}

export interface WsEvent {
  type:
    | 'telemetry'
    | 'alert'
    | 'command_status'
    | 'device_status'
    | 'config_sync'
    | 'prediction'
    | 'crop_cycle'
  data: Record<string, unknown>
}

export const CROP_NAMES_VI: Record<string, string> = {
  tomato_cherry: 'Cà chua bi',
  strawberry: 'Dâu tây',
  lettuce: 'Xà lách',
  cucumber: 'Dưa leo',
  bell_pepper: 'Ớt chuông',
}

export const ALERT_TYPE_LABELS: Record<string, string> = {
  DISEASE_RISK: 'Nguy cơ nấm bệnh',
  HEAT_STRESS: 'Sốc nhiệt',
  SOIL_DRY: 'Đất quá khô',
  SENSOR_FAULT: 'Lỗi cảm biến',
  DEVICE_OFFLINE: 'Mất kết nối Gateway',
  GATEWAY_OFFLINE: 'Mất kết nối Gateway',
  FAILSAFE_ACTIVE: 'Gateway đang chạy Failsafe',
  YIELD_FORECAST_LOW: 'Năng suất dự kiến thấp',
}

export const ACTUATOR_LABELS: Record<ActuatorName, string> = {
  pump_1: 'Bơm tưới Zone 1',
  pump_2: 'Bơm tưới Zone 2',
  fan: 'Quạt đối lưu',
  light: 'Đèn chiếu sáng',
}

export const QUALITY_LABELS: Record<string, string> = {
  ok: 'Hợp lệ',
  stuck: 'Cảm biến bị kẹt',
  spike: 'Nhiễu đột biến',
  dropout: 'Mất tín hiệu / Thiếu dữ liệu',
  out_of_range: 'Ngoài dải vật lý',
}

export function formatCropName(code: string | null | undefined, fallbackName?: string | null): string {
  if (fallbackName) return fallbackName
  if (!code) return 'Chưa gắn cây'
  return CROP_NAMES_VI[code] ?? code
}

export function formatDateTimeVi(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatTimeShortVi(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleTimeString('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
