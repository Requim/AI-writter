// Local API persistence is real; successful provider output is an explicit UI fixture.
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const assert = require('node:assert/strict');
const runtime = path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const { chromium } = require(path.join(runtime, 'playwright'));
const base = process.env.WORKBENCH_BASE_URL || 'http://127.0.0.1:5173';
const output = path.resolve(__dirname, '../.release/workbench-qa/browser');
const sampleReply = '雨停了，师父把青玉剑放回桌上。\n\n他决定在天亮前离开旧车站。';

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const report = { environment: 'local_native_postgresql', providerOutput: 'explicit_browser_fixture', screenshots: [] };
  try {
    const registration = await context.request.post(base + '/api/v1/auth/register', {
      data: { email: `workbench-${Date.now()}@example.test`, password: 'Workbench-QA-2026', tenant_name: '本地验收编辑部' },
    });
    assert.equal(registration.status(), 201, await registration.text());
    const session = await registration.json();
    const tenant = session.tenants[0].id;
    const headers = { Authorization: `Bearer ${session.access_token}`, 'X-Tenant-ID': tenant };
    await context.addInitScript(state => localStorage.setItem('novel-writer-auth', JSON.stringify(state)), {
      state: { accessToken: session.access_token, refreshToken: session.refresh_token,
        user: session.user, tenants: session.tenants, currentTenantId: tenant }, version: 0,
    });
    await page.goto(base + '/novels/new');
    await page.getByLabel('作品名', { exact: true }).fill('青玉剑与旧车站的最后一次约定');
    await page.getByLabel('故事起点', { exact: true }).fill('师父带着一封迟到十年的信，回到已停运的车站。');
    const creation = page.waitForResponse(response => response.url().endsWith('/api/v1/novels') && response.request().method() === 'POST');
    await page.getByRole('button', { name: '创建并开始讨论', exact: true }).click();
    const createdResponse = await creation;
    assert.equal(createdResponse.status(), 201, await createdResponse.text());
    const novel = (await createdResponse.json()).novel_id;
    await page.waitForURL(base + '/novels/' + novel);
    await page.getByRole('heading', { name: '青玉剑与旧车站的最后一次约定', exact: true }).waitFor();
    const api = `/api/v1/novels/${novel}/workbench`;
    report.simpleCreation = true;

    await page.getByRole('button', { name: '新建会话', exact: true }).click();
    await page.getByLabel('对话内容', { exact: true }).fill('讨论师父为什么回来');
    const request = page.waitForResponse(response => response.url().includes('/messages') && response.request().method() === 'POST');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    const submitted = await request;
    assert.equal(submitted.status(), 202, await submitted.text());
    const job = await submitted.json();
    await page.getByRole('button', { name: /重试任务/ }).waitFor();
    await page.reload();
    await page.getByText('讨论师父为什么回来', { exact: true }).waitFor();
    await page.getByRole('button', { name: /重试任务/ }).waitFor();
    report.missingCredentialsFailureRestored = true;

    const worldResponse = await context.request.post(base + api + '/assets', {
      headers, data: { title: '青玉剑的规则', kind: 'world', content: '青玉剑不可损毁。师父始终失明。' },
    });
    assert.equal(worldResponse.status(), 201, await worldResponse.text());
    const world = await worldResponse.json();
    const detailResponse = await context.request.get(base + api + '/conversations/' + job.conversation_id, { headers });
    const detail = await detailResponse.json();
    const fixtureSource = { source_type: 'asset', source_id: world.id, title: world.title,
      version: world.version, start: 0, end: world.content.length, text: world.content, score: 1 };
    const fixtureJob = { ...job, status: 'completed', content: sampleReply, error: null,
      sources: [fixtureSource], retrieval_available: true };
    await page.route('**' + api + '/conversations/' + job.conversation_id, route => route.fulfill({
      json: { ...detail, messages: detail.messages.map(message => message.id === job.message_id
        ? { ...message, status: 'completed', content: sampleReply, sources: [fixtureSource] } : message) },
    }));
    await page.route('**' + api + '/jobs/' + job.id, route => route.fulfill({ json: fixtureJob }));
    await page.reload();
    await page.getByText('雨停了，师父把青玉剑放回桌上。', { exact: true }).waitFor();
    await page.getByRole('button', { name: '查看来源 1', exact: true }).click();
    await page.getByText(world.id, { exact: true }).waitFor();
    await page.getByText(`偏移 0-${world.content.length}`, { exact: true }).waitFor();
    await page.locator('.ant-drawer-open .ant-drawer-close').click();
    report.replyProvenance = true;

    await page.getByRole('button', { name: /保存全文/ }).click();
    const editor = page.getByRole('dialog', { name: '保存为资产', exact: true });
    await editor.getByLabel('名称', { exact: true }).fill('第一章候选稿');
    await editor.getByRole('combobox').click();
    await page.locator('.ant-select-dropdown').getByText('章节草稿', { exact: true }).click();
    const [savedResponse] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith(api + '/assets') && response.request().method() === 'POST'),
      editor.locator('.ant-modal-footer .ant-btn-primary').click(),
    ]);
    assert.equal(savedResponse.status(), 201, await savedResponse.text());
    const asset = await savedResponse.json();
    assert.equal(asset.content, sampleReply);
    await page.getByText('第一章候选稿', { exact: true }).waitFor();
    const official = await context.request.get(base + `/api/v1/novels/${novel}/chapters`, { headers });
    assert.deepEqual(await official.json(), []);
    report.saveFullDraftDoesNotAdopt = true;

    await page.locator('.conversation-message.assistant .message-markdown').evaluate(element => {
      const paragraph = element.querySelector('p');
      const range = document.createRange();
      range.selectNodeContents(paragraph);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    });
    await page.getByRole('button', { name: '保存选中', exact: true }).click();
    await editor.getByLabel('名称', { exact: true }).fill('开头选段');
    assert.equal(await editor.getByLabel('内容', { exact: true }).inputValue(), '雨停了，师父把青玉剑放回桌上。');
    await editor.locator('.ant-modal-footer .ant-btn-primary').click();
    await page.getByText('开头选段', { exact: true }).waitFor();
    report.saveSelection = true;

    await page.getByLabel('检索来源', { exact: true }).fill('青玉剑');
    await page.getByLabel('检索来源', { exact: true }).press('Enter');
    const drawer = page.locator('.ant-drawer').filter({ hasText: '检索来源' });
    await drawer.getByText('青玉剑的规则', { exact: true }).waitFor();
    assert.equal(await drawer.getByText('第一章候选稿', { exact: true }).count(), 0);
    await page.locator('.ant-drawer-open .ant-drawer-close').click();
    report.keywordRetrievalExcludesDrafts = true;

    for (const [label, width, height] of [['desktop', 1440, 1000], ['tablet', 820, 1000], ['mobile', 390, 844]]) {
      await page.setViewportSize({ width, height });
      await page.goto(base + '/novels/' + novel);
      await page.getByRole('heading', { name: '青玉剑与旧车站的最后一次约定', exact: true }).waitFor();
      await page.locator('.conversation-message.assistant').getByText('雨停了，师父把青玉剑放回桌上。', { exact: true }).waitFor();
      const layout = await page.evaluate(() => ({
        viewport: innerWidth, document: document.documentElement.scrollWidth,
        visibleComposer: document.querySelector('.conversation-composer').getBoundingClientRect().bottom <= innerHeight + 1,
        composerAtBottom: document.querySelector('.conversation-composer').getBoundingClientRect().bottom >= innerHeight - 20,
      }));
      assert.equal(layout.document <= layout.viewport, true, JSON.stringify(layout));
      assert.equal(layout.visibleComposer, true, JSON.stringify(layout));
      assert.equal(layout.composerAtBottom, true, JSON.stringify(layout));
      const file = `workbench-${label}.png`;
      await page.screenshot({ path: path.join(output, file), fullPage: true });
      report.screenshots.push({ file, layout });
      if (width < 920) {
        await page.locator('.workbench-mobile-tabs').getByText('资产', { exact: true }).click();
        await page.getByText('第一章候选稿', { exact: true }).waitFor();
        await page.screenshot({ path: path.join(output, `assets-${label}.png`), fullPage: true });
      }
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole('link', { name: /原工作台/ }).click();
    await page.waitForURL(base + '/novels/' + novel + '/studio');
    await page.getByRole('heading', { level: 1 }).waitFor();
    report.legacyStudioAvailable = true;
    report.errors = errors;
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    console.error((await page.locator('body').innerText()).slice(-5000));
    throw error;
  } finally {
    await context.close();
    await browser.close();
  }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
