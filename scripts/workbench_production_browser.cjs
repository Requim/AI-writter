// Exercise real production APIs and the single marked provider reply.
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const runtime = path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const { chromium } = require(path.join(runtime, 'playwright'));
const base = 'https://myunlimatedlife.top';
const output = path.resolve(__dirname, '../.release/workbench-production-20261014/browser');

async function main() {
  const saved = JSON.parse(execFileSync('ssh', [
    '-i', path.join(os.homedir(), '.ssh/id_ed25519_tencent_leetionm'),
    '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes',
    'ubuntu@124.220.67.163',
    'sudo -n cat /opt/novel-writer/releases/workbench-production-20261014/smoke-private.json',
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
  const report = { environment: 'public_production', mocks: false, novel_id: saved.novel_id, screenshots: [] };
  try {
    await page.goto(base + '/login');
    await page.getByLabel('邮箱').fill(saved.email);
    await page.getByLabel('密码', { exact: true }).fill(saved.password);
    await page.getByRole('button', { name: /登录/ }).click();
    await page.waitForURL(base + '/');
    report.normalLogin = true;
    const auth = await page.evaluate(() => JSON.parse(localStorage.getItem('novel-writer-auth')).state);
    const headers = { Authorization: `Bearer ${auth.accessToken}`, 'X-Tenant-ID': saved.tenant_id };
    const api = `/api/v1/novels/${saved.novel_id}/workbench`;
    const jobResponse = await context.request.get(base + api + '/jobs/' + saved.job_id, { headers });
    assert.equal(jobResponse.status(), 200);
    const job = await jobResponse.json();
    assert.equal(job.status, 'completed', `Real provider status: ${job.status}; ${job.error}`);
    assert.ok(job.content.trim().length);
    const stream = await context.request.get(base + api + '/jobs/' + saved.job_id + '/stream', { headers });
    assert.equal(stream.status(), 200);
    assert.match(await stream.text(), /event: snapshot/);
    report.realReplyAndSSE = true;
    await page.goto(base + '/novels/' + saved.novel_id);
    await page.getByRole('heading', { name: '[生产测试]对话资产检索20261014', exact: true }).waitFor();
    await page.locator('.conversation-message.assistant .message-markdown').waitFor();
    await page.getByRole('button', { name: /查看来源/ }).click();
    await page.getByText(saved.asset_id, { exact: true }).first().waitFor();
    await page.locator('.ant-drawer-open .ant-drawer-close').click();
    report.replyProvenance = true;

    await page.getByRole('button', { name: /保存全文/ }).click();
    const editor = page.getByRole('dialog', { name: '保存为资产', exact: true });
    await editor.getByLabel('名称', { exact: true }).fill('生产验收候选稿');
    await editor.getByRole('combobox').click();
    await page.locator('.ant-select-dropdown').getByText('章节草稿', { exact: true }).click();
    const [assetResponse] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith(api + '/assets') && response.request().method() === 'POST'),
      editor.locator('.ant-modal-footer .ant-btn-primary').click(),
    ]);
    assert.equal(assetResponse.status(), 201);
    const asset = await assetResponse.json();
    assert.equal(asset.content, job.content);
    assert.equal(asset.source_message_id, job.message_id);
    await page.getByText('生产验收候选稿', { exact: true }).waitFor();
    const official = await context.request.get(base + `/api/v1/novels/${saved.novel_id}/chapters`, { headers });
    assert.deepEqual(await official.json(), []);
    report.saveFullDraftDoesNotAdopt = true;

    const selected = await page.locator('.conversation-message.assistant .message-markdown').evaluate(element => {
      const paragraph = element.querySelector('p') || element;
      const range = document.createRange();
      range.selectNodeContents(paragraph);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      return selection.toString();
    });
    await page.getByRole('button', { name: '保存选中', exact: true }).click();
    await editor.getByLabel('名称', { exact: true }).fill('生产验收选段');
    assert.equal(await editor.getByLabel('内容', { exact: true }).inputValue(), selected);
    await editor.locator('.ant-modal-footer .ant-btn-primary').click();
    await page.getByText('生产验收选段', { exact: true }).waitFor();
    report.saveSelection = true;
    await page.getByLabel('检索来源', { exact: true }).fill('青玉剑');
    await page.getByLabel('检索来源', { exact: true }).press('Enter');
    const drawer = page.locator('.ant-drawer').filter({ hasText: '检索来源' });
    await drawer.getByText('青玉剑规则', { exact: true }).waitFor();
    assert.equal(await drawer.getByText('生产验收候选稿', { exact: true }).count(), 0);
    await page.locator('.ant-drawer-open .ant-drawer-close').click();
    report.keywordRetrievalExcludesDrafts = true;

    for (const [label, width, height] of [['desktop', 1440, 1000], ['tablet', 820, 1000], ['mobile', 390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.goto(base + '/novels/' + saved.novel_id);
      await page.getByRole('heading', { name: '[生产测试]对话资产检索20261014', exact: true }).waitFor();
      await page.locator('.conversation-message.assistant .message-markdown').waitFor();
      const layout = await page.evaluate(() => ({
        viewport: innerWidth, document: document.documentElement.scrollWidth,
        visibleComposer: document.querySelector('.conversation-composer').getBoundingClientRect().bottom <= innerHeight + 1,
      }));
      assert.ok(layout.document <= layout.viewport && layout.visibleComposer, JSON.stringify(layout));
      const file = `workbench-${label}.png`;
      await page.screenshot({ path: path.join(output, file), fullPage: true });
      report.screenshots.push({ file, layout });
      if (width < 920) {
        await page.locator('.workbench-mobile-tabs').getByText('资产', { exact: true }).click();
        await page.getByText('生产验收候选稿', { exact: true }).waitFor();
      }
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole('link', { name: /原工作台/ }).click();
    await page.waitForURL(base + '/novels/' + saved.novel_id + '/studio');
    await page.getByRole('heading', { level: 1 }).waitFor();
    report.legacyStudioAvailable = true;
    report.errors = errors;
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
