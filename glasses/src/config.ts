// Per-user connection config, stored in the WebView's localStorage so NOTHING is
// baked into the shipped app — every user points the app at their own backend with
// their own token. The build-time env fallback is used ONLY when VITE_PERSONAL=1
// (set in glasses/.env for a personal build); a PUBLIC build never reads it, so a
// forgotten "move .env aside" step can't leak the token into the hub package.
const LS_URL = 'conductor.baseUrl'
const LS_TOKEN = 'conductor.token'
const PERSONAL = !!import.meta.env.VITE_PERSONAL  // personal build only

export interface Config { base: string; token: string }

export function getConfig(): Config {
  const envBase = PERSONAL ? import.meta.env.VITE_CONDUCTOR_API : ''
  const envToken = PERSONAL ? import.meta.env.VITE_CONDUCTOR_TOKEN : ''
  const base = (localStorage.getItem(LS_URL) || envBase || '').replace(/\/+$/, '')
  const token = localStorage.getItem(LS_TOKEN) || envToken || ''
  return { base, token }
}
export function setConfig(c: Config) {
  localStorage.setItem(LS_URL, c.base.trim().replace(/\/+$/, ''))
  localStorage.setItem(LS_TOKEN, c.token.trim())
}
export function isConfigured(): boolean { const c = getConfig(); return !!c.base && !!c.token }
