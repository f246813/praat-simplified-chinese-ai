import {expect, test} from '@playwright/test';

test('opening starts a blank session and keeps historical conversations accessible', async ({page}) => {
  await page.goto('/?demo=1');
  await expect(page.locator('.chat-header h1')).toHaveText('新会话');
  await expect(page.getByRole('textbox',{name:'消息输入'})).toBeEmpty();
  await expect(page.locator('.transcript .message')).toHaveCount(0);
  await page.getByRole('button',{name:'展开会话侧栏'}).click();
  await expect(page.locator('[data-session-id="demo-new-1"] .session-select')).toHaveAttribute('aria-current','page');
  await page.locator('[data-session-id="demo-history"] .session-select').click();
  await expect(page.locator('.chat-header h1')).toHaveText('长历史与渲染夹具');
  await expect(page.locator('.transcript .message').first()).toBeVisible();
  await page.getByRole('button',{name:'打开设置'}).click();
  await page.getByRole('button',{name:'刷新宿主记录'}).click();
  await expect(page.getByText('会话与任务状态已刷新',{exact:true})).toBeVisible();
  await expect(page.getByText(/4 个会话 ·/)).toBeVisible();
  await page.getByRole('button',{name:'返回聊天'}).click();
  await expect(page.locator('.chat-header h1')).toHaveText('长历史与渲染夹具');
  await page.reload();
  await expect(page.locator('.chat-header h1')).toHaveText('新会话');
  await expect(page.getByRole('textbox',{name:'消息输入'})).toBeEmpty();
  await expect(page.locator('.transcript .message')).toHaveCount(0);
});
