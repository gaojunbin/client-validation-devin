### Android guide

#### Environment facts
- Linux (Ubuntu) VM. User `ubuntu`, bash, home `/home/ubuntu`, repos in `~/repos/<repo>`, attached files in `~/.files/`.
- The blueprint installs the SDK at `$ANDROID_HOME` (usually `~/android-sdk`) with `adb`, `emulator`, `sdkmanager`
  and an x86_64 AVD named `devin` (phone) and sometimes `devin-tablet`. Check: `echo $ANDROID_HOME; adb version; emulator -list-avds`.
- Missing SDK: follow the project's blueprint commands (`sdkmanager "platform-tools" "emulator" "platforms;android-34"
  "system-images;android-34;google_apis;x86_64"`, then `echo no | avdmanager create avd -n devin -k "<image>" --device pixel_6`).
- Gradle needs JDK 17 (`java -version`). Working folders: `mkdir -p /tmp/qa/evidence`.

#### Build and install
- Use the spec's `setup`, `build` and `artifact` first. Fallbacks by stack:
  - Native: `./gradlew assembleDebug 2>&1 | tee /tmp/qa/android-build.log` → `app/build/outputs/apk/debug/app-debug.apk`.
  - Flutter: `flutter build apk --debug` → `build/app/outputs/flutter-apk/app-debug.apk`.
  - React Native: `cd android && ./gradlew assembleRelease` (JS bundled, debug-signed by the template, no Metro) →
    `android/app/build/outputs/apk/release/app-release.apk`. Expo: `npx expo prebuild -p android` first.
  - Compose Multiplatform: `./gradlew :composeApp:assembleDebug` → `composeApp/build/outputs/apk/debug/composeApp-debug.apk`.
- Locate APKs: `find . -name '*.apk' -path '*outputs*' -newer /tmp/qa -maxdepth 8`. Package name: `aapt2 dump badging <apk> | head -1`
  (aapt2 is under `$ANDROID_HOME/build-tools/*/`).
- Start the emulator with a window (Computer Use needs it):
  `emulator -avd devin -no-audio -no-boot-anim -gpu swiftshader_indirect > /tmp/qa/emulator.log 2>&1 &`
- Wait for boot: `adb wait-for-device; until [ "$(adb shell getprop sys.boot_completed | tr -d '\r')" = 1 ]; do sleep 2; done; adb shell input keyevent 82`.
- Stable UI: `for s in window_animation_scale transition_animation_scale animator_duration_scale; do adb shell settings put global $s 0; done`.
- Install: `adb install -r -t <apk>`. Fresh state: `adb shell pm clear <package>`.

#### Launch and crash detection
- `adb logcat -c`, then launch: `adb shell monkey -p <package> -c android.intent.category.LAUNCHER 1`
  (or `adb shell am start -W -n <package>/<activity>`, which prints `TotalTime`).
- Alive check: `adb shell pidof <package>`; empty means it died.
- Crashes: `adb logcat -b crash -d > /tmp/qa/android-crash.txt`; any `FATAL EXCEPTION` or native `signal` line is a crash.
- ANRs: `adb logcat -d | grep -E "ANR in|Application Not Responding" > /tmp/qa/android-anr.txt`; with `adb root`
  (works on google_apis images) pull `/data/anr` and `/data/tombstones`.
- Tests: unit `./gradlew testDebugUnitTest`; instrumented (emulator running) `./gradlew connectedDebugAndroidTest`,
  reports in `app/build/reports/androidTests/connected/`; Flutter integration `flutter test integration_test -d emulator-5554`.

#### Screenshots
- `adb exec-out screencap -p > /tmp/qa/evidence/r<round>-android__<check>__<variant>__<nn>.png` (full device resolution).
- Variant = device_theme_locale_scale, scale `std` or `xl`, e.g. `r2-android__create-note__pixel-6_dark_de_xl__03.png`.
- Optional clip: `adb shell screenrecord --time-limit 60 /sdcard/qa.mp4`, then `adb pull /sdcard/qa.mp4 /tmp/qa/evidence/`.
- Attach the files to your messages and list their names in `evidence_files`.

#### Interaction
- Computer Use on the emulator window first (watch it in the Desktop tab).
- Scripted fallback with device-pixel coordinates taken from the UI tree: `adb shell input tap X Y`,
  `adb shell input swipe X1 Y1 X2 Y2 300`, `adb shell input text 'milk%seggs'` (`%s` is a space),
  `adb shell input keyevent KEYCODE_BACK` / `KEYCODE_HOME` / `KEYCODE_ENTER`.
- Deep link: `adb shell am start -a android.intent.action.VIEW -d "<scheme>://<path>"`.
- Runtime permission: `adb shell pm grant <package> android.permission.POST_NOTIFICATIONS`.

#### Layout matrix switches
- Devices: `emulator -list-avds`; one emulator at a time (`adb emu kill` before starting the next). Without a tablet AVD,
  emulate sizes with `adb shell wm size 1600x2560; adb shell wm density 320` (undo: `wm size reset; wm density reset`).
- Theme: `adb shell cmd uimode night yes` or `no`.
- Largest text: `adb shell settings put system font_scale 2.0` (default `1.0`).
- Locale (API 33+, per app): `adb shell cmd locale set-app-locales <package> --locales de-DE`.
- Orientation: `adb shell settings put system accelerometer_rotation 0; adb shell settings put system user_rotation 1` (0 = portrait).
- Restart the app after a change: `adb shell am force-stop <package>`, then launch again.

#### UI tree dump for overlap checks
- `adb shell uiautomator dump /sdcard/ui.xml > /dev/null && adb pull /sdcard/ui.xml /tmp/qa/android-ui.xml`
- A dump with only one large node means the framework exposes no accessibility tree; rely on screenshots then.
- Flag overlaps, off-screen elements and ellipsized text (other platform guides reuse this logic):

```python
import re, sys, xml.etree.ElementTree as ET
B = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
box = lambda n: tuple(map(int, B.match(n.get("bounds")).groups()))
nodes = [n for n in ET.parse(sys.argv[1]).getroot().iter("node") if n.get("bounds")]
W, H = box(nodes[0])[2:]
name = lambda n: (n.get("text") or n.get("content-desc") or n.get("resource-id") or n.get("class"))[:40]
leaves = [n for n in nodes if not n.findall("node") and (n.get("text") or n.get("content-desc") or n.get("clickable") == "true")]
leaves = [n for n in leaves if box(n)[2] > box(n)[0] and box(n)[3] > box(n)[1]]
for n in leaves:
    l, t, r, b = box(n)
    if l < 0 or t < 0 or r > W or b > H: print("OFFSCREEN", name(n), (l, t, r, b))
    if (n.get("text") or "").endswith("…"): print("ELLIPSIZED", name(n))
for i, a in enumerate(leaves):
    for c in leaves[i + 1:]:
        (al, at, ar, ab), (cl, ct, cr, cb) = box(a), box(c)
        iw, ih = min(ar, cr) - max(al, cl), min(ab, cb) - max(at, ct)
        small = min((ar - al) * (ab - at), (cr - cl) * (cb - ct))
        if iw > 0 and ih > 0 and iw * ih / small > 0.2: print("OVERLAP", name(a), "<->", name(c), round(iw * ih / small, 2))
```
- Save it as `/tmp/qa/overlap.py`, run `python3 /tmp/qa/overlap.py /tmp/qa/android-ui.xml`, and confirm every hit on the
  screenshot before reporting it.

#### Logs to attach
- `/tmp/qa/android-build.log` (last 300 lines on failure), `android-crash.txt`, `android-anr.txt`,
  the app log `adb logcat -d --pid="$(adb shell pidof -s <package>)" > /tmp/qa/android-app.log`,
  `/tmp/qa/emulator.log` when the emulator misbehaves, the instrumented test report folder zipped.

#### Known pitfalls
- Emulator only: no physical devices; Play Services exist only on `google_apis_playstore` images, which refuse `adb root`.
- Use x86_64 system images; ARM images are very slow. If the emulator will not start, check `ls -l /dev/kvm`;
  the last resort `-accel off` is slow.
- The VM sleeps after idle periods and the emulator process stops; after a wake, start it again (add `-no-snapshot-load`
  if it boots into a broken state) and reinstall if needed.
- `adb devices` must list `emulator-5554 device` before any `adb` command; `offline` means wait or restart the emulator.
- Gradle builds need several GB of RAM; run one emulator at a time and stop Gradle daemons (`./gradlew --stop`) if memory runs out.
