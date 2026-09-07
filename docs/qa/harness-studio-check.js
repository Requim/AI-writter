async (page) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.getByRole('tab', { name: 'project 规划' }).click();
  for (const view of [
    { name: 'book 整书', text: '结局要求', file: 'plan' },
    { name: 'aim 近期推进方案', text: '找到族谱缺页的去向', file: 'tactical' },
  ]) {
    await page.getByRole('tab', { name: view.name, exact: true }).click();
    await page.getByText(view.text, { exact: true }).waitFor();
    for (const width of [375, 768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) {
        throw new Error('横向溢出: ' + view.file + ' ' + width);
      }
      await page.screenshot({ path: 'output/playwright/' + view.file + '-' + width + '.png', fullPage: true });
    }
  }
  await page.getByRole('button', { name: '接受当前版本', exact: true }).click();
  await page.getByText('仍要接受当前章节？', { exact: true }).waitFor();
  await page.getByRole('button', { name: '返回核对', exact: true }).click();
  await page.getByRole('button', { name: '接受当前版本', exact: true }).waitFor();
}
