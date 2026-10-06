import { test, expect, type Page } from '@playwright/test';

const bar = (page: Page) => page.locator('.chat-search');
const field = (page: Page) => page.getByRole('searchbox', {name: '在会话中查找'});
const status = (page: Page) => page.locator('.chat-search-count');
const transcript = (page: Page) => page.locator('.transcript');
const highlightSizes = (page: Page) => page.evaluate(() => {
  const api = (CSS as unknown as {highlights?: Map<string, {size: number}>}).highlights;
  return {all: api?.get('transcript-search')?.size ?? 0, active: api?.get('transcript-search-active')?.size ?? 0};
});

async function openLongHistory(page: Page) {
  await page.goto('/?demo=1');
  await page.getByRole('button', {name: '展开会话侧栏'}).click();
  await page.locator('.session-select').filter({hasText: '长历史'}).click();
  await expect(page.locator('[data-message-id="diagram-fixture"]')).toBeAttached();
}

test('Mod+K opens the find bar, and hits are painted without rewriting the transcript', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);
  await expect(bar(page)).toHaveCount(0);

  await page.keyboard.press('Control+k');
  await expect(bar(page)).toBeVisible();
  await expect(field(page)).toBeFocused();

  // Exactly one mounted row carries this string, so the count is deterministic.
  await field(page).fill('未投递');
  await expect(status(page)).toHaveText('1/1');
  expect(await highlightSizes(page)).toEqual({all: 1, active: 1});
  // The highlight is painted by the CSS Custom Highlight API, not by wrapping text in the DOM.
  await expect(page.locator('.transcript-content mark')).toHaveCount(0);
  await expect(transcript(page)).toContainText('未投递');

  await field(page).fill('夹具');
  await expect(status(page)).not.toHaveText('1/1');
  const many = await highlightSizes(page);
  expect(many.all).toBeGreaterThan(5);
  expect(many.active).toBe(1);

  // Escape closes the bar and releases the highlights.
  await page.keyboard.press('Escape');
  await expect(bar(page)).toHaveCount(0);
  expect(await highlightSizes(page)).toEqual({all: 0, active: 0});
  expect(errors).toEqual([]);
});

test('next and previous move between hits and bring them into view', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);
  await page.keyboard.press('Control+k');
  await field(page).fill('夹具');
  await expect(status(page)).toHaveText(/^1\/\d+$/);

  // The active hit must end up inside the viewport, which is what "bring it into view" means.
  const activeHitInView = () => page.evaluate(() => {
    const api = (CSS as unknown as {highlights?: Map<string, Set<Range>>}).highlights;
    const range = api?.get('transcript-search-active')?.values().next().value;
    if (!range) return false;
    const viewport = document.querySelector('.transcript')!.getBoundingClientRect();
    const rect = (range as Range).getBoundingClientRect();
    return rect.top >= viewport.top - 2 && rect.bottom <= viewport.bottom + 2;
  });
  const scrollTop = () => transcript(page).evaluate(el => Math.round(el.scrollTop));
  const first = await scrollTop();
  expect(await activeHitInView()).toBe(true);

  await page.getByRole('button', {name: '下一个匹配'}).click();
  await expect(status(page)).toHaveText(/^2\/\d+$/);
  await expect.poll(activeHitInView).toBe(true);
  await expect.poll(scrollTop).toBeGreaterThan(first);

  await page.getByRole('button', {name: '上一个匹配'}).click();
  await expect(status(page)).toHaveText(/^1\/\d+$/);
  await expect.poll(activeHitInView).toBe(true);
  await expect.poll(scrollTop).toBe(first);

  // Keyboard navigation and wrapping are the same code path as the buttons.
  await field(page).press('Enter');
  await expect(status(page)).toHaveText(/^2\/\d+$/);
  await field(page).press('Shift+Enter');
  await expect(status(page)).toHaveText(/^1\/\d+$/);
  expect(errors).toEqual([]);
});

test('a query that only exists in withheld rows offers that page instead of faking a count', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);
  await expect(page.locator('.message')).toHaveCount(60);

  await page.keyboard.press('Control+k');
  // The mounted rows start at history-61, whose heading is 第 62 条夹具.
  await field(page).fill('第 30 条夹具');
  await expect(status(page)).toHaveText('无匹配');
  const hint = page.locator('.chat-search-hint');
  await expect(hint).toBeVisible();
  await expect(hint).toContainText('显示更早的 61 条消息');
  expect(await highlightSizes(page)).toEqual({all: 0, active: 0});

  // One revealed page mounts history-21..120, which is where that match lives.
  await hint.getByRole('button').click();
  await expect(page.locator('.message')).toHaveCount(100);
  await expect(status(page)).toHaveText('1/1');
  await expect(page.locator('.chat-search-hint')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('a query with no hits anywhere reports it and offers nothing', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openLongHistory(page);
  await page.keyboard.press('Control+k');
  await field(page).fill('绝对不存在的字符串');
  await expect(status(page)).toHaveText('无匹配');
  await expect(page.locator('.chat-search-hint')).toHaveCount(0);
  await expect(page.getByRole('button', {name: '下一个匹配'})).toBeDisabled();
  expect(errors).toEqual([]);
});
