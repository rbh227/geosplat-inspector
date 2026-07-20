import { forwardRef } from 'react'
import { cn } from '../lib/utils'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'icon'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
}

/* ------------------------------------------------------------------ */
/*  Variant styles                                                     */
/* ------------------------------------------------------------------ */

const base = [
  'inline-flex items-center justify-center gap-2',
  'font-medium select-none cursor-pointer',
  'transition-colors duration-150',
  'focus-ring',                         // visible focus-visible ring from CSS
  'disabled:opacity-40 disabled:pointer-events-none',
].join(' ')

const variants: Record<ButtonVariant, string> = {
  // Tactile amber phosphor key — gradient face, inset highlight, warm halo.
  // All visual treatment lives in the .btn-phosphor utility (index.css).
  primary: 'btn-phosphor font-semibold',

  secondary: [
    'bg-bg-elevated text-text-secondary border border-border-subtle',
    'hover:bg-bg-hover hover:text-text-primary hover:border-border-active',
    'active:bg-bg-hover',
  ].join(' '),

  ghost: [
    'bg-transparent text-text-secondary border border-transparent',
    'hover:bg-bg-hover hover:text-text-primary',
    'active:bg-bg-hover',
  ].join(' '),

  danger: [
    'bg-accent-red/10 text-accent-red border border-accent-red/25',
    'hover:bg-accent-red/20 hover:border-accent-red/40',
    'active:bg-accent-red/25',
  ].join(' '),

  icon: [
    'bg-transparent text-text-secondary border border-transparent',
    'hover:bg-bg-hover hover:text-text-primary',
    'active:bg-bg-hover',
    'p-0',                              // sizing handled below
  ].join(' '),
}

const sizes: Record<ButtonSize, string> = {
  sm: 'text-xs rounded-[var(--radius-sm)] px-2 py-1 h-7',
  md: 'text-xs rounded-[var(--radius-md)] px-3 py-1.5 h-8',
  lg: 'text-sm rounded-[var(--radius-md)] px-4 py-2 h-9',
}

const iconSizes: Record<ButtonSize, string> = {
  sm: 'w-7 h-7 rounded-[var(--radius-sm)]',
  md: 'w-8 h-8 rounded-[var(--radius-md)]',
  lg: 'w-9 h-9 rounded-[var(--radius-md)]',
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    { variant = 'secondary', size = 'md', loading, className, children, disabled, ...rest },
    ref,
  ) {
    const isIcon = variant === 'icon'
    const sizeClass = isIcon ? iconSizes[size] : sizes[size]

    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(base, variants[variant], sizeClass, className)}
        {...rest}
      >
        {loading ? (
          <span
            className="inline-block w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin"
            aria-hidden="true"
          />
        ) : (
          children
        )}
      </button>
    )
  },
)

export default Button
