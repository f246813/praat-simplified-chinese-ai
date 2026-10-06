import {expect,test,type Page} from '@playwright/test';

const options=(page:Page)=>page.getByRole('button',{name:'会话历史选项',exact:true});
async function open(page:Page){await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();await options(page).click();}

test('ellipsis opens two real submenus; sorting retains existing creation/name choices',async({page})=>{
  await open(page);
  await expect(page.getByRole('button',{name:'会话排序',exact:true})).toHaveCount(0);
  const root=page.getByRole('menu',{name:'会话历史选项',exact:true});await expect(root).toBeVisible();
  await expect(root.getByRole('menuitem')).toHaveCount(2);
  await expect(root.getByRole('menuitem',{name:'整理侧边栏',exact:true})).toHaveAttribute('aria-haspopup','menu');
  const sort=root.getByRole('menuitem',{name:'聊天排序方式',exact:true});await sort.hover();
  const child=page.getByRole('menu',{name:'聊天排序方式',exact:true});await expect(child).toBeVisible();
  await expect(child.getByRole('menuitemradio',{name:'最近创建',exact:true})).toBeVisible();
  await expect(child.getByRole('menuitemradio',{name:'最早创建',exact:true})).toBeVisible();
  await expect(child.getByRole('menuitemradio',{name:'按名称',exact:true})).toBeVisible();
  await expect(child.getByRole('menuitemradio',{name:'最近更新',exact:true})).toHaveCount(1);
  await expect(child.getByRole('menuitemradio')).toHaveCount(4);
  await child.getByRole('menuitemradio',{name:'按名称',exact:true}).click();await expect(root).toHaveCount(0);
  await options(page).click();await page.getByRole('menuitem',{name:'聊天排序方式',exact:true}).hover();
  await expect(page.getByRole('menuitemradio',{name:'按名称',exact:true})).toHaveAttribute('aria-checked','true');
});

test('submenu opens by keyboard, closes to parent, escapes and restores trigger focus',async({page})=>{
  await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();
  await options(page).focus();await page.keyboard.press('Enter');await page.keyboard.press('End');await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('menu',{name:'聊天排序方式',exact:true})).toBeVisible();
  await page.keyboard.press('ArrowLeft');await expect(page.getByRole('menu',{name:'聊天排序方式',exact:true})).toHaveCount(0);
  await expect(page.getByRole('menuitem',{name:'聊天排序方式',exact:true})).toBeFocused();
  await page.keyboard.press('Escape');await expect(page.getByRole('menu')).toHaveCount(0);await expect(options(page)).toBeFocused();
  await options(page).click();await page.locator('.chat-header h1').click();await expect(page.getByRole('menu')).toHaveCount(0);
});

test('sidebar organization switches real project/connection groups without moving section history',async({page})=>{
  await page.goto('/?demo=1');await page.getByRole('button',{name:'展开会话侧栏'}).click();
  await page.getByRole('button',{name:'新建分区',exact:true}).click();await page.getByLabel('分区名称',{exact:true}).fill('研究');await page.getByRole('button',{name:'保存分区',exact:true}).click();
  await page.getByRole('button',{name:'会话操作 新的分析',exact:true}).click();await page.getByRole('menuitem',{name:'分区',exact:true}).click();await page.getByRole('menuitem',{name:'研究',exact:true}).click();
  const grouped=page.locator('[data-history-section]').filter({has:page.getByRole('button',{name:'折叠分区 研究',exact:true})});await expect(grouped.locator('[data-session-id="demo-1"]')).toBeVisible();
  await options(page).click();await page.getByRole('menuitem',{name:'整理侧边栏',exact:true}).hover();
  await page.getByRole('menuitemradio',{name:'在一个列表中',exact:true}).click();
  await expect(page.locator('.sidebar-origin-group')).toHaveCount(0);await expect(page.locator('.session-row')).toHaveCount(4);
  await expect(grouped.locator('[data-session-id="demo-1"]')).toBeVisible();
  await options(page).click();await page.getByRole('menuitem',{name:'整理侧边栏',exact:true}).hover();await page.getByRole('menuitemradio',{name:'按远程连接',exact:true}).click();
  await expect(page.locator('.sidebar-origin-header')).toContainText(['本地']);
  await options(page).click();await page.getByRole('menuitem',{name:'整理侧边栏',exact:true}).hover();await page.getByRole('menuitemradio',{name:'按项目',exact:true}).click();
  await expect(grouped.locator('[data-session-id="demo-1"]')).toBeVisible();await expect(page.locator('.session-row')).toHaveCount(4);
});

test('root and submenu stay inside a narrow desktop viewport',async({page})=>{
  await page.setViewportSize({width:800,height:600});await open(page);await page.getByRole('menuitem',{name:'聊天排序方式',exact:true}).hover();
  for(const menu of await page.getByRole('menu').all()){
    const rect=(await menu.boundingBox())!;expect(rect.x).toBeGreaterThanOrEqual(7);expect(rect.y).toBeGreaterThanOrEqual(7);expect(rect.x+rect.width).toBeLessThanOrEqual(793);expect(rect.y+rect.height).toBeLessThanOrEqual(593);
  }
});
