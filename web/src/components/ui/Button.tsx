import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger'
  size?: 'default' | 'sm'
  children: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'default', children, className = '', style, ...rest },
  ref,
) {
  const isSm = size === 'sm'

  const baseStyle: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.45rem',
    minHeight: isSm ? '36px' : '44px',
    height: isSm ? '36px' : '44px',
    padding: isSm ? '0 12px' : '0 18px',
    fontSize: isSm ? '13px' : '14px',
    fontWeight: isSm ? 500 : 600,
    fontFamily: 'var(--font-ui)',
    borderRadius: 'var(--radius-btn, 8px)',
    cursor: rest.disabled ? 'not-allowed' : 'pointer',
    opacity: rest.disabled ? 0.55 : 1,
    boxShadow: 'none',
    transition: 'background-color 0.15s ease, border-color 0.15s ease',
    boxSizing: 'border-box',
    ...style,
  }

  let variantStyle: React.CSSProperties = {}
  if (variant === 'primary') {
    variantStyle = {
      backgroundColor: 'var(--accent, #1E6B47)',
      color: '#FFFFFF',
      border: '1px solid var(--accent, #1E6B47)',
    }
  } else if (variant === 'secondary') {
    variantStyle = {
      backgroundColor: 'var(--surface-card, #FFFFFF)',
      color: 'var(--text-main, #1C211E)',
      border: '1px solid var(--border-input, #D9D6CB)',
    }
  } else if (variant === 'danger') {
    variantStyle = {
      backgroundColor: 'var(--surface-card, #FFFFFF)',
      color: 'var(--status-offline, #B94A32)',
      border: '1px solid var(--status-offline, #B94A32)',
    }
  }

  return (
    <button
      ref={ref}
      className={`btn btn-${variant} ${isSm ? 'btn-sm' : ''} ${className}`.trim()}
      style={{ ...baseStyle, ...variantStyle }}
      {...rest}
    >
      {children}
    </button>
  )
})

export default Button
