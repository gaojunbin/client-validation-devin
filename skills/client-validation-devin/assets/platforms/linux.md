### Linux desktop guide

#### Environment facts
- Linux (Ubuntu) VM with an X11 desktop that Computer Use sees. User `ubuntu`, bash, home `/home/ubuntu`,
  repos in `~/repos/<repo>`, files attached to the session in `~/.files/`. Chrome is preinstalled.
- Check first: `lsb_release -ds; echo "DISPLAY=$DISPLAY"; xdpyinfo | grep dimensions`. GUI commands need `DISPLAY` set.
- Tools that may need installing (use `sudo` when not root): `sudo apt-get install -y xdotool wmctrl imagemagick x11-utils`;
  CJK text renders as boxes until `sudo apt-get install -y fonts-noto-cjk`; UI trees need `python3-pyatspi at-spi2-core`.
- Working folders: `mkdir -p /tmp/qa/evidence`.

#### Build and install
- Use the spec's `setup`, `build` and `artifact` first. Fallbacks by stack:
  - Flutter: `flutter build linux --debug` → `build/linux/x64/debug/bundle/<app>` (needs `clang cmake ninja-build pkg-config libgtk-3-dev`).
  - Electron: `npx electron-builder --linux dir` → `dist/linux-unpacked/<app>`; Forge: `npm run package` → `out/<App>-linux-x64/<app>`.
  - Tauri: `npm run tauri build -- --debug --no-bundle` → `src-tauri/target/debug/<app>` (needs `libwebkit2gtk-4.1-dev`).
  - Compose Multiplatform desktop: `./gradlew :composeApp:createDistributable` → `composeApp/build/compose/binaries/main/app/<App>/bin/<App>`.
  - CMake / Qt / GTK: `cmake -B /tmp/qa/build -DCMAKE_BUILD_TYPE=Debug && cmake --build /tmp/qa/build -j"$(nproc)"`.
- Capture the build: append `2>&1 | tee /tmp/qa/linux-build.log`. Locate binaries with `find . -maxdepth 6 -type f -perm -u+x -newer /tmp/qa`.

#### Launch and crash detection
- Enable core dumps, then launch with output captured:
  `ulimit -c unlimited; "<artifact>" > /tmp/qa/linux-app.log 2>&1 & echo $! > /tmp/qa/app.pid`
- Alive check: `kill -0 "$(cat /tmp/qa/app.pid)"`. When it is gone, `wait` is not available across shells, so read the end of
  `linux-app.log` and `sudo dmesg | tail -20` (segfault lines name the binary); exit 134 is an abort, 139 a segfault.
- Core dumps: `coredumpctl list` when systemd-coredump is installed, else `core*` files in the working directory;
  backtrace with `gdb -batch -ex bt <binary> <core>` (optional install `gdb`).
- Hang: the window stops repainting or the title shows "Not Responding";
  `gdb -p "$(cat /tmp/qa/app.pid)" -batch -ex "thread apply all bt" > /tmp/qa/linux-hang.txt`.
- Tests: the spec's `test` command; Flutter `flutter test`, Electron `npm test`, Rust `cargo test`, JVM `./gradlew test`.

#### Screenshots
- Whole screen: `import -window root /tmp/qa/evidence/r<round>-linux__<check>__<variant>__<nn>.png`.
- One window: `import -window "$(xdotool search --pid "$(cat /tmp/qa/app.pid)" --onlyvisible | tail -1)" <file>.png`.
- If ImageMagick cannot be installed: `scrot <file>.png` (`sudo apt-get install -y scrot`) or, with Pillow present,
  `python3 -c "from PIL import ImageGrab; ImageGrab.grab().save('<file>.png')"`.
- Variant = size_theme_locale_scale, scale `std` or `xl`, e.g. `r2-linux__create-note__800x600_dark_de_xl__03.png`.
- Attach the files to your messages and list their names in `evidence_files`.

#### Interaction
- Computer Use first. Scripted fallback with xdotool:
  `xdotool search --name "<Window title>" windowactivate --sync`, `xdotool mousemove X Y click 1`,
  `xdotool type --delay 50 "milk, eggs"`, `xdotool key ctrl+s`.
- Window ids for the app: `xdotool search --pid "$(cat /tmp/qa/app.pid)" --onlyvisible`.

#### Layout matrix switches
- Window size: `xdotool windowsize <wid> 800 600` or `wmctrl -r "<Window title>" -e 0,0,0,800,600`; read back with
  `xdotool getwindowgeometry <wid>` because apps clamp to their minimum size.
- Theme (relaunch the app with it): GTK and Flutter `GTK_THEME=Adwaita:dark "<artifact>"`; also try
  `gsettings set org.gnome.desktop.interface color-scheme prefer-dark` when the schema exists; Qt `QT_QPA_PLATFORMTHEME=gtk3`;
  Electron and Chromium-based apps `--force-dark-mode`.
- Locale: `sudo locale-gen de_DE.UTF-8` once, then launch with `LANG=de_DE.UTF-8 LANGUAGE=de LC_ALL=de_DE.UTF-8`.
- Largest text: GTK and Flutter `GDK_DPI_SCALE=2`, Qt `QT_SCALE_FACTOR=1.5`, Electron `--force-device-scale-factor=1.5`;
  whole-session fonts: `echo "Xft.dpi: 192" | xrdb -merge` before launching.

#### UI tree dump for overlap checks
- AT-SPI (optional install above). Electron apps need `--force-renderer-accessibility`; Flutter and Compose expose
  trees only when their accessibility bridge is active, otherwise rely on screenshots.

```sh
python3 - <<'PY' > /tmp/qa/linux-tree.txt
import pyatspi
def walk(a):
    for i in range(a.childCount):
        c = a.getChildAtIndex(i)
        if c is None: continue
        if c.childCount == 0:
            e = c.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
            print(c.getRoleName(), "|", (c.name or "")[:40], "|", e.x, e.y, e.width, e.height)
        walk(c)
for app in pyatspi.Registry.getDesktop(0):
    if app is not None and app.name == "APP_NAME": walk(app)
PY
```
- Replace APP_NAME (list names with `for a in pyatspi.Registry.getDesktop(0): print(a.name)`). Apply the overlap logic from
  the Android guide (pairs overlapping more than 20 % of the smaller box, boxes outside the window, labels ending in "…")
  and confirm on the screenshot.

#### Logs to attach
- `/tmp/qa/linux-build.log` (last 300 lines on failure), `linux-app.log`, the `dmesg` excerpt, core backtraces,
  `linux-hang.txt`, test reports.

#### Known pitfalls
- No GPU: use software rendering (`LIBGL_ALWAYS_SOFTWARE=1`; Electron `--disable-gpu`) when the window stays black.
- The desktop is X11: set `GDK_BACKEND=x11` and `QT_QPA_PLATFORM=xcb` if an app tries Wayland.
- The VM sleeps after idle periods and running apps stop; relaunch after a wake.
- `apt-get` can collide with an unattended upgrade lock; wait and retry once.
- Locales and CJK fonts are not installed by default; missing glyphs are an environment problem, not an app bug.
