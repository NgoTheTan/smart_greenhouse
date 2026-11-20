import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import {
  formatCropName,
  formatDateTimeVi,
  type CropRecommendationDetails,
  type Greenhouse,
  type MlModelItem,
  type PredictionItem,
} from '../lib/types'

export default function RecommendationsPage() {
  const { id: routeGhId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [selectedGhId, setSelectedGhId] = useState<string>(routeGhId || '')
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null)
  const prevPredIdRef = useRef<string | null>(null)

  const greenhousesQuery = useQuery({
    queryKey: ['greenhouses'],
    queryFn: () => api<Greenhouse[]>('/greenhouses'),
  })

  const activeModelQuery = useQuery({
    queryKey: ['models', 'active'],
    queryFn: () => api<MlModelItem | null>('/models/active'),
  })

  const greenhouses = greenhousesQuery.data ?? []

  useEffect(() => {
    if (routeGhId) {
      setSelectedGhId(routeGhId)
    } else if (!selectedGhId && greenhouses.length > 0) {
      setSelectedGhId(greenhouses[0].id)
    }
  }, [routeGhId, greenhouses, selectedGhId])

  const currentGh = greenhouses.find((g) => g.id === selectedGhId)

  const recQuery = useQuery({
    queryKey: ['recommendations', selectedGhId],
    queryFn: () =>
      api<PredictionItem<CropRecommendationDetails> | null>(
        `/greenhouses/${selectedGhId}/recommendations`,
      ),
    enabled: Boolean(selectedGhId),
  })

  const rec = recQuery.data ?? null

  useEffect(() => {
    if (refreshing && rec && rec.id !== prevPredIdRef.current) {
      setRefreshing(false)
      setRefreshMsg('Đã cập nhật gợi ý mới nhất từ khí hậu nhà kính.')
    }
  }, [rec, refreshing])

  const refreshMutation = useMutation({
    mutationFn: (ghId: string) =>
      api<{ status: string; greenhouse_id: string }>(`/greenhouses/${ghId}/recommendations/refresh`, {
        method: 'POST',
      }),
    onMutate: () => {
      prevPredIdRef.current = rec?.id ?? null
      setRefreshing(true)
      setRefreshMsg(null)
    },
    onSuccess: (_res, ghId) => {
      window.setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ['recommendations', ghId] })
      }, 1500)
      window.setTimeout(() => {
        setRefreshing(false)
      }, 15000)
    },
    onError: (err) => {
      setRefreshing(false)
      setRefreshMsg(formatApiError(err))
    },
  })

  const details = rec?.details
  const features = details?.features ?? {}
  const climate = details?.climate_summary ?? {}
  const ranking = details?.ranking ?? []
  const top3 = ranking.slice(0, 3)

  const windowH = details?.window_h
  const windowLabel =
    windowH === undefined
      ? '—'
      : windowH >= 24
        ? `${Math.round(windowH / 24)} ngày gần nhất`
        : `${windowH} giờ gần nhất`

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Gợi ý cây trồng theo khí hậu nhà kính</h2>
          <p className="muted" style={{ margin: 0 }}>
            Xếp hạng 5 loại cây trồng theo năng suất dự kiến dựa trên điều kiện vi khí hậu thực tế của nhà kính
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <select
            aria-label="Chọn nhà kính"
            style={{ width: 'auto', minWidth: 230 }}
            value={selectedGhId}
            onChange={(e) => {
              const nextId = e.target.value
              setSelectedGhId(nextId)
              navigate(`/greenhouses/${nextId}/recommendations`)
            }}
          >
            {greenhouses.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name || g.id} {g.is_simulated ? '(Mô phỏng)' : ''}
              </option>
            ))}
          </select>

          {selectedGhId && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={refreshing || refreshMutation.isPending || !activeModelQuery.data}
              onClick={() => refreshMutation.mutate(selectedGhId)}
            >
              {refreshing ? 'Đang tính lại...' : 'Làm mới gợi ý'}
            </button>
          )}
        </div>
      </div>

      <div className="alert-banner info" style={{ marginBottom: '1rem' }}>
        <strong>Lưu ý quan trọng:</strong> Kết quả gợi ý là <strong>ước tính</strong> từ mô hình LightGBM toàn cục, chỉ dựa trên lịch sử khí hậu nhà kính và <strong>giả định tưới đủ</strong>. Tính năng này <strong>không</strong> gửi bất kỳ lệnh điều khiển nào xuống thiết bị.
      </div>

      {refreshMsg && (
        <div className="alert-banner ok" style={{ marginBottom: '1rem' }}>
          {refreshMsg}
        </div>
      )}

      {currentGh && (
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <span className={`badge ${currentGh.online ? 'ok' : 'bad'}`}>
            {currentGh.online ? '● Online' : '○ Offline'}
          </span>
          {currentGh.is_simulated && <span className="badge info">Nhà kính Mô phỏng</span>}
          {details?.low_confidence && (
            <span
              className="badge warning"
              title="Cửa sổ ngắn (< 24h), độ phủ dữ liệu chưa cao hoặc khí hậu ngoài vùng dữ liệu huấn luyện"
            >
              Độ tin cậy thấp
            </span>
          )}
          <Link to="/models" className="btn btn-sm btn-secondary">
            Xem thông số mô hình AI
          </Link>
        </div>
      )}

      {!activeModelQuery.isLoading && !activeModelQuery.data ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <h3>Chưa có mô hình</h3>
          <p className="muted">
            Hệ thống chưa kích hoạt mô hình dự đoán năng suất (<code>task = &apos;yield&apos;</code>). Hãy chạy{' '}
            <code>python -m ml.train --task yield</code> trên máy chủ để huấn luyện và kích hoạt mô hình.
          </p>
        </div>
      ) : recQuery.isLoading ? (
        <div className="card muted">Đang tải gợi ý cây trồng...</div>
      ) : recQuery.isError ? (
        <div className="alert-banner bad">{formatApiError(recQuery.error)}</div>
      ) : !rec || ranking.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <h3>Chưa đủ dữ liệu khí hậu để gợi ý</h3>
          <p className="muted">
            Nhà kính cần tích luỹ đủ độ phủ dữ liệu cảm biến trong cửa sổ đánh giá trước khi worker sinh bảng xếp hạng.
          </p>
        </div>
      ) : (
        <>
          {/* Tóm tắt khí hậu cửa sổ gần nhất */}
          <div className="card">
            <div className="card-header">
              <div>
                <h3>Tóm tắt khí hậu cửa sổ gần nhất</h3>
                <span className="muted" style={{ fontSize: '0.8rem' }}>
                  Cửa sổ: <strong>{windowLabel}</strong> • Độ phủ dữ liệu:{' '}
                  <strong>
                    {details?.coverage !== undefined ? `${Math.round(details.coverage * 100)}%` : '—'}
                  </strong>{' '}
                  • Cập nhật: {formatDateTimeVi(rec.ts)}
                </span>
              </div>
              {details?.low_confidence && (
                <span className="badge warning">
                  Độ tin cậy thấp
                  {details.ood_features && details.ood_features.length > 0
                    ? ` (ngoài dải: ${details.ood_features.join(', ')})`
                    : ''}
                </span>
              )}
            </div>

            <div className="grid grid-cols-4">
              <div className="metric-tile">
                <span className="label">Nhiệt độ TB</span>
                <span className="value">
                  {typeof climate.t_mean === 'number' ? climate.t_mean.toFixed(1) : '—'}
                  <span className="unit">°C</span>
                </span>
                <span className="subtext muted">
                  Ngày: {typeof climate.t_day_mean === 'number' ? climate.t_day_mean.toFixed(1) : '—'}°C · Đêm:{' '}
                  {typeof climate.t_night_mean === 'number' ? climate.t_night_mean.toFixed(1) : '—'}°C
                </span>
              </div>

              <div className="metric-tile">
                <span className="label">Ẩm độ &amp; VPD TB</span>
                <span className="value">
                  {typeof climate.vpd_mean === 'number' ? climate.vpd_mean.toFixed(2) : '—'}
                  <span className="unit">kPa</span>
                </span>
                <span className="subtext muted">
                  RH TB: {typeof climate.rh_mean === 'number' ? climate.rh_mean.toFixed(1) : '—'}%
                </span>
              </div>

              <div className="metric-tile">
                <span className="label">Ánh sáng (DLI TB)</span>
                <span className="value" style={{ fontSize: typeof climate.dli_mean === 'number' ? '1.75rem' : '1.05rem' }}>
                  {typeof climate.dli_mean === 'number'
                    ? `${climate.dli_mean.toFixed(1)}`
                    : 'Không có dữ liệu ánh sáng'}
                  {typeof climate.dli_mean === 'number' && <span className="unit">mol/m²/ngày</span>}
                </span>
              </div>

              <div className="metric-tile">
                <span className="label">Thời gian nóng &gt; 30 °C</span>
                <span className="value">
                  {typeof features.frac_t_gt_30 === 'number'
                    ? Math.round(features.frac_t_gt_30 * 100)
                    : '—'}
                  <span className="unit">%</span>
                </span>
                <span className="subtext muted">Tỉ lệ mẫu vượt 30 °C trong cửa sổ</span>
              </div>
            </div>
          </div>

          {/* 3 thẻ Top cây */}
          <h3 style={{ marginBottom: '0.75rem' }}>Top 3 cây trồng phù hợp nhất</h3>
          <div className="grid grid-cols-3" style={{ marginBottom: '1.25rem' }}>
            {top3.map((cand, index) => (
              <div
                key={cand.crop_code}
                className="card"
                style={{
                  marginBottom: 0,
                  borderColor: index === 0 ? 'var(--primary)' : 'var(--border)',
                  background: index === 0 ? '#f0fdf4' : 'var(--surface)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <span className={`badge ${index === 0 ? 'ok' : 'info'}`}>Hạng #{index + 1}</span>
                  <strong style={{ color: 'var(--primary)', fontSize: '1.1rem' }}>
                    {Math.round(cand.relative_yield * 100)}%
                  </strong>
                </div>
                <h3 style={{ margin: '0 0 0.35rem' }}>
                  {formatCropName(cand.crop_code, cand.crop_name)}
                </h3>
                <div style={{ fontSize: '0.92rem', marginBottom: '0.65rem' }}>
                  Năng suất ước tính: <strong>{cand.expected_kg_m2.toFixed(1)} kg/m²</strong>{' '}
                  <span className="muted">
                    ({cand.interval[0].toFixed(1)}–{cand.interval[1].toFixed(1)})
                  </span>
                </div>
                <ul style={{ margin: 0, paddingLeft: '1.15rem', fontSize: '0.8rem', color: 'var(--muted)' }}>
                  {cand.reasons.slice(0, 3).map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          {/* Bảng tất cả ứng viên */}
          <div className="card">
            <div className="card-header">
              <h3>Xếp hạng toàn bộ cây ứng viên</h3>
            </div>
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Hạng</th>
                    <th>Loại cây</th>
                    <th>Năng suất tương đối</th>
                    <th>Năng suất ước tính</th>
                    <th>Khoảng tin cậy</th>
                    <th>Lý do đánh giá</th>
                  </tr>
                </thead>
                <tbody>
                  {ranking.map((cand, idx) => (
                    <tr key={cand.crop_code}>
                      <td>
                        <strong>#{idx + 1}</strong>
                      </td>
                      <td>
                        <strong>{formatCropName(cand.crop_code, cand.crop_name)}</strong>
                      </td>
                      <td>
                        <span className={`badge ${cand.relative_yield >= 0.8 ? 'ok' : cand.relative_yield >= 0.6 ? 'warning' : 'bad'}`}>
                          {Math.round(cand.relative_yield * 100)}%
                        </span>
                      </td>
                      <td>
                        <strong>{cand.expected_kg_m2.toFixed(1)} kg/m²</strong>
                      </td>
                      <td className="muted">
                        {cand.interval[0].toFixed(1)} – {cand.interval[1].toFixed(1)} kg/m²
                      </td>
                      <td>
                        <ul style={{ margin: 0, paddingLeft: '1rem', fontSize: '0.8rem' }}>
                          {cand.reasons.slice(0, 3).map((r, i) => (
                            <li key={i}>{r}</li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
