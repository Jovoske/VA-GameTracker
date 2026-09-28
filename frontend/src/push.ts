import { api } from './api'
import { t } from './i18n'

/**
 * Web Push, browser side.
 *
 * The server generates its VAPID key pair once and hands the public half out in
 * the notification settings. Subscribing binds this browser to that key, so if
 * the key ever changes the old subscription is dropped and a fresh one made:
 * pushes signed with a different key are rejected by the push service and the
 * phone would simply go quiet with no error anyone could see.
 *
 * iPhone: Safari delivers web push only to an app installed on the Home Screen
 * (iOS 16.4+), never to a tab. That is the single most likely reason this does
 * nothing on a phone, so it gets its own message.
 *
 * Both halves have to hold: this browser's subscription, and the server's copy of
 * it. The server used to lose its copy after a night of network errors while the
 * phone still had its own, and Settings said "This phone gets alerts" to a phone
 * getting nothing (audit D-04). So the app sends its subscription every time it
 * opens (checkThisDevice), which puts the server's copy back, and Settings says
 * what that check found. Signing out takes the subscription with it (D-17).
 */
export type Support = { ok: true } | { ok: false; reason: string }

function iosDevice(): boolean {
  return /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

/**
 * Pushes to this device go through Apple's push service (an iPhone or iPad, or
 * Safari on a Mac). It sounds every push as a new banner, so the server doesn't send
 * it the quiet updates inside the two-hour cooldown (notifications/push.py, apple),
 * and Settings says where the running total is instead.
 */
export function applePush(): boolean {
  const ua = navigator.userAgent
  return iosDevice() || (/Macintosh/.test(ua) && /Safari\//.test(ua) && !/Chrome|Chromium|Edg|Firefox/.test(ua))
}

export function pushSupport(): Support {
  if (!window.isSecureContext) {
    return {
      ok: false,
      reason: t('push.needHttps'),
    }
  }
  const ios = iosDevice()
  const standalone =
    window.matchMedia?.('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  if (ios && !standalone) {
    return {
      ok: false,
      reason: t('push.iphone'),
    }
  }
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    return { ok: false, reason: t('push.unsupported') }
  }
  return { ok: true }
}

export function permission(): NotificationPermission | 'unsupported' {
  return 'Notification' in window ? Notification.permission : 'unsupported'
}

function keyBytes(base64url: string): Uint8Array {
  const pad = '='.repeat((4 - (base64url.length % 4)) % 4)
  const b64 = (base64url + pad).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(b64)
  const out = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

function sameKey(a: ArrayBuffer | null | undefined, b: Uint8Array): boolean {
  if (!a || a.byteLength !== b.byteLength) return false
  const v = new Uint8Array(a)
  for (let i = 0; i < v.length; i++) if (v[i] !== b[i]) return false
  return true
}

async function registration(): Promise<ServiceWorkerRegistration> {
  const existing = await navigator.serviceWorker.getRegistration()
  if (existing) return existing
  await navigator.serviceWorker.register('/sw.js')
  return navigator.serviceWorker.ready
}

/** This browser's live subscription, if it has one. Never throws. */
export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null
  try {
    const reg = await navigator.serviceWorker.getRegistration()
    return reg ? await reg.pushManager.getSubscription() : null
  } catch {
    return null
  }
}

/** What checkThisDevice found: subscribed on both sides; subscribed here but the
 *  server couldn't be reached to say so; not subscribed; or push can't work here. */
export type DeviceState = 'subscribed' | 'unconfirmed' | 'not_subscribed' | 'unsupported'
type Registered = { subscriptions: number; public_key: string; enabled: boolean }

async function register(sub: PushSubscription): Promise<Registered> {
  const json = sub.toJSON()
  return api<Registered>('/notifications/subscriptions', {
    method: 'POST',
    body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys, user_agent: navigator.userAgent }),
    timeoutMs: 15_000,
  })
}

/**
 * Ask for permission straight from the tap, before anything else is awaited.
 *
 * iPhones show the prompt only while the tap is fresh; waiting for a save on a weak
 * signal first could lose it and say "Permission was not given" with no prompt ever
 * shown (audit D-19). Start this first, then pass it to subscribeThisDevice.
 */
export function askPermission(): Promise<NotificationPermission> {
  try {
    return Notification.requestPermission()
  } catch (e) {
    return Promise.reject(e)
  }
}

/** Ask permission (unless already asked), subscribe under the server's key, and
 *  register the endpoint. */
export async function subscribeThisDevice(publicKey: string, asked?: Promise<NotificationPermission>): Promise<void> {
  const perm = await (asked ?? askPermission())
  if (perm !== 'granted') {
    throw new Error(
      perm === 'denied' ? t('push.blocked') : t('push.notGiven'),
    )
  }
  const reg = await registration()
  const key = keyBytes(publicKey)
  let sub = await reg.pushManager.getSubscription()
  if (sub && !sameKey(sub.options.applicationServerKey, key)) {
    await sub.unsubscribe().catch(() => {})
    sub = null
  }
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: key.buffer as ArrayBuffer,
    })
  }
  await register(sub)
}

let checking: Promise<DeviceState> | null = null

/**
 * The self-heal: send this browser's subscription again (the server keeps one row
 * per endpoint, so it is harmless) and say what came of it. Run as the app opens,
 * and again from Settings. A subscription made under an older server key is made
 * again under the new one; permission is already given, so no prompt.
 */
export function checkThisDevice(): Promise<DeviceState> {
  if (!checking) {
    checking = (async (): Promise<DeviceState> => {
      if (!pushSupport().ok) return 'unsupported'
      if (permission() !== 'granted') return 'not_subscribed'
      let sub = await currentSubscription()
      if (!sub) return 'not_subscribed'
      let got: Registered
      try {
        got = await register(sub)
      } catch {
        return 'unconfirmed'
      }
      const key = keyBytes(got.public_key)
      if (!sameKey(sub.options.applicationServerKey, key)) {
        try {
          await sub.unsubscribe().catch(() => {})
          const reg = await registration()
          sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key.buffer as ArrayBuffer })
          await register(sub)
        } catch {
          return 'not_subscribed'
        }
      }
      return 'subscribed'
    })().finally(() => { checking = null })
  }
  return checking
}

/** The service worker says the browser replaced this phone's subscription
 *  (pushsubscriptionchange): it can't sign in, so the page sends the new one. */
export function listenForNewSubscriptions(): () => void {
  if (!('serviceWorker' in navigator)) return () => {}
  const on = (e: MessageEvent) => {
    if (e.data?.type === 'gs-push-changed') void checkThisDevice()
  }
  navigator.serviceWorker.addEventListener('message', on)
  return () => navigator.serviceWorker.removeEventListener('message', on)
}

/**
 * Signing out: this phone stops getting that person's alerts (audit D-17, I-21).
 *
 * The server's copy is removed with the token of the person leaving, since the
 * sign-in is gone a moment later, and the browser's own is dropped. Best effort and
 * never in the way: with no signal the sign-out still happens at once, and a push to
 * the dropped subscription is refused by the push service, which removes the
 * server's copy then.
 */
export function forgetThisDevice(token: string | null): void {
  void currentSubscription().then(async (sub) => {
    if (!sub) return
    if (token) {
      const ctl = new AbortController()
      const timer = window.setTimeout(() => ctl.abort(), 5000)
      fetch('/api/notifications/subscriptions', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ endpoint: sub.endpoint }),
        keepalive: true,
        signal: ctl.signal,
      }).catch(() => {}).finally(() => window.clearTimeout(timer))
    }
    await sub.unsubscribe().catch(() => {})
  }).catch(() => {})
}

/** Drop this browser's subscription on both sides. Quiet if there is none. */
export async function unsubscribeThisDevice(): Promise<void> {
  const sub = await currentSubscription()
  if (!sub) return
  const endpoint = sub.endpoint
  await sub.unsubscribe().catch(() => {})
  await api('/notifications/subscriptions', {
    method: 'DELETE',
    body: JSON.stringify({ endpoint }),
  }).catch(() => {})
}
