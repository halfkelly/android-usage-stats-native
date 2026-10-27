#!/bin/bash
# Builds the companion APK without Gradle: aapt2 -> javac -> d8 -> zipalign -> apksigner.
#
# Toolchain, first match wins:
#   JDK          $JAVA_HOME, ../tools/jdk-linux
#   build-tools  $ANDROID_HOME/build-tools/34.0.0, ../tools/sdk/build-tools/34.0.0
#   android.jar  $ANDROID_HOME/platforms/android-34, ../tools/sdk/platforms/android-34
# On a fresh machine, README.md ("Building the phone app") fills ../tools.
set -euo pipefail
cd "$(dirname "$0")"
TOOLS=../tools

first_dir() { for d in "$@"; do [ -n "$d" ] && [ -d "$d" ] && { (cd "$d" && pwd); return; }; done; return 1; }

JAVA_HOME="$(first_dir "${JAVA_HOME:-}" $TOOLS/jdk-linux)" \
  || { echo "no JDK: set JAVA_HOME or unpack one into $TOOLS/jdk-linux" >&2; exit 1; }
export JAVA_HOME
PATH="$JAVA_HOME/bin:$PATH"
SDK="${ANDROID_HOME:-$TOOLS/sdk}"
BT="$(first_dir "$SDK/build-tools/34.0.0" $TOOLS/sdk/build-tools/34.0.0)" \
  || { echo "no build-tools 34: sdkmanager \"build-tools;34.0.0\"" >&2; exit 1; }
PLATFORM="$(first_dir "$SDK/platforms/android-34" $TOOLS/sdk/platforms/android-34)" \
  || { echo "no platform 34: sdkmanager \"platforms;android-34\"" >&2; exit 1; }
ANDROID_JAR="$PLATFORM/android.jar"
OUT=build
rm -rf $OUT/classes $OUT/gen $OUT/assets $OUT/*.apk.tmp && mkdir -p $OUT/classes

# The signing key, generated once. The APK only ever runs on your own phone.
# A new key cannot update an APK signed by another one -- the phone would need
# an uninstall and setup all over again -- so restore the backup first
# (README.md, "The signing key") rather than let this make a new one.
if [ ! -f debug.keystore ]; then
  echo "note: no android/debug.keystore -- generating a NEW key; it cannot update the installed app" >&2
  keytool -genkeypair -keystore debug.keystore -storepass android -keypass android \
    -alias debug -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Usage Dump Debug" >/dev/null 2>&1
fi

# Release by default. DEBUGGABLE=1 adds android:debuggable, which lets
# `adb shell run-as` read the app's private files -- useful for testing, but
# that includes the Drive refresh token, so never for the phone in daily use.
DEBUG_FLAG=""
if [ "${DEBUGGABLE:-0}" = "1" ]; then DEBUG_FLAG="--debug-mode"; echo "note: DEBUGGABLE build"; fi
# The dashboard: the PC's page, with phone.js loaded first to answer its
# requests from the app's own data (android/web/phone.js).
mkdir -p $OUT/assets
sed '0,/<script>/s//<script src="phone.js"><\/script>\n<script>/' ../wellbeing/templates/dashboard.html > $OUT/assets/dashboard.html
cp web/phone.js $OUT/assets/
grep -q 'src="phone.js"' $OUT/assets/dashboard.html || { echo "could not wire phone.js into dashboard.html" >&2; exit 1; }
"$BT/aapt2" link -I "$ANDROID_JAR" --manifest AndroidManifest.xml -A $OUT/assets $DEBUG_FLAG -o $OUT/base.apk
javac -source 8 -target 8 -nowarn -Xlint:-options -bootclasspath "$ANDROID_JAR:$BT/core-lambda-stubs.jar" -classpath "$ANDROID_JAR" \
  -d $OUT/classes $(find src -name '*.java')
"$BT/d8" --lib "$ANDROID_JAR" --min-api 26 --output $OUT $(find $OUT/classes -name '*.class')
(cd $OUT && zip -q base.apk classes.dex)
"$BT/zipalign" -f 4 $OUT/base.apk $OUT/aligned.apk
"$BT/apksigner" sign --ks debug.keystore --ks-pass pass:android --key-pass pass:android \
  --out $OUT/usagedump.apk $OUT/aligned.apk
rm -f $OUT/base.apk $OUT/aligned.apk $OUT/classes.dex $OUT/usagedump.apk.idsig
echo "built: $(cd $OUT && pwd)/usagedump.apk"
