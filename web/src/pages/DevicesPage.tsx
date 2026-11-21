import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import {
  Button,
  Card,
  DataTable,
  Field,
  SelectField,
  StatusDot,
  TableCell,
  TableHead,
} from '../components/ui'
import {
  formatDateTimeVi,
  type ConfigSyncResponse,
  type DeviceNode,
  type GatewayProvisionResponse,
  type GatewayStatus,
  type Greenhouse,
} from '../lib/types'

export default function DevicesPage() {
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

  // Pair Node
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
        text: `Đã ghép node ${node.mac_address} vào Zone thành công!`,
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

  const handleManualPair = (e: FormEvent) => {
    e.preventDefault()
    if (!manualMac.trim() || !manualZoneId) return
    setPairMsg(null)
    pairMutation.mutate({ mac: manualMac.trim(), zoneId: manualZoneId })
  }

  // Calibration Modal
  const [showCalModal, setShowCalModal] = useState(false)
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
        text: `Đã lưu hiệu chuẩn ẩm đất! cfg_version mới = v${res.cfg_version_desired}.`,
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
      {/* Header trang Thiết bị chuẩn theo ảnh thiết kế */}
      <div className="page-header">
        <div>
          <h2>Thiết bị</h2>

        </div>

        <div style={{ display: 'flex', gap: '0.65rem', flexWrap: 'wrap' }}>
          <Button
            variant="secondary"
            onClick={() => setShowCalModal(true)}
          >
            Hiệu chuẩn ẩm đất
          </Button>

          <Button
            variant="primary"
            onClick={() => {
              const unprov = greenhouses.find((g) => !g.gateway_id)
              setProvisionGhId(unprov?.id || greenhouses[0]?.id || '')
              setProvisionCred(null)
              setProvisionError(null)
              setShowProvisionModal(true)
            }}
          >
            + Cấp phát gateway mới
          </Button>
        </div>
      </div>

      {pairMsg && (
        <div className={`alert-banner ${pairMsg.ok ? 'ok' : 'bad'}`} style={{ marginBottom: '1.25rem' }}>
          {pairMsg.text}
        </div>
      )}

      {/* Khối 1: Gateway theo nhà kính */}
      <Card style={{ padding: '1.25rem', marginBottom: '1.5rem' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '1rem',
          }}
        >
          <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 600, color: 'var(--text-main, #1C211E)' }}>
            Gateway theo nhà kính
          </h3>
          <span style={{ fontSize: '0.82rem', color: 'var(--text-muted, #626861)' }}>
            {greenhouses.length} nhà kính
          </span>
        </div>

        <DataTable>
          <thead>
            <tr>
              <TableHead>Nhà kính</TableHead>
              <TableHead>Trạng thái</TableHead>
              <TableHead>MQTT username</TableHead>
              <TableHead>RSSI</TableHead>
              <TableHead>Firmware</TableHead>
              <TableHead>Đồng bộ cfg</TableHead>
              <TableHead>Thấy lần cuối</TableHead>
              <TableHead>Thao tác</TableHead>
            </tr>
          </thead>
          <tbody>
            {greenhouses.map((gh) => {
              const status = statusByGh.get(gh.id)
              const sync = syncByGh.get(gh.id)
              const hasGw = Boolean(gh.gateway_id)

              return (
                <tr key={gh.id}>
                  <TableCell>
                    <strong style={{ fontWeight: 600 }}>{gh.name || gh.id}</strong>
                  </TableCell>

                  <TableCell>
                    {hasGw ? (
                      <StatusDot
                        status={status?.online ? 'ok' : 'offline'}
                        label={status?.online ? 'Online' : 'Offline'}
                      />
                    ) : (
                      <StatusDot
                        status="unallocated"
                        label="Chưa cấp phát"
                      />
                    )}
                  </TableCell>

                  <TableCell>
                    <span className="font-mono">
                      {status?.mqtt_username || (hasGw ? 'gw-esp32' : '—')}
                    </span>
                  </TableCell>

                  <TableCell>
                    <span className="font-mono">
                      {status?.rssi != null
                        ? `${status.rssi < 0 ? `- ${Math.abs(status.rssi)}` : status.rssi} dBm`
                        : '—'}
                    </span>
                  </TableCell>

                  <TableCell>
                    <span className="font-mono">{status?.fw_version || (hasGw ? '1.2.0' : '—')}</span>
                  </TableCell>

                  <TableCell>
                    {sync ? (
                      <span className="font-mono">
                        v{sync.cfg_version_reported} / v{sync.cfg_version_desired}
                        <span
                          style={{
                            marginLeft: '6px',
                            fontSize: '0.78rem',
                            color: sync.synced ? 'var(--status-ok, #2E9A62)' : 'var(--text-muted, #626861)',
                          }}
                        >
                          {sync.synced ? 'Đã đồng bộ' : 'Chờ đồng bộ'}
                        </span>
                      </span>
                    ) : (
                      '—'
                    )}
                  </TableCell>

                  <TableCell>
                    <span className="font-mono">
                      {status?.last_seen ? formatDateTimeVi(status.last_seen) : '—'}
                    </span>
                  </TableCell>

                  <TableCell>
                    {hasGw ? (
                      <span style={{ fontSize: '0.82rem', color: 'var(--text-muted, #626861)' }}>
                        Đã cấp phát
                      </span>
                    ) : (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          setProvisionGhId(gh.id)
                          setProvisionCred(null)
                          setProvisionError(null)
                          setShowProvisionModal(true)
                        }}
                      >
                        Cấp phát
                      </Button>
                    )}
                  </TableCell>
                </tr>
              )
            })}
          </tbody>
        </DataTable>
      </Card>

      {/* Khối 2: Node lạ đang chờ ghép */}
      <Card style={{ padding: '1.25rem', marginBottom: '1.5rem' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '0.35rem',
          }}
        >
          <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 600, color: 'var(--text-main, #1C211E)' }}>
            Node lạ đang chờ ghép
          </h3>
          <span style={{ fontSize: '0.82rem', color: 'var(--text-muted, #626861)' }}>
            {discoveredNodes.length} chờ ghép
          </span>
        </div>
        <p style={{ margin: '0 0 1rem 0', fontSize: '0.85rem', color: 'var(--text-muted, #626861)' }}>
          Node bật nguồn và gửi bản tin tự động hiện ở đây.
        </p>

        {discoveredNodes.length === 0 ? (
          <p className="muted" style={{ padding: '0.5rem 0 1.25rem', margin: 0, fontSize: '0.85rem' }}>
            Hiện chưa có node mới nào đang chờ ghép nối.
          </p>
        ) : (
          <div style={{ marginBottom: '1.5rem' }}>
            <DataTable>
              <thead>
                <tr>
                  <TableHead>Địa chỉ MAC</TableHead>
                  <TableHead>Pin</TableHead>
                  <TableHead>RSSI</TableHead>
                  <TableHead>Thao tác ghép</TableHead>
                </tr>
              </thead>
              <tbody>
                {discoveredNodes.map((n) => (
                  <tr key={n.mac_address}>
                    <TableCell>
                      <span className="font-mono" style={{ fontWeight: 600 }}>{n.mac_address}</span>
                    </TableCell>
                    <TableCell>
                      <span className="font-mono">{n.battery_mv ? `${n.battery_mv} mV` : '—'}</span>
                    </TableCell>
                    <TableCell>
                      <span className="font-mono">
                        {n.rssi != null
                          ? `${n.rssi < 0 ? `- ${Math.abs(n.rssi)}` : n.rssi} dBm`
                          : '—'}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={pairMutation.isPending}
                        onClick={() => {
                          if (allZones.length > 0) {
                            pairMutation.mutate({ mac: n.mac_address, zoneId: allZones[0].id })
                          }
                        }}
                      >
                        Ghép vào {allZones[0]?.name || 'Zone'}
                      </Button>
                    </TableCell>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </div>
        )}

        {/* Khối con: Ghép thủ công bằng địa chỉ MAC chuẩn theo ảnh */}
        <div
          style={{
            borderTop: '1px solid var(--border-row, #EEECE5)',
            paddingTop: '1.25rem',
          }}
        >
          <h4 style={{ margin: '0 0 0.85rem 0', fontSize: '0.92rem', fontWeight: 600 }}>
            Ghép thủ công bằng địa chỉ MAC
          </h4>

          <form
            onSubmit={handleManualPair}
            className="manual-pair-form"
          >
            <Field
              label="Địa chỉ MAC"
              type="text"
              placeholder="AA:BB:CC:DD:EE:01"
              value={manualMac}
              onChange={(e) => setManualMac(e.target.value)}
              inputStyle={{ fontFamily: 'var(--font-mono)' }}
              containerStyle={{ marginBottom: 0 }}
              required
            />

            <SelectField
              label="Ghép vào zone"
              value={manualZoneId}
              onChange={(e) => setManualZoneId(e.target.value)}
              containerStyle={{ marginBottom: 0 }}
              required
            >
              {allZones.map((z) => (
                <option key={z.id} value={z.id}>
                  {z.greenhouseName} – {z.name || `Zone ${z.zone_index}`}
                </option>
              ))}
            </SelectField>

            <Button
              type="submit"
              variant="primary"
              disabled={pairMutation.isPending || !manualMac.trim()}
              style={{ minHeight: '44px' }}
            >
              {pairMutation.isPending ? 'Đang ghép...' : 'Ghép node'}
            </Button>
          </form>
        </div>
      </Card>

      {/* Khối 3: Node cảm biến đã ghép */}
      <Card style={{ padding: '1.25rem', marginBottom: '2rem' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '1rem',
          }}
        >
          <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 600, color: 'var(--text-main, #1C211E)' }}>
            Node cảm biến đã ghép
          </h3>
          <span style={{ fontSize: '0.82rem', color: 'var(--text-muted, #626861)' }}>
            {pairedNodes.length} node
          </span>
        </div>

        {pairedNodes.length === 0 ? (
          <p className="muted" style={{ margin: 0, fontSize: '0.85rem' }}>
            Chưa có node cảm biến nào được ghép nối vào Zone.
          </p>
        ) : (
          <DataTable>
            <thead>
              <tr>
                <TableHead>Địa chỉ MAC</TableHead>
                <TableHead>Nhà kính / Zone</TableHead>
                <TableHead>Sóng RSSI</TableHead>
                <TableHead>Pin</TableHead>
                <TableHead>Firmware</TableHead>
                <TableHead>Thấy lần cuối</TableHead>
              </tr>
            </thead>
            <tbody>
              {pairedNodes.map((n) => {
                const z = n.zone_id ? zoneById.get(n.zone_id) : undefined
                const gh = z ? ghById.get(z.greenhouse_id) : undefined

                return (
                  <tr key={n.mac_address}>
                    <TableCell>
                      <span className="font-mono" style={{ fontWeight: 600 }}>{n.mac_address}</span>
                    </TableCell>

                    <TableCell>
                      <strong style={{ fontWeight: 600 }}>{z?.name || (z ? `Zone ${z.zone_index}` : '—')}</strong>
                      {gh?.name && (
                        <span style={{ color: 'var(--text-muted, #626861)', fontSize: '0.8rem', marginLeft: '6px' }}>
                          {gh.name}
                        </span>
                      )}
                    </TableCell>

                    <TableCell>
                      <span className="font-mono">
                        {n.rssi != null
                          ? `${n.rssi < 0 ? `- ${Math.abs(n.rssi)}` : n.rssi} dBm`
                          : '—'}
                      </span>
                    </TableCell>

                    <TableCell>
                      <span className="font-mono">{n.battery_mv != null ? `${n.battery_mv} mV` : '—'}</span>
                    </TableCell>

                    <TableCell>
                      <span className="font-mono">{n.firmware_version || '1.0.4'}</span>
                    </TableCell>

                    <TableCell>
                      <span className="font-mono">
                        {n.last_seen ? formatDateTimeVi(n.last_seen) : '—'}
                      </span>
                    </TableCell>
                  </tr>
                )
              })}
            </tbody>
          </DataTable>
        )}
      </Card>

      {/* Modal Cấp phát Gateway mới */}
      {showProvisionModal && (
        <div className="modal-backdrop" onClick={() => setShowProvisionModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="card-header">
              <h3 style={{ margin: 0 }}>Cấp phát Gateway mới</h3>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setShowProvisionModal(false)}
                style={{ padding: '0.1rem 0.5rem' }}
              >
                ✕
              </button>
            </div>

            {provisionError && (
              <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
                {provisionError}
              </div>
            )}

            {!provisionCred ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!provisionGhId) return
                  setProvisionError(null)
                  provisionMutation.mutate({
                    greenhouse_id: provisionGhId,
                    is_simulated: provisionSimulated,
                  })
                }}
              >
                <SelectField
                  label="Chọn nhà kính cần gắn Gateway *"
                  value={provisionGhId}
                  onChange={(e) => setProvisionGhId(e.target.value)}
                  required
                >
                  {greenhouses.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name || g.id} {g.gateway_id ? '(Đã có gateway)' : '(Chưa có)'}
                    </option>
                  ))}
                </SelectField>

                <div style={{ marginBottom: '1.25rem' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.85rem' }}>
                    <input
                      type="checkbox"
                      checked={provisionSimulated}
                      onChange={(e) => setProvisionSimulated(e.target.checked)}
                      style={{ width: 'auto', minHeight: 'auto' }}
                    />
                    <span>Chế độ mô phỏng vi khí hậu ảo</span>
                  </label>
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                  <Button type="button" variant="secondary" onClick={() => setShowProvisionModal(false)}>
                    Hủy
                  </Button>
                  <Button type="submit" variant="primary" disabled={provisionMutation.isPending || !provisionGhId}>
                    {provisionMutation.isPending ? 'Đang cấp phát...' : 'Xác nhận cấp phát'}
                  </Button>
                </div>
              </form>
            ) : (
              <div>
                <div className="alert-banner ok" style={{ marginBottom: '1rem' }}>
                  Cấp phát Gateway thành công! Lưu lại mật khẩu MQTT ngay vì hệ thống sẽ không hiển thị lại mật khẩu thô.
                </div>

                <Field
                  label="MQTT Username"
                  type="text"
                  readOnly
                  value={provisionCred.mqtt_username}
                  inputStyle={{ fontFamily: 'var(--font-mono)' }}
                />

                <Field
                  label="MQTT Password"
                  type="text"
                  readOnly
                  value={provisionCred.mqtt_password}
                  inputStyle={{ fontFamily: 'var(--font-mono)' }}
                />

                <Field
                  label="Host & Port"
                  type="text"
                  readOnly
                  value={`${provisionCred.host}:${provisionCred.port}`}
                  inputStyle={{ fontFamily: 'var(--font-mono)' }}
                />

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1.25rem' }}>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      handleCopy(
                        'credentials',
                        `MQTT_USER=${provisionCred.mqtt_username}\nMQTT_PASS=${provisionCred.mqtt_password}\nMQTT_HOST=${provisionCred.host}\nMQTT_PORT=${provisionCred.port}`
                      )
                    }
                  >
                    {copiedField === 'credentials' ? 'Đã sao chép!' : 'Sao chép thông tin'}
                  </Button>
                  <Button type="button" variant="primary" onClick={() => setShowProvisionModal(false)}>
                    Hoàn tất
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Modal Hiệu chuẩn ẩm đất */}
      {showCalModal && (
        <div className="modal-backdrop" onClick={() => setShowCalModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="card-header">
              <h3 style={{ margin: 0 }}>Hiệu chuẩn cảm biến ẩm đất 2 điểm</h3>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                onClick={() => setShowCalModal(false)}
                style={{ padding: '0.1rem 0.5rem' }}
              >
                ✕
              </button>
            </div>

            {calMsg && (
              <div className={`alert-banner ${calMsg.ok ? 'ok' : 'bad'}`} style={{ marginBottom: '1rem' }}>
                {calMsg.text}
              </div>
            )}

            <form onSubmit={handleSaveCalibration}>
              <SelectField
                label="Chọn Zone hiệu chuẩn"
                value={calZoneId}
                onChange={(e) => handleSelectCalZone(e.target.value)}
              >
                {allZones.map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.greenhouseName} – {z.name || `Zone ${z.zone_index}`}
                  </option>
                ))}
              </SelectField>

              <Field
                label="Giá trị thô khi khô (dry_raw)"
                type="number"
                min="100"
                max="4090"
                value={soilDry}
                onChange={(e) => setSoilDry(Number(e.target.value))}
                hint="Đo cảm biến ngoài không khí khô (thường khoảng 2900 - 3200)."
                required
              />

              <Field
                label="Giá trị thô khi ướt bão hòa (wet_raw)"
                type="number"
                min="50"
                max="4000"
                value={soilWet}
                onChange={(e) => setSoilWet(Number(e.target.value))}
                hint="Đo cảm biến nhúng vào cốc nước sạch (thường khoảng 1200 - 1500)."
                required
              />

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1.25rem' }}>
                <Button type="button" variant="secondary" onClick={() => setShowCalModal(false)}>
                  Đóng
                </Button>
                <Button type="submit" variant="primary" disabled={calMutation.isPending}>
                  {calMutation.isPending ? 'Đang lưu...' : 'Lưu hiệu chuẩn'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
