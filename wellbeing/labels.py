"""Human readable app names for package ids.

Android keeps app labels inside each APK's resource table, which adb cannot
read directly, so names are resolved in three steps: a curated table for the
system and vendor packages that dominate a Samsung dump, an optional Play
Store lookup for third-party apps, and a prettified package name as fallback.
"""
from __future__ import annotations

import re

# Packages a Samsung dump is full of, where the prettified id would be useless
# or actively misleading ("Sec Android App Launcher").
CURATED: dict[str, str] = {
    "com.sec.android.app.launcher": "One UI Home",
    "com.samsung.android.app.launcher": "One UI Home",
    "com.android.systemui": "System UI",
    "com.android.settings": "Settings",
    "com.sec.android.app.clockpackage": "Clock",
    "com.samsung.android.dialer": "Phone",
    "com.samsung.android.incallui": "Phone (in call)",
    "com.samsung.android.messaging": "Messages",
    "com.samsung.android.app.contacts": "Contacts",
    "com.sec.android.gallery3d": "Gallery",
    "com.sec.android.app.camera": "Camera",
    "com.samsung.android.calendar": "Calendar",
    "com.samsung.android.app.notes": "Samsung Notes",
    "com.samsung.android.scloud": "Samsung Cloud",
    "com.samsung.android.forest": "Digital Wellbeing",
    "com.samsung.android.honeyboard": "Samsung Keyboard",
    "com.samsung.android.game.gamehome": "Game Launcher",
    "com.sec.android.app.myfiles": "My Files",
    "com.sec.android.app.sbrowser": "Samsung Internet",
    "com.samsung.android.oneconnect": "SmartThings",
    "com.samsung.android.spay": "Samsung Wallet",
    "com.samsung.android.bixby.agent": "Bixby",
    "com.samsung.android.app.aodservice": "Always On Display",
    "com.samsung.android.smartswitchassistant": "Smart Switch",
    "com.android.vending": "Play Store",
    "com.google.android.gms": "Google Play services",
    "com.google.android.googlequicksearchbox": "Google",
    "com.google.android.apps.maps": "Google Maps",
    "com.google.android.youtube": "YouTube",
    "com.google.android.gm": "Gmail",
    "com.google.android.apps.photos": "Google Photos",
    "com.google.android.permissioncontroller": "Permission controller",
    "com.google.android.apps.nbu.paisa.user": "Google Pay",
    "com.android.chrome": "Chrome",
    "com.whatsapp": "WhatsApp",
    "org.telegram.messenger": "Telegram",
    "org.mozilla.firefox": "Firefox",
    "com.anthropic.claude": "Claude",
    "com.instagram.android": "Instagram",
    "com.spotify.music": "Spotify",
    "com.truecaller": "Truecaller",
    "in.swiggy.android": "Swiggy",
    "com.zomato": "Zomato",
    "net.one97.paytm": "Paytm",
    "com.phonepe.app": "PhonePe",
    "com.jio.myjio": "MyJio",
    "in.amazon.mShop.android.shopping": "Amazon",
    "com.mygate.user": "MyGate",
    "com.bumble.app": "Bumble",
    "com.ubercab": "Uber",
    "com.flipkart.android": "Flipkart",

    # Messaging and calls
    "org.thoughtcrime.securesms": "Signal",
    "com.whatsapp.w4b": "WhatsApp Business",
    "com.facebook.orca": "Messenger",
    "us.zoom.videomeetings": "Zoom",

    # Streaming and media
    "com.amazon.avod.thirdpartyclient": "Prime Video",
    "com.amazon.mp3": "Amazon Music",
    "com.sonyliv": "SonyLIV",
    "com.timesprime.timesprimeandroid": "Times Prime",
    "com.samsung.android.video": "Video player",
    "com.deniscerri.ytdl": "YTDLnis",
    "com.hitrolab.audioeditor": "AudioLab",

    # Getting around, and getting things delivered
    "ee.mtakso.client": "Bolt",
    "com.grabtaxi.passenger": "Grab",
    "com.application.zomato": "Zomato",
    "com.application.zomato.district": "District by Zomato",
    "com.zeptoconsumerapp": "Zepto",
    "app.mycountrydelight.in.countrydelight": "Country Delight",
    "com.company.pronto": "Pronto",
    "com.delhiveryConsigneeApp": "Delhivery",
    "com.urbanclap.urbanclap": "Urban Company",

    # Shopping
    "com.ril.ajio": "AJIO",
    "com.lenskart.app": "Lenskart",
    "com.furlenco.android": "Furlenco",
    "com.cars24.seller": "CARS24",

    # Money, bills and insurance
    "com.idfcfirstbank.optimus": "IDFC FIRST Bank",
    "com.zerodha.kite3": "Kite by Zerodha",
    "com.sbi.authenticator": "SBI Secure",
    "com.acko.android": "Acko",
    "com.myairtelapp": "Airtel Thanks",
    "com.Splitwise.SplitwiseMobile": "Splitwise",

    # Health and fitness
    "com.garmin.android.apps.connectmobile": "Garmin Connect",
    "com.garmin.connectiq": "Connect IQ",
    "com.fitbit.FitbitMobile": "Fitbit",
    "com.github.jamesgay.fitnotes": "FitNotes",
    "com.aranoah.healthkart.plus": "1mg",
    "com.clove.patient": "Clove Dental",

    # Work and documents
    "com.trello": "Trello",
    "com.adobe.reader": "Adobe Acrobat",
    "com.google.android.apps.docs": "Google Drive",
    "com.google.android.apps.docs.editors.sheets": "Google Sheets",
    "com.google.android.calendar": "Google Calendar",
    "com.google.android.apps.translate": "Google Translate",
    "com.google.android.apps.subscriptions.red": "Google One",
    "com.google.android.apps.nbu.files": "Files by Google",

    # System surfaces that show up as "apps" in usage stats
    "android": "Android system",
    "com.android.intentresolver": "Share sheet",
    "com.android.companiondevicemanager": "Device pairing",
    "com.android.settings.intelligence": "Settings search",
    "com.google.android.captiveportallogin": "Wi-Fi sign-in",
    "com.google.android.photopicker": "Photo picker",
    "com.google.android.documentsui": "File picker",
    "com.samsung.android.app.telephonyui": "Phone (call UI)",
    "com.sec.android.app.voicenote": "Voice Recorder",
    "com.sec.android.app.popupcalculator": "Calculator",
    "com.samsung.android.lool": "Device Care",
    "com.osp.app.signin": "Samsung account",
    "com.samsung.android.easysetup": "Smart View",
    "com.samsung.android.app.dressroom": "Wallpapers and style",
    "com.digibites.accubattery": "AccuBattery",
}

# Prefixes that carry no information once stripped.
_NOISE = re.compile(
    r"^(com|org|net|in|io|app)\.(android|google|samsung|sec|samsung\.android)?\.?", re.IGNORECASE
)
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def prettify(package: str) -> str:
    """`com.sec.android.app.dressroom` -> `Dressroom`."""
    tail = package.split(".")[-1]
    if tail in {"app", "android", "core", "service", "services", "main", "client"}:
        parts = package.split(".")
        tail = parts[-2] if len(parts) > 1 else tail
    tail = _CAMEL.sub(" ", tail).replace("_", " ")
    return " ".join(w.capitalize() if w.islower() else w for w in tail.split()) or package


def resolve(packages: list[str], known: dict[str, str] | None = None,
            fetch: bool = False, timeout: float = 5.0) -> dict[str, tuple[str, str]]:
    """Return {package: (label, source)} for packages without a known label."""
    known = known or {}
    out: dict[str, tuple[str, str]] = {}
    to_fetch: list[str] = []

    for pkg in packages:
        # A curated name always wins, even over a label already stored, so
        # adding an entry here fixes every database on the next sync.
        if pkg in CURATED:
            if known.get(pkg) != CURATED[pkg]:
                out[pkg] = (CURATED[pkg], "curated")
        elif pkg in known:
            continue
        elif fetch:
            to_fetch.append(pkg)
        else:
            out[pkg] = (prettify(pkg), "prettified")

    for pkg in to_fetch:
        title = _play_store_title(pkg, timeout)
        out[pkg] = (title, "play") if title else (prettify(pkg), "prettified")
    return out


_TITLE = re.compile(r'<title[^>]*>([^<]+)</title>', re.IGNORECASE)


def _play_store_title(package: str, timeout: float) -> str | None:
    """Best-effort Play Store listing title. Returns None on any failure."""
    try:
        import requests
    except ImportError:
        return None
    try:
        resp = requests.get(
            "https://play.google.com/store/apps/details",
            params={"id": package, "hl": "en"},
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code != 200:
            return None
        m = _TITLE.search(resp.text)
        if not m:
            return None
        title = m.group(1)
        # Play titles look like "WhatsApp Messenger - Apps on Google Play"
        title = re.sub(r"\s*[-–]\s*Apps on Google Play\s*$", "", title).strip()
        return title or None
    except Exception:
        return None
