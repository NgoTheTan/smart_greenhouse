import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import { Button, Card, Field, SelectField, StatusDot } from '../components/ui'
import {
  formatCropName,
  type CropCycle,
  type CropProfile,
  type CropRecommendationDetails,
  type Greenhouse,
  type PredictionItem,
  type ReadingPoint,
} from '../lib/types'

function cycleDayNumber(startedAt: string): number {
  const diffMs = Date.now() - new Date(startedAt).getTime()
  return Math.max(1, Math.floor(diffMs / 86_400_000) + 1)
}

function fmtTemp(v: number | null | undefined): { val: string; unit: string } {
  return v != null ? { val: v.toFixed(1), unit: '°C' } : { val: '—', unit: '°C' }
}
function fmtRh(v: number | null | undefined): { val: string; unit: string } {
  return v != null ? { val: v.toFixed(0), unit: '%' } : { val: '—', unit: '%' }
}
function fmtSoil(v: number | null | undefined): { val: string; unit: string } {
  return v != null ? { val: v.toFixed(0), unit: '%' } : { val: '—', unit: '%' }
}
function fmtLux(v: number | null | undefined): { val: string; unit: string } {
  if (v == null) return { val: '—', unit: 'klux' }
  if (v >= 1000) return { val: (v / 1000).toFixed(1), unit: 'klux' }
  return { val: Math.round(v).toString(), unit: 'lux' }
}

export default function OverviewPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [newLocation, setNewLocation] = useState('')
  const [newZonesCount, setNewZonesCount] = useState<number>(2)
  const [createError, setCreateError] = useState<string | null>(null)

  const greenhousesQuery = useQuery({
    queryKey: ['greenhouses'],
    queryFn: () => api<Greenhouse[]>('/greenhouses'),
  })

  const profilesQuery = useQuery({
    queryKey: ['crop-profiles'],
    queryFn: () => api<CropProfile[]>('/crop-profiles'),
  })

  const greenhouses = greenhousesQuery.data ?? []
  const profilesById = new Map((profilesQuery.data ?? []).map((p) => [p.id, p]))

  const allZones = greenhouses.flatMap((gh) =>
    gh.zones.map((z) => ({
      ...z,
      greenhouseName: gh.name || gh.id,
    })),
  )

  const activeCycleQueries = useQueries({
    queries: allZones.map((z) => ({
      queryKey: ['cycles', z.id, 'active'],
      queryFn: () => api<CropCycle[]>(`/zones/${z.id}/cycles?status=active&limit=1`),
      enabled: allZones.length > 0,
    })),
  })

  const activeCycleByZone = new Map<string, CropCycle>()
  allZones.forEach((z, idx) => {
    const list = activeCycleQueries[idx]?.data
    if (list && list.length > 0) {
      activeCycleByZone.set(z.id, list[0])
    }
  })

  // Đọc dữ liệu cảm biến mới nhất của từng zone (nếu có telemetry từ Node)
  const readingQueries = useQueries({
    queries: allZones.map((z) => ({
      queryKey: ['readings', z.id, 'latest'],
      queryFn: () =>
        api<ReadingPoint[]>(`/zones/${z.id}/readings?limit=1&agg=raw`).then(
          (arr) => arr?.[0] ?? null,
        ),
      enabled: allZones.length > 0,
      refetchInterval: 15_000,
    })),
  })

  const readingByZone = new Map<string, ReadingPoint | null>()
  allZones.forEach((z, idx) => {
    readingByZone.set(z.id, readingQueries[idx]?.data ?? null)
  })

  const recommendationQueries = useQueries({
    queries: greenhouses.map((gh) => ({
      queryKey: ['recommendations', gh.id],
      queryFn: () =>
        api<PredictionItem<CropRecommendationDetails> | null>(`/greenhouses/${gh.id}/recommendations`),
      enabled: greenhouses.length > 0,
    })),
  })

  const recByGh = new Map<string, PredictionItem<CropRecommendationDetails> | null>()
  greenhouses.forEach((gh, idx) => {
    recByGh.set(gh.id, recommendationQueries[idx]?.data ?? null)
  })

  // Phát hiện các khu vườn đã đến hoặc quá hạn thu hoạch dự kiến
  const readyToHarvestZones = allZones.filter((z) => {
    const cycle = activeCycleByZone.get(z.id)
    if (!cycle) return false
    const profile = profilesById.get(cycle.crop_profile_id)
    const expectedDays = profile?.parameters_json?.cycle?.days ?? 90
    const elapsedDays = (Date.now() - new Date(cycle.started_at).getTime()) / 86_400_000
    return elapsedDays >= expectedDays
  })

  const createGhMutation = useMutation({
    mutationFn: (payload: { name: string; location: string | null; zones?: Array<{ zone_index: number; name: string; crop_profile_id: string | null; pump_channel: number; area_m2: number }> }) =>
      api<Greenhouse>('/greenhouses', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
      setShowCreateModal(false)
      setNewName('')
      setNewLocation('')
      setNewZonesCount(2)
      setCreateError(null)
    },
    onError: (err) => {
      setCreateError(formatApiError(err))
    },
  })

  const handleCreateSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!newName.trim()) return
    setCreateError(null)

    const availableProfiles = (profilesQuery.data ?? []).filter((p) => p.variety !== 'demo')
    const initialZones = Array.from({ length: newZonesCount }, (_, idx) => {
      const zIndex = idx + 1
      const defaultProf = availableProfiles[idx % (availableProfiles.length || 1)]
      return {
        zone_index: zIndex,
        name: `Khu ${zIndex}`,
        crop_profile_id: defaultProf?.id ?? null,
        pump_channel: zIndex,
        area_m2: 20.0,
      }
    })

    createGhMutation.mutate({
      name: newName.trim(),
      location: newLocation.trim() ? newLocation.trim() : null,
      zones: initialZones,
    })
  }

  const onlineCount = greenhouses.filter((g) => g.online).length

  return (
    <div>
      {/* Header trang Tổng quan chuẩn theo ảnh thiết kế */}
      <div className="page-header">
        <div>
          <h2>Tổng quan</h2>
          <p className="muted">Vi khí hậu và vụ trồng hiện tại của từng nhà kính.</p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', flexWrap: 'wrap' }}>
          <StatusDot
            status="ok"
            textColor="var(--text-muted, #626861)"
            label={`${onlineCount}/${greenhouses.length} nhà kính online`}
          />
          <Button variant="primary" onClick={() => setShowCreateModal(true)}>
            + Tạo nhà kính mới
          </Button>
        </div>
      </div>

      {readyToHarvestZones.length > 0 && (
        <Card
          style={{
            borderColor: '#F59E0B',
            background: '#FFFBEB',
            marginBottom: '1.5rem',
            padding: '1rem 1.25rem',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '1rem',
              flexWrap: 'wrap',
            }}
          >
            <div>
              <strong style={{ color: '#92400E', fontSize: '0.95rem', display: 'block', marginBottom: '0.2rem' }}>
                Thông báo mùa vụ: Có {readyToHarvestZones.length} khu vườn đã đến kỳ thu hoạch!
              </strong>
              <p style={{ margin: 0, fontSize: '0.85rem', color: '#78350F' }}>
                {readyToHarvestZones
                  .map((z) => {
                    const c = activeCycleByZone.get(z.id)
                    return `${z.greenhouseName} – ${z.name || `Zone ${z.zone_index}`} (${formatCropName(
                      c?.crop_code,
                      c?.crop_name,
                    )})`
                  })
                  .join('; ')}
                . Hãy ghi nhận sản lượng thực tế và đánh giá mùa vụ.
              </p>
            </div>
            <Link
              to={`/zones/${readyToHarvestZones[0].id}`}
              className="btn btn-sm btn-secondary"
              style={{
                borderColor: '#B45309',
                color: '#92400E',
                background: '#FFFFFF',
                fontWeight: 600,
                whiteSpace: 'nowrap',
              }}
            >
              Đến xem &amp; Phản hồi mùa vụ →
            </Link>
          </div>
        </Card>
      )}

      {greenhousesQuery.isLoading && (
        <Card>
          <p className="muted" style={{ margin: 0 }}>Đang tải danh sách nhà kính...</p>
        </Card>
      )}

      {greenhousesQuery.isError && (
        <div className="alert-banner bad">
          Không tải được danh sách nhà kính: {formatApiError(greenhousesQuery.error)}
        </div>
      )}

      {!greenhousesQuery.isLoading && greenhouses.length === 0 && (
        <Card style={{ textAlign: 'center', padding: '3rem 1.5rem' }}>
          <h3 style={{ margin: '0 0 0.5rem 0' }}>Chưa có nhà kính nào trong farm</h3>
          <p className="muted" style={{ margin: 0 }}>
            Bấm &quot;+ Tạo nhà kính mới&quot; để khởi tạo nhà kính đầu tiên cho vườn của bạn.
          </p>
        </Card>
      )}

      {/* Grid danh sách Nhà kính theo thiết kế mới (đúng 1200px, hàng kẻ chạy hết bề ngang card) */}
      <div className="grid grid-cols-2">
        {greenhouses.map((gh) => {
          return (
            <Card
              key={gh.id}
              style={{
                padding: 0,
                overflow: 'hidden',
                borderRadius: '10px',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {/* Header card nhà kính: Tên, trạng thái Online/Offline, Vị trí, Số liệu tổng quan & Link Vào nhà kính */}
              <div
                style={{
                  padding: '20px 24px 16px 24px',
                  borderBottom: '1px solid var(--border-row, #EEECE5)',
                  cursor: 'pointer',
                }}
                onClick={() => navigate(`/greenhouses/${gh.id}`)}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '0.5rem',
                    marginBottom: '4px',
                  }}
                >
                  <h3
                    style={{
                      margin: 0,
                      fontSize: '16px',
                      fontWeight: 700,
                      color: 'var(--text-main, #1C211E)',
                      lineHeight: 1.3,
                    }}
                  >
                    {gh.name || 'Nhà kính chưa đặt tên'}
                  </h3>

                  <StatusDot
                    status={gh.online ? 'ok' : 'offline'}
                    label={gh.online ? 'Online' : 'Offline'}
                  />
                </div>

                <div
                  style={{
                    fontSize: '13px',
                    color: 'var(--text-muted, #626861)',
                    marginBottom: '16px',
                  }}
                >
                  {gh.location || 'Chưa cập nhật vị trí'}
                </div>

                <div
                  style={{
                    fontSize: '13px',
                    color: 'var(--text-muted, #626861)',
                  }}
                >
                  {gh.open_alerts} cảnh báo · {gh.zones.length} vùng trồng
                </div>
              </div>

              {/* Danh sách các Zone trong Nhà kính - đường kẻ chạy hết bề ngang card */}
              <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
                {gh.zones.map((z, idx) => {
                  const profile = z.crop_profile_id ? profilesById.get(z.crop_profile_id) : undefined
                  const activeCycle = activeCycleByZone.get(z.id)
                  const cropLabel = activeCycle
                    ? formatCropName(activeCycle.crop_code, activeCycle.crop_name)
                    : profile
                      ? formatCropName(profile.crop_code, profile.crop_name)
                      : 'Chưa gắn cây'

                  const reading = readingByZone.get(z.id)
                  const hasReading = Boolean(
                    reading &&
                    (reading.air_temp != null || reading.air_rh != null || reading.soil_moisture != null || reading.lux != null)
                  )
                  const isSensorFault = reading?.quality && reading.quality !== 'ok'
                  const t = fmtTemp(reading?.air_temp)
                  const rh = fmtRh(reading?.air_rh)
                  const sm = fmtSoil(reading?.soil_moisture)
                  const lx = fmtLux(reading?.lux)

                  const isLast = idx === gh.zones.length - 1

                  return (
                    <div
                      key={z.id}
                      onClick={() => navigate(`/zones/${z.id}`)}
                      style={{
                        padding: '16px 24px',
                        borderBottom: isLast ? 'none' : '1px solid var(--border-row, #EEECE5)',
                        cursor: 'pointer',
                        transition: 'background-color 0.1s ease',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = '#FAFAF8'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'transparent'
                      }}
                    >
                      {/* Header zone: Tên zone, diện tích, ngày thứ & trạng thái cảm biến */}
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          justifyContent: 'space-between',
                          gap: '0.75rem',
                          marginBottom: '1rem',
                        }}
                      >
                        <div>
                          <div
                            style={{
                              fontSize: '1rem',
                              fontWeight: 700,
                              color: 'var(--text-main, #1C211E)',
                              marginBottom: '0.25rem',
                            }}
                          >
                            {z.name || `Khu ${z.zone_index}`}
                          </div>
                          <div style={{ fontSize: '0.82rem', color: 'var(--text-muted, #626861)' }}>
                            {cropLabel} · {z.area_m2 ? `${z.area_m2} m²` : '—'}
                          </div>
                        </div>

                        <div style={{ textAlign: 'right' }}>
                          <div
                            style={{
                              fontSize: '0.82rem',
                              fontWeight: 600,
                              color: 'var(--text-main, #1C211E)',
                              marginBottom: '0.2rem',
                            }}
                          >
                            {activeCycle ? `Ngày thứ ${cycleDayNumber(activeCycle.started_at)}` : 'Chưa có vụ'}
                          </div>
                          <StatusDot
                            status={isSensorFault ? 'warning' : hasReading ? 'ok' : 'unallocated'}
                            label={isSensorFault ? 'Lỗi cảm biến' : hasReading ? 'Cảm biến OK' : 'Chưa có dữ liệu'}
                          />
                        </div>
                      </div>

                      {/* Khối hiển thị 4 chỉ số cảm biến lớn theo lưới 2x2 */}
                      <div
                        style={{
                          display: 'grid',
                          gridTemplateColumns: 'repeat(2, 1fr)',
                          gap: '1.25rem 1rem',
                          padding: '0.25rem 0 0.25rem 0',
                          fontVariantNumeric: 'tabular-nums',
                        }}
                      >
                        {/* Nhiệt độ */}
                        <div>
                          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted, #626861)', marginBottom: '0.25rem' }}>
                            Nhiệt độ không khí
                          </div>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.3rem' }}>
                            <span style={{ fontSize: '1.65rem', fontWeight: 700, color: 'var(--text-main, #1C211E)', lineHeight: 1.1 }}>
                              {t.val}
                            </span>
                            <span style={{ fontSize: '0.88rem', color: 'var(--text-muted, #626861)' }}>
                              {t.unit}
                            </span>
                          </div>
                        </div>

                        {/* Độ ẩm không khí */}
                        <div>
                          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted, #626861)', marginBottom: '0.25rem' }}>
                            Độ ẩm không khí
                          </div>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.3rem' }}>
                            <span style={{ fontSize: '1.65rem', fontWeight: 700, color: 'var(--text-main, #1C211E)', lineHeight: 1.1 }}>
                              {rh.val}
                            </span>
                            <span style={{ fontSize: '0.88rem', color: 'var(--text-muted, #626861)' }}>
                              {rh.unit}
                            </span>
                          </div>
                        </div>

                        {/* Độ ẩm đất */}
                        <div>
                          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted, #626861)', marginBottom: '0.25rem' }}>
                            Độ ẩm đất
                          </div>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.3rem' }}>
                            <span style={{ fontSize: '1.65rem', fontWeight: 700, color: 'var(--text-main, #1C211E)', lineHeight: 1.1 }}>
                              {sm.val}
                            </span>
                            <span style={{ fontSize: '0.88rem', color: 'var(--text-muted, #626861)' }}>
                              {sm.unit}
                            </span>
                          </div>
                        </div>

                        {/* Cường độ ánh sáng */}
                        <div>
                          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted, #626861)', marginBottom: '0.25rem' }}>
                            Cường độ ánh sáng
                          </div>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.3rem' }}>
                            <span style={{ fontSize: '1.65rem', fontWeight: 700, color: 'var(--text-main, #1C211E)', lineHeight: 1.1 }}>
                              {lx.val}
                            </span>
                            <span style={{ fontSize: '0.88rem', color: 'var(--text-muted, #626861)' }}>
                              {lx.unit}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </Card>
          )
        })}
      </div>

      {/* Modal Tạo nhà kính mới */}
      {showCreateModal && (
        <div className="modal-backdrop" onClick={() => setShowCreateModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="card-header">
              <h3 style={{ margin: 0 }}>Tạo nhà kính mới</h3>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setShowCreateModal(false)}
                style={{ padding: '0.1rem 0.5rem' }}
              >
                ✕
              </button>
            </div>

            {createError && (
              <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
                {createError}
              </div>
            )}

            <form onSubmit={handleCreateSubmit}>
              <Field
                label="Tên nhà kính *"
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Ví dụ: Nhà kính A1 – Đà Lạt"
                required
                autoFocus
              />

              <Field
                label="Vị trí / Địa chỉ"
                type="text"
                value={newLocation}
                onChange={(e) => setNewLocation(e.target.value)}
                placeholder="Ví dụ: Phường 7, TP. Đà Lạt"
              />

              <SelectField
                label="Số vùng trồng (Zone) khởi tạo ban đầu"
                value={newZonesCount}
                onChange={(e) => setNewZonesCount(Number(e.target.value))}
                hint="Bạn có thể thêm hoặc bớt zone bất cứ lúc nào trong bảng cấu hình nhà kính."
              >
                <option value={1}>1 zone</option>
                <option value={2}>2 zone</option>
                <option value={3}>3 zone</option>
                <option value={4}>4 zone</option>
              </SelectField>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.65rem', marginTop: '1.25rem' }}>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setShowCreateModal(false)}
                >
                  Hủy
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={createGhMutation.isPending || !newName.trim()}
                >
                  {createGhMutation.isPending ? 'Đang tạo...' : 'Tạo nhà kính'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
