// Keeps the SLUGGER Streamlit Community Cloud apps awake.
// Community Cloud puts apps to sleep after ~12h without real visitor sessions;
// plain HTTP pings don't count, so this opens each app in headless Chromium,
// clicks the wake-up button if the app is asleep, and holds the websocket
// session long enough to register as activity. Run by .github/workflows/keepalive.yml.
const { chromium } = require("playwright");

const URLS = [
  "https://slugger-stats-widget2.streamlit.app/",
  "https://baseball-general-statistics-widget-alpb.streamlit.app/",
];

const HOLD_MS = 45000;

(async () => {
  const browser = await chromium.launch();
  let failures = 0;
  for (const url of URLS) {
    const page = await browser.newPage();
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
      const wakeButton = page.getByText(/get this app back up/i).first();
      if (await wakeButton.isVisible({ timeout: 8000 }).catch(() => false)) {
        await wakeButton.click().catch(() => {});
        console.log(`[wake clicked] ${url}`);
        await page.waitForTimeout(30000); // give the container time to boot
      }
      await page.waitForTimeout(HOLD_MS);
      console.log(`[ok] ${url}`);
    } catch (err) {
      failures += 1;
      console.error(`[fail] ${url}: ${err.message}`);
    } finally {
      await page.close();
    }
  }
  await browser.close();
  process.exit(failures > 0 ? 1 : 0);
})();
