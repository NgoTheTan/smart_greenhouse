import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import {
  ALERT_TYPE_LABELS,
  formatDateTimeVi,
  type AlertItem,
  type Greenhouse,
} from '../lib/types'

type FilterState = 'open' | 'raised' | 'notified' | 'acknowledged' | 'resolved' | 'all'

const STATE_TABS: Array<{ key: FilterState; label: string }> = [
  { key: 'open', label: 'Đang mở' },
  { key: 'raised', label: 'Mới phát sinh' },
  { key: 'notified', label: 'Đã thông báo' },
  { key: 'acknowledged', label: 'Đã xác nhận' },
  { key: 'resolved', label: 'Đã giải quyết' },
  { key: 'all', label: 'Tất cả' },
]

const STATE_LABELS: Record<string, { label: string; cls: string }> = {
  raised: { label: 'Mới phát sinh', cls: 'bad' },
  notified: { label: 'Đã thông báo', cls: 'warning' },
  acknowledged: { label: 'Đã xác nhận', cls: 'info' },
  resolved: { label: 'Đã giải quyết', cls: 'ok' },
}

export default function AlertsPage() {
  const { canOperate } = useAuth()
  const queryClient = useQueryClient()
  const [stateFilter, setStateFilter] = useState<FilterState>('open')
  const [ghFilter, setGhFilter] = useState<string>('all')
  const [ackError, setAckError] = useState<string | null>(null)

  const greenhousesQuery = useQuery({
    queryKey: ['greenhouses'],
    queryFn: () => api<Greenhouse[]>('/greenhouses'),
  })

  const alertsQuery = useQuery({
    queryKey: ['alerts', stateFilter, ghFilter],
    queryFn: () => {
      const params = new URLSearchParams()
      if (stateFilter !== 'all') params.set('state', stateFilter)
      if (ghFilter !== 'all') params.set('greenhouse_id', ghFilter)
      const qs = params.toString()
      return api<AlertItem[]>(`/alerts${qs ? `?${qs}` : ''}`)
    },
  })

  const ackMutation = useMutation({
    mutationFn: (alertId: string) =>
      api<AlertItem>(`/alerts/${alertId}/ack`, { method: 'POST' }),
    onSuccess: () => {
      setAckError(null)
      void queryClient.invalidateQueries({ queryKey: ['alerts'] })
      void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
    },
    onError: (err) => {
      setAckError(formatApiError(err))
    },
  })

  const greenhouses = greenhousesQuery.data ?? []
  const ghById = new Map(greenhouses.map((g) => [g.id, g]))
  const zoneById = new Map(greenhouses.flatMap((g) => g.zones).map((z) => [z.id, z]))
  const alerts = alertsQuery.data ?? []

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>🔔 Trung tâm Cảnh báo</h2>
          <p className="muted" style={{ margin: 0 }}>
            Theo dõi sự cố vi khí hậu, thiết bị và xác nhận tiếp nhận (Ack) để ngừng leo thang
          </p>
        </div>

        <div style={{ minWidth: 220 }}>
          <select
            aria-label="Lọc theo nhà kính"
            value={ghFilter}
            onChange={(e) => setGhFilter(e.target.value)}
          >
            <option value="all">Tất cả nhà kính</option>
            {greenhouses.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name || g.id} {g.is_simulated ? '(Mô phỏng)' : ''}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="tab-strip" style={{ marginBottom: '1rem' }}>
        {STATE_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`btn btn-sm ${stateFilter === t.key ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setStateFilter(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {ackError && (
        <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
          {ackError}
        </div>
      )}

      {alertsQuery.isError && (
        <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
          Không tải được danh sách cảnh báo: {formatApiError(alertsQuery.error)}
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <h3>Danh sách cảnh báo</h3>
          <span className="badge info">{alerts.length} bản ghi</span>
        </div>

        {alertsQuery.isLoading ? (
          <p className="muted">Đang tải cảnh báo...</p>
        ) : alerts.length === 0 ? (
          <p className="muted" style={{ textAlign: 'center', padding: '1.5rem 0', margin: 0 }}>
            Không có cảnh báo nào khớp bộ lọc hiện tại.
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {alerts.map((alt) => {
              const gh = ghById.get(alt.greenhouse_id)
              const zone = alt.zone_id ? zoneById.get(alt.zone_id) : undefined
              const payload = alt.payload ?? {}
              const title =
                typeof payload.title === 'string' && payload.title
                  ? payload.title
                  : ALERT_TYPE_LABELS[alt.alert_type] ?? alt.alert_type
              const body = typeof payload.body === 'string' ? payload.body : ''
              const stMeta = STATE_LABELS[alt.state] ?? { label: alt.state, cls: 'muted' }
              const sevCls =
                alt.severity === 'critical'
                  ? 'bad'
                  : alt.severity === 'warning'
                    ? 'warning'
                    : 'info'
              const canAck =
                canOperate && (alt.state === 'raised' || alt.state === 'notified')

              return (
                <div
                  key={alt.id}
                  style={{
                    border: `1px solid ${
                      alt.severity === 'critical'
                        ? '#fecaca'
                        : alt.severity === 'warning'
                          ? '#fed7aa'
                          : '#bfdbfe'
                    }`,
                    background:
                      alt.state === 'resolved'
                        ? '#f8fafc'
                        : alt.severity === 'critical'
                          ? '#fef2f2'
                          : alt.severity === 'warning'
                            ? '#fffbeb'
                            : '#eff6ff',
                    borderRadius: 'var(--radius)',
                    padding: '1rem',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    flexWrap: 'wrap',
                    gap: '1rem',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 260 }}>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                        flexWrap: 'wrap',
                        marginBottom: '0.35rem',
                      }}
                    >
                      <span className={`badge ${sevCls}`}>{alt.severity.toUpperCase()}</span>
                      <span className={`badge ${stMeta.cls}`}>{stMeta.label}</span>
                      <strong style={{ fontSize: '0.95rem' }}>{title}</strong>
                      <span className="muted" style={{ fontSize: '0.78rem' }}>
                        ({ALERT_TYPE_LABELS[alt.alert_type] ?? alt.alert_type})
                      </span>
                    </div>

                    {body && <p style={{ margin: '0.25rem 0', fontSize: '0.88rem' }}>{body}</p>}

                    <div
                      className="muted"
                      style={{
                        fontSize: '0.78rem',
                        display: 'flex',
                        gap: '0.85rem',
                        flexWrap: 'wrap',
                        marginTop: '0.35rem',
                      }}
                    >
                      <span>🏠 {gh?.name || alt.greenhouse_id}</span>
                      {gh?.is_simulated && <span className="badge info">Mô phỏng</span>}
                      {zone && (
                        <Link to={`/zones/${zone.id}`} style={{ color: 'var(--primary)' }}>
                          🌱 {zone.name || `Zone ${zone.zone_index}`}
                        </Link>
                      )}
                      <span>🕒 Phát sinh: {formatDateTimeVi(alt.created_at)}</span>
                      {alt.escalated_at && (
                        <span style={{ color: 'var(--danger)', fontWeight: 600 }}>
                          ⚠ Đã leo thang Email lúc: {formatDateTimeVi(alt.escalated_at)}
                        </span>
                      )}
                      {alt.acknowledged_at && (
                        <span>✓ Đã xác nhận lúc: {formatDateTimeVi(alt.acknowledged_at)}</span>
                      )}
                      {alt.resolved_at && (
                        <span>✔ Đã giải quyết lúc: {formatDateTimeVi(alt.resolved_at)}</span>
                      )}
                    </div>
                  </div>

                  {canAck && (
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      disabled={ackMutation.isPending}
                      onClick={() => ackMutation.mutate(alt.id)}
                    >
                      ✓ Xác nhận (Ack)
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
