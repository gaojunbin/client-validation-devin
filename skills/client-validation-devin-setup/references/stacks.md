# Stack detection and per-stack spec blocks

## Detection signals

| Files | Stack | Blueprint template | Typical platforms |
| - | - | - | - |
| `pubspec.yaml` with `flutter:` | Flutter | `flutter.yaml` | folders `ios/`, `android/`, `macos/`, `windows/`, `linux/`, `web/` decide |
| `package.json` with `react-native` | React Native (bare) | `react-native.yaml` | ios, android |
| `app.json`/`app.config.*` with `expo` | Expo | `react-native.yaml` | ios, android (web if `expo-web`) |
| `*.xcodeproj`/`*.xcworkspace`/`Package.swift`, `project.yml` (XcodeGen), `Tuist/` | Native Apple | `apple-native.yaml` | ios, macos (check the target SDKs) |
| `build.gradle(.kts)` with `com.android.application`, no `kotlin("multiplatform")` | Native Android | `android-native.yaml` | android |
| `build.gradle.kts` with `kotlin("multiplatform")` + `org.jetbrains.compose` | Compose Multiplatform | `compose-multiplatform.yaml` | android, ios, desktop JVM (macos, windows, linux) |
| `package.json` with `electron` | Electron | `electron.yaml` | macos, windows, linux |
| `src-tauri/tauri.conf.json` | Tauri | `tauri.yaml` | macos, windows, linux (mobile: add Android/iOS tooling) |
| `*.csproj` with `UseMaui` / WinUI / WPF | .NET | none: start from `electron.yaml`'s Windows document and use `choco install dotnet-sdk` | windows (MAUI: android, ios, macos too) |
| `CMakeLists.txt` with Qt | Qt | none: Linux document with `qt6-base-dev`, macOS `brew install qt`, Windows `choco install qt6-base-dev` or aqtinstall | linux, macos, windows |

## `[platforms.*]` blocks

### Flutter
```toml
[platforms.ios]
vm = "macos"
setup = "flutter pub get"
build = "flutter build ios --simulator --debug"
test = "flutter test"
artifact = "build/ios/iphonesimulator/Runner.app"
app_id = "<PRODUCT_BUNDLE_IDENTIFIER from ios/Runner.xcodeproj>"
devices = ["iPhone 17", "iPhone SE (3rd generation)", "iPad Air 13-inch (M3)"]

[platforms.android]
vm = "linux"
setup = "flutter pub get"
build = "flutter build apk --debug"
artifact = "build/app/outputs/flutter-apk/app-debug.apk"
app_id = "<applicationId from android/app/build.gradle>"
devices = ["pixel_6 api 34", "pixel_tablet api 34"]

[platforms.macos]
vm = "macos"
setup = "flutter pub get"
build = "flutter build macos --debug"
artifact = "build/macos/Build/Products/Debug/<App>.app"
window_sizes = ["1440x900", "1024x700"]

[platforms.linux]
vm = "linux"
setup = "flutter pub get"
build = "flutter build linux --debug"
artifact = "build/linux/x64/debug/bundle/<binary>"
window_sizes = ["1280x800", "800x600"]

[platforms.windows]
vm = "windows"
setup = "flutter pub get"
build = "flutter build windows --debug"
artifact = "build/windows/x64/runner/Debug/<binary>.exe"
window_sizes = ["1280x800", "1024x700"]
```

### React Native / Expo
```toml
[platforms.ios]
vm = "macos"
setup = "npm ci && cd ios && pod install"      # Expo without ios/: "npm ci && npx expo prebuild -p ios && cd ios && pod install"
build = "xcodebuild -workspace ios/<App>.xcworkspace -scheme <App> -configuration Release -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' -derivedDataPath /tmp/qa/dd build"
test = "npm test"
artifact = "/tmp/qa/dd/Build/Products/Release-iphonesimulator/<App>.app"
devices = ["iPhone 17", "iPhone SE (3rd generation)"]

[platforms.android]
vm = "linux"
setup = "npm ci"                                 # Expo without android/: add "&& npx expo prebuild -p android"
build = "cd android && ./gradlew assembleRelease"
artifact = "android/app/build/outputs/apk/release/app-release.apk"
devices = ["pixel_6 api 34"]
```
Release builds bundle the JavaScript, so validators do not need a Metro server.

### Native Apple (SwiftUI / UIKit / AppKit)
```toml
[platforms.ios]
vm = "macos"
build = "xcodebuild -scheme <App> -destination 'platform=iOS Simulator,name=iPhone 17' -derivedDataPath /tmp/qa/dd CODE_SIGNING_ALLOWED=NO build"
test = "xcodebuild test -scheme <App> -destination 'platform=iOS Simulator,name=iPhone 17' -resultBundlePath /tmp/qa/tests.xcresult"
artifact = "/tmp/qa/dd/Build/Products/Debug-iphonesimulator/<App>.app"
devices = ["iPhone 17", "iPhone SE (3rd generation)", "iPad Air 13-inch (M3)"]

[platforms.macos]
vm = "macos"
build = "xcodebuild -scheme <App> -destination 'platform=macOS' -derivedDataPath /tmp/qa/dd-mac CODE_SIGNING_ALLOWED=NO build"
artifact = "/tmp/qa/dd-mac/Build/Products/Debug/<App>.app"
window_sizes = ["1440x900", "900x600"]
```

### Native Android
```toml
[platforms.android]
vm = "linux"
build = "./gradlew assembleDebug"
test = "./gradlew testDebugUnitTest"
artifact = "app/build/outputs/apk/debug/app-debug.apk"
app_id = "<applicationId>"
devices = ["pixel_6 api 34", "pixel_tablet api 34"]
```

### Electron
```toml
[platforms.macos]
vm = "macos"
setup = "npm ci"
build = "npx electron-builder --mac dir"
artifact = "dist/mac-arm64/<App>.app"
window_sizes = ["1440x900", "1024x700"]
# linux: "npx electron-builder --linux dir" -> dist/linux-unpacked/<binary>
# windows: "npx electron-builder --win dir" -> dist/win-unpacked/<App>.exe
```

### Tauri v2
```toml
[platforms.linux]
vm = "linux"
setup = "npm ci"
build = "npm run tauri build -- --debug --no-bundle"
artifact = "src-tauri/target/debug/<binary>"
window_sizes = ["1280x800", "800x600"]
# macos and windows use the same commands; artifacts are target/debug/<binary> and <binary>.exe
```

### Compose Multiplatform
```toml
[platforms.android]
vm = "linux"
build = "./gradlew :composeApp:assembleDebug"
artifact = "composeApp/build/outputs/apk/debug/composeApp-debug.apk"

[platforms.ios]
vm = "macos"
build = "xcodebuild -project iosApp/iosApp.xcodeproj -scheme iosApp -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17' -derivedDataPath /tmp/qa/dd build"
artifact = "/tmp/qa/dd/Build/Products/Debug-iphonesimulator/iosApp.app"

[platforms.linux]
vm = "linux"
build = "./gradlew :composeApp:createDistributable"
artifact = "composeApp/build/compose/binaries/main/app/<App>/bin/<App>"
```

Device names are descriptive: validators map them to available simulators or AVDs (the blueprints create the AVDs
`devin` = Pixel 6 and `devin-tablet` = Pixel Tablet) or emulate the size.
