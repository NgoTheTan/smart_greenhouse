import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Button, Card, Field } from '../components/ui'
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

  const displayProfiles = useMemo(() => {
    const hasNonDemo = profiles.some((p) => p.variety !== 'demo')
    if (hasNonDemo) {
      return profiles.filter((p) => p.variety !== 'demo')
    }
    return profiles
  }, [profiles])

  useEffect(() => {
    if (!selectedId && displayProfiles.length > 0) {
      setSelectedId(displayProfiles[0].id)
    }
  }, [displayProfiles, selectedId])

  useEffect(() => {
    if (!assignZoneId && allZones.length > 0) {
      setAssignZoneId(allZones[0].id)
    }
  }, [allZones, assignZoneId])

  const selectedProfile = profiles.find((p) => p.id === selectedId) ?? null

  const handleResetForm = () => {
    if (selectedProfile) {
      setCropName(selectedProfile.crop_name)
      setVariety(selectedProfile.variety || 'real')
      setParams(structuredClone(selectedProfile.parameters_json))
      setSaveMsg(null)
    }
  }

  useEffect(() => {
    if (selectedProfile) {
      setCropName(selectedProfile.crop_name)
      setVariety(selectedProfile.variety || 'real')
      setParams(structuredClone(selectedProfile.parameters_json))
      setSaveMsg(null)
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
        text: `Đã lưu hồ sơ "${updated.crop_name}" thành công! Phiên bản cấu hình đã được đồng bộ xuống Gateway.`,
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
        text: `Đã gán hồ sơ cho ${z.name || `Zone ${z.zone_index}`} và đồng bộ cấu hình xuống Gateway.`,
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
      {/* Header trang Hồ sơ cây trồng chuẩn theo ảnh thiết kế */}
      <div className="page-header">
        <div>
          <h2>Hồ sơ cây trồng</h2>
          <p className="muted">Template hệ thống và ngưỡng sinh học cho từng zone.</p>
        </div>
      </div>

      {profilesQuery.isError && (
        <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
          {formatApiError(profilesQuery.error)}
        </div>
      )}

      {/* Bố cục 2 cột chuẩn theo ảnh thiết kế */}
      <div className="crop-profile-layout">
        {/* Cột trái: Danh sách hồ sơ */}
        <Card style={{ padding: '1rem' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '0.75rem',
              paddingBottom: '0.5rem',
              borderBottom: '1px solid var(--border-row, #EEECE5)',
            }}
          >
            <h3 style={{ margin: 0, fontSize: '0.92rem', fontWeight: 600, color: 'var(--text-main, #1C211E)' }}>
              Danh sách hồ sơ
            </h3>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted, #626861)' }}>
              {displayProfiles.length} hồ sơ
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
            {displayProfiles.map((p) => {
              const active = p.id === selectedId
              return (
                <div
                  key={p.id}
                  onClick={() => {
                    setSelectedId(p.id)
                    setSaveMsg(null)
                  }}
                  style={{
                    padding: '8px 12px',
                    borderRadius: 'var(--radius-input, 6px)',
                    cursor: 'pointer',
                    fontSize: '0.88rem',
                    fontWeight: active ? 600 : 400,
                    backgroundColor: active ? 'var(--item-selected, #E8F0EA)' : 'transparent',
                    color: active ? 'var(--accent, #1E6B47)' : 'var(--text-main, #1C211E)',
                    transition: 'background-color 0.15s ease',
                  }}
                >
                  {p.crop_name}
                </div>
              )
            })}
          </div>
        </Card>

        {/* Cột phải: Chi tiết hồ sơ và các thông số sinh học */}
        {selectedProfile && params && (
          <Card style={{ padding: '1.5rem' }}>
            {/* Header chi tiết cây & Gán cho Zone */}
            <div
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                justifyContent: 'space-between',
                gap: '1.5rem',
                paddingBottom: '1.25rem',
                borderBottom: '1px solid var(--border-row, #EEECE5)',
                flexWrap: 'wrap',
              }}
            >
              <div>
                <h3
                  style={{
                    margin: '0 0 0.25rem 0',
                    fontSize: '1.4rem',
                    fontWeight: 700,
                    color: 'var(--text-main, #1C211E)',
                  }}
                >
                  {selectedProfile.crop_name}
                </h3>
                <div style={{ fontSize: '0.84rem', color: 'var(--text-muted, #626861)' }}>
                  <span className="font-mono">{selectedProfile.crop_code}</span> · Template hệ thống
                </div>
              </div>

              {allZones.length > 0 && (
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted, #626861)', marginBottom: '0.35rem' }}>
                    Gán hồ sơ cho zone
                  </div>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <select
                      value={assignZoneId}
                      onChange={(e) => setAssignZoneId(e.target.value)}
                      style={{ minHeight: '36px', height: '36px', minWidth: '240px', fontSize: '0.82rem' }}
                    >
                      {allZones.map((z) => (
                        <option key={z.id} value={z.id}>
                          {z.greenhouseName} – {z.name || `Zone ${z.zone_index}`}
                        </option>
                      ))}
                    </select>
                    {isOwner && (
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        disabled={assignMutation.isPending}
                        onClick={() =>
                          assignMutation.mutate({ zoneId: assignZoneId, profileId: selectedProfile.id })
                        }
                      >
                        Gán cho zone này
                      </Button>
                    )}
                  </div>
                  <div style={{ fontSize: '0.76rem', color: 'var(--text-muted, #626861)', marginTop: '0.35rem' }}>
                    Nếu zone đang có vụ active, hồ sơ của zone được cố định theo vụ.
                  </div>
                </div>
              )}
            </div>

            {assignMsg && (
              <div
                className={`alert-banner ${assignMsg.ok ? 'ok' : 'bad'}`}
                style={{ marginTop: '1rem', marginBottom: '1rem' }}
              >
                {assignMsg.text}
              </div>
            )}
            {saveMsg && (
              <div
                className={`alert-banner ${saveMsg.ok ? 'ok' : 'bad'}`}
                style={{ marginTop: '1rem', marginBottom: '1rem' }}
              >
                {saveMsg.text}
              </div>
            )}

            <form onSubmit={handleSave} style={{ marginTop: '1.25rem' }}>
              {/* Mục 1: Thông tin chung */}
              <div style={{ marginBottom: '1.75rem' }}>
                <h4 style={{ margin: '0 0 0.85rem 0', fontSize: '0.96rem', fontWeight: 600 }}>
                  Thông tin chung
                </h4>
                <div className="field-grid-3">
                  <Field
                    label="Tên hiển thị tiếng Việt"
                    type="text"
                    value={cropName}
                    onChange={(e) => setCropName(e.target.value)}
                    required
                  />

                  <Field
                    label="Mã cây (crop_code)"
                    type="text"
                    value={selectedProfile.crop_code}
                    disabled
                    inputStyle={{ fontFamily: 'var(--font-mono)' }}
                  />

                  <Field
                    label="Biến thể / chế độ (variety)"
                    type="text"
                    value={variety}
                    onChange={(e) => setVariety(e.target.value)}
                  />
                </div>
              </div>

              {/* Mục 2: Vi khí hậu (VPD) */}
              <div
                style={{
                  borderTop: '1px solid var(--border-row, #EEECE5)',
                  paddingTop: '1.5rem',
                  marginBottom: '1.75rem',
                }}
              >
                <h4 style={{ margin: '0 0 0.2rem 0', fontSize: '0.96rem', fontWeight: 600 }}>
                  Vi khí hậu (VPD)
                </h4>
                <p style={{ margin: '0 0 1rem 0', fontSize: '0.82rem', color: 'var(--text-muted, #626861)' }}>
                  Dải VPD theo các ngưỡng đang cấu hình.
                </p>

                {/* Thanh phân dải màu VPD trực quan chuẩn theo ảnh */}
                <div style={{ marginBottom: '1.25rem' }}>
                  <div
                    style={{
                      height: '8px',
                      borderRadius: '4px',
                      display: 'flex',
                      overflow: 'hidden',
                      marginBottom: '6px',
                    }}
                  >
                    <div style={{ flex: '1.2', backgroundColor: '#C87A64' }} />
                    <div style={{ flex: '1', backgroundColor: '#E0CF98' }} />
                    <div style={{ flex: '1.6', backgroundColor: '#1E6B47' }} />
                    <div style={{ flex: '1', backgroundColor: '#E0CF98' }} />
                    <div style={{ flex: '1.2', backgroundColor: '#C87A64' }} />
                  </div>
                  <div
                    style={{
                      position: 'relative',
                      height: '16px',
                      fontSize: '0.74rem',
                      color: 'var(--text-muted, #626861)',
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    <span style={{ position: 'absolute', left: '20%', transform: 'translateX(-50%)' }}>0.4</span>
                    <span style={{ position: 'absolute', left: '36.5%', transform: 'translateX(-50%)' }}>0.8</span>
                    <span style={{ position: 'absolute', left: '63.5%', transform: 'translateX(-50%)' }}>1.2</span>
                    <span style={{ position: 'absolute', left: '80%', transform: 'translateX(-50%)' }}>1.6 kPa</span>
                  </div>

                  {/* Legend chú thích chuẩn theo ảnh */}
                  <div
                    style={{
                      display: 'flex',
                      gap: '1.25rem',
                      fontSize: '0.78rem',
                      color: 'var(--text-muted, #626861)',
                      marginTop: '0.5rem',
                    }}
                  >
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
                      <span style={{ width: 8, height: 8, backgroundColor: '#1E6B47', borderRadius: 1 }} />
                      <span>Tối ưu</span>
                    </div>
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
                      <span style={{ width: 8, height: 8, backgroundColor: '#E0CF98', borderRadius: 1 }} />
                      <span>Lệch ngưỡng</span>
                    </div>
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
                      <span style={{ width: 8, height: 8, backgroundColor: '#C87A64', borderRadius: 1 }} />
                      <span>Nguy hiểm</span>
                    </div>
                  </div>
                </div>

                <div className="field-grid-4" style={{ marginBottom: '0.75rem' }}>
                  <Field
                    label="VPD tối ưu – Min"
                    type="number"
                    step="0.05"
                    value={params.vpd.optimal[0]}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev
                          ? {
                              ...prev,
                              vpd: { ...prev.vpd, optimal: [v, prev.vpd.optimal[1]] },
                            }
                          : null,
                      )
                    }}
                    unit="kPa"
                    required
                  />

                  <Field
                    label="VPD tối ưu – Max"
                    type="number"
                    step="0.05"
                    value={params.vpd.optimal[1]}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev
                          ? {
                              ...prev,
                              vpd: { ...prev.vpd, optimal: [prev.vpd.optimal[0], v] },
                            }
                          : null,
                      )
                    }}
                    unit="kPa"
                    required
                  />

                  <Field
                    label="Leaf offset"
                    type="number"
                    step="0.1"
                    value={params.vpd.leaf_offset_c}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev ? { ...prev, vpd: { ...prev.vpd, leaf_offset_c: v } } : null,
                      )
                    }}
                    unit="°C"
                    required
                  />

                  <Field
                    label="VPD Low Crit"
                    type="number"
                    step="0.05"
                    value={params.vpd.low_crit}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev ? { ...prev, vpd: { ...prev.vpd, low_crit: v } } : null,
                      )
                    }}
                    unit="kPa"
                    required
                  />
                </div>

                <div className="field-grid-4">
                  <Field
                    label="VPD Low Off"
                    type="number"
                    step="0.05"
                    value={params.vpd.low_off}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev ? { ...prev, vpd: { ...prev.vpd, low_off: v } } : null,
                      )
                    }}
                    unit="kPa"
                    required
                  />

                  <Field
                    label="VPD High Crit"
                    type="number"
                    step="0.05"
                    value={params.vpd.high_crit}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev ? { ...prev, vpd: { ...prev.vpd, high_crit: v } } : null,
                      )
                    }}
                    unit="kPa"
                    required
                  />
                </div>
              </div>

              {/* Mục 3: Ẩm đất, tưới & hysteresis */}
              <div
                style={{
                  borderTop: '1px solid var(--border-row, #EEECE5)',
                  paddingTop: '1.5rem',
                  marginBottom: '1.75rem',
                }}
              >
                <h4 style={{ margin: '0 0 0.2rem 0', fontSize: '0.96rem', fontWeight: 600 }}>
                  Ẩm đất, tưới &amp; hysteresis
                </h4>
                <p style={{ margin: '0 0 1rem 0', fontSize: '0.82rem', color: 'var(--text-muted, #626861)' }}>
                  Bơm bật khi ẩm đất xuống dưới ngưỡng Min và ngắt khi đạt ngưỡng Max.
                </p>

                <div className="field-grid-4" style={{ marginBottom: '0.75rem' }}>
                  <Field
                    label="Ẩm đất Min – bật bơm"
                    type="number"
                    value={params.soil_moisture_pct.min}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev
                          ? {
                              ...prev,
                              soil_moisture_pct: { ...prev.soil_moisture_pct, min: v },
                            }
                          : null,
                      )
                    }}
                    unit="%"
                    required
                  />

                  <Field
                    label="Ẩm đất Max – ngắt bơm"
                    type="number"
                    value={params.soil_moisture_pct.max}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev
                          ? {
                              ...prev,
                              soil_moisture_pct: { ...prev.soil_moisture_pct, max: v },
                            }
                          : null,
                      )
                    }}
                    unit="%"
                    required
                  />

                  <Field
                    label="Chờ đất thấm (soil_settle_s)"
                    type="number"
                    value={params.irrigation.soil_settle_s}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev
                          ? {
                              ...prev,
                              irrigation: { ...prev.irrigation, soil_settle_s: v },
                            }
                          : null,
                      )
                    }}
                    unit="giây"
                    required
                  />

                  <Field
                    label="Tưới tối đa 1 lần"
                    type="number"
                    value={params.irrigation.max_run_s}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev
                          ? {
                              ...prev,
                              irrigation: { ...prev.irrigation, max_run_s: v },
                            }
                          : null,
                      )
                    }}
                    unit="giây"
                    required
                  />
                </div>

                <div className="field-grid-4">
                  <Field
                    label="Khoảng nghỉ tối thiểu"
                    type="number"
                    value={params.irrigation.min_gap_s}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev
                          ? {
                              ...prev,
                              irrigation: { ...prev.irrigation, min_gap_s: v },
                            }
                          : null,
                      )
                    }}
                    unit="giây"
                    required
                  />

                  <Field
                    label="Tổng tưới tối đa / giờ"
                    type="number"
                    value={params.irrigation.max_total_s_per_hour}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setParams((prev) =>
                        prev
                          ? {
                              ...prev,
                              irrigation: { ...prev.irrigation, max_total_s_per_hour: v },
                            }
                          : null,
                      )
                    }}
                    unit="giây"
                    required
                  />
                </div>
              </div>

              {/* Hàng nút bấm cuối form: Hoàn tác & Lưu thay đổi chuẩn theo ảnh */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  gap: '0.75rem',
                  borderTop: '1px solid var(--border-row, #EEECE5)',
                  paddingTop: '1.25rem',
                }}
              >
                <Button
                  type="button"
                  variant="secondary"
                  onClick={handleResetForm}
                >
                  Hoàn tác
                </Button>
                {isOwner && (
                  <Button
                    type="submit"
                    variant="primary"
                    disabled={saveMutation.isPending}
                  >
                    {saveMutation.isPending ? 'Đang lưu...' : 'Lưu thay đổi'}
                  </Button>
                )}
              </div>
            </form>
          </Card>
        )}
      </div>
    </div>
  )
}
