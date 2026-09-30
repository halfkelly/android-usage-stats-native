#!/usr/bin/env bash
# Pull the phone, update the shared archive, open the dashboard.
# Works on macOS and on WSL/Linux. The .command files call this.
set -uo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
ADB=./platform-tools/adb
[ -x "$ADB" ] || ADB=adb

echo ""
echo "  Phone Usage — sync"
echo "  ------------------"
echo ""

# Pull in whatever the other computer has already archived. Done before the
# phone is even looked for, so this still brings the dashboard up to date on a
# machine that cannot reach the phone right now.
echo "  Catching up on the shared archive..."
"$PY" -m wellbeing import 2>/dev/null | tail -2 | sed 's/^/  /'
echo ""

# A phone already on Wi-Fi needs no cable; harmless when there isn't one.
"$PY" -m wellbeing connect >/dev/null 2>&1 || true

if "$ADB" devices 2>/dev/null | grep -q "no permissions"; then
  echo "  ✗ The phone is connected, but adb isn't allowed to talk to it."
  echo ""
  echo "    Restart adb with root once, then run this again:"
  echo "        $ADB kill-server && sudo $ADB start-server"
  echo ""
  exit 1
fi

if ! "$ADB" devices 2>/dev/null | grep -qw device; then
  echo "  ✗ I can't see your phone."
  echo ""
  echo "    Over Wi-Fi (no cable): turn on Settings > Developer options >"
  echo "    Wireless debugging, then run this again. First time on this"
  echo "    computer, pair once:"
  echo "        .venv/bin/python -m wellbeing pair <ip:port> <code>"
  echo ""
  echo "    Or by cable: plug it in, unlock the screen, and tap Allow if asked."
  if grep -qi microsoft /proc/version 2>/dev/null; then
    echo ""
    echo "    On WSL the phone must be attached to Linux first, from"
    echo "    an admin PowerShell on Windows:"
    echo "        usbipd list                          # find the phone's BUSID"
    echo "        usbipd bind --busid <BUSID>          # one time only"
    echo "        usbipd attach --wsl --busid <BUSID>  # after every reconnect"
  fi
  echo ""
  exit 1
fi

"$PY" -m wellbeing deep-sync || "$PY" -m wellbeing sync
"$PY" -m wellbeing export

echo ""
"$PY" -m wellbeing where
