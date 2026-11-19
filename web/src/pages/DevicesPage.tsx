import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  formatDateTimeVi,
  type ConfigSyncResponse,
  type DeviceNode,
  type GatewayProvisionResponse,
  type GatewayStatus,
  type Greenhouse,
} from '../lib/types'

export default function DevicesPage() {
  const { isOwner } = useAuth()
  const queryClient = useQueryClient()

  const greenhousesQuery = useQuery({
    queryKey: ['greenhouses'],
    queryFn: () => api<Greenhouse[]>('/greenhouses'),
  })

  const nodesQuery = useQuery({
    queryKey: ['nodes'],
    queryFn: () => api<DeviceNode[]>('/nodes'),
  })

  const greenhouses = Array.isArray(greenhousesQuery.data) ? greenhousesQuery.data : []
  const allZones = greenhouses.flatMap((gh) =>
    Array.isArray(gh.zones)
      ? gh.zones.map((z) => ({
          ...z,
          greenhouseName: gh.name || gh.id,
        }))
      : [],
  )
  const zoneById = new Map(allZones.map((z) => [z.id, z]))
  const ghById = new Map(greenhouses.map((g) => [g.id, g]))

  const gwsWithId = greenhouses.filter((g) => Boolean(g.gateway_id))

  const gwStatusQueries = useQueries({
    queries: gwsWithId.map((gh) => ({
      queryKey: ['gateway-status', gh.gateway_id],
      queryFn: () => api<GatewayStatus>(`/gateways/${gh.gateway_id}/status`),
      enabled: Boolean(gh.gateway_id),
    })),
  })

  const cfgSyncQueries = useQueries({
    queries: greenhouses.map((gh) => ({
      queryKey: ['config-sync', gh.id],
      queryFn: () => api<ConfigSyncResponse>(`/greenhouses/${gh.id}/config-sync`),
      enabled: greenhouses.length > 0,
    })),
  })

  const statusByGh = new Map<string, GatewayStatus>()
  gwsWithId.forEach((gh, idx) => {
    const data = gwStatusQueries[idx]?.data
    if (data) statusByGh.set(gh.id, data)
  })

  const syncByGh = new Map<string, ConfigSyncResponse>()
  greenhouses.forEach((gh, idx) => {
    const data = cfgSyncQueries[idx]?.data
    if (data) syncByGh.set(gh.id, data)
  })

  // Provision Gateway Modal
  const [provisionGhId, setProvisionGhId] = useState<string>('')
  const [provisionSimulated, setProvisionSimulated] = useState(false)
  const [showProvisionModal, setShowProvisionModal] = useState(false)
  const [provisionCred, setProvisionCred] = useState<GatewayProvisionResponse | null>(null)
  const [provisionError, setProvisionError] = useState<string | null>(null)
  const [copiedField, setCopiedField] = useState<string | null>(null)

  const provisionMutation = useMutation({
    mutationFn: (payload: { greenhouse_id: string; is_simulated: boolean }) =>
      api<GatewayProvisionResponse>('/gateways', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    onSuccess: (res) => {
      setProvisionCred(res)
      setProvisionError(null)
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
      void queryClient.invalidateQueries({ queryKey: ['gateway-status'] })
    },
    onError: (err) => {
      setProvisionError(formatApiError(err))
    },
  })

  const handleCopy = async (label: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopiedField(label)
      window.setTimeout(() => setCopiedField(null), 2000)
    } catch {
      // ignore clipboard errors
    }
  }

  // Pair Node (discovered + manual MAC)
  const [pairZoneByMac, setPairZoneByMac] = useState<Record<string, string>>({})
  const [manualMac, setManualMac] = useState('')
  const [manualZoneId, setManualZoneId] = useState('')
  const [pairMsg, setPairMsg] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    if (!manualZoneId && allZones.length > 0) {
      setManualZoneId(allZones[0].id)
    }
  }, [allZones, manualZoneId])

  const pairMutation = useMutation({
    mutationFn: ({ mac, zoneId }: { mac: string; zoneId: string }) =>
      api<DeviceNode>(`/nodes/${encodeURIComponent(mac)}/pair`, {
        method: 'POST',
        body: JSON.stringify({ zone_id: zoneId }),
      }),
    onSuccess: (node) => {
      setPairMsg({
        ok: true,
        text: `Đã ghép node ${node.mac_address} vào Zone. Phiên bản cấu hình cfg đã tăng để đồng bộ xuống Gateway.`,
      })
      setManualMac('')
      void queryClient.invalidateQueries({ queryKey: ['nodes'] })
      void queryClient.invalidateQueries({ queryKey: ['config-sync'] })
      void queryClient.invalidateQueries({ queryKey: ['gateway-status'] })
    },
    onError: (err) => {
      setPairMsg({ ok: false, text: formatApiError(err) })
    },
  })

  // Calibration
  const [calZoneId, setCalZoneId] = useState('')
  const [soilDry, setSoilDry] = useState(2900)
  const [soilWet, setSoilWet] = useState(1300)
  const [calMsg, setCalMsg] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    if (!calZoneId && allZones.length > 0) {
      setCalZoneId(allZones[0].id)
      setSoilDry(allZones[0].soil_dry_raw ?? 2900)
      setSoilWet(allZones[0].soil_wet_raw ?? 1300)
    }
  }, [allZones, calZoneId])

  const handleSelectCalZone = (zid: string) => {
    setCalZoneId(zid)
    const z = zoneById.get(zid)
    if (z) {
      setSoilDry(z.soil_dry_raw ?? 2900)
      setSoilWet(z.soil_wet_raw ?? 1300)
    }
  }

  const calMutation = useMutation({
    mutationFn: (payload: { zoneId: string; soil_dry_raw: number; soil_wet_raw: number }) =>
      api<{ zone_id: string; cfg_version_desired: number }>(
        `/zones/${payload.zoneId}/calibration`,
        {
          method: 'PUT',
          body: JSON.stringify({
            soil_dry_raw: payload.soil_dry_raw,
            soil_wet_raw: payload.soil_wet_raw,
          }),
        },
      ),
    onSuccess: (res) => {
      setCalMsg({
        ok: true,
        text: `Đã lưu hiệu chuẩn ẩm đất! cfg_version_desired mới = v${res.cfg_version_desired}.`,
      })
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
      void queryClient.invalidateQueries({ queryKey: ['config-sync'] })
      void queryClient.invalidateQueries({ queryKey: ['gateway-status'] })
    },
    onError: (err) => {
      setCalMsg({ ok: false, text: formatApiError(err) })
    },
  })

  const handleSaveCalibration = (e: FormEvent) => {
    e.preventDefault()
    if (!calZoneId) return
    setCalMsg(null)
    calMutation.mutate({
      zoneId: calZoneId,
      soil_dry_raw: soilDry,
      soil_wet_raw: soilWet,
    })
  }

  const nodes = Array.isArray(nodesQuery.data) ? nodesQuery.data : []
  const discoveredNodes = nodes.filter((n) => n.status === 'discovered')
  const pairedNodes = nodes.filter((n) => n.status === 'paired')

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>📡 Quản lý Thiết bị, Ghép Node &amp; Hiệu chuẩn</h2>
          <p className="muted" style={{ margin: 0 }}>
            Theo dõi Gateway ESP32, đồng bộ cấu hình <code>cfg_version</code>, ghép nối Node ESP-NOW và hiệu chuẩn ẩm đất 2 điểm
          </p>
        </div>

        {isOwner && greenhouses.some((g) => !g.gateway_id) && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              const unprov = greenhouses.find((g) => !g.gateway_id)
              setProvisionGhId(unprov?.id || '')
              setProvisionCred(null)
              setProvisionError(null)
              setShowProvisionModal(true)
            }}
          >
            + Cấp phát Gateway mới
          </button>
        )}
      </div>

      {/* Gateway Table */}
      <div className="card">
        <div className="card-header">
          <h3>🚪 Danh sách Gateway theo Nhà kính</h3>
          <span className="badge info">{greenhouses.length} nhà kính</span>
        </div>

        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Nhà kính</th>
                <th>Trạng thái</th>
                <th>MQTT Username</th>
                <th>RSSI</th>
                <th>Firmware</th>
                <th>Đồng bộ <code>cfg</code></th>
                <th>Thấy lần cuối</th>
                {isOwner && <th>Thao tác</th>}
              </tr>
            </thead>
            <tbody>
              {greenhouses.map((gh) => {
                const st = statusByGh.get(gh.id)
                const sync = syncByGh.get(gh.id)
                const synced = sync?.synced ?? false
                const desiredV = sync?.cfg_version_desired ?? st?.cfg_version_desired ?? 0
                const reportedV = sync?.cfg_version_reported ?? st?.cfg_version_reported ?? 0

                return (
                  <tr key={gh.id}>
                    <td>
                      <strong>{gh.name || gh.id}</strong>{' '}
                      {gh.is_simulated && <span className="badge info">Mô phỏng</span>}
                    </td>
                    <td>
                      {!gh.gateway_id ? (
                        <span className="badge muted">Chưa cấp phát</span>
                      ) : (
                        <span className={`badge ${gh.online ? 'ok' : 'bad'}`}>
                          {gh.online ? '● Online' : '○ Offline'}
                        </span>
                      )}
                    </td>
                    <td>
                      {st?.mqtt_username ? <code>{st.mqtt_username}</code> : '—'}
                    </td>
                    <td>{st?.rssi !== null && st?.rssi !== undefined ? `${st.rssi} dBm` : '—'}</td>
                    <td>{st?.fw_version || '—'}</td>
                    <td>
                      {gh.gateway_id ? (
                        <span className={`badge ${synced ? 'ok' : 'warning'}`}>
                          v{reportedV} / v{desiredV} {synced ? '(Đã đồng bộ)' : '(Đang chờ)'}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="muted">{formatDateTimeVi(st?.last_seen)}</td>
                    {isOwner && (
                      <td>
                        {!gh.gateway_id ? (
                          <button
                            type="button"
                            className="btn btn-sm btn-primary"
                            onClick={() => {
                              setProvisionGhId(gh.id)
                              setProvisionCred(null)
                              setProvisionError(null)
                              setShowProvisionModal(true)
                            }}
                          >
                            Cấp phát Gateway
                          </button>
                        ) : (
                          <span className="muted" style={{ fontSize: '0.78rem' }}>
                            Đã cấp phát
                          </span>
                        )}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Node Discovery & Manual Pairing */}
      {pairMsg && (
        <div
          className={`alert-banner ${pairMsg.ok ? 'ok' : 'bad'}`}
          style={{ marginBottom: '1rem' }}
        >
          {pairMsg.text}
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <div>
            <h3>🔍 Phát hiện Node lạ (<code>status = discovered</code>)</h3>
            <span className="muted" style={{ fontSize: '0.8rem' }}>
              Node bật nguồn gửi bản tin HELLO qua ESP-NOW sẽ xuất hiện tự động tại đây
            </span>
          </div>
          <span className="badge warning">{discoveredNodes.length} chờ ghép</span>
        </div>

        {discoveredNodes.length === 0 ? (
          <p className="muted" style={{ margin: '0 0 1rem' }}>
            Hiện chưa có node mới nào đang chờ ghép nối.
          </p>
        ) : (
          <div className="table-container" style={{ marginBottom: '1.25rem' }}>
            <table>
              <thead>
                <tr>
                  <th>Địa chỉ MAC</th>
                  <th>RSSI</th>
                  <th>Firmware</th>
                  <th>Thấy lần đầu</th>
                  {isOwner && <th>Chọn Zone &amp; Ghép</th>}
                </tr>
              </thead>
              <tbody>
                {discoveredNodes.map((n) => {
                  const chosenZone = pairZoneByMac[n.mac_address] || allZones[0]?.id || ''
                  return (
                    <tr key={n.id}>
                      <td>
                        <code>{n.mac_address}</code>
                      </td>
                      <td>{n.rssi !== null ? `${n.rssi} dBm` : '—'}</td>
                      <td>{n.firmware_version || '—'}</td>
                      <td className="muted">{formatDateTimeVi(n.first_seen)}</td>
                      {isOwner && (
                        <td>
                          <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                            <select
                              style={{ minWidth: 200 }}
                              value={chosenZone}
                              onChange={(e) =>
                                setPairZoneByMac((prev) => ({
                                  ...prev,
                                  [n.mac_address]: e.target.value,
                                }))
                              }
                            >
                              {allZones.map((z) => (
                                <option key={z.id} value={z.id}>
                                  {z.greenhouseName} – {z.name || `Zone ${z.zone_index}`}
                                </option>
                              ))}
                            </select>
                            <button
                              type="button"
                              className="btn btn-sm btn-primary"
                              disabled={!chosenZone || pairMutation.isPending}
                              onClick={() =>
                                pairMutation.mutate({ mac: n.mac_address, zoneId: chosenZone })
                              }
                            >
                              Ghép vào Zone
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {isOwner && (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (!manualMac.trim() || !manualZoneId) return
              setPairMsg(null)
              pairMutation.mutate({ mac: manualMac.trim(), zoneId: manualZoneId })
            }}
            style={{
              background: '#f8fafc',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '0.9rem',
            }}
          >
            <h4 style={{ margin: '0 0 0.6rem', fontSize: '0.9rem' }}>
              ⌨️ Fallback: Nhập MAC thủ công để ghép Node
            </h4>
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 200 }}>
                <label htmlFor="manual-mac">Địa chỉ MAC</label>
                <input
                  id="manual-mac"
                  type="text"
                  value={manualMac}
                  onChange={(e) => setManualMac(e.target.value)}
                  placeholder="AA:BB:CC:DD:EE:01"
                  required
                />
              </div>
              <div style={{ flex: 1, minWidth: 220 }}>
                <label htmlFor="manual-zone">Ghép vào Zone</label>
                <select
                  id="manual-zone"
                  value={manualZoneId}
                  onChange={(e) => setManualZoneId(e.target.value)}
                  required
                >
                  {allZones.map((z) => (
                    <option key={z.id} value={z.id}>
                      {z.greenhouseName} – {z.name || `Zone ${z.zone_index}`}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={pairMutation.isPending}
              >
                {pairMutation.isPending ? 'Đang ghép...' : 'Ghép node'}
              </button>
            </div>
          </form>
        )}
      </div>

      {/* Paired Nodes */}
      <div className="card">
        <div className="card-header">
          <h3>🌱 Node cảm biến đã ghép (<code>status = paired</code>)</h3>
          <span className="badge ok">{pairedNodes.length} node</span>
        </div>

        {nodesQuery.isLoading ? (
          <p className="muted">Đang tải danh sách node...</p>
        ) : pairedNodes.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>
            Chưa có node nào được ghép nối.
          </p>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Địa chỉ MAC</th>
                  <th>Nhà kính / Zone</th>
                  <th>Sóng RSSI</th>
                  <th>Pin (mV)</th>
                  <th>Firmware</th>
                  <th>Thấy lần cuối</th>
                </tr>
              </thead>
              <tbody>
                {pairedNodes.map((n) => {
                  const z = n.zone_id ? zoneById.get(n.zone_id) : undefined
                  const gh = n.greenhouse_id ? ghById.get(n.greenhouse_id) : undefined
                  return (
                    <tr key={n.id}>
                      <td>
                        <code>{n.mac_address}</code>
                      </td>
                      <td>
                        {gh ? `${gh.name || gh.id} – ` : ''}
                        <span className="badge info">
                          {z ? z.name || `Zone ${z.zone_index}` : 'Chưa gán Zone'}
                        </span>
                      </td>
                      <td>{n.rssi !== null ? `${n.rssi} dBm` : '—'}</td>
                      <td>{n.battery_mv ? `${n.battery_mv} mV` : 'USB 5V'}</td>
                      <td>{n.firmware_version || '—'}</td>
                      <td className="muted">{formatDateTimeVi(n.last_seen)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 2-point Soil Calibration */}
      <div className="card">
        <div className="card-header">
          <h3>⚖️ Hiệu chuẩn Cảm biến Độ ẩm đất 2 điểm</h3>
        </div>
        <p className="muted" style={{ fontSize: '0.85rem', marginTop: 0 }}>
          Cảm biến điện dung đo giá trị ADC 12-bit (100–4090). Nhập giá trị đọc được khi để khô ngoài không khí (Dry RAW) và khi nhúng đất ẩm bão hoà (Wet RAW).
        </p>

        {calMsg && (
          <div
            className={`alert-banner ${calMsg.ok ? 'ok' : 'bad'}`}
            style={{ marginBottom: '1rem' }}
          >
            {calMsg.text}
          </div>
        )}

        <form
          onSubmit={handleSaveCalibration}
          style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', flexWrap: 'wrap' }}
        >
          <div style={{ flex: 1, minWidth: 220 }}>
            <label htmlFor="cal-zone">Chọn Zone</label>
            <select
              id="cal-zone"
              value={calZoneId}
              onChange={(e) => handleSelectCalZone(e.target.value)}
            >
              {allZones.map((z) => (
                <option key={z.id} value={z.id}>
                  {z.greenhouseName} – {z.name || `Zone ${z.zone_index}`}
                </option>
              ))}
            </select>
          </div>
          <div style={{ flex: 1, minWidth: 160 }}>
            <label htmlFor="cal-dry">ADC Điểm Khô (Dry RAW)</label>
            <input
              id="cal-dry"
              type="number"
              min={100}
              max={4090}
              value={soilDry}
              onChange={(e) => setSoilDry(Number(e.target.value))}
              disabled={!isOwner}
              required
            />
          </div>
          <div style={{ flex: 1, minWidth: 160 }}>
            <label htmlFor="cal-wet">ADC Điểm Ướt (Wet RAW)</label>
            <input
              id="cal-wet"
              type="number"
              min={50}
              max={4000}
              value={soilWet}
              onChange={(e) => setSoilWet(Number(e.target.value))}
              disabled={!isOwner}
              required
            />
          </div>
          {isOwner && (
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!calZoneId || calMutation.isPending}
            >
              {calMutation.isPending ? 'Đang lưu...' : '💾 Lưu & Đồng bộ CFG'}
            </button>
          )}
        </form>
      </div>

      {/* Provision Gateway Modal */}
      {showProvisionModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card" style={{ maxWidth: 560 }}>
            <div className="card-header">
              <h3>🔑 Cấp phát Gateway &amp; Tài khoản MQTT TLS</h3>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setShowProvisionModal(false)}
              >
                ✕
              </button>
            </div>

            {provisionError && (
              <div className="alert-banner bad" style={{ marginBottom: '0.9rem' }}>
                {provisionError}
              </div>
            )}

            {!provisionCred ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!provisionGhId) return
                  provisionMutation.mutate({
                    greenhouse_id: provisionGhId,
                    is_simulated: provisionSimulated,
                  })
                }}
              >
                <div className="form-group">
                  <label htmlFor="prov-gh">Nhà kính cần cấp phát</label>
                  <select
                    id="prov-gh"
                    value={provisionGhId}
                    onChange={(e) => setProvisionGhId(e.target.value)}
                    required
                  >
                    {greenhouses
                      .filter((g) => !g.gateway_id)
                      .map((g) => (
                        <option key={g.id} value={g.id}>
                          {g.name || g.id}
                        </option>
                      ))}
                  </select>
                </div>

                <label className="checkbox-card" style={{ marginBottom: '1rem' }}>
                  <input
                    type="checkbox"
                    checked={provisionSimulated}
                    onChange={(e) => setProvisionSimulated(e.target.checked)}
                  />
                  <span>Đánh dấu đây là Gateway giả lập (<code>is_simulated = true</code>)</span>
                </label>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setShowProvisionModal(false)}
                  >
                    Huỷ
                  </button>
                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={provisionMutation.isPending}
                  >
                    {provisionMutation.isPending ? 'Đang cấp phát...' : 'Cấp phát ngay'}
                  </button>
                </div>
              </form>
            ) : (
              <div>
                <div className="alert-banner warning" style={{ marginBottom: '1rem' }}>
                  <strong>Quan trọng:</strong> <code>mqtt_password</code> chỉ hiển thị{' '}
                  <strong>DUY NHẤT 1 LẦN</strong>! Hãy sao chép và nạp ngay vào Captive Portal của ESP32 Gateway.
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem', fontSize: '0.85rem' }}>
                  {(
                    [
                      ['MQTT Host', provisionCred.host],
                      ['MQTT Port (TLS)', String(provisionCred.port)],
                      ['MQTT Username', provisionCred.mqtt_username],
                      ['MQTT Password', provisionCred.mqtt_password],
                      ['Farm ID', provisionCred.farm_id],
                      ['Greenhouse ID', provisionCred.greenhouse_id],
                    ] as Array<[string, string]>
                  ).map(([label, val]) => (
                    <div
                      key={label}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        background: '#f8fafc',
                        border: '1px solid var(--border)',
                        borderRadius: '8px',
                        padding: '0.45rem 0.7rem',
                        gap: '0.5rem',
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div className="muted" style={{ fontSize: '0.72rem' }}>
                          {label}
                        </div>
                        <code style={{ wordBreak: 'break-all' }}>{val}</code>
                      </div>
                      <button
                        type="button"
                        className="btn btn-sm btn-secondary"
                        onClick={() => void handleCopy(label, val)}
                      >
                        {copiedField === label ? '✓ Đã chép' : 'Copy'}
                      </button>
                    </div>
                  ))}
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => setShowProvisionModal(false)}
                  >
                    Đã lưu xong, đóng
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
