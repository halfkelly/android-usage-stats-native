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

## 3. OAuth client

1. **Clients → Create client** → type **TVs and Limited Input devices** →
   name `Usage Dump phone` → Create.
2. Copy the **Client ID** and **Client secret** into `android/oauth.properties`:

   ```properties
   client_id=1234567890-abc...apps.googleusercontent.com
   client_secret=GOCSPX-...
   ```

   The file is gitignored. For this kind of client, Google says the secret
   isn't truly confidential, since it ships inside the app. It stays out of
   git anyway.

## 4. Build and connect

```bash
bash android/build.sh        # no "building without Drive upload" note this time
```

Install the APK (see WINDOWS.md, "Install the phone app"), open **Usage Dump**,
tap **Connect Google Drive**. The app copies a code and opens
google.com/device: paste the code, pick the account, **Allow**, then switch
back to the app. It uploads straight away. After that it uploads every
6 hours on its own.

## If uploads stop

The status screen says why:

- **"access expired — reconnect"**: the consent screen was left in Testing, the
  grant was removed at <https://myaccount.google.com/permissions>, or the
  password changed. Tap **Connect Google Drive** again. Nothing collected in
  the meantime is lost, and it all uploads after reconnecting.
- **"(will retry)"**: no network or a Drive hiccup. It retries on its own.
