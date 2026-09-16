import { api } from './api'

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
 */
export type Support = { ok: true } | { ok: false; reason: string }

export function pushSupport(): Support {
  if (!window.isSecureContext) {
    return {
      ok: false,
      reason: 'Notifications need an https connection. Open the app at its https address, not the LAN one.',
    }
  }
  const ua = navigator.userAgent
  const ios =
    /iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  const standalone =
    window.matchMedia?.('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  if (ios && !standalone) {
    return {
      ok: false,
      reason:
        'On iPhone, notifications only reach an installed app. In Safari, tap Share, then "Add to Home Screen", open GameSense from there and turn this on.',
    }
  }
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    return { ok: false, reason: 'This browser does not support web push notifications.' }
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

/** Ask permission, subscribe under the server's key, and register the endpoint. */
export async function subscribeThisDevice(publicKey: string): Promise<void> {
  const perm = await Notification.requestPermission()
  if (perm !== 'granted') {
    throw new Error(
      perm === 'denied'
        ? 'Notifications are blocked for GameSense. Allow them in your browser or phone settings, then try again.'
        : 'Permission was not given.',
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
  const json = sub.toJSON()
  await api('/notifications/subscriptions', {
    method: 'POST',
    body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys, user_agent: navigator.userAgent }),
  })
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
