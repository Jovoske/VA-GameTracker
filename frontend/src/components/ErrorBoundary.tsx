import { Component, type ErrorInfo, type ReactNode, useEffect, useState } from 'react'
import { Link, useRouteError } from 'react-router-dom'
import { forgetSaved } from '../api'
import { type ReloadResult, isChunkError, isReloading, reloadOnce, reportCrash } from '../crash'

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
    return { error: error ?? new Error('Unknown error'), why: isChunkError(error) ? 'checking' : null }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    if (isReloading()) return
    const chunk = isChunkError(error)
    const stack = `${(error as Error)?.stack ?? ''}\n${info.componentStack ?? ''}`.trim()
    reportCrash(chunk ? 'chunk' : 'render', error, stack)
    if (chunk) reloadOnce().then((why) => { if (this.state.error === error) this.setState({ why }) })
    // Pages paint their saved copy first; if that copy is what broke, the next try
    // would break the same way before it could ask for a fresh one.
    else forgetSaved()
  }

  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null, why: null })
  }

  render() {
    if (this.state.error) return <Crashed error={this.state.error} why={this.state.why} />
    return this.props.children
  }
}

/** For the router: a crash outside any page (the frame, the sign-in screen, Sit mode). */
export function RouteCrash() {
  const error = useRouteError()
  const [why, setWhy] = useState<Why>(() => (isChunkError(error) ? 'checking' : null))
  // The router caught it, so the window never saw it: report it here.
  useEffect(() => {
    if (isReloading()) return
    const chunk = isChunkError(error)
    reportCrash(chunk ? 'chunk' : 'render', error)
    if (chunk) reloadOnce().then(setWhy)
    else forgetSaved()
  }, [error])
  return (
    <div className="page" style={{ maxWidth: 560, margin: '0 auto' }}>
      <Crashed error={error} why={why} />
    </div>
  )
}

const CHUNK_WORDS: Record<string, string> = {
  checking: 'Getting the latest version of the app…',
  reloading: 'Getting the latest version of the app…',
  'no-signal': 'No signal, and this page isn’t saved on the phone yet. It opens once you have signal.',
  recent: 'The app was just updated and this page still didn’t load. Reload to try again.',
}

export function Crashed({ error, why = null }: { error: unknown; why?: Why }) {
  if (isReloading()) return <div className="status-panel" role="status">Opening the new version…</div>
  const chunk = isChunkError(error)
  return (
    <div className="crashed" role="alert">
      <h1 className="crashed-title">{chunk ? 'This page didn’t load.' : 'Something broke.'}</h1>
      <p className="crashed-text">
        {chunk ? CHUNK_WORDS[why ?? 'recent'] : 'It has been reported. Reload to carry on.'}
      </p>
      <button type="button" className="btn crashed-reload" onClick={() => location.reload()}>
        Reload
      </button>
      <Link className="text-action crashed-home" to="/">Go to Tonight</Link>
    </div>
  )
}
