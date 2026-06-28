#!/usr/bin/env python3
"""JSON control-plane for the tmux conductor — the data/control API that the
Even Hub glasses PLUGIN (Path B) consumes. Clean JSON + SSE over the existing
tmux_conductor functions. Separate from even_conductor_server.py (the Path-A
OpenAI/Add-Agent text bridge).

Pane ids in URLs are the NUMBER only (no '%'), because '%' is URL-encoding —
e.g. pane '%29' -> /api/panes/29/screen. The server re-adds the '%'.

Endpoints:
  GET  /api/health
  GET  /api/panes[?claude_only=1]                 -> {panes:[...]}
  GET  /api/panes/<n>/screen[?lines=200]          -> {id, text}
  GET  /api/panes/<n>/conversation                -> {id, turns:[{role,text}...], working}
  GET  /api/windows                               -> {windows:[{index,name,panes}]}
  POST /api/panes/<n>/send  {text, submit=true}   -> {ok, pane, submitted}
  POST /api/panes/<n>/keys  {keys}                -> {ok, pane, keys}
  POST /api/new-session     {path|text, tag?}     -> {ok, pane, n, cwd, how}
  GET  /api/events/<n>[?lines=40]                 -> SSE stream of the pane screen on change

Run:  python conductor_api.py
Bind: defaults to your Tailscale IP (tailscale ip -4), port 8790.
Env:  CONDUCTOR_TOKEN (optional bearer), CONDUCTOR_API_PORT, CONDUCTOR_BIND.
"""
import hmac
import json
import os
import re
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import tmux_conductor as tc

# parallelize the per-pane `capture-pane` forks in /api/panes (one per idle Claude
# pane) so their latency overlaps instead of summing on the 5s fleet poll.
_POOL = ThreadPoolExecutor(max_workers=8)

TOKEN = os.environ.get("CONDUCTOR_TOKEN", "")
TMUX_SESSION = os.environ.get("CONDUCTOR_TMUX_SESSION", "0")
# command typed into a freshly-spawned pane to start a session (override per-user,
# e.g. a shell fn that pins a Claude profile). Default = plain `claude`.
LAUNCH_CMD = os.environ.get("CONDUCTOR_LAUNCH_CMD", "claude")


# A pane is "waiting" (needs you) when an interactive prompt/menu is on screen.
_WAIT_RE = re.compile(r"(?:to navigate|to select|esc to cancel|\(y/n\)|\[y/n\]|\by/n\b|press enter to continue)", re.I)


def _pane_status(p):
    st = tc.session_status(p)
    if st == "idle" and p["is_claude"]:
        try:
            if _WAIT_RE.search(tc.capture_pane(p["pane_id"], 16)):
                return "waiting"
        except Exception:
            pass
    return st


def pane_view(p):
    return {
        "id": p["pane_id"],
        "n": p["pane_id"].lstrip("%"),
        "window": p["window_index"],
        "window_name": p["window_name"],
        "pane_index": p["pane_index"],
        "title": p["title"],
        "label": tc.session_label(p),
        "tag": tc.window_tag(p),
        "status": _pane_status(p),
        "cwd": p["path"],
        "is_claude": p["is_claude"],
        "is_conductor": p["is_conductor"],
    }


def find_pane(n):
    pane_id = "%" + str(n)
    for p in tc.list_panes():
        if p["pane_id"] == pane_id:
            return p
    return None


# --- AI: turn a spoken description into a shell command (for non-claude panes) ---

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _anthropic_key():
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_API_GEMA"):
        v = os.environ.get(name, "")
        if v.startswith("sk-ant-"):
            return v
    try:
        with open(os.path.expanduser("~/.env")) as f:
            for ln in f:
                ln = ln.strip()
                if ln.startswith("export "):
                    ln = ln[7:]
                if "=" in ln:
                    val = ln.split("=", 1)[1].strip().strip('"').strip("'")
                    if val.startswith("sk-ant-"):
                        return val
    except FileNotFoundError:
        pass
    return None


def translate_command(description, cwd):
    """Turn a natural-language description into a single shell command via Claude."""
    key = _anthropic_key()
    if not key:
        raise RuntimeError("no Anthropic key (set ANTHROPIC_API_KEY or ~/.env)")
    system = (
        "Convert the user's request into ONE shell command for bash to run in "
        + (cwd or "~") + ". Output ONLY the command on a single line — no prose, "
        "no markdown, no backticks."
    )
    payload = {
        "model": os.environ.get("CONDUCTOR_MODEL", "claude-opus-4-8"),
        "max_tokens": 300,
        "system": system,
        "messages": [{"role": "user", "content": description}],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return text.strip().strip("`").strip()


WHISPER_USD_PER_MIN = 0.006  # OpenAI whisper-1 pricing


def wav_seconds(audio):
    """Duration of a PCM16 mono WAV (our recorder's format): data bytes / (rate*2)."""
    try:
        rate = int.from_bytes(audio[24:28], "little")
        data = int.from_bytes(audio[40:44], "little")
        if rate and data:
            return data / (rate * 2)
    except Exception:
        pass
    return 0.0


def whisper_transcribe(audio):
    """Transcribe WAV audio bytes via OpenAI Whisper. Key from OPENAI_API_KEY."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key.startswith("sk-"):
        raise RuntimeError("no OPENAI_API_KEY in environment")
    boundary = "----conductor-" + str(int(time.time() * 1000))
    crlf = b"\r\n"
    bb = boundary.encode()

    def field(name, value):
        return (b"--" + bb + crlf
                + ('Content-Disposition: form-data; name="%s"' % name).encode() + crlf + crlf
                + value.encode() + crlf)

    body = field("model", "whisper-1") + field("response_format", "json")
    body += (b"--" + bb + crlf
             + b'Content-Disposition: form-data; name="file"; filename="audio.wav"' + crlf
             + b"Content-Type: audio/wav" + crlf + crlf + audio + crlf
             + b"--" + bb + b"--" + crlf)
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions", data=body,
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "multipart/form-data; boundary=" + boundary}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode()).get("text", "").strip()


# --- new session: resolve a spoken folder -> dir, spawn a pane in window 1 ---

def resolve_folder(spoken):
    s = (spoken or "").strip().rstrip(".")
    if not s:
        return None
    cand = os.path.expanduser(s)
    if os.path.isdir(cand):
        return os.path.abspath(cand)
    norm = re.sub(r"[\s_\-]", "", s.lower())
    bases, seen = [], set()
    for root in ("~/projects", "~/Documents", "~"):
        r = os.path.expanduser(root)
        try:
            for d in sorted(os.listdir(r)):
                p = os.path.join(r, d)
                if os.path.isdir(p) and p not in seen:
                    seen.add(p)
                    bases.append(p)
        except OSError:
            pass
    for p in tc.list_panes():
        if os.path.isdir(p["path"]) and p["path"] not in seen:
            seen.add(p["path"])
            bases.append(p["path"])
    named = [(re.sub(r"[\s_\-]", "", os.path.basename(b).lower()), b) for b in bases]
    for name, b in named:  # exact basename first
        if name and name == norm:
            return os.path.abspath(b)
    for name, b in named:  # then contains
        if name and (norm in name or name in norm):
            return os.path.abspath(b)
    return None


def list_windows():
    """All windows (project tags) in the conductor's tmux session."""
    out = tc._run(["list-windows", "-t", TMUX_SESSION, "-F", "#{window_index}\t#{window_name}\t#{window_panes}"])
    wins = []
    for line in out.stdout.splitlines():
        p = line.split("\t")
        if len(p) >= 3 and p[0].isdigit() and p[2].isdigit():  # skip malformed rows
            wins.append({"index": int(p[0]), "name": p[1], "panes": int(p[2])})
    return wins


def _session_exists():
    return tc._run(["has-session", "-t", TMUX_SESSION]).returncode == 0


def create_session(folder, tag=None):
    """Open a Claude session in `folder` under a project `tag` (tmux window): if a
    window named `tag` exists, add the session as a new pane there; otherwise open a
    new window named `tag` (or the folder's basename). On a fresh machine with NO tmux
    session yet, create the session itself with this as its first window. Returns
    (pane_id, how)."""
    have = _session_exists()
    idx = None
    if tag and have:
        for w in list_windows():
            if w["name"] == tag:
                idx = w["index"]
                break
    out, how = None, ""
    if idx is not None:
        out = tc._run(["split-window", "-t", f"{TMUX_SESSION}:{idx}", "-c", folder, "-P", "-F", "#{pane_id}"])
        how = f"pane in '{tag}'"
    if out is None or out.returncode != 0:  # no existing tag, that window is full, or no server yet
        name = (tag or os.path.basename(folder.rstrip("/")) or "claude")[:20]
        if not have:
            # fresh machine: no tmux session -> create it with this as the first window
            out = tc._run(["new-session", "-d", "-s", TMUX_SESSION, "-n", name, "-c", folder, "-P", "-F", "#{pane_id}"])
            how = f"new session '{name}'"
        else:
            # NOTE: target "0:" (trailing colon = the SESSION) so tmux appends at the next
            # free index. Bare "0" is read as window-index 0 → "index 0 in use" / wrong slot.
            out = tc._run(["new-window", "-t", f"{TMUX_SESSION}:", "-c", folder, "-n", name, "-P", "-F", "#{pane_id}"])
            how = f"new window '{name}'"
        if out.returncode != 0:
            raise RuntimeError((out.stderr or out.stdout).strip() or "could not create pane or window")
    pane = out.stdout.strip()
    # start the session (CONDUCTOR_LAUNCH_CMD, default `claude`; the new pane's
    # interactive shell resolves shell functions/aliases like a custom profile launcher).
    tc._run(["send-keys", "-t", pane, LAUNCH_CMD, "Enter"])
    return pane, how


class Handler(BaseHTTPRequestHandler):
    timeout = 30  # drop slow/half-open connections so they can't pin threads (slowloris)

    # --- helpers ---
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        # token is REQUIRED in every mode (no default-open); main() refuses to start
        # without one. Bearer header, or ?token= for SSE (EventSource can't set headers).
        tok = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not tok:
            tok = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        # compare BYTES: hmac.compare_digest on two str raises TypeError on non-ASCII
        # input (e.g. ?token=%C3%A9), which would abort the request thread.
        return bool(TOKEN) and hmac.compare_digest(tok.encode(), TOKEN.encode())  # constant-time

    def _body(self):
        n = int(self.headers.get("content-length", 0))
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return None

    def log_message(self, *a):
        pass

    # --- GET ---
    def do_OPTIONS(self):  # CORS preflight for POSTs from the phone webview
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "authorization, content-type")
        self.send_header("content-length", "0")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        if path == "/api/health":
            # advertise whether voice works (OpenAI key present) so the app can gate
            # the talk gesture instead of failing on transcribe. No secret leaked.
            voice = os.environ.get("OPENAI_API_KEY", "").startswith("sk-")
            return self._json(200, {"ok": True, "service": "conductor-api", "voice": voice})
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})
        if path == "/api/panes":
            claude_only = q.get("claude_only", ["0"])[0] in ("1", "true")
            panes = tc.list_panes(claude_only=claude_only)
            views = list(_POOL.map(pane_view, panes)) if panes else []  # captures run concurrently
            return self._json(200, {"panes": views})
        if path == "/api/windows":
            return self._json(200, {"windows": list_windows()})
        m = re.fullmatch(r"/api/panes/(\d+)/screen", path)
        if m:
            p = find_pane(m.group(1))
            if not p:
                return self._json(404, {"error": "no such pane"})
            lines = int(q.get("lines", ["200"])[0])
            return self._json(200, {"id": p["pane_id"], "text": tc.capture_pane(p["pane_id"], lines)})
        m = re.fullmatch(r"/api/panes/(\d+)/conversation", path)
        if m:
            p = find_pane(m.group(1))
            if not p:
                return self._json(404, {"error": "no such pane"})
            sess = tc.resolve_session(p)
            if sess is not None:
                # exact session identified: use ITS transcript. jsonl=None means a
                # brand-new session with no turns yet -> show empty, NEVER fall back
                # to "newest in folder" (that's a different session's conversation).
                jsonl = sess.get("jsonl")
                working = sess.get("status") == "busy"
            else:
                # couldn't identify the session -> best-effort newest transcript in cwd
                cands = tc.transcript_candidates(p["path"], p["pid"])
                jsonl = str(cands[0]) if cands else None
                working = _pane_status(p) == "working"
            # etag = transcript identity + working flag, passed back via ?etag=. When it
            # matches, return a tiny {notModified} 200 (skip read/parse/serialize) — a
            # plain 200 (not HTTP 304) so the WebView's fetch never sees a bare 304.
            etag = None
            if jsonl:
                try:
                    st = os.stat(jsonl)
                    etag = f"{st.st_mtime_ns}-{st.st_size}-{int(working)}"
                except OSError:
                    pass
            if etag and q.get("etag", [""])[0] == etag:
                return self._json(200, {"id": p["pane_id"], "notModified": True, "etag": etag})
            turns = tc.read_conversation(jsonl) if jsonl else []
            return self._json(200, {"id": p["pane_id"], "turns": turns, "working": working, "etag": etag})
        m = re.fullmatch(r"/api/events/(\d+)", path)
        if m:
            return self._sse_screen(m.group(1), int(q.get("lines", ["40"])[0]))
        self._json(404, {"error": "not_found", "path": path})

    # --- POST ---
    def do_POST(self):
        path = urlparse(self.path).path
        if not self._authed():
            return self._json(401, {"error": "unauthorized"})
        if path == "/api/transcribe":  # raw WAV body -> Whisper (read before JSON parse)
            n = int(self.headers.get("content-length", 0))
            audio = self.rfile.read(n)
            try:
                secs = wav_seconds(audio)
                return self._json(200, {
                    "text": whisper_transcribe(audio),
                    "seconds": round(secs, 1),
                    "cost": round(secs / 60 * WHISPER_USD_PER_MIN, 4),
                })
            except Exception as e:
                return self._json(502, {"error": str(e)})
        body = self._body()
        if body is None:
            return self._json(400, {"error": "invalid JSON"})
        m = re.fullmatch(r"/api/panes/(\d+)/send", path)
        if m:
            p = find_pane(m.group(1))
            if not p:
                return self._json(404, {"error": "no such pane"})
            text = body.get("text", "")
            if not text:
                return self._json(400, {"error": "text required"})
            r = tc.send_text(p["pane_id"], text, submit=bool(body.get("submit", True)))
            return self._json(200, {"ok": True, **r})
        m = re.fullmatch(r"/api/panes/(\d+)/keys", path)
        if m:
            p = find_pane(m.group(1))
            if not p:
                return self._json(404, {"error": "no such pane"})
            keys = body.get("keys")
            if not keys:
                return self._json(400, {"error": "keys required"})
            return self._json(200, {"ok": True, **tc.send_keys(p["pane_id"], keys)})
        if path == "/api/translate":
            desc = body.get("description", "")
            if not desc:
                return self._json(400, {"error": "description required"})
            try:
                return self._json(200, {"command": translate_command(desc, body.get("cwd", ""))})
            except Exception as e:
                return self._json(502, {"error": str(e)})
        if path == "/api/resolve-folder":
            f = resolve_folder(body.get("text", ""))
            return self._json(200, {"found": bool(f), "path": f or "", "query": body.get("text", "")})
        if path == "/api/new-session":
            f = body.get("path") or resolve_folder(body.get("text", ""))
            if not f or not os.path.isdir(f):
                return self._json(400, {"error": "folder not found", "query": body.get("text", "")})
            try:
                # sanitize the spoken tag -> a safe tmux window name (no tabs/newlines/
                # control chars that would corrupt the tab-delimited list-panes parse)
                tag = re.sub(r"[^\w.-]", "", (body.get("tag") or "").strip()) or None
                pane, how = create_session(f, tag)
                return self._json(200, {"ok": True, "pane": pane, "n": pane.lstrip("%"), "cwd": f, "how": how})
            except Exception as e:
                return self._json(502, {"error": str(e)})
        self._json(404, {"error": "not_found", "path": path})

    # --- SSE: stream a pane's screen whenever it changes ---
    def _sse_screen(self, n, lines):
        p = find_pane(n)
        if not p:
            return self._json(404, {"error": "no such pane"})
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        last = None
        try:
            for _ in range(36000):  # ~10h cap at 1s
                screen = tc.capture_pane(p["pane_id"], lines)
                if screen != last:
                    last = screen
                    payload = json.dumps({"id": p["pane_id"], "text": screen})
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                time.sleep(1)
        except (BrokenPipeError, ConnectionResetError):
            return


def tailscale_ip():
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.split()
        return out[0] if out else None
    except Exception:
        return None


def main():
    port = int(os.environ.get("CONDUCTOR_API_PORT", "8790"))
    # fail closed: this control plane runs commands on the box, and loopback is NOT
    # user-isolated on Linux — so require a token in EVERY mode, and default to loopback.
    if not TOKEN:
        raise SystemExit("refusing to start without CONDUCTOR_TOKEN — this runs commands on your machine; set a token.")
    bind = os.environ.get("CONDUCTOR_BIND") or tailscale_ip() or "127.0.0.1"
    print(f"conductor-api on http://{bind}:{port}  (token required)")
    ThreadingHTTPServer((bind, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
