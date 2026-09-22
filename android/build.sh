#!/bin/bash
# Builds the companion APK without Gradle: aapt2 -> javac -> d8 -> zipalign -> apksigner.
set -euo pipefail
cd "$(dirname "$0")"
TOOLS=../tools
export JAVA_HOME="$(cd $TOOLS/jdk/Contents/Home && pwd)"
PATH="$JAVA_HOME/bin:$PATH"
BT="$(cd $TOOLS/android-14 && pwd)"
ANDROID_JAR="$(cd $TOOLS/sdk/platforms/android-34 && pwd)/android.jar"
OUT=build
rm -rf $OUT && mkdir -p $OUT/classes

# A debug keystore, generated once. The APK only ever runs on your own phone.
if [ ! -f debug.keystore ]; then
  keytool -genkeypair -keystore debug.keystore -storepass android -keypass android \
    -alias debug -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Usage Dump Debug" >/dev/null 2>&1
fi

"$BT/aapt2" link -I "$ANDROID_JAR" --manifest AndroidManifest.xml -o $OUT/base.apk
javac -source 8 -target 8 -nowarn -bootclasspath "$ANDROID_JAR" -classpath "$ANDROID_JAR" \
  -d $OUT/classes $(find src -name '*.java') 2>&1 | grep -v 'bootstrap class path' || true
"$BT/d8" --lib "$ANDROID_JAR" --output $OUT $(find $OUT/classes -name '*.class')
(cd $OUT && zip -q base.apk classes.dex)
"$BT/zipalign" -f 4 $OUT/base.apk $OUT/aligned.apk
"$BT/apksigner" sign --ks debug.keystore --ks-pass pass:android --key-pass pass:android \
  --out $OUT/usagedump.apk $OUT/aligned.apk
echo "built: $(cd $OUT && pwd)/usagedump.apk"
