import { useState, type FormEvent } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  formatCropName,
  formatDateTimeVi,
  type CropCycle,
  type CropProfile,
  type CropRecommendationDetails,
  type Greenhouse,
  type MlModelItem,
  type PredictionItem,
  type ReadingPoint,
  type Zone,
} from '../lib/types'

// ─── helpers ────────────────────────────────────────────────────────────────

function cycleDayNumber(startedAt: string): number {
  const diffMs = Date.now() - new Date(startedAt).getTime()
  return Math.max(1, Math.floor(diffMs / 86_400_000) + 1)
}

function fmtTemp(v: number | null | undefined) {
  return v != null ? `${v.toFixed(1)} °C` : '—'
}
function fmtRh(v: number | null | undefined) {
  return v != null ? `${v.toFixed(0)}%` : '—'
}
function fmtSoil(v: number | null | undefined) {
  return v != null ? `${v.toFixed(0)}%` : '—'
}
function fmtLux(v: number | null | undefined) {
  if (v == null) return '—'
  return v >= 1000 ? `${(v / 1000).toFixed(1)} klux` : `${Math.round(v)} lux`
}

function qualityBadgeClass(q: string | null | undefined): string {
  if (!q || q === 'ok') return 'ok'
  if (q === 'spike' || q === 'stuck') return 'warning'
  return 'bad'
}

// ─── SensorRow ───────────────────────────────────────────────────────────────

function SensorRow({
  icon,
  label,
  value,
  highlight,
}: {
  icon: string
  label: string
  value: string
  highlight?: boolean
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0.35rem 0',
        borderBottom: '1px solid rgba(0,0,0,0.05)',
      }}
    >
      <span style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>
        {icon} {label}
      </span>
      <span
        style={{
          fontSize: '0.92rem',
          fontWeight: 700,
          color: highlight ? 'var(--danger)' : 'inherit',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
      </span>
    </div>
  )
}

// ─── ZoneCard ────────────────────────────────────────────────────────────────

interface ZoneCardProps {
  zone: Greenhouse['zones'][number]
  activeCycle: CropCycle | undefined
  profile: CropProfile | undefined
  reading: ReadingPoint | null
}

function ZoneCard({ zone, activeCycle, profile, reading }: ZoneCardProps) {
  const navigate = useNavigate()

  const cropLabel = activeCycle
    ? formatCropName(activeCycle.crop_code, activeCycle.crop_name)
    : profile
      ? formatCropName(profile.crop_code, profile.crop_name)
      : 'Chưa gắn cây'

  const q = reading?.quality

  return (
    <div
      role="button"
      tabIndex={0}
      className="card"
      onClick={() => navigate(`/zones/${zone.id}`)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') navigate(`/zones/${zone.id}`)
      }}
      style={{
        cursor: 'pointer',
        transition: 'box-shadow 0.18s, transform 0.18s',
        outline: 'none',
        userSelect: 'none',
        borderTop: `4px solid ${activeCycle ? 'var(--primary)' : 'var(--muted)'}`,
        background: '#ffffff',
      }}
      onMouseEnter={(e) => {
        ;(e.currentTarget as HTMLDivElement).style.boxShadow = '0 8px 24px rgba(22,163,74,0.18)'
        ;(e.currentTarget as HTMLDivElement).style.transform = 'translateY(-2px)'
      }}
      onMouseLeave={(e) => {
        ;(e.currentTarget as HTMLDivElement).style.boxShadow = ''
        ;(e.currentTarget as HTMLDivElement).style.transform = ''
      }}
    >
      {/* Header zone */}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          marginBottom: '0.75rem',
          gap: '0.4rem',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
            <span
              style={{
                background: 'var(--primary)',
                color: '#fff',
                borderRadius: '50%',
                width: '1.65rem',
                height: '1.65rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '0.8rem',
                fontWeight: 700,
                flexShrink: 0,
              }}
            >
              {zone.zone_index}
            </span>
            <strong style={{ fontSize: '1.05rem' }}>{zone.name || `Zone ${zone.zone_index}`}</strong>
          </div>
          <div style={{ fontSize: '0.82rem', color: 'var(--muted)', marginTop: '0.25rem' }}>
            🌱 Cây: <strong>{cropLabel}</strong>
            {zone.area_m2 ? ` • ${zone.area_m2} m²` : ''}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.25rem' }}>
          {activeCycle && (
            <span className="badge ok" style={{ fontSize: '0.72rem', whiteSpace: 'nowrap' }}>
              Ngày {cycleDayNumber(activeCycle.started_at)}
            </span>
          )}
          {reading && (
            <span
              className={`badge ${qualityBadgeClass(q)}`}
              style={{ fontSize: '0.72rem', whiteSpace: 'nowrap' }}
              title={`Chất lượng cảm biến: ${q ?? 'ok'}`}
            >
              {q && q !== 'ok' ? `⚠ ${q}` : '● Cảm biến OK'}
            </span>
          )}
        </div>
      </div>

      {/* 4 chỉ số sensor */}
      {reading ? (
        <div style={{ marginBottom: '0.6rem' }}>
          <SensorRow
            icon="🌡️"
            label="Nhiệt độ không khí"
            value={fmtTemp(reading.air_temp)}
            highlight={reading.air_temp != null && reading.air_temp > 35}
          />
          <SensorRow
            icon="💧"
            label="Độ ẩm không khí"
            value={fmtRh(reading.air_rh)}
            highlight={reading.air_rh != null && reading.air_rh > 90}
          />
          <SensorRow
            icon="🌱"
            label="Độ ẩm đất"
            value={fmtSoil(reading.soil_moisture)}
            highlight={reading.soil_moisture != null && reading.soil_moisture < 20}
          />
          <SensorRow icon="☀️" label="Cường độ ánh sáng" value={fmtLux(reading.lux)} />
        </div>
      ) : (
        <div
          style={{
            textAlign: 'center',
            padding: '1.2rem 0',
            color: 'var(--muted)',
            fontSize: '0.84rem',
          }}
        >
          Chưa nhận được tín hiệu cảm biến
        </div>
      )}

      {/* Footer CTA */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderTop: '1px solid var(--border)',
          paddingTop: '0.55rem',
          marginTop: '0.25rem',
        }}
      >
        <span className="muted" style={{ fontSize: '0.75rem' }}>
          Điều khiển bơm, quạt &amp; thu hoạch
        </span>
        <span style={{ fontSize: '0.82rem', color: 'var(--primary)', fontWeight: 600 }}>
          Chi tiết zone →
        </span>
      </div>
    </div>
  )
}

// ─── GreenhousePage ───────────────────────────────────────────────────────────

export default function GreenhousePage() {
  const { ghId } = useParams<{ ghId: string }>()
  const { isOwner } = useAuth()
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null)

  // Sửa Zone states
  const [showZoneEdit, setShowZoneEdit] = useState(false)
  const [editZoneId, setEditZoneId] = useState('')
  const [editZoneName, setEditZoneName] = useState('')
  const [editZoneProfileId, setEditZoneProfileId] = useState('')
  const [editZoneArea, setEditZoneArea] = useState('')
  const [zoneEditMsg, setZoneEditMsg] = useState<string | null>(null)
  const [zoneEditError, setZoneEditError] = useState<string | null>(null)

  // Lấy thông tin nhà kính
  const ghQuery = useQuery({
    queryKey: ['greenhouses'],
    queryFn: () => api<Greenhouse[]>('/greenhouses'),
  })

  const profilesQuery = useQuery({
    queryKey: ['crop-profiles'],
    queryFn: () => api<CropProfile[]>('/crop-profiles'),
  })

  const gh = ghQuery.data?.find((g) => g.id === ghId)
  const zones = gh?.zones ?? []
  const profilesById = new Map((profilesQuery.data ?? []).map((p) => [p.id, p]))

  // Active cycles
  const cycleQueries = useQueries({
    queries: zones.map((z) => ({
      queryKey: ['cycles', z.id, 'active'],
      queryFn: () => api<CropCycle[]>(`/zones/${z.id}/cycles?status=active&limit=1`),
      enabled: zones.length > 0,
    })),
  })

  // Readings mới nhất của từng zone
  const readingQueries = useQueries({
    queries: zones.map((z) => ({
      queryKey: ['readings', z.id, 'latest'],
      queryFn: () =>
        api<ReadingPoint[]>(`/zones/${z.id}/readings?limit=1&agg=raw`).then(
          (arr) => arr?.[0] ?? null,
        ),
      enabled: zones.length > 0,
      refetchInterval: 15_000,
    })),
  })

  // Gợi ý cây trồng cho nhà kính này
  const recQuery = useQuery({
    queryKey: ['recommendations', ghId],
    queryFn: () =>
      api<PredictionItem<CropRecommendationDetails> | null>(
        `/greenhouses/${ghId}/recommendations`,
      ),
    enabled: Boolean(ghId),
  })

  const activeModelQuery = useQuery({
    queryKey: ['models', 'active'],
    queryFn: () => api<MlModelItem | null>('/models/active'),
  })

  const refreshMutation = useMutation({
    mutationFn: (id: string) =>
      api<{ status: string; greenhouse_id: string }>(`/greenhouses/${id}/recommendations/refresh`, {
        method: 'POST',
      }),
    onMutate: () => {
      setRefreshing(true)
      setRefreshMsg(null)
    },
    onSuccess: () => {
      setRefreshMsg('Đang tính toán lại dự đoán năng suất từ dữ liệu khí hậu...')
      window.setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ['recommendations', ghId] })
        setRefreshing(false)
        setRefreshMsg('Đã cập nhật bảng xếp hạng cây trồng mới nhất!')
      }, 2000)
    },
    onError: (err) => {
      setRefreshing(false)
      setRefreshMsg(formatApiError(err))
    },
  })

  const handleSelectZoneToEdit = (targetZone: Greenhouse['zones'][number]) => {
    setEditZoneId(targetZone.id)
    setEditZoneName(targetZone.name || '')
    setEditZoneProfileId(targetZone.crop_profile_id || '')
    setEditZoneArea(targetZone.area_m2 ? String(targetZone.area_m2) : '1.0')
    setZoneEditMsg(null)
    setZoneEditError(null)
    setShowZoneEdit(true)
  }

  const updateZoneMutation = useMutation({
    mutationFn: (payload: { zoneId: string; name: string; crop_profile_id: string | null; area_m2: number | null }) =>
      api<Zone>(`/zones/${payload.zoneId}`, {
        method: 'PUT',
        body: JSON.stringify({
          name: payload.name,
          crop_profile_id: payload.crop_profile_id,
          area_m2: payload.area_m2,
        }),
      }),
    onSuccess: (_, variables) => {
      setShowZoneEdit(false)
      setZoneEditMsg(`Đã cập nhật thành công ${variables.name}.`)
      setZoneEditError(null)
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
    },
    onError: (err) => {
      setZoneEditError(formatApiError(err))
    },
  })

  const handleZoneEditSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!editZoneId) return
    const parsedArea = Number(editZoneArea)
    updateZoneMutation.mutate({
      zoneId: editZoneId,
      name: editZoneName.trim(),
      crop_profile_id: editZoneProfileId || null,
      area_m2: parsedArea > 0 ? parsedArea : null,
    })
  }

  const activeCycleByZone = new Map<string, CropCycle>()
  zones.forEach((z, idx) => {
    const list = cycleQueries[idx]?.data
    if (list && list.length > 0) activeCycleByZone.set(z.id, list[0])
  })

  const readingByZone = new Map<string, ReadingPoint | null>()
  zones.forEach((z, idx) => {
    readingByZone.set(z.id, readingQueries[idx]?.data ?? null)
  })

  const rec = recQuery.data ?? null
  const details = rec?.details
  const climate = details?.climate_summary ?? {}
  const ranking = details?.ranking ?? []

  // Loading / Error
  if (ghQuery.isLoading) {
    return (
      <div className="card muted" style={{ textAlign: 'center', padding: '2.5rem' }}>
        Đang tải thông tin nhà kính...
      </div>
    )
  }

  if (ghQuery.isError || !gh) {
    return (
      <div>
        <div className="alert-banner bad">
          {ghQuery.isError
            ? `Không tải được nhà kính: ${formatApiError(ghQuery.error)}`
            : 'Không tìm thấy nhà kính này.'}
        </div>
        <Link to="/" className="btn btn-secondary" style={{ marginTop: '1rem' }}>
          ← Quay lại Tổng quan
        </Link>
      </div>
    )
  }

  return (
    <div>
      {/* ── Header ── */}
      <div className="page-header" style={{ marginBottom: '1.25rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <Link
              to="/"
              style={{
                color: 'var(--primary)',
                fontWeight: 600,
                textDecoration: 'none',
                fontSize: '0.84rem',
              }}
            >
              ← Tổng quan
            </Link>
            <h2 style={{ margin: 0 }}>🏡 {gh.name || 'Nhà kính chưa đặt tên'}</h2>
            {gh.is_simulated && <span className="badge info">Mô phỏng</span>}
            <span className={`badge ${gh.online ? 'ok' : 'bad'}`}>
              {gh.online ? '● Gateway Online' : '○ Gateway Ngoại tuyến'}
            </span>
            {gh.open_alerts > 0 && (
              <span className="badge bad" title="Số cảnh báo đang mở">
                🔔 {gh.open_alerts} cảnh báo
              </span>
            )}
          </div>
          {gh.location && (
            <p className="muted" style={{ margin: '0.25rem 0 0', fontSize: '0.84rem' }}>
              📍 Vị trí: {gh.location}
            </p>
          )}
        </div>
      </div>

      {/* ── 1. SƠ ĐỒ NHÀ KÍNH & CÁC VÙNG TRỒNG (ZONES) ── */}
      <div
        style={{
          background: 'linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)',
          border: '1.5px solid #bbf7d0',
          borderRadius: 'var(--radius)',
          padding: '1.1rem 1.25rem 1.25rem',
          marginBottom: '1.5rem',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '0.9rem',
            flexWrap: 'wrap',
            gap: '0.5rem',
          }}
        >
          <div>
            <h3 style={{ margin: 0, fontSize: '1rem', color: '#15803d' }}>
              🗺️ Sơ đồ Nhà kính &amp; Vi khí hậu các Zone
            </h3>
            <span className="muted" style={{ fontSize: '0.78rem' }}>
              Bao gồm {zones.length} vùng trồng • Nhấp vào từng Zone để điều khiển thiết bị &amp; xem chi tiết
            </span>
          </div>

          {isOwner && zones.length > 0 && (
            <button
              type="button"
              className={`btn btn-sm ${showZoneEdit ? 'btn-primary' : 'btn-secondary'}`}
              style={
                !showZoneEdit
                  ? {
                      background: '#ffffff',
                      borderColor: '#86efac',
                      color: '#166534',
                      fontWeight: 600,
                    }
                  : undefined
              }
              onClick={() => {
                if (!showZoneEdit) {
                  const target = zones.find((z) => z.id === editZoneId) || zones[0]
                  handleSelectZoneToEdit(target)
                } else {
                  setShowZoneEdit(false)
                }
              }}
            >
              {showZoneEdit ? '✕ Đóng form sửa' : '✏️ Sửa Zone'}
            </button>
          )}
        </div>

        {zoneEditMsg && (
          <div
            className="alert-banner info"
            style={{
              marginBottom: '0.9rem',
              background: '#ecfdf5',
              borderColor: '#a7f3d0',
              color: '#065f46',
            }}
          >
            ✓ {zoneEditMsg}
          </div>
        )}
        {zoneEditError && (
          <div className="alert-banner bad" style={{ marginBottom: '0.9rem' }}>
            {zoneEditError}
          </div>
        )}

        {/* Form cập nhật thông tin Zone ngay trong hộp */}
        {showZoneEdit && isOwner && (
          <form
            onSubmit={handleZoneEditSubmit}
            style={{
              background: '#ffffff',
              border: '1.5px solid #86efac',
              borderRadius: 'var(--radius)',
              padding: '1rem 1.15rem',
              marginBottom: '1rem',
              boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.05)',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '0.85rem',
                borderBottom: '1px solid #f0fdf4',
                paddingBottom: '0.5rem',
                flexWrap: 'wrap',
                gap: '0.5rem',
              }}
            >
              <h4 style={{ margin: 0, fontSize: '0.95rem', color: '#166534' }}>
                ✏️ Cập nhật thông tin vùng trồng
              </h4>

              {zones.length > 1 && (
                <div style={{ display: 'flex', gap: '0.35rem', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>Chọn zone:</span>
                  {zones.map((z) => (
                    <button
                      key={z.id}
                      type="button"
                      className={`btn btn-sm ${z.id === editZoneId ? 'btn-primary' : 'btn-secondary'}`}
                      style={{ fontSize: '0.78rem', padding: '0.2rem 0.5rem' }}
                      onClick={() => handleSelectZoneToEdit(z)}
                    >
                      {z.name || `Zone ${z.zone_index}`}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="grid grid-cols-3" style={{ gap: '0.85rem' }}>
              <div className="form-group" style={{ margin: 0 }}>
                <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>Tên Zone *</label>
                <input
                  type="text"
                  value={editZoneName}
                  onChange={(e) => setEditZoneName(e.target.value)}
                  placeholder="Ví dụ: Khu A - Dâu tây"
                  required
                />
              </div>

              <div className="form-group" style={{ margin: 0 }}>
                <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>Loại cây trồng (Crop Profile)</label>
                <select
                  value={editZoneProfileId}
                  onChange={(e) => setEditZoneProfileId(e.target.value)}
                >
                  <option value="">-- Chưa gán profile --</option>
                  {(profilesQuery.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.crop_name} ({p.variety || 'real'})
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group" style={{ margin: 0 }}>
                <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>Diện tích canh tác (m²)</label>
                <input
                  type="number"
                  step="0.1"
                  min="0.05"
                  value={editZoneArea}
                  onChange={(e) => setEditZoneArea(e.target.value)}
                  placeholder="1.0"
                />
              </div>
            </div>

            <div
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '0.5rem',
                marginTop: '1rem',
              }}
            >
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setShowZoneEdit(false)}
              >
                Huỷ
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={updateZoneMutation.isPending}
              >
                {updateZoneMutation.isPending ? 'Đang lưu...' : 'Lưu thay đổi'}
              </button>
            </div>
          </form>
        )}

        {zones.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: '1.5rem',
              color: 'var(--muted)',
              fontSize: '0.88rem',
            }}
          >
            Nhà kính này chưa có vùng trồng nào.
          </div>
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: `repeat(${Math.min(zones.length, 2)}, 1fr)`,
              gap: '1rem',
            }}
          >
            {zones.map((z) => (
              <ZoneCard
                key={z.id}
                zone={z}
                activeCycle={activeCycleByZone.get(z.id)}
                profile={z.crop_profile_id ? profilesById.get(z.crop_profile_id) : undefined}
                reading={readingByZone.get(z.id) ?? null}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── 2. PHẦN GỢI Ý CÂY TRỒNG THEO KHÍ HẬU (TÍCH HỢP TRỰC TIẾP) ── */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="card-header" style={{ alignItems: 'flex-start' }}>
          <div>
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              🌱 Gợi ý cây trồng tối ưu theo vi khí hậu
            </h3>
            <span className="muted" style={{ fontSize: '0.82rem' }}>
              Mô hình AI dự đoán loại cây đem lại năng suất cao nhất dựa vào lịch sử nhiệt độ, ẩm độ &amp; ánh sáng thực tế của nhà kính này
            </span>
          </div>

          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={refreshing || refreshMutation.isPending || !activeModelQuery.data}
            onClick={() => ghId && refreshMutation.mutate(ghId)}
          >
            {refreshing ? '⏳ Đang tính...' : '🔄 Làm mới gợi ý'}
          </button>
        </div>

        {refreshMsg && (
          <div className="alert-banner ok" style={{ marginBottom: '1rem' }}>
            {refreshMsg}
          </div>
        )}

        {/* Tóm tắt điều kiện khí hậu trung bình */}
        {details?.climate_summary && (
          <div
            style={{
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: 'var(--radius)',
              padding: '0.75rem 1rem',
              marginBottom: '1rem',
              fontSize: '0.84rem',
            }}
          >
            <div style={{ fontWeight: 600, color: 'var(--muted)', marginBottom: '0.4rem', fontSize: '0.76rem', textTransform: 'uppercase' }}>
              🌤️ Vi khí hậu trung bình đo được tại nhà kính:
            </div>
            <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
              <div>
                🌡️ Nhiệt độ TB:{' '}
                <strong>{typeof climate.t_mean === 'number' ? `${climate.t_mean.toFixed(1)} °C` : '—'}</strong>
                <span className="muted" style={{ fontSize: '0.78rem', marginLeft: '0.35rem' }}>
                  (Ngày {climate.t_day_mean?.toFixed(1) ?? '—'}°C / Đêm {climate.t_night_mean?.toFixed(1) ?? '—'}°C)
                </span>
              </div>
              <div>
                💧 Độ ẩm TB:{' '}
                <strong>{typeof climate.rh_mean === 'number' ? `${climate.rh_mean.toFixed(1)}%` : '—'}</strong>
              </div>
              <div>
                📊 VPD TB:{' '}
                <strong>{typeof climate.vpd_mean === 'number' ? `${climate.vpd_mean.toFixed(2)} kPa` : '—'}</strong>
              </div>
              {typeof climate.dli_mean === 'number' && (
                <div>
                  ☀️ Ánh sáng (DLI): <strong>{climate.dli_mean.toFixed(1)} mol/m²/ngày</strong>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Danh sách xếp hạng cây trồng */}
        {recQuery.isLoading ? (
          <div className="muted" style={{ padding: '1rem 0', textAlign: 'center' }}>
            Đang phân tích khí hậu để gợi ý cây trồng...
          </div>
        ) : ranking.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '1.5rem 0', color: 'var(--muted)', fontSize: '0.86rem' }}>
            Chưa đủ dữ liệu vi khí hậu trong cửa sổ đánh giá để đưa ra bảng xếp hạng. Hãy để cảm biến hoạt động thêm thời gian.
          </div>
        ) : (
          <div className="table-container" style={{ margin: 0 }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: '4rem' }}>Hạng</th>
                  <th>Loại cây</th>
                  <th>Phù hợp ước tính</th>
                  <th>Năng suất dự kiến</th>
                  <th>Khoảng tin cậy</th>
                  <th>Đánh giá khí hậu</th>
                </tr>
              </thead>
              <tbody>
                {ranking.map((cand, idx) => (
                  <tr key={cand.crop_code} style={{ background: idx === 0 ? '#f0fdf4' : undefined }}>
                    <td>
                      <span
                        className={`badge ${idx === 0 ? 'ok' : 'muted'}`}
                        style={{ fontWeight: 700 }}
                      >
                        #{idx + 1}
                      </span>
                    </td>
                    <td>
                      <strong>{formatCropName(cand.crop_code, cand.crop_name)}</strong>
                      {idx === 0 && (
                        <span className="badge ok" style={{ marginLeft: '0.4rem', fontSize: '0.7rem' }}>
                          Khuyên trồng
                        </span>
                      )}
                    </td>
                    <td>
                      <strong style={{ color: cand.relative_yield >= 0.8 ? 'var(--success)' : 'inherit' }}>
                        {Math.round(cand.relative_yield * 100)}%
                      </strong>
                    </td>
                    <td>
                      <strong>{cand.expected_kg_m2.toFixed(1)} kg/m²</strong>
                    </td>
                    <td className="muted" style={{ fontSize: '0.8rem' }}>
                      {cand.interval[0].toFixed(1)} – {cand.interval[1].toFixed(1)} kg/m²
                    </td>
                    <td>
                      <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: '0.78rem', color: 'var(--muted)' }}>
                        {cand.reasons.slice(0, 2).map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {rec && (
          <div className="muted" style={{ fontSize: '0.76rem', marginTop: '0.75rem', textAlign: 'right' }}>
            Cập nhật lần cuối: {formatDateTimeVi(rec.ts)}
          </div>
        )}
      </div>

      {/* ── 3. THÔNG TIN PHỤ TRỢ ── */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: '0.75rem',
          fontSize: '0.84rem',
        }}
      >
        <div className="card" style={{ padding: '0.75rem 1rem' }}>
          <div className="muted" style={{ fontSize: '0.75rem', marginBottom: '0.3rem' }}>
            Trạng thái Gateway
          </div>
          <strong style={{ color: gh.online ? 'var(--success)' : 'var(--danger)' }}>
            {gh.online ? '● Đang hoạt động' : '○ Ngoại tuyến'}
          </strong>
        </div>
        <div className="card" style={{ padding: '0.75rem 1rem' }}>
          <div className="muted" style={{ fontSize: '0.75rem', marginBottom: '0.3rem' }}>
            Số vùng trồng
          </div>
          <strong>{zones.length} zone</strong>
        </div>
        <div className="card" style={{ padding: '0.75rem 1rem' }}>
          <div className="muted" style={{ fontSize: '0.75rem', marginBottom: '0.3rem' }}>
            Cảnh báo đang mở
          </div>
          <strong style={{ color: gh.open_alerts > 0 ? 'var(--danger)' : 'var(--success)' }}>
            {gh.open_alerts} cảnh báo
          </strong>
        </div>
      </div>
    </div>
  )
}

