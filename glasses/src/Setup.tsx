import { useState, useRef, useEffect, type CSSProperties } from 'react'
import { getConfig, setConfig } from './config'
import { listPanes } from './api'
import jsQR from 'jsqr'

// Decode the `tmuxor:<base64>` blob that install.sh prints (paste OR QR) into a config.
function decodeBlob(text: string): { base: string; token: string } | null {
  try {
    const raw = text.trim().replace(/^tmuxor:/, '').replace(/-/g, '+').replace(/_/g, '/')
    const o = JSON.parse(atob(raw))
    const base = (o.base || '').trim(); const token = (o.token || '').trim()
    if (!/^https:\/\/.+/i.test(base) || !token) return null
    return { base, token }
  } catch { return null }
}

// Phone-side settings form. Each user points the app at THEIR OWN backend with THEIR
// OWN token — nothing is shipped in the app. Fastest path: scan the QR install.sh prints.
export function Setup({ onSave, onCancel }: { onSave: () => void; onCancel?: () => void }) {
  const c = getConfig()
  const [base, setBase] = useState(c.base)
  const [token, setToken] = useState(c.token)
  const [blob, setBlob] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [scanning, setScanning] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const rafRef = useRef<number>(0)

  // Test the connection before declaring success, so a wrong URL/token/down backend fails
  // HERE (on the phone) instead of dropping the user into an "offline" glasses screen.
  const connect = async (b: string, t: string) => {
    setErr(''); setBusy(true)
    setConfig({ base: b, token: t })
    try {
      await listPanes()
      onSave()
    } catch (e) {
      const msg = String((e as Error)?.message || e)
      setErr(/\b401\b/.test(msg) ? 'Token rejected — check your CONDUCTOR_TOKEN.'
        : "Can't reach the backend — check the URL, and that the service + `tailscale serve` are running.")
    } finally { setBusy(false) }
  }

  const stopScan = () => {
    cancelAnimationFrame(rafRef.current)
    streamRef.current?.getTracks().forEach((tr) => tr.stop())
    streamRef.current = null
    setScanning(false)
  }

  // Scan the QR off the laptop's install.sh output — no cross-device typing/pasting.
  const startScan = async () => {
    setErr('')
    if (!navigator.mediaDevices?.getUserMedia) { setErr('Camera not available here — paste the config code below.'); return }
    setScanning(true)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
      streamRef.current = stream
      const v = videoRef.current!
      v.srcObject = stream
      await v.play()
      const canvas = document.createElement('canvas')
      const tick = () => {
        if (!streamRef.current) return
        if (v.readyState === v.HAVE_ENOUGH_DATA && v.videoWidth) {
          canvas.width = v.videoWidth; canvas.height = v.videoHeight
          const cx = canvas.getContext('2d')!
          cx.drawImage(v, 0, 0, canvas.width, canvas.height)
          const img = cx.getImageData(0, 0, canvas.width, canvas.height)
          const code = jsQR(img.data, img.width, img.height)
          const cfg = code?.data ? decodeBlob(code.data) : null
          if (cfg) { stopScan(); connect(cfg.base, cfg.token); return }
        }
        rafRef.current = requestAnimationFrame(tick)
      }
      rafRef.current = requestAnimationFrame(tick)
    } catch {
      stopScan()
      setErr('Camera unavailable or denied — paste the config code below instead.')
    }
  }

  useEffect(() => () => stopScan(), []) // stop the camera if the screen unmounts

  const applyBlob = () => { const cfg = decodeBlob(blob); cfg ? connect(cfg.base, cfg.token) : setErr('That config code is not valid — copy the whole line from install.sh.') }
  const save = () => {
    const b = base.trim()
    if (!/^https:\/\/.+/i.test(b)) { setErr('Backend URL must start with https://'); return }
    if (!token.trim()) { setErr('An access token is required (set CONDUCTOR_TOKEN on your backend).'); return }
    connect(b, token.trim())
  }

  const wrap: CSSProperties = { background: '#0b0f0c', color: '#d6ffe6', minHeight: '100vh', padding: 20, fontFamily: 'system-ui, sans-serif', boxSizing: 'border-box' }
  const label: CSSProperties = { display: 'block', fontSize: 13, color: '#7fd9a6', margin: '16px 0 6px' }
  const input: CSSProperties = { width: '100%', padding: '12px 14px', fontSize: 16, borderRadius: 10, border: '1px solid #1f6e45', background: '#0f1712', color: '#e8fff1', boxSizing: 'border-box' }
  const btn: CSSProperties = { marginTop: 14, width: '100%', padding: '14px', fontSize: 16, fontWeight: 600, borderRadius: 10, border: 'none', background: '#16c46a', color: '#04130a', opacity: busy ? 0.6 : 1 }
  const ghost: CSSProperties = { ...btn, background: 'transparent', color: '#88a895', border: '1px solid #1f6e45' }
  const divider: CSSProperties = { display: 'flex', alignItems: 'center', gap: 10, margin: '22px 0 0', color: '#5f7a6b', fontSize: 12 }
  const rule: CSSProperties = { flex: 1, height: 1, background: '#1f6e45' }

  return (
    <div style={wrap}>
      <h2 style={{ margin: 0, fontSize: 20 }}>TMUXor — Setup</h2>
      <p style={{ color: '#88a895', fontSize: 13, lineHeight: 1.4 }}>
        Run <code>install.sh</code> on your computer, then scan the QR it prints. Everything stays on this phone.
      </p>

      {scanning ? (
        <div>
          <video ref={videoRef} playsInline muted style={{ width: '100%', borderRadius: 12, background: '#000', aspectRatio: '1 / 1', objectFit: 'cover' }} />
          <p style={{ color: '#88a895', fontSize: 13, textAlign: 'center', margin: '8px 0 0' }}>Point at the QR code from install.sh…</p>
          <button style={ghost} onClick={stopScan}>Cancel scan</button>
        </div>
      ) : (
        <button style={{ ...btn, marginTop: 18 }} onClick={startScan} disabled={busy}>{busy ? 'Connecting…' : '📷 Scan QR code'}</button>
      )}

      <div style={divider}><div style={rule} /> or paste the code <div style={rule} /></div>
      <textarea style={{ ...input, marginTop: 8, minHeight: 54, resize: 'vertical', fontFamily: 'monospace', fontSize: 13 }}
        value={blob} onChange={(e) => { setBlob(e.target.value); setErr('') }} placeholder="tmuxor:…" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
      <button style={btn} onClick={applyBlob} disabled={busy}>Paste config &amp; connect</button>

      <div style={divider}><div style={rule} /> or enter manually <div style={rule} /></div>
      <label style={label} htmlFor="cfg-url">Backend URL (your Tailscale HTTPS address)</label>
      <input id="cfg-url" type="url" inputMode="url" style={input} value={base} onChange={(e) => { setBase(e.target.value); setErr('') }} placeholder="https://your-host.tailnet.ts.net" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
      <label style={label} htmlFor="cfg-token">Access token (your CONDUCTOR_TOKEN)</label>
      <input id="cfg-token" type="password" style={input} value={token} onChange={(e) => { setToken(e.target.value); setErr('') }} placeholder="paste your token" autoCapitalize="off" autoCorrect="off" spellCheck={false} />

      {err && <p style={{ color: '#ff8a8a', fontSize: 13 }}>{err}</p>}
      <button style={btn} onClick={save} disabled={busy}>{busy ? 'Connecting…' : 'Save & connect'}</button>
      {onCancel && <button style={ghost} onClick={onCancel} disabled={busy}>Cancel</button>}
    </div>
  )
}
