#!/usr/bin/env bash
# Manage the TMUXor macOS LaunchAgent without enabling login autostart.
set -euo pipefail

LABEL="${TMUXOR_LAUNCHD_LABEL:-com.tmuxor.conductor}"
DOMAIN="gui/$UID"
SERVICE="$DOMAIN/$LABEL"
PLIST="${TMUXOR_LAUNCHD_PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}"

usage() {
  cat <<EOF
Usage: $(basename "$0") {start|stop|restart|status}

  start    Start TMUXor now, but keep login autostart disabled
  stop     Stop TMUXor and keep login autostart disabled
  restart  Stop and start TMUXor
  status   Show whether TMUXor is running
EOF
}

is_loaded() {
  launchctl print "$SERVICE" >/dev/null 2>&1
}

disable_autostart() {
  launchctl disable "$SERVICE"
}

start_service() {
  if [ ! -f "$PLIST" ]; then
    echo "TMUXor LaunchAgent not found: $PLIST" >&2
    echo "Run install.sh first." >&2
    exit 1
  fi

  # A disabled job cannot be bootstrapped. Enable it briefly, load it for the
  # current login session, then mark it disabled again for the next login.
  launchctl enable "$SERVICE"
  local rc=0
  if is_loaded; then
    launchctl kickstart -k "$SERVICE" || rc=$?
  else
    launchctl bootstrap "$DOMAIN" "$PLIST" || rc=$?
  fi
  disable_autostart

  if [ "$rc" -ne 0 ]; then
    echo "TMUXor could not be started (launchctl exit $rc)." >&2
    exit "$rc"
  fi
  echo "TMUXor started. Login autostart remains disabled."
}

stop_service() {
  if is_loaded; then
    launchctl bootout "$SERVICE"
    echo "TMUXor stopped."
  else
    echo "TMUXor is already stopped."
  fi
  disable_autostart
  echo "Login autostart is disabled."
}

status_service() {
  if is_loaded; then
    local state
    state="$(launchctl print "$SERVICE" | awk '/^[[:space:]]*state = / { print $3; exit }')"
    echo "TMUXor is ${state:-loaded}."
  else
    echo "TMUXor is stopped."
  fi

  if launchctl print-disabled "$DOMAIN" | grep -Eq "\"$LABEL\" => (true|disabled)"; then
    echo "Login autostart is disabled."
  else
    echo "Warning: login autostart is enabled."
  fi
}

case "${1:-}" in
  start) start_service ;;
  stop) stop_service ;;
  restart)
    stop_service
    start_service
    ;;
  status) status_service ;;
  *)
    usage >&2
    exit 2
    ;;
esac
