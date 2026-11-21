import { useEffect, useState } from 'react'
import { api } from '../api'
import { t } from '../i18n'
import SettingsSection from './SettingsSection'

type AccessRequest = { id: string; email: string }
type Decision = 'approve' | 'decline'

export default function AccessRequests({ onApproved }: { onApproved: () => void }) {
  const [requests, setRequests] = useState<AccessRequest[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setMessage('')
    setError('')
    try {
      await action()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function refresh() {
    return run(async () => setRequests(await api<AccessRequest[]>('/users/access-requests')))
  }

  useEffect(() => { void refresh() }, [])

  function review(request: AccessRequest, decision: Decision) {
    if (decision === 'decline' && !window.confirm(t('signup.confirmDecline', { email: request.email }))) return
    return run(async () => {
      await api(`/users/access-requests/${request.id}/decision`, {
        method: 'POST', body: JSON.stringify({ decision }),
      })
      setRequests((current) => current?.filter(({ id }) => id !== request.id) ?? null)
      setMessage(t(decision === 'approve' ? 'signup.approved' : 'signup.declined', { email: request.email }))
      if (decision === 'approve') onApproved()
    })
  }

  return (
    <SettingsSection id="access-requests" title={t('signup.queue')} summary={requests?.length || undefined}>
      <p className="settings-hint">{t('signup.verifyPerson')}</p>
      {requests?.length === 0 && <p>{t('signup.empty')}</p>}
      {requests?.map((request) => (
        <div key={request.id} style={{ padding: '10px 0', borderTop: '1px solid var(--border)' }}>
          <div style={{ overflowWrap: 'anywhere', marginBottom: 6 }}>{request.email}</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="button" className="btn" disabled={busy}
              onClick={() => void review(request, 'approve')}>{t('signup.approve')}</button>
            <button type="button" className="btn" disabled={busy}
              onClick={() => void review(request, 'decline')}>{t('signup.decline')}</button>
          </div>
        </div>
      ))}
      <button type="button" className="btn" onClick={() => void refresh()} disabled={busy}>
        {t('signup.refresh')}
      </button>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
    </SettingsSection>
  )
}
