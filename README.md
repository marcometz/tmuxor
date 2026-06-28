# TMUXor

**Your tmux Claude Code fleet, hands-free on your Even G2 glasses.**

TMUXor puts the Claude Code (and shell) sessions running in your tmux panes onto your
glasses — see which session needs you, read its latest reply, and respond by voice —
over your own private Tailscale network. Nothing is sent to anyone but your own machine.

This repo is the **backend** (a small stdlib-Python control plane that runs on your
computer) plus the **glasses app source**. The glasses app itself installs from the
Even Hub.

---

## Screenshots

| | |
|---|---|
| ![Fleet list](store-assets/screenshots/01-fleet-list.png)<br>**Fleet** — your sessions, sorted by what needs you (! waiting · ● working · ○ idle). | ![Conversation](store-assets/screenshots/02-conversation.png)<br>**Conversation** — real prompts + replies, opening at the latest question. |
| ![New session](store-assets/screenshots/03-new-session-tag.png)<br>**New session** — pick a project tag, then speak the folder. | ![Voice review](store-assets/screenshots/04-voice-review.png)<br>**Voice** — review the transcription (and its cost) before sending. |

*576×288 monochrome-green glasses display. Images use demo data.*

---

## Quick start

On the computer where your tmux + Claude Code sessions run:

```bash
curl -fsSL https://raw.githubusercontent.com/liyiyuian/tmuxor/main/install.sh | bash
```

The installer checks prerequisites, downloads the backend, generates an access token,
writes the config file, installs a `systemd --user` service, exposes it on your tailnet
with `tailscale serve`, and prints a **scannable QR code** (plus a one-line config code).

Then on your phone:

1. Install **TMUXor** from the Even Hub.
2. Open it → **Setup** → tap **📷 Scan QR code** and scan the QR the installer printed.

That's it — no typing the URL or token. (No camera? Tap **Paste config** instead, or enter it
by hand — see [SETUP.md](SETUP.md).)

### Requirements (prepare these first)
- **Even G2 glasses** + the Even phone app, paired.
- **tmux** and **Claude Code** installed. You do *not* need a session running already —
  TMUXor can start your first one from the glasses ("＋ new session").
- **Tailscale**, signed in on the computer **and** the phone (same tailnet), **with HTTPS
  Certificates enabled** for your tailnet (Tailscale admin console → Settings → enable
  HTTPS) — `tailscale serve` needs it for the secure URL the glasses connect to.
- **Python 3.10+** on the computer.
- *(Optional)* an **OpenAI API key** — only for voice replies. Without it, read + tap still
  work and the app shows "voice off"; re-run the installer later to add it.

The installer checks Python / tmux / Claude / Tailscale and tells you what's missing. The
Tailscale **HTTPS** toggle and signing in on the phone are the two it can't do for you.

---

## Security model

This backend **runs commands on your machine** — treat it as a remote-control surface:

- Binds **loopback only** (`127.0.0.1`); reached over the tailnet via `tailscale serve`.
- **Token required** on every request (constant-time check); it refuses to start without one.
- The token lives only in `~/.config/tmux-conductor.env` (mode `600`). **Never share it or
  commit it** — anyone with it can run commands as you.

Do not expose this backend to the public internet.

---

## Manual setup, usage, and troubleshooting

See **[SETUP.md](SETUP.md)** for the step-by-step manual install, how session-matching
works, the gesture reference, and troubleshooting.

## Building the glasses app yourself

The app installs from the Even Hub, but you can build it from `glasses/` (Vite + React +
even-toolkit). A public build ships no secrets — each user enters their own URL + token.
See `glasses/` and the project notes.

## License

**MIT** — see [LICENSE](LICENSE).
