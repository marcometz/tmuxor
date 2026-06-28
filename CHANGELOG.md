# Changelog — TMUXor

User-facing changes per version. Newest first. Deeper technical notes live in the
project memory; this file is the short "what changed" for each build.

> Builds: each version ships as a **public** `.ehpk` (no baked secrets — users enter their
> own backend URL + token in Setup) and, when needed, a **`-personal`** `.ehpk` that bakes
> the owner's URL + token to skip Setup. The personal build contains a secret — never publish it.

## 1.3.0 — 2026-06-28
Fewer setup steps — scan to connect.
- **QR setup** — `install.sh` prints a scannable QR (and saves `~/tmuxor-setup-qr.png`); the
  Setup screen's **📷 Scan QR code** reads it with the phone camera and connects, so there's no
  cross-device typing or pasting of the URL + token. Paste and manual entry stay as fallbacks.
- Setup now leads with Scan → Paste → Manual (fastest path first).
- Adds the `camera` permission, used only to scan the setup QR.
- **Fresh-machine support (backend)** — with no tmux server running yet, the fleet list is
  empty instead of erroring, and "＋ new session" creates the tmux session itself (first run
  needs no pre-existing session). *(backend only — no app reinstall needed.)*

## 1.2.0 — 2026-06-28
Submission-readiness pass against Even's beta-testing checklist.
- **App exit** — double-tap on the session list now opens the system exit dialog
  (`shutDownPageContainer(1)`), matching Even's root-double-tap convention.
- **Wrap-around list scroll** — swiping up from the first row jumps to the last (and down
  from the last wraps to the first), so a long fleet is fast to traverse now that double-tap
  is the exit gesture.
- **Microphone permission** — a denied/unavailable mic is handled gracefully ("mic
  unavailable — check microphone permission") instead of an unhandled promise rejection.

## 1.1.0 — 2026-06-28
Hardening + optimization pass from a multi-agent code review (35 findings raised → 18
confirmed after adversarial verification → all fixed).

**Security**
- The token can no longer leak into a public build — the build-time credential fallback is
  gated behind a `VITE_PERSONAL` flag, so a public build never bakes secrets even if a
  packaging step is skipped.
- Auth no longer crashes on a non-ASCII token (compares bytes; returns a clean 401).

**Efficiency**
- Conversation polling is far cheaper: the backend memoizes the parsed transcript and returns
  a tiny "not modified" response when nothing changed (it used to re-read + re-parse the whole
  transcript every 2.5s); per-pane session resolution is now cached.
- `/api/panes` captures panes concurrently instead of one-at-a-time.
- The glasses app skips redundant identical screen pushes (conversation / fleet / activity),
  saving radio + battery on the wearable.

**UI/UX**
- Setup now actually tests the connection before declaring success — a wrong URL/token or down
  backend fails on the phone with a clear message instead of a silent "offline" later.
- Voice-off now explains itself when tapped (was a silent dead-end).
- Phone status bar reflects offline state; clearer menu back hint; new-session tag list shows
  loading/error; "Paste config" wording matches the installer; validation errors clear on edit;
  form labels/keyboard hints.

## 1.0.0 — 2026-06-28
- **Fresh hub project** under a new package id (`com.liyiyuian.tmuxor`) for a clean version history.
- **Much simpler setup** — a one-line `install.sh` stands up the backend (prereq check,
  auto-generated token, env file, `systemd --user` service, `tailscale serve`) and prints a
  Backend URL + token + a one-line config code.
- **Paste-to-connect** — the Setup screen accepts the installer's config code in one paste, so
  there's no thumb-typing the URL + token.
- **Voice is now optional** — the app works (read + tap) without an OpenAI key and shows
  "voice off"; add a key anytime to enable voice replies.
- **Public build whitelists Tailscale wildcards** (`https://*.ts.net`, `https://*.*.ts.net`) so any
  user reaches their own backend — pending Even accepting wildcards at review. (The personal build
  keeps the owner's exact domain.)
- QA'd against Even's docs: `app.json` validated field-by-field, build + pack clean, simulator smoke
  test, 0 console errors.

## 0.2.7 — 2026-06-27
- Version bump so the hub accepts a re-upload; produced separate **public** and
  **`-personal`** (creds-baked) builds. No functional change over 0.2.6.

## 0.2.6 — 2026-06-27
- **Reopening a session now jumps to the newest question if one arrived while you were
  away**; otherwise it resumes exactly where you left off (refines 0.2.5).

## 0.2.5 — 2026-06-27
- **Per-session scroll memory.** First time you open a session (after launching the app)
  it jumps to the most recent question so you catch up; reopening a session you'd been
  reading returns to your previous scroll position instead of snapping to top/bottom.

## 0.2.4 — 2026-06-26
- **Security hardening:** access token is now mandatory and the backend refuses to start
  without one (fail-closed); constant-time token check; defaults to loopback bind.
- Reliability: fixed resource leaks (voice/stream/poll cleanup when leaving a session).
- UI polish: gesture hints on every screen, tag shown before title in the list, consistent
  status bar (waiting · working · idle).

## 0.2.3 — 2026-06-26
- **New-session "tag" flow:** when starting a session you first pick (or speak) a tmux
  window/tag, then speak the folder — so new sessions land in the project group you want.

## 0.2.2 — 2026-06-26
- **Menu fix:** long option menus now scroll so every option is visible, the selected row
  is always shown and highlighted, and single-select options are numbered.

## 0.2.1 — 2026-06-26
- Renamed the app to **TMUXor**.
- Transcription is **OpenAI-only** (removed the experimental on-device option).
- Access token required to connect.

## 0.2.0 — 2026-06-26
- **Per-user setup:** a phone-side Setup screen where each user enters their own backend
  URL + access token (stored on the phone). No secrets are baked into the public build, so
  the app can be shared without exposing anyone's machine.

## 0.1.x — 2026-06-25 → 06-26 (early development)
Rapid pre-release iteration that built the core app:
- Fleet list of your tmux sessions, sorted attention-first (waiting → working → idle) with
  status glyphs and page counter; double-tap to jump to the next waiting session.
- Conversation view rendered as the real chat — prompts interleaved with answers, marked
  with `▶`, markdown flattened (tables/bullets/headings), turn dividers and hanging indent,
  full-bleed text.
- Exact per-pane → session transcript mapping (each session shows *its own* conversation).
- Voice input: speak → transcribe (Whisper) → send to the session; transcription cost shown.
- Line-by-line scrolling with acceleration on sustained swipes.
- Create a new session by voice (speak a folder).
- Open a session at its most recent question.
- First packaged build installable on the glasses (private dashboard install / QR sideload).
