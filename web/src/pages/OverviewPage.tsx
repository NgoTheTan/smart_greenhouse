import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  formatCropName,
  type CropCycle,
  type CropProfile,
  type CropRecommendationDetails,
  type Greenhouse,
  type PredictionItem,
} from '../lib/types'

function cycleDayNumber(startedAt: string): number {
  const diffMs = Date.now() - new Date(startedAt).getTime()
  return Math.max(1, Math.floor(diffMs / 86_400_000) + 1)
}

export default function OverviewPage() {
  const { isOwner } = useAuth()
  const queryClient = useQueryClient()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [newLocation, setNewLocation] = useState('')
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
    mutationFn: (payload: { name: string; location: string | null }) =>
      api<Greenhouse>('/greenhouses', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
      setShowCreateModal(false)
      setNewName('')
      setNewLocation('')
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
    createGhMutation.mutate({
      name: newName.trim(),
      location: newLocation.trim() ? newLocation.trim() : null,
    })
  }

  const onlineCount = greenhouses.filter((g) => g.online).length

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>🌿 Tổng quan Nhà kính &amp; Farm</h2>
          <p className="muted" style={{ margin: 0 }}>
            Theo dõi vi khí hậu, vụ trồng hiện tại và gợi ý cây trồng theo từng nhà kính
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
          <span className="badge ok">
            ● {onlineCount}/{greenhouses.length} Nhà kính Online
          </span>
          {isOwner && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setShowCreateModal(true)}
            >
              + Tạo nhà kính mới
            </button>
          )}
        </div>
      </div>

      {readyToHarvestZones.length > 0 && (
        <div
          style={{
            background: 'linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%)',
            border: '2px solid #f59e0b',
            borderRadius: 'var(--radius)',
            padding: '1.1rem 1.25rem',
            marginBottom: '1.25rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '1rem',
            flexWrap: 'wrap',
            boxShadow: '0 4px 12px rgba(245, 158, 11, 0.15)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.85rem', flex: 1, minWidth: 260 }}>
            <span style={{ fontSize: '2.4rem' }}>🌾</span>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.2rem' }}>
                <span className="badge warning" style={{ fontWeight: 700 }}>
                  THÔNG BÁO MÙA VỤ
                </span>
                <strong style={{ color: '#92400e', fontSize: '1rem' }}>
                  Có {readyToHarvestZones.length} khu vườn đã đến kỳ thu hoạch!
                </strong>
              </div>
              <p style={{ margin: 0, fontSize: '0.86rem', color: '#78350f', lineHeight: 1.4 }}>
                {readyToHarvestZones
                  .map((z) => {
                    const c = activeCycleByZone.get(z.id)
                    return `${z.greenhouseName} – ${z.name || `Zone ${z.zone_index}`} (${formatCropName(
                      c?.crop_code,
                      c?.crop_name,
                    )})`
                  })
                  .join('; ')}
                . Hãy ghi nhận sản lượng thực tế và đánh giá mùa vụ. Cảm ơn bạn đã đóng góp!
              </p>
            </div>
          </div>
          <Link
            to={`/zones/${readyToHarvestZones[0].id}`}
            className="btn btn-primary"
            style={{
              background: '#d97706',
              borderColor: '#b45309',
              fontWeight: 700,
              whiteSpace: 'nowrap',
              boxShadow: '0 2px 6px rgba(180, 83, 9, 0.25)',
            }}
          >
            🧺 Đến xem &amp; Phản hồi mùa vụ →
          </Link>
        </div>
      )}

      {greenhousesQuery.isLoading && (
        <div className="card muted">Đang tải danh sách nhà kính...</div>
      )}

      {greenhousesQuery.isError && (
        <div className="alert-banner bad">
          Không tải được danh sách nhà kính: {formatApiError(greenhousesQuery.error)}
        </div>
      )}

      {!greenhousesQuery.isLoading && greenhouses.length === 0 && (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <h3>Chưa có nhà kính nào trong farm</h3>
          <p className="muted">
            Bấm &quot;Tạo nhà kính mới&quot; để khởi tạo nhà kính đầu tiên cho vườn của bạn với 2 zone mặc định.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2">
        {greenhouses.map((gh) => {
          const rec = recByGh.get(gh.id)
          const top1 = rec?.details?.ranking?.[0]

          return (
            <div key={gh.id} className="card">
              <div className="card-header">
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                    <Link
                      to={`/greenhouses/${gh.id}`}
                      style={{ textDecoration: 'none', color: 'inherit' }}
                    >
                      <h3 style={{ margin: 0, cursor: 'pointer' }}>
                        🏡 {gh.name || 'Nhà kính chưa đặt tên'}
                      </h3>
                    </Link>
                    {gh.is_simulated && <span className="badge info">Mô phỏng</span>}
                  </div>
                  <span className="muted" style={{ fontSize: '0.8rem' }}>
                    📍 {gh.location || 'Chưa cập nhật vị trí'}
                  </span>
                </div>
                <span className={`badge ${gh.online ? 'ok' : 'bad'}`}>
                  {gh.online ? '● Online' : '○ Offline'}
                </span>
              </div>

              <div
                style={{
                  display: 'flex',
                  gap: '1rem',
                  marginBottom: '1rem',
                  fontSize: '0.85rem',
                  flexWrap: 'wrap',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <div style={{ display: 'flex', gap: '1rem' }}>
                  <div>
                    <span className="muted">Cảnh báo mở: </span>
                    <strong style={{ color: gh.open_alerts > 0 ? 'var(--danger)' : 'var(--success)' }}>
                      {gh.open_alerts}
                    </strong>
                  </div>
                  <div>
                    <span className="muted">Số vùng: </span>
                    <strong>{gh.zones.length}</strong>
                  </div>
                </div>

                <Link
                  to={`/greenhouses/${gh.id}`}
                  style={{
                    color: 'var(--primary)',
                    fontWeight: 600,
                    textDecoration: 'none',
                    fontSize: '0.84rem',
                  }}
                >
                  Vào nhà kính →
                </Link>
              </div>

              {top1 && (
                <div
                  style={{
                    background: '#f0fdf4',
                    border: '1px solid #bbf7d0',
                    borderRadius: 'var(--radius)',
                    padding: '0.55rem 0.75rem',
                    marginBottom: '0.9rem',
                    fontSize: '0.82rem',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: '0.5rem',
                    flexWrap: 'wrap',
                  }}
                >
                  <span>
                    🏆 Gợi ý phù hợp nhất (ước tính):{' '}
                    <strong>{formatCropName(top1.crop_code, top1.crop_name)}</strong>
                  </span>
                  <span className="badge ok">
                    {Math.round(top1.relative_yield * 100)}% (~{top1.expected_kg_m2.toFixed(1)} kg/m²)
                  </span>
                </div>
              )}

              <div>
                <h4
                  style={{
                    fontSize: '0.8rem',
                    margin: '0 0 0.5rem',
                    color: 'var(--muted)',
                    textTransform: 'uppercase',
                  }}
                >
                  Các vùng trồng (Zones)
                </h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {gh.zones.map((z) => {
                    const profile = z.crop_profile_id ? profilesById.get(z.crop_profile_id) : undefined
                    const activeCycle = activeCycleByZone.get(z.id)
                    const cropLabel = activeCycle
                      ? formatCropName(activeCycle.crop_code, activeCycle.crop_name)
                      : profile
                        ? formatCropName(profile.crop_code, profile.crop_name)
                        : 'Chưa gắn cây'

                    return (
                      <Link
                        key={z.id}
                        to={`/zones/${z.id}`}
                        className="zone-list-item"
                      >
                        <div>
                          <div style={{ fontWeight: 600 }}>
                            🌱 {z.name || `Zone ${z.zone_index}`}
                          </div>
                          <div className="muted" style={{ fontSize: '0.78rem', marginTop: '0.15rem' }}>
                            Cây: <strong>{cropLabel}</strong>
                            {z.area_m2 ? ` • ${z.area_m2} m²` : ''}
                          </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          {activeCycle ? (
                            <span className="badge ok">
                              Đang trồng – Ngày thứ {cycleDayNumber(activeCycle.started_at)}
                            </span>
                          ) : (
                            <span className="badge muted">Chưa có vụ</span>
                          )}
                          <span style={{ color: 'var(--primary)', fontWeight: 600, fontSize: '0.85rem' }}>
                            Chi tiết →
                          </span>
                        </div>
                      </Link>
                    )
                  })}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {showCreateModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card">
            <div className="card-header">
              <h3>➕ Tạo nhà kính mới</h3>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setShowCreateModal(false)}
              >
                ✕
              </button>
            </div>

            {createError && (
              <div className="alert-banner bad" style={{ marginBottom: '0.85rem' }}>
                {createError}
              </div>
            )}

            <form onSubmit={handleCreateSubmit}>
              <div className="form-group">
                <label htmlFor="gh-name">Tên nhà kính *</label>
                <input
                  id="gh-name"
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="VD: Nhà kính Đà Lạt 01"
                  required
                />
              </div>

              <div className="form-group">
                <label htmlFor="gh-location">Vị trí / Khu vực</label>
                <input
                  id="gh-location"
                  type="text"
                  value={newLocation}
                  onChange={(e) => setNewLocation(e.target.value)}
                  placeholder="VD: Khu A – Lâm Đồng"
                />
              </div>

              <p className="muted" style={{ fontSize: '0.8rem', marginTop: 0 }}>
                Hệ thống sẽ tự tạo sẵn 2 Zone mặc định (Zone 1 – Cà chua bi, Zone 2 – Dâu tây). Sau đó bạn vào trang Thiết bị để cấp phát Gateway.
              </p>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowCreateModal(false)}
                >
                  Huỷ
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={createGhMutation.isPending}
                >
                  {createGhMutation.isPending ? 'Đang tạo...' : 'Tạo nhà kính'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
