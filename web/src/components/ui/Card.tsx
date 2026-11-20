import { forwardRef, type HTMLAttributes, type ReactNode } from 'react'

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  interactive?: boolean
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { children, interactive = false, className = '', style, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={`card ${interactive ? 'card-interactive' : ''} ${className}`.trim()}
      style={{
        background: 'var(--surface-card, #FFFFFF)',
        border: '1px solid var(--border-card, #E6E3DA)',
        borderRadius: 'var(--radius-card, 10px)',
        padding: '1.25rem',
        boxShadow: 'none',
        cursor: interactive ? 'pointer' : undefined,
        transition: interactive ? 'background-color 0.15s ease' : undefined,
        boxSizing: 'border-box',
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  )
})

export default Card
