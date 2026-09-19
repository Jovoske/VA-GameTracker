import { CaretDownIcon } from '@phosphor-icons/react/dist/csr/CaretDown'
import { type CSSProperties, type ReactNode, useId, useState } from 'react'
import { useReducedMotion } from '../hooks'

/**
 * One card on the Settings page, folded behind its heading. The species lists,
 * camera accounts and people used to stack into a screen-long scroll before the
 * password box was even in view; now each section is a row until it is wanted.
 * The choice is remembered per section on this device.
 */
const KEY = 'gs.settings.open.'

function remembered(id: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(KEY + id)
    return v == null ? fallback : v === '1'
  } catch {
    return fallback
  }
}

export default function SettingsSection({
  id,
  title,
  summary,
  defaultOpen = false,
  style,
  children,
}: {
  /** Stable key for remembering whether it is open. */
  id: string
  title: string
  /** A short status shown beside the title even when folded: "3 of 7 shown". */
  summary?: ReactNode
  defaultOpen?: boolean
  style?: CSSProperties
  children: ReactNode
}) {
  const [open, setOpen] = useState(() => remembered(id, defaultOpen))
  const reduced = useReducedMotion()
  const bodyId = useId()

  function toggle() {
    setOpen((o) => {
      try {
        localStorage.setItem(KEY + id, o ? '0' : '1')
      } catch {
        // Private mode or blocked storage: the section still folds, it just forgets.
      }
      return !o
    })
  }

  return (
    <section className="card settings-section" style={style}>
      <h2 className="sect settings-section-title">
        <button type="button" className="settings-section-head" aria-expanded={open} aria-controls={bodyId} onClick={toggle}>
          <span className="settings-section-name">{title}</span>
          {summary && <span className="sect-note">{summary}</span>}
          <CaretDownIcon
            size={16}
            aria-hidden
            style={{ flexShrink: 0, transform: open ? 'rotate(180deg)' : 'none', transition: reduced ? 'none' : 'transform .15s' }}
          />
        </button>
      </h2>
      {open && (
        <div id={bodyId} className="settings-section-body">
          {children}
        </div>
      )}
    </section>
  )
}
