type Props = {
  on: boolean
  onChange: () => void
  label: string
  disabled?: boolean
}

/**
 * The one switch the app uses, so every on/off row in Settings moves the same way.
 *
 * A real switch role rather than a pressed button: a screen reader says "on" or
 * "off", which is what the row means. The knob moves on `transform`, so it rides
 * the compositor instead of forcing layout on every frame.
 */
export default function Toggle({ on, onChange, label, disabled }: Props) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      title={label}
      onClick={onChange}
      disabled={disabled}
      style={{
        width: 46,
        height: 26,
        borderRadius: 'var(--r-card)',
        border: 'none',
        cursor: disabled ? 'default' : 'pointer',
        background: on ? 'var(--go)' : 'var(--surface-2)',
        position: 'relative',
        transition: 'background var(--d-base) var(--ease-out)',
        flexShrink: 0,
        opacity: disabled ? 0.6 : 1,
        padding: 0,
      }}
    >
      <span
        style={{
          position: 'absolute',
          top: 3,
          left: 3,
          width: 20,
          height: 20,
          borderRadius: '50%',
          background: '#fff',
          transform: on ? 'translateX(20px)' : 'translateX(0)',
          transition: 'transform var(--d-base) var(--ease-out)',
        }}
      />
    </button>
  )
}
