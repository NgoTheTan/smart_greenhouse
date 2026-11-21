import { useState, type FormEvent } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Button, Card, Field, SelectField, StatusDot } from '../components/ui'
import {
  formatCropName,
  type CropCycle,
  type CropProfile,
  type CropRecommendationDetails,
  type Greenhouse,
  type PredictionItem,
  type ReadingPoint,
  type Zone,
} from '../lib/types'

// ─── helpers ────────────────────────────────────────────────────────────────

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
  return { val: String(Math.round(v)), unit: 'lux' }
}

// ─── ZoneCard ────────────────────────────────────────────────────────────────

interface ZoneCardProps {
  zone: Greenhouse['zones'][number]
  activeCycle: CropCycle | undefined
  profile: CropProfile | undefined
  reading: ReadingPoint | null
  isOwner?: boolean
  onDelete?: (zoneId: string, zoneName: string) => void
}

function ZoneCard({ zone, activeCycle, profile, reading, isOwner, onDelete }: ZoneCardProps) {
  const navigate = useNavigate()
  const cropLabel = activeCycle
    ? formatCropName(activeCycle.crop_code, activeCycle.crop_name)
    : profile
      ? formatCropName(profile.crop_code, profile.crop_name)
      : 'Chưa gắn cây'

  const t = fmtTemp(reading?.air_temp)
  const rh = fmtRh(reading?.air_rh)
  const sm = fmtSoil(reading?.soil_moisture)
  const lx = fmtLux(reading?.lux)

  const isSensorFault = reading?.quality && reading.quality !== 'ok'

  return (
    <Card
      onClick={() => navigate(`/zones/${zone.id}`)}
      style={{
        padding: '1.25rem',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        cursor: 'pointer',
        transition: 'background-color 0.1s ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = '#FAFAF8'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = '#FFFFFF'
      }}
    >
      <div>
        {/* Header zone card: Tên zone, diện tích, ngày thứ & trạng thái cảm biến */}
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: '0.75rem',
            paddingBottom: '1rem',
            borderBottom: '1px solid var(--border-row, #EEECE5)',
          }}
        >
          <div>
            <h4
              style={{
                margin: '0 0 0.25rem 0',
                fontSize: '1rem',
                fontWeight: 700,
                color: 'var(--text-main, #1C211E)',
              }}
            >
              {zone.name || `Khu ${zone.zone_index}`}
            </h4>
            <div style={{ fontSize: '0.82rem', color: 'var(--text-muted, #626861)' }}>
              {cropLabel} · {zone.area_m2 ? `${zone.area_m2} m²` : '—'}
            </div>
          </div>

          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-main, #1C211E)', marginBottom: '0.2rem' }}>
              {activeCycle ? `Ngày thứ ${cycleDayNumber(activeCycle.started_at)}` : 'Chưa có vụ'}
            </div>
            <StatusDot
              status={isSensorFault ? 'warning' : reading ? 'ok' : 'unallocated'}
              label={isSensorFault ? 'Lỗi cảm biến' : reading ? 'Cảm biến OK' : 'Chưa có dữ liệu'}
            />
          </div>
        </div>

        {/* Khối hiển thị 4 chỉ số cảm biến lớn */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: '1.25rem 1rem',
            padding: '1.25rem 0 0.5rem 0',
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

      {/* Nút xóa zone màu đỏ ở cuối mỗi zone */}
      {isOwner && onDelete && (
        <div
          style={{
            borderTop: '1px solid var(--border-row, #EEECE5)',
            paddingTop: '0.75rem',
            marginTop: '0.75rem',
            display: 'flex',
            justifyContent: 'flex-end',
          }}
        >
          <Button
            type="button"
            variant="danger"
            size="sm"
            style={{
              color: 'var(--status-offline, #B94A32)',
              borderColor: 'var(--status-offline, #B94A32)',
              minHeight: '32px',
              height: '32px',
              padding: '0 12px',
              fontSize: '12px',
            }}
            onClick={(e) => {
              e.stopPropagation()
              onDelete(zone.id, zone.name || `Khu ${zone.zone_index}`)
            }}
          >
            Xóa zone
          </Button>
        </div>
      )}
    </Card>
  )
}

// ─── GreenhousePage ───────────────────────────────────────────────────────────

export default function GreenhousePage() {
  const { ghId } = useParams<{ ghId: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const isOwner = user?.role === 'owner' || Boolean(user)
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null)

  // Sửa Zone states
  const [showZoneModal, setShowZoneModal] = useState(false)
  const [editZoneId, setEditZoneId] = useState('')
  const [editZoneName, setEditZoneName] = useState('')
  const [editZoneProfileId, setEditZoneProfileId] = useState('')
  const [editZoneArea, setEditZoneArea] = useState('')
  const [zoneEditMsg, setZoneEditMsg] = useState<string | null>(null)
  const [zoneEditError, setZoneEditError] = useState<string | null>(null)

  // Thêm Zone mới states (cô lập nút ngoài)
  const [showAddZoneModal, setShowAddZoneModal] = useState(false)
  const [newZoneName, setNewZoneName] = useState('')
  const [newZoneProfileId, setNewZoneProfileId] = useState('')
  const [newZoneArea, setNewZoneArea] = useState('')
  const [addZoneError, setAddZoneError] = useState<string | null>(null)

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

  const handleOpenZoneModal = () => {
    if (zones.length > 0) {
      const firstZone = zones[0]
      setEditZoneId(firstZone.id)
      setEditZoneName(firstZone.name || '')
      setEditZoneProfileId(firstZone.crop_profile_id || '')
      setEditZoneArea(firstZone.area_m2 ? String(firstZone.area_m2) : '20.0')
    }
    setZoneEditMsg(null)
    setZoneEditError(null)
    setShowZoneModal(true)
  }

  const handleSelectZoneToEdit = (targetZone: Greenhouse['zones'][number]) => {
    setEditZoneId(targetZone.id)
    setEditZoneName(targetZone.name || '')
    setEditZoneProfileId(targetZone.crop_profile_id || '')
    setEditZoneArea(targetZone.area_m2 ? String(targetZone.area_m2) : '20.0')
    setZoneEditMsg(null)
    setZoneEditError(null)
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

  const addZoneMutation = useMutation({
    mutationFn: (payload: { name: string; crop_profile_id: string | null; area_m2: number | null }) =>
      api<Zone>(`/greenhouses/${ghId}/zones`, {
        method: 'POST',
        body: JSON.stringify({
          name: payload.name,
          crop_profile_id: payload.crop_profile_id,
          area_m2: payload.area_m2,
        }),
      }),
    onSuccess: (newZone) => {
      setShowAddZoneModal(false)
      setNewZoneName('')
      setNewZoneProfileId('')
      setNewZoneArea('')
      setAddZoneError(null)
      setZoneEditMsg(`Đã thêm thành công ${newZone.name || `Zone ${newZone.zone_index}`}.`)
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
    },
    onError: (err) => {
      setAddZoneError(formatApiError(err))
    },
  })

  const handleAddZoneSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!newZoneName.trim()) return
    const parsedArea = Number(newZoneArea)
    addZoneMutation.mutate({
      name: newZoneName.trim(),
      crop_profile_id: newZoneProfileId || null,
      area_m2: parsedArea > 0 ? parsedArea : null,
    })
  }

  const deleteZoneMutation = useMutation({
    mutationFn: ({ zoneId, deleteGreenhouseIfLast }: { zoneId: string; deleteGreenhouseIfLast?: boolean }) =>
      api<{ ok: boolean; message: string; deleted_greenhouse?: boolean }>(
        `/zones/${zoneId}${deleteGreenhouseIfLast ? '?delete_greenhouse_if_last=true' : ''}`,
        {
          method: 'DELETE',
        },
      ),
    onSuccess: (res) => {
      setZoneEditError(null)
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
      if (res.deleted_greenhouse) {
        setShowZoneModal(false)
        navigate('/')
      } else {
        setZoneEditMsg(res.message || 'Đã xóa vùng trồng thành công.')
      }
    },
    onError: (err) => {
      setZoneEditError(formatApiError(err))
    },
  })

  const handleDeleteZone = (zoneId: string, zoneName: string) => {
    if (zones.length <= 1) {
      const confirmedLast = window.confirm(
        `CẢNH BÁO: Đây là vùng trồng cuối cùng của nhà kính "${gh?.name || ''}".\n\nNếu bạn xóa vùng trồng này, TOÀN BỘ NHÀ KÍNH và các dữ liệu liên quan sẽ bị xóa vĩnh viễn!\n\nBạn có chắc chắn muốn xóa cả vùng trồng và nhà kính này không?`
      )
      if (confirmedLast) {
        deleteZoneMutation.mutate({ zoneId, deleteGreenhouseIfLast: true })
      }
      return
    }

    const confirmed = window.confirm(
      `Bạn có chắc chắn muốn xóa "${zoneName}" không? Các thiết bị và dữ liệu cảm biến liên quan sẽ được gỡ bỏ.`
    )
    if (confirmed) {
      deleteZoneMutation.mutate({ zoneId, deleteGreenhouseIfLast: false })
    }
  }

  if (ghQuery.isLoading) {
    return (
      <Card>
        <p className="muted" style={{ margin: 0 }}>Đang tải thông tin nhà kính...</p>
      </Card>
    )
  }

  if (!gh) {
    return (
      <Card style={{ textAlign: 'center', padding: '3rem 1.5rem' }}>
        <h3>Không tìm thấy nhà kính</h3>
        <p className="muted">Nhà kính này có thể đã bị xóa hoặc không thuộc quyền quản lý của bạn.</p>
        <Link to="/" className="btn btn-primary" style={{ marginTop: '1rem' }}>
          ← Quay lại Tổng quan
        </Link>
      </Card>
    )
  }

  const recData = recQuery.data
  const ranking = recData?.details?.ranking ?? []

  return (
    <div>
      {/* Nút quay lại & Breadcrumb */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.75rem',
          marginBottom: '1rem',
          flexWrap: 'wrap',
        }}
      >
        <Link
          to="/"
          className="btn btn-secondary btn-sm"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            textDecoration: 'none',
            fontSize: '13px',
            fontWeight: 500,
            padding: '0 14px',
            height: '36px',
            minHeight: '36px',
          }}
        >
          <span>←</span>
          <span>Quay lại</span>
        </Link>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted, #626861)' }}>
          <Link to="/" style={{ color: 'var(--text-muted, #626861)', textDecoration: 'none' }}>
            Tổng quan
          </Link>
          <span style={{ margin: '0 0.35rem' }}>/</span>
          <span style={{ color: 'var(--text-main, #1C211E)', fontWeight: 500 }}>{gh.name || 'Nhà kính'}</span>
        </div>
      </div>

      {/* Header trang Chi tiết nhà kính chuẩn theo ảnh */}
      <div style={{ marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.25rem' }}>
          <h2 style={{ fontSize: '1.75rem', fontWeight: 700, margin: 0, color: 'var(--text-main, #1C211E)' }}>
            {gh.name || 'Nhà kính'}
          </h2>
          <StatusDot
            status={gh.online ? 'ok' : 'offline'}
            label={gh.online ? 'Gateway online' : 'Gateway offline'}
          />
        </div>
        <p style={{ margin: 0, fontSize: '0.88rem', color: 'var(--text-muted, #626861)' }}>
          {gh.location || 'Chưa cập nhật vị trí'}
        </p>
      </div>

      {/* Hàng thông số tổng hợp (Meta stats row chuẩn theo ảnh) */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '2.5rem',
          padding: '1.1rem 0',
          borderTop: '1px solid var(--border-row, #EEECE5)',
          borderBottom: '1px solid var(--border-row, #EEECE5)',
          marginBottom: '2rem',
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted, #626861)', marginBottom: '0.2rem' }}>
            Trạng thái gateway
          </div>
          <div style={{ fontSize: '0.92rem', fontWeight: 600, color: 'var(--text-main, #1C211E)' }}>
            {gh.online ? 'Đang hoạt động' : 'Mất kết nối'}
          </div>
        </div>

        <div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted, #626861)', marginBottom: '0.2rem' }}>
            Vùng trồng
          </div>
          <div style={{ fontSize: '0.92rem', fontWeight: 600, color: 'var(--text-main, #1C211E)' }}>
            {zones.length} zone
          </div>
        </div>

        <div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted, #626861)', marginBottom: '0.2rem' }}>
            Cảnh báo đang mở
          </div>
          <div style={{ fontSize: '0.92rem', fontWeight: 600, color: 'var(--text-main, #1C211E)' }}>
            {gh.open_alerts}
          </div>
        </div>
      </div>

      {/* Tiêu đề mục Vùng trồng & Các nút Thêm zone, Sửa zone cô lập */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '1rem',
          flexWrap: 'wrap',
          gap: '0.75rem',
        }}
      >
        <div>
          <h3 style={{ margin: '0 0 0.2rem 0', fontSize: '1.15rem', fontWeight: 700, color: 'var(--text-main, #1C211E)' }}>
            Vùng trồng
          </h3>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted, #626861)' }}>
            Chọn một zone để điều khiển thiết bị và xem chi tiết.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.65rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {isOwner && (
            <Button
              variant="primary"
              onClick={() => {
                setNewZoneName('')
                setNewZoneProfileId(profilesQuery.data?.[0]?.id || '')
                setNewZoneArea('20.0')
                setAddZoneError(null)
                setShowAddZoneModal(true)
              }}
            >
              + Thêm zone
            </Button>
          )}

          {isOwner && (
            <Button variant="secondary" onClick={handleOpenZoneModal}>
              Sửa zone
            </Button>
          )}
        </div>
      </div>

      {zoneEditMsg && (
        <div className="alert-banner ok" style={{ marginBottom: '1rem' }}>
          {zoneEditMsg}
        </div>
      )}

      {/* Grid danh sách các Zone */}
      <div className="grid grid-cols-2" style={{ marginBottom: '2rem' }}>
        {zones.map((zone, idx) => {
          const activeCycle = cycleQueries[idx]?.data?.[0]
          const profile = zone.crop_profile_id
            ? profilesById.get(zone.crop_profile_id)
            : undefined
          const reading = readingQueries[idx]?.data ?? null

          return (
            <ZoneCard
              key={zone.id}
              zone={zone}
              activeCycle={activeCycle}
              profile={profile}
              reading={reading}
              isOwner={isOwner}
              onDelete={handleDeleteZone}
            />
          )
        })}
      </div>

      {/* Khối Gợi ý cây trồng theo vi khí hậu chuẩn theo ảnh */}
      <Card style={{ padding: '1.25rem', marginBottom: '2rem' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: '1rem',
            paddingBottom: '1rem',
            borderBottom: '1px solid var(--border-row, #EEECE5)',
            flexWrap: 'wrap',
          }}
        >
          <div>
            <h4 style={{ margin: '0 0 0.25rem 0', fontSize: '1rem', fontWeight: 700, color: 'var(--text-main, #1C211E)' }}>
              Gợi ý cây trồng theo vi khí hậu
            </h4>
            <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted, #626861)' }}>
              Mô hình AI dự đoán loại cây cho năng suất cao nhất dựa trên lịch sử nhiệt độ, độ ẩm và ánh sáng của nhà kính này.
            </p>
          </div>

          <Button
            variant="secondary"
            disabled={refreshing}
            onClick={() => ghId && refreshMutation.mutate(ghId)}
          >
            {refreshing ? 'Đang phân tích...' : 'Làm mới gợi ý'}
          </Button>
        </div>

        <div style={{ paddingTop: '1rem' }}>
          {refreshMsg && (
            <div className="alert-banner ok" style={{ marginBottom: '1rem' }}>
              {refreshMsg}
            </div>
          )}

          {ranking.length === 0 ? (
            <p className="muted" style={{ margin: 0, fontSize: '0.88rem' }}>
              Chưa đủ dữ liệu vi khí hậu trong cửa sổ đánh giá để xếp hạng. Hãy để cảm biến hoạt động thêm thời gian.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {ranking.map((cand, idx) => (
                <div
                  key={cand.crop_code}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '0.75rem 1rem',
                    borderRadius: 'var(--radius-input, 6px)',
                    border: '1px solid var(--border-row, #EEECE5)',
                    background: idx === 0 ? 'var(--item-selected, #E8F0EA)' : '#FFFFFF',
                  }}
                >
                  <div>
                    <strong style={{ fontSize: '0.92rem', color: 'var(--text-main)' }}>
                      #{idx + 1} {cand.crop_name || cand.crop_code}
                    </strong>
                    <div className="muted" style={{ fontSize: '0.78rem', marginTop: '2px' }}>
                      Năng suất kỳ vọng: {cand.expected_kg_m2.toFixed(1)} kg/m²
                    </div>
                  </div>

                  <span className="badge ok" style={{ fontSize: '0.8rem', fontWeight: 600 }}>
                    {Math.round(cand.relative_yield * 100)}% tối ưu
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      {/* Modal Quản lý & Sửa Zone */}
      {showZoneModal && (
        <div className="modal-backdrop" onClick={() => setShowZoneModal(false)}>
          <div className="modal-card" style={{ maxWidth: '560px' }} onClick={(e) => e.stopPropagation()}>
            <div className="card-header">
              <h3 style={{ margin: 0 }}>Sửa thông tin vùng trồng (Zone)</h3>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setShowZoneModal(false)}
                style={{ padding: '0.1rem 0.5rem' }}
              >
                ✕
              </button>
            </div>

            {zoneEditError && (
              <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
                {zoneEditError}
              </div>
            )}
            {zoneEditMsg && (
              <div className="alert-banner ok" style={{ marginBottom: '1rem' }}>
                {zoneEditMsg}
              </div>
            )}

            {/* Danh sách các zone để chọn sửa */}
            <div style={{ marginBottom: '1.25rem' }}>
              <label style={{ display: 'block', fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
                Chọn Zone cần sửa thông tin:
              </label>
              <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                {zones.map((z) => (
                  <button
                    key={z.id}
                    type="button"
                    onClick={() => handleSelectZoneToEdit(z)}
                    className={`btn btn-sm ${editZoneId === z.id ? 'btn-primary' : 'btn-secondary'}`}
                  >
                    {z.name || `Khu ${z.zone_index}`}
                  </button>
                ))}
              </div>
            </div>

            {/* Form chỉnh sửa zone đang chọn */}
            {editZoneId && (
              <form onSubmit={handleZoneEditSubmit}>
                <Field
                  label="Tên vùng trồng"
                  type="text"
                  value={editZoneName}
                  onChange={(e) => setEditZoneName(e.target.value)}
                  placeholder="Ví dụ: Khu 1 - Cà chua bi"
                  required
                />

                <SelectField
                  label="Hồ sơ cây trồng mặc định"
                  value={editZoneProfileId}
                  onChange={(e) => setEditZoneProfileId(e.target.value)}
                >
                  <option value="">Chưa gắn cây</option>
                  {(profilesQuery.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.crop_name}
                    </option>
                  ))}
                </SelectField>

                <Field
                  label="Diện tích canh tác"
                  type="number"
                  step="0.1"
                  min="0.1"
                  value={editZoneArea}
                  onChange={(e) => setEditZoneArea(e.target.value)}
                  unit="m²"
                  required
                />

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1.5rem' }}>
                  <Button type="button" variant="secondary" onClick={() => setShowZoneModal(false)}>
                    Đóng
                  </Button>
                  <Button type="submit" variant="primary" disabled={updateZoneMutation.isPending}>
                    {updateZoneMutation.isPending ? 'Đang lưu...' : 'Lưu thay đổi'}
                  </Button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* Modal Thêm Zone mới riêng biệt */}
      {showAddZoneModal && (
        <div className="modal-backdrop" onClick={() => setShowAddZoneModal(false)}>
          <div className="modal-card" style={{ maxWidth: '480px' }} onClick={(e) => e.stopPropagation()}>
            <div className="card-header">
              <h3 style={{ margin: 0 }}>Thêm vùng trồng (Zone) mới</h3>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setShowAddZoneModal(false)}
                style={{ padding: '0.1rem 0.5rem' }}
              >
                ✕
              </button>
            </div>

            {addZoneError && (
              <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
                {addZoneError}
              </div>
            )}

            <form onSubmit={handleAddZoneSubmit}>
              <Field
                label="Tên vùng trồng mới *"
                type="text"
                value={newZoneName}
                onChange={(e) => setNewZoneName(e.target.value)}
                placeholder="Ví dụ: Khu 3 - Xà lách"
                required
              />

              <SelectField
                label="Hồ sơ cây trồng mặc định"
                value={newZoneProfileId}
                onChange={(e) => setNewZoneProfileId(e.target.value)}
              >
                <option value="">Chưa gắn cây</option>
                {(profilesQuery.data ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.crop_name}
                  </option>
                ))}
              </SelectField>

              <Field
                label="Diện tích canh tác"
                type="number"
                step="0.1"
                min="0.1"
                value={newZoneArea}
                onChange={(e) => setNewZoneArea(e.target.value)}
                unit="m²"
                placeholder="20.0"
              />

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1.25rem' }}>
                <Button type="button" variant="secondary" onClick={() => setShowAddZoneModal(false)}>
                  Hủy
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={addZoneMutation.isPending || !newZoneName.trim()}
                >
                  {addZoneMutation.isPending ? 'Đang thêm...' : 'Xác nhận thêm'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
