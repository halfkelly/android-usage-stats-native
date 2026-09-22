#!/usr/bin/env bash
# One-command phone sync on Windows (WSL): attach the phone, sync, open the dashboard.
set -uo pipefail
cd "$(dirname "$0")"
ADB=./platform-tools/adb
# WSL only sees Windows programs that were on PATH when WSL started, so fall back
# to usbipd's default install location if it was installed afterwards.
USBIPD=""
for candidate in usbipd.exe "/mnt/c/Program Files/usbipd-win/usbipd.exe"; do
  if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
    USBIPD="$candidate"; break
  fi
done
if [ -z "$USBIPD" ]; then
  echo "  ✗ Can't find usbipd. In PowerShell run:  wsl --shutdown"
  echo "    then reopen Ubuntu and run this again."
  exit 1
fi

# Samsung's USB vendor id is 04e8; the bus id changes if you use a different port.
BUSID=$("$USBIPD" list 2>/dev/null | tr -d '\r' | awk 'tolower($2) ~ /^04e8:/ {print $1; exit}')
if [ -z "$BUSID" ]; then
  echo "  ✗ Phone not found. Plug it in, unlock it, and run this again."
  exit 1
fi
echo "  Phone found. Connecting..."

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
  echo "  ✗ Couldn't connect to the phone (state: ${STATE:-not seen})."
  echo "    Fallback — in Administrator PowerShell run:  usbipd attach --wsl --busid $BUSID"
  echo "    then run this again."
  exit 1
fi

./sync.sh || exit 1
./dashboard.sh
