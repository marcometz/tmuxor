import { useState, useSyncExternalStore, type CSSProperties } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router'
import { App } from './AppGlasses'
import { Setup } from './Setup'
import { getConfig, isConfigured } from './config'
import { subscribe, getSnapshot } from './store'

// Bottom bar reflects the live connection: green when reachable, "offline" when the
// fleet poll is erroring. Its own subscriber so only the bar re-renders, not <App/>.
function StatusBar({ onSettings }: { onSettings: () => void }) {
  const st = useSyncExternalStore(subscribe, getSnapshot)
  const online = !st.error
  const host = getConfig().base.replace(/^https:\/\//, '')
  const bar: CSSProperties = { position: 'fixed', bottom: 0, left: 0, right: 0, background: '#0b0f0c', color: online ? '#88a895' : '#ffb38a', padding: '12px 16px', fontFamily: 'system-ui, sans-serif', fontSize: 13, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid #173a26' }
  return (
    <div style={bar}>
      <span>{online ? `● driving glasses · ${host}` : `○ offline — check Settings · ${host}`}</span>
      <button onClick={onSettings} style={{ background: 'transparent', color: '#16c46a', border: '1px solid #1f6e45', borderRadius: 8, padding: '6px 12px', fontSize: 13 }}>Settings</button>
    </div>
  )
}

// Phone-side root: show the Setup form until the user has configured their own
// backend; then mount the glasses driver (App) and a small status/Settings bar.
// (App uses even-toolkit's useGlasses, which needs a Router — hence MemoryRouter.)
function Root() {
  const [editing, setEditing] = useState(!isConfigured())

  if (editing || !isConfigured()) {
    return <Setup onSave={() => setEditing(false)} onCancel={isConfigured() ? () => setEditing(false) : undefined} />
  }

  return (
    <>
      <MemoryRouter><App /></MemoryRouter>
      <StatusBar onSettings={() => setEditing(true)} />
    </>
  )
}

createRoot(document.getElementById('root')!).render(<Root />)
