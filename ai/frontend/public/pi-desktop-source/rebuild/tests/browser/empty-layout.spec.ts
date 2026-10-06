import {expect, test} from '@playwright/test';

test('blank conversation fits the available window without vertical scrolling', async ({page}, testInfo) => {
  await page.goto('/?demo=1');
  await expect(page.locator('.welcome')).toBeVisible();
  const failures: unknown[] = [];
  for (const expanded of [false, true]) {
    if (expanded) await page.getByRole('button', {name:'展开会话侧栏'}).click();
    for (const [width, height] of [[1280,850], [900,640], [800,600], [640,480], [450,400], [360,320], [1600,1000]]) {
      await page.setViewportSize({width, height});
      const transcript = page.locator('.transcript');
      const size = await transcript.evaluate(el => ({client:el.clientHeight, scroll:el.scrollHeight}));
      if (size.scroll > size.client) failures.push({expanded, width, height, ...size});
      await transcript.evaluate(el => {el.scrollTop = 10000;});
      if (await transcript.evaluate(el => el.scrollTop) !== 0) failures.push({expanded, width, height, scrolled:true});
      const composer = await page.locator('.composer').boundingBox();
      expect(composer).not.toBeNull();
      expect(composer!.y + composer!.height).toBeLessThanOrEqual(height);
    }
  }
  expect(failures).toEqual([]);
  await page.setViewportSize({width:800, height:600});
  await page.screenshot({path:testInfo.outputPath('empty-minimum.png')});
});

test('welcome shortcuts still fill the composer and history remains scrollable', async ({page}) => {
  await page.goto('/?demo=1');
  await page.getByRole('button', {name:'计算VOT', exact:true}).click();
  await expect(page.getByRole('textbox', {name:'消息输入'})).toHaveText('计算VOT');
  await page.getByRole('button', {name:'展开会话侧栏'}).click();
  await page.locator('[data-session-id="demo-history"] .session-select').click();
  await expect(page.locator('.welcome')).toHaveCount(0);
  const transcript = page.locator('.transcript');
  await expect.poll(() => transcript.evaluate(el => el.scrollHeight - el.clientHeight)).toBeGreaterThan(0);
  await transcript.evaluate(el => {el.scrollTop = 1000;});
  await expect.poll(() => transcript.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  await page.locator('[data-session-id="demo-new-1"] .session-select').click();
  await expect(page.locator('.welcome')).toBeVisible();
  await expect.poll(() => transcript.evaluate(el => el.scrollHeight - el.clientHeight)).toBe(0);
});
