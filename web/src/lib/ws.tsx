import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from './auth'
import { ALERT_TYPE_LABELS, type AlertSeverity, type ReadingPoint, type WsEvent } from './types'

export interface ToastMessage {
  id: string
  severity: AlertSeverity
  title: string
  body: string
  url?: string
  createdAt: number
}

interface WebSocketContextValue {
  connected: boolean
  toasts: ToastMessage[]
  dismissToast: (id: string) => void
  pushToast: (toast: Omit<ToastMessage, 'id' | 'createdAt'>) => void
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null)

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const { token, isAuthenticated } = useAuth()
  const queryClient = useQueryClient()
  const [connected, setConnected] = useState(false)
  const [toasts, setToasts] = useState<ToastMessage[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const pushToast = useCallback((toast: Omit<ToastMessage, 'id' | 'createdAt'>) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    setToasts((prev) => [{ ...toast, id, createdAt: Date.now() }, ...prev].slice(0, 5))
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 8000)
  }, [])

  const handleWsEvent = useCallback(
    (msg: WsEvent) => {
      const d = msg.data || {}
      switch (msg.type) {
        case 'telemetry': {
          const zoneId = String(d.zone_id || '')
          if (!zoneId) break
          const newPt: ReadingPoint = {
            ts: String(d.ts),
            air_temp: typeof d.air_temp === 'number' ? d.air_temp : null,
            air_rh: typeof d.air_rh === 'number' ? d.air_rh : null,
            vpd: typeof d.vpd === 'number' ? d.vpd : null,
            soil_moisture: typeof d.soil_moisture === 'number' ? d.soil_moisture : null,
            soil_raw: typeof d.soil_raw === 'number' ? d.soil_raw : null,
            lux: typeof d.lux === 'number' ? d.lux : null,
            quality: typeof d.quality === 'string' ? d.quality : 'ok',
            source: 'live',
          }
          queryClient.setQueriesData<ReadingPoint[]>(
            { queryKey: ['readings', zoneId] },
            (old) => {
              if (!Array.isArray(old)) return old
              if (old.some((p) => p.ts === newPt.ts)) return old
              return [...old, newPt].slice(-500)
            },
          )
          void queryClient.invalidateQueries({ queryKey: ['dli', zoneId] })
          break
        }
        case 'alert': {
          const alertType = String(d.alert_type || 'ALERT')
          const severity = (d.severity as AlertSeverity) || 'warning'
          const payload = (d.payload as Record<string, unknown> | undefined) || {}
          const state = String(d.state || 'raised')
          if (state !== 'resolved' && state !== 'acknowledged') {
            const title =
              typeof payload.title === 'string' && payload.title
                ? payload.title
                : ALERT_TYPE_LABELS[alertType] ?? alertType
            const body =
              typeof payload.body === 'string' && payload.body
                ? payload.body
                : 'Có cảnh báo mới từ hệ thống giám sát nhà kính.'
            const zoneId = typeof d.zone_id === 'string' ? d.zone_id : null
            pushToast({
              severity,
              title,
              body,
              url: zoneId ? `/zones/${zoneId}` : '/alerts',
            })
          }
          void queryClient.invalidateQueries({ queryKey: ['alerts'] })
          void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
          break
        }
        case 'command_status': {
          const ghId = String(d.greenhouse_id || '')
          if (ghId) {
            void queryClient.invalidateQueries({ queryKey: ['commands', ghId] })
          }
          void queryClient.invalidateQueries({ queryKey: ['gateway-status'] })
          break
        }
        case 'device_status': {
          void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
          void queryClient.invalidateQueries({ queryKey: ['gateway-status'] })
          if (d.event === 'node_discovered') {
            void queryClient.invalidateQueries({ queryKey: ['nodes'] })
            pushToast({
              severity: 'info',
              title: 'Phát hiện Node cảm biến mới',
              body: `MAC ${String(d.mac || '')} sẵn sàng ghép nối vào Zone.`,
              url: '/devices',
            })
          }
          break
        }
        case 'config_sync': {
          const ghId = String(d.greenhouse_id || '')
          if (ghId) {
            void queryClient.invalidateQueries({ queryKey: ['config-sync', ghId] })
          }
          void queryClient.invalidateQueries({ queryKey: ['gateway-status'] })
          break
        }
        case 'prediction': {
          if (d.task === 'yield_forecast' && d.zone_id) {
            void queryClient.invalidateQueries({ queryKey: ['predictions', String(d.zone_id)] })
          } else if (d.task === 'crop_recommendation' && d.greenhouse_id) {
            void queryClient.invalidateQueries({
              queryKey: ['recommendations', String(d.greenhouse_id)],
            })
          }
          break
        }
        case 'crop_cycle': {
          const zoneId = String(d.zone_id || '')
          if (zoneId) {
            void queryClient.invalidateQueries({ queryKey: ['cycles', zoneId] })
            void queryClient.invalidateQueries({ queryKey: ['zone', zoneId] })
          }
          void queryClient.invalidateQueries({ queryKey: ['greenhouses'] })
          break
        }
      }
    },
    [pushToast, queryClient],
  )

  useEffect(() => {
    if (!isAuthenticated || !token) {
      setConnected(false)
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      return
    }

    let cancelled = false
    let reconnectTimer: number | undefined
    let pingTimer: number | undefined
    let backoffMs = 1000

    const connect = () => {
      if (cancelled) return
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const url = `${proto}//${window.location.host}/ws?token=${encodeURIComponent(token)}`
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (cancelled) {
          ws.close()
          return
        }
        setConnected(true)
        backoffMs = 1000
        pingTimer = window.setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping')
          }
        }, 25_000)
      }

      ws.onmessage = (evt) => {
        if (evt.data === 'pong') return
        try {
          const parsed = JSON.parse(String(evt.data)) as WsEvent
          if (parsed && parsed.type) {
            handleWsEvent(parsed)
          }
        } catch {
          // bỏ qua frame không phải JSON
        }
      }

      ws.onclose = () => {
        setConnected(false)
        if (pingTimer !== undefined) window.clearInterval(pingTimer)
        if (!cancelled) {
          reconnectTimer = window.setTimeout(() => {
            backoffMs = Math.min(backoffMs * 2, 30_000)
            connect()
          }, backoffMs)
        }
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      cancelled = true
      setConnected(false)
      if (pingTimer !== undefined) window.clearInterval(pingTimer)
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer)
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [isAuthenticated, token, handleWsEvent])

  const value = useMemo<WebSocketContextValue>(
    () => ({ connected, toasts, dismissToast, pushToast }),
    [connected, toasts, dismissToast, pushToast],
  )

  return <WebSocketContext.Provider value={value}>{children}</WebSocketContext.Provider>
}

export function useRealtime(): WebSocketContextValue {
  const ctx = useContext(WebSocketContext)
  if (!ctx) throw new Error('useRealtime phải được dùng bên trong WebSocketProvider')
  return ctx
}
