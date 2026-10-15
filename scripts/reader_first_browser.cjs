// Verify the isolated UI, with explicit fixtures for title and failed-review states.
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { execFileSync } = require('node:child_process');
const runtime = path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const { chromium } = require(path.join(runtime, 'playwright'));
const base = 'http://127.0.0.1:15184';
const output = path.resolve(__dirname, '../.release/reader-first-20261013/browser');
const longTitle = '重来七次以后我终于知道她为什么没有等我一起回家';
const fixtures = {
  title: {
    action: 'confirm_or_provide_title',
    ai_suggestions: [{ title: longTitle, hint: '明确设定与人物关系的布局测试候选', total_score: 86, score_max: 100 }],
  },
  reader: {
    action: 'quality_gate_human_review', chapter_number: 1,
    proposal: { proposal_id: 'browser-layout-fixture', kind: 'reflection', version: 1, payload: { gate: {
      reader_review_required: true,
      reader_comprehension: { status: 'failed', source: 'simulated_reader', report: {
        checks: [{ key: 'goal', status: 'unclear', answer: '不知道她为什么反复整理纸杯',
          evidence: [{ source: 'current', quote: '她又把纸杯推过去' }] }],
        issues: [{ kind: 'padding', quote: '她又把纸杯推过去', reason: '动作没有推动事情',
          suggestion: '让对白说清当前需要办的事', blocking: true }],
      } },
    } } },
  },
};

async function main() {
  const saved = JSON.parse(execFileSync('ssh', [
    '-i', path.join(os.homedir(), '.ssh/id_ed25519_tencent_leetionm'),
    '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes',
    'ubuntu@124.220.67.163',
    'sudo -n cat /opt/novel-writer/releases/reader-first-20261013/acceptance-private.json',
  ], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }));
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const report = { environment: 'isolated_qa', mockStates: ['title', 'reader'], screenshots: [] };
  try {
    await page.goto(base + '/login');
    await page.getByLabel('邮箱').fill(saved.email);
    await page.getByLabel('密码', { exact: true }).fill(saved.password);
    await page.getByRole('button', { name: /登录/ }).click();
    await page.waitForURL(base + '/');
    report.normalLogin = true;
    const novel = saved.books.romance.id;
    await page.goto(base + '/novels/' + novel);
    await page.getByRole('heading', { level: 1 }).waitFor();
    await page.screenshot({ path: path.join(output, 'actual-studio-desktop.png'), fullPage: true });
    for (const [name, interrupt] of Object.entries(fixtures)) {
      await page.route(`**/api/v1/workflows/${novel}/state`, route => route.fulfill({
        json: { thread_id: novel, status: 'paused', has_interrupt: true, interrupts: [interrupt],
          next_nodes: [name === 'title' ? 'title_review_node' : 'reflection_review_node'],
          has_pending_checkpoint: true, execution: { status: 'idle', auto_mode: false },
          state: { current_chapter_index: 0, auto_mode: false, chapter_outlines: [],
            reader_comprehension: interrupt.proposal?.payload.gate.reader_comprehension } },
      }));
      for (const [label, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
        await page.setViewportSize({ width, height });
        await page.goto(base + '/novels/' + novel);
        await page.getByRole('heading', { level: 1 }).waitFor();
        if (label === 'mobile') await page.getByRole('tab', { name: /进度/ }).click();
        const target = page.getByText(name === 'title' ? longTitle : '不知道她为什么反复整理纸杯', { exact: true });
        await target.first().waitFor();
        await target.first().scrollIntoViewIfNeeded();
        if (name === 'title') {
          await page.getByRole('button', { name: new RegExp(longTitle) }).first().click();
          await page.getByRole('button', { name: /确认使用/ }).waitFor();
          await page.getByText('86 / 100').waitFor();
        } else {
          if (await page.getByRole('button', { name: '接受当前版本', exact: true }).count()) {
            throw new Error('Failed reader gate offers acceptance');
          }
          await page.getByText(/模拟试读/).first().waitFor();
        }
        const layout = await page.evaluate(() => ({
          viewport: innerWidth, document: document.documentElement.scrollWidth,
          overflow: [...document.querySelectorAll('.title-review button, .title-decision-actions button, .reader-comprehension')]
            .filter(el => el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 2).map(el => el.className),
        }));
        if (layout.document > layout.viewport || layout.overflow.length) throw new Error(JSON.stringify(layout));
        const file = `${name}-${label}.png`;
        await page.screenshot({ path: path.join(output, file), fullPage: true });
        report.screenshots.push({ file, source: 'browser_layout_fixture', layout });
      }
      await page.unroute(`**/api/v1/workflows/${novel}/state`);
    }
    for (const [label, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.goto(base + '/novels/' + saved.books.suspense.id);
      await page.getByRole('heading', { level: 1 }).waitFor();
      if (label === 'mobile') await page.getByRole('tab', { name: /目录/ }).click();
      if (!await page.locator('.chapter-list button').count()) {
        await page.locator('.studio-navigation-switch').getByText('目录', { exact: true }).click();
      }
      await page.locator('.chapter-list button').first().click();
      const review = page.locator('.editor-panel .reader-comprehension');
      await review.locator('summary').click();
      await review.getByText('模拟试读 · 理解验收通过', { exact: true }).waitFor();
      for (const name of ['人物身份', '眼前关系', '当前目标', '阻碍与风险', '继续阅读的理由']) {
        await review.getByText(name, { exact: true }).waitFor();
      }
      const layout = await page.evaluate(() => ({
        viewport: innerWidth, document: document.documentElement.scrollWidth,
      }));
      if (layout.document > layout.viewport) throw new Error(JSON.stringify(layout));
      const file = `archived-reader-${label}.png`;
      await review.locator('summary').scrollIntoViewIfNeeded();
      await page.evaluate(() => window.scrollBy(0, -80));
      await page.screenshot({ path: path.join(output, file) });
      report.screenshots.push({ file, source: 'real_api_archived_chapter', layout });
    }
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
