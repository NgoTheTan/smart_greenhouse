import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, formatApiError } from '../lib/api'
import {
  getCurrentPushSubscription,
  subscribePush,
  unsubscribePush,
} from '../lib/push'
import type { AlertSeverity, NotificationPref } from '../lib/types'

export default function NotificationsPage() {
  const queryClient = useQueryClient()
  const [permission, setPermission] = useState<NotificationPermission>(() =>
    'Notification' in window ? Notification.permission : 'denied',
  )
  const [hasSubscription, setHasSubscription] = useState(false)
  const [pushBusy, setPushBusy] = useState(false)
  const [pushMessage, setPushMessage] = useState<{ ok: boolean; text: string } | null>(null)

  const prefsQuery = useQuery({
    queryKey: ['notification-prefs'],
    queryFn: () => api<NotificationPref>('/me/notification-prefs'),
  })

  const [pushEnabled, setPushEnabled] = useState(true)
  const [emailEnabled, setEmailEnabled] = useState(true)
  const [minSeverity, setMinSeverity] = useState<AlertSeverity>('warning')
  const [prefsMsg, setPrefsMsg] = useState<string | null>(null)

  useEffect(() => {
    if (prefsQuery.data) {
      setPushEnabled(prefsQuery.data.push_enabled)
      setEmailEnabled(prefsQuery.data.email_enabled)
      setMinSeverity(prefsQuery.data.min_severity)
    }
  }, [prefsQuery.data])

  useEffect(() => {
    void getCurrentPushSubscription()
      .then((sub) => setHasSubscription(Boolean(sub)))
      .catch(() => setHasSubscription(false))
  }, [])

  const updatePrefsMutation = useMutation({
    mutationFn: (payload: Partial<NotificationPref>) =>
      api<NotificationPref>('/me/notification-prefs', {
        method: 'PUT',
        body: JSON.stringify(payload),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(['notification-prefs'], data)
      setPrefsMsg('Đã lưu tuỳ chọn nhận thông báo.')
    },
    onError: (err) => {
      setPrefsMsg(formatApiError(err))
    },
  })

  const handleSubscribe = async () => {
    setPushBusy(true)
    setPushMessage(null)
    try {
      const ok = await subscribePush()
      if ('Notification' in window) setPermission(Notification.permission)
      const sub = await getCurrentPushSubscription()
      setHasSubscription(Boolean(sub))
      if (ok) {
        setPushMessage({
          ok: true,
          text: 'Đã đăng ký Web Push thành công! Thiết bị này sẽ nhận cảnh báo ngay cả khi đóng tab.',
        })
      } else {
        setPushMessage({
          ok: false,
          text: 'Trình duyệt chưa cấp quyền thông báo (Permission chưa được Granted).',
        })
      }
    } catch (err) {
      if ('Notification' in window) setPermission(Notification.permission)
      setPushMessage({ ok: false, text: formatApiError(err) })
    } finally {
      setPushBusy(false)
    }
  }

  const handleUnsubscribe = async () => {
    setPushBusy(true)
    setPushMessage(null)
    try {
      await unsubscribePush()
      setHasSubscription(false)
      setPushMessage({ ok: true, text: 'Đã huỷ đăng ký Web Push trên thiết bị này.' })
    } catch (err) {
      setPushMessage({ ok: false, text: formatApiError(err) })
    } finally {
      setPushBusy(false)
    }
  }

  const handleSavePrefs = () => {
    setPrefsMsg(null)
    updatePrefsMutation.mutate({
      push_enabled: pushEnabled,
      email_enabled: emailEnabled,
      min_severity: minSeverity,
    })
  }

  const permLabel =
    permission === 'granted' ? 'Đã cho phép' : permission === 'denied' ? 'Bị chặn' : 'Chưa bật'

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>📲 Cài đặt Thông báo &amp; Web Push</h2>
          <p className="muted" style={{ margin: 0 }}>
            Quản lý đăng ký Web Push (VAPID) trên thiết bị này và tuỳ chọn kênh nhận cảnh báo cá nhân
          </p>
        </div>
      </div>

      {/* Khối Web Push */}
      <div className="card">
        <div className="card-header">
          <h3>🔔 Thông báo đẩy Web Push (Service Worker + VAPID)</h3>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <span className={`badge ${permission === 'granted' ? 'ok' : 'warning'}`}>
              Quyền trình duyệt: {permLabel}
            </span>
            <span className={`badge ${hasSubscription ? 'ok' : 'muted'}`}>
              {hasSubscription ? 'Đã đăng ký thiết bị' : 'Chưa đăng ký thiết bị'}
            </span>
          </div>
        </div>

        <p className="muted" style={{ fontSize: '0.86rem' }}>
          Khi phát sinh sự cố nguy cơ nấm bệnh hoặc sốc nhiệt, Web Push sẽ gửi thông báo trực tiếp tới trình duyệt hoặc điện thoại ngay cả khi không mở trang web.
        </p>

        {pushMessage && (
          <div
            className={`alert-banner ${pushMessage.ok ? 'ok' : 'bad'}`}
            style={{ marginBottom: '1rem' }}
          >
            {pushMessage.text}
          </div>
        )}

        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSubscribe}
            disabled={pushBusy}
          >
            {pushBusy ? 'Đang xử lý...' : '🔔 Bật thông báo đẩy (Web Push)'}
          </button>

          {hasSubscription && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleUnsubscribe}
              disabled={pushBusy}
            >
              Huỷ đăng ký trên thiết bị này
            </button>
          )}
        </div>

        <div
          style={{
            background: '#f1f5f9',
            padding: '1rem',
            borderRadius: 'var(--radius)',
            border: '1px solid var(--border)',
            marginBottom: '1rem',
          }}
        >
          <h4 style={{ margin: '0 0 0.5rem' }}>
            🍎 Hướng dẫn riêng cho iPhone / iPad (iOS 16.4 trở lên)
          </h4>
          <ol
            style={{
              margin: 0,
              paddingLeft: '1.25rem',
              fontSize: '0.85rem',
              color: 'var(--muted)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.25rem',
            }}
          >
            <li>Mở GreenHub bằng trình duyệt Safari qua HTTPS.</li>
            <li>
              Bấm biểu tượng <strong>Chia sẻ (Share)</strong> và chọn{' '}
              <strong>&quot;Thêm vào Màn hình chính&quot; (Add to Home Screen)</strong>.
            </li>
            <li>Mở ứng dụng GreenHub từ biểu tượng trên màn hình chính rồi bấm nút bật Web Push ở trên.</li>
          </ol>
        </div>

        <div className="muted" style={{ fontSize: '0.8rem' }}>
          <strong>Lưu ý giới hạn:</strong> Web Push phụ thuộc dịch vụ đẩy của trình duyệt và có thể bị ẩn khi bật chế độ <em>Không làm phiền (DND)</em>. Vì vậy, với cảnh báo mức <code>critical</code> chưa được xác nhận, hệ thống luôn có lớp dự phòng qua <strong>Email leo thang</strong> và <strong>Buzzer trên Gateway</strong>.
        </div>
      </div>

      {/* Khối Tuỳ chọn nhận thông báo */}
      <div className="card">
        <div className="card-header">
          <h3>⚙️ Tuỳ chọn nhận thông báo tài khoản</h3>
        </div>

        {prefsQuery.isError && (
          <div className="alert-banner bad" style={{ marginBottom: '1rem' }}>
            {formatApiError(prefsQuery.error)}
          </div>
        )}

        {prefsMsg && (
          <div className="alert-banner info" style={{ marginBottom: '1rem' }}>
            {prefsMsg}
          </div>
        )}

        <div className="grid grid-cols-3" style={{ marginBottom: '1rem' }}>
          <label className="checkbox-card">
            <input
              type="checkbox"
              checked={pushEnabled}
              onChange={(e) => setPushEnabled(e.target.checked)}
            />
            <span>
              <strong>Nhận Web Push</strong>
              <span className="muted" style={{ display: 'block', fontSize: '0.78rem' }}>
                Gửi thông báo đẩy qua trình duyệt đã đăng ký
              </span>
            </span>
          </label>

          <label className="checkbox-card">
            <input
              type="checkbox"
              checked={emailEnabled}
              onChange={(e) => setEmailEnabled(e.target.checked)}
            />
            <span>
              <strong>Nhận Email leo thang</strong>
              <span className="muted" style={{ display: 'block', fontSize: '0.78rem' }}>
                Gửi email khi cảnh báo critical chưa được Ack
              </span>
            </span>
          </label>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label htmlFor="min-severity">Mức độ nghiêm trọng tối thiểu</label>
            <select
              id="min-severity"
              value={minSeverity}
              onChange={(e) => setMinSeverity(e.target.value as AlertSeverity)}
            >
              <option value="info">Info (Tất cả cảnh báo)</option>
              <option value="warning">Warning (Cảnh báo &amp; Nghiêm trọng)</option>
              <option value="critical">Critical (Chỉ sự cố nghiêm trọng)</option>
            </select>
          </div>
        </div>

        <button
          type="button"
          className="btn btn-primary"
          onClick={handleSavePrefs}
          disabled={updatePrefsMutation.isPending || prefsQuery.isLoading}
        >
          {updatePrefsMutation.isPending ? 'Đang lưu...' : '💾 Lưu tuỳ chọn thông báo'}
        </button>
      </div>
    </div>
  )
}
