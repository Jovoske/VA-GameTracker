import { useCallback, useEffect, useRef, useState } from 'react'
import { type Failure, api, getToken, peek, plainWords } from '../api'
import { type Key, cap, fmtDate, fmtNumber, t } from '../i18n'
import { HarvestForm, type HarvestLine, lineWords } from './Harvest'
import SettingsSection from './SettingsSection'

/**
 * Settings → the harvest book. An admin sees the season's lines, everyone's, logs
 * one by hand (a driven hunt, a guest's animal) and downloads the season as a CSV
 * for the annual return. A member sees and changes their own. Viewers have nothing
 * here. Just the lines, newest first: no tallies, no ranking.
 */

type Book = {
  season: number
  label: string
  from: string
  to: string
  seasons: { season: number; label: string }[]
  items: HarvestLine[]
  can_export: boolean
}

const when = (iso: string) => fmtDate(iso, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const day = (isoDate: string) => fmtDate(`${isoDate}T12:00:00Z`, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

function failed(e: unknown, what: Key): string {
  const x = e as Failure
  if (x.offline) return t('book.failNoSignal', { what: t(what) })
  if (x.timeout) return t('book.failTimeout', { what: t(what) })
  return t('harvest.failOther', { reason: plainWords(x.message || t('common.wentWrong')), what: cap(t(what)) })
}

/** Save the season's CSV. A plain link can't carry the sign-in, so it is fetched and
 *  handed to the browser as a file. */
async function downloadSeason(season: number): Promise<void> {
  const ctl = new AbortController()
  const timer = window.setTimeout(() => ctl.abort(), 30_000)
  let resp: Response
  try {
    resp = await fetch(`/api/harvests/export.csv?season=${season}`, {
      headers: { Authorization: `Bearer ${getToken() ?? ''}` }, signal: ctl.signal,
    })
  } catch {
    throw Object.assign(new Error(ctl.signal.aborted ? t('api.noAnswer') : t('api.noSignalShort')),
      ctl.signal.aborted ? { timeout: true } : { offline: true })
  } finally {
    window.clearTimeout(timer)
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}))
    throw Object.assign(new Error(typeof body?.detail === 'string' ? body.detail : t('api.wentWrong', { status: resp.status })),
      { status: resp.status })
  }
  const blob = await resp.blob()
  const name = /filename="([^"]+)"/.exec(resp.headers.get('Content-Disposition') ?? '')?.[1] ?? `harvest-${season}.csv`
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000)
}

export default function HarvestBook({ admin }: { admin: boolean }) {
  const [season, setSeason] = useState<number | null>(null)
  const path = season == null ? '/harvests' : `/harvests?season=${season}`
  const [book, setBook] = useState<Book | null>(() => peek<Book>('/harvests')?.data ?? null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState<{ line?: HarvestLine } | null>(null)
  const [stands, setStands] = useState<{ id: string; name: string }[]>([])
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const ctl = useRef<AbortController | null>(null)

  const load = useCallback(() => {
    ctl.current?.abort()
    const c = new AbortController()
    ctl.current = c
    setErr('')
    api<Book>(path, { signal: c.signal, timeoutMs: 20_000 })
      .then((b) => { if (!c.signal.aborted) setBook(b) })
      .catch((e) => { if (!c.signal.aborted && (e as Error).name !== 'AbortError') setErr(failed(e, 'book.what.didntLoad')) })
  }, [path])
  useEffect(() => {
    load()
    return () => ctl.current?.abort()
  }, [load])
  useEffect(() => {
    api<{ id: string; name: string }[]>('/stands', { timeoutMs: 20_000 }).then(setStands).catch(() => {})
  }, [])

  async function exportCsv() {
    if (!book || busy) return
    setBusy(true)
    setNote('')
    try {
      await downloadSeason(book.season)
      setNote(t('book.downloading', { season: book.label }))
    } catch (e) {
      setNote(failed(e, 'book.what.noDownload'))
    } finally {
      setBusy(false)
    }
  }

  const title = admin ? t('book.title') : t('book.yours')
  return (
    <SettingsSection id="harvest" title={title} summary={book ? t('book.season', { season: book.label }) : undefined}>
      <div className="hv-book-tools">
        {book && book.seasons.length > 1 && (
          <select className="input" aria-label={t('book.seasonLabel')} value={book.season}
            onChange={(e) => setSeason(Number(e.target.value))}>
            {book.seasons.map((s) => <option key={s.season} value={s.season}>{s.label}</option>)}
          </select>
        )}
        <button type="button" className="hv-tool" onClick={() => setOpen({})}>{t('book.logOne')}</button>
        {book?.can_export && (
          <button type="button" className="hv-tool" onClick={exportCsv} disabled={busy}>
            {busy ? t('book.downloadingShort') : t('book.download')}
          </button>
        )}
      </div>
      {note && <p className="hv-season-note" role="status">{note}</p>}
      {err && <p className="hv-err" role="alert">{err} <button type="button" className="hv-link" onClick={load}>{t('common.tryAgain')}</button></p>}
      {!book && !err && <p className="hv-dim" role="status">{t('common.loading')}</p>}
      {book && book.items.length === 0 && (
        <p className="hv-dim">{t('book.empty', { season: book.label })}</p>
      )}
      {book && book.items.length > 0 && (
        <ul className="hv-lines">
          {book.items.map((h) => (
            <li key={h.id}>
              <button type="button" className="hv-line" disabled={!h.can_edit} onClick={() => setOpen({ line: h })}
                aria-label={`${lineWords(h)}, ${when(h.taken_at)}${h.can_edit ? `. ${t('harvest.changeIt')}` : ''}`}>
                <b>{lineWords(h)}</b>
                <span>{[when(h.taken_at), admin || !h.yours ? h.hunter : null, h.stand, h.weight_kg != null ? `${fmtNumber(h.weight_kg)} kg` : null]
                  .filter(Boolean).join(' · ')}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {book && (
        <p className="hv-season-note">
          {t('book.runs', { season: book.label, from: day(book.from), to: day(book.to) })}
          {book.can_export ? ` ${t('book.excel')}` : ''}
        </p>
      )}
      {open && (
        <HarvestForm
          line={open.line}
          stands={stands}
          onClose={() => setOpen(null)}
          onSaved={() => load()}
          onDeleted={() => load()}
        />
      )}
    </SettingsSection>
  )
}
