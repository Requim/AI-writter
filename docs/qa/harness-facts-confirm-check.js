async (page) => {
  let confirmed = 0;
  await page.route('**/facts/proposals', async route => {
    const input = route.request().postDataJSON();
    await route.fulfill({ json: { token: 'synthetic-token', previous: { value_text: '辛', version: 1 }, proposal: { expected_version: 1, fact: { ...input, evidence: { quote: input.reason } } } } });
  });
  await page.route('**/facts/confirm', async route => {
    if (route.request().postDataJSON().token !== 'synthetic-token') throw Error('确认令牌不匹配');
    confirmed += 1;
    await route.fulfill({ json: { version: 2 } });
  });
  await page.reload();
  await page.getByRole('button', { name: '事实台账与冲突中心' }).click();
  await page.getByRole('button', { name: '纠错', exact: true }).click();
  await page.getByLabel('确认依据或纠错原因').fill('合成测试：核对族谱确认姓辛');
  await page.getByRole('button', { name: '预览事实变更', exact: true }).click();
  await page.getByRole('dialog', { name: '确认事实变更', exact: true }).waitFor();
  if (confirmed) throw Error('预览不应写入');
  await page.screenshot({ path: 'output/playwright/facts-confirm.png', fullPage: true });
  await page.getByRole('button', { name: '确认追加版本', exact: true }).click();
  await page.getByRole('dialog', { name: '确认事实变更', exact: true }).waitFor({ state: 'hidden' });
  if (confirmed !== 1) throw Error('应只确认一次');
}
