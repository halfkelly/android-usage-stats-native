#!/usr/bin/env bash
# The two files a GitHub release carries, into dist/, both from the last commit:
#   UsageDump.apk            the phone app (android/build/usagedump.apk)
#   UsageStats-Windows.zip   the Windows dashboard: what setup needs, nothing more
# Upload them under exactly these names: the README's download links point at
# releases/latest/download/<name>. Steps: README.md, "Making a release".
set -euo pipefail
cd "$(dirname "$0")"

SHIPPED=("Set up (Windows).bat" "Open dashboard.bat" "Stop dashboard.bat" "Sync my phone.bat"
         README.md requirements.txt wellbeing windows data/.gitkeep)

if ! git diff --quiet HEAD -- "${SHIPPED[@]}" android/build/usagedump.apk; then
    echo "error: uncommitted changes to what a release ships; commit them first:" >&2
    git status --short -- "${SHIPPED[@]}" android/build/usagedump.apk >&2
    exit 1
fi

rm -rf dist && mkdir dist
git show HEAD:android/build/usagedump.apk > dist/UsageDump.apk
if unzip -p dist/UsageDump.apk classes.dex | grep -aq GOCSPX; then
    echo "error: the APK contains an OAuth client secret; rebuild it without one" >&2
    exit 1
fi
# DATA.md stays out: its examples are the maintainer's own days.
git archive --format=zip --prefix="Phone Usage Dashboard/" -o dist/UsageStats-Windows.zip HEAD -- "${SHIPPED[@]}"

version=$(git show HEAD:android/AndroidManifest.xml | grep -o 'versionName="[^"]*"' | cut -d'"' -f2)
echo "App $version, commit $(git rev-parse --short HEAD):"
ls -l dist
echo "Next: GitHub > Releases > Draft a new release, tag v$version, add both files, Publish."
