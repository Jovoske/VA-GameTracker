import { Component, type ErrorInfo, type ReactNode, useEffect, useState } from 'react'
import { Link, useRouteError } from 'react-router-dom'
import { forgetSaved } from '../api'
import { type ReloadResult, isChunkError, isReloading, reloadOnce, reportCrash } from '../crash'
import { type Key, t, useLang } from '../i18n'

/**
 * The app never goes blank.
 *
 * A page that throws used to take the whole app with it: React unmounted
 * everything and the hunter was left with a black screen and no tab bar, and had
 * to kill the app (audit B-02, C-02, D-01). Now a page that breaks is replaced by
 * a short message with Reload, the tab bar stays, and moving to another tab clears
 * it. When the page broke because one of the app's own files didn't arrive (the
 * map after a deploy), it reloads once by itself to get the new build.
 */
type Why = ReloadResult | 'checking' | null

export class PageBoundary extends Component<{ resetKey: string; children: ReactNode }, { error: unknown; why: Why }> {
  state = { error: null as unknown, why: null as Why }

  static getDerivedStateFromError(error: unknown) {
    // i18n-ok: never on screen, only in the crash report.
    return { error: error ?? new Error('Unknown error'), why: isChunkError(error) ? 'checking' : null }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    if (isReloading()) return
    const chunk = isChunkError(error)
    const stack = `${(error as Error)?.stack ?? ''}\n${info.componentStack ?? ''}`.trim()
    reportCrash(chunk ? 'chunk' : 'render', error, stack)
    if (chunk) reloadOnce().then((why) => { if (this.state.error === error) this.setState({ why }) })
    // Pages paint their saved copy first; if that copy is what broke, the next try
    // would break the same way before it could ask for a fresh one. Only this
    // page's copies: the plan saved for tonight is not Photos' to throw away.
    else forgetSaved(location.pathname)
  }

  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null, why: null })
  }

  // "Go to Tonight" on Tonight itself goes nowhere (the reset above follows the
  // path), so Tonight is tried again here. Elsewhere the move to "/" clears it.
  retry = () => { if (location.pathname === '/') this.setState({ error: null, why: null }) }

  render() {
    if (this.state.error) return <Crashed error={this.state.error} why={this.state.why} onRetry={this.retry} />
    return this.props.children
  }
}

/** For the router: a crash outside any page (the frame, the sign-in screen, Sit mode). */
export function RouteCrash() {
  const error = useRouteError()
  // Outside App, so it follows the language itself.
  useLang()
  const [why, setWhy] = useState<Why>(() => (isChunkError(error) ? 'checking' : null))
  // The router caught it, so the window never saw it: report it here.
  useEffect(() => {
    if (isReloading()) return
    const chunk = isChunkError(error)
    reportCrash(chunk ? 'chunk' : 'render', error)
    if (chunk) reloadOnce().then(setWhy)
    else forgetSaved(location.pathname)
  }, [error])
  return (
    <div className="page" style={{ maxWidth: 560, margin: '0 auto' }}>
      <Crashed error={error} why={why} />
    </div>
  )
}

const CHUNK_WORDS: Record<string, Key> = {
  checking: 'crash.gettingLatest',
  reloading: 'crash.gettingLatest',
  'no-signal': 'crash.noSignal',
  server: 'crash.server',
  recent: 'crash.recent',
}

export function Crashed({ error, why = null, onRetry }: { error: unknown; why?: Why; onRetry?: () => void }) {
  if (isReloading()) return <div className="status-panel" role="status">{t('crash.opening')}</div>
  const chunk = isChunkError(error)
  return (
    <div className="crashed" role="alert">
      <h1 className="crashed-title">{chunk ? t('crash.pageDidntLoad') : t('crash.broke')}</h1>
      <p className="crashed-text">
        {chunk ? t(CHUNK_WORDS[why ?? 'recent']) : t('crash.reported')}
      </p>
      <button type="button" className="btn crashed-reload" onClick={() => location.reload()}>
        {t('common.reload')}
      </button>
      <Link className="text-action crashed-home" to="/" onClick={onRetry}>{t('crash.goTonight')}</Link>
    </div>
  )
}
