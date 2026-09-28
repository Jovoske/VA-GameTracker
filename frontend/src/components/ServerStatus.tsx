import type { ReactNode } from 'react'
import { ageLabel, plainWords, whenLabel } from '../api'
import { fmtNumber, t } from '../i18n'

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
const line = { fontSize: 13, lineHeight: 1.5 } as const
const dim = { ...line, color: 'var(--text-dim)' } as const
const bad = { ...line, color: 'var(--skip)' } as const

/** The self-update, lead with the answer: what runs, whether an update got stuck. */
export function UpdateStatus({ info }: { info: VersionInfo | null }) {
  const d = info?.deploy
  if (!info) return null
  if (!d) {
    return <div style={dim}>{t('server.noUpdates')}</div>
  }
  const lookedAt = d.checked_at ? ageLabel(d.checked_at) : null
  const failed = d.failed && d.failed.commit !== d.running ? d.failed : null
  return (
    <div data-deploy={d.late ? 'late' : failed ? 'failed' : 'ok'} style={{ display: 'grid', gap: 8 }}>
      {d.running && (
        <div style={line}>
          {d.running_since
            ? t('server.runningSince', { what: d.running_subject ? `“${d.running_subject}”` : short(d.running), when: whenLabel(d.running_since) })
            : t('server.running', { what: d.running_subject ? `“${d.running_subject}”` : short(d.running) })}
        </div>
      )}
      {failed && (
        <div role="alert" style={bad}>
          {failed.subject ? t('server.failedNamed', { subject: failed.subject }) : t('server.failed')} {failed.reason ? plainWords(failed.reason) : ''}{' '}
          {failed.rolled_back ? t('server.rolledBack') : t('server.nothingChanged')}{' '}
          {failed.gave_up ? t('server.gaveUp') : t('server.retrySoon')}
        </div>
      )}
      {d.late ? (
        <div role="alert" style={bad}>
          {lookedAt ? t('server.lastLooked', { ago: lookedAt }) : t('server.neverLooked')}{' '}
          {t('server.taskStopped')}
        </div>
      ) : (
        <div style={dim}>
          {d.source === 'main' ? t('server.everyChange') : t('server.onlyTested')}{' '}
          {lookedAt ? t('server.looksEveryLast', { ago: lookedAt }) : t('server.looksEvery')}
          {d.offline ? ` ${t('server.noGithub')}` : ''}
        </div>
      )}
      {!!d.waiting_for_tests && (
        <div style={dim}>
          {t('server.waiting', { count: d.waiting_for_tests })}
        </div>
      )}
      {(info.commit || failed) && (
        <details style={{ ...dim, fontSize: 12 }}>
          <summary style={{ cursor: 'pointer', minHeight: 44, display: 'flex', alignItems: 'center' }}>{t('common.detail')}</summary>
          <div style={{ overflowWrap: 'anywhere' }}>
            {t('server.runsCommit', { commit: short(info.commit) || '?' })}
            {failed ? ` ${t(failed.at ? 'server.failedDetailAt' : 'server.failedDetail', {
              commit: short(failed.commit), step: failed.step ?? '?', count: failed.attempts ?? 1, ago: failed.at ? ageLabel(failed.at) : '',
            })} ${failed.reason ?? ''}` : ''}
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
      <Row label={t('server.space')} alert={!!tone} tone={tone}>
        {disk.full ? t('server.diskFull', { gb: fmtNumber(disk.free_gb) })
          : disk.low ? t('server.diskLow', { gb: fmtNumber(disk.free_gb) }) : t('server.diskFree', { gb: fmtNumber(disk.free_gb) })}
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
    text = t('server.noBackup')
  } else if (!backup.ok) {
    tone = 'bad'
    text = `${t('server.failedAt', { ago: backup.at ? ageLabel(backup.at) : '', why: backup.error ?? t('server.noReason') })} ${backup.last_ok_at ? t('server.lastGood', { ago: ageLabel(backup.last_ok_at) }) : t('server.noGood')}`
  } else if (backup.late) {
    tone = 'bad'
    text = t('server.backupLate', { ago: backup.last_ok_at ? ageLabel(backup.last_ok_at) : t('server.longAgo') })
  } else {
    text = backup.last_ok_at ? ageLabel(backup.last_ok_at) : t('common.done')
  }
  const detail = backup && backup.ok
    ? [backup.dump_mb != null ? t('server.database', { mb: fmtNumber(backup.dump_mb) }) : null,
       backup.photos_in_backup != null ? t('server.photos', { count: backup.photos_in_backup, n: fmtNumber(backup.photos_in_backup) }) : null,
       backup.target_free_gb != null ? t('server.freeThere', { gb: fmtNumber(backup.target_free_gb) }) : null].filter(Boolean).join(' · ')
    : ''
  let rText: ReactNode = t('server.notRun')
  let rTone: 'bad' | 'warn' | undefined
  if (restore) {
    if (!restore.ok) {
      rTone = 'bad'
      rText = t('server.failedAt', { ago: restore.at ? ageLabel(restore.at) : '', why: restore.error ?? t('server.noReason') })
    } else {
      rTone = restore.late ? 'warn' : undefined
      rText = restore.late ? t('server.passedLate', { ago: restore.at ? ageLabel(restore.at) : '' }) : t('server.passed', { ago: restore.at ? ageLabel(restore.at) : '' })
    }
  }
  return (
    <>
      <div data-backup={tone ? 'bad' : 'ok'}>
        <Row label={t('server.lastBackup')} alert={!!tone} tone={tone}>{text}</Row>
        {detail && <div style={{ ...dim, fontSize: 12, textAlign: 'right', marginTop: -2 }}>{detail}</div>}
      </div>
      <div data-restore={rTone ?? 'ok'}>
        <Row label={t('server.restoreTest')} alert={rTone === 'bad'} tone={rTone}>{rText}</Row>
      </div>
    </>
  )
}
