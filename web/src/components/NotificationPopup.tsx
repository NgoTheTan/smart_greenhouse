import { useEffect, useRef, useState, type MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useNotifications, type FormattedNotification } from '../lib/notifications'

export default function NotificationPopup() {
  const navigate = useNavigate()
  const {
    notifications,
    unreadCount,
    isLoading,
    markAsRead,
    markAsUnread,
    markAllAsRead,
  } = useNotifications()

  const [isOpen, setIsOpen] = useState(false)
  const [filter, setFilter] = useState<'all' | 'unread'>('all')
  const popupRef = useRef<HTMLDivElement | null>(null)

  // Đóng pop up khi nhấp chuột ra ngoài hoặc bấm phím Escape
  useEffect(() => {
    if (!isOpen) return

    const handleClickOutside = (e: globalThis.MouseEvent) => {
      if (popupRef.current && !popupRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  const displayedNotifications =
    filter === 'unread' ? notifications.filter((n) => !n.isRead) : notifications

  const handleItemClick = (n: FormattedNotification) => {
    if (!n.isRead) {
      markAsRead(n.id)
    }
    setIsOpen(false)
    navigate(n.targetUrl)
  }

  const handleToggleRead = (e: MouseEvent, n: FormattedNotification) => {
    e.stopPropagation()
    if (n.isRead) {
      markAsUnread(n.id)
    } else {
      markAsRead(n.id)
    }
  }

  return (
    <div ref={popupRef} style={{ position: 'relative', display: 'inline-block' }}>
      {/* Nút Chuông Thông báo */}
      <button
        type="button"
        title={unreadCount > 0 ? `Có ${unreadCount} thông báo chưa đọc` : 'Thông báo'}
        aria-label="Thông báo"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((prev) => !prev)}
        style={{
          position: 'relative',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '36px',
          height: '36px',
          borderRadius: 'var(--radius-btn, 8px)',
          background: isOpen ? '#EEECE5' : 'transparent',
          color: 'var(--text-main, #1C211E)',
          border: '1px solid transparent',
          cursor: 'pointer',
          padding: 0,
          transition: 'background-color 0.15s ease',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = '#EEECE5'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = isOpen ? '#EEECE5' : 'transparent'
        }}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>

        {unreadCount > 0 && (
          <span
            style={{
              position: 'absolute',
              top: '2px',
              right: '2px',
              background: 'var(--status-offline, #B94A32)',
              color: '#fff',
              fontSize: '0.62rem',
              fontWeight: 700,
              borderRadius: '9999px',
              minWidth: '1rem',
              height: '1rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '0 0.2rem',
              border: '1px solid #FFFFFF',
              lineHeight: 1,
            }}
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Pop up Dropdown */}
      {isOpen && (
        <div
          role="dialog"
          aria-label="Hộp thoại thông báo"
          style={{
            position: 'absolute',
            top: 'calc(100% + 8px)',
            right: 0,
            width: '380px',
            maxWidth: 'calc(100vw - 20px)',
            background: 'var(--surface-card, #FFFFFF)',
            color: 'var(--text-main, #1C211E)',
            borderRadius: 'var(--radius-card, 10px)',
            border: '1px solid var(--border-card, #E6E3DA)',
            boxShadow: 'none',
            zIndex: 1000,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* Header Pop up */}
          <div
            style={{
              padding: '0.85rem 1rem 0.6rem',
              borderBottom: '1px solid var(--border-row, #EEECE5)',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '0.55rem',
              }}
            >
              <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-main, #1C211E)' }}>
                Thông báo
              </h3>
              {unreadCount > 0 && (
                <button
                  type="button"
                  onClick={markAllAsRead}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--accent, #1E6B47)',
                    fontSize: '0.78rem',
                    fontWeight: 500,
                    cursor: 'pointer',
                    padding: '0.2rem 0.4rem',
                    borderRadius: '4px',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.textDecoration = 'underline'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.textDecoration = 'none'
                  }}
                >
                  Đánh dấu tất cả là đã đọc
                </button>
              )}
            </div>

            {/* Bộ lọc Tất cả / Chưa đọc */}
            <div style={{ display: 'flex', gap: '0.4rem' }}>
              <button
                type="button"
                onClick={() => setFilter('all')}
                style={{
                  padding: '0.25rem 0.75rem',
                  borderRadius: 'var(--radius-btn, 8px)',
                  fontSize: '0.8rem',
                  fontWeight: 500,
                  border: '1px solid var(--border-input, #D9D6CB)',
                  cursor: 'pointer',
                  background: filter === 'all' ? 'var(--item-selected, #E8F0EA)' : '#FFFFFF',
                  color: filter === 'all' ? 'var(--accent, #1E6B47)' : 'var(--text-muted, #626861)',
                  transition: 'background-color 0.15s ease',
                }}
              >
                Tất cả
              </button>
              <button
                type="button"
                onClick={() => setFilter('unread')}
                style={{
                  padding: '0.25rem 0.75rem',
                  borderRadius: 'var(--radius-btn, 8px)',
                  fontSize: '0.8rem',
                  fontWeight: 500,
                  border: '1px solid var(--border-input, #D9D6CB)',
                  cursor: 'pointer',
                  background: filter === 'unread' ? 'var(--item-selected, #E8F0EA)' : '#FFFFFF',
                  color: filter === 'unread' ? 'var(--accent, #1E6B47)' : 'var(--text-muted, #626861)',
                  transition: 'background-color 0.15s ease',
                }}
              >
                Chưa đọc {unreadCount > 0 ? `(${unreadCount})` : ''}
              </button>
            </div>
          </div>

          {/* Danh sách Thông báo cuộn */}
          <div
            style={{
              maxHeight: '420px',
              overflowY: 'auto',
              padding: '0.4rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
            }}
          >
            {isLoading ? (
              <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--muted)', fontSize: '0.85rem' }}>
                Đang tải thông báo...
              </div>
            ) : displayedNotifications.length === 0 ? (
              <div style={{ padding: '2.5rem 1rem', textAlign: 'center', color: 'var(--muted)', fontSize: '0.88rem' }}>
                {filter === 'unread' ? 'Không có thông báo chưa đọc nào.' : 'Chưa có thông báo nào.'}
              </div>
            ) : (
              displayedNotifications.map((n) => {
                const borderAccent =
                  n.severity === 'critical'
                    ? '#ef4444'
                    : n.severity === 'warning'
                      ? '#f59e0b'
                      : '#3b82f6'

                return (
                  <div
                    key={n.id}
                    onClick={() => handleItemClick(n)}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '0.75rem',
                      padding: '0.65rem 0.75rem',
                      borderRadius: '8px',
                      cursor: 'pointer',
                      background: n.isRead ? 'transparent' : '#f0fdf4',
                      borderLeft: `4px solid ${borderAccent}`,
                      transition: 'background 0.15s ease',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = n.isRead ? '#f8fafc' : '#e6f7ec'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = n.isRead ? 'transparent' : '#f0fdf4'
                    }}
                  >
                    {/* Khối Nội dung Liền mạch */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          fontWeight: n.isRead ? 600 : 700,
                          fontSize: '0.88rem',
                          color: 'var(--text)',
                          marginBottom: '0.2rem',
                          lineHeight: 1.3,
                        }}
                      >
                        {n.title}
                      </div>

                      <div
                        style={{
                          fontSize: '0.82rem',
                          color: n.isRead ? 'var(--muted)' : '#1e293b',
                          lineHeight: 1.4,
                          marginBottom: '0.3rem',
                        }}
                      >
                        {n.body}
                      </div>

                      <div
                        style={{
                          fontSize: '0.74rem',
                          color: n.isRead ? 'var(--muted)' : 'var(--primary)',
                          fontWeight: n.isRead ? 500 : 600,
                        }}
                      >
                        {n.relativeTime}
                      </div>
                    </div>

                    {/* Chỉ báo Chưa đọc & Nút Thao tác đọc/chưa đọc */}
                    <div
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        gap: '0.4rem',
                        paddingTop: '0.2rem',
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

                      <button
                        type="button"
                        title={n.isRead ? 'Đánh dấu là chưa đọc' : 'Đánh dấu là đã đọc'}
                        aria-label={n.isRead ? 'Đánh dấu là chưa đọc' : 'Đánh dấu là đã đọc'}
                        onClick={(e) => handleToggleRead(e, n)}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--muted)',
                          cursor: 'pointer',
                          padding: '0.15rem',
                          fontSize: '0.7rem',
                          borderRadius: '4px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.color = 'var(--text)'
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.color = 'var(--muted)'
                        }}
                      >
                        <svg
                          width="14"
                          height="14"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden="true"
                        >
                          {n.isRead ? (
                            <>
                              <circle cx="12" cy="12" r="10" />
                              <circle cx="12" cy="12" r="4" fill="currentColor" />
                            </>
                          ) : (
                            <>
                              <polyline points="20 6 9 17 4 12" />
                            </>
                          )}
                        </svg>
                      </button>
                    </div>
                  </div>
                )
              })
            )}
          </div>

          {/* Footer Pop up */}
          <div
            style={{
              padding: '0.65rem 1rem',
              borderTop: '1px solid var(--border-row, #EEECE5)',
              background: 'var(--surface-card, #FFFFFF)',
              textAlign: 'center',
            }}
          >
            <Link
              to="/alerts"
              onClick={() => setIsOpen(false)}
              style={{
                fontSize: '0.82rem',
                fontWeight: 500,
                color: 'var(--accent, #1E6B47)',
                textDecoration: 'none',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.textDecoration = 'underline'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.textDecoration = 'none'
              }}
            >
              Xem tất cả trong trang Cảnh báo →
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
