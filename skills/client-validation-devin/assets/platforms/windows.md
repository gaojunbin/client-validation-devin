### Windows guide

#### Environment facts
- Windows VM (or a Windows Outpost machine). User `Administrator`; Git Bash is the default shell: home
  `/c/Users/Administrator` (= `C:\Users\Administrator`), repos in `/c/Users/Administrator/repos/<repo>`,
  attached files in `/c/Users/Administrator/.files/`. Packages: `choco install -y <pkg>`. Chrome is preinstalled on
  Devin VMs; on an Outpost only what the owner installed exists.
- Run PowerShell from Git Bash by writing a script file and calling
  `powershell -NoProfile -ExecutionPolicy Bypass -File /c/qa/<name>.ps1`; inline `-Command` quoting breaks easily.
- Windows commands with `/switches` get rewritten by Git Bash: prefix them with `MSYS_NO_PATHCONV=1` (e.g. `MSYS_NO_PATHCONV=1 reg add ...`).
- Working folders: `mkdir -p /c/qa/evidence` (`C:\qa\evidence` in PowerShell).

#### Build and install
- Use the spec's `setup`, `build` and `artifact` first. Fallbacks by stack:
  - .NET (WPF, WinForms, WinUI unpackaged): `dotnet build -c Debug 2>&1 | tee /c/qa/windows-build.log` → `bin/Debug/<tfm>/<App>.exe`.
  - MSBuild / C++: locate MSBuild with `"/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe" -latest -products '*' -find 'MSBuild/**/Bin/MSBuild.exe'`,
    then `"<msbuild>" <App>.sln -p:Configuration=Debug -p:Platform=x64`.
  - Flutter: `flutter build windows --debug` → `build/windows/x64/runner/Debug/<app>.exe` (plugins need Developer Mode:
    `MSYS_NO_PATHCONV=1 reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" /t REG_DWORD /f /v AllowDevelopmentWithoutDevLicense /d 1`).
  - Electron: `npx electron-builder --win dir` → `dist/win-unpacked/<App>.exe`; Forge: `npm run package` → `out/<App>-win32-x64/<App>.exe`.
  - Tauri: `npm run tauri build -- --debug --no-bundle` → `src-tauri/target/debug/<app>.exe`.
  - Compose Multiplatform desktop: `./gradlew :composeApp:createDistributable` → `composeApp/build/compose/binaries/main/app/<App>/<App>.exe`.
- Packaged (MSIX) apps must be registered: `Add-AppxPackage -Register <path>\AppxManifest.xml`, then launched by AUMID.

#### Launch and crash detection
- Launch from PowerShell and keep the process id:
  `$p = Start-Process -FilePath "C:\path\App.exe" -PassThru -RedirectStandardOutput C:\qa\windows-stdout.log -RedirectStandardError C:\qa\windows-stderr.log; $p.Id | Out-File C:\qa\app.pid`
- Alive and responsive: `$p = Get-Process -Id (Get-Content C:\qa\app.pid) -ErrorAction SilentlyContinue; $p.Responding`
  (`$null` = exited, `False` = hung).
- Crashes: `Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Application Error','.NET Runtime'; StartTime=(Get-Date).AddMinutes(-30)} -ErrorAction SilentlyContinue | Format-List TimeCreated, Message | Out-File C:\qa\windows-events.txt`;
  Windows Error Reporting folders: `C:\ProgramData\Microsoft\Windows\WER\ReportArchive` and `ReportQueue`.
- Tests: `dotnet test --logger "trx;LogFileName=C:\qa\windows-tests.trx"`, `flutter test`, `npm test`, `cargo test`, or the spec's `test`.

#### Screenshots
- PowerShell (DPI-aware so the image has real pixels):

```powershell
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type 'using System; using System.Runtime.InteropServices; public class Dpi { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }'
[Dpi]::SetProcessDPIAware() | Out-Null
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
[System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
$bmp.Save($args[0], [System.Drawing.Imaging.ImageFormat]::Png)
```
- Save as `C:\qa\shot.ps1`, run `powershell -NoProfile -ExecutionPolicy Bypass -File C:\qa\shot.ps1 C:\qa\evidence\r<round>-windows__<check>__<variant>__<nn>.png`.
- Variant = size_theme_locale_scale, scale `std` or `xl`, e.g. `r2-windows__create-note__1024x700_dark_de_std__03.png`.
- Attach the files to your messages and list their names in `evidence_files`.

#### Interaction
- Computer Use first. Scripted fallback through UI Automation (PowerShell): find by name and invoke,
  `$el = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, 'Save')))`,
  then `$el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()` (`$root` as in the UI tree dump).
- Keys: `Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('^s')`.

#### Layout matrix switches
- Window size: `Add-Type 'using System; using System.Runtime.InteropServices; public class Win { [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool r); }'`
  then `[Win]::MoveWindow((Get-Process -Id (Get-Content C:\qa\app.pid)).MainWindowHandle, 0, 0, 1024, 700, $true)`.
- Theme: `Set-ItemProperty HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize -Name AppsUseLightTheme -Value 0`
  (`1` = light); restart the app. Restore the original value when done, especially on an Outpost.
- Largest text: `Set-ItemProperty HKCU:\Software\Microsoft\Accessibility -Name TextScaleFactor -Value 200 -Type DWord`
  (100 = default). Many Win32 apps only pick it up after sign-out: mark `xl` as `skipped` with the reason when nothing changes.
- Locale: prefer the app's own language setting or flags (Electron `--lang=de`); `Set-Culture de-DE` changes formats for new
  processes; switching the display language needs a language pack and sign-out, so mark it `skipped` if unavailable.
- Display scaling (DPI) needs a sign-out; skip it on the VM.

#### UI tree dump for overlap checks
```powershell
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::FromHandle((Get-Process -Id (Get-Content C:\qa\app.pid)).MainWindowHandle)
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($e in $all) { $r = $e.Current.BoundingRectangle
  if (-not $r.IsEmpty -and $null -eq $walker.GetFirstChild($e)) {
    '{0}|{1}|{2}|{3}|{4}|{5}' -f $e.Current.ControlType.ProgrammaticName, $e.Current.Name, $r.X, $r.Y, $r.Width, $r.Height } }
```
- Save as `C:\qa\tree.ps1` and redirect the output to `C:\qa\windows-tree.txt`. Apply the overlap logic from the Android
  guide (pairs overlapping more than 20 % of the smaller box, boxes outside the window rectangle, names ending in "…") and
  confirm on the screenshot. Flutter and other canvas-drawn UIs may expose little; rely on screenshots then.

#### Logs to attach
- `C:\qa\windows-build.log` (last 300 lines on failure), `windows-stdout.log`, `windows-stderr.log`, `windows-events.txt`,
  WER report folders for the app (zip them), `windows-tests.trx`.

#### Known pitfalls
- If `npm` or `npx` fails in Git Bash with "No such file or directory" (a shim problem seen on Devin's Windows VM),
  run the same command as `npm.cmd ...` / `npx.cmd ...`, or from PowerShell, and note it in `spec_feedback`.
- Paths: Git Bash uses `/c/...`, PowerShell and the apps use `C:\...`; quote paths with spaces.
- Apps must start on the interactive desktop (Start-Process from your shell is fine; services and scheduled tasks are not).
- Sessions sleep after about 30 idle minutes and running apps stop; relaunch after a wake.
- Long paths break some builds: `git config --global core.longpaths true`.
- Windows usage costs about 9 % more than Linux; avoid idle waiting. On an Outpost, undo every system setting you change.
