import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import {
  CROP_NAMES_VI,
  formatCropName,
  formatDateTimeVi,
  type MlModelItem,
} from '../lib/types'

const SOURCE_LABELS: Record<string, string> = {
  synthetic: 'Synthetic',
  sim: 'Simulator',
  real: 'Real',
  public: 'Public',
}

const SOURCE_COLORS: Record<string, string> = {
  synthetic: '#15803d',
  sim: '#0284c7',
  real: '#d97706',
  public: '#7c3aed',
}

function fmtNum(val: number | undefined | null, digits = 3): string {
  if (typeof val !== 'number' || Number.isNaN(val)) return '—'
  return val.toFixed(digits)
}

export default function ModelsPage() {
  const activeQuery = useQuery({
    queryKey: ['models', 'active'],
    queryFn: () => api<MlModelItem | null>('/models/active'),
  })

  const listQuery = useQuery({
    queryKey: ['models', 'list'],
    queryFn: () => api<MlModelItem[]>('/models'),
  })

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const activeModel = activeQuery.data ?? null
  const modelList = listQuery.data ?? []

  useEffect(() => {
    if (!selectedId) {
      if (activeModel) setSelectedId(activeModel.id)
      else if (modelList.length > 0) setSelectedId(modelList[0].id)
    }
  }, [selectedId, activeModel, modelList])

  const detailQuery = useQuery({
    queryKey: ['models', 'detail', selectedId],
    queryFn: () => api<MlModelItem>(`/models/${selectedId}`),
    enabled: Boolean(selectedId && selectedId !== activeModel?.id),
  })

  const displayedModel =
    selectedId && activeModel && selectedId === activeModel.id
      ? activeModel
      : detailQuery.data ?? activeModel ?? modelList[0] ?? null

  const isEmpty =
    !activeQuery.isLoading && !listQuery.isLoading && !activeModel && modelList.length === 0

  const metrics = displayedModel?.metrics
  const b0 = displayedModel?.baseline_metrics?.B0
  const b1 = displayedModel?.baseline_metrics?.B1

  const sourceMix = displayedModel?.source_mix ?? {}
  const totalMix = Object.values(sourceMix).reduce((acc, v) => acc + Number(v || 0), 0)

  const maeCandidates = [
    metrics?.mae_kg_m2,
    b0?.mae_kg_m2,
    b1?.mae_kg_m2,
  ].filter((x): x is number => typeof x === 'number')
  const bestMae = maeCandidates.length > 0 ? Math.min(...maeCandidates) : null

  const rmseCandidates = [
    metrics?.rmse_kg_m2,
    b0?.rmse_kg_m2,
    b1?.rmse_kg_m2,
  ].filter((x): x is number => typeof x === 'number')
  const bestRmse = rmseCandidates.length > 0 ? Math.min(...rmseCandidates) : null

  const r2Candidates = [metrics?.r2, b0?.r2, b1?.r2].filter(
    (x): x is number => typeof x === 'number',
  )
  const bestR2 = r2Candidates.length > 0 ? Math.max(...r2Candidates) : null

  const driftFeatures = Object.entries(displayedModel?.feature_drift?.features ?? {})

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Mô hình AI Năng suất Toàn cục</h2>
          <p className="muted" style={{ margin: 0 }}>
            Chỉ số đánh giá tổng hợp trên nhà kính chưa từng thấy (Test), so sánh Baseline B0/B1 và theo dõi lệch dữ liệu (Data Drift)
          </p>
        </div>
        {displayedModel && (
          <span className={`badge ${displayedModel.is_active ? 'ok' : 'muted'}`}>
            {displayedModel.is_active
              ? `● Đang kích hoạt: v${displayedModel.version}`
              : `Đang xem phiên bản: v${displayedModel.version}`}
          </span>
        )}
      </div>

      {(activeQuery.isError || listQuery.isError) && (
        <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
          {formatApiError(activeQuery.error || listQuery.error)}
        </div>
      )}

      {(activeQuery.isLoading || listQuery.isLoading) && (
        <div className="card muted">Đang tải thông tin mô hình AI...</div>
      )}

      {isEmpty && (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem' }}>
          <h3>Chưa có mô hình</h3>
          <p className="muted">
            Chưa có phiên bản mô hình <code>task = &apos;yield&apos;</code> nào được đăng ký. Huấn luyện offline bằng{' '}
            <code>python -m ml.train --task yield</code>.
          </p>
        </div>
      )}

      {displayedModel && (
        <>
          {/* Thông tin tổng quan & cơ cấu nguồn dữ liệu */}
          <div className="card">
            <div className="card-header">
              <div>
                <h3>
                  Mô hình <code>yield</code> v{displayedModel.version}{' '}
                  {displayedModel.is_active && <span className="badge ok">Active</span>}
                </h3>
                <span className="muted" style={{ fontSize: '0.8rem' }}>
                  Huấn luyện lúc: {formatDateTimeVi(displayedModel.trained_at)} • Feature version:{' '}
                  <code>v{displayedModel.feature_version}</code> • Artifact:{' '}
                  <code>{displayedModel.artifact_path}</code>
                </span>
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                <span className="badge info">{displayedModel.n_samples ?? 0} mẫu</span>
                <span className="badge info">{displayedModel.n_greenhouses ?? 0} nhà kính</span>
              </div>
            </div>

            {displayedModel.notes && (
              <div className="alert-banner info" style={{ marginBottom: '1rem' }}>
                Ghi chú: {displayedModel.notes}
              </div>
            )}

            {/* Cơ cấu nguồn dữ liệu */}
            <h4 style={{ margin: '0 0 0.5rem', fontSize: '0.88rem' }}>
              Cơ cấu nguồn dữ liệu huấn luyện (<code>source_mix</code>)
            </h4>
            {totalMix > 0 ? (
              <>
                <div
                  style={{
                    display: 'flex',
                    height: 16,
                    borderRadius: 999,
                    overflow: 'hidden',
                    background: '#e2e8f0',
                    marginBottom: '0.6rem',
                  }}
                >
                  {Object.entries(sourceMix).map(([src, cnt]) => {
                    const pct = (Number(cnt) / totalMix) * 100
                    return (
                      <div
                        key={src}
                        style={{
                          width: `${pct}%`,
                          background: SOURCE_COLORS[src] ?? '#64748b',
                        }}
                        title={`${src}: ${cnt} mẫu (${pct.toFixed(1)}%)`}
                      />
                    )
                  })}
                </div>
                <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', fontSize: '0.82rem', marginBottom: '1.1rem' }}>
                  {Object.entries(sourceMix).map(([src, cnt]) => (
                    <span key={src} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                      <span
                        style={{
                          width: 10,
                          height: 10,
                          borderRadius: 2,
                          background: SOURCE_COLORS[src] ?? '#64748b',
                          display: 'inline-block',
                        }}
                      />
                      <strong>{SOURCE_LABELS[src] ?? src}:</strong> {cnt} ({((Number(cnt) / totalMix) * 100).toFixed(1)}%)
                    </span>
                  ))}
                </div>
              </>
            ) : (
              <p className="muted">Chưa có thống kê nguồn dữ liệu.</p>
            )}

            {/* Danh sách cây hỗ trợ */}
            <h4 style={{ margin: '0 0 0.5rem', fontSize: '0.88rem' }}>
              Danh sách cây trồng và năng suất tham chiếu
            </h4>
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Tên cây</th>
                    <th>Mã kỹ thuật (<code>crop_code</code>)</th>
                    <th>Số mẫu huấn luyện</th>
                    <th>Năng suất tham chiếu (<code>reference_kg_m2</code>)</th>
                  </tr>
                </thead>
                <tbody>
                  {(displayedModel.crops ?? []).map((c) => (
                    <tr key={c.crop_code}>
                      <td>
                        <strong>{formatCropName(c.crop_code)}</strong>
                      </td>
                      <td>
                        <code>{c.crop_code}</code>
                      </td>
                      <td>{c.n}</td>
                      <td>{c.reference_kg_m2} kg/m²</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Bảng chất lượng trên tập Test & Baseline */}
          <div className="grid grid-cols-2">
            <div className="card">
              <div className="card-header">
                <h3>Chất lượng trên nhà kính chưa từng thấy</h3>
              </div>
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Mô hình</th>
                      <th>MAE (kg/m²) ↓</th>
                      <th>RMSE (kg/m²) ↓</th>
                      <th>R² ↑</th>
                      <th>MAPE (%) ↓</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>
                        <strong>LightGBM</strong>
                      </td>
                      <td>
                        <strong
                          style={{
                            color:
                              bestMae !== null && metrics?.mae_kg_m2 === bestMae
                                ? 'var(--primary)'
                                : undefined,
                          }}
                        >
                          {fmtNum(metrics?.mae_kg_m2, 4)}
                        </strong>
                      </td>
                      <td>
                        <strong
                          style={{
                            color:
                              bestRmse !== null && metrics?.rmse_kg_m2 === bestRmse
                                ? 'var(--primary)'
                                : undefined,
                          }}
                        >
                          {fmtNum(metrics?.rmse_kg_m2, 4)}
                        </strong>
                      </td>
                      <td>
                        <strong
                          style={{
                            color:
                              bestR2 !== null && metrics?.r2 === bestR2
                                ? 'var(--primary)'
                                : undefined,
                          }}
                        >
                          {fmtNum(metrics?.r2, 4)}
                        </strong>
                      </td>
                      <td>{typeof metrics?.mape === 'number' ? `${metrics.mape.toFixed(1)}%` : '—'}</td>
                    </tr>
                    <tr>
                      <td>B0</td>
                      <td>{fmtNum(b0?.mae_kg_m2, 4)}</td>
                      <td>{fmtNum(b0?.rmse_kg_m2, 4)}</td>
                      <td>{fmtNum(b0?.r2, 4)}</td>
                      <td>{typeof b0?.mape === 'number' ? `${b0.mape.toFixed(1)}%` : '—'}</td>
                    </tr>
                    <tr>
                      <td>B1</td>
                      <td>{fmtNum(b1?.mae_kg_m2, 4)}</td>
                      <td>{fmtNum(b1?.rmse_kg_m2, 4)}</td>
                      <td>{fmtNum(b1?.r2, 4)}</td>
                      <td>{typeof b1?.mape === 'number' ? `${b1.mape.toFixed(1)}%` : '—'}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <h3>Chất lượng Gợi ý cây trồng</h3>
              </div>
              <p className="muted" style={{ fontSize: '0.8rem', marginTop: 0 }}>
                Đối chiếu với xếp hạng lý tưởng (oracle) trên tập test — lưu ý chỉ tính trên dữ liệu{' '}
                <code>synthetic</code>.
              </p>
              <div className="grid grid-cols-2">
                <div className="metric-tile">
                  <span className="label">Top-1 Accuracy</span>
                  <span className="value">
                    {typeof metrics?.top1_accuracy === 'number'
                      ? `${(metrics.top1_accuracy * 100).toFixed(1)}%`
                      : '—'}
                  </span>
                  <span className="subtext muted">
                    B0: {typeof b0?.top1_accuracy === 'number' ? `${(b0.top1_accuracy * 100).toFixed(1)}%` : '—'} ·
                    B1: {typeof b1?.top1_accuracy === 'number' ? `${(b1.top1_accuracy * 100).toFixed(1)}%` : '—'}
                  </span>
                </div>
                <div className="metric-tile">
                  <span className="label">NDCG@3</span>
                  <span className="value">{fmtNum(metrics?.ndcg_at_3, 4)}</span>
                  <span className="subtext muted">
                    Số mẫu đánh giá: {metrics?.n_eval ?? 0}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Tách theo cây và theo nguồn */}
          <div className="grid grid-cols-2">
            <div className="card">
              <div className="card-header">
                <h3>Sai số theo từng cây trồng</h3>
              </div>
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Cây trồng</th>
                      <th>Số mẫu</th>
                      <th>MAE (kg/m²)</th>
                      <th>RMSE (kg/m²)</th>
                      <th>R²</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(metrics?.by_crop ?? {}).map(([code, m]) => (
                      <tr key={code}>
                        <td>
                          <strong>{CROP_NAMES_VI[code] ?? code}</strong>{' '}
                          <span className="muted" style={{ fontSize: '0.75rem' }}>
                            (<code>{code}</code>)
                          </span>
                        </td>
                        <td>{m.n}</td>
                        <td>{fmtNum(m.mae_kg_m2, 4)}</td>
                        <td>{fmtNum(m.rmse_kg_m2, 4)}</td>
                        <td>{fmtNum(m.r2, 4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <h3>Sai số tách theo nguồn dữ liệu</h3>
              </div>
              <p className="muted" style={{ fontSize: '0.8rem', marginTop: 0 }}>
                Báo cáo trung thực từng nguồn dữ liệu, bao gồm mẫu <code>real</code> dù số lượng ít.
              </p>
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Nguồn</th>
                      <th>Số mẫu</th>
                      <th>MAE (kg/m²)</th>
                      <th>RMSE (kg/m²)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(metrics?.by_source ?? {}).map(([src, m]) => (
                      <tr key={src}>
                        <td>
                          <strong>{SOURCE_LABELS[src] ?? src}</strong>
                        </td>
                        <td>{m.n}</td>
                        <td>{fmtNum(m.mae_kg_m2, 4)}</td>
                        <td>{fmtNum(m.rmse_kg_m2, 4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Dấu hiệu lệch dữ liệu (Data Drift) */}
          <div className="card">
            <div className="card-header">
              <div>
                <h3>Dấu hiệu lệch dữ liệu</h3>
                <span className="muted" style={{ fontSize: '0.8rem' }}>
                  So sánh phân phối đặc trưng khí hậu của {displayedModel.feature_drift?.n_predictions ?? 0} lượt dự đoán gần nhất của farm với tập huấn luyện (cảnh báo khi |z| ≥ 2.0 với ≥ 5 mẫu)
                </span>
              </div>
            </div>

            {driftFeatures.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>
                Chưa có đủ dữ liệu thống kê lệch phân phối đặc trưng.
              </p>
            ) : (
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>Đặc trưng</th>
                      <th>Train</th>
                      <th>7 ngày gần nhất</th>
                      <th>Số mẫu gần đây</th>
                      <th>|Z-score|</th>
                      <th>Trạng thái</th>
                    </tr>
                  </thead>
                  <tbody>
                    {driftFeatures.map(([feat, stat]) => (
                      <tr key={feat}>
                        <td>
                          <code>{feat}</code>
                        </td>
                        <td>
                          {stat.train_mean !== null
                            ? `${stat.train_mean.toFixed(2)} ± ${(stat.train_std ?? 0).toFixed(2)}`
                            : '—'}
                        </td>
                        <td>
                          {stat.recent_mean !== null
                            ? `${stat.recent_mean.toFixed(2)} ± ${(stat.recent_std ?? 0).toFixed(2)}`
                            : 'Chưa có'}
                        </td>
                        <td>{stat.n_recent}</td>
                        <td>{stat.z_score !== null ? stat.z_score.toFixed(2) : '—'}</td>
                        <td>
                          {stat.drifted ? (
                            <span className="badge warning">Lệch phân phối</span>
                          ) : stat.n_recent === 0 ? (
                            <span className="badge muted">Chưa có dự đoán</span>
                          ) : (
                            <span className="badge ok">Bình thường</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Lịch sử phiên bản */}
          <div className="card">
            <div className="card-header">
              <h3>Lịch sử các phiên bản mô hình</h3>
            </div>
            <div className="table-container">
              <table>
                <thead>
                  <tr>
                    <th>Phiên bản</th>
                    <th>Thời gian huấn luyện</th>
                    <th>Số mẫu</th>
                    <th>MAE Test (kg/m²)</th>
                    <th>Trạng thái</th>
                    <th>Ghi chú</th>
                    <th>Xem</th>
                  </tr>
                </thead>
                <tbody>
                  {modelList.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <strong>v{m.version}</strong>
                      </td>
                      <td>{formatDateTimeVi(m.trained_at)}</td>
                      <td>{m.n_samples ?? 0}</td>
                      <td>{fmtNum(m.metrics?.mae_kg_m2, 4)}</td>
                      <td>
                        <span className={`badge ${m.is_active ? 'ok' : 'muted'}`}>
                          {m.is_active ? 'Đang kích hoạt' : 'Không kích hoạt'}
                        </span>
                      </td>
                      <td className="muted" style={{ fontSize: '0.8rem' }}>
                        {m.notes || '—'}
                      </td>
                      <td>
                        <button
                          type="button"
                          className={`btn btn-sm ${displayedModel.id === m.id ? 'btn-primary' : 'btn-secondary'}`}
                          onClick={() => setSelectedId(m.id)}
                        >
                          {displayedModel.id === m.id ? 'Đang xem' : 'Chi tiết'}
                        </button>
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
