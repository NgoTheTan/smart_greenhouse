import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, formatApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  ACTUATOR_LABELS,
  ALERT_TYPE_LABELS,
  QUALITY_LABELS,
  formatCropName,
  formatDateTimeVi,
  formatTimeShortVi,
  type ActuatorName,
  type AlertItem,
  type CommandItem,
  type CropCycle,
  type CropProfile,
  type DliResponse,
  type GatewayStatus,
  type Greenhouse,
  type MlModelItem,
  type PredictionItem,
  type ReadingPoint,
  type YieldForecastDetails,
  type Zone,
} from '../lib/types'

type RangeKey = '15m' | '1h' | '6h' | '24h' | '7d'

const RANGE_OPTIONS: Array<{
  key: RangeKey
  label: string
  hours: number
  agg: 'raw' | '1m' | '1h'
}> = [
  { key: '15m', label: '15 phút', hours: 0.25, agg: 'raw' },
  { key: '1h', label: '1 giờ', hours: 1, agg: 'raw' },
  { key: '6h', label: '6 giờ', hours: 6, agg: '1m' },
  { key: '24h', label: '24 giờ', hours: 24, agg: '1m' },
  { key: '7d', label: '7 ngày', hours: 168, agg: '1h' },
]

const ACTUATORS: ActuatorName[] = ['pump_1', 'pump_2', 'fan', 'mist']

const CMD_STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  pending: { label: 'Chờ gửi', cls: 'muted' },
  sent: { label: 'Đã gửi MQTT', cls: 'info' },
  applied: { label: 'Đã thực thi', cls: 'ok' },
  rejected: { label: 'Bị từ chối', cls: 'bad' },
  expired: { label: 'Hết hạn', cls: 'warning' },
  timeout: { label: 'Timeout ACK', cls: 'warning' },
}

export default function ZoneDetailPage() {
  const { id: routeZoneId, ghId: routeGhId } = useParams<{ id: string; ghId: string }>()
  const navigate = useNavigate()
  const { canOperate, isOwner } = useAuth()
  const queryClient = useQueryClient()

  const [rangeKey, setRangeKey] = useState<RangeKey>('1h')
  const [durationInput, setDurationInput] = useState<number>(30)
  const [manualMinutes, setManualMinutes] = useState<number>(30)
  const [cmdFeedback, setCmdFeedback] = useState<{ ok: boolean; text: string } | null>(null)

  // Modals: Start Cycle, Harvest Cycle, Edit Zone
  const [showStartModal, setShowStartModal] = useState(false)
  const [startProfileId, setStartProfileId] = useState('')
  const [startAreaM2, setStartAreaM2] = useState<string>('1.0')
  const [startNotes, setStartNotes] = useState('')
  const [cycleError, setCycleError] = useState<string | null>(null)

  const [showHarvestModal, setShowHarvestModal] = useState(false)
  const [harvestKg, setHarvestKg] = useState<string>('1.5')
  const [harvestNotes, setHarvestNotes] = useState('')

  const [showZoneEdit, setShowZoneEdit] = useState(false)
  const [editZoneName, setEditZoneName] = useState('')
  const [editZoneProfileId, setEditZoneProfileId] = useState('')
  const [editZoneArea, setEditZoneArea] = useState('')
  const [zoneEditMsg, setZoneEditMsg] = useState<string | null>(null)

  const greenhousesQuery = useQuery({
    queryKey: ['greenhouses'],
    queryFn: () => api<Greenhouse[]>('/greenhouses'),
  })

  const profilesQuery = useQuery({
    queryKey: ['crop-profiles'],
    queryFn: () => api<CropProfile[]>('/crop-profiles'),
  })

  const activeModelQuery = useQuery({
    queryKey: ['models', 'active'],
    queryFn: () => api<MlModelItem | null>('/models/active'),
  })

  const greenhouses = greenhousesQuery.data ?? []
  const profiles = profilesQuery.data ?? []

  // Xác định Zone và Greenhouse hiện tại từ route `/zones/:id` hoặc `/greenhouses/:ghId/control`
  const resolvedGh = routeGhId
    ? greenhouses.find((g) => g.id === routeGhId)
    : greenhouses.find((g) => g.zones.some((z) => z.id === routeZoneId))

  const zoneId = routeZoneId || resolvedGh?.zones[0]?.id || ''

  const zoneQuery = useQuery({
    queryKey: ['zone', zoneId],
    queryFn: () => api<Zone>(`/zones/${zoneId}`),
    enabled: Boolean(zoneId),
  })

  const zone = zoneQuery.data ?? resolvedGh?.zones.find((z) => z.id === zoneId) ?? null
  const gh = resolvedGh ?? greenhouses.find((g) => g.id === zone?.greenhouse_id) ?? null
  const ghId = gh?.id || routeGhId || ''

  const profile = profiles.find((p) => p.id === zone?.crop_profile_id) ?? null
  const params = profile?.parameters_json

  const rangeOpt = RANGE_OPTIONS.find((r) => r.key === rangeKey) ?? RANGE_OPTIONS[1]

  const readingsQuery = useQuery({
    queryKey: ['readings', zoneId, rangeKey],
    queryFn: () => {
      const to = new Date()
      const from = new Date(to.getTime() - rangeOpt.hours * 3_600_000)
      return api<ReadingPoint[]>(
        `/zones/${zoneId}/readings?from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(to.toISOString())}&agg=${rangeOpt.agg}&limit=500`,
      )
    },
    enabled: Boolean(zoneId),
  })

  const dliQuery = useQuery({
    queryKey: ['dli', zoneId],
    queryFn: () => api<DliResponse>(`/zones/${zoneId}/dli`),
    enabled: Boolean(zoneId),
  })

  const cyclesQuery = useQuery({
    queryKey: ['cycles', zoneId],
    queryFn: () => api<CropCycle[]>(`/zones/${zoneId}/cycles`),
    enabled: Boolean(zoneId),
  })

  const predictionsQuery = useQuery({
    queryKey: ['predictions', zoneId],
    queryFn: () =>
      api<PredictionItem<YieldForecastDetails>[]>(
        `/zones/${zoneId}/predictions?task=yield_forecast&limit=50`,
      ),
    enabled: Boolean(zoneId),
  })

  const gwStatusQuery = useQuery({
    queryKey: ['gateway-status', ghId],
    queryFn: () => api<GatewayStatus>(`/gateways/${gh?.gateway_id || ghId}/status`),
    enabled: Boolean(ghId && (gh?.gateway_id || routeGhId)),
  })

  const commandsQuery = useQuery({
    queryKey: ['commands', ghId],
    queryFn: () => api<CommandItem[]>(`/greenhouses/${ghId}/commands?limit=25`),
    enabled: Boolean(ghId),
  })

  const ghAlertsQuery = useQuery({
    queryKey: ['alerts', 'gh', ghId],
    queryFn: () => api<AlertItem[]>(`/alerts?greenhouse_id=${ghId}&limit=30`),
    enabled: Boolean(ghId),
  })

  useEffect(() => {
    if (zone) {
      setEditZoneName(zone.name || '')
      setEditZoneProfileId(zone.crop_profile_id || '')
      setEditZoneArea(zone.area_m2 ? String(zone.area_m2) : '1.0')
      setStartProfileId(zone.crop_profile_id || profiles[0]?.id || '')
      setStartAreaM2(zone.area_m2 ? String(zone.area_m2) : '1.0')
    }
  }, [zone, profiles])

  const readings = readingsQuery.data ?? []
  const latest = readings.length > 0 ? readings[readings.length - 1] : null
  const latestOk = [...readings].reverse().find((r) => r.quality === 'ok') ?? latest

  const cycles = cyclesQuery.data ?? []
  const activeCycle = cycles.find((c) => c.status === 'active') ?? null
  const predictions = predictionsQuery.data ?? []
  const cyclePredictions = activeCycle
    ? predictions.filter((p) => p.crop_cycle_id === activeCycle.id)
    : []
  const latestForecast = cyclePredictions[0] ?? predictions[0] ?? null

  const chartData = useMemo(
    () =>
      readings.map((r) => ({
        ...r,
        timeLabel: formatTimeShortVi(r.ts),
      })),
    [readings],
  )

  // Mốc thời gian alert & command trên biểu đồ
  const firstTsMs = readings.length > 0 ? new Date(readings[0].ts).getTime() : 0
  const lastTsMs = readings.length > 0 ? new Date(readings[readings.length - 1].ts).getTime() : 0

  const overlayEvents = useMemo(() => {
    if (readings.length === 0) return []
    const items: Array<{ label: string; timeLabel: string; color: string }> = []
    for (const alt of ghAlertsQuery.data ?? []) {
      const ms = new Date(alt.created_at).getTime()
      if (ms >= firstTsMs && ms <= lastTsMs) {
        items.push({
          label: `⚠ ${ALERT_TYPE_LABELS[alt.alert_type] ?? alt.alert_type}`,
          timeLabel: formatTimeShortVi(alt.created_at),
          color: '#ef4444',
        })
      }
    }
    for (const cmd of commandsQuery.data ?? []) {
      const ms = new Date(cmd.created_at).getTime()
      if (ms >= firstTsMs && ms <= lastTsMs && cmd.action === 'on') {
        items.push({
          label: `${cmd.actuator} ON`,
          timeLabel: formatTimeShortVi(cmd.created_at),
          color: '#0284c7',
        })
      }
    }
    return items.slice(0, 10)
  }, [readings.length, ghAlertsQuery.data, commandsQuery.data, firstTsMs, lastTsMs])

  // Mutations
  const sendCommandMutation = useMutation({
    mutationFn: (payload: { actuator: ActuatorName; action: 'on' | 'off'; duration_s?: number }) =>
      api<CommandItem>(`/greenhouses/${ghId}/commands`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    onSuccess: (cmd) => {
      setCmdFeedback({
        ok: true,
        text: `Đã gửi lệnh ${cmd.actuator} → ${cmd.action.toUpperCase()} (${cmd.status}).`,
      })
      void queryClient.invalidateQueries({ queryKey: ['commands', ghId] })
    },
    onError: (err) => {
      setCmdFeedback({ ok: false, text: formatApiError(err) })
    },
  })

  const setModeMutation = useMutation({
    mutationFn: (payload: { actuator: ActuatorName; mode: 'auto' | 'manual'; until: string | null }) =>
      api<{ greenhouse_id: string }>(`/greenhouses/${ghId}/modes`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['gateway-status', ghId] })
    },
    onError: (err) => {
      setCmdFeedback({ ok: false, text: formatApiError(err) })
    },
  })

  const startCycleMutation = useMutation({
    mutationFn: (payload: { crop_profile_id: string; area_m2: number; notes: string | null }) =>
      api<CropCycle>(`/zones/${zoneId}/cycles`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      setShowStartModal(false)
      setCycleError(null)
      setStartNotes('')
      void queryClient.invalidateQueries({ queryKey: ['cycles', zoneId] })
      void queryClient.invalidateQueries({ queryKey: ['zone', zoneId] })
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
    },
    onError: (err) => setCycleError(formatApiError(err)),
  })

  const harvestCycleMutation = useMutation({
    mutationFn: (payload: { cycleId: string; yield_kg: number; notes: string | null }) =>
      api<CropCycle>(`/cycles/${payload.cycleId}/harvest`, {
        method: 'POST',
        body: JSON.stringify({ yield_kg: payload.yield_kg, notes: payload.notes }),
      }),
    onSuccess: () => {
      setShowHarvestModal(false)
      setCycleError(null)
      setHarvestNotes('')
      void queryClient.invalidateQueries({ queryKey: ['cycles', zoneId] })
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
    },
    onError: (err) => setCycleError(formatApiError(err)),
  })

  const abandonCycleMutation = useMutation({
    mutationFn: (cycleId: string) =>
      api<CropCycle>(`/cycles/${cycleId}/abandon`, {
        method: 'POST',
        body: JSON.stringify({ notes: 'Huỷ vụ từ Web Console' }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['cycles', zoneId] })
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
    },
    onError: (err) => setCycleError(formatApiError(err)),
  })

  const updateZoneMutation = useMutation({
    mutationFn: (payload: { name: string; crop_profile_id: string | null; area_m2: number | null }) =>
      api<Zone>(`/zones/${zoneId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      setShowZoneEdit(false)
      setZoneEditMsg('Đã cập nhật thông tin Zone.')
      void queryClient.invalidateQueries({ queryKey: ['zone', zoneId] })
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
    },
    onError: (err) => setZoneEditMsg(formatApiError(err)),
  })

  const gwStatus = gwStatusQuery.data
  const reportedActuators = gwStatus?.reported?.actuators ?? {}
  const desiredModes = gwStatus?.desired?.modes ?? {}
  const commands = commandsQuery.data ?? []

  // Tính tiến độ vụ
  const elapsedDays = activeCycle
    ? Math.max(0, (Date.now() - new Date(activeCycle.started_at).getTime()) / 86_400_000)
    : 0
  const elapsedHours = elapsedDays * 24
  const expectedDays = params?.cycle.days ?? 40
  const progressPct = Math.min(100, Math.round((elapsedDays / expectedDays) * 100))
  const dayOrdinal = Math.max(1, Math.floor(elapsedDays) + 1)
  const isOverdue = Boolean(activeCycle && elapsedDays > expectedDays)

  const handleTriggerActuator = (act: ActuatorName, currentState: string) => {
    const turningOn = currentState !== 'on'
    if (turningOn) {
      if (act === 'mist' && reportedActuators.fan === 'on') {
        setCmdFeedback({
          ok: false,
          text: 'Vi phạm Interlock: Quạt đối lưu đang BẬT, không thể bật máy tạo ẩm cùng lúc.',
        })
        return
      }
      if (durationInput < 1 || durationInput > 3600) {
        setCmdFeedback({ ok: false, text: 'Thời lượng bật phải từ 1 đến 3600 giây.' })
        return
      }
    }
    setCmdFeedback(null)
    sendCommandMutation.mutate({
      actuator: act,
      action: turningOn ? 'on' : 'off',
      duration_s: turningOn ? durationInput : undefined,
    })
  }

  const handleToggleMode = (act: ActuatorName, currentMode: string) => {
    const nextMode = currentMode === 'manual' ? 'auto' : 'manual'
    const until =
      nextMode === 'manual' && manualMinutes > 0
        ? new Date(Date.now() + manualMinutes * 60_000).toISOString()
        : null
    setModeMutation.mutate({ actuator: act, mode: nextMode, until })
  }

  const handleZoneEditSubmit = (e: FormEvent) => {
    e.preventDefault()
    const parsedArea = Number(editZoneArea)
    updateZoneMutation.mutate({
      name: editZoneName.trim(),
      crop_profile_id: editZoneProfileId || null,
      area_m2: parsedArea > 0 ? parsedArea : null,
    })
  }

  const dliVal = dliQuery.data?.dli_mol_m2_day
  const dliOpt = params?.light.dli_optimal
  const vpdOpt = params?.vpd.optimal ?? [0.8, 1.2]
  const vpdLowCrit = params?.vpd.low_crit ?? 0.4
  const vpdHighCrit = params?.vpd.high_crit ?? 1.6
  const soilMin = params?.soil_moisture_pct.min ?? 45
  const soilMax = params?.soil_moisture_pct.max ?? 70

  const latestForecastDetails = latestForecast?.details
  const forecastVal = latestForecast?.value
  const forecastPct =
    typeof latestForecast?.score === 'number' ? Math.round(latestForecast.score * 100) : null
  const forecastArea = activeCycle?.area_m2 ?? zone?.area_m2 ?? null

  const forecastChartData = useMemo(
    () =>
      [...cyclePredictions]
        .reverse()
        .map((p) => ({
          tsLabel: formatDateTimeVi(p.ts),
          value: p.value,
        })),
    [cyclePredictions],
  )

  return (
    <div>
      {/* Header & Zone switcher */}
      <div className="page-header">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <Link to="/" style={{ color: 'var(--muted)', textDecoration: 'none' }}>
              ← Tổng quan
            </Link>
            <h2 style={{ margin: 0 }}>
              🌱 {zone?.name || (zone ? `Zone ${zone.zone_index}` : 'Chi tiết Zone & Điều khiển')}
            </h2>
            {gh?.is_simulated && <span className="badge info">Mô phỏng</span>}
            {gh && (
              <span className={`badge ${gh.online ? 'ok' : 'bad'}`}>
                {gh.online ? '● Gateway Online' : '○ Gateway Offline'}
              </span>
            )}
          </div>
          <p className="muted" style={{ margin: '0.25rem 0 0' }}>
            {gh?.name || ''} • Cây hiện tại:{' '}
            <strong>{formatCropName(profile?.crop_code, profile?.crop_name)}</strong>
            {zone?.area_m2 ? ` • Diện tích: ${zone.area_m2} m²` : ''}
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap', alignItems: 'center' }}>
          {(gh?.zones ?? []).map((z) => (
            <button
              key={z.id}
              type="button"
              className={`btn btn-sm ${z.id === zoneId ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => navigate(`/zones/${z.id}`)}
            >
              {z.name || `Zone ${z.zone_index}`}
            </button>
          ))}
          {isOwner && zone && (
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => setShowZoneEdit((v) => !v)}
            >
              ✏️ Sửa Zone
            </button>
          )}
        </div>
      </div>

      {zoneEditMsg && (
        <div className="alert-banner info" style={{ marginBottom: '1rem' }}>
          {zoneEditMsg}
        </div>
      )}

      {showZoneEdit && isOwner && (
        <form onSubmit={handleZoneEditSubmit} className="card">
          <div className="card-header">
            <h3>✏️ Cập nhật thông tin Zone</h3>
          </div>
          <div className="grid grid-cols-3">
            <div className="form-group">
              <label>Tên Zone</label>
              <input
                type="text"
                value={editZoneName}
                onChange={(e) => setEditZoneName(e.target.value)}
                required
              />
            </div>
            <div className="form-group">
              <label>Crop Profile</label>
              <select
                value={editZoneProfileId}
                onChange={(e) => setEditZoneProfileId(e.target.value)}
              >
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.crop_name} ({p.variety || 'real'})
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Diện tích canh tác (m²)</label>
              <input
                type="number"
                step="0.1"
                min="0.05"
                value={editZoneArea}
                onChange={(e) => setEditZoneArea(e.target.value)}
              />
            </div>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
            <button type="button" className="btn btn-secondary" onClick={() => setShowZoneEdit(false)}>
              Huỷ
            </button>
            <button type="submit" className="btn btn-primary" disabled={updateZoneMutation.isPending}>
              Lưu thay đổi
            </button>
          </div>
        </form>
      )}

      {/* Cảnh báo chất lượng dữ liệu nếu mẫu mới nhất != ok */}
      {latest && latest.quality && latest.quality !== 'ok' && (
        <div className="alert-banner warning" style={{ marginBottom: '1rem' }}>
          <strong>⚠ Cảnh báo chất lượng dữ liệu (Kiểm tra luật):</strong> Mẫu gần nhất lúc{' '}
          {formatTimeShortVi(latest.ts)} bị gắn nhãn{' '}
          <strong>{QUALITY_LABELS[latest.quality] ?? latest.quality}</strong> và đã được loại khỏi vòng điều khiển tự động.
        </div>
      )}

      {/* Thẻ chỉ số tức thời */}
      <div className="grid grid-cols-4" style={{ marginBottom: '1.25rem' }}>
        <div className="metric-tile">
          <span className="label">Nhiệt độ &amp; Độ ẩm</span>
          <span className="value">
            {latestOk?.air_temp !== null && latestOk?.air_temp !== undefined
              ? latestOk.air_temp.toFixed(1)
              : '—'}
            <span className="unit">°C</span>
          </span>
          <span className="subtext muted">
            Độ ẩm:{' '}
            {latestOk?.air_rh !== null && latestOk?.air_rh !== undefined
              ? `${latestOk.air_rh.toFixed(1)}%`
              : '—'}
          </span>
        </div>

        <div
          className={`metric-tile ${
            latestOk?.vpd !== null && latestOk?.vpd !== undefined
              ? latestOk.vpd >= vpdOpt[0] && latestOk.vpd <= vpdOpt[1]
                ? 'vpd-optimal'
                : latestOk.vpd <= vpdLowCrit || latestOk.vpd >= vpdHighCrit
                  ? 'vpd-danger'
                  : 'vpd-warning'
              : ''
          }`}
        >
          <span className="label">VPD hiện tại</span>
          <span className="value">
            {latestOk?.vpd !== null && latestOk?.vpd !== undefined ? latestOk.vpd.toFixed(2) : '—'}
            <span className="unit">kPa</span>
          </span>
          <span className="subtext muted">
            Tối ưu: {vpdOpt[0]}–{vpdOpt[1]} kPa
          </span>
        </div>

        <div className="metric-tile">
          <span className="label">Độ ẩm đất</span>
          <span className="value">
            {latestOk?.soil_moisture !== null && latestOk?.soil_moisture !== undefined
              ? latestOk.soil_moisture.toFixed(1)
              : '—'}
            <span className="unit">%</span>
          </span>
          <span className="subtext muted">
            Hysteresis: {soilMin}% – {soilMax}%
          </span>
        </div>

        <div className="metric-tile">
          <span className="label">Ánh sáng &amp; DLI hôm nay</span>
          <span className="value">
            {dliVal !== undefined ? dliVal.toFixed(1) : '—'}
            <span className="unit">mol/m²/ngày</span>
          </span>
          <span className="subtext muted">
            Lux: {latestOk?.lux !== null && latestOk?.lux !== undefined ? Math.round(latestOk.lux) : 'Không có'}
            {dliOpt ? ` · Tối ưu ${dliOpt[0]}–${dliOpt[1]}` : ''}
          </span>
        </div>
      </div>

      {/* Khung AI – Vụ trồng & Năng suất dự kiến */}
      <div className="ai-card" style={{ marginBottom: '1.25rem' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            flexWrap: 'wrap',
            gap: '0.75rem',
            marginBottom: '0.85rem',
          }}
        >
          <div>
            <h3 style={{ margin: 0, color: 'var(--primary-text)' }}>
              🌾 Vụ trồng &amp; Dự báo Năng suất AI (ước tính)
            </h3>
            <span className="muted" style={{ fontSize: '0.8rem' }}>
              Mô hình LightGBM toàn cục theo dõi tích luỹ vi khí hậu từ đầu vụ tới hiện tại
            </span>
          </div>

          {canOperate && zone && (
            <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
              {!activeCycle ? (
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  onClick={() => {
                    setCycleError(null)
                    setShowStartModal(true)
                  }}
                >
                  🌱 Bắt đầu vụ
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    onClick={() => {
                      setCycleError(null)
                      setShowHarvestModal(true)
                    }}
                  >
                    🧺 Thu hoạch
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    disabled={abandonCycleMutation.isPending}
                    onClick={() => {
                      if (window.confirm('Xác nhận huỷ vụ trồng đang chạy? (Sẽ không tạo mẫu huấn luyện)')) {
                        abandonCycleMutation.mutate(activeCycle.id)
                      }
                    }}
                  >
                    Huỷ vụ
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        <div className="grid grid-cols-2" style={{ gap: '1rem' }}>
          {/* Vụ hiện tại */}
          <div style={{ background: 'rgba(255,255,255,0.85)', padding: '0.9rem', borderRadius: '8px' }}>
            {activeCycle ? (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <strong>
                    Vụ đang trồng: {formatCropName(activeCycle.crop_code, activeCycle.crop_name)}
                  </strong>
                  <span className={`badge ${isOverdue ? 'warning' : 'ok'}`}>
                    {isOverdue
                      ? `Đã quá thời gian vụ dự kiến (${dayOrdinal}/${expectedDays} ngày)`
                      : `Ngày thứ ${dayOrdinal} / ${expectedDays}`}
                  </span>
                </div>
                <div className="muted" style={{ fontSize: '0.8rem', margin: '0.35rem 0 0.5rem' }}>
                  Bắt đầu: {formatDateTimeVi(activeCycle.started_at)} • Diện tích: {activeCycle.area_m2} m²
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progressPct}%` }} />
                </div>
              </>
            ) : (
              <div>
                <strong>Chưa có vụ trồng đang hoạt động</strong>
                <p className="muted" style={{ fontSize: '0.82rem', margin: '0.35rem 0 0' }}>
                  Bấm <em>&quot;Bắt đầu vụ&quot;</em> để bắt đầu ghi nhận khí hậu vụ trồng và nhận dự báo năng suất.
                </p>
              </div>
            )}
          </div>

          {/* Năng suất dự kiến */}
          <div style={{ background: 'rgba(255,255,255,0.85)', padding: '0.9rem', borderRadius: '8px' }}>
            {!activeModelQuery.isLoading && !activeModelQuery.data ? (
              <div>
                <strong>Chưa có mô hình</strong>
                <p className="muted" style={{ fontSize: '0.82rem', margin: '0.35rem 0 0' }}>
                  Hệ thống chưa kích hoạt mô hình <code>yield</code>.
                </p>
              </div>
            ) : !activeCycle ? (
              <div>
                <strong>Chưa có dự báo vụ hiện tại</strong>
                <p className="muted" style={{ fontSize: '0.82rem', margin: '0.35rem 0 0' }}>
                  Cần có vụ trồng đang chạy để tính năng suất dự kiến.
                </p>
              </div>
            ) : !latestForecast ||
              (params && elapsedHours < params.ai.min_cycle_hours) ? (
              <div>
                <strong>Chưa đủ dữ liệu để dự báo</strong>
                <p className="muted" style={{ fontSize: '0.82rem', margin: '0.35rem 0 0' }}>
                  Cần tối thiểu {params?.ai.min_cycle_hours ?? 0.5} giờ dữ liệu kể từ khi bắt đầu vụ và độ phủ đạt ngưỡng.
                </p>
              </div>
            ) : (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                  <span className="muted" style={{ fontSize: '0.78rem', fontWeight: 600 }}>
                    NĂNG SUẤT DỰ KIẾN (ƯỚC TÍNH)
                  </span>
                  {latestForecastDetails?.low_confidence && (
                    <span
                      className="badge warning"
                      title={`Độ phủ: ${Math.round((latestForecastDetails.coverage ?? 0) * 100)}%${
                        latestForecastDetails.ood_features?.length
                          ? `, ngoài dải: ${latestForecastDetails.ood_features.join(', ')}`
                          : ''
                      }`}
                    >
                      ⚠ Độ tin cậy thấp
                    </span>
                  )}
                </div>

                <div style={{ fontSize: '1.35rem', fontWeight: 700, color: 'var(--primary)', margin: '0.2rem 0' }}>
                  {typeof forecastVal === 'number' ? forecastVal.toFixed(1) : '—'} kg/m²
                  {latestForecastDetails?.interval && (
                    <span className="muted" style={{ fontSize: '0.9rem', fontWeight: 500 }}>
                      {' '}
                      ({latestForecastDetails.interval[0].toFixed(1)}–
                      {latestForecastDetails.interval[1].toFixed(1)})
                    </span>
                  )}
                  {forecastPct !== null && (
                    <span className="badge ok" style={{ marginLeft: '0.5rem' }}>
                      {forecastPct}% mức chuẩn
                    </span>
                  )}
                </div>

                <div className="muted" style={{ fontSize: '0.8rem' }}>
                  Sản lượng ước tính cả vụ:{' '}
                  <strong>
                    {typeof forecastVal === 'number' && forecastArea
                      ? `${(forecastVal * forecastArea).toFixed(1)} kg`
                      : '—'}
                  </strong>{' '}
                  • Cập nhật: {formatDateTimeVi(latestForecast.ts)} • Mô hình v
                  {activeModelQuery.data?.version ?? '?'}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Biểu đồ xu hướng dự báo trong vụ */}
        {forecastChartData.length >= 2 && (
          <div style={{ marginTop: '0.85rem', background: 'rgba(255,255,255,0.85)', padding: '0.75rem', borderRadius: '8px' }}>
            <div className="muted" style={{ fontSize: '0.78rem', marginBottom: '0.35rem', fontWeight: 600 }}>
              Xu hướng năng suất dự kiến trong vụ (kg/m²)
            </div>
            <div style={{ width: '100%', height: 130 }}>
              <ResponsiveContainer>
                <LineChart data={forecastChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="tsLabel" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} width={42} />
                  <Tooltip />
                  <Line type="monotone" dataKey="value" name="Năng suất (kg/m²)" stroke="#15803d" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </div>

      {/* Bộ chọn khoảng thời gian & 4 Biểu đồ trực tiếp */}
      <div className="card">
        <div className="card-header">
          <div>
            <h3>📈 Biểu đồ Vi khí hậu &amp; Lớp phủ Sự kiện</h3>
            <span className="muted" style={{ fontSize: '0.8rem' }}>
              Độ mịn: <code>agg={rangeOpt.agg}</code> • {readings.length} điểm dữ liệu
            </span>
          </div>
          <div className="tab-strip">
            {RANGE_OPTIONS.map((r) => (
              <button
                key={r.key}
                type="button"
                className={`btn btn-sm ${rangeKey === r.key ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setRangeKey(r.key)}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {overlayEvents.length > 0 && (
          <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
            <span className="muted" style={{ fontSize: '0.78rem', alignSelf: 'center' }}>
              Sự kiện trong khung giờ:
            </span>
            {overlayEvents.map((ev, i) => (
              <span key={`${ev.timeLabel}-${i}`} className="badge muted" style={{ borderColor: ev.color }}>
                {ev.timeLabel} · {ev.label}
              </span>
            ))}
          </div>
        )}

        {readingsQuery.isLoading ? (
          <p className="muted">Đang tải dữ liệu chuỗi thời gian...</p>
        ) : chartData.length === 0 ? (
          <p className="muted" style={{ textAlign: 'center', padding: '2rem 0' }}>
            Chưa có dữ liệu cảm biến trong khoảng thời gian đã chọn.
          </p>
        ) : (
          <div className="grid grid-cols-2">
            {/* 1. Biểu đồ VPD */}
            <div className="chart-box" style={{ marginBottom: 0 }}>
              <div className="chart-header">
                <strong>VPD (kPa) – Dải tối ưu [{vpdOpt[0]}–{vpdOpt[1]}]</strong>
              </div>
              <div style={{ width: '100%', height: 240 }}>
                <ResponsiveContainer>
                  <AreaChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="timeLabel" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} width={40} />
                    <Tooltip />
                    <ReferenceArea y1={vpdOpt[0]} y2={vpdOpt[1]} fill="#dcfce7" fillOpacity={0.7} />
                    <ReferenceLine y={vpdLowCrit} stroke="#ef4444" strokeDasharray="4 4" label="Low Crit" />
                    <ReferenceLine y={vpdHighCrit} stroke="#f59e0b" strokeDasharray="4 4" label="High Crit" />
                    {overlayEvents.map((ev, i) => (
                      <ReferenceLine key={i} x={ev.timeLabel} stroke={ev.color} strokeDasharray="2 2" />
                    ))}
                    <Area type="monotone" dataKey="vpd" name="VPD (kPa)" stroke="#15803d" fill="#bbf7d0" strokeWidth={2} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* 2. Nhiệt độ & Độ ẩm */}
            <div className="chart-box" style={{ marginBottom: 0 }}>
              <div className="chart-header">
                <strong>Nhiệt độ (°C) &amp; Độ ẩm không khí (%RH)</strong>
              </div>
              <div style={{ width: '100%', height: 240 }}>
                <ResponsiveContainer>
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="timeLabel" tick={{ fontSize: 11 }} />
                    <YAxis yAxisId="left" tick={{ fontSize: 11 }} width={36} />
                    <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} width={38} domain={[0, 100]} />
                    <Tooltip />
                    <Legend />
                    <Line yAxisId="left" type="monotone" dataKey="air_temp" name="Nhiệt độ (°C)" stroke="#ef4444" strokeWidth={2} dot={false} />
                    <Line yAxisId="right" type="monotone" dataKey="air_rh" name="Độ ẩm (%RH)" stroke="#0284c7" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* 3. Độ ẩm đất */}
            <div className="chart-box" style={{ marginBottom: 0 }}>
              <div className="chart-header">
                <strong>Độ ẩm đất (%) – Hysteresis [{soilMin}%–{soilMax}%]</strong>
              </div>
              <div style={{ width: '100%', height: 240 }}>
                <ResponsiveContainer>
                  <AreaChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="timeLabel" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} width={38} domain={[0, 100]} />
                    <Tooltip />
                    <ReferenceLine y={soilMin} stroke="#ef4444" strokeDasharray="4 4" label="Min tưới" />
                    <ReferenceLine y={soilMax} stroke="#15803d" strokeDasharray="4 4" label="Max ngắt" />
                    <Area type="monotone" dataKey="soil_moisture" name="Ẩm đất (%)" stroke="#0369a1" fill="#bae6fd" strokeWidth={2} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* 4. Ánh sáng Lux */}
            <div className="chart-box" style={{ marginBottom: 0 }}>
              <div className="chart-header">
                <strong>Ánh sáng (Lux)</strong>
              </div>
              <div style={{ width: '100%', height: 240 }}>
                <ResponsiveContainer>
                  <AreaChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="timeLabel" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} width={48} />
                    <Tooltip />
                    <Area type="monotone" dataKey="lux" name="Ánh sáng (lux)" stroke="#d97706" fill="#fde68a" strokeWidth={2} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Khối Điều khiển thiết bị chấp hành & Interlock */}
      <div id="control-section" className="card">
        <div className="card-header">
          <div>
            <h3>🎛️ Điều khiển Chấp hành (Hysteresis Cố định &amp; Manual)</h3>
            <span className="muted" style={{ fontSize: '0.8rem' }}>
              Chế độ Auto dùng luật hysteresis cố định theo Crop Profile (Ẩm đất {soilMin}–{soilMax}%, VPD {vpdLowCrit}–{vpdHighCrit} kPa).
            </span>
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <label style={{ margin: 0, display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
              Thời lượng bật (s):
              <input
                type="number"
                min={1}
                max={3600}
                style={{ width: 85 }}
                value={durationInput}
                onChange={(e) => setDurationInput(Number(e.target.value))}
              />
            </label>
            <label style={{ margin: 0, display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
              Hạn Manual:
              <select
                style={{ width: 'auto' }}
                value={manualMinutes}
                onChange={(e) => setManualMinutes(Number(e.target.value))}
              >
                <option value={15}>15 phút</option>
                <option value={30}>30 phút</option>
                <option value={60}>60 phút</option>
                <option value={0}>Không giới hạn</option>
              </select>
            </label>
          </div>
        </div>

        <div className="alert-banner warning" style={{ marginBottom: '1rem' }}>
          <strong>Quy tắc Interlock (Quạt ↔ Tạo ẩm):</strong> Quạt đối lưu và Máy tạo ẩm <strong>không</strong> chạy đồng thời. Khi quạt bật do rủi ro nấm/nhiệt hoặc thủ công, máy tạo ẩm bị ép tắt và khoá tạm thời.
        </div>

        {cmdFeedback && (
          <div
            className={`alert-banner ${cmdFeedback.ok ? 'ok' : 'bad'}`}
            style={{ marginBottom: '1rem' }}
          >
            {cmdFeedback.text}
          </div>
        )}

        <div className="grid grid-cols-4" style={{ marginBottom: '1.25rem' }}>
          {ACTUATORS.map((act) => {
            const state = reportedActuators[act] ?? 'off'
            const modeObj = desiredModes[act]
            const mode = modeObj?.mode ?? 'auto'
            const isOn = state === 'on'
            const interlockLocked = act === 'mist' && reportedActuators.fan === 'on'

            return (
              <div key={act} className={`actuator-card ${isOn ? 'on' : ''}`}>
                <div className="title-row">
                  <strong>{ACTUATOR_LABELS[act]}</strong>
                  <span className="status-indicator" />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.82rem' }}>
                  <span>
                    Trạng thái: <strong>{isOn ? 'ĐANG BẬT' : 'TẮT'}</strong>
                  </span>
                  <span className={`badge ${mode === 'manual' ? 'warning' : 'info'}`}>
                    {mode === 'manual' ? 'Manual' : 'Auto'}
                  </span>
                </div>
                {mode === 'manual' && modeObj?.until && (
                  <div className="muted" style={{ fontSize: '0.73rem' }}>
                    Hết hạn: {formatTimeShortVi(modeObj.until)}
                  </div>
                )}
                {canOperate && (
                  <div style={{ display: 'flex', gap: '0.4rem' }}>
                    <button
                      type="button"
                      className={`btn btn-sm ${isOn ? 'btn-danger' : 'btn-primary'}`}
                      style={{ flex: 1 }}
                      disabled={sendCommandMutation.isPending || (!isOn && interlockLocked)}
                      onClick={() => handleTriggerActuator(act, state)}
                    >
                      {isOn ? 'TẮT' : `BẬT (${durationInput}s)`}
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-secondary"
                      disabled={setModeMutation.isPending}
                      onClick={() => handleToggleMode(act, mode)}
                    >
                      {mode === 'manual' ? 'Về Auto' : 'Manual'}
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Lịch sử lệnh gần nhất */}
        <h4 style={{ margin: '0 0 0.6rem', fontSize: '0.9rem' }}>📜 Lịch sử lệnh điều khiển gần nhất</h4>
        {commands.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>
            Chưa có lệnh điều khiển nào cho nhà kính này.
          </p>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Thiết bị</th>
                  <th>Hành động</th>
                  <th>Nguồn</th>
                  <th>Trạng thái</th>
                  <th>Lý do / Ghi chú</th>
                </tr>
              </thead>
              <tbody>
                {commands.map((c) => {
                  const st = CMD_STATUS_BADGE[c.status] ?? { label: c.status, cls: 'muted' }
                  return (
                    <tr key={c.id}>
                      <td className="muted">{formatTimeShortVi(c.created_at)}</td>
                      <td>
                        <strong>{ACTUATOR_LABELS[c.actuator as ActuatorName] ?? c.actuator}</strong>
                      </td>
                      <td>
                        {c.action.toUpperCase()}
                        {c.duration_s ? ` (${c.duration_s}s)` : ''}
                      </td>
                      <td>
                        <span className="badge muted">{c.source}</span>
                      </td>
                      <td>
                        <span className={`badge ${st.cls}`}>{st.label}</span>
                      </td>
                      <td className="muted" style={{ fontSize: '0.8rem' }}>
                        {c.reject_reason || c.reason || '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Lịch sử vụ trồng */}
      <div className="card">
        <div className="card-header">
          <h3>📅 Lịch sử Vụ trồng của Zone</h3>
          <span className="badge info">{cycles.length} vụ</span>
        </div>

        {cycles.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>
            Zone này chưa có lịch sử vụ trồng nào.
          </p>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Cây trồng</th>
                  <th>Bắt đầu</th>
                  <th>Thu hoạch</th>
                  <th>Diện tích (m²)</th>
                  <th>Tổng sản lượng (kg)</th>
                  <th>Năng suất (kg/m²)</th>
                  <th>Trạng thái</th>
                  <th>Ghi chú</th>
                </tr>
              </thead>
              <tbody>
                {cycles.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <strong>{formatCropName(c.crop_code, c.crop_name)}</strong>
                    </td>
                    <td>{formatDateTimeVi(c.started_at)}</td>
                    <td>{formatDateTimeVi(c.harvested_at)}</td>
                    <td>{c.area_m2}</td>
                    <td>{c.yield_kg !== null ? c.yield_kg.toFixed(2) : '—'}</td>
                    <td>{c.yield_kg_m2 !== null ? c.yield_kg_m2.toFixed(2) : '—'}</td>
                    <td>
                      <span
                        className={`badge ${
                          c.status === 'active'
                            ? 'info'
                            : c.status === 'harvested'
                              ? 'ok'
                              : 'muted'
                        }`}
                      >
                        {c.status === 'active'
                          ? 'Đang trồng'
                          : c.status === 'harvested'
                            ? 'Đã thu hoạch'
                            : 'Đã huỷ'}
                      </span>
                    </td>
                    <td className="muted" style={{ fontSize: '0.8rem' }}>
                      {c.notes || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal Bắt đầu vụ */}
      {showStartModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card">
            <div className="card-header">
              <h3>🌱 Bắt đầu Vụ trồng mới</h3>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setShowStartModal(false)}
              >
                ✕
              </button>
            </div>

            {cycleError && (
              <div className="alert-banner bad" style={{ marginBottom: '0.9rem' }}>
                {cycleError}
              </div>
            )}

            <form
              onSubmit={(e) => {
                e.preventDefault()
                const area = Number(startAreaM2)
                if (!startProfileId || !(area > 0)) {
                  setCycleError('Diện tích phải lớn hơn 0.')
                  return
                }
                startCycleMutation.mutate({
                  crop_profile_id: startProfileId,
                  area_m2: area,
                  notes: startNotes.trim() || null,
                })
              }}
            >
              <div className="form-group">
                <label>Crop Profile cho vụ</label>
                <select
                  value={startProfileId}
                  onChange={(e) => setStartProfileId(e.target.value)}
                  required
                >
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.crop_name} ({p.variety || 'real'})
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>Diện tích canh tác (m²) *</label>
                <input
                  type="number"
                  step="0.05"
                  min="0.05"
                  value={startAreaM2}
                  onChange={(e) => setStartAreaM2(e.target.value)}
                  required
                />
              </div>
              <div className="form-group">
                <label>Ghi chú vụ</label>
                <input
                  type="text"
                  value={startNotes}
                  onChange={(e) => setStartNotes(e.target.value)}
                  placeholder="VD: Vụ xà lách đợt 1"
                />
              </div>
              <p className="muted" style={{ fontSize: '0.78rem' }}>
                Bắt đầu vụ sẽ gán Crop Profile đã chọn cho Zone và tự động đồng bộ cấu hình xuống Gateway.
              </p>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowStartModal(false)}
                >
                  Huỷ
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={startCycleMutation.isPending}
                >
                  {startCycleMutation.isPending ? 'Đang tạo...' : 'Bắt đầu vụ'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Thu hoạch */}
      {showHarvestModal && activeCycle && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card">
            <div className="card-header">
              <h3>🧺 Ghi nhận Thu hoạch Vụ trồng</h3>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setShowHarvestModal(false)}
              >
                ✕
              </button>
            </div>

            {cycleError && (
              <div className="alert-banner bad" style={{ marginBottom: '0.9rem' }}>
                {cycleError}
              </div>
            )}

            <form
              onSubmit={(e) => {
                e.preventDefault()
                const kg = Number(harvestKg)
                if (Number.isNaN(kg) || kg < 0) {
                  setCycleError('Tổng khối lượng thu hoạch phải ≥ 0 kg.')
                  return
                }
                harvestCycleMutation.mutate({
                  cycleId: activeCycle.id,
                  yield_kg: kg,
                  notes: harvestNotes.trim() || null,
                })
              }}
            >
              <div className="form-group">
                <label>Tổng khối lượng thu hoạch (kg) *</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={harvestKg}
                  onChange={(e) => setHarvestKg(e.target.value)}
                  required
                />
                <span className="muted" style={{ fontSize: '0.8rem' }}>
                  Quy đổi năng suất: <strong>{(Number(harvestKg || 0) / activeCycle.area_m2).toFixed(2)} kg/m²</strong>{' '}
                  (trên {activeCycle.area_m2} m²)
                </span>
              </div>
              <div className="form-group">
                <label>Ghi chú thu hoạch</label>
                <input
                  type="text"
                  value={harvestNotes}
                  onChange={(e) => setHarvestNotes(e.target.value)}
                  placeholder="Chất lượng lá tốt, không sâu bệnh..."
                />
              </div>
              <p className="muted" style={{ fontSize: '0.78rem' }}>
                Sau khi ghi nhận, dữ liệu khí hậu &amp; năng suất của vụ sẽ được tổng hợp làm mẫu huấn luyện nếu đủ độ phủ dữ liệu.
              </p>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowHarvestModal(false)}
                >
                  Huỷ
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={harvestCycleMutation.isPending}
                >
                  {harvestCycleMutation.isPending ? 'Đang lưu...' : 'Xác nhận Thu hoạch'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
