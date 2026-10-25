# Builds the phone app: `docker compose run --rm apk` (runs android/build.sh).
# JDK 17 and the Android SDK pieces build.sh needs -- the same versions as the
# tools/ folder it replaces. android/debug.keystore and oauth.properties are
# read from the mounted android/ folder, never baked in.
FROM eclipse-temurin:17-jdk-jammy

RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip zip curl \
 && rm -rf /var/lib/apt/lists/*

ENV ANDROID_HOME=/opt/android-sdk
RUN mkdir -p $ANDROID_HOME/cmdline-tools \
 && curl -sSfL -o /tmp/cmdline.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
 && unzip -q /tmp/cmdline.zip -d $ANDROID_HOME/cmdline-tools \
 && mv $ANDROID_HOME/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest \
 && rm /tmp/cmdline.zip \
 && yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --sdk_root=$ANDROID_HOME \
      "build-tools;34.0.0" "platforms;android-34" >/dev/null \
 && rm -rf $ANDROID_HOME/cmdline-tools /root/.android

# build.sh finds the JDK through JAVA_HOME and the SDK through ANDROID_HOME.
