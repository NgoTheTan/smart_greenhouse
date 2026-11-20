import type { TableHTMLAttributes, ReactNode, ThHTMLAttributes, TdHTMLAttributes } from 'react'

export interface DataTableProps extends TableHTMLAttributes<HTMLTableElement> {
  children: ReactNode
  containerClassName?: string
  containerStyle?: React.CSSProperties
}

export function DataTable({
  children,
  containerClassName = '',
  containerStyle,
  className = '',
  style,
  ...rest
}: DataTableProps) {
  return (
    <div
      className={`table-container ${containerClassName}`.trim()}
      style={{
        overflowX: 'auto',
        border: '1px solid var(--border-card, #E6E3DA)',
        borderRadius: 'var(--radius-card, 10px)',
        background: 'var(--surface-card, #FFFFFF)',
        ...containerStyle,
      }}
    >
      <table
        className={className}
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: '0.875rem',
          textAlign: 'left',
          fontVariantNumeric: 'tabular-nums',
          ...style,
        }}
        {...rest}
      >
        {children}
      </table>
    </div>
  )
}

export function TableHead({ children, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      style={{
        padding: '10px 14px',
        fontWeight: 500,
        color: 'var(--text-muted, #626861)',
        borderBottom: '1px solid var(--border-row, #EEECE5)',
        textTransform: 'none',
        fontSize: '12px',
        letterSpacing: 0,
        whiteSpace: 'nowrap',
        background: 'transparent',
      }}
      {...rest}
    >
      {children}
    </th>
  )
}

export function TableCell({ children, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      style={{
        padding: '12px 14px',
        borderBottom: '1px solid var(--border-row, #EEECE5)',
        color: 'var(--text-main, #1C211E)',
        verticalAlign: 'middle',
      }}
      {...rest}
    >
      {children}
    </td>
  )
}

export default DataTable
