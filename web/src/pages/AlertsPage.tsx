import { useState } from 'react'
import { Link } from 'react-router-dom'
import { formatApiError } from '../lib/api'
import { useNotifications, type FormattedNotification } from '../lib/notifications'

export default function AlertsPage() {
  const {
    notifications,
    unreadCount,
    isLoading,
    isError,
    error,
    markAsRead,
    markAsUnread,
    markAllAsRead,
  } = useNotifications()

  const [filter, setFilter] = useState<'all' | 'unread'>('all')

  const displayedNotifications =
    filter === 'unread' ? notifications.filter((n) => !n.isRead) : notifications

  const handleToggleRead = (n: FormattedNotification) => {
    if (n.isRead) {
      markAsUnread(n.id)
    } else {
      markAsRead(n.id)
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Trung tâm Thông báo &amp; Cảnh báo</h2>
          <p className="muted" style={{ margin: 0 }}>
            Tất cả thông báo sự cố vi khí hậu, thiết bị và mùa vụ của toàn bộ nhà kính
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {unreadCount > 0 && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={markAllAsRead}
              style={{ fontSize: '0.85rem' }}
            >
              Đánh dấu tất cả là đã đọc
            </button>
          )}
        </div>
      </div>

      {/* Bộ lọc đơn giản: Tất cả / Chưa đọc */}
      <div className="tab-strip" style={{ marginBottom: '1rem' }}>
        <button
          type="button"
          className={`btn btn-sm ${filter === 'all' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setFilter('all')}
        >
          Tất cả ({notifications.length})
        </button>
        <button
          type="button"
          className={`btn btn-sm ${filter === 'unread' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setFilter('unread')}
        >
          Chưa đọc ({unreadCount})
        </button>
      </div>

      {isError && (
        <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
          Không tải được danh sách thông báo: {formatApiError(error)}
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <h3>Danh sách thông báo</h3>
          <span className="badge info">{displayedNotifications.length} thông báo</span>
        </div>

        {isLoading ? (
          <p className="muted" style={{ padding: '1rem 0', margin: 0 }}>
            Đang tải thông báo...
          </p>
        ) : displayedNotifications.length === 0 ? (
          <p className="muted" style={{ textAlign: 'center', padding: '2.5rem 0', margin: 0 }}>
            {filter === 'unread'
              ? 'Tuyệt vời, bạn đã đọc hết toàn bộ thông báo!'
              : 'Hiện chưa có thông báo nào được ghi nhận.'}
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {displayedNotifications.map((n) => {
              const borderAccent =
                n.severity === 'critical'
                  ? '#ef4444'
                  : n.severity === 'warning'
                    ? '#f59e0b'
                    : '#3b82f6'

              const badgeCls =
                n.severity === 'critical'
                  ? 'bad'
                  : n.severity === 'warning'
                    ? 'warning'
                    : 'info'

              const severityLabel =
                n.severity === 'critical'
                  ? 'Khẩn cấp'
                  : n.severity === 'warning'
                    ? 'Cảnh báo'
                    : 'Thông tin'

              return (
                <div
                  key={n.id}
                  style={{
                    border: `1px solid ${n.isRead ? 'var(--border)' : '#bbf7d0'}`,
                    borderLeft: `5px solid ${borderAccent}`,
                    background: n.isRead ? '#ffffff' : '#f0fdf4',
                    borderRadius: 'var(--radius)',
                    padding: '1rem 1.15rem',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    flexWrap: 'wrap',
                    gap: '1rem',
                    transition: 'background 0.15s ease',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 260 }}>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.55rem',
                        flexWrap: 'wrap',
                        marginBottom: '0.4rem',
                      }}
                    >
                      {!n.isRead && (
                        <span
                          title="Chưa đọc"
                          style={{
                            width: '9px',
                            height: '9px',
                            borderRadius: '50%',
                            background: '#16a34a',
                            display: 'inline-block',
                          }}
                        />
                      )}
                      <span className={`badge ${badgeCls}`}>{severityLabel}</span>
                      <strong style={{ fontSize: '0.96rem', color: 'var(--text)' }}>
                        {n.title}
                      </strong>
                    </div>

                    <p
                      style={{
                        margin: '0.35rem 0',
                        fontSize: '0.88rem',
                        color: n.isRead ? 'var(--text)' : '#1e293b',
                        lineHeight: 1.45,
                      }}
                    >
                      {n.body}
                    </p>

                    <div
                      className="muted"
                      style={{
                        fontSize: '0.8rem',
                        display: 'flex',
                        gap: '1rem',
                        flexWrap: 'wrap',
                        marginTop: '0.5rem',
                      }}
                    >
                      <span>{n.relativeTime}</span>
                      <span>Thời gian: {n.formattedTime}</span>
                    </div>
                  </div>

                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.55rem',
                      flexWrap: 'wrap',
                    }}
                  >
                    <button
                      type="button"
                      className={`btn btn-sm ${n.isRead ? 'btn-secondary' : 'btn-primary'}`}
                      onClick={() => handleToggleRead(n)}
                      style={{ fontSize: '0.82rem' }}
                    >
                      {n.isRead ? 'Đánh dấu chưa đọc' : 'Đánh dấu đã đọc'}
                    </button>

                    <Link
                      to={n.targetUrl}
                      onClick={() => {
                        if (!n.isRead) markAsRead(n.id)
                      }}
                      className="btn btn-sm btn-secondary"
                      style={{ fontSize: '0.82rem' }}
                    >
                      Xem chi tiết →
                    </Link>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
