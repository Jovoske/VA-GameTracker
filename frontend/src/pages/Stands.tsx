import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { flushSitQueue } from './SitMode'

/**
 * Stands — claim one for tonight, then report what came of it.
 *
 * The claim is the point. It is written before the sit, when the phone is out and
 * hands are clean, and it exists because claiming has a payoff for the person doing
 * it: the wind verdict and the answer to "is anyone else on that ridge". Whether or
 * not anyone ever reports an outcome, that row makes hunting pressure measurable.
 *
 * Outcome buttons are large and few. This gets tapped in the dark, in gloves.
 */

type Stand = {
  id: string
  name: string
  approach_dirs_deg: number[] | null
  shooting_dirs_deg: number[] | null
  has_geometry: boolean
  claimed_tonight: boolean
  claimed_by: string | null
}
type Sit = {
  id: string
  stand_id: string
  stand: string | null
  outcome: string
  started_at: string | null
  wind_status: string | null
  wind_text: string | null
}
type Me = { id: string; role: string }

const btn = {
  background: 'var(--surface-2)',
  color: 'var(--text)',
  border: '1px solid var(--border)',
  borderRadius: 10,
  padding: '12px 14px',
  fontSize: 14,
  cursor: 'pointer',
  minHeight: 48,
} as const

const OUTCOMES: [string, string][] = [
  ['nothing', 'Nothing'],
  ['seen', 'Seen'],
  ['shootable_no_shot', 'Shootable, no shot'],
  ['shot', 'Shot'],
]

export default function Stands() {
  const nav = useNavigate()
  const [stands, setStands] = useState<Stand[] | null>(null)
  const [sits, setSits] = useState<Sit[]>([])
  const [me, setMe] = useState<Me | null>(null)
  const [msg, setMsg] = useState('')
  const [newName, setNewName] = useState('')

  async function load() {
    try {
      setMe(await api<Me>('/users/me'))
      setStands(await api<Stand[]>('/stands'))
      setSits(await api<Sit[]>('/sits'))
    } catch (e) {
      setMsg((e as Error).message)
      setStands([])
    }
  }

  useEffect(() => {
    // Drain anything Sit Mode recorded while out of signal — and say how much
    // came through. A queue that empties silently is indistinguishable from one
    // that lost the night, which is the one thing this app cannot afford to be
    // ambiguous about.
    flushSitQueue()
      .then((n) => {
        if (n > 0) setMsg(`${n} sit${n === 1 ? '' : 's'} from the valley are in.`)
      })
      .finally(load)
  }, [])

  async function run(fn: () => Promise<unknown>, ok = '') {
    setMsg('')
    try {
      await fn()
      if (ok) setMsg(ok)
      await load()
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  async function bootstrap() {
    await run(async () => {
      const r = await api<{ created: string[]; note: string }>('/stands/bootstrap', {
        method: 'POST',
      })
      setMsg(
        r.created.length
          ? `Created ${r.created.length} stand${r.created.length === 1 ? '' : 's'}. ${r.note}`
          : 'Every camera already has a stand.',
      )
    })
  }

  if (!stands) return <div style={{ color: 'var(--text-dim)' }}>Loading…</div>

  const sitFor = (standId: string) => sits.find((s) => s.stand_id === standId)

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 12 }}>Stands</div>

      {msg && (
        <div
          onClick={() => setMsg('')}
          className="card"
          style={{ padding: '10px 14px', marginBottom: 14, fontSize: 13, cursor: 'pointer' }}
        >
          {msg}
        </div>
      )}

      {stands.length === 0 && (
        <div className="card" style={{ padding: 18, marginBottom: 14, fontSize: 13, lineHeight: 1.6 }}>
          <div className="sect">No stands yet</div>
          A stand is where you actually sit, not where a camera hangs. Cameras go where animals
          go; stands exist where a bullet can safely stop. Add one below, then record its
          approach bearings (where animals come from) so the wind check has something to work
          with. Until then the app will say so rather than guess.
          <button
            onClick={bootstrap}
            style={{
              display: 'block', marginTop: 12, background: 'var(--surface-2)',
              color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 8,
              padding: '8px 12px', cursor: 'pointer', fontSize: 13,
            }}
          >
            Start me off, one per camera
          </button>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 6 }}>
            Places a stand at each camera so you have something to drag, rather than typing
            the estate in from scratch. Arcs stay unset, so wind advice stays quiet.
          </div>
        </div>
      )}

      {stands.map((s) => {
        const sit = sitFor(s.id)
        return (
          <div key={s.id} className="card" style={{ padding: 16, marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
              <div style={{ fontSize: 16, fontWeight: 600, flex: 1 }}>{s.name}</div>
              {!s.has_geometry && (
                <span style={{ fontSize: 11, color: 'var(--v-look)' }}>no approach arcs</span>
              )}
            </div>

            {sit?.wind_text && (
              <div style={{ fontSize: 13, marginTop: 6, lineHeight: 1.45, color: 'var(--text-dim)' }}>
                {sit.wind_text}
              </div>
            )}

            {!sit && (
              <button
                style={{ ...btn, width: '100%', marginTop: 12 }}
                onClick={() => run(() => api('/sits', { method: 'POST', body: JSON.stringify({ stand_id: s.id }) }))}
              >
                Claim for tonight
              </button>
            )}

            {sit && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 8 }}>
                  Claimed tonight
                  {sit.started_at ? ' · sitting' : ''}
                  {sit.outcome !== 'unreported' ? ` · ${sit.outcome.replace(/_/g, ' ')}` : ''}
                </div>

                {sit.outcome === 'unreported' && (
                  <button
                    style={{ ...btn, width: '100%' }}
                    onClick={async () => {
                      if (!sit.started_at) {
                        await api(`/sits/${sit.id}/start`, { method: 'POST' }).catch(() => {})
                      }
                      nav(`/sit/${sit.id}`)
                    }}
                  >
                    {sit.started_at ? 'Back to sit mode' : 'Start sit'}
                  </button>
                )}

                {sit.outcome === 'unreported' && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8 }}>
                    {OUTCOMES.map(([value, text]) => (
                      <button
                        key={value}
                        style={btn}
                        onClick={() =>
                          run(
                            () =>
                              api(`/sits/${sit.id}`, {
                                method: 'PATCH',
                                body: JSON.stringify({ outcome: value }),
                              }),
                            'Logged. Thank you: that is the only ground truth this app gets.',
                          )
                        }
                      >
                        {text}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}

      {me?.role === 'admin' && (
        <div className="card" style={{ padding: 16 }}>
          <div className="sect">Add a stand</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              className="input"
              placeholder="Stand name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <button
              style={btn}
              disabled={!newName}
              onClick={() =>
                run(async () => {
                  await api('/stands', { method: 'POST', body: JSON.stringify({ name: newName }) })
                  setNewName('')
                })
              }
            >
              Add
            </button>
          </div>
        </div>
      )}

      <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 14, lineHeight: 1.6, textAlign: 'center' }}>
        A sit nobody reports on stays <b>unreported</b>, never "nothing". Confusing "I saw
        nothing" with "I didn't say" would poison the only ground truth this app will ever have.
      </div>
    </div>
  )
}
