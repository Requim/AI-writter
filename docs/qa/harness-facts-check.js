async (page) => {
  await page.reload();
  await page.getByRole('button', { name: '事实台账与冲突中心' }).click();
  await page.getByRole('cell', { name: '辛远', exact: true }).waitFor();
  for (const width of [375, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    const dialog = page.getByRole('dialog', { name: '事实台账与冲突中心' });
    await dialog.evaluate(element => Promise.allSettled(element.getAnimations({ subtree: true }).map(animation => animation.finished)));
    const bounds = await dialog.boundingBox();
    if (!bounds || bounds.x < -1 || bounds.x + bounds.width > width + 1) throw new Error('台账抽屉超出视口: ' + JSON.stringify({ width, bounds }));
    await page.screenshot({ path: 'output/playwright/facts-' + width + '.png', fullPage: true });
  }
  await page.getByRole('tab', { name: '冲突与章节记录' }).click();
  await page.getByText('历史章节未验证', { exact: true }).waitFor();
  await page.screenshot({ path: 'output/playwright/facts-conflicts.png', fullPage: true });
}
