import { useState, useEffect } from 'react'
import { subscribePush } from '../lib/push'

export default function NotificationsPage() {
  const [permission, setPermission] = useState<NotificationPermission>('default')
  const [subscribing, setSubscribing] = useState(false)
  const [pushStatus, setPushStatus] = useState<string | null>(null)
  const [testSent, setTestSent] = useState(false)

  useEffect(() => {
    if ('Notification' in window) {
      setPermission(Notification.permission)
    }
  }, [])

  const handleSubscribe = async () => {
    setSubscribing(true)
    setPushStatus('Đang xin quyền thông báo từ trình duyệt...')
    try {
      const ok = await subscribePush()
      if (ok) {
        setPermission('granted')
        setPushStatus('✅ Đã đăng ký Web Push thành công! Thiết bị này sẽ nhận thông báo kể cả khi đóng tab.')
      } else {
        setPermission(Notification.permission)
        setPushStatus('ℹ️ Đã cấp quyền thông báo cục bộ (chế độ demo/localhost).')
      }
    } catch {
      // Khi backend chưa bật endpoint /push/public-key, ta vẫn kích hoạt Notification API cục bộ
      if ('Notification' in window) {
        const p = await Notification.requestPermission()
        setPermission(p)
        if (p === 'granted') {
          setPushStatus('✅ Đã cấp quyền Notification của trình duyệt thành công!')
        } else {
          setPushStatus('⚠️ Quyền thông báo đã bị từ chối trong cài đặt trình duyệt.')
        }
      }
    } finally {
      setSubscribing(false)
    }
  }

  const handleTestNotification = () => {
    if (Notification.permission === 'granted') {
      new Notification('🌱 [GreenHub] Cảnh báo thử nghiệm', {
        body: 'Hệ thống Web Push hoạt động hoàn hảo! VPD Zone 1 đang ở mức tối ưu 0.95 kPa.',
        icon: '/icon-192.png',
      })
      setTestSent(true)
      setTimeout(() => setTestSent(false), 3000)
    } else {
      alert('Vui lòng bấm nút "Bật nhận thông báo Web Push" trước!')
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
        <div>
          <h2>📲 Cài đặt Thông báo & Web Push</h2>
          <p className="muted" style={{ margin: 0 }}>Nhận thông báo sự cố ngay lập tức trên máy tính và điện thoại</p>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3>🔔 Thông báo đẩy Web Push (VAPID + Service Worker)</h3>
          <span className={`badge ${permission === 'granted' ? 'ok' : 'warning'}`}>
            Trạng thái: {permission === 'granted' ? 'Đã cho phép' : permission === 'denied' ? 'Bị chặn' : 'Chưa bật'}
          </span>
        </div>

        <p className="muted" style={{ fontSize: '0.85rem' }}>
          GreenHub sử dụng tiêu chuẩn Web Push mở. Khi có rủi ro nấm bệnh (A3) hoặc đất quá khô, thông báo sẽ rung chuông điện thoại ngay cả khi bạn không mở web.
        </p>

        {pushStatus && (
          <div style={{ padding: '0.6rem 0.85rem', background: '#f8fafc', border: '1px solid var(--border)', borderRadius: 'var(--radius)', marginBottom: '1rem', fontSize: '0.85rem' }}>
            {pushStatus}
          </div>
        )}

        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
          <button
            className="btn btn-primary"
            onClick={handleSubscribe}
            disabled={subscribing}
          >
            {subscribing ? 'Đang kích hoạt...' : '🔔 Bật nhận thông báo Web Push trên thiết bị này'}
          </button>

          <button
            className="btn btn-secondary"
            onClick={handleTestNotification}
          >
            {testSent ? '✓ Đã bắn thông báo!' : '🚀 Gửi thông báo thử nghiệm (Test Push)'}
          </button>
        </div>

        {/* HƯỚNG DẪN DÀNH CHO IPHONE IOS */}
        <div style={{ background: '#f1f5f9', padding: '1rem', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
          <h4 style={{ margin: '0 0 0.5rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
            🍎 Lưu ý quan trọng cho người dùng iPhone / iPad (iOS 16.4+)
          </h4>
          <ol style={{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.85rem', color: 'var(--muted)', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
            <li>Apple yêu cầu web phải được cài đặt ra màn hình chính thì mới được phép nhận Web Push.</li>
            <li>Trên trình duyệt Safari: Bấm vào nút <strong>Chia sẻ (Share icon)</strong> ở góc dưới màn hình.</li>
            <li>Chọn <strong>"Thêm vào Màn hình chính" (Add to Home Screen)</strong>.</li>
            <li>Mở icon GreenHub từ màn hình chính và bấm nút <em>"Bật nhận thông báo"</em> ở trên.</li>
          </ol>
        </div>
      </div>
    </div>
  )
}

