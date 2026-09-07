async (page) => {
  await page.getByRole('heading', { name: '正文事实核对' }).waitFor();
  if (!await page.getByRole('button', { name: '人工核对后继续' }).isDisabled()) throw new Error('硬冲突接受未禁用');
  for (const width of [375, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    const progress = page.getByRole('tab', { name: 'history 进度' });
    if (await progress.isVisible()) await progress.click();
    await page.getByRole('heading', { name: '正文事实核对' }).scrollIntoViewIfNeeded();
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('事实复核横向溢出: ' + width);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: 'output/playwright/fact-review-' + width + '.png', fullPage: true });
  }
}
