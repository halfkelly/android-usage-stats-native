# Drive upload: the Google Cloud side

The app uploads to `My Drive/PhoneUsage/phone/` of whoever signs in, using the
Google account already on their phone. For that, Google has to know the app,
which takes one free Google Cloud project, set up once by whoever builds and
signs the APK (Shrey's project `865905461724` for the APK in this repo).
**Friends who only install the APK do none of this.**

The app asks for one permission, `drive.file`. It lets the app see and change
**only the files it created itself**. It can't list, read or delete anything
else in anyone's Drive, and the project owner never sees anyone's data: tokens
stay on each phone.

None of it costs money: no billing account is needed, and `drive.file` is a
non-sensitive scope, so publishing needs no Google review.

## 1. Project and API

1. <https://console.cloud.google.com/> → project picker → **New project**
   (`Phone Usage`) → select it.
2. **APIs & Services → Library** → **Google Drive API** → **Enable**.

## 2. Consent screen (Google Auth Platform)

1. **Google Auth Platform → Get started**: app name `Usage Dump`, your email as
   support and contact email, audience **External**.
2. **Data access → Add or remove scopes** → tick `.../auth/drive.file` →
   Update → **Save**.
3. **Branding**: app name, user support email, developer contact email, and --
   although not marked required -- an **Application home page** and
   **Application privacy policy link**, with their domain under **Authorized
   domains**: Publish stays greyed out without them. Ours are on GitHub Pages
   (public repo `<user>.github.io`, domain `<user>.github.io`). Leave the logo
   empty: a logo triggers a review. → **Save**.
4. **Audience → Publish app → Confirm**. The status becomes **In production**.

Until it is published, only the addresses under **Audience → Test users** can
sign in (up to 100), and Google ends their sign-in after 7 days. The app then
notifies and the person taps the notification, picks the account and Allows;
nothing is lost meanwhile. Publishing ends both limits.

Everyone signing in sees "Google hasn't verified this app" once: tap
**Continue**. That's expected for an app nobody has had verified by Google.

## 3. The Android client

**Clients → Create client** → type **Android**:
- Package name: `com.shrey.usagedump`
- SHA-1 certificate fingerprint:
  `E6:6F:DB:DC:4D:A9:F0:2F:D3:BE:5D:26:8E:CA:DF:23:BF:36:D9:53`

That's the fingerprint of `android/debug.keystore`, which signs every APK of
this app. Print it with
`docker compose run --rm apk keytool -list -v -keystore debug.keystore -storepass android`.
Nothing goes into the app: Google recognises it by package name and
fingerprint. A different key needs a new Android client with its fingerprint.

## 4. Connect

Install the APK, open **Usage Dump**, tap **Connect Google Drive**: pick the
account in the phone's account picker, then **Allow**. A "Google Drive
connected ✓" notification confirms it, and the first upload starts. After
that it uploads every 6 hours on its own.

## If uploads stop

The app shows a notification, and the status screen says why:

- **"sign-in has expired"**: Testing-mode expiry (above), or the grant was
  removed at <https://myaccount.google.com/permissions>. Tap the notification,
  pick the account, **Allow**. Everything collected meanwhile uploads.
- **"(will retry)"**: no network or a Drive hiccup. It retries on its own.
- **"Google sign-in: …"** straight after picking the account: the account
  isn't a test user while the app is in Testing, or the Android client's
  package name or fingerprint doesn't match the APK.
