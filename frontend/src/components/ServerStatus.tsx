import type { ReactNode } from 'react'
import { ageLabel, plainWords, whenLabel } from '../api'

/**
 * What the server's own upkeep last did, from the files its scheduled tasks leave
 * (backend app.ops): the self-update (deploy/update.ps1), the nightly backup and the
 * weekly restore test. "Up to date" used to come from GitHub's release tags, which
 * stopped long ago, so it said so whatever the server ran (audit D-22); a backup
 * nobody could see was a backup nobody knew had stopped (H-10).
 */

export type DeployStatus = {
  checked_at: string | null
  /** The self-update stopped looking: three missed runs of a 10-minute task. */
  late: boolean
  /** "deploy": only commits that passed the tests go in; "main": every push. */
  source: 'deploy' | 'main' | null
  running: string | null
  running_subject: string | null
  running_since: string | null
  waiting_for_tests: number | null
  offline: boolean
  failed: {
    commit: string | null
    subject: string | null
    step: string | null
    reason: string | null
    at: string | null
    attempts: number | null
    gave_up: boolean
    rolled_back: boolean
  } | null
}
export type VersionInfo = { version: string; commit: string | null; deploy: DeployStatus | null }

export type BackupStatus = {
  at: string | null
  ok: boolean
  last_ok_at: string | null
  /** No good backup for 36 hours. */
  late: boolean
  target: string | null
  dump_mb: number | null
  photos_on_server: number | null
  photos_in_backup: number | null
  target_free_gb: number | null
  error: string | null
}
export type RestoreCheck = {
  at: string | null
  ok: boolean
  late: boolean
  photos_checked: number | null
  photos_found: number | null
  error: string | null
}
/** Free space where the photos are kept: `low` under 20 GB, `full` under 5 GB (the
 *  photo fetch stops downloading there). */
export type Disk = { free_gb: number; total_gb: number; low: boolean; full?: boolean }

const short = (sha: string | null | undefined) => (sha ? sha.slice(0, 7) : '')
const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`
const line = { fontSize: 13, lineHeight: 1.5 } as const
const dim = { ...line, color: 'var(--text-dim)' } as const
const bad = { ...line, color: 'var(--skip)' } as const

/** The self-update, lead with the answer: what runs, whether an update got stuck. */
export function UpdateStatus({ info }: { info: VersionInfo | null }) {
  const d = info?.deploy
  if (!info) return null
  if (!d) {
    return <div style={dim}>This server doesn’t update itself.</div>
  }
  const lookedAt = d.checked_at ? ageLabel(d.checked_at) : null
  const failed = d.failed && d.failed.commit !== d.running ? d.failed : null
  return (
    <div data-deploy={d.late ? 'late' : failed ? 'failed' : 'ok'} style={{ display: 'grid', gap: 8 }}>
      {d.running && (
        <div style={line}>
          Running {d.running_subject ? <>“{d.running_subject}”</> : short(d.running)}
          {d.running_since ? `, in since ${whenLabel(d.running_since)}.` : '.'}
        </div>
      )}
      {failed && (
        <div role="alert" style={bad}>
          An update didn’t go in{failed.subject ? <>: “{failed.subject}”</> : ''}. {failed.reason ? plainWords(failed.reason) : ''}{' '}
          {failed.rolled_back ? 'The version before it was put back and is running.' : 'Nothing changed on the server.'}{' '}
          {failed.gave_up
            ? 'It tries again every 6 hours, or as soon as a newer change arrives.'
            : 'It tries again in 10 minutes.'}
        </div>
      )}
      {d.late ? (
        <div role="alert" style={bad}>
          {lookedAt
            ? `The server last looked for updates ${lookedAt}.`
            : 'The server has never looked for updates.'}{' '}
          The GameSense-Update task on the server may have stopped.
        </div>
      ) : (
        <div style={dim}>
          {d.source === 'main'
            ? 'Every change goes in as it is made: the tests aren’t set up to check them first yet.'
            : 'Only changes that passed the tests go in.'}{' '}
          The server looks every 10 minutes{lookedAt ? ` (last look ${lookedAt})` : ''}.
          {d.offline ? ' It couldn’t reach GitHub at the last look.' : ''}
        </div>
      )}
      {!!d.waiting_for_tests && (
        <div style={dim}>
          {d.waiting_for_tests === 1
            ? 'One newer change is waiting for its tests to pass.'
            : `${d.waiting_for_tests} newer changes are waiting for their tests to pass.`}
        </div>
      )}
      {(info.commit || failed) && (
        <details style={{ ...dim, fontSize: 12 }}>
          <summary style={{ cursor: 'pointer', minHeight: 44, display: 'flex', alignItems: 'center' }}>The detail</summary>
          <div style={{ overflowWrap: 'anywhere' }}>
            This server runs commit {short(info.commit) || '?'}.
            {failed ? ` The one that didn’t go in: ${short(failed.commit)}, at the ${failed.step ?? '?'} step, ${failed.attempts ?? 1} ${(failed.attempts ?? 1) === 1 ? 'try' : 'tries'}${failed.at ? `, last ${ageLabel(failed.at)}` : ''}. ${failed.reason ?? ''}` : ''}
          </div>
        </details>
      )}
    </div>
  )
}

function Row({ label, children, alert, tone }: {
  label: string
  children: ReactNode
  alert?: boolean
  tone?: 'bad' | 'warn'
}) {
  const color = tone === 'bad' ? 'var(--skip)' : tone === 'warn' ? 'var(--marginal)' : undefined
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13, padding: '4px 0' }}
      role={alert ? 'alert' : undefined}>
      <span style={{ color: 'var(--text-dim)', flexShrink: 0 }}>{label}</span>
      <span style={{ textAlign: 'right', color, overflowWrap: 'anywhere' }}>{children}</span>
    </div>
  )
}

/** Free space where the photos are kept, amber when getting full, red when full. */
export function DiskRow({ disk }: { disk: Disk }) {
  const tone = disk.full ? 'bad' : disk.low ? 'warn' : undefined
  return (
    <div data-disk={disk.full ? 'full' : disk.low ? 'low' : 'ok'}>
      <Row label="Space for photos" alert={!!tone} tone={tone}>
        {disk.free_gb} GB free
        {disk.full
          ? '. Full: new photos aren’t fetched until some space is freed on the server.'
          : disk.low ? '. Getting full: free some space on the server soon.' : ''}
      </Row>
    </div>
  )
}

/** The nightly backup and the weekly restore test. */
export function BackupRows({ backup, restore }: { backup: BackupStatus | null; restore: RestoreCheck | null }) {
  let text: ReactNode
  let tone: 'bad' | undefined
  if (!backup) {
    tone = 'bad'
    text = 'None on record. Set up the nightly backup on the server (deploy/register-tasks.ps1).'
  } else if (!backup.ok) {
    tone = 'bad'
    text = `Failed ${backup.at ? ageLabel(backup.at) : ''}: ${backup.error ?? 'no reason given.'}${backup.last_ok_at ? ` The last good one is from ${ageLabel(backup.last_ok_at)}.` : ' There is no good one yet.'}`
  } else if (backup.late) {
    tone = 'bad'
    text = `${backup.last_ok_at ? ageLabel(backup.last_ok_at) : 'Long ago'}. Check the GameSense-Backup task on the server.`
  } else {
    text = backup.last_ok_at ? ageLabel(backup.last_ok_at) : 'Done'
  }
  const detail = backup && backup.ok
    ? [backup.dump_mb != null ? `database ${backup.dump_mb} MB` : null,
       backup.photos_in_backup != null ? plural(backup.photos_in_backup, 'photo') : null,
       backup.target_free_gb != null ? `${backup.target_free_gb} GB free there` : null].filter(Boolean).join(' · ')
    : ''
  let rText: ReactNode = 'Not run yet.'
  let rTone: 'bad' | 'warn' | undefined
  if (restore) {
    if (!restore.ok) {
      rTone = 'bad'
      rText = `Failed ${restore.at ? ageLabel(restore.at) : ''}: ${restore.error ?? 'no reason given.'}`
    } else {
      rTone = restore.late ? 'warn' : undefined
      rText = `Passed ${restore.at ? ageLabel(restore.at) : ''}${restore.late ? '. It runs every Sunday: check the GameSense-RestoreCheck task.' : ''}`
    }
  }
  return (
    <>
      <div data-backup={tone ? 'bad' : 'ok'}>
        <Row label="Last backup" alert={!!tone} tone={tone}>{text}</Row>
        {detail && <div style={{ ...dim, fontSize: 12, textAlign: 'right', marginTop: -2 }}>{detail}</div>}
      </div>
      <div data-restore={rTone ?? 'ok'}>
        <Row label="Restore test" alert={rTone === 'bad'} tone={rTone}>{rText}</Row>
      </div>
    </>
  )
}
