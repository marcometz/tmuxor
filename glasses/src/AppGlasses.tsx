import { useEffect, useSyncExternalStore } from 'react'
import { useGlasses } from 'even-toolkit/useGlasses'
import { waitForEvenAppBridge } from '@evenrealities/even_hub_sdk'
import {
  getSnapshot, subscribe, refresh,
  openPane, closePane, scrollDetail, startVoice, stopVoice, cancelInput,
  redoVoice, sendNow, scrollConfirm,
  pickMenuOption, submitMenu,
  startNewSession, moveNewTag, chooseNewTag, stopNewTagVoice, stopNewVoice, retryNewVoice, createNewSession, cancelNewSession,
  type AppState,
} from './store'
import { router, type Ctx } from './screens'

// root double-tap -> hand off to the foreground layer's system exit dialog (exitMode 1)
const exitApp = () => { waitForEvenAppBridge().then((b) => b.shutDownPageContainer(1)).catch(() => {}) }

const ctx: Ctx = {
  exitApp,
  openPane, closePane, scrollDetail, startVoice, stopVoice, cancelInput,
  redoVoice, sendNow, scrollConfirm,
  pickMenuOption, submitMenu,
  startNewSession, moveNewTag, chooseNewTag, stopNewTagVoice, stopNewVoice, retryNewVoice, createNewSession, cancelNewSession,
}

export function App() {
  useSyncExternalStore(subscribe, getSnapshot) // re-render -> re-push glasses display on store change

  useEffect(() => {
    refresh()
    // poll the fleet only while the list is showing — while a pane is open the
    // conversation has its own poll, so skip ~30 capture-pane subprocesses/5s.
    const t = setInterval(() => { if (!getSnapshot().activePaneN) refresh() }, 5000)
    // When (re)launched — from the phone app menu OR the glasses menu — pull a fresh
    // fleet immediately so you don't wait for the next poll.
    let unsub: (() => void) | undefined
    waitForEvenAppBridge()
      .then((b) => { unsub = b.onLaunchSource((src) => { console.log('launched from', src); refresh() }) })
      .catch(() => {})
    // full teardown (SSE stream, conversation poll, mic) if App unmounts (e.g. Settings)
    return () => { clearInterval(t); unsub?.(); closePane() }
  }, [])

  useGlasses<AppState>({
    appName: 'TMUXor',
    getSnapshot,
    columns: [{ x: 0, w: 576 }], // single full-width column => flush-left, no 2-space prefix
    toDisplayData: (s, nav) => router.toDisplayData(s, nav),
    toColumns: (s, nav) => ({ columns: [router.toDisplayData(s, nav).lines.map((l) => l.text).join('\n')] }),
    onGlassAction: (a, nav, s) => router.onGlassAction(a, nav, s, ctx),
    deriveScreen: () => 'list',
    // Full-bleed columns mode for the live detail VIEW and the REVIEW transcript
    // (both want full width); styled text mode elsewhere (list/menu/listening).
    getPageMode: () => {
      const s = getSnapshot()
      if (!s.activePaneN || s.menu) return 'text'
      if (s.phase === 'view') return 'columns'
      if (s.phase === 'confirm' && !s.busy) return 'columns'
      return 'text'
    },
  })

  return null
}
