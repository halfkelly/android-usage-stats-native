# Drive upload: one-time setup

The app uploads to `My Drive/PhoneUsage/phone/` with its own Google OAuth
client. That needs a (free) Google Cloud project, created once. About 15
minutes.

The app asks for one permission, `drive.file`. It lets the app see and change
**only the files it created itself**. It can't list, read or delete anything
else in your Drive.

## 1. Project and API

1. Open <https://console.cloud.google.com/> with the Google account whose Drive
   should hold the data.
2. Project picker (top bar) → **New project** → name it `Phone Usage` → Create,
   then make sure it is selected.
3. **APIs & Services → Library** → search **Google Drive API** → **Enable**.

## 2. Consent screen (Google Auth Platform)

1. **APIs & Services → OAuth consent screen**, or **Google Auth Platform**, →
   **Get started**.
2. App name `Usage Dump`, your email as support and contact email, audience
   **External** → Create.
3. **Data access → Add or remove scopes** → tick
   `.../auth/drive.file` ("See, edit, create, and delete only the specific
   Google Drive files you use with this app") → Update → Save.
4. **Audience → Publish app** (status becomes **In production**). The button
   stays greyed out until every required field on the **Branding** page is
   filled in. Leave the logo empty, because uploading one can trigger a review.
   To test before that, add your own address under **Audience → Test users**:
   sign-in works the same, but it expires after 7 days.

   **This step matters.** While the app is in "Testing", Google expires the
   sign-in after 7 days and uploads stop. `drive.file` is not a sensitive scope,
   so publishing needs no review. Google may still show an "unverified app"
   warning during sign-in. That's expected for a personal app: choose
   **Advanced → Go to Usage Dump**.

## 3. OAuth clients

**The Android client is the normal sign-in.** **Clients → Create client** →
type **Android**:
- Package name: `com.shrey.usagedump`
- SHA-1 certificate fingerprint:
  `E6:6F:DB:DC:4D:A9:F0:2F:D3:BE:5D:26:8E:CA:DF:23:BF:36:D9:53`. That's the
  app's signing key, `android/debug.keystore`. Print it with
  `tools/jdk-linux/bin/keytool -list -v -keystore android/debug.keystore -storepass android`.

There's nothing to copy into the app. Google recognises it by package name and
fingerprint, and the phone's own Google account does the sign-in. If the
signing key ever changes, the fingerprint here must change too.

**The device-code client is the fallback** ("Sign in with a code instead").
**Clients → Create client** → type **TVs and Limited Input devices** → Create,
then put its id and secret in `android/oauth.properties`:

```properties
client_id=1234567890-abc...apps.googleusercontent.com
client_secret=GOCSPX-...
```

The file is gitignored and backed up in `My Drive/PhoneUsage/code/signing/`.
Google doesn't treat this kind of secret as truly confidential, because it
ships inside the app, but it stays out of git anyway.

Both clients belong to the same project, and Drive's `drive.file` access is
per project, so either sign-in sees what the other uploaded.

## 4. Build and connect

```bash
bash android/build.sh
```

Install the APK (README, "Building the phone app"), open **Usage Dump**, and
tap **Connect Google Drive**: pick the account in the phone's account picker,
then **Allow**. A "Google Drive connected ✓" notification confirms it, and the
upload starts straight away. After that it uploads every 6 hours on its own.

## If uploads stop

The app shows a notification, and the status screen says why:

- **"sign-in has expired"**: the consent screen was left in Testing (7 days),
  or the grant was removed at <https://myaccount.google.com/permissions>. Tap
  the notification, then pick the account and **Allow** again. Nothing
  collected in the meantime is lost; it all uploads after reconnecting.
- **"(will retry)"**: no network or a Drive hiccup. It retries on its own.
- **"Google sign-in: …"** straight after picking the account: the Android
  client's package name or SHA-1 doesn't match the app. Check step 3.
