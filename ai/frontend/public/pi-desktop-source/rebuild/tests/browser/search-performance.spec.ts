import {expect,test} from '@playwright/test';

test('navigating search hits reuses matches instead of rescanning the transcript',async({page})=>{
  await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();
  await page.locator('[data-session-id="demo-history"] .session-select').click();
  await expect(page.locator('[data-message-id="diagram-fixture"]')).toBeAttached();
  await page.keyboard.press('Control+k');
  await page.getByRole('searchbox',{name:'在会话中查找'}).fill('夹具');
  await expect(page.locator('.chat-search-count')).toHaveText(/^1\/\d+$/);
  await page.evaluate(()=>{
    const original=document.createTreeWalker.bind(document);
    (window as any).searchScans=0;
    document.createTreeWalker=((...args:Parameters<typeof original>)=>{(window as any).searchScans++;return original(...args);}) as typeof document.createTreeWalker;
  });
  for(let i=0;i<5;i++)await page.getByRole('button',{name:'下一个匹配',exact:true}).click();
  await expect(page.locator('.chat-search-count')).toHaveText(/^6\/\d+$/);
  expect(await page.evaluate(()=>(window as any).searchScans)).toBe(0);
});
