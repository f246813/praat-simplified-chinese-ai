import { test, expect, type Page } from '@playwright/test';
import { revealAllHistory } from './reveal';

const transcript = (page: Page) => page.locator('.transcript');
const mounted = (page: Page) => page.locator('.message').count();
const reveal = (page: Page) => page.locator('.history-reveal button');
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

test('a long history is windowed to its tail and says what it withheld', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);

  await expect.poll(() => mounted(page)).toBe(60);
  await expect(reveal(page)).toContainText('显示更早的 61 条消息');
  // The tail is what a session opened at the bottom needs, so the newest row is always mounted.
  await expect(page.locator('[data-message-id="diagram-fixture"]')).toBeAttached();
  await expect(page.locator('[data-message-id="history-0"]')).toHaveCount(0);

  await revealAllHistory(page);
  expect(await mounted(page)).toBe(121);
  await expect(reveal(page)).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('a short history is never windowed, so nothing is hidden from the reader', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await page.goto('/?demo=1');
  await page.getByRole('button', {name: '展开会话侧栏'}).click();
  await page.locator('.session-select').filter({hasText: '演示旧记录'}).click();
  await expect(page.locator('.message')).toHaveCount(2);
  await expect(reveal(page)).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('revealing earlier messages keeps the reading position instead of jumping', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);
  await expect.poll(() => mounted(page)).toBe(60);

  // The row holding the reading position must stay exactly where it is; the newly prepended
  // row legitimately becomes the topmost partially visible one, so identity is not the test.
  const offsetOf = (id: string) => transcript(page).evaluate((el, mid) => {
    const row = document.querySelector(`[data-message-id="${mid}"]`) as HTMLElement | null;
    return row ? Math.round(row.getBoundingClientRect().top - el.getBoundingClientRect().top) : Number.NaN;
  }, id);
  const before = await offsetOf('history-61');
  expect(before).toBeGreaterThanOrEqual(0);
  await reveal(page).evaluate(el => (el as HTMLElement).click());
  await expect.poll(() => mounted(page)).toBe(100);

  await expect.poll(() => offsetOf('history-61')).toBe(before);
  // And the older page really did land above the reading position.
  expect(await offsetOf('history-21')).toBeLessThan(0);
  expect(errors).toEqual([]);
});

test('scrolling to the top reveals the next page on its own', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);
  await expect.poll(() => mounted(page)).toBe(60);

  // Park just inside the reveal threshold so the reading row is known, then reach the top.
  await transcript(page).evaluate(el => { el.scrollTop = 4; });
  await expect.poll(() => mounted(page), {timeout: 4000}).toBeGreaterThan(60);
  // The revealed page is absorbed by the scroll position, so the reader stays where they were.
  expect(await transcript(page).evaluate(el => el.scrollTop)).toBeGreaterThan(100);
  await expect(reveal(page)).toContainText('显示更早的');
  expect(errors).toEqual([]);
});
