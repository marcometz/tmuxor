#!/usr/bin/env bash
# TMUXor backend installer — one command to stand up the control plane on YOUR machine.
#
#   curl -fsSL https://raw.githubusercontent.com/marcometz/tmuxor/main/install.sh | bash
#
# It: checks prereqs, downloads the backend, generates a token, writes the env file,
# installs a systemd --user service (Linux) or LaunchAgent (macOS), exposes it on
# your tailnet, and prints the Backend URL + token + a paste-config blob to enter
# in the glasses app.
#
# This backend runs commands on your machine — it is loopback-bound + token-required +
# tailnet-only. Never expose it publicly or share the token.
#
# Testing hooks (not for normal use):
#   TMUXOR_SRC=/path/to/repo   copy backend files from a local dir instead of curl
#   TMUXOR_DRYRUN=1            don't start services or change Tailscale (print instead)
#   TMUXOR_OPENAI_KEY=sk-...   supply the OpenAI key non-interactively ("" = skip voice)
#   TMUXOR_SOURCE=herdr        set the default backend (tmux or herdr)
#   TMUXOR_AUTOSTART=1         opt into macOS login autostart (default: disabled)
set -euo pipefail

REPO="${TMUXOR_REPO:-marcometz/tmuxor}"
RAW="https://raw.githubusercontent.com/${REPO}/main"
PORT="${CONDUCTOR_API_PORT:-8790}"
INSTALL_DIR="${TMUXOR_DIR:-$HOME/.local/share/tmuxor}"
ENV_FILE="${TMUXOR_ENV:-$HOME/.config/tmux-conductor.env}"
DRY="${TMUXOR_DRYRUN:-0}"
AUTOSTART="${TMUXOR_AUTOSTART:-0}"
OS="$(uname -s)"

c()  { printf '\033[36m%s\033[0m\n' "$*"; }      # info
ok() { printf '\033[32m✓ %s\033[0m\n' "$*"; }
warn(){ printf '\033[33m! %s\033[0m\n' "$*"; }
die(){ printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
run(){ if [ "$DRY" = 1 ]; then echo "  [dry-run] $*"; else "$@"; fi; }

c "TMUXor backend installer"

# 1) prerequisites -----------------------------------------------------------
case "$OS" in
  Linux|Darwin) ;;
  *) die "unsupported operating system: $OS (need Linux or macOS)" ;;
esac
PYTHON_BIN=""
for candidate in "$(command -v python3 2>/dev/null || true)" /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if [ -n "$candidate" ] && [ -x "$candidate" ] \
     && "$candidate" -c 'import sys;exit(0 if sys.version_info[:2]>=(3,10) else 1)' 2>/dev/null; then
    PYTHON_BIN="$candidate"
    break
  fi
done
[ -n "$PYTHON_BIN" ] || die "Python 3.10+ not found. Install it first (macOS: brew install python)."
PYV=$("$PYTHON_BIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])')
ok "python3 $PYV"
TMUX_BIN="$(command -v tmux 2>/dev/null || true)"
HERDR_BIN="$(command -v herdr 2>/dev/null || true)"
[ -n "$TMUX_BIN" ] && ok "tmux" || warn "tmux not found"
[ -n "$HERDR_BIN" ] && ok "herdr" || warn "herdr not found"
[ -n "$TMUX_BIN" ] || [ -n "$HERDR_BIN" ] || die "install at least one session backend: tmux or Herdr (https://herdr.dev)"
command -v claude >/dev/null && ok "claude"    || warn "claude (Claude Code) not on PATH — install it so sessions can launch."
TAILSCALE_BIN="$(command -v tailscale 2>/dev/null || true)"
if [ -z "$TAILSCALE_BIN" ] && [ "$OS" = Darwin ] && [ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]; then
  TAILSCALE_BIN=/Applications/Tailscale.app/Contents/MacOS/Tailscale
fi
[ -n "$TAILSCALE_BIN" ] && ok "tailscale" || die "tailscale not found. Install + log in: https://tailscale.com/download"

# 2) download backend --------------------------------------------------------
mkdir -p "$INSTALL_DIR"
for f in conductor_api.py tmux_conductor.py sources.py tmuxor-service.sh; do
  if [ -n "${TMUXOR_SRC:-}" ]; then
    cp "$TMUXOR_SRC/$f" "$INSTALL_DIR/$f"
  else
    curl -fsSL "$RAW/$f" -o "$INSTALL_DIR/$f" || die "could not download $f from $RAW"
  fi
done
chmod 700 "$INSTALL_DIR/tmuxor-service.sh"
ok "backend in $INSTALL_DIR"

# 3) token (reuse existing if present) ---------------------------------------
TOKEN=""
[ -f "$ENV_FILE" ] && TOKEN=$(sed -n 's/^CONDUCTOR_TOKEN=//p' "$ENV_FILE" | head -1)
if [ -z "$TOKEN" ]; then
  TOKEN="tmxr_$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
  ok "generated a new access token"
else
  ok "reusing existing access token"
fi
EXISTING_OPENAI_KEY=""
EXISTING_SOURCE=""
EXISTING_HERDR_BIN=""
if [ -f "$ENV_FILE" ]; then
  EXISTING_OPENAI_KEY=$(sed -n 's/^OPENAI_API_KEY=//p' "$ENV_FILE" | head -1)
  EXISTING_SOURCE=$(sed -n 's/^CONDUCTOR_SOURCE=//p' "$ENV_FILE" | head -1)
  EXISTING_HERDR_BIN=$(sed -n 's/^CONDUCTOR_HERDR_BIN=//p' "$ENV_FILE" | head -1)
fi

# 4) OpenAI key (OPTIONAL) — enables VOICE input. Without it you just type replies and
#    new-session names on your phone instead. ---------------------------------
if [ "${TMUXOR_OPENAI_KEY+set}" = set ]; then
  OPENAI_KEY="$TMUXOR_OPENAI_KEY"
elif [ -r /dev/tty ]; then
  if [ -n "$EXISTING_OPENAI_KEY" ]; then
    printf 'OpenAI API key already configured. Paste a replacement, or Enter to keep it: '
    read -r OPENAI_KEY </dev/tty || OPENAI_KEY=""
    OPENAI_KEY="${OPENAI_KEY:-$EXISTING_OPENAI_KEY}"
  else
    printf 'OpenAI API key (optional) — enables VOICE input via Whisper; without it you type on your phone. Paste it, or Enter to skip: '
    read -r OPENAI_KEY </dev/tty || OPENAI_KEY=""
  fi
else
  OPENAI_KEY="$EXISTING_OPENAI_KEY"
fi
[ -n "$OPENAI_KEY" ] && ok "voice input enabled" || warn "no OpenAI key — voice input off; you'll type replies/new-session names on your phone (re-run later to add voice)."

# 5) write env file (chmod 600) ---------------------------------------------
SOURCE="${TMUXOR_SOURCE:-$EXISTING_SOURCE}"
if [ -z "$SOURCE" ]; then
  if [ -n "$HERDR_BIN" ] && [ -z "$TMUX_BIN" ]; then SOURCE=herdr; else SOURCE=tmux; fi
fi
[ "$SOURCE" = tmux ] || [ "$SOURCE" = herdr ] || die "TMUXOR_SOURCE must be tmux or herdr"
if [ "$SOURCE" = tmux ] && [ -z "$TMUX_BIN" ]; then SOURCE=herdr; fi
if [ "$SOURCE" = herdr ] && [ -z "$HERDR_BIN" ] && [ -z "$EXISTING_HERDR_BIN" ]; then SOURCE=tmux; fi
HERDR_CONFIG_BIN="${HERDR_BIN:-$EXISTING_HERDR_BIN}"

mkdir -p "$(dirname "$ENV_FILE")"
umask 177
ENV_TMP=$(mktemp "${ENV_FILE}.tmp.XXXXXX")
if [ -f "$ENV_FILE" ]; then
  # Keep advanced/user-managed settings such as CONDUCTOR_LAUNCH_CMD,
  # ANTHROPIC_API_KEY and CONDUCTOR_PROJECTS_DIR across installer upgrades.
  grep -Ev '^(CONDUCTOR_TOKEN|CONDUCTOR_BIND|CONDUCTOR_API_PORT|CONDUCTOR_SOURCE|CONDUCTOR_HERDR_BIN|OPENAI_API_KEY)=' "$ENV_FILE" > "$ENV_TMP" || true
fi
{
  cat "$ENV_TMP"
  echo "CONDUCTOR_TOKEN=$TOKEN"
  echo "CONDUCTOR_BIND=127.0.0.1"
  echo "CONDUCTOR_API_PORT=$PORT"
  echo "CONDUCTOR_SOURCE=$SOURCE"
  [ -n "$HERDR_CONFIG_BIN" ] && echo "CONDUCTOR_HERDR_BIN=$HERDR_CONFIG_BIN"
  [ -n "$OPENAI_KEY" ] && echo "OPENAI_API_KEY=$OPENAI_KEY"
} > "${ENV_TMP}.new"
mv "${ENV_TMP}.new" "$ENV_FILE"
rm -f "$ENV_TMP"
umask 022
chmod 600 "$ENV_FILE"
ok "wrote $ENV_FILE"

# 6) background service ------------------------------------------------------
if [ "$OS" = Linux ]; then
  UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  command -v systemctl >/dev/null || die "systemctl not found; this Linux installer requires systemd --user"
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/tmux-conductor.service" <<UNIT
[Unit]
Description=TMUXor backend (conductor-api)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON_BIN $INSTALL_DIR/conductor_api.py
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
UNIT
  ok "wrote systemd user service"
  run systemctl --user daemon-reload
  run systemctl --user enable --now tmux-conductor.service
  [ "$DRY" = 1 ] || warn "to keep it running after logout: sudo loginctl enable-linger $USER"
else
  [ "$AUTOSTART" = 0 ] || [ "$AUTOSTART" = 1 ] || die "TMUXOR_AUTOSTART must be 0 or 1"
  LABEL="com.tmuxor.conductor"
  PLIST_DIR="$HOME/Library/LaunchAgents"
  PLIST="$PLIST_DIR/$LABEL.plist"
  LOG_DIR="$HOME/Library/Logs/TMUXor"
  RUNNER="$INSTALL_DIR/run-backend.sh"
  mkdir -p "$PLIST_DIR" "$LOG_DIR"
  cat > "$RUNNER" <<RUNNER
#!/bin/sh
set -a
. "$ENV_FILE"
set +a
exec "$PYTHON_BIN" "$INSTALL_DIR/conductor_api.py"
RUNNER
  chmod 700 "$RUNNER"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNNER</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$INSTALL_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/backend.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/backend-error.log</string>
</dict>
</plist>
PLIST
  plutil -lint "$PLIST" >/dev/null || die "generated invalid LaunchAgent plist"
  ok "wrote macOS LaunchAgent"
  if [ "$DRY" = 1 ]; then
    echo "  [dry-run] launchctl bootout gui/$UID $PLIST"
    echo "  [dry-run] launchctl enable gui/$UID/$LABEL"
    echo "  [dry-run] launchctl bootstrap gui/$UID $PLIST"
    echo "  [dry-run] launchctl kickstart -k gui/$UID/$LABEL"
    [ "$AUTOSTART" = 0 ] && echo "  [dry-run] launchctl disable gui/$UID/$LABEL"
  else
    launchctl bootout "gui/$UID" "$PLIST" >/dev/null 2>&1 || true
    launchctl enable "gui/$UID/$LABEL"
    launchctl bootstrap "gui/$UID" "$PLIST"
    launchctl kickstart -k "gui/$UID/$LABEL"
    if [ "$AUTOSTART" = 0 ]; then
      launchctl disable "gui/$UID/$LABEL"
    fi
  fi
  if [ "$AUTOSTART" = 0 ]; then
    ok "login autostart disabled; manage the service with $INSTALL_DIR/tmuxor-service.sh"
  else
    ok "login autostart enabled"
  fi
fi

# 7) expose on the tailnet ---------------------------------------------------
if [ "$OS" = Linux ]; then
  run sudo "$TAILSCALE_BIN" set --operator="$USER"   # one-time, so Serve needs no sudo
fi
run "$TAILSCALE_BIN" serve --bg "$PORT"

# 8) summary + paste-config --------------------------------------------------
DNS=$("$TAILSCALE_BIN" status --json 2>/dev/null | "$PYTHON_BIN" -c 'import sys,json;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)
URL="https://${DNS:-<your-tailscale-host>.ts.net}"
BLOB="tmuxor:$("$PYTHON_BIN" -c 'import base64,json,sys;print(base64.urlsafe_b64encode(json.dumps({"base":sys.argv[1],"token":sys.argv[2]}).encode()).decode())' "$URL" "$TOKEN")"

echo
ok "TMUXor backend is up."
c  "Backend URL : $URL"
c  "Token       : $TOKEN"
echo
c  "On your phone: open TMUXor → Setup → 'Paste config'. Paste this line:"
echo "  $BLOB"
if command -v qrencode >/dev/null; then
  echo
  c "(or scan this QR with your phone's camera to copy the code, then paste it)"
  qrencode -t ANSIUTF8 "$BLOB"
  qrencode -o "$HOME/tmuxor-setup-qr.png" "$BLOB" 2>/dev/null && c "(QR also saved to ~/tmuxor-setup-qr.png)"
fi
echo
[ -z "$DNS" ] && warn "couldn't read your Tailscale domain — run 'tailscale status' and use your https://<host>.ts.net URL."
