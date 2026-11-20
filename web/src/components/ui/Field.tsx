import {
  forwardRef,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react'

export interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  label?: ReactNode
  unit?: string
  error?: string
  hint?: string
  containerStyle?: React.CSSProperties
  inputStyle?: React.CSSProperties
}

export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field(
  {
    label,
    unit,
    error,
    hint,
    containerStyle,
    inputStyle,
    className = '',
    style,
    id,
    disabled,
    ...rest
  },
  ref,
) {
  const generatedId = id || (typeof label === 'string' ? label.toLowerCase().replace(/\s+/g, '-') : undefined)

  return (
    <div className={`form-group ${className}`.trim()} style={{ marginBottom: '1rem', ...containerStyle }}>
      {label && (
        <label
          htmlFor={generatedId}
          style={{
            display: 'block',
            fontSize: '0.82rem',
            fontWeight: 500,
            color: 'var(--text-muted, #626861)',
            marginBottom: '0.35rem',
          }}
        >
          {label}
        </label>
      )}

      {/* Input container với đơn vị nằm bên trong */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          minHeight: '44px',
          border: `1px solid ${error ? 'var(--status-offline, #B94A32)' : 'var(--border-input, #D9D6CB)'}`,
          borderRadius: 'var(--radius-input, 6px)',
          backgroundColor: disabled ? '#F5F4EF' : 'var(--surface-card, #FFFFFF)',
          padding: '0 12px',
          transition: 'border-color 0.15s ease',
          boxSizing: 'border-box',
          ...style,
        }}
        onFocus={(e) => {
          if (!disabled) {
            e.currentTarget.style.borderColor = 'var(--accent, #1E6B47)'
          }
        }}
        onBlur={(e) => {
          if (!disabled) {
            e.currentTarget.style.borderColor = error
              ? 'var(--status-offline, #B94A32)'
              : 'var(--border-input, #D9D6CB)'
          }
        }}
      >
        <input
          ref={ref}
          id={generatedId}
          disabled={disabled}
          style={{
            flex: 1,
            minWidth: 0,
            border: 'none',
            outline: 'none',
            background: 'transparent',
            padding: 0,
            fontSize: '0.88rem',
            fontFamily: 'var(--font-ui)',
            color: 'var(--text-main, #1C211E)',
            fontVariantNumeric: 'tabular-nums',
            height: '100%',
            ...inputStyle,
          }}
          {...rest}
        />

        {unit && (
          <span
            style={{
              color: 'var(--text-muted, #626861)',
              fontSize: '0.82rem',
              marginLeft: '8px',
              userSelect: 'none',
              pointerEvents: 'none',
              flexShrink: 0,
            }}
          >
            {unit}
          </span>
        )}
      </div>

      {hint && !error && (
        <span style={{ display: 'block', fontSize: '0.76rem', color: 'var(--text-muted, #626861)', marginTop: '0.25rem' }}>
          {hint}
        </span>
      )}

      {error && (
        <span style={{ display: 'block', fontSize: '0.76rem', color: 'var(--status-offline, #B94A32)', marginTop: '0.25rem' }}>
          {error}
        </span>
      )}
    </div>
  )
})

export interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: ReactNode
  error?: string
  hint?: string
  containerStyle?: React.CSSProperties
}

export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(function SelectField(
  { label, error, hint, containerStyle, className = '', id, disabled, children, ...rest },
  ref,
) {
  const generatedId = id || (typeof label === 'string' ? label.toLowerCase().replace(/\s+/g, '-') : undefined)

  return (
    <div className={`form-group ${className}`.trim()} style={{ marginBottom: '1rem', ...containerStyle }}>
      {label && (
        <label
          htmlFor={generatedId}
          style={{
            display: 'block',
            fontSize: '0.82rem',
            fontWeight: 500,
            color: 'var(--text-muted, #626861)',
            marginBottom: '0.35rem',
          }}
        >
          {label}
        </label>
      )}

      <select
        ref={ref}
        id={generatedId}
        disabled={disabled}
        style={{
          width: '100%',
          minHeight: '44px',
          border: `1px solid ${error ? 'var(--status-offline, #B94A32)' : 'var(--border-input, #D9D6CB)'}`,
          borderRadius: 'var(--radius-input, 6px)',
          backgroundColor: disabled ? '#F5F4EF' : 'var(--surface-card, #FFFFFF)',
          padding: '0 12px',
          fontSize: '0.88rem',
          fontFamily: 'var(--font-ui)',
          color: 'var(--text-main, #1C211E)',
          outline: 'none',
          boxSizing: 'border-box',
          cursor: disabled ? 'not-allowed' : 'pointer',
        }}
        {...rest}
      >
        {children}
      </select>

      {hint && !error && (
        <span style={{ display: 'block', fontSize: '0.76rem', color: 'var(--text-muted, #626861)', marginTop: '0.25rem' }}>
          {hint}
        </span>
      )}

      {error && (
        <span style={{ display: 'block', fontSize: '0.76rem', color: 'var(--status-offline, #B94A32)', marginTop: '0.25rem' }}>
          {error}
        </span>
      )}
    </div>
  )
})

export default Field
