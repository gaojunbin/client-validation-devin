### macOS guide

#### Environment facts
- macOS VM on Apple silicon. User `devin` (admin, passwordless `sudo`), shell zsh, home `/Users/devin`,
  repos in `/Users/devin/repos/<repo>`, files attached to the session in `/Users/devin/.files/`.
- Preinstalled: Xcode 26 (default) and Xcode 27 RC, Swift, Homebrew (`/opt/homebrew`), Node, Python, Java, Rust,
  `jq`, `ffmpeg`, Chrome. Never install Xcode. BSD userland: `sed -i ''`; GNU tools via `brew install coreutils`.
- Check first: `sw_vers; xcodebuild -version; system_profiler SPDisplaysDataType | grep Resolution`.
- Working folders: `mkdir -p /tmp/qa/evidence`.

#### Build and install
- Use the spec's `setup`, `build` and `artifact` first. Fallbacks by stack:
  - Native (AppKit/SwiftUI): `xcodebuild -scheme <Scheme> -destination 'platform=macOS' -derivedDataPath /tmp/qa/dd CODE_SIGN_IDENTITY=- build 2>&1 | tee /tmp/qa/macos-build.log`
    → `/tmp/qa/dd/Build/Products/Debug/<App>.app`. SwiftPM executable: `swift build` → `.build/debug/<exe>`.
  - Flutter: `flutter build macos --debug` → `build/macos/Build/Products/Debug/<App>.app`.
  - Electron: `npx electron-builder --mac --dir` → `dist/mac-arm64/<App>.app`; Forge: `npm run package` → `out/<App>-darwin-arm64/<App>.app`.
  - Tauri: `npm run tauri build -- --debug --bundles app` → `src-tauri/target/debug/bundle/macos/<App>.app`.
  - Compose Multiplatform desktop: `./gradlew :composeApp:createDistributable` → `composeApp/build/compose/binaries/main/app/<App>.app`.
- Locate bundles: `find . /tmp/qa/dd -name '*.app' -maxdepth 7 -newer /tmp/qa`. Executable name:
  `/usr/libexec/PlistBuddy -c 'Print CFBundleExecutable' <App>.app/Contents/Info.plist`.
- Downloaded or copied bundles that refuse to open: `xattr -dr com.apple.quarantine <App>.app`.

#### Launch and crash detection
- Launch the executable directly so output is captured:
  `"<App>.app/Contents/MacOS/<Executable>" > /tmp/qa/macos-app.log 2>&1 & echo $! > /tmp/qa/app.pid`
  (or `open -n <App>.app --stdout /tmp/qa/macos-app.log --stderr /tmp/qa/macos-app.log`).
- Alive check: `kill -0 "$(cat /tmp/qa/app.pid)"`. A crash leaves `~/Library/Logs/DiagnosticReports/<Executable>-*.ips`.
- Unified log: `log show --last 10m --style compact --predicate 'process == "<Executable>"' > /tmp/qa/macos-log.txt`.
- Hang (spinning cursor, no response for 5 s or more): `sample "$(cat /tmp/qa/app.pid)" 5 -file /tmp/qa/macos-hang.txt`.
- Tests: `xcodebuild test -scheme <Scheme> -destination 'platform=macOS' -resultBundlePath /tmp/qa/macos-tests.xcresult`,
  summary with `xcrun xcresulttool get test-results summary --path /tmp/qa/macos-tests.xcresult --format json > /tmp/qa/macos-tests-summary.json`.

#### Screenshots
- Whole screen at full resolution: `screencapture -x /tmp/qa/evidence/r<round>-macos__<check>__<variant>__<nn>.png`.
- One window: read its frame (see Layout matrix switches), then `screencapture -x -R<x>,<y>,<w>,<h> <file>.png`.
- Variant = size_theme_locale_scale, scale `std` or `xl`, e.g. `r2-macos__create-note__1024x700_dark_de_std__03.png`.
- A screenshot that shows only the wallpaper means Screen Recording permission is missing for the shell: grant it in
  System Settings → Privacy & Security → Screen Recording (password `devin`) and retry.
- Attach the files to your messages and list their names in `evidence_files`.

#### Interaction
- Computer Use first. macOS shortcuts use ⌘ (⌘N, ⌘W, ⌘, for Settings, ⌘Q).
- Scripted fallback with AppleScript (the controlling app needs Accessibility permission, password `devin`):
  `osascript -e 'tell application "System Events" to tell process "<Process>" to click button "Save" of window 1'`,
  `osascript -e 'tell application "System Events" to keystroke "n" using command down'`,
  `osascript -e 'tell application "System Events" to tell process "<Process>" to click menu item "Settings…" of menu 1 of menu bar item "<App>" of menu bar 1'`.

#### Layout matrix switches
- Window size and position:
  `osascript -e 'tell application "System Events" to tell process "<Process>" to set position of window 1 to {0, 25}' -e 'tell application "System Events" to tell process "<Process>" to set size of window 1 to {1024, 700}'`.
  Read the frame back with `osascript -e 'tell application "System Events" to tell process "<Process>" to get {position, size} of window 1'`;
  apps clamp to their minimum size, so record the size you actually got. Also try the minimum size by dragging the corner.
- Theme: `osascript -e 'tell application "System Events" to tell appearance preferences to set dark mode to true'` (`false` for light).
- Locale per launch: `open -n <App>.app --args -AppleLanguages '(de)' -AppleLocale de_DE`.
- Text scale: macOS has no global Dynamic Type. Use the app's own text-size setting if it has one, otherwise mark the
  `xl` variants `skipped` with the reason. Display scaling cannot be changed on the VM.
- Relaunch the app after switching theme or locale.

#### UI tree dump for overlap checks
- Dump leaf elements with frames (JavaScript for Automation; slow on big windows, so run it once per screen):

```sh
osascript -l JavaScript -e 'const p = Application("System Events").processes.byName("PROCESS");
const keep = ["AXStaticText","AXButton","AXTextField","AXTextArea","AXImage","AXCheckBox","AXPopUpButton","AXLink","AXRadioButton"];
p.windows[0].entireContents().filter(e => { try { return keep.includes(e.role()); } catch (x) { return false; } })
 .map(e => { const pos = e.position(), size = e.size();
   return [e.role(), String(e.name() || e.description() || "").slice(0, 40), pos[0], pos[1], size[0], size[1]].join("|"); })
 .join("\n")' > /tmp/qa/macos-tree.txt
```
- Replace PROCESS with the process name. Apply the overlap logic from the Android guide (pairs overlapping more than 20 %
  of the smaller frame, frames outside the window, labels ending in "…") and confirm on the screenshot.

#### Logs to attach
- `/tmp/qa/macos-build.log` (last 300 lines on failure), `macos-app.log`, `macos-log.txt`, new `.ips` crash reports for the
  executable, `macos-tests-summary.json`, `macos-hang.txt` when a hang was sampled.

#### Known pitfalls
- No nested virtualization: Docker runs under software emulation and is very slow; avoid it.
- The VM sleeps after idle periods and running apps stop; relaunch after a wake.
- Permission prompts (Accessibility, Screen Recording, Automation) appear on the desktop; answer them through Computer Use
  with the password `devin`, then rerun the command that triggered them.
- Apps with `LSUIElement` (menu bar apps) have no Dock icon or main window; interact through the menu bar extra.
- Performance numbers inside the VM are not representative; report only freezes of several seconds.
