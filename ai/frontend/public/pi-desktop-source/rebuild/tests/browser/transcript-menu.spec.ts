import { test, expect, type Page } from '@playwright/test';
import { revealAllHistory } from './reveal';

const openOnMessage = async (page: Page, id: string, button: 'right' = 'right') => {
  await page.locator(`[data-message-id="${id}"] .message-content`).click({button});
  await expect(page.getByRole('menu')).toBeVisible();
};

async function openLongHistory(page: Page) {
  await page.goto('/?demo=1');
  await page.getByRole('button', {name: '展开会话侧栏'}).click();
  await page.locator('.session-select').filter({hasText: '长历史'}).click();
  await revealAllHistory(page);
  await expect(page.locator('[data-message-id="history-0"]')).toBeAttached();
}

test('a message row offers only the actions this host can carry out', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);

  await page.locator('[data-message-id="history-0"]').evaluate(el => el.scrollIntoView({block: 'center'}));
  await page.waitForTimeout(200);
  await openOnMessage(page, 'history-0');
  const labels = await page.getByRole('menuitem').allInnerTexts();
  expect(labels).toEqual(['复制消息', '选择消息文本']);

  // The tool row additionally exposes its structured evidence, and nothing else.
  await page.keyboard.press('Escape');
  await expect(page.getByRole('menu')).toHaveCount(0);
  await page.locator('[data-message-id="diagram-fixture"]').evaluate(el => el.scrollIntoView({block: 'center'}));
  await page.waitForTimeout(200);
  await openOnMessage(page, 'diagram-fixture');
  expect(await page.getByRole('menuitem').allInnerTexts()).toEqual(['复制消息', '选择消息文本', '复制结构化证据']);
  // Menu mutation of history is not offered because no RPC can honour it.
  for (const label of ['编辑', '删除', '重新生成', '分支']) await expect(page.getByRole('menuitem', {name: label})).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('the transcript background offers the conversation actions and the selection actions work', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);

  const transcript = page.locator('.transcript');
  const box = (await transcript.boundingBox())!;
  // Dispatched on the scroller itself: that is the transcript background, not a row.
  const openBackground = async () => {
    await transcript.dispatchEvent('contextmenu', {clientX: box.x + box.width / 2, clientY: box.y + box.height / 2, bubbles: true});
    await expect(page.getByRole('menu')).toBeVisible();
  };
  await openBackground();
  expect(await page.getByRole('menuitem').allInnerTexts()).toEqual(['复制整个会话', '选择会话文本', '跳到顶部', '回到最新']);

  // Selecting the conversation text must reach the platform selection, not a private copy.
  await page.getByRole('menuitem', {name: '选择会话文本'}).click();
  const selected = await page.evaluate(() => window.getSelection()?.toString() ?? '');
  expect(selected).toContain('演示历史问题');
  expect(selected.length).toBeGreaterThan(100);

  await openBackground();
  await page.getByRole('menuitem', {name: '跳到顶部'}).click();
  await expect.poll(() => transcript.evaluate(el => el.scrollTop)).toBeLessThanOrEqual(1);
  await openBackground();
  await page.getByRole('menuitem', {name: '回到最新'}).click();
  await expect.poll(() => transcript.evaluate(el => Math.round(el.scrollHeight - el.clientHeight - el.scrollTop))).toBeLessThanOrEqual(2);
  expect(errors).toEqual([]);
});
