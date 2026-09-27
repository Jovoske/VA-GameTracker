import { Link } from 'react-router-dom'
import { ageLabel } from '../api'
import { fmtList, t } from '../i18n'

/** How current the photos behind the plan are (forecast_tonight's `freshness`). */
export type Freshness = {
  newest_photo_at: string | null
  last_fetch_ok_at: string | null
  // "login": some camera login is failing or stalled; "stopped": no fetch works at all.
  problem: 'login' | 'stopped' | null
  logins: string[]
}

/**
 * One plain line when the plan rests on photos that have stopped coming in.
 *
 * "Plan from just now" says when the answer was worked out, not how old its photos
 * are: with a login broken or the scheduled fetch stopped, a fresh-looking plan can
 * rest on photos days old. Says nothing at all when photos are coming in.
 */
export default function PhotoFreshness({ freshness }: { freshness?: Freshness | null }) {
  if (!freshness?.problem) return null
  const newest = freshness.newest_photo_at ? ` ${t('fresh.newest', { ago: ageLabel(freshness.newest_photo_at) })}` : ''
  const text = freshness.problem === 'stopped'
    ? freshness.last_fetch_ok_at ? t('fresh.stoppedSince', { ago: ageLabel(freshness.last_fetch_ok_at) }) : t('fresh.stopped')
    : t('fresh.loginsNot', { names: fmtList(freshness.logins) })
  return (
    <p className="tn-fresh tn-fresh--photos" data-stale="true" role="status">
      {text}{newest}{' '}
      <Link to="/settings#accounts">{t('fresh.cameraLogins')}</Link>
    </p>
  )
}
