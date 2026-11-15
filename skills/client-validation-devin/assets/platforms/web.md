### Web guide

#### Environment facts
- Linux (Ubuntu) VM. User `ubuntu`, bash, home `/home/ubuntu`, repos in `~/repos/<repo>`, attached files in `~/.files/`.
- Devin's Chrome exposes the Chrome DevTools Protocol at `http://localhost:29229`; Playwright attaches to it, so the browser
  you see through Computer Use and the scripted one are the same.
- Playwright without a browser download, outside the repo: `python3 -m venv /tmp/qa/venv && /tmp/qa/venv/bin/pip install playwright`
  (or `cd /tmp/qa && npm i playwright`). Never add dependencies to the product repo.
- Working folders: `mkdir -p /tmp/qa/evidence`.

#### Build and install
- Use the spec's `setup`, `build` and `artifact` first. Fallbacks by stack:
  - Vite / React / Vue / Svelte: `npm install && npm run build && npx --yes serve -s dist -l 4173` (Next.js: `npm run build && npm start`).
  - Flutter web: `flutter build web` then `python3 -m http.server 8080 -d build/web`.
  - Compose for Web (Wasm): `./gradlew :composeApp:wasmJsBrowserDistribution`, serve the `productionExecutable` folder it prints.
- Run servers in the background with logs: `<command> > /tmp/qa/web-server.log 2>&1 &`, then wait:
  `until curl -sf http://127.0.0.1:<port> > /dev/null; do sleep 1; done`.

#### Launch and crash detection
- Open the app in a fresh browser context so cookies from earlier checks do not leak into first-launch scenarios.
- Record console errors, uncaught exceptions and failed requests while you test:

```python
import json
from playwright.sync_api import sync_playwright
log = []
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:29229")
    page = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
    page.on("console", lambda m: m.type in ("error", "warning") and log.append(["console", m.type, m.text]))
    page.on("pageerror", lambda e: log.append(["pageerror", str(e)]))
    page.on("requestfailed", lambda r: log.append(["requestfailed", r.url, r.failure]))
    page.on("response", lambda r: r.status >= 400 and log.append(["http", r.status, r.url]))
    page.goto("http://127.0.0.1:4173", wait_until="networkidle")
    page.screenshot(path="/tmp/qa/evidence/r<round>-web__launch__390x844_light_en_std__01.png", full_page=True)
json.dump(log, open("/tmp/qa/web-console.json", "w"), indent=1)
```
- A blank page (empty `document.body.innerText` and no visible elements), an uncaught exception or a 5xx response on load is a
  launch failure. Server-side errors also appear in `/tmp/qa/web-server.log`.

#### Screenshots
- `page.screenshot(path=..., full_page=True)` for whole pages, `locator.screenshot(path=...)` for one component.
- Variant = size_theme_locale_scale, scale `std` or `xl`, e.g. `r2-web__create-note__390x844_dark_de_xl__03.png`.
- Attach the files to your messages and list their names in `evidence_files`.

#### Interaction
- Computer Use in Chrome first. Scripted fallback with Playwright locators: `page.get_by_role("button", name="Save").click()`,
  `page.get_by_label("Title").fill("Groceries")`, `page.keyboard.press("Control+S")`.
- Keep the CDP browser alive: close only the contexts and pages you created.

#### Layout matrix switches
- Size: spec `window_sizes`, otherwise 390x844 (phone), 768x1024 (tablet), 1440x900 (desktop): `page.set_viewport_size({"width": 768, "height": 1024})`.
- Theme: `page.emulate_media(color_scheme="dark")`; reduced motion: `page.emulate_media(reduced_motion="reduce")`.
- Locale: a new context per locale, `browser.new_context(locale="de-DE", viewport=...)`, plus the app's own language switch if it has one.
- Largest text: `page.add_style_tag(content="html { font-size: 200% !important; }")` after load, then re-check the layout.

#### UI tree dump for overlap checks
- Flags horizontal page overflow, clipped text, elements outside the viewport and overlapping visible leaf elements:

```python
JS = """() => {
  const out = [], W = document.documentElement.clientWidth;
  const name = e => (e.innerText || e.getAttribute('aria-label') || e.getAttribute('alt') || e.tagName).trim().slice(0, 40);
  const els = [...document.querySelectorAll('body *')].filter(e => {
    const s = getComputedStyle(e), r = e.getBoundingClientRect();
    return e.children.length === 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0 &&
      r.width > 0 && r.height > 0 && (e.innerText || e.getAttribute('aria-label') || ['IMG', 'INPUT', 'BUTTON'].includes(e.tagName));
  });
  if (document.documentElement.scrollWidth > W + 1) out.push(['HSCROLL', document.documentElement.scrollWidth, W]);
  for (const e of els) {
    const r = e.getBoundingClientRect();
    if (r.left < -1 || r.right > W + 1) out.push(['OFFSCREEN', name(e)]);
    if (e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible') out.push(['CLIPPED', name(e)]);
  }
  for (let i = 0; i < els.length; i++) for (let j = i + 1; j < els.length; j++) {
    const a = els[i].getBoundingClientRect(), b = els[j].getBoundingClientRect();
    const iw = Math.min(a.right, b.right) - Math.max(a.left, b.left), ih = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    if (iw > 0 && ih > 0 && iw * ih / Math.min(a.width * a.height, b.width * b.height) > 0.2) out.push(['OVERLAP', name(els[i]), name(els[j])]);
  }
  return out;
}"""
for row in page.evaluate(JS): print(*row)
```
- Run it on every screen and variant of the matrix; sticky headers overlapping scrolled content are expected, so confirm each
  hit on the screenshot before reporting it.

#### Logs to attach
- `/tmp/qa/web-console.json`, `/tmp/qa/web-server.log` (last 300 lines), the build log on failure, test reports from the spec's
  `test` command (for example Playwright's `playwright-report` folder zipped).

#### Known pitfalls
- The Chrome profile is shared and persistent; use new contexts for clean-state scenarios.
- Service workers can serve an old build: test in a new context or unregister them before judging a change.
- `localhost` and `127.0.0.1` are different origins for cookies and storage; use the one the app expects.
- CJK pages need `sudo apt-get install -y fonts-noto-cjk`; boxes instead of glyphs are an environment problem.
- The VM sleeps after idle periods and dev servers stop; restart them after a wake.
