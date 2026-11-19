import type {
  AlertItem,
  CommandItem,
  CropCycle,
  CropParameters,
  CropProfile,
  DeviceNode,
  DliResponse,
  GatewayStatus,
  Greenhouse,
  MlModelItem,
  PredictionItem,
  ReadingPoint,
  User,
  YieldForecastDetails,
  CropRecommendationDetails,
} from './types'

export const MOCK_USER: User = {
  id: 'u-owner-001',
  farm_id: 'farm-dalat-01',
  email: 'owner@greenhub.vn',
  role: 'owner',
  created_at: '2026-01-01T00:00:00Z',
}

const DEFAULT_PARAMS: CropParameters = {
  schema_version: 2,
  vpd: { optimal: [0.8, 1.2], low_crit: 0.4, low_off: 0.6, high_crit: 1.6, leaf_offset_c: -2.0 },
  temp_c: { optimal: [20.0, 26.0] },
  light: { dli_optimal: [14.0, 22.0] },
  soil_moisture_pct: { min: 60.0, max: 80.0 },
  disease: { rh_gt: 85.0, temp_range_c: [18.0, 24.0], fungal_minutes_alert: 60 },
  irrigation: { max_run_s: 180, min_gap_s: 600, max_total_s_per_hour: 600, soil_settle_s: 120 },
  fan: { min_on_s: 60, max_on_s: 1800 },
  mist: { max_on_s: 60, lockout_s: 300 },
  risk: { vpd_low_duration_min: 120 },
  cycle: { days: 90 },
  yield: { reference_kg_m2: 6.5 },
  ai: {
    recommend_window_h: 168,
    min_cycle_hours: 0.5,
    inference_interval_s: 1800,
    min_coverage: 0.7,
  },
  sample_interval_s: 30,
  failsafe: { temp_critical_high_c: 38.0, soil_moisture_critical_low_pct: 35.0 },
}

export const MOCK_PROFILES: CropProfile[] = [
  {
    id: 'cp-tomato-real',
    farm_id: null,
    crop_code: 'tomato_cherry',
    crop_name: 'Cà chua bi (Thực tế)',
    variety: 'real',
    schema_version: 2,
    parameters_json: {
      ...DEFAULT_PARAMS,
      vpd: { optimal: [0.8, 1.2], low_crit: 0.4, low_off: 0.6, high_crit: 1.6, leaf_offset_c: -2.0 },
      temp_c: { optimal: [20.0, 26.0] },
      light: { dli_optimal: [14.0, 22.0] },
      soil_moisture_pct: { min: 60.0, max: 80.0 },
      cycle: { days: 90 },
      yield: { reference_kg_m2: 6.5 },
    },
  },
  {
    id: 'cp-tomato-demo',
    farm_id: null,
    crop_code: 'tomato_cherry',
    crop_name: 'Cà chua bi (Demo nhanh)',
    variety: 'demo',
    schema_version: 2,
    parameters_json: {
      ...DEFAULT_PARAMS,
      cycle: { days: 1 },
      yield: { reference_kg_m2: 6.5 },
      ai: { ...DEFAULT_PARAMS.ai, min_cycle_hours: 0.05, inference_interval_s: 60 },
    },
  },
  {
    id: 'cp-strawberry-real',
    farm_id: null,
    crop_code: 'strawberry',
    crop_name: 'Dâu tây Đà Lạt',
    variety: 'real',
    schema_version: 2,
    parameters_json: {
      ...DEFAULT_PARAMS,
      vpd: { optimal: [0.6, 1.0], low_crit: 0.3, low_off: 0.5, high_crit: 1.4, leaf_offset_c: -1.5 },
      temp_c: { optimal: [16.0, 22.0] },
      light: { dli_optimal: [12.0, 18.0] },
      soil_moisture_pct: { min: 65.0, max: 85.0 },
      cycle: { days: 120 },
      yield: { reference_kg_m2: 3.5 },
    },
  },
  {
    id: 'cp-lettuce-real',
    farm_id: null,
    crop_code: 'lettuce',
    crop_name: 'Xà lách Thủy canh',
    variety: 'real',
    schema_version: 2,
    parameters_json: {
      ...DEFAULT_PARAMS,
      vpd: { optimal: [0.7, 1.1], low_crit: 0.4, low_off: 0.5, high_crit: 1.3, leaf_offset_c: -1.0 },
      temp_c: { optimal: [18.0, 23.0] },
      light: { dli_optimal: [14.0, 17.0] },
      soil_moisture_pct: { min: 70.0, max: 90.0 },
      cycle: { days: 45 },
      yield: { reference_kg_m2: 4.0 },
    },
  },
  {
    id: 'cp-cucumber-real',
    farm_id: null,
    crop_code: 'cucumber',
    crop_name: 'Dưa leo Baby',
    variety: 'real',
    schema_version: 2,
    parameters_json: {
      ...DEFAULT_PARAMS,
      vpd: { optimal: [0.8, 1.3], low_crit: 0.4, low_off: 0.6, high_crit: 1.7, leaf_offset_c: -2.0 },
      temp_c: { optimal: [22.0, 28.0] },
      light: { dli_optimal: [15.0, 24.0] },
      soil_moisture_pct: { min: 65.0, max: 85.0 },
      cycle: { days: 65 },
      yield: { reference_kg_m2: 9.0 },
    },
  },
  {
    id: 'cp-bell_pepper-real',
    farm_id: null,
    crop_code: 'bell_pepper',
    crop_name: 'Ớt chuông Đà Lạt',
    variety: 'real',
    schema_version: 2,
    parameters_json: {
      ...DEFAULT_PARAMS,
      vpd: { optimal: [0.8, 1.2], low_crit: 0.4, low_off: 0.6, high_crit: 1.5, leaf_offset_c: -1.5 },
      temp_c: { optimal: [20.0, 25.0] },
      light: { dli_optimal: [14.0, 20.0] },
      soil_moisture_pct: { min: 60.0, max: 80.0 },
      cycle: { days: 110 },
      yield: { reference_kg_m2: 7.0 },
    },
  },
]

export const MOCK_GREENHOUSES: Greenhouse[] = [
  {
    id: 'gh-dalat-01',
    farm_id: 'farm-dalat-01',
    name: 'Vườn Đà Lạt #1 (Thực nghiệm)',
    location: 'Phường 7, TP. Đà Lạt, Lâm Đồng',
    created_at: '2026-09-01T07:00:00Z',
    gateway_id: 'gw-esp32-01',
    is_simulated: false,
    online: true,
    open_alerts: 1,
    zones: [
      {
        id: 'zone-01',
        greenhouse_id: 'gh-dalat-01',
        zone_index: 1,
        name: 'Zone 1 - Cà chua bi cao sản',
        crop_profile_id: 'cp-tomato-real',
        area_m2: 120,
        planting_date: '2026-10-15',
        pump_channel: 1,
        soil_dry_raw: 3200,
        soil_wet_raw: 1400,
      },
      {
        id: 'zone-02',
        greenhouse_id: 'gh-dalat-01',
        zone_index: 2,
        name: 'Zone 2 - Dâu tây New Zealand',
        crop_profile_id: 'cp-strawberry-real',
        area_m2: 80,
        planting_date: '2026-10-20',
        pump_channel: 2,
        soil_dry_raw: 3150,
        soil_wet_raw: 1420,
      },
    ],
  },
  {
    id: 'gh-sim-02',
    farm_id: 'farm-dalat-01',
    name: 'Nhà kính Đa khí hậu #2',
    location: 'Khu nghiên cứu công nghệ cao',
    created_at: '2026-10-01T08:00:00Z',
    gateway_id: 'gw-sim-02',
    is_simulated: true,
    online: true,
    open_alerts: 0,
    zones: [
      {
        id: 'zone-03',
        greenhouse_id: 'gh-sim-02',
        zone_index: 1,
        name: 'Zone A - Xà lách thủy canh',
        crop_profile_id: 'cp-lettuce-real',
        area_m2: 100,
        planting_date: '2026-11-01',
        pump_channel: 1,
        soil_dry_raw: 3200,
        soil_wet_raw: 1400,
      },
      {
        id: 'zone-04',
        greenhouse_id: 'gh-sim-02',
        zone_index: 2,
        name: 'Zone B - Dưa leo Baby',
        crop_profile_id: 'cp-cucumber-real',
        area_m2: 150,
        planting_date: '2026-11-05',
        pump_channel: 2,
        soil_dry_raw: 3250,
        soil_wet_raw: 1410,
      },
    ],
  },
]

export const MOCK_CYCLES: Record<string, CropCycle[]> = {
  'zone-01': [
    {
      id: 'cycle-01-active',
      zone_id: 'zone-01',
      crop_profile_id: 'cp-tomato-real',
      crop_code: 'tomato_cherry',
      crop_name: 'Cà chua bi (Thực tế)',
      started_at: new Date(Date.now() - 92 * 86_400_000).toISOString(),
      harvested_at: null,
      area_m2: 120,
      yield_kg: null,
      yield_kg_m2: null,
      status: 'active',
      notes: 'Vụ mùa Thu Đông, sinh trưởng tốt, đã bước sang ngày thứ 92 (đến thời điểm thu hoạch).',
      created_by: 'owner@greenhub.vn',
      created_at: new Date(Date.now() - 92 * 86_400_000).toISOString(),
    },
    {
      id: 'cycle-01-past',
      zone_id: 'zone-01',
      crop_profile_id: 'cp-tomato-real',
      crop_code: 'tomato_cherry',
      crop_name: 'Cà chua bi (Thực tế)',
      started_at: new Date(Date.now() - 130 * 86_400_000).toISOString(),
      harvested_at: new Date(Date.now() - 40 * 86_400_000).toISOString(),
      area_m2: 120,
      yield_kg: 744,
      yield_kg_m2: 6.2,
      status: 'harvested',
      notes: 'Vụ Hè Thu, đạt 95% năng suất chuẩn.',
      created_by: 'owner@greenhub.vn',
      created_at: new Date(Date.now() - 130 * 86_400_000).toISOString(),
    },
  ],
  'zone-02': [
    {
      id: 'cycle-02-active',
      zone_id: 'zone-02',
      crop_profile_id: 'cp-strawberry-real',
      crop_code: 'strawberry',
      crop_name: 'Dâu tây Đà Lạt',
      started_at: new Date(Date.now() - 25 * 86_400_000).toISOString(),
      harvested_at: null,
      area_m2: 80,
      yield_kg: null,
      yield_kg_m2: null,
      status: 'active',
      notes: 'Bắt đầu đợt hoa đầu tiên.',
      created_by: 'owner@greenhub.vn',
      created_at: new Date(Date.now() - 25 * 86_400_000).toISOString(),
    },
  ],
}

export const MOCK_FORECASTS: Record<string, PredictionItem<YieldForecastDetails>[]> = {
  'zone-01': [
    {
      id: 'pred-yield-01',
      ts: new Date(Date.now() - 15 * 60_000).toISOString(),
      task: 'yield_forecast',
      greenhouse_id: 'gh-dalat-01',
      zone_id: 'zone-01',
      crop_cycle_id: 'cycle-01-active',
      model_id: 'model-lgbm-v1',
      value: 6.38,
      score: 0.98,
      details: {
        crop_code: 'tomato_cherry',
        reference_kg_m2: 6.5,
        cycle_days_elapsed: 35,
        window_hours: 168,
        interval: [5.25, 7.15],
        interval_relative: [0.81, 1.1],
        coverage: 0.99,
        low_confidence: false,
        ood_features: [],
        features: {
          t_mean: 23.4,
          rh_mean: 72.1,
          vpd_mean: 1.02,
          dli_mean: 15.2,
          soil_mean: 68.4,
        },
      },
    },
    {
      id: 'pred-yield-00',
      ts: new Date(Date.now() - 24 * 3600_000).toISOString(),
      task: 'yield_forecast',
      greenhouse_id: 'gh-dalat-01',
      zone_id: 'zone-01',
      crop_cycle_id: 'cycle-01-active',
      model_id: 'model-lgbm-v1',
      value: 6.25,
      score: 0.96,
      details: {
        crop_code: 'tomato_cherry',
        reference_kg_m2: 6.5,
        interval: [5.1, 7.0],
        coverage: 0.97,
        low_confidence: false,
      },
    },
  ],
  'zone-02': [
    {
      id: 'pred-yield-02',
      ts: new Date(Date.now() - 15 * 60_000).toISOString(),
      task: 'yield_forecast',
      greenhouse_id: 'gh-dalat-01',
      zone_id: 'zone-02',
      crop_cycle_id: 'cycle-02-active',
      model_id: 'model-lgbm-v1',
      value: 3.15,
      score: 0.9,
      details: {
        crop_code: 'strawberry',
        reference_kg_m2: 3.5,
        cycle_days_elapsed: 25,
        window_hours: 168,
        interval: [2.5, 3.6],
        coverage: 0.95,
        low_confidence: false,
      },
    },
  ],
}

export const MOCK_RECOMMENDATION: PredictionItem<CropRecommendationDetails> = {
  id: 'pred-rec-01',
  ts: new Date(Date.now() - 30 * 60_000).toISOString(),
  task: 'crop_recommendation',
  greenhouse_id: 'gh-dalat-01',
  zone_id: null,
  crop_cycle_id: null,
  model_id: 'model-lgbm-v1',
  value: 0.98,
  score: 0.98,
  details: {
    window_h: 168,
    coverage: 0.98,
    low_confidence: false,
    climate_summary: {
      t_mean: 23.2,
      t_day_mean: 26.1,
      t_night_mean: 19.4,
      rh_mean: 72.5,
      vpd_mean: 1.05,
      dli_mean: 15.6,
    },
    ranking: [
      {
        crop_code: 'tomato_cherry',
        crop_name: 'Cà chua bi',
        relative_yield: 0.98,
        expected_kg_m2: 6.38,
        interval: [5.25, 7.15],
        reasons: [
          'Nhiệt độ ngày đêm 19–26°C rất thích hợp phân hóa mầm hoa',
          'VPD trung bình 1.05 kPa nằm trọn trong dải tối ưu [0.8–1.2 kPa]',
          'Ánh sáng tích lũy DLI 15.6 mol/m²/ngày đáp ứng quang hợp tối đa',
        ],
      },
      {
        crop_code: 'cucumber',
        crop_name: 'Dưa leo Baby',
        relative_yield: 0.91,
        expected_kg_m2: 8.19,
        interval: [6.8, 9.3],
        reasons: [
          'Độ ẩm tương đối 72.5% giúp trái mọng nước, phát triển nhanh',
          'Nhiệt độ đêm không bị rét dưới 18°C',
        ],
      },
      {
        crop_code: 'bell_pepper',
        crop_name: 'Ớt chuông',
        relative_yield: 0.88,
        expected_kg_m2: 6.16,
        interval: [5.1, 7.0],
        reasons: ['Khí hậu ổn định, biên độ nhiệt ngày đêm lý tưởng cho tích lũy đường'],
      },
      {
        crop_code: 'strawberry',
        crop_name: 'Dâu tây',
        relative_yield: 0.83,
        expected_kg_m2: 2.91,
        interval: [2.3, 3.4],
        reasons: ['Cần chú ý thông gió hạ nhiệt vào giữa trưa khi nhiệt độ vượt 26°C'],
      },
      {
        crop_code: 'lettuce',
        crop_name: 'Xà lách',
        relative_yield: 0.8,
        expected_kg_m2: 3.2,
        interval: [2.5, 3.7],
        reasons: ['Nhiệt độ trưa hơi cao có thể làm xà lách dễ trổ ngồng sớm'],
      },
    ],
  },
}

export const MOCK_ACTIVE_MODEL: MlModelItem = {
  id: 'model-lgbm-v1',
  task: 'yield',
  version: 1,
  feature_version: 1,
  artifact_path: 'models/yield_lgbm_v1.joblib',
  trained_at: '2026-11-15T08:30:00Z',
  n_samples: 1240,
  n_greenhouses: 18,
  is_active: true,
  notes: 'Mô hình hồi quy LightGBM toàn cục kết hợp 16 đặc trưng vi khí hậu đa nhà kính.',
  source_mix: {
    synthetic: 600,
    sim: 420,
    real: 120,
    public: 100,
  },
  crops: [
    { crop_code: 'tomato_cherry', n: 320, reference_kg_m2: 6.5 },
    { crop_code: 'cucumber', n: 280, reference_kg_m2: 9.0 },
    { crop_code: 'bell_pepper', n: 240, reference_kg_m2: 7.0 },
    { crop_code: 'strawberry', n: 220, reference_kg_m2: 3.5 },
    { crop_code: 'lettuce', n: 180, reference_kg_m2: 4.0 },
  ],
  metrics: {
    n: 248,
    mae_kg_m2: 0.3821,
    rmse_kg_m2: 0.512,
    r2: 0.9412,
    mape: 6.8,
    top1_accuracy: 0.88,
    ndcg_at_3: 0.945,
    n_eval: 120,
    by_crop: {
      tomato_cherry: { n: 64, mae_kg_m2: 0.342, rmse_kg_m2: 0.461, r2: 0.952 },
      cucumber: { n: 56, mae_kg_m2: 0.495, rmse_kg_m2: 0.642, r2: 0.931 },
      bell_pepper: { n: 48, mae_kg_m2: 0.412, rmse_kg_m2: 0.535, r2: 0.938 },
      strawberry: { n: 44, mae_kg_m2: 0.285, rmse_kg_m2: 0.384, r2: 0.945 },
      lettuce: { n: 36, mae_kg_m2: 0.264, rmse_kg_m2: 0.352, r2: 0.948 },
    },
    by_source: {
      synthetic: { n: 120, mae_kg_m2: 0.312, rmse_kg_m2: 0.421 },
      sim: { n: 84, mae_kg_m2: 0.415, rmse_kg_m2: 0.562 },
      real: { n: 24, mae_kg_m2: 0.462, rmse_kg_m2: 0.615 },
      public: { n: 20, mae_kg_m2: 0.435, rmse_kg_m2: 0.582 },
    },
  },
  baseline_metrics: {
    B0: {
      mae_kg_m2: 0.8124,
      rmse_kg_m2: 1.0542,
      r2: 0.612,
      mape: 14.2,
      top1_accuracy: 0.62,
    },
    B1: {
      mae_kg_m2: 0.6105,
      rmse_kg_m2: 0.832,
      r2: 0.765,
      mape: 10.5,
      top1_accuracy: 0.74,
    },
  },
  feature_drift: {
    window_days: 7,
    n_predictions: 168,
    features: {
      t_mean: {
        train_mean: 23.5,
        train_std: 3.2,
        recent_mean: 23.8,
        recent_std: 2.9,
        z_score: 0.1,
        drifted: false,
        n_recent: 168,
      },
      vpd_mean: {
        train_mean: 1.05,
        train_std: 0.28,
        recent_mean: 1.08,
        recent_std: 0.25,
        z_score: 0.12,
        drifted: false,
        n_recent: 168,
      },
      rh_mean: {
        train_mean: 73.0,
        train_std: 9.5,
        recent_mean: 72.1,
        recent_std: 8.8,
        z_score: -0.1,
        drifted: false,
        n_recent: 168,
      },
      dli_mean: {
        train_mean: 16.2,
        train_std: 4.1,
        recent_mean: 15.4,
        recent_std: 3.8,
        z_score: -0.21,
        drifted: false,
        n_recent: 168,
      },
      soil_mean: {
        train_mean: 68.0,
        train_std: 8.0,
        recent_mean: 67.5,
        recent_std: 7.2,
        z_score: -0.07,
        drifted: false,
        n_recent: 168,
      },
    },
  },
}

export const MOCK_ALERTS: AlertItem[] = [
  {
    id: 'alt-001',
    greenhouse_id: 'gh-dalat-01',
    zone_id: 'zone-02',
    alert_type: 'SOIL_DRY',
    severity: 'warning',
    state: 'raised',
    dedupe_key: 'soil_dry_zone_02',
    payload: {
      title: 'Độ ẩm đất thấp ở Zone 2 (Dâu tây)',
      body: 'Độ ẩm đất đo được 48%, thấp hơn ngưỡng tối thiểu 65% của giống Dâu tây.',
    },
    created_at: new Date(Date.now() - 42 * 60_000).toISOString(),
    notified_at: new Date(Date.now() - 40 * 60_000).toISOString(),
    escalated_at: null,
    acknowledged_at: null,
    acked_by: null,
    resolved_at: null,
  },
  {
    id: 'alt-002',
    greenhouse_id: 'gh-dalat-01',
    zone_id: 'zone-01',
    alert_type: 'DISEASE_RISK',
    severity: 'info',
    state: 'acknowledged',
    dedupe_key: 'disease_risk_zone_01',
    payload: {
      title: 'Nguy cơ sương mai do ẩm kéo dài',
      body: 'Độ ẩm không khí duy trì trên 85% trong hơn 60 phút qua. Đã tự động kích hoạt quạt đối lưu.',
    },
    created_at: new Date(Date.now() - 150 * 60_000).toISOString(),
    notified_at: new Date(Date.now() - 148 * 60_000).toISOString(),
    escalated_at: null,
    acknowledged_at: new Date(Date.now() - 90 * 60_000).toISOString(),
    acked_by: 'owner@greenhub.vn',
    resolved_at: null,
  },
]

export const MOCK_GATEWAY_STATUS: GatewayStatus = {
  id: 'gw-esp32-01',
  greenhouse_id: 'gh-dalat-01',
  mqtt_username: 'gw_dalat_01',
  is_simulated: false,
  online: true,
  last_seen: new Date().toISOString(),
  fw_version: '1.2.0',
  rssi: -64,
  reported: {
    actuators: { pump_1: 'off', pump_2: 'off', fan: 'on', mist: 'off' },
    uptime_s: 86400 * 5,
    heap: 184520,
    queue_len: 0,
    nodes: [
      { mac: '24:6F:28:AB:01:10', zone: 1, last_seen_s: 12 },
      { mac: '24:6F:28:CD:02:20', zone: 2, last_seen_s: 18 },
    ],
  },
  desired: {
    modes: {
      pump_1: { mode: 'auto', until: null },
      pump_2: { mode: 'auto', until: null },
      fan: { mode: 'auto', until: null },
      mist: { mode: 'auto', until: null },
    },
  },
  cfg_version_desired: 4,
  cfg_version_reported: 4,
}

export const MOCK_NODES: DeviceNode[] = [
  {
    id: 'node-01',
    mac_address: '24:6F:28:AB:01:10',
    greenhouse_id: 'gh-dalat-01',
    zone_id: 'zone-01',
    status: 'paired',
    firmware_version: '1.1.2',
    battery_mv: 3240,
    rssi: -62,
    first_seen: '2026-09-01T08:00:00Z',
    last_seen: new Date().toISOString(),
  },
  {
    id: 'node-02',
    mac_address: '24:6F:28:CD:02:20',
    greenhouse_id: 'gh-dalat-01',
    zone_id: 'zone-02',
    status: 'paired',
    firmware_version: '1.1.2',
    battery_mv: 3180,
    rssi: -67,
    first_seen: '2026-09-01T08:00:00Z',
    last_seen: new Date().toISOString(),
  },
  {
    id: 'node-03',
    mac_address: '24:6F:28:EF:03:30',
    greenhouse_id: null,
    zone_id: null,
    status: 'discovered',
    firmware_version: '1.1.2',
    battery_mv: 3290,
    rssi: -58,
    first_seen: new Date(Date.now() - 10 * 60_000).toISOString(),
    last_seen: new Date().toISOString(),
  },
]

export const MOCK_COMMANDS: CommandItem[] = [
  {
    id: 'cmd-01',
    greenhouse_id: 'gh-dalat-01',
    actuator: 'fan',
    action: 'on',
    duration_s: 900,
    source: 'auto',
    requested_by: null,
    reason: 'Hạ ẩm ngăn ngừa nấm bệnh',
    status: 'applied',
    reject_reason: null,
    created_at: new Date(Date.now() - 15 * 60_000).toISOString(),
    sent_at: new Date(Date.now() - 15 * 60_000).toISOString(),
    acked_at: new Date(Date.now() - 15 * 60_000 + 450).toISOString(),
    expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
  },
  {
    id: 'cmd-02',
    greenhouse_id: 'gh-dalat-01',
    actuator: 'pump_1',
    action: 'on',
    duration_s: 120,
    source: 'manual',
    requested_by: 'owner@greenhub.vn',
    reason: 'Tưới bổ sung thủ công',
    status: 'applied',
    reject_reason: null,
    created_at: new Date(Date.now() - 90 * 60_000).toISOString(),
    sent_at: new Date(Date.now() - 90 * 60_000).toISOString(),
    acked_at: new Date(Date.now() - 90 * 60_000 + 320).toISOString(),
    expires_at: new Date(Date.now() - 85 * 60_000).toISOString(),
  },
]

export function generateMockReadings(hours = 24, count = 120): ReadingPoint[] {
  const points: ReadingPoint[] = []
  const now = Date.now()
  const stepMs = (hours * 3600_000) / count

  for (let i = count - 1; i >= 0; i--) {
    const t = new Date(now - i * stepMs)
    const hour = t.getHours() + t.getMinutes() / 60
    // Chu kỳ ngày đêm: trưa ấm khô, đêm mát ẩm
    const sunFactor = Math.max(0, Math.sin(((hour - 6) / 12) * Math.PI))
    const temp = 19.0 + sunFactor * 8.5 + (Math.sin(i * 0.3) * 0.4)
    const rh = 84.0 - sunFactor * 22.0 + (Math.cos(i * 0.25) * 1.5)
    // VPD xấp xỉ
    const vpd = Math.max(0.4, (0.7 + sunFactor * 0.55 + Math.sin(i * 0.2) * 0.08))
    const soil = 72.0 - (i % 30) * 0.3 + (Math.sin(i * 0.15) * 0.8)
    const lux = sunFactor > 0 ? Math.round(sunFactor * 42000 + Math.random() * 2000) : 0

    points.push({
      ts: t.toISOString(),
      air_temp: Math.round(temp * 10) / 10,
      air_rh: Math.round(rh * 10) / 10,
      vpd: Math.round(vpd * 100) / 100,
      soil_moisture: Math.round(soil * 10) / 10,
      soil_raw: 1850,
      lux,
      quality: 'ok',
      source: 'node',
    })
  }

  return points
}

export function handleMockApiRequest(path: string, init: RequestInit = {}): unknown {
  const method = (init.method || 'GET').toUpperCase()

  // 1. Health
  if (path === '/health') {
    return { status: 'ok', db: true, mock: true }
  }

  // 2. Auth login
  if (path === '/auth/login') {
    return { access_token: 'mock-jwt-owner-token', token_type: 'bearer' }
  }

  // 3. Me
  if (path === '/me') {
    return MOCK_USER
  }

  // 4. Greenhouses
  if (path === '/greenhouses') {
    if (method === 'POST') {
      const body = JSON.parse((init.body as string) || '{}')
      const newGh: Greenhouse = {
        id: `gh-new-${Date.now()}`,
        farm_id: 'farm-dalat-01',
        name: body.name || 'Nhà kính mới',
        location: body.location || 'Khu nông trại chính',
        created_at: new Date().toISOString(),
        gateway_id: null,
        is_simulated: false,
        online: true,
        open_alerts: 0,
        zones: [
          {
            id: `zone-${Date.now()}-1`,
            greenhouse_id: `gh-new-${Date.now()}`,
            zone_index: 1,
            name: 'Zone 1',
            crop_profile_id: 'cp-tomato-real',
            area_m2: 100,
            planting_date: new Date().toISOString().slice(0, 10),
            pump_channel: 1,
            soil_dry_raw: 3200,
            soil_wet_raw: 1400,
          },
          {
            id: `zone-${Date.now()}-2`,
            greenhouse_id: `gh-new-${Date.now()}`,
            zone_index: 2,
            name: 'Zone 2',
            crop_profile_id: 'cp-cucumber-real',
            area_m2: 100,
            planting_date: new Date().toISOString().slice(0, 10),
            pump_channel: 2,
            soil_dry_raw: 3200,
            soil_wet_raw: 1400,
          },
        ],
      }
      MOCK_GREENHOUSES.push(newGh)
      return newGh
    }
    return MOCK_GREENHOUSES
  }

  // 5. Zone detail
  const zoneMatch = path.match(/^\/zones\/([^/?]+)$/)
  if (zoneMatch) {
    const zid = zoneMatch[1]
    const z = MOCK_GREENHOUSES.flatMap((g) => g.zones).find((item) => item.id === zid)
    if (z) {
      if (method === 'PUT') {
        const body = JSON.parse((init.body as string) || '{}')
        Object.assign(z, body)
      }
      return z
    }
    return MOCK_GREENHOUSES[0].zones[0]
  }

  // 6. Zone readings
  if (path.includes('/readings')) {
    const isShort = path.includes('hours=1') || path.includes('15m')
    return generateMockReadings(isShort ? 1 : 24, 80)
  }

  // 7. Zone DLI
  if (path.includes('/dli')) {
    const dli: DliResponse = {
      zone_id: 'zone-01',
      date: new Date().toISOString().slice(0, 10),
      dli_mol_m2_day: 15.6,
      sample_count: 288,
    }
    return dli
  }

  // 8. Zone cycles
  if (path.includes('/cycles')) {
    const zMatch = path.match(/\/zones\/([^/]+)\/cycles/)
    if (zMatch) {
      const zid = zMatch[1]
      const list = MOCK_CYCLES[zid] || MOCK_CYCLES['zone-01']
      if (method === 'POST') {
        const body = JSON.parse((init.body as string) || '{}')
        const newCycle: CropCycle = {
          id: `cycle-${Date.now()}`,
          zone_id: zid,
          crop_profile_id: body.crop_profile_id || 'cp-tomato-real',
          crop_code: 'tomato_cherry',
          crop_name: 'Cà chua bi',
          started_at: body.started_at || new Date().toISOString(),
          harvested_at: null,
          area_m2: Number(body.area_m2) || 100,
          yield_kg: null,
          yield_kg_m2: null,
          status: 'active',
          notes: body.notes || 'Vụ trồng mới tạo',
          created_by: 'owner@greenhub.vn',
          created_at: new Date().toISOString(),
        }
        MOCK_CYCLES[zid] = [newCycle, ...(MOCK_CYCLES[zid] || [])]
        return newCycle
      }
      if (path.includes('status=active')) {
        return list.filter((c) => c.status === 'active')
      }
      return list
    }
  }

  // Harvest or abandon cycle
  if (path.match(/\/cycles\/([^/]+)\/harvest/)) {
    const cMatch = path.match(/\/cycles\/([^/]+)\/harvest/)
    const cid = cMatch ? cMatch[1] : ''
    const body = JSON.parse((init.body as string) || '{}')
    
    // Tìm cycle trong mọi zone và cập nhật
    for (const list of Object.values(MOCK_CYCLES)) {
      const cycle = list.find((c) => c.id === cid)
      if (cycle) {
        cycle.status = 'harvested'
        cycle.harvested_at = new Date().toISOString()
        cycle.yield_kg = Number(body.yield_kg) || 0
        cycle.yield_kg_m2 = Number(((body.yield_kg || 0) / cycle.area_m2).toFixed(2))
        cycle.notes = body.notes || 'Đã thu hoạch và ghi nhận phản hồi mùa vụ thực tế'
        cycle.feedback = body.feedback || null
        break
      }
    }

    // Tăng số mẫu thực tế trong model để phản ánh đóng góp dữ liệu của người dùng
    if (MOCK_ACTIVE_MODEL.metrics?.by_source?.real) {
      MOCK_ACTIVE_MODEL.metrics.by_source.real.n += 1
    }
    if (MOCK_ACTIVE_MODEL.n_samples) {
      MOCK_ACTIVE_MODEL.n_samples += 1
    }

    return { status: 'harvested', updated_at: new Date().toISOString() }
  }

  if (path.match(/\/cycles\/([^/]+)\/abandon/)) {
    const cMatch = path.match(/\/cycles\/([^/]+)\/abandon/)
    const cid = cMatch ? cMatch[1] : ''
    for (const list of Object.values(MOCK_CYCLES)) {
      const cycle = list.find((c) => c.id === cid)
      if (cycle) {
        cycle.status = 'abandoned'
        cycle.harvested_at = new Date().toISOString()
        break
      }
    }
    return { status: 'abandoned', updated_at: new Date().toISOString() }
  }

  // 9. Predictions
  if (path.includes('/predictions')) {
    const zMatch = path.match(/\/zones\/([^/]+)\/predictions/)
    const zid = zMatch ? zMatch[1] : 'zone-01'
    return MOCK_FORECASTS[zid] || MOCK_FORECASTS['zone-01']
  }

  // 10. Recommendations
  if (path.includes('/recommendations')) {
    if (path.includes('/refresh')) {
      return { status: 'refreshing', greenhouse_id: 'gh-dalat-01' }
    }
    return MOCK_RECOMMENDATION
  }

  // 11. Models
  if (path === '/models/active') {
    return MOCK_ACTIVE_MODEL
  }
  if (path === '/models') {
    return [MOCK_ACTIVE_MODEL]
  }
  if (path.startsWith('/models/')) {
    return MOCK_ACTIVE_MODEL
  }

  // 12. Crop Profiles
  if (path === '/crop-profiles') {
    return MOCK_PROFILES
  }
  const cpMatch = path.match(/^\/crop-profiles\/([^/?]+)$/)
  if (cpMatch) {
    const cpid = cpMatch[1]
    const p = MOCK_PROFILES.find((item) => item.id === cpid) ?? MOCK_PROFILES[0]
    if (method === 'PUT') {
      const body = JSON.parse((init.body as string) || '{}')
      Object.assign(p, body)
    }
    return p
  }

  // 13. Alerts
  if (path.startsWith('/alerts')) {
    if (path.includes('/ack')) {
      const idMatch = path.match(/\/alerts\/([^/]+)\/ack/)
      const aid = idMatch ? idMatch[1] : ''
      const alt = MOCK_ALERTS.find((a) => a.id === aid)
      if (alt) {
        alt.state = 'acknowledged'
        alt.acknowledged_at = new Date().toISOString()
        alt.acked_by = 'owner@greenhub.vn'
      }
      return alt || MOCK_ALERTS[0]
    }
    return MOCK_ALERTS
  }

  // 14. Gateways & Devices
  if (path.includes('/status')) {
    return MOCK_GATEWAY_STATUS
  }
  if (path.includes('/config-sync')) {
    const ghIdMatch = path.match(/\/greenhouses\/([^/]+)\/config-sync/)
    const ghId = ghIdMatch ? ghIdMatch[1] : 'gh-dalat-01'
    return {
      greenhouse_id: ghId,
      cfg_version_desired: 4,
      cfg_version_reported: 4,
      synced: true,
      updated_at: new Date().toISOString(),
    }
  }
  if (path === '/gateways' || path.startsWith('/devices/gateways/provision')) {
    if (method === 'POST') {
      const body = JSON.parse((init.body as string) || '{}')
      return {
        gateway_id: `gw-${Date.now()}`,
        farm_id: 'farm-dalat-01',
        greenhouse_id: body.greenhouse_id || 'gh-dalat-01',
        mqtt_username: `gw_mqtt_${Date.now()}`,
        mqtt_password: 'SecrEtMqttPassword123!',
        host: 'mqtt.greenhub.vn',
        port: 8883,
        is_simulated: Boolean(body.is_simulated),
      }
    }
    return [MOCK_GATEWAY_STATUS]
  }
  if (path.startsWith('/nodes')) {
    if (path.includes('/pair')) {
      const macMatch = path.match(/\/nodes\/([^/]+)\/pair/)
      const rawMac = macMatch ? decodeURIComponent(macMatch[1]) : ''
      const body = JSON.parse((init.body as string) || '{}')
      let node = MOCK_NODES.find((n) => n.mac_address.toLowerCase() === rawMac.toLowerCase())
      if (node) {
        node.status = 'paired'
        node.zone_id = body.zone_id || 'zone-01'
        node.greenhouse_id = 'gh-dalat-01'
      } else {
        node = {
          id: `node-${Date.now()}`,
          mac_address: rawMac || '24:6F:28:99:99:99',
          greenhouse_id: 'gh-dalat-01',
          zone_id: body.zone_id || 'zone-01',
          status: 'paired',
          firmware_version: '1.1.2',
          battery_mv: 3200,
          rssi: -60,
          first_seen: new Date().toISOString(),
          last_seen: new Date().toISOString(),
        }
        MOCK_NODES.push(node)
      }
      return node
    }
    return MOCK_NODES
  }
  if (path.includes('/calibration')) {
    const zMatch = path.match(/\/zones\/([^/]+)\/calibration/)
    const zid = zMatch ? zMatch[1] : 'zone-01'
    return {
      zone_id: zid,
      cfg_version_desired: 5,
    }
  }
  if (path.startsWith('/greenhouses/') && path.includes('/commands')) {
    if (method === 'POST') {
      const body = JSON.parse((init.body as string) || '{}')
      const newCmd: CommandItem = {
        id: `cmd-${Date.now()}`,
        greenhouse_id: 'gh-dalat-01',
        actuator: body.actuator || 'pump_1',
        action: body.action || 'on',
        duration_s: body.duration_s || 60,
        source: 'manual',
        requested_by: 'owner@greenhub.vn',
        reason: 'Điều khiển thử nghiệm trên Web',
        status: 'applied',
        reject_reason: null,
        created_at: new Date().toISOString(),
        sent_at: new Date().toISOString(),
        acked_at: new Date(Date.now() + 200).toISOString(),
        expires_at: new Date(Date.now() + 60_000).toISOString(),
      }
      MOCK_COMMANDS.unshift(newCmd)
      return newCmd
    }
    return MOCK_COMMANDS
  }

  // Default fallback
  return { status: 'ok', mock: true }
}
