import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { CropParameters, CropProfile, Greenhouse, Zone } from '../lib/types'

export default function CropProfilesPage() {
  const { isOwner } = useAuth()
  const queryClient = useQueryClient()

  const profilesQuery = useQuery({
    queryKey: ['crop-profiles'],
    queryFn: () => api<CropProfile[]>('/crop-profiles'),
  })

  const greenhousesQuery = useQuery({
    queryKey: ['greenhouses'],
    queryFn: () => api<Greenhouse[]>('/greenhouses'),
  })

  const profiles = profilesQuery.data ?? []
  const greenhouses = greenhousesQuery.data ?? []
  const allZones = greenhouses.flatMap((gh) =>
    gh.zones.map((z) => ({ ...z, greenhouseName: gh.name || gh.id })),
  )

  const [selectedId, setSelectedId] = useState<string>('')
  const [cropName, setCropName] = useState('')
  const [variety, setVariety] = useState('')
  const [params, setParams] = useState<CropParameters | null>(null)
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null)

  // Gán nhanh profile cho zone
  const [assignZoneId, setAssignZoneId] = useState('')
  const [assignMsg, setAssignMsg] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    if (!selectedId && profiles.length > 0) {
      setSelectedId(profiles[0].id)
    }
  }, [profiles, selectedId])

  useEffect(() => {
    if (!assignZoneId && allZones.length > 0) {
      setAssignZoneId(allZones[0].id)
    }
  }, [allZones, assignZoneId])

  const selectedProfile = profiles.find((p) => p.id === selectedId) ?? null

  useEffect(() => {
    if (selectedProfile) {
      setCropName(selectedProfile.crop_name)
      setVariety(selectedProfile.variety || 'real')
      setParams(structuredClone(selectedProfile.parameters_json))
    }
  }, [selectedProfile])

  const saveMutation = useMutation({
    mutationFn: (payload: {
      id: string
      body: {
        crop_code: string
        crop_name: string
        variety: string
        parameters_json: CropParameters
      }
    }) =>
      api<CropProfile>(`/crop-profiles/${payload.id}`, {
        method: 'PUT',
        body: JSON.stringify(payload.body),
      }),
    onSuccess: (updated) => {
      setSelectedId(updated.id)
      setSaveMsg({
        ok: true,
        text: `Đã lưu Crop Profile "${updated.crop_name}"! Phiên bản cấu hình cfg đã được tăng và đồng bộ xuống Gateway.`,
      })
      void queryClient.invalidateQueries({ queryKey: ['crop-profiles'] })
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
      void queryClient.invalidateQueries({ queryKey: ['config-sync'] })
    },
    onError: (err) => {
      setSaveMsg({ ok: false, text: formatApiError(err) })
    },
  })

  const assignMutation = useMutation({
    mutationFn: ({ zoneId, profileId }: { zoneId: string; profileId: string }) =>
      api<Zone>(`/zones/${zoneId}`, {
        method: 'PUT',
        body: JSON.stringify({ crop_profile_id: profileId }),
      }),
    onSuccess: (z) => {
      setAssignMsg({
        ok: true,
        text: `Đã gán profile cho ${z.name || `Zone ${z.zone_index}`} và đồng bộ cấu hình xuống Gateway.`,
      })
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
      void queryClient.invalidateQueries({ queryKey: ['zone', z.id] })
    },
    onError: (err) => {
      setAssignMsg({ ok: false, text: formatApiError(err) })
    },
  })

  const handleSave = (e: FormEvent) => {
    e.preventDefault()
    if (!selectedProfile || !params) return
    setSaveMsg(null)
    saveMutation.mutate({
      id: selectedProfile.id,
      body: {
        crop_code: selectedProfile.crop_code,
        crop_name: cropName.trim() || selectedProfile.crop_name,
        variety: variety.trim() || selectedProfile.variety || 'real',
        parameters_json: { ...params, schema_version: 2 },
      },
    })
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>🌿 Hồ sơ Cây trồng (Crop Profiles)</h2>
          <p className="muted" style={{ margin: 0 }}>
            Quản lý 10 bộ template hệ thống (5 cây × <code>real</code>/<code>demo</code>) và cấu hình ngưỡng sinh học cho từng Zone
          </p>
        </div>
      </div>

      {profilesQuery.isError && (
        <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
          {formatApiError(profilesQuery.error)}
        </div>
      )}

      {/* Danh sách Profile */}
      <div className="card">
        <div className="card-header">
          <h3>📚 Danh sách Crop Profiles</h3>
          <span className="badge info">{profiles.length} hồ sơ</span>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '1rem' }}>
          {profiles.map((p) => {
            const active = p.id === selectedId
            return (
              <button
                key={p.id}
                type="button"
                className={`btn btn-sm ${active ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => {
                  setSelectedId(p.id)
                  setSaveMsg(null)
                }}
              >
                <span>{p.crop_name}</span>
                <span className="badge muted" style={{ fontSize: '0.68rem', padding: '0.05rem 0.35rem' }}>
                  {p.variety || 'real'}
                </span>
                {p.farm_id && (
                  <span className="badge info" style={{ fontSize: '0.68rem', padding: '0.05rem 0.35rem' }}>
                    Riêng
                  </span>
                )}
              </button>
            )
          })}
        </div>

        {/* Gán Profile cho Zone */}
        {selectedProfile && allZones.length > 0 && (
          <div
            style={{
              background: '#f8fafc',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '0.85rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '0.75rem',
              flexWrap: 'wrap',
            }}
          >
            <div style={{ fontSize: '0.84rem' }}>
              <strong>Gán hồ sơ đang chọn cho Zone:</strong>{' '}
              <span className="muted">
                (Lưu ý: nếu Zone đang có vụ active, crop profile của Zone được cố định theo vụ.)
              </span>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
              <select
                style={{ width: 'auto', minWidth: 220 }}
                value={assignZoneId}
                onChange={(e) => setAssignZoneId(e.target.value)}
              >
                {allZones.map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.greenhouseName} – {z.name || `Zone ${z.zone_index}`}
                  </option>
                ))}
              </select>
              {isOwner && (
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={assignMutation.isPending}
                  onClick={() =>
                    assignMutation.mutate({ zoneId: assignZoneId, profileId: selectedProfile.id })
                  }
                >
                  Gán cho Zone này
                </button>
              )}
            </div>
          </div>
        )}

        {assignMsg && (
          <div
            className={`alert-banner ${assignMsg.ok ? 'ok' : 'bad'}`}
            style={{ marginTop: '0.75rem' }}
          >
            {assignMsg.text}
          </div>
        )}
      </div>

      {/* Form chỉnh sửa schema_version = 2 */}
      {selectedProfile && params && (
        <div className="card">
          <div className="card-header">
            <div>
              <h3>
                ⚙️ Tham số chi tiết (<code>schema_version = 2</code>)
              </h3>
              <span className="muted" style={{ fontSize: '0.8rem' }}>
                Mã cây (chỉ đọc): <code>{selectedProfile.crop_code}</code> • Phân loại:{' '}
                <code>{selectedProfile.variety || 'real'}</code>
                {selectedProfile.farm_id === null &&
                  ' • Đang xem Template hệ thống (khi sửa sẽ tự tạo bản sao riêng cho Farm)'}
              </span>
            </div>
          </div>

          {saveMsg && (
            <div
              className={`alert-banner ${saveMsg.ok ? 'ok' : 'bad'}`}
              style={{ marginBottom: '1rem' }}
            >
              {saveMsg.text}
            </div>
          )}

          <form onSubmit={handleSave}>
            <div className="grid grid-cols-3" style={{ marginBottom: '1rem' }}>
              <div className="form-group">
                <label>Tên hiển thị tiếng Việt</label>
                <input
                  type="text"
                  value={cropName}
                  onChange={(e) => setCropName(e.target.value)}
                  disabled={!isOwner}
                  required
                />
              </div>
              <div className="form-group">
                <label>Mã cây (<code>crop_code</code>)</label>
                <input type="text" value={selectedProfile.crop_code} disabled />
              </div>
              <div className="form-group">
                <label>Biến thể / Chế độ (<code>variety</code>)</label>
                <input
                  type="text"
                  value={variety}
                  onChange={(e) => setVariety(e.target.value)}
                  disabled={!isOwner}
                />
              </div>
            </div>

            <div className="grid grid-cols-2" style={{ gap: '1.25rem' }}>
              {/* 1. VPD & Nhiệt độ & DLI */}
              <div className="subpanel">
                <h4>1. Vi khí hậu (VPD, Nhiệt độ, DLI)</h4>
                <div className="grid grid-cols-2">
                  <div className="form-group">
                    <label>VPD tối ưu Min (kPa)</label>
                    <input
                      type="number"
                      step="0.05"
                      value={params.vpd.optimal[0]}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          vpd: {
                            ...params.vpd,
                            optimal: [Number(e.target.value), params.vpd.optimal[1]],
                          },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>VPD tối ưu Max (kPa)</label>
                    <input
                      type="number"
                      step="0.05"
                      value={params.vpd.optimal[1]}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          vpd: {
                            ...params.vpd,
                            optimal: [params.vpd.optimal[0], Number(e.target.value)],
                          },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>VPD Low Crit (kPa)</label>
                    <input
                      type="number"
                      step="0.05"
                      value={params.vpd.low_crit}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({ ...params, vpd: { ...params.vpd, low_crit: Number(e.target.value) } })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>VPD Low Off (kPa)</label>
                    <input
                      type="number"
                      step="0.05"
                      value={params.vpd.low_off}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({ ...params, vpd: { ...params.vpd, low_off: Number(e.target.value) } })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>VPD High Crit (kPa)</label>
                    <input
                      type="number"
                      step="0.05"
                      value={params.vpd.high_crit}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({ ...params, vpd: { ...params.vpd, high_crit: Number(e.target.value) } })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Leaf Offset (°C)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={params.vpd.leaf_offset_c}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          vpd: { ...params.vpd, leaf_offset_c: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Nhiệt độ tối ưu Min (°C)</label>
                    <input
                      type="number"
                      step="0.5"
                      value={params.temp_c.optimal[0]}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          temp_c: {
                            optimal: [Number(e.target.value), params.temp_c.optimal[1]],
                          },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Nhiệt độ tối ưu Max (°C)</label>
                    <input
                      type="number"
                      step="0.5"
                      value={params.temp_c.optimal[1]}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          temp_c: {
                            optimal: [params.temp_c.optimal[0], Number(e.target.value)],
                          },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>DLI tối ưu Min (mol/m²/ngày)</label>
                    <input
                      type="number"
                      step="0.5"
                      value={params.light.dli_optimal[0]}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          light: {
                            dli_optimal: [Number(e.target.value), params.light.dli_optimal[1]],
                          },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>DLI tối ưu Max (mol/m²/ngày)</label>
                    <input
                      type="number"
                      step="0.5"
                      value={params.light.dli_optimal[1]}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          light: {
                            dli_optimal: [params.light.dli_optimal[0], Number(e.target.value)],
                          },
                        })
                      }
                    />
                  </div>
                </div>
              </div>

              {/* 2. Ẩm đất, Tưới, Quạt, Tạo ẩm */}
              <div className="subpanel">
                <h4>2. Ẩm đất, Tưới &amp; Điều khiển Hysteresis</h4>
                <div className="grid grid-cols-2">
                  <div className="form-group">
                    <label>Ẩm đất Min – Bật bơm (%)</label>
                    <input
                      type="number"
                      step="1"
                      value={params.soil_moisture_pct.min}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          soil_moisture_pct: {
                            ...params.soil_moisture_pct,
                            min: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Ẩm đất Max – Ngắt bơm (%)</label>
                    <input
                      type="number"
                      step="1"
                      value={params.soil_moisture_pct.max}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          soil_moisture_pct: {
                            ...params.soil_moisture_pct,
                            max: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Tưới tối đa 1 lần (s)</label>
                    <input
                      type="number"
                      value={params.irrigation.max_run_s}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          irrigation: { ...params.irrigation, max_run_s: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Khoảng nghỉ tối thiểu (s)</label>
                    <input
                      type="number"
                      value={params.irrigation.min_gap_s}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          irrigation: { ...params.irrigation, min_gap_s: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Tổng tưới tối đa / giờ (s)</label>
                    <input
                      type="number"
                      value={params.irrigation.max_total_s_per_hour}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          irrigation: {
                            ...params.irrigation,
                            max_total_s_per_hour: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Chờ đất thấm (<code>soil_settle_s</code>)</label>
                    <input
                      type="number"
                      value={params.irrigation.soil_settle_s}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          irrigation: {
                            ...params.irrigation,
                            soil_settle_s: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Quạt Min On (s)</label>
                    <input
                      type="number"
                      value={params.fan.min_on_s}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          fan: { ...params.fan, min_on_s: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Quạt Max On (s)</label>
                    <input
                      type="number"
                      value={params.fan.max_on_s}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          fan: { ...params.fan, max_on_s: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Tạo ẩm Max On (s)</label>
                    <input
                      type="number"
                      value={params.mist.max_on_s}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          mist: { ...params.mist, max_on_s: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Khoá tạo ẩm sau quạt (<code>lockout_s</code>)</label>
                    <input
                      type="number"
                      value={params.mist.lockout_s}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          mist: { ...params.mist, lockout_s: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                </div>
              </div>

              {/* 3. Bệnh cây, Rủi ro, Lấy mẫu & Failsafe */}
              <div className="subpanel">
                <h4>3. Rủi ro nấm bệnh, Chu kỳ đo &amp; Failsafe</h4>
                <div className="grid grid-cols-2">
                  <div className="form-group">
                    <label>Ngưỡng RH nấm bệnh (&gt; %)</label>
                    <input
                      type="number"
                      value={params.disease.rh_gt}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          disease: { ...params.disease, rh_gt: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Thời gian nấm cảnh báo (phút)</label>
                    <input
                      type="number"
                      value={params.disease.fungal_minutes_alert}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          disease: {
                            ...params.disease,
                            fungal_minutes_alert: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>VPD thấp kéo dài (phút)</label>
                    <input
                      type="number"
                      value={params.risk.vpd_low_duration_min}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          risk: { vpd_low_duration_min: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Chu kỳ gửi mẫu Node (<code>sample_interval_s</code>)</label>
                    <input
                      type="number"
                      value={params.sample_interval_s}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({ ...params, sample_interval_s: Number(e.target.value) })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Failsafe Nhiệt cao nguy hiểm (°C)</label>
                    <input
                      type="number"
                      step="0.5"
                      value={params.failsafe.temp_critical_high_c}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          failsafe: {
                            ...params.failsafe,
                            temp_critical_high_c: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Failsafe Ẩm đất cạn nguy hiểm (%)</label>
                    <input
                      type="number"
                      step="1"
                      value={params.failsafe.soil_moisture_critical_low_pct}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          failsafe: {
                            ...params.failsafe,
                            soil_moisture_critical_low_pct: Number(e.target.value),
                          },
                        })
                      }
                    />
                  </div>
                </div>
              </div>

              {/* 4. Vụ trồng, Năng suất tham chiếu & AI */}
              <div className="subpanel">
                <h4>4. Vụ trồng, Năng suất tham chiếu &amp; Tham số AI</h4>
                <div className="grid grid-cols-2">
                  <div className="form-group">
                    <label>Độ dài vụ dự kiến (<code>cycle.days</code>)</label>
                    <input
                      type="number"
                      value={params.cycle.days}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({ ...params, cycle: { days: Number(e.target.value) } })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Năng suất tham chiếu (<code>yield.reference_kg_m2</code>)</label>
                    <input
                      type="number"
                      step="0.1"
                      value={params.yield.reference_kg_m2}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          yield: { reference_kg_m2: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Cửa sổ gợi ý cây (giờ)</label>
                    <input
                      type="number"
                      value={params.ai.recommend_window_h}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          ai: { ...params.ai, recommend_window_h: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Giờ tối thiểu để dự báo vụ (<code>min_cycle_hours</code>)</label>
                    <input
                      type="number"
                      step="0.5"
                      value={params.ai.min_cycle_hours}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          ai: { ...params.ai, min_cycle_hours: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Chu kỳ suy luận AI (s)</label>
                    <input
                      type="number"
                      value={params.ai.inference_interval_s}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          ai: { ...params.ai, inference_interval_s: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                  <div className="form-group">
                    <label>Độ phủ tối thiểu (<code>min_coverage</code>)</label>
                    <input
                      type="number"
                      step="0.05"
                      min="0.1"
                      max="1"
                      value={params.ai.min_coverage}
                      disabled={!isOwner}
                      onChange={(e) =>
                        setParams({
                          ...params,
                          ai: { ...params.ai, min_coverage: Number(e.target.value) },
                        })
                      }
                    />
                  </div>
                </div>
                <p className="muted" style={{ fontSize: '0.78rem', margin: '0.25rem 0 0' }}>
                  <strong>Ghi chú năng suất tham chiếu:</strong> Giá trị này dùng để quy đổi năng suất tương đối (<code>relative_yield</code>) của mô hình AI ra kg/m² (mô hình toàn cục sử dụng giá trị tham chiếu đã lưu trong mô hình lúc huấn luyện).
                </p>
              </div>
            </div>

            {isOwner && (
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1.25rem' }}>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={saveMutation.isPending}
                >
                  {saveMutation.isPending ? 'Đang lưu & đồng bộ...' : '💾 Lưu hồ sơ & Đồng bộ CFG'}
                </button>
              </div>
            )}
          </form>
        </div>
      )}
    </div>
  )
}
