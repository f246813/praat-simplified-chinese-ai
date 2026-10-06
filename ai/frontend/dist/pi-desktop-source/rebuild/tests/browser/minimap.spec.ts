import { test, expect, type Page } from '@playwright/test';

const rail = (page: Page) => page.locator('.minimap-rail');
const dashes = (page: Page) => page.locator('.minimap-marker:not(.history)');
const transcript = (page: Page) => page.locator('.transcript');
const topMessage = (page: Page) => transcript(page).evaluate(el => {
  const top = el.getBoundingClientRect().top;
  const row = Array.from(document.querySelectorAll('[data-message-id]')).find(r => r.getBoundingClientRect().bottom > top) as HTMLElement | undefined;
  return row?.dataset.messageId || '';
});

async function openLongHistory(page: Page) {
  await page.goto('/?demo=1');
  await page.getByRole('button', {name: '展开会话侧栏'}).click();
  await page.locator('.session-select').filter({hasText: '长历史'}).click();
  await expect(page.locator('[data-message-id="diagram-fixture"]')).toBeAttached();
}

test('the rail mirrors the mounted history and offers the withheld page', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);

  await expect(rail(page)).toBeVisible();
  // One dash per mounted row, plus the dashed entry for the page above them.
  await expect(dashes(page)).toHaveCount(60);
  await expect(page.locator('.minimap-marker.history')).toHaveCount(1);
  await expect(page.locator('.minimap-marker.user').first()).toBeAttached();
  await expect(page.locator('.minimap-marker.assistant').first()).toBeAttached();

  await page.locator('.minimap-marker.history').click();
  await expect(dashes(page)).toHaveCount(100);
  expect(errors).toEqual([]);
});

test('the active dash follows the reading line and a click jumps to that row', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);
  await expect(dashes(page)).toHaveCount(60);

  await transcript(page).evaluate(el => { el.scrollTop = 0; });
  await expect(page.locator('.minimap-marker.active')).toHaveCount(1);
  await expect(page.locator('.minimap-marker.active')).toHaveAttribute('data-marker-id', 'history-61');

  // At the bottom the reading line sits in the last rows, not on the very last one.
  await transcript(page).evaluate(el => { el.scrollTop = el.scrollHeight; });
  const activeIndex = () => page.locator('.minimap-marker.active').evaluate(el => Array.from(document.querySelectorAll('.minimap-marker:not(.history)')).indexOf(el as Element));
  await expect.poll(activeIndex).toBeGreaterThanOrEqual(58);

  // Clicking a dash puts that row at the top of the viewport.
  await page.locator('[data-marker-id="history-71"]').click();
  await expect.poll(() => topMessage(page)).toBe('history-71');
  await expect(page.locator('.minimap-marker.active')).toHaveAttribute('data-marker-id', 'history-71');
  expect(errors).toEqual([]);
});

test('hovering a dash previews that row without leaving the rail', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);
  await expect(dashes(page)).toHaveCount(60);

  await expect(page.locator('.minimap-popover')).toHaveCount(0);
  // history-62 is a user turn, history-63 the assistant's answer to it.
  await page.locator('[data-marker-id="history-62"]').hover();
  const popover = page.locator('.minimap-popover');
  await expect(popover).toBeVisible();
  await expect(popover.locator('.minimap-popover-role')).toHaveText('你');
  await expect(popover.locator('.minimap-popover-text')).toContainText('演示历史问题 63');
  // The magnification is written imperatively, so it must be gone once the pointer leaves.
  await expect(page.locator('[data-marker-id="history-62"]')).toHaveCSS('--magnify', /.+/);
  await page.locator('[data-marker-id="history-63"]').hover();
  await expect(popover.locator('.minimap-popover-role')).toHaveText('声学助手');
  await expect(popover.locator('.minimap-popover-text')).toContainText('第 64 条夹具');
  await page.locator('.composer').hover();
  await expect(page.locator('.minimap-popover')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('a history that fits needs no rail', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await page.goto('/?demo=1');
  await page.getByRole('button', {name: '展开会话侧栏'}).click();
  await page.locator('.session-select').filter({hasText: '演示旧记录'}).click();
  await expect(page.locator('.message')).toHaveCount(2);
  await expect(rail(page)).toHaveCount(0);
  expect(errors).toEqual([]);
});
