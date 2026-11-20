import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { useAuth } from './auth'
import {
  ALERT_TYPE_LABELS,
  formatDateTimeVi,
  type AlertItem,
  type Greenhouse,
} from './types'

const READ_KEY_PREFIX = 'greenhub_read_alerts_'
const UNREAD_OVERRIDE_KEY_PREFIX = 'greenhub_unread_override_'

export function formatRelativeTimeVi(isoString: string | null | undefined): string {
  if (!isoString) return '—'
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return isoString
  const diffMs = Date.now() - date.getTime()
  if (diffMs < 0) return 'Vừa xong'
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return 'Vừa xong'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} phút trước`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} giờ trước`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay === 1) {
    const timeStr = date.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
    return `Hôm qua lúc ${timeStr}`
  }
  if (diffDay < 7) return `${diffDay} ngày trước`
  return formatDateTimeVi(isoString)
}

function loadIdSet(storageKey: string): Set<string> {
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? new Set(parsed) : new Set()
  } catch {
    return new Set()
  }
}

function saveIdSet(storageKey: string, set: Set<string>) {
  try {
    // Lưu tối đa 500 ID gần nhất để tránh localStorage quá tải
    const list = Array.from(set).slice(-500)
    localStorage.setItem(storageKey, JSON.stringify(list))
  } catch {
    // Bỏ qua lỗi hạn ngạch storage nếu có
  }
}

export interface FormattedNotification {
  id: string
  title: string
  body: string
  location: string
  targetUrl: string
  relativeTime: string
  formattedTime: string
  severity: 'critical' | 'warning' | 'info'
  isRead: boolean
  rawAlert: AlertItem
}

export function useNotifications() {
  const { isAuthenticated, user } = useAuth()
  const queryClient = useQueryClient()

  const userKey = user?.id || 'guest'
  const readStorageKey = `${READ_KEY_PREFIX}${userKey}`
  const unreadStorageKey = `${UNREAD_OVERRIDE_KEY_PREFIX}${userKey}`

  const [readIds, setReadIds] = useState<Set<string>>(() => loadIdSet(readStorageKey))
  const [unreadOverrides, setUnreadOverrides] = useState<Set<string>>(() => loadIdSet(unreadStorageKey))

  // Đồng bộ lại khi đổi tài khoản đăng nhập
  useEffect(() => {
    setReadIds(loadIdSet(readStorageKey))
    setUnreadOverrides(loadIdSet(unreadStorageKey))
  }, [readStorageKey, unreadStorageKey])

  // Lấy toàn bộ danh sách cảnh báo (không phân chia trạng thái)
  const alertsQuery = useQuery({
    queryKey: ['alerts', 'all'],
    queryFn: () => api<AlertItem[]>('/alerts?limit=250'),
    enabled: isAuthenticated,
    refetchInterval: 15_000,
  })

  // Lấy thông tin nhà kính để ánh xạ vị trí
  const greenhousesQuery = useQuery({
    queryKey: ['greenhouses'],
    queryFn: () => api<Greenhouse[]>('/greenhouses'),
    enabled: isAuthenticated,
  })

  const greenhouses = greenhousesQuery.data ?? []
  const ghById = useMemo(() => new Map(greenhouses.map((g) => [g.id, g])), [greenhouses])
  const zoneById = useMemo(
    () => new Map(greenhouses.flatMap((g) => g.zones).map((z) => [z.id, z])),
    [greenhouses],
  )

  const isRead = useCallback(
    (alert: AlertItem): boolean => {
      if (unreadOverrides.has(alert.id)) return false
      if (readIds.has(alert.id)) return true
      if (alert.state === 'acknowledged' || alert.state === 'resolved') return true
      return false
    },
    [readIds, unreadOverrides],
  )

  const ackSingleMutation = useMutation({
    mutationFn: (alertId: string) =>
      api<AlertItem>(`/alerts/${alertId}/ack`, { method: 'POST' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alerts'] })
    },
  })

  const ackAllMutation = useMutation({
    mutationFn: () =>
      api<{ acknowledged_count: number }>('/alerts/ack-all', { method: 'POST' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alerts'] })
    },
  })

  const markAsRead = useCallback(
    (alertId: string) => {
      setReadIds((prev) => {
        const next = new Set(prev)
        next.add(alertId)
        saveIdSet(readStorageKey, next)
        return next
      })
      setUnreadOverrides((prev) => {
        if (!prev.has(alertId)) return prev
        const next = new Set(prev)
        next.delete(alertId)
        saveIdSet(unreadStorageKey, next)
        return next
      })

      // Gửi ACK lên server để tắt còi và đánh dấu đã xử lý
      const targetAlert = alertsQuery.data?.find((a) => a.id === alertId)
      if (targetAlert && (targetAlert.state === 'raised' || targetAlert.state === 'notified')) {
        ackSingleMutation.mutate(alertId)
      }
    },
    [readStorageKey, unreadStorageKey, alertsQuery.data, ackSingleMutation],
  )

  const markAsUnread = useCallback(
    (alertId: string) => {
      setUnreadOverrides((prev) => {
        const next = new Set(prev)
        next.add(alertId)
        saveIdSet(unreadStorageKey, next)
        return next
      })
      setReadIds((prev) => {
        if (!prev.has(alertId)) return prev
        const next = new Set(prev)
        next.delete(alertId)
        saveIdSet(readStorageKey, next)
        return next
      })
    },
    [readStorageKey, unreadStorageKey],
  )

  const markAllAsRead = useCallback(() => {
    const allAlerts = alertsQuery.data ?? []
    const nextRead = new Set(readIds)
    for (const a of allAlerts) {
      nextRead.add(a.id)
    }
    setReadIds(nextRead)
    saveIdSet(readStorageKey, nextRead)

    const nextUnread = new Set<string>()
    setUnreadOverrides(nextUnread)
    saveIdSet(unreadStorageKey, nextUnread)

    if (isAuthenticated) {
      ackAllMutation.mutate()
    }
  }, [alertsQuery.data, readIds, readStorageKey, unreadStorageKey, isAuthenticated, ackAllMutation])

  // Định dạng danh sách thông báo hoàn chỉnh
  const formattedNotifications: FormattedNotification[] = useMemo(() => {
    const rawAlerts = alertsQuery.data ?? []
    return rawAlerts.map((alt) => {
      const gh = ghById.get(alt.greenhouse_id)
      const zone = alt.zone_id ? zoneById.get(alt.zone_id) : undefined
      const payload = alt.payload ?? {}

      const title =
        typeof payload.title === 'string' && payload.title.trim()
          ? payload.title.trim()
          : ALERT_TYPE_LABELS[alt.alert_type] ?? alt.alert_type

      const bodyText = typeof payload.body === 'string' && payload.body.trim() ? payload.body.trim() : ''

      const locParts: string[] = []
      if (gh?.name) locParts.push(gh.name)
      if (zone?.name) {
        locParts.push(zone.name)
      } else if (zone?.zone_index) {
        locParts.push(`Zone ${zone.zone_index}`)
      }
      const location = locParts.join(' • ')

      // Tạo một nội dung thông báo liền mạch, tự nhiên
      let combinedBody = bodyText
      if (location) {
        combinedBody = combinedBody ? `${combinedBody} tại ${location}.` : `Phát sinh tại ${location}.`
      } else if (!combinedBody) {
        combinedBody = 'Hệ thống ghi nhận sự kiện cảnh báo cần lưu ý.'
      }

      const targetUrl = zone
        ? `/zones/${zone.id}`
        : gh
          ? `/greenhouses/${gh.id}`
          : '/alerts'

      const sev: 'critical' | 'warning' | 'info' =
        alt.severity === 'critical' || alt.severity === 'warning' ? alt.severity : 'info'

      return {
        id: alt.id,
        title,
        body: combinedBody,
        location,
        targetUrl,
        relativeTime: formatRelativeTimeVi(alt.created_at),
        formattedTime: formatDateTimeVi(alt.created_at),
        severity: sev,
        isRead: isRead(alt),
        rawAlert: alt,
      }
    })
  }, [alertsQuery.data, ghById, zoneById, isRead])

  const unreadCount = useMemo(() => {
    return formattedNotifications.filter((n) => !n.isRead).length
  }, [formattedNotifications])

  return {
    notifications: formattedNotifications,
    unreadCount,
    isLoading: alertsQuery.isLoading,
    isError: alertsQuery.isError,
    error: alertsQuery.error,
    isRead,
    markAsRead,
    markAsUnread,
    markAllAsRead,
    refetch: alertsQuery.refetch,
  }
}
