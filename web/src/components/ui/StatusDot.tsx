import type { CSSProperties, ReactNode } from 'react'

export type StatusDotVariant = 'ok' | 'offline' | 'unallocated' | 'warning'

export interface StatusDotProps {
  status?: StatusDotVariant
  color?: string
  textColor?: string
  children?: ReactNode
  label?: ReactNode
  className?: string
  style?: CSSProperties
}

const STATUS_COLORS: Record<StatusDotVariant, string> = {
  ok: 'var(--status-ok, #2E9A62)',
  offline: 'var(--status-offline, #B94A32)',
  unallocated: 'var(--status-unallocated, #B7B3A6)',
  warning: 'var(--status-warning, #D97706)',
}

export function StatusDot({
  status = 'ok',
  color,
  textColor,
  children,
  label,
  className = '',
  style,
}: StatusDotProps) {
  const dotColor = color || STATUS_COLORS[status] || STATUS_COLORS.ok
  const content = label ?? children
  const computedTextColor = textColor || (status === 'unallocated' ? 'var(--text-muted, #626861)' : 'var(--text-main, #1C211E)')

  return (
    <span
      className={`status-dot ${className}`.trim()}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        fontSize: '0.82rem',
        color: computedTextColor,
        fontVariantNumeric: 'tabular-nums',
        ...style,
      }}
    >
      <span
        style={{
          width: '8px',
          height: '8px',
          borderRadius: '50%',
          backgroundColor: dotColor,
          flexShrink: 0,
          display: 'inline-block',
        }}
        aria-hidden="true"
      />
      {content && <span>{content}</span>}
    </span>
  )
}

export default StatusDot
