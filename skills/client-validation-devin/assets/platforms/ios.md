### iOS guide

#### Environment facts
- macOS VM on Apple silicon. User `devin`, shell zsh, home `/Users/devin`, repos in
  `/Users/devin/repos/<repo>`, files attached to the session in `/Users/devin/.files/`.
- Preinstalled: Xcode 26 (default, `xcode-select -p`), Xcode 27 RC at `/Applications/Xcode-27*.app`,
  iOS 26 and 27 simulator runtimes, `xcodebuild`, `xcrun simctl`, Swift, Homebrew (`/opt/homebrew`),
  Node, Python, Java, Rust, `jq`, `ffmpeg`, Chrome. Never install Xcode.
- Check first: `sw_vers; xcodebuild -version; xcrun simctl list devices available`.
- One command on another Xcode: `DEVELOPER_DIR=/Applications/Xcode-27.0-RC.app/Contents/Developer /usr/bin/xcodebuild ...`.
- Optional installs, only when needed: `brew install cocoapods xcbeautify`; idb for UI trees:
  `brew install facebook/fb/idb-companion && pip3 install fb-idb`.
- Working folders: `mkdir -p /tmp/qa/evidence`; keep logs in `/tmp/qa`.

#### Build and install
- Use the spec's `setup`, `build` and `artifact` first. Fallbacks by stack:
  - Native: `xcodebuild -list`, then `xcodebuild -scheme <Scheme> -destination 'platform=iOS Simulator,name=iPhone 17' -derivedDataPath /tmp/qa/dd CODE_SIGNING_ALLOWED=NO build 2>&1 | tee /tmp/qa/ios-build.log`;
    app at `/tmp/qa/dd/Build/Products/Debug-iphonesimulator/<App>.app`. CocoaPods projects use `-workspace <App>.xcworkspace` after `pod install`.
  - Flutter: `flutter build ios --simulator --debug` → `build/ios/iphonesimulator/Runner.app`.
  - React Native / Expo: `npx expo prebuild -p ios` (Expo only), `cd ios && pod install`, then the native command with
    `-workspace` and `-configuration Release` (bundles the JS, so no Metro server is needed).
  - Compose Multiplatform: `xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' -derivedDataPath /tmp/qa/dd build`.
- Locate a bundle: `find . /tmp/qa/dd -name '*.app' -path '*iphonesimulator*' -maxdepth 7`.
- Bundle id: `/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' <App>.app/Info.plist`.
- Boot and install: `xcrun simctl boot "iPhone 17" 2>/dev/null; open -a Simulator; xcrun simctl bootstatus booted -b; xcrun simctl install booted <App>.app`.
- Fresh state for first-launch scenarios: `xcrun simctl uninstall booted <bundle-id>` before installing.

#### Launch and crash detection
- Launch with console capture (runs until the app exits, so background it):
  `xcrun simctl launch --console-pty --terminate-running-process booted <bundle-id> > /tmp/qa/ios-console.log 2>&1 &`
- Alive check: `xcrun simctl spawn booted launchctl list | grep <bundle-id>`; no line after launch means it died.
- Crash reports land on the host: `ls -t ~/Library/Logs/DiagnosticReports/*.ips | head`; attach the newest
  report whose name starts with the app's executable name.
- App log: `xcrun simctl spawn booted log show --last 10m --style compact --predicate 'process == "<Executable>"' > /tmp/qa/ios-log.txt`.
- Hang (no response to input for 5 s or more): `sample "$(pgrep -n <Executable>)" 5 -file /tmp/qa/ios-hang.txt`.
- Tests: `xcodebuild test -scheme <Scheme> -destination 'platform=iOS Simulator,name=iPhone 17' -resultBundlePath /tmp/qa/ios-tests.xcresult`,
  then `xcrun xcresulttool get test-results summary --path /tmp/qa/ios-tests.xcresult --format json > /tmp/qa/ios-tests-summary.json`
  and `xcrun xcresulttool get test-results tests --path /tmp/qa/ios-tests.xcresult > /tmp/qa/ios-tests.txt` for failure details.

#### Screenshots
- Normalize the status bar once per boot: `xcrun simctl status_bar booted override --time 9:41 --batteryState charged --batteryLevel 100`.
- Capture at full device resolution: `xcrun simctl io booted screenshot --type=png /tmp/qa/evidence/r<round>-ios__<check>__<variant>__<nn>.png`.
- Variant = device_theme_locale_scale with a lowercase device slug and scale `std` or `xl`, for example
  `r2-ios__create-note__iphone-se_dark_de_xl__03.png`.
- Optional clip: `xcrun simctl io booted recordVideo --codec=h264 /tmp/qa/evidence/r<round>-ios__<check>__<variant>.mp4 &`, stop with `kill -INT $!`.
- Attach the files to your messages and list their names in `evidence_files`.

#### Interaction
- Computer Use on the Simulator window first. Shortcuts: ⌘⇧H home, ⌘← / ⌘→ rotate, ⌘K software keyboard.
- Deep link: `xcrun simctl openurl booted "<scheme>://<path>"`. Paste text: `printf '%s' "text" | xcrun simctl pbcopy booted`.
- Permissions and state: `xcrun simctl privacy booted grant photos <bundle-id>`, `xcrun simctl location booted set 37.33,-122.03`,
  `xcrun simctl push booted <bundle-id> payload.apns`.
- Scripted fallback: the repo's XCUITest target, or idb (`idb ui tap X Y`, `idb ui text "..."`, `idb ui swipe X1 Y1 X2 Y2`).

#### Layout matrix switches
- Devices: `xcrun simctl list devices available`. Create a missing one with
  `xcrun simctl create "iPhone SE (3rd generation)" "iPhone SE (3rd generation)" <runtime-id>` (ids from `xcrun simctl list runtimes`).
  Run one simulator at a time: `xcrun simctl shutdown all` before booting the next.
- Theme: `xcrun simctl ui booted appearance dark` or `light`.
- Largest text: `xcrun simctl ui booted content_size accessibility-extra-extra-extra-large`; default is `large`.
- Locale per launch: `xcrun simctl terminate booted <bundle-id>; xcrun simctl launch booted <bundle-id> -AppleLanguages "(de)" -AppleLocale de_DE`.
- Orientation: ⌘← / ⌘→ through Computer Use. Increased contrast: `xcrun simctl ui booted increase_contrast enabled`.
- Relaunch the app after theme or text-size changes before judging the layout.

#### UI tree dump for overlap checks
- With idb: `idb ui describe-all --udid "$(xcrun simctl list devices booted -j | jq -r '.devices[][] | .udid' | head -1)" --json > /tmp/qa/ios-tree.json`.
  Each element has `frame` (x, y, width, height in points) and `AXLabel`/`AXValue`/`type`.
- Without idb: a temporary XCUITest that prints `XCUIApplication().debugDescription` (frames in points); revert it afterwards.
- Apply the overlap logic from the Android guide: leaf elements with a label, value or button type; flag pairs whose
  intersection is over 20 % of the smaller frame, frames outside the screen (the `Application` element's frame is the
  screen), and labels ending in "…". Confirm each finding on the screenshot: text inside its own button is expected.

#### Logs to attach
- `/tmp/qa/ios-build.log` (last 300 lines when the build fails), `ios-console.log`, `ios-log.txt`, the newest app `.ips`
  crash reports, `ios-tests-summary.json` and `ios-tests.txt`, `ios-hang.txt` when a hang was sampled.

#### Known pitfalls
- Simulators only: no physical devices, no camera, push only through `simctl push`. Timing is not representative;
  report performance only for freezes of several seconds.
- The software keyboard can stay up and cover content: tap outside the field, or turn on I/O → Keyboard →
  Connect Hardware Keyboard (⇧⌘K) before typing; relaunching the app also clears it.
- If the accessibility tree is unavailable on one simulator (queries time out or return nothing), use idb for
  that device instead of retrying XCUITest queries.
- The VM sleeps after idle periods and running simulators stop; after a wake, boot the device and relaunch the app.
- The first build after a snapshot rebuild is slow (cold DerivedData); keep one `-derivedDataPath` for the whole job.
- A `-destination` must match `xcrun simctl list devices available` exactly, including the OS when given.
- macOS permission prompts (Accessibility, Screen Recording, Automation) take the password `devin`.
- Signing errors on simulator builds: add `CODE_SIGNING_ALLOWED=NO`. Docker is very slow here (no nested virtualization); avoid it.
