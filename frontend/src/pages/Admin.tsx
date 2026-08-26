import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setToken } from '../api'

type Status = {
  cameras: number
  images: number
  detections: number
  empty: number
  last_sync: { status: string; at: string | null } | null
}
type Check = {
  current: string
  latest: string | null
  update_available?: boolean
  update_command?: string
  error?: string
}
type Species = {
  id: string
  common_name: string
  huntable: boolean
  is_priority: boolean
  detections: number
}
type Me = { id: string; email: string; role: string }
type UserRow = { id: string; email: string; role: string; is_you: boolean }
type CamAccount = {
  id: string
  label: string
  username: string
  owner: string | null
  active: boolean
  cameras: number
  can_remove: boolean
}
const smallBtn = {
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  color: 'var(--text-dim)',
  borderRadius: 8,
  padding: '5px 10px',
  fontSize: 12,
  cursor: 'pointer',
  flexShrink: 0,
} as const

export default function Admin() {
  const nav = useNavigate()
  const [version, setVersion] = useState('')
  const [status, setStatus] = useState<Status | null>(null)
  const [check, setCheck] = useState<Check | null>(null)
  const [checking, setChecking] = useState(false)
  const [sexMsg, setSexMsg] = useState('')
  const [sexBusy, setSexBusy] = useState(false)
  const [species, setSpecies] = useState<Species[]>([])
  const [savingId, setSavingId] = useState<string | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  const [users, setUsers] = useState<UserRow[]>([])
  const [newUser, setNewUser] = useState({ email: '', password: '', role: 'member' })
  const [userMsg, setUserMsg] = useState('')
  const [accounts, setAccounts] = useState<CamAccount[]>([])
  const [newAcct, setNewAcct] = useState({ username: '', password: '', label: '' })
  const [acctMsg, setAcctMsg] = useState('')
  const [acctBusy, setAcctBusy] = useState(false)
  const [pw, setPw] = useState({ current: '', next: '' })
  const [pwMsg, setPwMsg] = useState('')

  async function runSexPass() {
    setSexBusy(true)
    try {
      const r = await api<{ note?: string }>('/admin/sex-pass', { method: 'POST' })
      setSexMsg(r.note || 'Started.')
    } catch (e) {
      setSexMsg((e as Error).message)
    }
    setSexBusy(false)
  }

  useEffect(() => {
    api<{ version: string }>('/admin/version').then((r) => setVersion(r.version)).catch(() => {})
    api<Status>('/admin/status').then(setStatus).catch(() => {})
    api<Species[]>('/species').then(setSpecies).catch(() => {})
    api<Me>('/auth/me').then(setMe).catch(() => {})
    api<UserRow[]>('/users').then(setUsers).catch(() => {})
    api<CamAccount[]>('/camera-accounts').then(setAccounts).catch(() => {})
  }, [])

  async function addUser() {
    setUserMsg('')
    try {
      await api('/users', { method: 'POST', body: JSON.stringify(newUser) })
      setNewUser({ email: '', password: '', role: 'member' })
      setUsers(await api<UserRow[]>('/users'))
      setUserMsg('Added')
    } catch (e) {
      setUserMsg((e as Error).message)
    }
  }

  async function delUser(u: UserRow) {
    if (!window.confirm(`Remove ${u.email}? They will no longer be able to sign in.`)) return
    setUserMsg('')
    try {
      await api(`/users/${u.id}`, { method: 'DELETE' })
      setUsers(await api<UserRow[]>('/users'))
    } catch (e) {
      setUserMsg((e as Error).message)
    }
  }

  async function addAccount() {
    setAcctMsg('')
    setAcctBusy(true)
    try {
      const r = await api<{ note?: string }>('/camera-accounts', {
        method: 'POST',
        body: JSON.stringify({
          username: newAcct.username,
          password: newAcct.password,
          label: newAcct.label || null,
        }),
      })
      setNewAcct({ username: '', password: '', label: '' })
      setAccounts(await api<CamAccount[]>('/camera-accounts'))
      setAcctMsg(r.note || 'Connected')
    } catch (e) {
      setAcctMsg((e as Error).message)
    }
    setAcctBusy(false)
  }

  async function delAccount(a: CamAccount) {
    if (!window.confirm(`Disconnect ${a.label}? Its photos stay, but new ones stop syncing.`)) return
    setAcctMsg('')
    try {
      await api(`/camera-accounts/${a.id}`, { method: 'DELETE' })
      setAccounts(await api<CamAccount[]>('/camera-accounts'))
    } catch (e) {
      setAcctMsg((e as Error).message)
    }
  }

  async function changePw() {
    setPwMsg('')
    try {
      await api('/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ current_password: pw.current, new_password: pw.next }),
      })
      setPw({ current: '', next: '' })
      setPwMsg('Password changed')
    } catch (e) {
      setPwMsg((e as Error).message)
    }
  }

  async function toggleSpecies(s: Species) {
    const next = !s.huntable
    setSavingId(s.id)
    setSpecies((list) => list.map((x) => (x.id === s.id ? { ...x, huntable: next } : x)))
    try {
      await api(`/species/${s.id}`, { method: 'PATCH', body: JSON.stringify({ huntable: next }) })
    } catch {
      // revert on failure
      setSpecies((list) => list.map((x) => (x.id === s.id ? { ...x, huntable: !next } : x)))
    }
    setSavingId(null)
  }

  async function checkUpdates() {
    setChecking(true)
    try {
      setCheck(await api<Check>('/admin/version/check'))
    } catch {
      /* ignore */
    }
    setChecking(false)
  }

  const rows: [string, number][] = status
    ? [
        ['Cameras', status.cameras],
        ['Photos', status.images],
        ['Detections', status.detections],
        ['Empty frames filtered', status.empty],
      ]
    : []

  const onCount = species.filter((s) => s.huntable).length

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 12 }}>Settings</div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div className="sect">Hunting advice</div>
          {species.length > 0 && (
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              {onCount} of {species.length} shown
            </div>
          )}
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.5, marginBottom: 8 }}>
          Choose which animals appear in Tonight's recommendation and the outlook. Turn off
          anything out of season or that you don't hunt: ibex when it's closed, say, or
          rabbits. The stats keep tracking every species regardless; this only shapes the advice.
        </div>
        {species.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--text-dim)', padding: '8px 0' }}>Loading…</div>
        ) : (
          species.map((s) => (
            <div
              key={s.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 0',
                borderTop: '1px solid var(--border)',
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 14, color: s.huntable ? 'var(--text)' : 'var(--text-dim)' }}>
                  {s.common_name}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', fontVariantNumeric: 'tabular-nums' }}>
                  {s.detections} sighting{s.detections === 1 ? '' : 's'}
                </div>
              </div>
              <button
                onClick={() => toggleSpecies(s)}
                disabled={savingId === s.id}
                aria-pressed={s.huntable}
                title={s.huntable ? 'Shown in advice. Click to hide.' : 'Hidden from advice. Click to show.'}
                style={{
                  width: 46,
                  height: 26,
                  borderRadius: 13,
                  border: 'none',
                  cursor: savingId === s.id ? 'default' : 'pointer',
                  background: s.huntable ? 'var(--go)' : 'var(--surface-2)',
                  position: 'relative',
                  transition: 'background var(--d-base) var(--ease-out)',
                  flexShrink: 0,
                  opacity: savingId === s.id ? 0.6 : 1,
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
                    // translate, not `left`: the knob rides the compositor
                    // instead of forcing layout and paint on every frame.
                    transform: s.huntable ? 'translateX(20px)' : 'translateX(0)',
                    transition: 'transform var(--d-base) var(--ease-out)',
                  }}
                />
              </button>
            </div>
          ))
        )}
      </div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div className="sect">Camera accounts</div>
        <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.5, marginBottom: 10 }}>
          Connect a SPYPOINT account and its cameras join the estate, with photos, AI detection and
          forecasts included. Guests can add their own account here.
        </div>
        {accounts.map((a) => (
          <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderTop: '1px solid var(--border)' }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 14 }}>{a.label}</div>
              <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                {a.cameras} camera{a.cameras === 1 ? '' : 's'}{a.owner ? ` · added by ${a.owner}` : ''}
              </div>
            </div>
            {a.can_remove && (
              <button onClick={() => delAccount(a)} style={smallBtn}>Disconnect</button>
            )}
          </div>
        ))}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
          <input className="input" placeholder="SPYPOINT email" value={newAcct.username}
            onChange={(e) => setNewAcct({ ...newAcct, username: e.target.value })} autoComplete="off" />
          <input className="input" placeholder="SPYPOINT password" type="password" value={newAcct.password}
            onChange={(e) => setNewAcct({ ...newAcct, password: e.target.value })} autoComplete="new-password" />
          <input className="input" placeholder="Label, optional (e.g. 'Marco's cameras')" value={newAcct.label}
            onChange={(e) => setNewAcct({ ...newAcct, label: e.target.value })} />
          <button className="btn" style={{ width: 'auto', padding: '9px 14px' }}
            onClick={addAccount} disabled={acctBusy || !newAcct.username || !newAcct.password}>
            {acctBusy ? 'Checking with SPYPOINT…' : 'Connect account'}
          </button>
        </div>
        {acctMsg && <div style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{acctMsg}</div>}
      </div>

      {me?.role === 'admin' && (
        <div className="card" style={{ padding: 18, marginBottom: 14 }}>
          <div className="sect">People</div>
          <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.5, marginBottom: 10 }}>
            Who can sign in. Guests get "member": they see everything and can connect their own
            cameras, but can't change settings or manage people.
          </div>
          {users.map((u) => (
            <div key={u.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderTop: '1px solid var(--border)' }}>
              <div style={{ flex: 1, minWidth: 0, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {u.email}{u.is_you ? ' (you)' : ''}
              </div>
              <span style={{ fontSize: 11, color: u.role === 'admin' ? 'var(--sand)' : 'var(--text-dim)', border: '1px solid var(--border)', borderRadius: 6, padding: '1px 7px' }}>
                {u.role}
              </span>
              {!u.is_you && <button onClick={() => delUser(u)} style={smallBtn}>Remove</button>}
            </div>
          ))}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
            <input className="input" placeholder="Guest email (their login name)" value={newUser.email}
              onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} autoComplete="off" />
            <input className="input" placeholder="Password for them (min 8 chars)" value={newUser.password}
              onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} autoComplete="new-password" />
            <div style={{ display: 'flex', gap: 8 }}>
              <select className="input" style={{ width: 130 }} value={newUser.role}
                onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
                <option value="member">member</option>
                <option value="admin">admin</option>
              </select>
              <button className="btn" style={{ width: 'auto', padding: '9px 14px' }}
                onClick={addUser} disabled={!newUser.email || newUser.password.length < 8}>
                Add person
              </button>
            </div>
          </div>
          {userMsg && <div style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{userMsg}</div>}
        </div>
      )}

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div className="sect">Change password</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input className="input" placeholder="Current password" type="password" value={pw.current}
            onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" />
          <input className="input" placeholder="New password (min 8 chars)" type="password" value={pw.next}
            onChange={(e) => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" />
          <button className="btn" style={{ width: 'auto', padding: '9px 14px' }}
            onClick={changePw} disabled={!pw.current || pw.next.length < 8}>
            Change password
          </button>
        </div>
        {pwMsg && <div style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{pwMsg}</div>}
      </div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div className="sect">Version</div>
        <div style={{ fontSize: 16, fontWeight: 600 }}>GameSense v{version || '…'}</div>
        <button
          className="btn"
          style={{ width: 'auto', marginTop: 12, padding: '8px 14px' }}
          onClick={checkUpdates}
          disabled={checking}
        >
          {checking ? 'Checking…' : 'Check for updates'}
        </button>
        {check && (
          <div style={{ marginTop: 12, fontSize: 13 }}>
            {check.error ? (
              <span style={{ color: 'var(--text-dim)' }}>Couldn't reach GitHub: {check.error}</span>
            ) : check.update_available ? (
              <>
                <div style={{ color: 'var(--go)' }}>
                  Update available: {check.latest} (you have {check.current})
                </div>
                <div style={{ color: 'var(--text-dim)', marginTop: 6 }}>Deployment is automatic:</div>
                <code
                  style={{
                    display: 'block',
                    background: 'var(--surface-2)',
                    padding: '8px 10px',
                    borderRadius: 8,
                    marginTop: 4,
                    fontSize: 12,
                    fontFamily: 'var(--font-mono, monospace)',
                  }}
                >
                  {check.update_command}
                </code>
              </>
            ) : (
              <span style={{ color: 'var(--text-dim)' }}>Up to date ({check.current}).</span>
            )}
          </div>
        )}
      </div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div className="sect">AI labelling</div>
        <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.5, marginBottom: 10 }}>
          Identify sex on red deer (stag / hind) and wild boar using cloud vision. Uses your
          ANTHROPIC_API_KEY and costs a little API credit per photo; only un-sexed animals are processed.
        </div>
        <button
          className="btn"
          style={{ width: 'auto', padding: '8px 14px' }}
          onClick={runSexPass}
          disabled={sexBusy}
        >
          {sexBusy ? 'Starting…' : 'Identify deer / boar sex'}
        </button>
        {sexMsg && <div style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{sexMsg}</div>}
      </div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div className="sect">Account</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 13, color: 'var(--text-dim)', flex: 1, minWidth: 0 }}>
            Signed in as <span style={{ color: 'var(--text)' }}>{me?.email ?? '…'}</span>
          </div>
          <button
            onClick={() => {
              setToken(null)
              nav('/login')
            }}
            style={{ ...smallBtn, padding: '9px 16px', fontSize: 14 }}
          >
            Sign out
          </button>
        </div>
      </div>

      {status && (
        <div className="card" style={{ padding: 18 }}>
          <div className="sect">System</div>
          {rows.map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0' }}>
              <span style={{ color: 'var(--text-dim)' }}>{k}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</span>
            </div>
          ))}
          {status.last_sync && (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0' }}>
              <span style={{ color: 'var(--text-dim)' }}>Last sync</span>
              <span>{status.last_sync.status}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
