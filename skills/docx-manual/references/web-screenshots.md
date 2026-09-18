# Web screenshots with Playwright

Use a script, not a browser session: the same script re-runs next sprint and produces identically framed figures. Skeleton in `assets/web_shots.template.js`; run it with `node` (Playwright installed via `npm i playwright && npx playwright install chromium`, or through an existing Playwright skill's `run.js`).

## Viewports

| Target | Viewport | Why |
|---|---|---|
| Back-office / admin web | 1600 × 1100, `deviceScaleFactor: 1` | Wide enough for data tables, short enough that one screen is one figure |
| Member / consumer site (responsive) | 414 × 896, `isMobile: true` | Clients see it on phones; the desktop layout is not what operators support |
| Block crops | same viewport, then `locator.screenshot()` or `clip` | Crop to the component; do not zoom the page |

## Long pages: one viewport per section

`fullPage: true` is unreliable on admin apps: the page itself is often `height: 100vh` with an inner scroll container, so the capture is either the first screen or a 6000-px strip that is illegible on A4. Instead:

1. Find the inner scroll container (`document.querySelector('main, .content, [class*=scroll]')`).
2. Scroll it section by section (`el.scrollTop = n * viewportHeight`), wait for the network to settle, and take a viewport screenshot each time.
3. Name them `<screen>-1.png`, `<screen>-2.png` and caption them as parts of one figure, or pick only the segments the text needs.

If a single full capture is unavoidable, enlarge the viewport to the inner container's `scrollHeight` (`page.setViewportSize({width, height: scrollHeight})`) rather than using `fullPage`.

## Login and stability

- Locate login fields by type, not by placeholder text (which changes with i18n): the non-password `input` is the account, `input[type=password]` the password, the button `getByRole('button', {name: /登入|log ?in/i})`.
- Login is often async: after clicking, wait for a post-login element (sidebar, avatar) instead of `waitForURL`. A fixed 3-second wait after `networkidle` is a pragmatic floor.
- Before each capture: `waitForLoadState('networkidle')` then `waitForTimeout(1500–2000)` so skeleton loaders and chart animations finish. Fixed waits are ugly but predictable; flaky captures cost more than two seconds.
- Copy-to-clipboard fields keep their value in `input.value`, not in text; read them with `inputValue()` when you need the real data (e.g. to find a demo account's email).
- Set the UI language explicitly (cookie, localStorage key, or `locale` in the context) so a stale browser profile cannot flip it.

## Dialogs and state

Screens that only exist in a state (a refund window, a "pending review" tab with items) need the state to exist. Create it through the app's API in a setup step of the script (or reset the demo account server-side) instead of clicking through it every run; then the capture step is idempotent.

## Output

Write PNGs straight to the project's `images/` folder with the final file names (see writing guide). Print one line per capture so the log doubles as a checklist of what was shot.
