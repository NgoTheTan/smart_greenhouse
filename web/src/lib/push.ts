// Đăng ký Web Push - PHẢI gọi từ cú bấm của người dùng (spec 10).
import { api } from './api'

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const raw = atob((base64 + padding).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

export async function subscribePush(): Promise<boolean> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return false
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') return false

  const { public_key } = await api<{ public_key: string }>('/push/public-key')
  const reg = await navigator.serviceWorker.ready
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(public_key) as BufferSource,
  })
  await api('/push/subscribe', { method: 'POST', body: JSON.stringify(sub.toJSON()) })
  return true
}

