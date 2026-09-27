import { CheckIcon } from '@phosphor-icons/react/dist/csr/Check'
import { GlobeIcon } from '@phosphor-icons/react/dist/csr/Globe'
import { useState } from 'react'
import { chooseLanguage } from '../api'
import { LANGS, type Lang, isLang, t, useLang } from '../i18n'

/**
 * The app's language: English, Suomi, Svenska, Norsk (bokmål), Español, each named
 * in itself so whoever can't read the one on screen still finds their own. It
 * changes the moment it is tapped, stays on this phone, and is saved to the person
 * on the server (api.ts chooseLanguage).
 *
 * `compact`: the sign-in page's small switch, a native list the phone opens large.
 * Otherwise Settings' rows, one glove-sized row per language.
 */
export default function LanguagePicker({ compact = false }: { compact?: boolean }) {
  const current = useLang()
  const [busy, setBusy] = useState<Lang | null>(null)
  const [said, setSaid] = useState<{ text: string; err: boolean } | null>(null)

  async function pick(code: Lang) {
    if (code === current || busy) return
    setBusy(code)
    setSaid(null)
    try {
      const where = await chooseLanguage(code)
      if (!compact) setSaid({ err: false, text: where === 'saved' ? t('lang.saved') : t('lang.phoneOnly') })
    } catch {
      setSaid({ err: true, text: t('lang.failed') })
    } finally {
      setBusy(null)
    }
  }

  if (compact) {
    return (
      <div className="lang-switch">
        <label>
          <GlobeIcon size={18} aria-hidden="true" />
          <span className="sr-only">{t('lang.label')}</span>
          <select value={busy ?? current} disabled={busy != null}
            onChange={(e) => { if (isLang(e.target.value)) void pick(e.target.value) }}>
            {LANGS.map((l) => <option key={l.code} value={l.code} lang={l.code}>{l.name}</option>)}
          </select>
        </label>
        {said?.err && <p role="alert" className="lang-said lang-said--err">{said.text}</p>}
      </div>
    )
  }

  return (
    <div className="lang-picker">
      <div role="radiogroup" aria-label={t('lang.label')} className="lang-rows">
        {LANGS.map((l) => (
          <button key={l.code} type="button" role="radio" aria-checked={l.code === current} lang={l.code}
            className={`lang-row${l.code === current ? ' lang-row--on' : ''}`} disabled={busy != null}
            onClick={() => void pick(l.code)}>
            <span>{l.name}</span>
            {busy === l.code ? <span className="lang-row-busy" aria-hidden="true">{t('lang.loading')}</span>
              : l.code === current ? <CheckIcon size={20} weight="bold" aria-hidden="true" /> : null}
          </button>
        ))}
      </div>
      {said && <p role={said.err ? 'alert' : 'status'} className={`lang-said${said.err ? ' lang-said--err' : ''}`}>{said.text}</p>}
    </div>
  )
}
