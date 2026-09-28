import { CheckIcon } from '@phosphor-icons/react/dist/csr/Check'
import { GlobeIcon } from '@phosphor-icons/react/dist/csr/Globe'
import { useRef, useState } from 'react'
import { chooseLanguage, languageWaiting, saveLanguage } from '../api'
import { LANGS, type Lang, isLang, t, useLang } from '../i18n'

/**
 * The app's language: English, Suomi, Svenska, Norsk (bokmål), Español, each named
 * in itself so whoever can't read the one on screen still finds their own. It
 * changes the moment its words are here, stays on this phone, and is saved to the
 * person on the server (api.ts chooseLanguage, saveLanguage).
 *
 * The rows are never held while the server is asked: on a link that hangs, the
 * choice is already on screen and a mis-tap can be put right at once; the line
 * under them says "Saving…", then where it was saved. A language whose words won't
 * load is not kept at all, so the phone never switches to it later by itself.
 *
 * `compact`: the sign-in page's small switch, a native list the phone opens large.
 * Otherwise Settings' rows, one glove-sized row per language.
 */
export default function LanguagePicker({ compact = false }: { compact?: boolean }) {
  const current = useLang()
  // The language whose words are on their way (its row says "Loading…").
  const [loading, setLoading] = useState<Lang | null>(null)
  const [said, setSaid] = useState<{ text: string; err: boolean } | null>(null)
  // Only the latest tap speaks: an earlier one answering late says nothing.
  const picks = useRef(0)

  async function pick(code: Lang) {
    // The language on screen again: nothing to do, unless a different choice is
    // still waiting to be sent, which this one replaces.
    if (code === current && !languageWaiting()) return
    const mine = ++picks.current
    setLoading(code)
    setSaid(null)
    let shown: boolean
    try {
      shown = await chooseLanguage(code)
    } catch {
      if (mine !== picks.current) return
      setLoading(null)
      setSaid({ err: true, text: t('lang.failed') })
      return
    }
    if (mine !== picks.current) return
    setLoading(null)
    if (!shown) return
    if (!compact) setSaid({ err: false, text: t('common.saving') })
    const where = await saveLanguage(code)
    if (mine === picks.current && !compact) setSaid({ err: false, text: where === 'saved' ? t('lang.saved') : t('lang.phoneOnly') })
  }

  if (compact) {
    return (
      <div className="lang-switch">
        <label>
          <GlobeIcon size={18} aria-hidden="true" />
          <span className="sr-only">{t('lang.label')}</span>
          <select value={loading ?? current}
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
            className={`lang-row${l.code === current ? ' lang-row--on' : ''}`}
            onClick={() => void pick(l.code)}>
            <span>{l.name}</span>
            {loading === l.code ? <span className="lang-row-busy" aria-hidden="true">{t('lang.loading')}</span>
              : l.code === current ? <CheckIcon size={20} weight="bold" aria-hidden="true" /> : null}
          </button>
        ))}
      </div>
      {said && <p role={said.err ? 'alert' : 'status'} className={`lang-said${said.err ? ' lang-said--err' : ''}`}>{said.text}</p>}
    </div>
  )
}
