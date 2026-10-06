// Read-only observer for the production WebView2 opened by the real native menu.
const { chromium } = require('../frontend/node_modules/playwright');
(async () => {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9337');
  try {
    const page = browser.contexts().flatMap(c => c.pages()).find(p => /^http:\/\/127\.0\.0\.1:\d+\/index\.html$/.test(p.url()));
    if (!page) throw Error('No production WebView2 page');
    await page.getByRole('button', { name: '新建会话', exact: true }).first().waitFor();
    const result = await page.evaluate(async () => {
      const boot = await window.pywebview.api.rpc('bootstrap', {});
      return { url: location.href, api: Object.keys(window.pywebview.api), host: boot.host,
        taskCount: boot.tasks.length, demoBanner: document.body.innerText.includes('浏览器测试适配器') };
    });
    if (result.demoBanner) throw Error('Demo page is not acceptance evidence');
    console.log(JSON.stringify(result));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
