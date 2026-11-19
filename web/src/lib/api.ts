// Client REST: base /api, gắn JWT từ localStorage và xử lý 401.
const BASE = '/api'
const TOKEN_KEY = 'gh_token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t: string | null) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY)

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(`API ${status}`)
  }
}

export function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) {
      return 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.'
    }
    if (err.status === 403) {
      return 'Bạn không có quyền thực hiện thao tác này.'
    }
    if (typeof err.body === 'object' && err.body !== null && 'detail' in err.body) {
      const detail = (err.body as { detail: unknown }).detail
      if (detail === 'gateway_offline') {
        return 'Gateway đang offline, không thể gửi lệnh.'
      }
      if (detail === 'zone_already_has_active_cycle') {
        return 'Zone này đang có vụ trồng đang chạy. Hãy thu hoạch hoặc huỷ vụ trước.'
      }
      if (detail === 'cycle_not_active') {
        return 'Vụ trồng không còn ở trạng thái đang hoạt động.'
      }
      if (typeof detail === 'string') return detail
      if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0] as { msg?: string }
        if (first?.msg) return first.msg
      }
    }
    if (typeof err.body === 'string' && err.body) return err.body
    return `Lỗi máy chủ (HTTP ${err.status}).`
  }
  if (err instanceof Error) return err.message
  return 'Đã xảy ra lỗi không xác định.'
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  const isJson = res.headers.get('content-type')?.includes('json')
  const body = isJson ? await res.json() : await res.text()

  if (!res.ok) {
    if (res.status === 401 && !path.startsWith('/auth/login')) {
      setToken(null)
      window.dispatchEvent(new CustomEvent('gh:unauthorized'))
    }
    throw new ApiError(res.status, body)
  }
  return body as T
}
