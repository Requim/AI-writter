// Browser-only verification of the deployed service through a loopback SSH tunnel.
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { execFileSync } = require('node:child_process');
const runtime = path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const { chromium } = require(path.join(runtime, 'playwright'));
const base = process.env.ACCEPTANCE_BROWSER_URL || 'http://127.0.0.1:15173';
const output = path.resolve(__dirname, '../.release/production-20261001/browser');

async function main() {
  const saved = JSON.parse(execFileSync('ssh', [
    '-i', path.join(os.homedir(), '.ssh/id_ed25519_tencent_leetionm'),
    '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes',
    'ubuntu@124.220.67.163',
    'sudo -n cat /opt/novel-writer/releases/production-20261001/acceptance-private.json',
  ], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }));
  const account = saved.accounts[0];
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.status() >= 500) errors.push(`${response.status()} ${new URL(response.url()).pathname}`);
  });
  const report = {};
  try {
    await page.goto(base + '/login');
    await page.getByLabel('邮箱').fill(account.email);
    await page.getByLabel('密码', { exact: true }).fill(account.password);
    await page.getByRole('button', { name: /登录/ }).click();
    await page.waitForURL(base + '/');
    report.normalLogin = true;
    const book = saved.books[process.env.ACCEPTANCE_BOOK_KIND || 'smoke-r3'] ||
      saved.books['smoke-r2'] || saved.books.smoke;
    await page.goto(base + '/novels/' + book.id);
    await page.getByRole('heading', { level: 1 }).waitFor();
    await page.waitForFunction(() => !document.body.textContent.includes('正在读取进度'));
    report.bookId = book.id;
    report.baseUrl = base;
    report.progressLoaded = true;
    await page.screenshot({ path: path.join(output, 'studio-desktop.png'), fullPage: true });
    const exportButton = page.getByRole('button', { name: '导出整书', exact: true });
    if (await exportButton.isEnabled()) {
      await exportButton.click();
      const download = page.waitForEvent('download');
      await page.getByText('TXT', { exact: true }).click();
      const downloaded = await download;
      await downloaded.saveAs(path.join(output, 'browser-manuscript.txt'));
      const bytes = fs.readFileSync(path.join(output, 'browser-manuscript.txt'));
      if (!bytes.subarray(0, 3).equals(Buffer.from([0xef, 0xbb, 0xbf]))) throw new Error('Download missing UTF-8 BOM');
      report.manuscriptDownload = true;
    } else {
      report.manuscriptDownload = 'not_available_before_archival';
    }
    report.desktop = await page.evaluate(() => ({
      viewport: innerWidth, document: document.documentElement.scrollWidth,
      heading: document.querySelector('h1')?.textContent,
    }));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(output, 'studio-mobile.png'), fullPage: true });
    report.mobile = await page.evaluate(() => ({
      viewport: innerWidth, document: document.documentElement.scrollWidth,
      heading: document.querySelector('h1')?.textContent,
    }));
    if (report.mobile.document > report.mobile.viewport) throw new Error('Mobile horizontal overflow');
    await page.reload();
    await page.getByRole('heading', { level: 1 }).waitFor();
    await page.waitForFunction(() => !document.body.textContent.includes('正在读取进度'));
    report.reload = true;
    if (errors.length) throw new Error(JSON.stringify(errors));
    report.browserErrors = errors;
    fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
