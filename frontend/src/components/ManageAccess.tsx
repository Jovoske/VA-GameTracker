import { useEffect, useState } from 'react'
import { api } from '../api'

/**
 * Admin-only management of who can sign in, and which SPYPOINT logins are synced.
 *
 * Two deliberate choices show up in the markup:
 *  - SPYPOINT passwords are write-only. The API never returns them, so this UI
 *    reports whether a usable password is stored rather than displaying one.
 *  - An account that still owns cameras cannot be deleted, only deactivated —
 *    deleting would orphan its images and detections. The server enforces it; the
 *    UI explains it before you try.
 */

type Me = { id: string; email: string; role: string }
type User = { id: string; email: string; role: string; created_at: string }
type Account = {
  id: string
  label: string
  username: string
  active: boolean
  password_set: boolean
  password_readable: boolean
  last_sync_at: string | null
  last_error: string | null
  cameras: number
}

const label = {
  fontSize: 12,
  color: 'var(--text-dim)',
  letterSpacing: '.05em',
  marginBottom: 12,
} as const

const input = {
  background: 'var(--surface-2)',
  color: 'var(--text)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  padding: '9px 10px',
  fontSize: 14,
  minWidth: 0,
  flex: 1,
} as const

const btn = {
  background: 'var(--surface-2)',
  color: 'var(--text)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  padding: '9px 12px',
  fontSize: 13,
  cursor: 'pointer',
  minHeight: 40,
} as const

const ROLES = ['admin', 'member', 'viewer']

export default function ManageAccess() {
  const [me, setMe] = useState<Me | null>(null)
  const [users, setUsers] = useState<User[] | null>(null)
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [msg, setMsg] = useState('')

  const [uEmail, setUEmail] = useState('')
  const [uPass, setUPass] = useState('')
  const [uRole, setURole] = useState('member')

  const [aLabel, setALabel] = useState('')
  const [aUser, setAUser] = useState('')
  const [aPass, setAPass] = useState('')

  async function load() {
    try {
      setMe(await api<Me>('/users/me'))
      setUsers(await api<User[]>('/users'))
      setAccounts(await api<Account[]>('/spypoint/accounts'))
    } catch {
      // A non-admin simply doesn't get this panel; that isn't an error worth showing.
      setUsers([])
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg('')
    try {
      await fn()
      setMsg(ok)
      await load()
    } catch (e) {
      setMsg((e as Error).message)
    }
  }

  if (me && me.role !== 'admin') return null
  if (!users) return null

  const adminCount = users.filter((u) => u.role === 'admin').length

  return (
    <>
      {msg && (
        <div
          onClick={() => setMsg('')}
          className="card"
          style={{ padding: '10px 14px', marginBottom: 14, fontSize: 13, cursor: 'pointer' }}
        >
          {msg}
        </div>
      )}

      {/* ── People ─────────────────────────────────────── */}
      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div style={label}>PEOPLE</div>

        {users.map((u) => {
          const isMe = me?.id === u.id
          const lastAdmin = u.role === 'admin' && adminCount <= 1
          return (
            <div
              key={u.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                flexWrap: 'wrap',
                padding: '8px 0',
                borderBottom: '1px solid var(--border)',
              }}
            >
              <div style={{ flex: 1, minWidth: 160, fontSize: 14 }}>
                {u.email}
                {isMe && <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> · you</span>}
              </div>
              <select
                value={u.role}
                disabled={lastAdmin}
                title={lastAdmin ? 'The only admin — promote someone else first' : undefined}
                onChange={(e) =>
                  run(
                    () =>
                      api(`/users/${u.id}`, {
                        method: 'PATCH',
                        body: JSON.stringify({ role: e.target.value }),
                      }),
                    `${u.email} is now ${e.target.value}`,
                  )
                }
                style={{ ...btn, minWidth: 96 }}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <button
                style={{ ...btn, opacity: isMe || lastAdmin ? 0.45 : 1 }}
                disabled={isMe || lastAdmin}
                title={
                  isMe
                    ? 'You cannot delete your own account'
                    : lastAdmin
                      ? 'The only admin — promote someone else first'
                      : undefined
                }
                onClick={() => {
                  if (!confirm(`Remove ${u.email}? They will lose access immediately.`)) return
                  run(() => api(`/users/${u.id}`, { method: 'DELETE' }), `Removed ${u.email}`)
                }}
              >
                Remove
              </button>
            </div>
          )
        })}

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
          <input
            style={input}
            placeholder="email"
            value={uEmail}
            onChange={(e) => setUEmail(e.target.value)}
          />
          <input
            style={input}
            type="password"
            placeholder="password (min 8)"
            value={uPass}
            onChange={(e) => setUPass(e.target.value)}
          />
          <select style={{ ...btn, minWidth: 96 }} value={uRole} onChange={(e) => setURole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button
            style={btn}
            disabled={!uEmail || uPass.length < 8}
            onClick={() =>
              run(async () => {
                await api('/users', {
                  method: 'POST',
                  body: JSON.stringify({ email: uEmail, password: uPass, role: uRole }),
                })
                setUEmail('')
                setUPass('')
              }, `Added ${uEmail}`)
            }
          >
            Add person
          </button>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8, lineHeight: 1.5 }}>
          Guests can be given <b>viewer</b> access — they see the plan and the photos but change
          nothing. The last admin cannot be removed or demoted; that would lock everyone out.
        </div>
      </div>

      {/* ── SPYPOINT accounts ──────────────────────────── */}
      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div style={label}>SPYPOINT ACCOUNTS</div>

        {(accounts ?? []).map((a) => (
          <div key={a.id} style={{ padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 160 }}>
                <div style={{ fontSize: 14 }}>{a.label}</div>
                <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                  {a.username} · {a.cameras} camera{a.cameras === 1 ? '' : 's'}
                </div>
              </div>
              <button
                style={btn}
                onClick={() =>
                  run(
                    () =>
                      api(`/spypoint/accounts/${a.id}`, {
                        method: 'PATCH',
                        body: JSON.stringify({ active: !a.active }),
                      }),
                    `${a.label} ${a.active ? 'paused' : 'resumed'}`,
                  )
                }
              >
                {a.active ? 'Pause sync' : 'Resume sync'}
              </button>
              <button
                style={{ ...btn, opacity: a.cameras ? 0.45 : 1 }}
                disabled={a.cameras > 0}
                title={
                  a.cameras > 0
                    ? 'Cameras still belong to this account — pause it instead, or deleting would orphan their history'
                    : undefined
                }
                onClick={() => {
                  if (!confirm(`Delete ${a.label}?`)) return
                  run(
                    () => api(`/spypoint/accounts/${a.id}`, { method: 'DELETE' }),
                    `Deleted ${a.label}`,
                  )
                }}
              >
                Delete
              </button>
            </div>

            {!a.password_readable && a.password_set && (
              <div style={{ fontSize: 12, color: 'var(--marginal)', marginTop: 4 }}>
                Stored password can't be read — this happens if JWT_SECRET changed. Re-enter it below.
              </div>
            )}
            {!a.password_set && (
              <div style={{ fontSize: 12, color: 'var(--marginal)', marginTop: 4 }}>
                No password stored — sync will skip this account.
              </div>
            )}
            {a.last_error && (
              <div style={{ fontSize: 12, color: 'var(--skip)', marginTop: 4 }}>{a.last_error}</div>
            )}

            <NewPassword
              onSave={(pw) =>
                run(
                  () =>
                    api(`/spypoint/accounts/${a.id}`, {
                      method: 'PATCH',
                      body: JSON.stringify({ password: pw }),
                    }),
                  `Password updated for ${a.label}`,
                )
              }
            />
          </div>
        ))}

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
          <input style={input} placeholder="label (e.g. North block)" value={aLabel} onChange={(e) => setALabel(e.target.value)} />
          <input style={input} placeholder="SPYPOINT username" value={aUser} onChange={(e) => setAUser(e.target.value)} />
          <input style={input} type="password" placeholder="SPYPOINT password" value={aPass} onChange={(e) => setAPass(e.target.value)} />
          <button
            style={btn}
            disabled={!aLabel || !aUser || !aPass}
            onClick={() =>
              run(async () => {
                await api('/spypoint/accounts', {
                  method: 'POST',
                  body: JSON.stringify({ label: aLabel, username: aUser, password: aPass }),
                })
                setALabel('')
                setAUser('')
                setAPass('')
              }, `Added ${aLabel}`)
            }
          >
            Add account
          </button>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8, lineHeight: 1.5 }}>
          Cameras split across several SPYPOINT logins all sync into one estate. Passwords are
          encrypted and never shown again. If one account fails, the others still sync.
        </div>
      </div>
    </>
  )
}

function NewPassword({ onSave }: { onSave: (pw: string) => void }) {
  const [pw, setPw] = useState('')
  const [open, setOpen] = useState(false)
  if (!open)
    return (
      <button style={{ ...btn, marginTop: 8, padding: '6px 10px' }} onClick={() => setOpen(true)}>
        Change password
      </button>
    )
  return (
    <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
      <input
        style={input}
        type="password"
        placeholder="new SPYPOINT password"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
      />
      <button
        style={btn}
        disabled={!pw}
        onClick={() => {
          onSave(pw)
          setPw('')
          setOpen(false)
        }}
      >
        Save
      </button>
      <button style={btn} onClick={() => setOpen(false)}>
        Cancel
      </button>
    </div>
  )
}
