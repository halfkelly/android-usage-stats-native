#!/usr/bin/env bash
# One-command phone sync on Windows (WSL).
# Wi-Fi is tried first; USB is the fallback and needs usbipd to pass the phone
# through to WSL, which Wi-Fi avoids entirely.
set -uo pipefail
cd "$(dirname "$0")"
ADB=./platform-tools/adb
PY=.venv/bin/python

attached() { "$ADB" devices 2>/dev/null | awk 'NR>1 && $2=="device"' | grep -q .; }

echo ""
echo "  Phone Usage — sync"
echo "  ------------------"
echo ""

if "$PY" -m wellbeing connect >/dev/null 2>&1 && attached; then
  echo "  Connected over Wi-Fi — no cable needed."
else
  # ---- USB fallback -------------------------------------------------------
  # WSL only sees Windows programs that were on PATH when WSL started, so fall
  # back to usbipd's default install location if it was installed afterwards.
  USBIPD=""
  for candidate in usbipd.exe "/mnt/c/Program Files/usbipd-win/usbipd.exe"; do
    if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
      USBIPD="$candidate"; break
    fi
  done
  if [ -z "$USBIPD" ]; then
    echo "  ✗ No phone on Wi-Fi, and usbipd isn't available for a USB connection."
    echo "    Easiest fix: on the phone turn on Settings > Developer options >"
    echo "    Wireless debugging, then run this again."
    exit 1
  fi

  BUSID=$("$USBIPD" list 2>/dev/null | tr -d '\r' | awk 'tolower($2) ~ /^04e8:/ {print $1; exit}')
  if [ -z "$BUSID" ]; then
    echo "  ✗ Phone not found on Wi-Fi or USB."
    echo "    Plug it in and unlock it, or turn on Wireless debugging, then run this again."
    exit 1
  fi
  echo "  Phone found on USB. Connecting..."

  # --auto-attach re-attaches if the phone resets its USB connection mid-sync.
  "$USBIPD" attach --wsl --busid "$BUSID" --auto-attach >/tmp/usbipd-attach.log 2>&1 &
  ATTACH_PID=$!
  disown "$ATTACH_PID"   # stopping it at the end is expected; don't print "Terminated"
  cleanup() {
    kill "$ATTACH_PID" 2>/dev/null
    "$USBIPD" detach --busid "$BUSID" >/dev/null 2>&1   # hand the phone back to Windows
  }
  trap cleanup EXIT

  echo "  (Enter your Ubuntu password if asked — adb needs it to reach the phone.)"
  sudo "$ADB" kill-server >/dev/null 2>&1
  sudo "$ADB" start-server >/dev/null 2>&1

  STATE=""
  for _ in $(seq 1 40); do
    STATE=$("$ADB" devices 2>/dev/null | awk 'NR>1 && NF {print $2; exit}')
    [ "$STATE" = "device" ] && break
    [ "$STATE" = "unauthorized" ] && echo "  Tap Allow on the phone..."
    sleep 1
  done
  if [ "$STATE" != "device" ]; then
    echo "  ✗ Couldn't reach the phone over USB (state: ${STATE:-not seen})."
    echo "    Wi-Fi avoids this entirely: turn on Wireless debugging on the phone,"
    echo "    pair once with '$PY -m wellbeing pair <ip:port> <code>', then run this again."
    exit 1
  fi
fi

./sync.sh || exit 1
./dashboard.sh
