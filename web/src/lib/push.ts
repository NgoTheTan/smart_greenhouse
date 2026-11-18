// Đăng ký & hủy đăng ký Web Push - PHẢI gọi từ thao tác bấm của người dùng (spec 10).
import { api } from './api'

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

export async function getCurrentPushSubscription(): Promise<PushSubscription | null> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null
  const reg = await navigator.serviceWorker.ready
  return reg.pushManager.getSubscription()
}

export async function subscribePush(): Promise<boolean> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    throw new Error('Trình duyệt hiện tại không hỗ trợ Web Push.')
  }
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') return false

  const { public_key } = await api<{ public_key: string }>('/push/public-key')
  const reg = await navigator.serviceWorker.ready
  const existing = await reg.pushManager.getSubscription()
  const sub =
    existing ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key) as BufferSource,
    }))
  await api('/push/subscribe', { method: 'POST', body: JSON.stringify(sub.toJSON()) })
  return true
}

export async function unsubscribePush(): Promise<boolean> {
  const sub = await getCurrentPushSubscription()
  if (!sub) return false
  try {
    await api('/push/subscribe', {
      method: 'DELETE',
      body: JSON.stringify({ endpoint: sub.endpoint }),
    })
  } finally {
    await sub.unsubscribe()
  }
  return true
}
