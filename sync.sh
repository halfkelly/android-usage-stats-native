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
  echo "    1. Plug it in and unlock the screen"
  echo "    2. Tap Allow if asked about USB debugging"
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
