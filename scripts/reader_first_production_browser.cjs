// Verify the actual public production entry without mocked API responses.
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { execFileSync } = require('node:child_process');
const runtime = path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const { chromium } = require(path.join(runtime, 'playwright'));
const base = process.env.READER_PRODUCTION_URL || 'https://myunlimatedlife.top';
const output = path.resolve(__dirname, '../.release/reader-first-production-20261013/browser');

async function main() {
  const saved = JSON.parse(execFileSync('ssh', [
    '-i', path.join(os.homedir(), '.ssh/id_ed25519_tencent_leetionm'),
    '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes',
    'ubuntu@124.220.67.163',
    'sudo -n cat /opt/novel-writer/releases/reader-first-production-20261013/smoke-private.json',
  ], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }));
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.status() >= 500) errors.push(`${response.status()} ${new URL(response.url()).pathname}`);
  });
  const report = { environment: 'public_production', mocks: false, novel_id: saved.novel_id,
    screenshots: [], real_reader_validation: 'not_performed' };
  try {
    await page.goto(base + '/login');
    await page.getByLabel('邮箱').fill(saved.email);
    await page.getByLabel('密码', { exact: true }).fill(saved.password);
    await page.getByRole('button', { name: /登录/ }).click();
    await page.waitForURL(base + '/');
    report.normal_login = true;
    for (const [label, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.goto(base + '/novels/' + saved.novel_id);
      await page.getByRole('heading', { level: 1 }).waitFor();
      await page.waitForFunction(() => !document.body.textContent.includes('正在读取进度'));
      if (label === 'mobile') await page.getByRole('tab', { name: /进度/ }).click();
      const layout = await page.evaluate(() => ({
        viewport: innerWidth, document: document.documentElement.scrollWidth,
        heading: document.querySelector('h1')?.textContent,
      }));
      if (layout.document > layout.viewport) throw new Error(JSON.stringify(layout));
      if (!layout.heading?.includes('生产测试')) throw new Error('Missing test-book marker');
      const file = `studio-${label}.png`;
      await page.screenshot({ path: path.join(output, file), fullPage: true });
      report.screenshots.push({ file, source: 'real_public_api', layout });
      const chapterButtons = page.locator('.chapter-list button');
      if (await chapterButtons.count()) {
        if (label === 'mobile') await page.getByRole('tab', { name: /目录/ }).click();
        await chapterButtons.first().click();
        const reader = page.locator('.editor-panel .reader-comprehension');
        await reader.locator('summary').click();
        await reader.getByText(/模拟试读/).first().waitFor();
        for (const name of ['人物身份', '眼前关系', '当前目标', '阻碍与风险', '继续阅读的理由']) {
          await reader.getByText(name, { exact: true }).waitFor();
        }
        await reader.locator('summary').scrollIntoViewIfNeeded();
        await page.evaluate(() => window.scrollBy(0, -80));
        const reviewFile = `reader-${label}.png`;
        await page.screenshot({ path: path.join(output, reviewFile) });
        report.screenshots.push({ file: reviewFile, source: 'real_public_api_archived_report' });
        report.archived_reader_report = true;
      }
    }
    await page.reload();
    await page.getByRole('heading', { level: 1 }).waitFor();
    report.reload = true;
    report.archived_reader_report ??= 'not_available_before_archive';
    report.errors = errors;
    if (errors.length) throw new Error(JSON.stringify(errors));
    fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally {
    await context.close();
    await browser.close();
  }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
