import type { ReactNode } from 'react'

/**
 * A whole row that is the switch, so the target is the row and not a 26px pill:
 * glove-sized, and it says On or Off in words beside the knob. A real switch role,
 * so a screen reader says "on" or "off" too.
 */
export default function SwitchRow({ label, note, on, onChange, disabled, words = ['On', 'Off'] }: {
  label: ReactNode
  note?: ReactNode
  on: boolean
  onChange: (on: boolean) => void
  disabled?: boolean
  /** What the row says for on and off. */
  words?: [string, string]
}) {
  return (
    <button type="button" role="switch" aria-checked={on} className="switch-row" disabled={disabled} onClick={() => onChange(!on)}>
      <span className="switch-row-text"><span>{label}</span>{note && <small>{note}</small>}</span>
      <span className="switch-row-word" aria-hidden="true">{on ? words[0] : words[1]}</span>
      <span className="switch-row-knob" aria-hidden="true"><span /></span>
    </button>
  )
}
