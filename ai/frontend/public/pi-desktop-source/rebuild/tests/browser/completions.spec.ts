import { test, expect, type Page } from '@playwright/test';

const editor = (page: Page) => page.getByRole('textbox', {name: '消息输入'});
const listbox = (page: Page) => page.getByRole('listbox', {name: '命令补全'});
const names = (page: Page) => page.locator('.completion-item code').allInnerTexts();

async function openComposer(page: Page) {
  await page.goto('/?demo=1');
  await page.getByRole('button', {name: '展开会话侧栏'}).click();
  await expect(editor(page)).toBeVisible();
}

test('typing a leading slash opens a list of commands this host can actually run', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openComposer(page);

  // A slash inside a word is ordinary text, not a trigger. A slash after a space is a new token.
  await editor(page).fill('2026/10');
  await expect(listbox(page)).toHaveCount(0);
  await editor(page).fill('https://example.com');
  await expect(listbox(page)).toHaveCount(0);
  await editor(page).fill('/设置 其余');
  await expect(listbox(page)).toHaveCount(0);

  await editor(page).fill('/');
  await expect(listbox(page)).toBeVisible();
  expect(await names(page)).toEqual(['/新建', '/设置', '/附件']);
  // Cancelling is only offered when there is something to cancel.
  await expect(page.getByRole('option', {name: /取消本会话任务/})).toHaveCount(0);

  await editor(page).fill('/新');
  expect(await names(page)).toEqual(['/新建']);
  await editor(page).fill('/s');
  expect(await names(page)).toEqual(['/设置']);
  await editor(page).fill('/zzz');
  await expect(listbox(page)).toHaveCount(0);

  // Escape closes the list and keeps the draft for the user to finish by hand.
  await editor(page).fill('/设置');
  await expect(listbox(page)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(listbox(page)).toHaveCount(0);
  await expect(editor(page)).toContainText('/设置');
  expect(errors).toEqual([]);
});

test('accepting with Enter runs the command and never sends the token as a message', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openComposer(page);
  const sessionCount = await page.locator('.session-select').count();

  await editor(page).fill('/新建');
  await expect(listbox(page)).toBeVisible();
  await page.keyboard.press('Enter');

  // The command ran (a new session exists) and the token never became a user message.
  await expect.poll(() => page.locator('.session-select').count()).toBe(sessionCount + 1);
  await expect(page.locator('.message.user')).toHaveCount(0);
  await expect(editor(page)).toHaveText('');
  await expect(listbox(page)).toHaveCount(0);

  // Arrow keys move the highlight, and the highlighted row is the one Enter runs.
  await editor(page).fill('/');
  await expect(listbox(page)).toBeVisible();
  expect(await page.locator('.completion-item.selected code').innerText()).toBe('/新建');
  await page.keyboard.press('ArrowDown');
  expect(await page.locator('.completion-item.selected code').innerText()).toBe('/设置');
  await page.keyboard.press('ArrowUp');
  expect(await page.locator('.completion-item.selected code').innerText()).toBe('/新建');
  expect(errors).toEqual([]);
});

test('cancelling is offered while this session has a running task', async ({page}) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  await openComposer(page);
  await editor(page).fill('隔离测试');
  await page.getByRole('button', {name: '发送消息'}).click();
  await expect(page.locator('.message.user')).toHaveCount(1);

  await editor(page).fill('/取消');
  await expect(page.getByRole('option', {name: /取消本会话任务/})).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(page.locator('.message.assistant .badge')).toContainText('已取消');
  await expect(editor(page)).toHaveText('');
  expect(errors).toEqual([]);
});
