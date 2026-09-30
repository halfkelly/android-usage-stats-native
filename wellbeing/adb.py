"""Thin wrapper around the adb binary."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class AdbError(RuntimeError):
    pass


def adb_path() -> str:
    """Prefer the platform-tools bundled next to this project, else PATH."""
    local = ROOT / "platform-tools" / "adb"
    if local.exists() and os.access(local, os.X_OK):
        return str(local)
    found = shutil.which("adb")
    if not found:
        raise AdbError(
            "adb not found. Run scripts/install_platform_tools.sh or put adb on PATH."
        )
    return found


def _run(args: list[str], timeout: int = 120) -> str:
    cmd = [adb_path(), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise AdbError(f"{' '.join(cmd)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def devices() -> list[tuple[str, str]]:
    """[(serial, state)] for every attached device."""
    out = _run(["devices"])
    result = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            result.append((parts[0], parts[1]))
    return result


def require_device(serial: str | None = None) -> str:
    devs = devices()
    if not devs:
        raise AdbError(
            "No phone reachable. Turn on Settings > Developer options > Wireless "
            "debugging with the phone on the same Wi-Fi, then run 'wellbeing "
            "connect <ip:port>' using the address it shows. The port changes after "
            "a reboot. A USB cable also works if you prefer."
        )
    if serial:
        for s, state in devs:
            if s == serial:
                if state != "device":
                    raise AdbError(f"Device {s} is in state '{state}', not 'device'.")
                return s
        raise AdbError(f"Device {serial} not attached.")
    ready = [s for s, state in devs if state == "device"]
    # A phone on Wi-Fi has a host:port serial. When both a cable and a wireless
    # connection are present, prefer the wireless one so a forgotten cable does
    # not turn every sync into an ambiguous-device error.
    wireless = [s for s in ready if ":" in s]
    if wireless:
        ready = wireless
    if not ready:
        s, state = devs[0]
        hint = " (accept the USB debugging prompt on the phone)" if state == "unauthorized" else ""
        raise AdbError(f"Device {s} is in state '{state}', not 'device'{hint}.")
    if len(ready) > 1:
        # One phone on Wi-Fi can appear twice -- as ip:port and under its mDNS
        # name -- so ask each entry which phone it is before calling it two.
        by_phone: dict[str, list[str]] = {}
        for candidate in ready:
            try:
                phone = shell("getprop ro.serialno", candidate, timeout=20).strip()
            except AdbError:
                phone = ""
            by_phone.setdefault(phone or candidate, []).append(candidate)
        if len(by_phone) == 1:
            entries = next(iter(by_phone.values()))
            # talk to the ip:port form; the mDNS name can change between sessions
            ready = sorted(entries, key=lambda e: ("." not in e.split(":")[0], e))[:1]
    if len(ready) > 1:
        raise AdbError(f"Multiple devices attached: {', '.join(ready)}. Pass --serial.")
    return ready[0]


MDNS_CONNECT = "_adb-tls-connect._tcp"
MDNS_PAIR = "_adb-tls-pairing._tcp"


def mdns_services(service: str = MDNS_CONNECT) -> list[str]:
    """host:port for each phone advertising wireless debugging on this network."""
    try:
        out = _run(["mdns", "services"], timeout=15)
    except AdbError:
        return []
    found = []
    for line in out.splitlines():
        if service in line:
            address = line.split()[-1].strip()
            if ":" in address:
                found.append(address)
    return found


def connect(address: str) -> str:
    out = _run(["connect", address], timeout=30)
    if "cannot connect" in out.lower() or "failed" in out.lower():
        raise AdbError(out.strip())
    return out.strip()


def pair(address: str, code: str) -> str:
    out = _run(["pair", address, code], timeout=60)
    if "successfully" not in out.lower():
        raise AdbError(out.strip())
    return out.strip()


def shell(command: str, serial: str | None = None, timeout: int = 180) -> str:
    args = (["-s", serial] if serial else []) + ["shell", command]
    return _run(args, timeout=timeout)


def device_name(serial: str) -> str:
    try:
        brand = shell("getprop ro.product.manufacturer", serial).strip()
        model = shell("getprop ro.product.model", serial).strip()
        return f"{brand} {model}".strip() or serial
    except AdbError:
        return serial


def android_release(serial: str) -> str:
    try:
        return shell("getprop ro.build.version.release", serial).strip()
    except AdbError:
        return ""


def phone_timezone(serial: str) -> str:
    return shell("getprop persist.sys.timezone", serial).strip()


def dump_usagestats(serial: str) -> str:
    return shell("dumpsys usagestats", serial, timeout=300)


def installed_packages(serial: str) -> list[str]:
    out = shell("pm list packages", serial)
    return sorted(l.strip()[8:] for l in out.splitlines() if l.strip().startswith("package:"))
