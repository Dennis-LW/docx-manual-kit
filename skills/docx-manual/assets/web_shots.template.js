// Playwright screenshot script skeleton for operation manuals.
// Usage: node web_shots.template.js
// Fill in BASE, ACCOUNT, PASSWORD, OUT and the SHOTS list; keep one script per system.
const { chromium } = require('playwright');
const path = require('path');

const BASE = process.env.BASE_URL || 'https://dev-admin.example.com';
const ACCOUNT = process.env.SHOT_ACCOUNT || 'admin';
const PASSWORD = process.env.SHOT_PASSWORD || 'changeme';
const OUT = process.env.SHOT_OUT || path.resolve('images');
const MOBILE = process.env.SHOT_MOBILE === '1'; // member/consumer site → phone layout
// Third-party login (LINE/Google OAuth) cannot be scripted: paste the persisted
// auth store from a hand login into SHOT_SESSION_JSON ({"<localStorage key>": "<json string>"}).
// Make sure it contains what the route guard checks (e.g. authStatus: 'authenticated'),
// not only the token. See references/web-screenshots.md.
const SESSION = process.env.SHOT_SESSION_JSON ? JSON.parse(process.env.SHOT_SESSION_JSON) : null;

// One entry per figure. `steps` runs before the capture; `segments` captures a
// long page one viewport at a time (see references/web-screenshots.md).
const SHOTS = [
  { name: 'admin-01-login', url: '/login', beforeLogin: true },
  { name: 'admin-02-home', url: '/' },
  { name: 'admin-10-order-list', url: '/orders' },
  { name: 'admin-10-order-list-review-tab', url: '/orders', steps: async (p) => p.getByRole('tab', { name: /待審核|pending/i }).click() },
  { name: 'admin-18-product-form', url: '/products/1/edit', segments: 3, scroll: 'main' },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function settle(page, ms = 2000) {
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(ms);
}

async function injectStorage(context) {
  if (!SESSION) return false;
  await context.addInitScript((entries) => {
    for (const [k, v] of entries) localStorage.setItem(k, typeof v === 'string' ? v : JSON.stringify(v));
  }, Object.entries(SESSION));
  return true;
}

async function login(page) {
  await page.goto(BASE + '/login');
  await settle(page);
  const inputs = page.locator('input:not([type=password]):not([type=hidden]):not([type=checkbox])');
  await inputs.first().fill(ACCOUNT);
  await page.locator('input[type=password]').first().fill(PASSWORD);
  await page.getByRole('button', { name: /登入|log ?in|sign ?in/i }).click();
  await sleep(3000); // login is async; do not judge by URL right away
  await settle(page);
}

async function capture(page, shot) {
  const file = (suffix = '') => path.join(OUT, `${shot.name}${suffix}.png`);
  if (!shot.segments) {
    await page.screenshot({ path: file() });
    console.log('[capture]', file());
    return;
  }
  // Long page: scroll the inner container one viewport per segment.
  const sel = shot.scroll || 'main';
  const vh = page.viewportSize().height;
  for (let i = 0; i < shot.segments; i++) {
    await page.evaluate(([s, top]) => { const el = document.querySelector(s) || document.scrollingElement; el.scrollTop = top; }, [sel, i * vh]);
    await page.waitForTimeout(800);
    await page.screenshot({ path: file(`-${i + 1}`) });
    console.log('[capture]', file(`-${i + 1}`));
  }
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext(
    MOBILE
      ? { viewport: { width: 414, height: 896 }, isMobile: true, deviceScaleFactor: 2, locale: 'zh-TW' }
      : { viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 1, locale: 'zh-TW' },
  );
  let loggedIn = await injectStorage(context);   // OAuth apps: session injected, no login form
  const page = await context.newPage();
  for (const shot of SHOTS) {
    if (!shot.beforeLogin && !loggedIn) { await login(page); loggedIn = true; }
    await page.goto(BASE + shot.url);
    await settle(page);
    // steps: component-library checkboxes hide the real <input>; click the wrapper
    // (page.locator('.el-checkbox').click()), never locator.check(). Do not press a
    // submit button unless the client-side validation is known to block it.
    if (shot.steps) { await shot.steps(page); await settle(page, 1500); }
    await capture(page, shot);
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
