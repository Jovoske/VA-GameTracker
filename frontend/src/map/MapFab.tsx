import type { ReactNode } from 'react'

/**
 * One round floating map button, WeHunt-style: 48px, dark glass over the imagery,
 * a 22px line icon. The label is the accessible name and the tooltip, because an
 * icon alone doesn't say what a button does to someone who hasn't used it yet.
 *
 * `pressed` makes it a toggle (Measure, Me) so a screen reader hears on and off.
 */
export default function MapFab({ label, onClick, pressed, disabled, children, className }: {
  label: string
  onClick: () => void
  pressed?: boolean
  disabled?: boolean
  className?: string
  children: ReactNode
}) {
  return <button
    type="button"
    className={`map-fab${pressed ? ' is-on' : ''}${className ? ` ${className}` : ''}`}
    aria-label={label}
    title={label}
    aria-pressed={pressed}
    disabled={disabled}
    onClick={onClick}
  >{children}</button>
}
